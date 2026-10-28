/* ==========================================================================
   base.js - JavaScript na ginagamit sa LAHAT ng pahina (kasama sa base.html).
   Walang inline onclick sa HTML; lahat ng event ay dito idinadagdag gamit
   ang addEventListener.
   ========================================================================== */

/* Hintayin munang ma-load ang buong HTML bago hanapin ang mga element. */
document.addEventListener("DOMContentLoaded", function () {
    initNavToggle();
    initUserDropdown();
    initAlerts();
    initConfirmForms();
    setCurrentYear();
});

/* ---------- 1. Hamburger menu sa cellphone ---------- */
function initNavToggle() {
    var toggle = document.getElementById("nav-toggle");
    var nav = document.getElementById("main-nav");
    if (!toggle || !nav) return;

    toggle.addEventListener("click", function () {
        var isOpen = nav.classList.toggle("is-open");
        /* aria-expanded = para alam ng screen reader kung bukas o sarado ang menu. */
        toggle.setAttribute("aria-expanded", String(isOpen));
    });
}

/* ---------- 2. User Profile Dropdown Toggle (Log out menu) ---------- */
function initUserDropdown() {
    const userToggle = document.getElementById('user-menu-toggle');
    const userDropdown = document.getElementById('user-dropdown');

    if (!userToggle || !userDropdown) return;

    userToggle.addEventListener('click', function (e) {
        e.stopPropagation();
        var isShown = userDropdown.classList.toggle('show');
        userToggle.setAttribute('aria-expanded', String(isShown));
    });

    // Isara ang dropdown kapag pinindot ang labas nito
    window.addEventListener('click', function () {
        if (userDropdown.classList.contains('show')) {
            userDropdown.classList.remove('show');
            userToggle.setAttribute('aria-expanded', 'false');
        }
    });
}

/* ---------- 3. Flash messages ----------
   - May "x" button para isara ang alert.
   - Kusang nawawala ang "success" at "info" pagkalipas ng 6 na segundo.
   - Hindi kusang nawawala ang "danger" at "warning" para hindi mo ito makaligtaan. */
function initAlerts() {
    var alerts = document.querySelectorAll(".alert");

    alerts.forEach(function (alertBox) {
        var closeButton = alertBox.querySelector(".alert-close");
        if (closeButton) {
            closeButton.addEventListener("click", function () {
                alertBox.remove();
            });
        }

        var autoHide = alertBox.classList.contains("alert-success") ||
            alertBox.classList.contains("alert-info");
        if (autoHide) {
            setTimeout(function () {
                alertBox.remove();
            }, 6000);
        }
    });
}

/* ---------- 4. Confirmation bago mag-submit ----------
   Paggamit sa HTML:  <form method="post" data-confirm="Cancel this request?">
   Kapag pinindot ng user ang "Cancel" sa kahon, hindi ipapadala ang form. */
function initConfirmForms() {
    var forms = document.querySelectorAll("form[data-confirm]");

    forms.forEach(function (form) {
        form.addEventListener("submit", function (event) {
            var message = form.getAttribute("data-confirm");
            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });
}

/* ---------- 5. Taon sa footer ---------- */
function setCurrentYear() {
    var yearSpan = document.getElementById("current-year");
    if (yearSpan) {
        yearSpan.textContent = new Date().getFullYear();
    }
}