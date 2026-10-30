"""
BCDR_system - Barangay Clearance and Document Request System

Ang file na ito ang "utak" ng buong system (backend). Dito natin inilalagay ang:
  1. Configuration (settings ng app)
  2. Database (SQLite / Supabase PostgreSQL) at ang mga table
  3. Helper functions at decorators (login check, role check)
  4. Routes (mga URL / pahina ng system)
"""

import io
import os
import re
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import (
    Flask, abort, flash, g, redirect, render_template,
    request, send_file, send_from_directory, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# Imports para sa PDF Generation
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
except ImportError:
    pass


# =============================================================================
# 1. CONFIGURATION
# =============================================================================

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")

DATABASE_URL = os.environ.get("DATABASE_URL")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
TEMPLATE_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, "templates")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}
MAX_FILES_PER_REQUEST = 5

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("BCDR_SECRET_KEY", "dev-only-change-me")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB max upload

SEX_OPTIONS = ("Male", "Female")
CIVIL_STATUS_OPTIONS = ("Single", "Married", "Widowed", "Separated")

REQUEST_STATUSES = (
    "Submitted", "Under Review", "For Compliance", "Approved",
    "For Payment", "Ready for Release", "Released", "Rejected", "Cancelled",
)
STAFF_SETTABLE_STATUSES = (
    "Under Review", "For Compliance", "Approved", 
    "For Payment", "Ready for Release", "Released", "Rejected"
)
OPEN_STATUSES = ("Submitted", "Under Review", "For Compliance")
FINAL_STATUSES = ("Rejected", "Cancelled", "Released")
REMARKS_REQUIRED_STATUSES = ("Rejected", "For Compliance")

STAFF_ROLES = ("staff", "admin")


# =============================================================================
# 2. DATABASE
# =============================================================================

