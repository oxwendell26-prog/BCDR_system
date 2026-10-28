"""
BCDR_system - Barangay Clearance and Document Request System

Ang file na ito ang "utak" ng buong system (backend). Dito natin inilalagay ang:
  1. Configuration (settings ng app)
  2. Database (SQLite / Supabase PostgreSQL) at ang mga table
  3. Helper functions at decorators (login check, role check)
  4. Routes (mga URL / pahina ng system)

Phase 1 (MVP): register, login, resident requests, staff review/approve.
Kasama na rin ang document_types admin, notifications with request_id, at PDF generation.
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

# Kukunin nito ang Supabase connection link kapag naka-deploy na sa Render
DATABASE_URL = os.environ.get("DATABASE_URL")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
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
            # Kapag nasa Render na (Konekta sa Supabase PostgreSQL)
            g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        else:
            # Kapag nagde-develop ka pa sa local PC mo (Gagamit ng SQLite database.db)
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


SCHEMA = """
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
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    requirements    TEXT,
    fee             REAL NOT NULL DEFAULT 0,
    processing_days INTEGER NOT NULL DEFAULT 1,
    is_active       INTEGER NOT NULL DEFAULT 1
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
    if DATABASE_URL:
        # Initial check para sa Supabase connection
        try:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            conn.close()
        except Exception as e:
            print(f"Database connection warning: {e}")
    else:
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA)

        if db.execute("SELECT COUNT(*) FROM document_types").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO document_types (name, description, requirements, fee, processing_days) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    ("Barangay Clearance", "General-purpose barangay clearance.",
                     "Valid ID; Proof of residency", 50, 1),
                    ("Certificate of Residency", "Certifies that the person lives in the barangay.",
                     "Valid ID", 30, 1),
                    ("Certificate of Indigency", "Certifies that the person belongs to an indigent family.",
                     "Valid ID", 0, 2),
                    ("Business Clearance", "Clearance for operating a business in the barangay.",
                     "Valid ID; Business permit or DTI registration", 200, 3),
                ],
            )

        if db.execute("SELECT COUNT(*) FROM barangay_settings").fetchone()[0] == 0:
            db.execute(
                "INSERT INTO barangay_settings (id, barangay_name, municipality, province, "
                "address, punong_barangay, secretary) VALUES (1, ?, ?, ?, ?, ?, ?)",
                ("Your Barangay", "Your Municipality", "Your Province",
                 "Barangay Hall address", "Punong Barangay Name", "Barangay Secretary Name"),
            )

        if db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] == 0:
            admin_password = os.environ.get("BCDR_ADMIN_PASSWORD", "ChangeMe123!")
            db.execute(
                "INSERT INTO users (email, password_hash, role, status, created_at) "
                "VALUES (?, ?, 'admin', 'active', ?)",
                ("admin@barangay.local", generate_password_hash(admin_password), now()),
            )

        db.commit()
        db.close()


def log_action(user_id, action, details=""):
    get_db().execute(
        "INSERT INTO audit_logs (user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
        (user_id, action, details, now()),
    )


# =============================================================================
# 3. HELPERS & DECORATORS
# =============================================================================

@app.before_request
def load_logged_in_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        user = get_db().execute(
            "SELECT id, email, role, status FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user is not None and user["status"] == "active":
            g.user = user
        else:
            session.clear()


@app.context_processor
def inject_template_globals():
    barangay = get_db().execute("SELECT * FROM barangay_settings WHERE id = 1").fetchone()
    unread_notifications_count = 0
    if g.user:
        row = get_db().execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
            (g.user["id"],)
        ).fetchone()
        unread_notifications_count = row[0] if row else 0

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
    resident = get_db().execute(
        "SELECT * FROM residents WHERE user_id = ?", (g.user["id"],)
    ).fetchone()
    if resident is None:
        abort(404)
    return resident


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_attachments(request_id, files):
    db = get_db()
    for file in files:
        extension = file.filename.rsplit(".", 1)[1].lower()
        stored_name = f"{uuid.uuid4().hex}.{extension}"
        file.save(os.path.join(UPLOAD_FOLDER, stored_name))
        db.execute(
            "INSERT INTO request_attachments (request_id, original_name, stored_name, uploaded_at) "
            "VALUES (?, ?, ?, ?)",
            (request_id, secure_filename(file.filename) or "file", stored_name, now()),
        )


