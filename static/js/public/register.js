document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("register-form");
    if (!form) return;

    var EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
    var PHONE_PATTERN = /^[0-9+\-\s()]+$/;

    var registerButton = document.getElementById("register-button");
    var showPassword = document.getElementById("show-password");

    var fieldNames = [
        "first_name", "middle_name", "last_name", "birthdate", "sex", "civil_status",
        "purok", "contact_number", "address", "email", "password", "confirm_password"
    ];
    var trimmedFields = [
        "first_name", "middle_name", "last_name", "purok", "contact_number", "address", "email"
    ];

    var inputs = {};
    var errors = {};
    fieldNames.forEach(function (name) {
        inputs[name] = document.getElementById(name);
        errors[name] = document.getElementById(name + "-error");
    });

    function todayAsText() {
        var now = new Date();
        var month = String(now.getMonth() + 1).padStart(2, "0");
        var day = String(now.getDate()).padStart(2, "0");
        return now.getFullYear() + "-" + month + "-" + day;
    }

    inputs.birthdate.max = todayAsText();

    var validators = {
        first_name: function (value) {
            return value === "" ? "Please enter your first name." : "";
        },
        middle_name: function () {
            return "";
        },
        last_name: function (value) {
            return value === "" ? "Please enter your last name." : "";
        },
        birthdate: function (value) {
            if (value === "") return "Please enter your birthdate.";
            var birthdate = new Date(value + "T00:00:00");
            if (isNaN(birthdate.getTime())) return "Please enter a valid birthdate.";
            if (value > todayAsText()) return "Birthdate cannot be in the future.";
            return "";
        },
        sex: function (value) {
            return value === "" ? "Please select your sex." : "";
        },
        civil_status: function (value) {
            return value === "" ? "Please select your civil status." : "";
        },
        purok: function (value) {
            return value === "" ? "Please enter your purok." : "";
        },
        contact_number: function (value) {
            if (value === "") return "Please enter your contact number.";
            if (!PHONE_PATTERN.test(value) || value.replace(/\D/g, "").length < 7) {
                return "Please enter a valid contact number.";
            }
            return "";
        },
        address: function (value) {
            return value === "" ? "Please enter your home address." : "";
        },
        email: function (value) {
            if (value === "") return "Please enter your email address.";
            if (!EMAIL_PATTERN.test(value)) return "Please enter a valid email address.";
            return "";
        },
        password: function (value) {
            if (value === "") return "Please enter a password.";
            if (value.length < 8) return "Password must be at least 8 characters long.";
            return "";
        },
        confirm_password: function (value) {
            if (value === "") return "Please confirm your password.";
            if (value !== inputs.password.value) return "Passwords do not match.";
            return "";
        }
    };

    function showError(name, message) {
        inputs[name].classList.add("is-invalid");
        errors[name].textContent = message;
        errors[name].hidden = false;
    }

    function clearError(name) {
        inputs[name].classList.remove("is-invalid");
        errors[name].textContent = "";
        errors[name].hidden = true;
    }

    fieldNames.forEach(function (name) {
        var eventName = inputs[name].tagName === "SELECT" ? "change" : "input";
        inputs[name].addEventListener(eventName, function () {
            clearError(name);
        });
    });

    showPassword.addEventListener("change", function () {
        var type = showPassword.checked ? "text" : "password";
        inputs.password.type = type;
        inputs.confirm_password.type = type;
    });

    form.addEventListener("submit", function (event) {
        var firstInvalid = null;

        trimmedFields.forEach(function (name) {
            inputs[name].value = inputs[name].value.trim();
        });

        fieldNames.forEach(function (name) {
            clearError(name);
            var message = validators[name](inputs[name].value);
            if (message !== "") {
                showError(name, message);
                if (firstInvalid === null) {
                    firstInvalid = inputs[name];
                }
            }
        });

        if (firstInvalid !== null) {
            event.preventDefault();
            firstInvalid.focus();
            return;
        }

        registerButton.disabled = true;
        registerButton.textContent = "Creating account...";
    });

    window.addEventListener("pageshow", function (event) {
        if (event.persisted) {
            registerButton.disabled = false;
            registerButton.textContent = "Create account";
        }
    });
});