def get_db():
    if "db" not in g:
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            conn.autocommit = True
            g.db = conn
        else:
            conn = sqlite3.connect(DATABASE)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(50) NOT NULL CHECK (role IN ('resident', 'staff', 'admin')),
    status        VARCHAR(50) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'active', 'rejected', 'disabled')),
    created_at    VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS residents (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    first_name     VARCHAR(255) NOT NULL,
    middle_name    VARCHAR(255),
    last_name      VARCHAR(255) NOT NULL,
    birthdate      VARCHAR(100) NOT NULL,
    sex            VARCHAR(50) NOT NULL,
    civil_status   VARCHAR(50) NOT NULL,
    purok          VARCHAR(255) NOT NULL,
    address        TEXT NOT NULL,
    contact_number VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS document_types (
    id                SERIAL PRIMARY KEY,
    name              VARCHAR(255) NOT NULL UNIQUE,
    description       TEXT,
    requirements      TEXT,
    fee               REAL NOT NULL DEFAULT 0,
    processing_days   INTEGER NOT NULL DEFAULT 1,
    is_active         INTEGER NOT NULL DEFAULT 1,
    template_filename VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS requests (
    id               SERIAL PRIMARY KEY,
    resident_id      INTEGER NOT NULL REFERENCES residents(id),
    document_type_id INTEGER NOT NULL REFERENCES document_types(id),
    purpose          TEXT NOT NULL,
    status           VARCHAR(50) NOT NULL DEFAULT 'Submitted',
    remarks          TEXT,
    reviewed_by      INTEGER REFERENCES users(id),
    created_at       VARCHAR(100) NOT NULL,
    updated_at       VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS request_attachments (
    id            SERIAL PRIMARY KEY,
    request_id    INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    original_name VARCHAR(255) NOT NULL,
    stored_name   VARCHAR(255) NOT NULL,
    uploaded_at   VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_id INTEGER REFERENCES requests(id) ON DELETE CASCADE,
    message    TEXT NOT NULL,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS barangay_settings (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    barangay_name         VARCHAR(255) NOT NULL,
    municipality          VARCHAR(255) NOT NULL,
    province              VARCHAR(255) NOT NULL,
    address               TEXT,
    punong_barangay       VARCHAR(255),
    secretary             VARCHAR(255),
    control_number_prefix VARCHAR(50) NOT NULL DEFAULT 'BRGY'
);
"""

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('resident', 'staff', 'admin')),
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'active', 'rejected', 'disabled')),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS residents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    first_name     TEXT NOT NULL,
    middle_name    TEXT,
    last_name      TEXT NOT NULL,
    birthdate      TEXT NOT NULL,
    sex            TEXT NOT NULL,
    civil_status   TEXT NOT NULL,
    purok          TEXT NOT NULL,
    address        TEXT NOT NULL,
    contact_number TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_types (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,
    description       TEXT,
    requirements      TEXT,
    fee               REAL NOT NULL DEFAULT 0,
    processing_days   INTEGER NOT NULL DEFAULT 1,
    is_active         INTEGER NOT NULL DEFAULT 1,
    template_filename TEXT
);

CREATE TABLE IF NOT EXISTS requests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id      INTEGER NOT NULL REFERENCES residents(id),
    document_type_id INTEGER NOT NULL REFERENCES document_types(id),
    purpose          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'Submitted',
    remarks          TEXT,
    reviewed_by      INTEGER REFERENCES users(id),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS request_attachments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id    INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    stored_name   TEXT NOT NULL,
    uploaded_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_id INTEGER REFERENCES requests(id) ON DELETE CASCADE,
    message    TEXT NOT NULL,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS barangay_settings (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    barangay_name         TEXT NOT NULL,
    municipality          TEXT NOT NULL,
    province              TEXT NOT NULL,
    address               TEXT,
    punong_barangay       TEXT,
    secretary             TEXT,
    control_number_prefix TEXT NOT NULL DEFAULT 'BRGY'
);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(TEMPLATE_UPLOAD_FOLDER, exist_ok=True)
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            conn.autocommit = True
            cursor = conn.cursor()
            cursor.execute(SCHEMA_PG)
            
            cursor.execute("SELECT COUNT(*) AS cnt FROM document_types")
            row = cursor.fetchone()
            count = list(row.values())[0] if row else 0
            if count == 0:
                docs = [
                    ("Barangay Clearance", "General-purpose barangay clearance.", "Valid ID; Proof of residency", 50, 1),
                    ("Certificate of Residency", "Certifies that the person lives in the barangay.", "Valid ID", 30, 1),
                    ("Certificate of Indigency", "Certifies that the person belongs to an indigent family.", "Valid ID", 0, 2),
                    ("Business Clearance", "Clearance for operating a business in the barangay.", "Valid ID; Business permit or DTI registration", 200, 3),
                ]
                for d in docs:
                    cursor.execute(
                        "INSERT INTO document_types (name, description, requirements, fee, processing_days) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (name) DO NOTHING",
                        d
                    )
            
            cursor.execute("SELECT COUNT(*) AS cnt FROM barangay_settings")
            row = cursor.fetchone()
            count = list(row.values())[0] if row else 0
            if count == 0:
                cursor.execute(
                    "INSERT INTO barangay_settings (id, barangay_name, municipality, province, address, punong_barangay, secretary) VALUES (1, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                    ("Barangay Lanao", "Kidapawan City", "Cotabato", "Barangay Hall Address", "Punong Barangay Name", "Barangay Secretary Name")
                )

            cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'")
            row = cursor.fetchone()
            count = list(row.values())[0] if row else 0
            if count == 0:
                admin_password = os.environ.get("BCDR_ADMIN_PASSWORD", "ChangeMe123!")
                cursor.execute(
                    "INSERT INTO users (email, password_hash, role, status, created_at) VALUES (%s, %s, 'admin', 'active', %s) ON CONFLICT (email) DO NOTHING",
                    ("admin@barangay.local", generate_password_hash(admin_password), now())
                )
            conn.close()
        except Exception as e:
            print(f"Database initialization warning: {e}")
    else:
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA_SQLITE)

        if db.execute("SELECT COUNT(*) FROM document_types").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO document_types (name, description, requirements, fee, processing_days) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    ("Barangay Clearance", "General-purpose barangay clearance.", "Valid ID; Proof of residency", 50, 1),
                    ("Certificate of Residency", "Certifies that the person lives in the barangay.", "Valid ID", 30, 1),
                    ("Certificate of Indigency", "Certifies that the person belongs to an indigent family.", "Valid ID", 0, 2),
                    ("Business Clearance", "Clearance for operating a business in the barangay.", "Valid ID; Business permit or DTI registration", 200, 3),
                ],
            )

        if db.execute("SELECT COUNT(*) FROM barangay_settings").fetchone()[0] == 0:
            db.execute(
                "INSERT INTO barangay_settings (id, barangay_name, municipality, province, "
                "address, punong_barangay, secretary) VALUES (1, ?, ?, ?, ?, ?, ?)",
                ("Barangay Lanao", "Kidapawan City", "Cotabato", "Barangay Hall address", "Punong Barangay Name", "Barangay Secretary Name"),
            )

        if db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] == 0:
            admin_password = os.environ.get("BCDR_ADMIN_PASSWORD", "ChangeMe123!")
            db.execute(
                "INSERT INTO users (email, password_hash, role, status, created_at) VALUES (?, ?, 'admin', 'active', ?)",
                ("admin@barangay.local", generate_password_hash(admin_password), now()),
            )

        db.commit()
        db.close()


# =============================================================================
# 3. HELPERS & DECORATORS
# =============================================================================

@app.before_request
def load_logged_in_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        try:
            db = get_db()
            cursor = db.cursor() if DATABASE_URL else db
            cursor.execute(
                "SELECT id, email, role, status FROM users WHERE id = %s" if DATABASE_URL else "SELECT id, email, role, status FROM users WHERE id = ?",
                (user_id,)
            )
            user = cursor.fetchone()
            if user is not None and user["status"] == "active":
                g.user = user
            else:
                session.clear()
        except Exception:
            session.clear()


@app.context_processor
def inject_template_globals():
    db = get_db()
    barangay = None
    try:
        if DATABASE_URL:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM barangay_settings WHERE id = 1")
            barangay = cursor.fetchone()
        else:
            barangay = db.execute("SELECT * FROM barangay_settings WHERE id = 1").fetchone()
    except Exception:
        barangay = None
    
    unread_notifications_count = 0
    if g.user:
        try:
            if DATABASE_URL:
                cursor = db.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = 0",
                    (g.user["id"],)
                )
                row = cursor.fetchone()
                if row:
                    unread_notifications_count = list(row.values())[0]
            else:
                row = db.execute(
                    "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
                    (g.user["id"],)
                ).fetchone()
                unread_notifications_count = row[0] if row else 0
        except Exception:
            unread_notifications_count = 0

    return {
        "current_user": g.get("user"),
        "barangay": barangay,
        "unread_notifications_count": unread_notifications_count,
        "SEX_OPTIONS": SEX_OPTIONS,
        "CIVIL_STATUS_OPTIONS": CIVIL_STATUS_OPTIONS,
        "REQUEST_STATUSES": REQUEST_STATUSES,
        "STAFF_SETTABLE_STATUSES": STAFF_SETTABLE_STATUSES,
    }


def home_for(user):
    if user["role"] in STAFF_ROLES:
        return url_for("staff_dashboard")
    return url_for("resident_dashboard")


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def login_required(view):
    return role_required("resident", "staff", "admin")(view)


def get_current_resident():
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    cursor.execute(
        "SELECT * FROM residents WHERE user_id = %s" if DATABASE_URL else "SELECT * FROM residents WHERE user_id = ?",
        (g.user["id"],)
    )
    resident = cursor.fetchone()
    if resident is None:
        abort(404)
    return resident


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_attachments(request_id, files):
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    for file in files:
        extension = file.filename.rsplit(".", 1)[1].lower()
        stored_name = f"{uuid.uuid4().hex}.{extension}"
        file.save(os.path.join(UPLOAD_FOLDER, stored_name))
        if DATABASE_URL:
            cursor.execute(
                "INSERT INTO request_attachments (request_id, original_name, stored_name, uploaded_at) VALUES (%s, %s, %s, %s)",
                (request_id, secure_filename(file.filename) or "file", stored_name, now()),
            )
        else:
            cursor.execute(
                "INSERT INTO request_attachments (request_id, original_name, stored_name, uploaded_at) VALUES (?, ?, ?, ?)",
                (request_id, secure_filename(file.filename) or "file", stored_name, now()),
            )
    if not DATABASE_URL:
        db.commit()


def notify_staff_and_admins(request_id, message):
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    cursor.execute("SELECT id FROM users WHERE role IN ('staff', 'admin') AND status = 'active'")
    staff_users = cursor.fetchall()
    for staff in staff_users:
        if DATABASE_URL:
            cursor.execute(
                "INSERT INTO notifications (user_id, request_id, message, is_read, created_at) VALUES (%s, %s, %s, 0, %s)",
                (staff["id"], request_id, message, now())
            )
        else:
            cursor.execute(
                "INSERT INTO notifications (user_id, request_id, message, is_read, created_at) VALUES (?, ?, ?, 0, ?)",
                (staff["id"], request_id, message, now())
            )
    if not DATABASE_URL:
        db.commit()


REQUEST_DETAIL_SQL = """
    SELECT r.*, dt.name AS document_name, dt.fee, dt.processing_days, dt.requirements, dt.template_filename,
           res.first_name, res.middle_name, res.last_name, res.purok, res.address,
           res.contact_number, res.birthdate, u.email, u.id AS user_id
    FROM requests r
    JOIN document_types dt ON dt.id = r.document_type_id
    JOIN residents res ON res.id = r.resident_id
    JOIN users u ON u.id = res.user_id
"""


# =============================================================================
# 4. PUBLIC ROUTES
# =============================================================================

@app.route("/")
def index():
    if g.user:
        return redirect(home_for(g.user))
    return render_template("public/index.html")


REGISTER_FIELDS = (
    "email", "first_name", "middle_name", "last_name", "birthdate", "sex",
    "civil_status", "purok", "address", "contact_number",
)


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(home_for(g.user))

    if request.method == "POST":
        data = {field: request.form.get(field, "").strip() for field in REGISTER_FIELDS}
        data["email"] = data["email"].lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        db = get_db()
        cursor = db.cursor() if DATABASE_URL else db
        try:
            if DATABASE_URL:
                cursor.execute(
                    "INSERT INTO users (email, password_hash, role, status, created_at) VALUES (%s, %s, 'resident', 'pending', %s) RETURNING id",
                    (data["email"], generate_password_hash(password), now()),
                )
                user_id = cursor.fetchone()["id"]
                cursor.execute(
                    "INSERT INTO residents (user_id, first_name, middle_name, last_name, birthdate, sex, civil_status, purok, address, contact_number) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (user_id, data["first_name"], data["middle_name"], data["last_name"], data["birthdate"], data["sex"], data["civil_status"], data["purok"], data["address"], data["contact_number"]),
                )
            else:
                cursor.execute(
                    "INSERT INTO users (email, password_hash, role, status, created_at) VALUES (?, ?, 'resident', 'pending', ?)",
                    (data["email"], generate_password_hash(password), now()),
                )
                cursor.execute(
                    "INSERT INTO residents (user_id, first_name, middle_name, last_name, birthdate, sex, civil_status, purok, address, contact_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (cursor.lastrowid, data["first_name"], data["middle_name"], data["last_name"], data["birthdate"], data["sex"], data["civil_status"], data["purok"], data["address"], data["contact_number"]),
                )
                db.commit()
        except Exception:
            if not DATABASE_URL:
                db.rollback()
            flash("An account with that email already exists.", "danger")
            return render_template("public/register.html", form=data)

        flash("Registration submitted. Please wait for the barangay staff to approve your account.", "success")
        return redirect(url_for("login"))

    return render_template("public/register.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_for(g.user))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        cursor = db.cursor() if DATABASE_URL else db
        cursor.execute(
            "SELECT * FROM users WHERE email = %s" if DATABASE_URL else "SELECT * FROM users WHERE email = ?",
            (email,)
        )
        user = cursor.fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "danger")
            return render_template("public/login.html", email=email)

        if user["status"] == "pending":
            flash("Your account is still waiting for approval by the barangay staff.", "warning")
            return render_template("public/login.html", email=email)
        if user["status"] != "active":
            flash("Your account is not active. Please contact the barangay hall.", "danger")
            return render_template("public/login.html", email=email)

        session.clear()
        session["user_id"] = user["id"]
        return redirect(home_for(user))

    return render_template("public/login.html", email="")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# =============================================================================
# 5. RESIDENT ROUTES
# =============================================================================

@app.route("/resident/dashboard")
@role_required("resident")
def resident_dashboard():
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    resident = get_current_resident()

    cursor.execute(
        "SELECT status, COUNT(*) AS total FROM requests WHERE resident_id = %s GROUP BY status" if DATABASE_URL else "SELECT status, COUNT(*) AS total FROM requests WHERE resident_id = ? GROUP BY status",
        (resident["id"],),
    )
    rows = cursor.fetchall()
    status_counts = {row["status"]: row["total"] for row in rows}

    cursor.execute(
        (REQUEST_DETAIL_SQL + " WHERE r.resident_id = %s ORDER BY r.created_at DESC, r.id DESC LIMIT 5") if DATABASE_URL else (REQUEST_DETAIL_SQL + " WHERE r.resident_id = ? ORDER BY r.created_at DESC, r.id DESC LIMIT 5"),
        (resident["id"],),
    )
    recent_requests = cursor.fetchall()

    return render_template(
        "resident/dashboard.html",
        resident=resident, status_counts=status_counts, recent_requests=recent_requests,
    )


@app.route("/resident/new-request", methods=["GET", "POST"])
@role_required("resident")
def new_request():
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    resident = get_current_resident()
    
    cursor.execute("SELECT * FROM document_types WHERE is_active = 1 ORDER BY name")
    document_types = cursor.fetchall()

    if request.method == "POST":
        document_type_id = request.form.get("document_type_id", type=int)
        purpose = request.form.get("purpose", "").strip()
        files = [f for f in request.files.getlist("attachments") if f and f.filename]

        errors = []
        document_type = None
        if document_type_id:
            cursor.execute(
                "SELECT * FROM document_types WHERE id = %s AND is_active = 1" if DATABASE_URL else "SELECT * FROM document_types WHERE id = ? AND is_active = 1",
                (document_type_id,)
            )
            document_type = cursor.fetchone()
        if document_type is None:
            errors.append("Please choose a valid document type.")
        if len(purpose) < 5:
            errors.append("Please state the purpose of your request.")

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "resident/new-request.html", document_types=document_types,
                form={"document_type_id": document_type_id, "purpose": purpose},
            )

        timestamp = now()
        if DATABASE_URL:
            cursor.execute(
                "INSERT INTO requests (resident_id, document_type_id, purpose, status, created_at, updated_at) VALUES (%s, %s, %s, 'Submitted', %s, %s) RETURNING id",
                (resident["id"], document_type["id"], purpose, timestamp, timestamp),
            )
            request_id = cursor.fetchone()["id"]
        else:
            cursor.execute(
                "INSERT INTO requests (resident_id, document_type_id, purpose, status, created_at, updated_at) VALUES (?, ?, ?, 'Submitted', ?, ?)",
                (resident["id"], document_type["id"], purpose, timestamp, timestamp),
            )
            request_id = cursor.lastrowid
            
        save_attachments(request_id, files)
        flash("Your request has been submitted.", "success")
        return redirect(url_for("request_details", request_id=request_id))

    return render_template("resident/new-request.html", document_types=document_types, form={})


@app.route("/resident/my-requests")
@role_required("resident")
def my_requests():
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    resident = get_current_resident()
    
    cursor.execute(
        (REQUEST_DETAIL_SQL + " WHERE r.resident_id = %s ORDER BY r.created_at DESC, r.id DESC") if DATABASE_URL else (REQUEST_DETAIL_SQL + " WHERE r.resident_id = ? ORDER BY r.created_at DESC, r.id DESC"),
        (resident["id"],),
    )
    requests_list = cursor.fetchall()
    return render_template("resident/my-requests.html", requests=requests_list)


@app.route("/resident/requests/<int:request_id>")
@role_required("resident")
def request_details(request_id):
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    resident = get_current_resident()
    
    cursor.execute(
        (REQUEST_DETAIL_SQL + " WHERE r.id = %s AND r.resident_id = %s") if DATABASE_URL else (REQUEST_DETAIL_SQL + " WHERE r.id = ? AND r.resident_id = ?"),
        (request_id, resident["id"])
    )
    req = cursor.fetchone()
    if req is None:
        abort(404)
        
    cursor.execute(
        "SELECT * FROM request_attachments WHERE request_id = %s" if DATABASE_URL else "SELECT * FROM request_attachments WHERE request_id = ?",
        (request_id,)
    )
    attachments = cursor.fetchall()
    return render_template("resident/request-details.html", req=req, attachments=attachments)


@app.route("/requests/<int:request_id>/download-pdf")
@role_required("resident", "staff", "admin")
def download_document_pdf(request_id):
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    
    if g.user["role"] in STAFF_ROLES:
        cursor.execute(
            (REQUEST_DETAIL_SQL + " WHERE r.id = %s") if DATABASE_URL else (REQUEST_DETAIL_SQL + " WHERE r.id = ?"),
            (request_id,)
        )
        req = cursor.fetchone()
    else:
        resident = get_current_resident()
        cursor.execute(
            (REQUEST_DETAIL_SQL + " WHERE r.id = %s AND r.resident_id = %s") if DATABASE_URL else (REQUEST_DETAIL_SQL + " WHERE r.id = ? AND r.resident_id = ?"),
            (request_id, resident["id"])
        )
        req = cursor.fetchone()

    if not req or req["status"] != "Released":
        flash("Document is not available for download yet.", "danger")
        return redirect(url_for("my_requests"))

    cursor.execute("SELECT * FROM barangay_settings WHERE id = 1")
    barangay = cursor.fetchone()

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica-Bold", 14)
    p.drawCentredString(width / 2, height - 60, f"REPUBLIC OF THE PHILIPPINES")
    p.setFont("Helvetica-Bold", 12)
    p.drawCentredString(width / 2, height - 76, f"PROVINCE OF {barangay['province'].upper()}")
    p.drawCentredString(width / 2, height - 92, f"MUNICIPALITY OF {barangay['municipality'].upper()}")
    p.setFont("Helvetica-Bold", 14)
    p.drawCentredString(width / 2, height - 108, f"BARANGAY {barangay['barangay_name'].upper()}")
    
    p.setLineWidth(1)
    p.line(50, height - 120, width - 50, height - 120)

    p.setFont("Helvetica-Bold", 18)
    p.drawCentredString(width / 2, height - 170, str(req['document_name']).upper())

    full_name = f"{req['first_name']} {req['middle_name'] or ''} {req['last_name']}".strip()
    address = f"{req['purok']}, {req['address']}"

    text_object = p.beginText(60, height - 230)
    text_object.setFont("Helvetica-Bold", 11)
    text_object.textLine("TO WHOM IT MAY CONCERN:")
    text_object.textLine("")
    text_object.setFont("Helvetica", 11)
    text_object.setLeading(20)
    
    text_object.textLine(f"This is to certify that {full_name}, of legal age, residing at")
    text_object.textLine(f"{address}, is a bona fide resident of this Barangay.")
    text_object.textLine("")
    text_object.textLine(f"This certification/clearance is issued for the purpose of: {req['purpose']}.")
    text_object.textLine("")
    text_object.textLine("Given this day upon request ofamin the interested party.")
    
    p.drawText(text_object)

    p.setFont("Helvetica-Oblique", 9)
    p.drawString(60, height - 420, f"Control Ref No: {barangay['control_number_prefix']}-{req['id']:05d}")
    p.drawString(60, height - 435, f"Date Issued: {req['updated_at']}")

    p.setFont("Helvetica-Bold", 11)
    p.drawString(width - 240, height - 500, str(barangay['punong_barangay']).upper())
    p.line(width - 240, height - 505, width - 60, height - 505)
    p.setFont("Helvetica", 9)
    p.drawString(width - 240, height - 518, "Punong Barangay")

    p.showPage()
    p.save()

    buffer.seek(0)
    filename = f"{req['document_name'].replace(' ', '_')}_{req['id']}.pdf"
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )


# =============================================================================
# 6. STAFF ROUTES & DOCUMENT TYPES WITH TEMPLATE UPLOAD
# =============================================================================

@app.route("/staff/dashboard")
@role_required(*STAFF_ROLES)
def staff_dashboard():
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    cursor.execute("SELECT status, COUNT(*) AS total FROM requests GROUP BY status")
    rows = cursor.fetchall()
    status_counts = {row["status"]: row["total"] for row in rows}
    return render_template("staff/dashboard.html", status_counts=status_counts)


@app.route("/staff/request-queue")
@role_required(*STAFF_ROLES)
def request_queue():
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    cursor.execute(REQUEST_DETAIL_SQL + " ORDER BY r.created_at ASC")
    requests_list = cursor.fetchall()
    return render_template("staff/request-queue.html", requests=requests_list)


@app.route("/staff/requests/<int:request_id>", methods=["GET", "POST"])
@role_required(*STAFF_ROLES)
def review_request(request_id):
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    
    cursor.execute(
        (REQUEST_DETAIL_SQL + " WHERE r.id = %s") if DATABASE_URL else (REQUEST_DETAIL_SQL + " WHERE r.id = ?"),
        (request_id,)
    )
    req = cursor.fetchone()
    if req is None:
        abort(404)

    if request.method == "POST":
        new_status = request.form.get("status", "").strip()
        remarks = request.form.get("remarks", "").strip()

        cursor.execute(
            "UPDATE requests SET status = %s, remarks = %s, reviewed_by = %s, updated_at = %s WHERE id = %s" if DATABASE_URL else "UPDATE requests SET status = ?, remarks = ?, reviewed_by = ?, updated_at = ? WHERE id = ?",
            (new_status, remarks, g.user["id"], now(), request_id),
        )
        if not DATABASE_URL:
            db.commit()
        flash(f"Request status updated to '{new_status}'.", "success")
        return redirect(url_for("request_queue"))

    return render_template("staff/review-request.html", req=req, attachments=[])


@app.route("/staff/document_types")
@role_required(*STAFF_ROLES)
def document_types():
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    cursor.execute("SELECT * FROM document_types ORDER BY name")
    rows = cursor.fetchall()
    return render_template("staff/document_types.html", document_types=rows)


@app.route("/staff/document_types/save", methods=["POST"])
@role_required(*STAFF_ROLES)
def save_document_type():
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    doc_id = request.form.get("doc_id", "").strip()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    requirements = request.form.get("requirements", "").strip()
    
    try:
        fee = float(request.form.get("fee", 0))
    except ValueError:
        fee = 0.0

    try:
        processing_days = int(request.form.get("processing_days", 1))
    except ValueError:
        processing_days = 1

    if not name:
        flash("Document name is required.", "danger")
        return redirect(url_for("document_types"))

    template_filename = None
    file = request.files.get("template_file")
    if file and file.filename:
        if allowed_file(file.filename):
            ext = file.filename.rsplit(".", 1)[1].lower()
            template_filename = f"template_{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(TEMPLATE_UPLOAD_FOLDER, template_filename))

    try:
        if doc_id:
            if template_filename:
                cursor.execute(
                    "UPDATE document_types SET name = %s, description = %s, requirements = %s, fee = %s, processing_days = %s, template_filename = %s WHERE id = %s" if DATABASE_URL else "UPDATE document_types SET name = ?, description = ?, requirements = ?, fee = ?, processing_days = ?, template_filename = ? WHERE id = ?",
                    (name, description, requirements, fee, processing_days, template_filename, doc_id),
                )
            else:
                cursor.execute(
                    "UPDATE document_types SET name = %s, description = %s, requirements = %s, fee = %s, processing_days = %s WHERE id = %s" if DATABASE_URL else "UPDATE document_types SET name = ?, description = ?, requirements = ?, fee = ?, processing_days = ?, id = ?",
                    (name, description, requirements, fee, processing_days, doc_id),
                )
            flash("Document type updated successfully.", "success")
        else:
            cursor.execute(
                "INSERT INTO document_types (name, description, requirements, fee, processing_days, is_active, template_filename) VALUES (%s, %s, %s, %s, %s, 1, %s)" if DATABASE_URL else "INSERT INTO document_types (name, description, requirements, fee, processing_days, is_active, template_filename) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (name, description, requirements, fee, processing_days, template_filename),
            )
            flash("New document type added successfully.", "success")
        if not DATABASE_URL:
            db.commit()
    except Exception as e:
        if not DATABASE_URL:
            db.rollback()
        flash(f"Error saving document type: {e}", "danger")

    return redirect(url_for("document_types"))

@app.route("/staff/records/released")
@role_required(*STAFF_ROLES)
def released_records():
    db = get_db()
    cursor = db.cursor() if DATABASE_URL else db
    cursor.execute(
        (REQUEST_DETAIL_SQL + " WHERE r.status = 'Released' ORDER BY r.updated_at DESC, r.id DESC")
    )
    released_list = cursor.fetchall()
    return render_template("staff/released_records.html", requests=released_list)

# =============================================================================
# 7. APP START
# =============================================================================

init_db()

if __name__ == "__main__":
    app.run(debug=True)