/**
 * auth.js — Gestion login et register pour le dashboard MIA.
 * JS vanilla, zero dependance.
 */
(function () {
    "use strict";

    var API_BASE = window.location.origin;

    /**
     * Affiche un message d'erreur dans l'element cible.
     * @param {string} elementId - id de l'element erreur
     * @param {string} message   - texte a afficher
     */
    function showError(elementId, message) {
        var el = document.getElementById(elementId);
        if (!el) return;
        el.textContent = message;
        el.classList.add("visible");
    }

    /**
     * Cache le message d'erreur.
     * @param {string} elementId - id de l'element erreur
     */
    function hideError(elementId) {
        var el = document.getElementById(elementId);
        if (!el) return;
        el.textContent = "";
        el.classList.remove("visible");
    }

    /**
     * POST JSON vers l'API et retourne la reponse parsee.
     * @param {string} url  - endpoint
     * @param {object} body - payload JSON
     * @returns {Promise<object>}
     */
    function postJSON(url, body) {
        return fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        }).then(function (res) {
            return res.json().then(function (data) {
                if (!res.ok) {
                    var msg = data.detail || "Erreur inconnue.";
                    throw new Error(msg);
                }
                return data;
            });
        });
    }

    // =========================================================
    // Login
    // =========================================================

    function handleLogin(e) {
        e.preventDefault();
        hideError("login-error");

        var email = document.getElementById("email").value.trim();
        var password = document.getElementById("password").value;

        if (!email || !password) {
            showError("login-error", "Veuillez remplir tous les champs.");
            return;
        }

        postJSON(API_BASE + "/api/auth/login", {
            email: email,
            password: password,
        })
            .then(function (data) {
                try {
                    localStorage.setItem("mia_token", data.token);
                } catch (_e) {
                    // localStorage indisponible — on continue quand meme
                }
                window.location.href = "/";
            })
            .catch(function (err) {
                showError("login-error", err.message);
            });
    }

    // =========================================================
    // Register
    // =========================================================

    function handleRegister(e) {
        e.preventDefault();
        hideError("reg-error");

        var firstName = document.getElementById("first_name").value.trim();
        var lastName = document.getElementById("last_name").value.trim();
        var email = document.getElementById("email").value.trim();
        var password = document.getElementById("password").value;
        var confirm = document.getElementById("password_confirm").value;

        if (!firstName || !lastName || !email || !password || !confirm) {
            showError("reg-error", "Veuillez remplir tous les champs.");
            return;
        }

        if (password !== confirm) {
            showError("reg-error", "Les mots de passe ne correspondent pas.");
            return;
        }

        if (password.length < 6) {
            showError("reg-error", "Le mot de passe doit faire au moins 6 caracteres.");
            return;
        }

        postJSON(API_BASE + "/api/auth/register", {
            email: email,
            password: password,
            first_name: firstName,
            last_name: lastName,
        })
            .then(function (data) {
                try {
                    localStorage.setItem("mia_token", data.token);
                } catch (_e) {
                    // localStorage indisponible
                }
                window.location.href = "/";
            })
            .catch(function (err) {
                showError("reg-error", err.message);
            });
    }

    // =========================================================
    // Checkbox CGU -> active/desactive bouton register
    // =========================================================

    function setupCguCheckbox() {
        var checkbox = document.getElementById("accept-cgu");
        var btn = document.getElementById("btn-register");
        if (!checkbox || !btn) return;

        checkbox.addEventListener("change", function () {
            btn.disabled = !checkbox.checked;
        });
    }

    // =========================================================
    // Init
    // =========================================================

    function init() {
        var loginForm = document.getElementById("login-form");
        if (loginForm) {
            loginForm.addEventListener("submit", handleLogin);
        }

        var registerForm = document.getElementById("register-form");
        if (registerForm) {
            registerForm.addEventListener("submit", handleRegister);
        }

        setupCguCheckbox();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