def notify_staff_and_admins(request_id, message):
    db = get_db()
    staff_users = db.execute("SELECT id FROM users WHERE role IN ('staff', 'admin') AND status = 'active'").fetchall()
    for staff in staff_users:
        db.execute(
            "INSERT INTO notifications (user_id, request_id, message, is_read, created_at) VALUES (?, ?, ?, 0, ?)",
            (staff["id"], request_id, message, now())
        )
    db.commit()


REQUEST_DETAIL_SQL = """
    SELECT r.*, dt.name AS document_name, dt.fee, dt.processing_days, dt.requirements,
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


def validate_registration(data, password, confirm_password):
    errors = []
    required = [f for f in REGISTER_FIELDS if f != "middle_name"]
    if any(not data[field] for field in required):
        errors.append("Please fill in all required fields.")

    if data["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", data["email"]):
        errors.append("Please enter a valid email address.")

    if data["sex"] and data["sex"] not in SEX_OPTIONS:
        errors.append("Please choose a valid sex option.")
    if data["civil_status"] and data["civil_status"] not in CIVIL_STATUS_OPTIONS:
        errors.append("Please choose a valid civil status.")

    if data["birthdate"]:
        try:
            birthdate = datetime.strptime(data["birthdate"], "%Y-%m-%d")
            if birthdate > datetime.now():
                errors.append("Birthdate cannot be in the future.")
        except ValueError:
            errors.append("Please enter a valid birthdate.")

    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if password != confirm_password:
        errors.append("Passwords do not match.")
    return errors


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(home_for(g.user))

    if request.method == "POST":
        data = {field: request.form.get(field, "").strip() for field in REGISTER_FIELDS}
        data["email"] = data["email"].lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = validate_registration(data, password, confirm_password)
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("public/register.html", form=data)

        db = get_db()
        try:
            if DATABASE_URL:
                cursor = db.cursor()
                cursor.execute(
                    "INSERT INTO users (email, password_hash, role, status, created_at) "
                    "VALUES (%s, %s, 'resident', 'pending', %s) RETURNING id",
                    (data["email"], generate_password_hash(password), now()),
                )
                user_id = cursor.fetchone()["id"]
                db.execute(
                    "INSERT INTO residents (user_id, first_name, middle_name, last_name, birthdate, "
                    "sex, civil_status, purok, address, contact_number) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (user_id, data["first_name"], data["middle_name"], data["last_name"],
                     data["birthdate"], data["sex"], data["civil_status"], data["purok"],
                     data["address"], data["contact_number"]),
                )
            else:
                cursor = db.execute(
                    "INSERT INTO users (email, password_hash, role, status, created_at) "
                    "VALUES (?, ?, 'resident', 'pending', ?)",
                    (data["email"], generate_password_hash(password), now()),
                )
                db.execute(
                    "INSERT INTO residents (user_id, first_name, middle_name, last_name, birthdate, "
                    "sex, civil_status, purok, address, contact_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (cursor.lastrowid, data["first_name"], data["middle_name"], data["last_name"],
                     data["birthdate"], data["sex"], data["civil_status"], data["purok"],
                     data["address"], data["contact_number"]),
                )
            db.commit()
        except Exception:
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

        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

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


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if g.user:
        return redirect(home_for(g.user))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        contact_number = request.form.get("contact_number", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        db = get_db()
        
        user = db.execute("SELECT * FROM users WHERE email = ? AND role = 'resident'", (email,)).fetchone()
        
        if not user:
            flash("No resident account found with that email address.", "danger")
            return render_template("public/forgot_password.html", email=email)

        resident = db.execute("SELECT * FROM residents WHERE user_id = ? AND contact_number = ?", (user["id"], contact_number)).fetchone()
        
        if not resident:
            flash("The contact number does not match our records for this email.", "danger")
            return render_template("public/forgot_password.html", email=email)

        if len(new_password) < 8:
            flash("Password must be at least 8 characters long.", "danger")
            return render_template("public/forgot_password.html", email=email)

        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("public/forgot_password.html", email=email)

        new_hash = generate_password_hash(new_password)
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user["id"]))
        db.commit()

        flash("Your password has been successfully reset. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("public/forgot_password.html", email="")


# =============================================================================
# 5. RESIDENT ROUTES
# =============================================================================

@app.route("/resident/dashboard")
@role_required("resident")
def resident_dashboard():
    db = get_db()
    resident = get_current_resident()

    rows = db.execute(
        "SELECT status, COUNT(*) AS total FROM requests WHERE resident_id = ? GROUP BY status",
        (resident["id"],),
    ).fetchall()
    status_counts = {row["status"]: row["total"] for row in rows}

    recent_requests = db.execute(
        REQUEST_DETAIL_SQL + " WHERE r.resident_id = ? ORDER BY r.created_at DESC, r.id DESC LIMIT 5",
        (resident["id"],),
    ).fetchall()

    return render_template(
        "resident/dashboard.html",
        resident=resident, status_counts=status_counts, recent_requests=recent_requests,
    )


@app.route("/resident/new-request", methods=["GET", "POST"])
@role_required("resident")
def new_request():
    db = get_db()
    resident = get_current_resident()
    document_types = db.execute(
        "SELECT * FROM document_types WHERE is_active = 1 ORDER BY name"
    ).fetchall()

    if request.method == "POST":
        document_type_id = request.form.get("document_type_id", type=int)
        purpose = request.form.get("purpose", "").strip()
        files = [f for f in request.files.getlist("attachments") if f and f.filename]

        errors = []
        document_type = None
        if document_type_id:
            document_type = db.execute(
                "SELECT * FROM document_types WHERE id = ? AND is_active = 1", (document_type_id,)
            ).fetchone()
        if document_type is None:
            errors.append("Please choose a valid document type.")
        if len(purpose) < 5:
            errors.append("Please state the purpose of your request.")
        if len(files) > MAX_FILES_PER_REQUEST:
            errors.append(f"You can upload up to {MAX_FILES_PER_REQUEST} files only.")
        for file in files:
            if not allowed_file(file.filename):
                errors.append(f'"{file.filename}" is not allowed. Allowed types: '
                              f'{", ".join(sorted(ALLOWED_EXTENSIONS))}.')

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "resident/new-request.html", document_types=document_types,
                form={"document_type_id": document_type_id, "purpose": purpose},
            )

        timestamp = now()
        if DATABASE_URL:
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO requests (resident_id, document_type_id, purpose, status, created_at, updated_at) "
                "VALUES (%s, %s, %s, 'Submitted', %s, %s) RETURNING id",
                (resident["id"], document_type["id"], purpose, timestamp, timestamp),
            )
            request_id = cursor.fetchone()["id"]
        else:
            cursor = db.execute(
                "INSERT INTO requests (resident_id, document_type_id, purpose, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'Submitted', ?, ?)",
                (resident["id"], document_type["id"], purpose, timestamp, timestamp),
            )
            request_id = cursor.lastrowid
            
        save_attachments(request_id, files)

        resident_info = db.execute("SELECT first_name, last_name FROM residents WHERE id = ?", (resident["id"],)).fetchone()
        resident_name = f"{resident_info['first_name']} {resident_info['last_name']}" if resident_info else "A resident"
        notif_msg = f"New document request (#{request_id}) for {document_type['name']} submitted by {resident_name}."
        notify_staff_and_admins(request_id, notif_msg)

        db.commit()

        flash("Your request has been submitted.", "success")
        return redirect(url_for("request_details", request_id=request_id))

    return render_template("resident/new-request.html", document_types=document_types, form={})


@app.route("/resident/my-requests")
@role_required("resident")
def my_requests():
    resident = get_current_resident()
    requests_list = get_db().execute(
        REQUEST_DETAIL_SQL + " WHERE r.resident_id = ? ORDER BY r.created_at DESC, r.id DESC",
        (resident["id"],),
    ).fetchall()
    return render_template("resident/my-requests.html", requests=requests_list)


@app.route("/resident/requests/<int:request_id>")
@role_required("resident")
def request_details(request_id):
    db = get_db()
    resident = get_current_resident()
    req = db.execute(
        REQUEST_DETAIL_SQL + " WHERE r.id = ? AND r.resident_id = ?", (request_id, resident["id"])
    ).fetchone()
    if req is None:
        abort(404)
    attachments = db.execute(
        "SELECT * FROM request_attachments WHERE request_id = ?", (request_id,)
    ).fetchall()
    return render_template("resident/request-details.html", req=req, attachments=attachments)


@app.route("/resident/requests/<int:request_id>/cancel", methods=["POST"])
@role_required("resident")
def cancel_request(request_id):
    db = get_db()
    resident = get_current_resident()
    req = db.execute(
        "SELECT * FROM requests WHERE id = ? AND resident_id = ?", (request_id, resident["id"])
    ).fetchone()
    if req is None:
        abort(404)

    if req["status"] != "Submitted":
        flash("Only requests that are still 'Submitted' can be cancelled.", "warning")
    else:
        db.execute("UPDATE requests SET status = 'Cancelled', updated_at = ? WHERE id = ?",
                   (now(), request_id))
        db.commit()
        flash("Your request has been cancelled.", "info")
    return redirect(url_for("request_details", request_id=request_id))


@app.route("/requests/<int:request_id>/download-pdf")
@role_required("resident", "staff", "admin")
def download_document_pdf(request_id):
    db = get_db()
    
    if g.user["role"] in STAFF_ROLES:
        req = db.execute(
            REQUEST_DETAIL_SQL + " WHERE r.id = ?", (request_id,)
        ).fetchone()
    else:
        resident = get_current_resident()
        req = db.execute(
            REQUEST_DETAIL_SQL + " WHERE r.id = ? AND r.resident_id = ?", (request_id, resident["id"])
        ).fetchone()

    if not req or req["status"] != "Released":
        flash("Document is not available for download yet. Please settle your payment or wait for the staff to release the document.", "danger")
        if g.user["role"] in STAFF_ROLES:
            return redirect(url_for("review_request", request_id=request_id))
        return redirect(url_for("my_requests"))

    barangay = db.execute("SELECT * FROM barangay_settings WHERE id = 1").fetchone()

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
    text_object.textLine("Given this day upon request of the interested party for whatever legal purpose")
    text_object.textLine("it may serve.")
    
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
# 6. GENERAL NOTIFICATIONS & PROFILE ROUTES
# =============================================================================

@app.route("/notifications")
@login_required
def notifications_page():
    db = get_db()
    notifications = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC",
        (g.user["id"],)
    ).fetchall()

    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (g.user["id"],))
    db.commit()

    return render_template("resident/notifications.html", notifications=notifications)


@app.route("/notifications/clear", methods=["POST"])
@login_required
def clear_notifications():
    db = get_db()
    db.execute("DELETE FROM notifications WHERE user_id = ?", (g.user["id"],))
    db.commit()
    flash("All notifications have been cleared.", "info")
    return redirect(url_for("notifications_page"))


@app.route("/notifications/<int:notif_id>/delete", methods=["POST"])
@login_required
def delete_notification(notif_id):
    db = get_db()
    db.execute("DELETE FROM notifications WHERE id = ? AND user_id = ?", (notif_id, g.user["id"]))
    db.commit()
    flash("Notification deleted.", "info")
    return redirect(url_for("notifications_page"))


@app.route("/resident/profile", methods=["GET", "POST"])
@role_required("resident")
def profile():
    db = get_db()
    resident = get_current_resident()

    if request.method == "POST":
        purok = request.form.get("purok", "").strip()
        address = request.form.get("address", "").strip()
        contact_number = request.form.get("contact_number", "").strip()
        if not (purok and address and contact_number):
            flash("Purok, address, and contact number are required.", "danger")
        else:
            db.execute(
                "UPDATE residents SET purok = ?, address = ?, contact_number = ? WHERE id = ?",
                (purok, address, contact_number, resident["id"]),
            )
            db.commit()
            flash("Your profile has been updated.", "success")
            return redirect(url_for("profile"))
        resident = get_current_resident()

    return render_template("resident/profile.html", resident=resident)

@app.route("/resident/requests/<int:request_id>/delete", methods=["POST"])
@role_required("resident")
def delete_resident_request(request_id):
    db = get_db()
    resident = get_current_resident()
    db.execute("DELETE FROM requests WHERE id = ? AND resident_id = ?", (request_id, resident["id"]))
    db.commit()
    flash("Request deleted successfully.", "success")
    return redirect(url_for('my_requests'))

@app.route("/resident/requests/delete-all", methods=["POST"])
@role_required("resident")
def delete_all_resident_requests():
    db = get_db()
    resident = get_current_resident()
    db.execute("DELETE FROM requests WHERE resident_id = ?", (resident["id"],))
    db.commit()
    flash("All your requests have been cleared.", "success")
    return redirect(url_for('my_requests'))


# =============================================================================
# 7. STAFF ROUTES
# =============================================================================

@app.route("/staff/dashboard")
@role_required(*STAFF_ROLES)
def staff_dashboard():
    db = get_db()
    rows = db.execute("SELECT status, COUNT(*) AS total FROM requests GROUP BY status").fetchall()
    status_counts = {row["status"]: row["total"] for row in rows}
    pending_residents = db.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'resident' AND status = 'pending'"
    ).fetchone()[0]
    return render_template(
        "staff/dashboard.html", status_counts=status_counts, pending_residents=pending_residents,
    )


@app.route("/staff/request-queue")
@role_required(*STAFF_ROLES)
def request_queue():
    db = get_db()
    status = request.args.get("status", "").strip()
    search = request.args.get("search", "").strip()

    query = REQUEST_DETAIL_SQL + " WHERE 1=1"
    params = []

    if status in REQUEST_STATUSES:
        query += " AND r.status = ?"
        params.append(status)
    else:
        placeholders = ", ".join("?" for _ in OPEN_STATUSES)
        query += f" AND r.status IN ({placeholders})"
        params.extend(OPEN_STATUSES)

    if search:
        query += " AND (res.first_name LIKE ? OR res.last_name LIKE ? OR u.email LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])

    query += " ORDER BY r.created_at ASC, r.id ASC"

    requests_list = db.execute(query, params).fetchall()
    
    return render_template(
        "staff/request-queue.html",
        requests=requests_list,
        selected_status=status,
        search_query=search,
    )


@app.route("/staff/requests/<int:request_id>", methods=["GET", "POST"])
@role_required(*STAFF_ROLES)
def review_request(request_id):
    db = get_db()
    req = db.execute(REQUEST_DETAIL_SQL + " WHERE r.id = ?", (request_id,)).fetchone()
    if req is None:
        abort(404)

    if request.method == "POST":
        new_status = request.form.get("status", "").strip()
        remarks = request.form.get("remarks", "").strip()

        if req["status"] in FINAL_STATUSES and req["status"] != "Approved":
            flash(f"This request is already {req['status']} and can no longer be changed.", "warning")
        elif new_status not in STAFF_SETTABLE_STATUSES:
            flash("Please choose a valid status.", "danger")
        elif new_status in REMARKS_REQUIRED_STATUSES and not remarks:
            flash(f"Remarks are required when setting a request to '{new_status}'.", "danger")
        else:
            db.execute(
                "UPDATE requests SET status = ?, remarks = ?, reviewed_by = ?, updated_at = ? WHERE id = ?",
                (new_status, remarks, g.user["id"], now(), request_id),
            )

            if new_status == "Approved":
                notif_msg = f"Your request for '{req['document_name']}' has been APPROVED! Please settle your payment so staff can release your document."
                db.execute(
                    "INSERT INTO notifications (user_id, request_id, message, is_read, created_at) VALUES (?, ?, ?, 0, ?)",
                    (req["user_id"], request_id, notif_msg, now())
                )
            elif new_status == "Released":
                notif_msg = f"Your document '{req['document_name']}' has been RELEASED! You can now view and download your official document."
                db.execute(
                    "INSERT INTO notifications (user_id, request_id, message, is_read, created_at) VALUES (?, ?, ?, 0, ?)",
                    (req["user_id"], request_id, notif_msg, now())
                )

            db.commit()
            flash(f"Request #{request_id} is now '{new_status}'.", "success")
            return redirect(url_for("request_queue"))

        req = db.execute(REQUEST_DETAIL_SQL + " WHERE r.id = ?", (request_id,)).fetchone()

    attachments = db.execute(
        "SELECT * FROM request_attachments WHERE request_id = ?", (request_id,)
    ).fetchall()
    return render_template("staff/review-request.html", req=req, attachments=attachments)


@app.route("/staff/residents")
@role_required(*STAFF_ROLES)
def residents_list():
    residents = get_db().execute(
        """
        SELECT res.*, u.id AS user_id, u.email, u.status, u.created_at
        FROM residents res
        JOIN users u ON u.id = res.user_id
        ORDER BY CASE u.status WHEN 'pending' THEN 0 ELSE 1 END, res.last_name, res.first_name
        """
    ).fetchall()
    return render_template("staff/residents.html", residents=residents)


@app.route("/staff/residents/<int:user_id>/decision", methods=["POST"])
@role_required(*STAFF_ROLES)
def resident_decision(user_id):
    decision = request.form.get("decision", "")
    if decision not in ("approve", "reject"):
        abort(400)

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ? AND role = 'resident'", (user_id,)
    ).fetchone()
    if user is None:
        abort(404)

    new_status = "active" if decision == "approve" else "rejected"
    db.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, user_id))
    db.commit()
    flash(f"Resident account {new_status}: {user['email']}", "success")
    return redirect(url_for("residents_list"))


@app.route("/staff/document_types")
@role_required(*STAFF_ROLES)
def document_types():
    db = get_db()
    rows = db.execute("SELECT * FROM document_types ORDER BY name").fetchall()
    document_types_list = [dict(row) for row in rows]
    return render_template("staff/document_types.html", document_types=document_types_list)


@app.route("/staff/document_types/save", methods=["POST"])
@role_required(*STAFF_ROLES)
def save_document_type():
    db = get_db()
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

    try:
        if doc_id:
            db.execute(
                "UPDATE document_types SET name = ?, description = ?, requirements = ?, fee = ?, processing_days = ? WHERE id = ?",
                (name, description, requirements, fee, processing_days, doc_id),
            )
            flash("Document type updated successfully.", "success")
        else:
            db.execute(
                "INSERT INTO document_types (name, description, requirements, fee, processing_days, is_active) VALUES (?, ?, ?, ?, ?, 1)",
                (name, description, requirements, fee, processing_days),
            )
            flash("New document type added successfully.", "success")
        db.commit()
    except Exception:
        db.rollback()
        flash("A document type with that name already exists.", "danger")

    return redirect(url_for("document_types"))


@app.route("/staff/document_types/toggle/<int:doc_id>", methods=["POST"])
@role_required(*STAFF_ROLES)
def toggle_document_type(doc_id):
    db = get_db()
    doc = db.execute("SELECT * FROM document_types WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        abort(404)

    new_status = 0 if doc["is_active"] == 1 else 1
    db.execute("UPDATE document_types SET is_active = ? WHERE id = ?", (new_status, doc_id))
    db.commit()

    status_word = "activated" if new_status == 1 else "deactivated"
    flash(f"Document type has been {status_word}.", "info")
    return redirect(url_for("document_types"))


@app.route("/staff/settings", methods=["GET", "POST"])
@role_required(*STAFF_ROLES)
def barangay_settings_page():
    db = get_db()

    if request.method == "POST":
        barangay_name = request.form.get("barangay_name", "").strip()
        municipality = request.form.get("municipality", "").strip()
        province = request.form.get("province", "").strip()
        address = request.form.get("address", "").strip()
        punong_barangay = request.form.get("punong_barangay", "").strip()
        secretary = request.form.get("secretary", "").strip()
        control_prefix = request.form.get("control_number_prefix", "").strip() or "BRGY"

        if not (barangay_name and municipality and province):
            flash("Barangay Name, Municipality, and Province are required.", "danger")
        else:
            db.execute(
                """
                UPDATE barangay_settings
                SET barangay_name = ?, municipality = ?, province = ?, address = ?,
                    punong_barangay = ?, secretary = ?, control_number_prefix = ?
                WHERE id = 1
                """,
                (barangay_name, municipality, province, address, punong_barangay, secretary, control_prefix),
            )
            db.commit()
            flash("Barangay settings updated successfully!", "success")
            return redirect(url_for("barangay_settings_page"))

    settings = db.execute("SELECT * FROM barangay_settings WHERE id = 1").fetchone()
    return render_template("staff/settings.html", settings=settings)

@app.route("/staff/records/released")
@role_required(*STAFF_ROLES)
def released_records():
    search_query = request.args.get("q", "").strip()
    db = get_db()
    
    if search_query:
        sql = REQUEST_DETAIL_SQL + " WHERE r.status = 'Released' AND (u.first_name LIKE ? OR u.last_name LIKE ? OR dt.name LIKE ?) ORDER BY r.updated_at DESC, r.id DESC"
        like_term = f"%{search_query}%"
        released_list = db.execute(sql, (like_term, like_term, like_term)).fetchall()
    else:
        released_list = db.execute(
            REQUEST_DETAIL_SQL + " WHERE r.status = 'Released' ORDER BY r.updated_at DESC, r.id DESC"
        ).fetchall()
        
    return render_template("staff/released_records.html", requests=released_list, search_query=search_query)

@app.route("/staff/records/delete/<int:request_id>", methods=["POST"])
@role_required(*STAFF_ROLES)
def delete_released_record(request_id):
    db = get_db()
    db.execute("DELETE FROM requests WHERE id = ? AND status = 'Released'", (request_id,))
    db.commit()
    flash("Released record deleted successfully.", "success")
    return redirect(url_for('released_records'))

@app.route("/staff/records/delete-all", methods=["POST"])
@role_required(*STAFF_ROLES)
def delete_all_released_records():
    db = get_db()
    db.execute("DELETE FROM requests WHERE status = 'Released'")
    db.commit()
    flash("All released records have been cleared.", "success")
    return redirect(url_for('released_records'))

@app.route("/staff/residents/<int:resident_id>/edit", methods=["GET", "POST"])
@role_required(*STAFF_ROLES)
def staff_edit_resident(resident_id):
    db = get_db()
    resident = db.execute(
        """
        SELECT res.*, u.email, u.status, u.id AS user_id
        FROM residents res
        JOIN users u ON u.id = res.user_id
        WHERE res.id = ?
        """,
        (resident_id,),
    ).fetchone()
    if resident is None:
        abort(404)

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        middle_name = request.form.get("middle_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        birthdate = request.form.get("birthdate", "").strip()
        sex = request.form.get("sex", "").strip()
        civil_status = request.form.get("civil_status", "").strip()
        purok = request.form.get("purok", "").strip()
        address = request.form.get("address", "").strip()
        contact_number = request.form.get("contact_number", "").strip()

        if not (first_name and last_name and birthdate and sex and civil_status and purok and address and contact_number):
            flash("Please fill in all required fields.", "danger")
        else:
            db.execute(
                """
                UPDATE residents 
                SET first_name = ?, middle_name = ?, last_name = ?, birthdate = ?, 
                    sex = ?, civil_status = ?, purok = ?, address = ?, contact_number = ?
                WHERE id = ?
                """,
                (first_name, middle_name, last_name, birthdate, sex, civil_status, purok, address, contact_number, resident_id)
            )
            db.commit()
            flash(f"Resident profile for {first_name} {last_name} updated successfully.", "success")
            return redirect(url_for("residents_list"))

    return render_template("staff/edit_resident.html", resident=resident)


# =============================================================================
# 8. PROTECTED FILE DOWNLOAD
# =============================================================================

@app.route("/attachments/<int:attachment_id>")
@login_required
def view_attachment(attachment_id):
    db = get_db()
    attachment = db.execute(
        """
        SELECT a.*, res.user_id AS owner_user_id
        FROM request_attachments a
        JOIN requests r ON r.id = a.request_id
        JOIN residents res ON res.id = r.resident_id
        WHERE a.id = ?
        """,
        (attachment_id,),
    ).fetchone()
    if attachment is None:
        abort(404)

    if g.user["role"] not in STAFF_ROLES and attachment["owner_user_id"] != g.user["id"]:
        abort(404)

    return send_from_directory(
        UPLOAD_FOLDER, attachment["stored_name"],
        download_name=attachment["original_name"],
    )


# =============================================================================
# 9. ERROR HANDLERS
# =============================================================================

def render_error(code, title, message):
    return render_template("error.html", code=code, title=title, message=message), code


@app.errorhandler(400)
def bad_request(error):
    return render_error(400, "Bad Request", "The request could not be understood.")


@app.errorhandler(403)
def forbidden(error):
    return render_error(403, "Access Denied", "You do not have permission to view this page.")


@app.errorhandler(404)
def not_found(error):
    return render_error(404, "Page Not Found", "The page you are looking for does not exist.")


@app.errorhandler(413)
def too_large(error):
    return render_error(413, "File Too Large", "The upload is too large. The maximum total size is 5 MB.")


@app.errorhandler(500)
def server_error(error):
    return render_error(500, "Server Error", "Something went wrong on our side. Please try again later.")


# =============================================================================
# 10. APP START
# =============================================================================

init_db()

if __name__ == "__main__":
    app.run(debug=True)