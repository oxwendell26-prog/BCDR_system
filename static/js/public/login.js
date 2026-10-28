document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("login-form");
    if (!form) return;

    var emailInput = document.getElementById("email");
    var passwordInput = document.getElementById("password");
    var showPasswordCheckbox = document.getElementById("show-password");
    var togglePasswordBtn = document.getElementById("toggle-password-icon");
    var eyeIcon = document.getElementById("eye-icon");
    var loginButton = document.getElementById("login-button");

    var EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

    // Function para baguhin ang state ng password visibility
    function setPasswordVisibility(isVisible) {
        if (!passwordInput) return;
        passwordInput.type = isVisible ? "text" : "password";
        if (showPasswordCheckbox) {
            showPasswordCheckbox.checked = isVisible;
        }

        // Palitan ang kulay o hitsura ng eye icon kapag naka-show/hide
        if (eyeIcon) {
            eyeIcon.style.stroke = isVisible ? "#2563eb" : "#64748b";
        }
    }

    // Kapag pinindot ang icon ng mata sa loob ng input
    if (togglePasswordBtn && passwordInput) {
        togglePasswordBtn.addEventListener("click", function (e) {
            e.preventDefault();
            var isCurrentlyPassword = passwordInput.type === "password";
            setPasswordVisibility(isCurrentlyPassword);
        });
    }

    // Kapag tinanggalan o nilagyan ng check ang "Show passwords" sa baba
    if (showPasswordCheckbox && passwordInput) {
        showPasswordCheckbox.addEventListener("change", function () {
            setPasswordVisibility(showPasswordCheckbox.checked);
        });
    }

    // Form submission validation at loading state
    form.addEventListener("submit", function (event) {
        var emailVal = emailInput ? emailInput.value.trim() : "";
        var passwordVal = passwordInput ? passwordInput.value : "";

        if (emailVal === "" || !EMAIL_PATTERN.test(emailVal) || passwordVal === "") {
            return;
        }

        if (loginButton) {
            loginButton.disabled = true;
            loginButton.textContent = "Logging in...";
        }
    });

    window.addEventListener("pageshow", function (event) {
        if (event.persisted && loginButton) {
            loginButton.disabled = false;
            loginButton.textContent = "Log in";
        }
    });
});