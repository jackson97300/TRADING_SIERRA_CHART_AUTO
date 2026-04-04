/**
 * dashboard.js — MIA Dashboard polling + rendering
 * IIFE — pas de globales, JS vanilla, zero dependance
 */
(function () {
    "use strict";

    // =========================================================
    // Constantes
    // =========================================================
    var API_BASE = window.location.origin;
    var POLL_INTERVAL = 5000;
    var DISCORD_WEBHOOK_URL = "DISCORD_WEBHOOK_URL"; // placeholder — remplacer par le vrai webhook

    // =========================================================
    // Etat interne
    // =========================================================
    var userTier = "free";
    var pollTimer = null;

    // =========================================================
    // Auth helpers
    // =========================================================

    /** Lit le JWT stocke dans localStorage */
    function getToken() {
        try {
            return localStorage.getItem("mia_token") || null;
        } catch (_e) {
            return null;
        }
    }

    /** Decode le payload JWT (base64url) et retourne le tier */
    function getUserTier() {
        var token = getToken();
        if (!token) return "free";
        try {
            var parts = token.split(".");
            if (parts.length < 2) return "free";
            // base64url -> base64 standard
            var payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
            var decoded = JSON.parse(atob(payload));
            return decoded.tier || "free";
        } catch (_e) {
            return "free";
        }
    }

    // =========================================================
    // Helpers DOM
    // =========================================================

    /** Met a jour le textContent d'un element par son id */
    function setText(id, text) {
        var el = document.getElementById(id);
        if (el) el.textContent = text != null ? text : "--";
    }

    /**
     * Affiche une valeur coloree selon comparaison avec un seuil neutre.
     * @param {string} id       — id de l'element
     * @param {*}      value    — valeur brute
     * @param {number} neutral  — seuil de neutralite (0 par defaut)
     * @param {string} suffix   — suffixe optionnel
     */
    function setColoredValue(id, value, neutral, suffix) {
        var el = document.getElementById(id);
        if (!el) return;
        if (neutral == null) neutral = 0;
        if (suffix == null) suffix = "";

        var num = parseFloat(value);
        var display = (value == null || value === "") ? "--" : formatNum(value) + suffix;
        el.textContent = display;

        // Nettoyage classes
        el.classList.remove("stat-positive", "stat-negative", "stat-neutral");
        if (isNaN(num)) {
            el.classList.add("stat-neutral");
        } else if (num > neutral) {
            el.classList.add("stat-positive");
        } else if (num < neutral) {
            el.classList.add("stat-negative");
        } else {
            el.classList.add("stat-neutral");
        }
    }

    /** Met a jour une gauge (barre de progression) */
    function setGauge(id, pct, colorClass) {
        var el = document.getElementById(id);
        if (!el) return;
        var clamped = Math.max(0, Math.min(100, pct));
        el.style.width = clamped + "%";
        if (colorClass) {
            el.className = "gauge-fill " + colorClass;
        }
    }

    /** Formatte un nombre — retourne "--" si invalide */
    function formatNum(n) {
        if (n == null || n === "") return "--";
        var num = parseFloat(n);
        if (isNaN(num)) return "--";
        return num.toFixed(2);
    }

    /** Met a jour l'heure de derniere MAJ */
    function updateLastUpdate() {
        var now = new Date();
        var hh = String(now.getHours()).padStart(2, "0");
        var mm = String(now.getMinutes()).padStart(2, "0");
        var ss = String(now.getSeconds()).padStart(2, "0");
        setText("last-update", hh + ":" + mm + ":" + ss);
    }

    /** Badge de statut de rafraichissement */
    function updateRefreshStatus(ok) {
        var el = document.getElementById("refresh-status");
        if (!el) return;
        if (ok) {
            el.style.color = "var(--text-disabled)";
        } else {
            el.style.color = "var(--red)";
        }
    }

    /** Deverrouille les panels premium */
    function unlockPanels() {
        var locked = document.querySelectorAll(".premium-locked");
        for (var i = 0; i < locked.length; i++) {
            locked[i].classList.remove("premium-locked");
        }
        var overlays = document.querySelectorAll(".premium-overlay");
        for (var j = 0; j < overlays.length; j++) {
            overlays[j].style.display = "none";
        }
    }

    // =========================================================
    // Horloge navbar
    // =========================================================
    function updateNavbarClock() {
        var now = new Date();
        var hh = String(now.getHours()).padStart(2, "0");
        var mm = String(now.getMinutes()).padStart(2, "0");
        var ss = String(now.getSeconds()).padStart(2, "0");
        setText("navbar-time", hh + ":" + mm + ":" + ss);
    }
    setInterval(updateNavbarClock, 1000);
    updateNavbarClock();

    // =========================================================
    // Fermeture bandeau CTA
    // =========================================================
    (function () {
        var closeBtn = document.getElementById("cta-banner-close");
        var banner = document.getElementById("cta-banner");
        if (closeBtn && banner) {
            closeBtn.addEventListener("click", function () {
                banner.style.display = "none";
            });
        }
    })();

    // =========================================================
    // Bouton premium -> redirection
    // =========================================================
    (function () {
        var btn = document.getElementById("btn-premium");
        if (btn) {
            btn.addEventListener("click", function () {
                window.location.href = "/pricing";
            });
        }
    })();

    // =========================================================
    // API fetch
    // =========================================================

    /** Appel principal — GET /api/dashboard */
    function fetchDashboard() {
        var headers = { "Content-Type": "application/json" };
        var token = getToken();
        if (token) {
            headers["Authorization"] = "Bearer " + token;
        }

        fetch(API_BASE + "/api/dashboard", { method: "GET", headers: headers })
            .then(function (res) {
                if (!res.ok) throw new Error("HTTP " + res.status);
                return res.json();
            })
            .then(function (data) {
                renderDashboard(data);
                updateRefreshStatus(true);
            })
            .catch(function (_err) {
                updateRefreshStatus(false);
            });
    }

    // =========================================================
    // Rendering principal
    // =========================================================

    function renderDashboard(data) {
        if (!data) return;

        // Rafraichir le tier a chaque cycle
        userTier = getUserTier();

        updateLastUpdate();
        renderBotStatus(data);
        renderMarketContext(data);

        if (userTier === "premium") {
            unlockPanels();
            renderOrderFlow(data);
            renderOptionsGamma(data);
            renderIntermarket(data);
            renderSignals(data);
        }

        // Toast FOMO pour free users si signal detecte
        if (userTier !== "premium" && data.signals_journal) {
            var sj = data.signals_journal;
            if (sj.signal && sj.signal !== "HOLD") {
                showToast(sj.symbol || "ES", sj.signal, sj.time || "");
            }
        }
    }

    // =========================================================
    // Bot Status
    // =========================================================

    function renderBotStatus(data) {
        var badgeEl = document.getElementById("bot-running-badge");
        if (badgeEl) {
            if (data.bot_running) {
                badgeEl.className = "badge badge-green";
                badgeEl.innerHTML = '<span class="dot dot-green"></span> RUNNING';
            } else {
                badgeEl.className = "badge badge-red";
                badgeEl.innerHTML = '<span class="dot dot-red"></span> OFFLINE';
            }
        }

        setText("bot-global-status", data.bot_status || "--");
        if (data.bot_running) {
            var statusEl = document.getElementById("bot-global-status");
            if (statusEl) {
                statusEl.className = "kv-value text-green";
            }
        } else {
            var statusEl2 = document.getElementById("bot-global-status");
            if (statusEl2) {
                statusEl2.className = "kv-value text-red";
            }
        }

        setText("bot-heartbeat", data.bot_heartbeat || "--:--:--");

        if (data.es) renderInstrument("es", data.es);
        if (data.nq) renderInstrument("nq", data.nq);
    }

    function renderInstrument(sym, inst) {
        // Badge position
        var posEl = document.getElementById(sym + "-position");
        if (posEl) {
            if (inst.in_position) {
                var status = (inst.status || "").toUpperCase();
                if (status.indexOf("SHORT") !== -1) {
                    posEl.className = "badge badge-cyan";
                    posEl.textContent = "SHORT";
                } else if (status.indexOf("LONG") !== -1) {
                    posEl.className = "badge badge-cyan";
                    posEl.textContent = "LONG";
                } else {
                    posEl.className = "badge badge-cyan";
                    posEl.textContent = "IN POS";
                }
            } else {
                posEl.className = "badge badge-yellow";
                posEl.textContent = "FLAT";
            }
        }

        // P&L
        var pnlEl = document.getElementById(sym + "-pnl");
        if (pnlEl) {
            var pnl = parseFloat(inst.pnl);
            if (isNaN(pnl)) {
                pnlEl.textContent = "$0.00";
                pnlEl.className = "kv-value stat-neutral";
            } else {
                pnlEl.textContent = "$" + pnl.toFixed(2);
                pnlEl.className = "kv-value " + (pnl >= 0 ? "stat-positive" : "stat-negative");
            }
        }

        // Trades W/L
        var tradesEl = document.getElementById(sym + "-trades");
        if (tradesEl && inst.trades != null) {
            var w = inst.trades.wins || 0;
            var l = inst.trades.losses || 0;
            var total = inst.trades.total || (w + l);
            tradesEl.textContent = w + "W / " + l + "L (" + total + " total)";
        }
    }

    // =========================================================
    // Market Context
    // =========================================================

    function renderMarketContext(data) {
        var mc = data.market_context;
        if (!mc) return;

        // VIX
        if (mc.vix != null) {
            setText("mc-vix", parseFloat(mc.vix).toFixed(2));
        } else {
            setText("mc-vix", "--");
        }

        // Regime VIX
        var regimeEl = document.getElementById("mc-vix-regime");
        if (regimeEl && mc.vix_regime) {
            var regime = mc.vix_regime.toUpperCase();
            regimeEl.textContent = mc.vix_regime;
            regimeEl.classList.remove("stat-positive", "stat-negative", "stat-neutral");
            if (regime === "LOW") {
                regimeEl.classList.add("stat-positive");
            } else if (regime === "HIGH") {
                regimeEl.classList.add("stat-negative");
            } else {
                regimeEl.classList.add("stat-neutral");
            }
        }

        // ATR ES / NQ
        if (mc.atr_es != null || mc.atr_nq != null) {
            var atrEs = mc.atr_es != null ? parseFloat(mc.atr_es).toFixed(1) : "--";
            var atrNq = mc.atr_nq != null ? parseFloat(mc.atr_nq).toFixed(1) : "--";
            setText("mc-atr", atrEs + " / " + atrNq);
        }

        // VWAP Slope
        if (mc.vwap_slope_es != null || mc.vwap_slope_nq != null) {
            var vsEs = mc.vwap_slope_es != null ? parseFloat(mc.vwap_slope_es).toFixed(4) : "--";
            var vsNq = mc.vwap_slope_nq != null ? parseFloat(mc.vwap_slope_nq).toFixed(4) : "--";
            setText("mc-vwap-slope", vsEs + " / " + vsNq);
        }

        // Session
        setText("session-badge", mc.session_id || "PRE-MARKET");

        // Premium : Market Profile
        if (userTier === "premium" && mc.open_type_label) {
            setText("mc-open-type", mc.open_type_label);
            setText("mc-day-type", mc.day_type || "--");
            if (mc.ib_range != null) {
                setText("mc-ib-range", parseFloat(mc.ib_range).toFixed(1) + " ticks");
            }
            setText("mc-profile", mc.profile_shape || "--");
            if (mc.trend_prob != null) {
                setText("mc-trend-prob", parseFloat(mc.trend_prob).toFixed(0) + "%");
            }
            // Triple align
            var tripleEl = document.getElementById("mc-triple-align");
            if (tripleEl && mc.triple_align != null) {
                var ta = parseFloat(mc.triple_align);
                if (ta > 0) {
                    tripleEl.textContent = "BULL";
                    tripleEl.className = "kv-value stat-positive";
                } else if (ta < 0) {
                    tripleEl.textContent = "BEAR";
                    tripleEl.className = "kv-value stat-negative";
                } else {
                    tripleEl.textContent = "NEUTRE";
                    tripleEl.className = "kv-value stat-neutral";
                }
            }
        }
    }

    // =========================================================
    // Order Flow (premium)
    // =========================================================

    function renderOrderFlow(data) {
        var of = data.order_flow_es || data.order_flow_nq;
        if (!of) return;

        // Delta
        setColoredValue("of-delta", of.delta, 0);

        // CVD
        if (of.cvd != null) {
            var cvd = parseFloat(of.cvd);
            if (!isNaN(cvd)) {
                var cvdStr;
                if (Math.abs(cvd) >= 1000) {
                    cvdStr = (cvd / 1000).toFixed(1) + "K";
                } else {
                    cvdStr = cvd.toFixed(0);
                }
                if (cvd > 0) cvdStr = "+" + cvdStr;
                setText("of-cvd", cvdStr);
            } else {
                setText("of-cvd", "--");
            }
        } else {
            setText("of-cvd", "--");
        }

        // RVOL
        var rvol = parseFloat(of.rvol);
        if (!isNaN(rvol)) {
            setText("of-rvol", rvol.toFixed(2) + "x");

            // Gauge RVOL
            var rvolPct = Math.min((rvol / 5) * 100, 100);
            var rvolColor;
            if (rvol < 0.5) {
                rvolColor = "gauge-fill-red";
            } else if (rvol < 2.0) {
                rvolColor = "gauge-fill-cyan";
            } else if (rvol < 4.0) {
                rvolColor = "gauge-fill-green";
            } else {
                rvolColor = "gauge-fill-gold";
            }
            setGauge("of-rvol-gauge", rvolPct, rvolColor);

            // Badge regime RVOL
            var rvolBadge = document.getElementById("of-rvol-badge");
            if (rvolBadge) {
                rvolBadge.textContent = of.rvol_regime || "";
                if (rvol >= 3) {
                    rvolBadge.className = "badge badge-red";
                } else if (rvol >= 2) {
                    rvolBadge.className = "badge badge-yellow";
                } else {
                    rvolBadge.className = "badge badge-cyan";
                }
            }
        } else {
            setText("of-rvol", "--");
        }

        // Absorption
        setText("of-absorption", formatNum(of.absorption));

        // Divergence (coloree)
        setColoredValue("of-divergence", of.divergence != null ? of.divergence : null, 0);
        // Afficher texte si c'est un booleen/string
        if (of.divergence === true || of.divergence === "Oui") {
            var divEl = document.getElementById("of-divergence");
            if (divEl) {
                divEl.textContent = "Oui";
                divEl.className = "kv-value stat-negative";
            }
        } else if (of.divergence === false || of.divergence === "Non") {
            var divEl2 = document.getElementById("of-divergence");
            if (divEl2) {
                divEl2.textContent = "Non";
                divEl2.className = "kv-value stat-neutral";
            }
        }

        // Climax (colore)
        var climaxEl = document.getElementById("of-climax");
        if (climaxEl) {
            if (of.climax != null && of.climax !== "" && of.climax !== "--") {
                climaxEl.textContent = of.climax;
                climaxEl.className = "kv-value stat-negative";
            } else {
                climaxEl.textContent = "--";
                climaxEl.className = "kv-value stat-neutral";
            }
        }

        // LTR
        setText("of-ltr", formatNum(of.ltr));

        // Imbalance (colore)
        setColoredValue("of-imbalance", of.imbalance, 1.0);
    }

    // =========================================================
    // Options & Gamma (premium)
    // =========================================================

    function renderOptionsGamma(data) {
        var og = data.options_gamma_es || data.options_gamma_nq;
        if (!og) return;

        // Call / Put walls
        setColoredValue("og-call", og.call_wall, 0, " ticks");
        setColoredValue("og-put", og.put_wall, 0, " ticks");

        // HVL
        setText("og-hvl", og.hvl != null ? formatNum(og.hvl) + " ticks" : "--");

        // 0DTE
        setText("og-0dte-call", og.dte0_call != null ? formatNum(og.dte0_call) + " ticks" : "--");
        setText("og-0dte-put", og.dte0_put != null ? formatNum(og.dte0_put) + " ticks" : "--");

        // GEX
        setText("og-gex-up", og.gex_up != null ? formatNum(og.gex_up) + " ticks" : "--");
        setText("og-gex-dn", og.gex_dn != null ? formatNum(og.gex_dn) + " ticks" : "--");
        setText("og-gex-count", og.gex_count != null ? og.gex_count : "--");

        // GEX Flip
        var flipEl = document.getElementById("og-gex-flip");
        if (flipEl) {
            if (og.gex_flip === true || og.gex_flip === "OUI") {
                flipEl.textContent = "OUI";
                flipEl.className = "kv-value stat-negative";
            } else {
                flipEl.textContent = "NON";
                flipEl.className = "kv-value stat-neutral";
            }
        }

        // VIX
        setText("og-vix", og.vix != null ? parseFloat(og.vix).toFixed(1) : "--");
    }

    // =========================================================
    // Intermarket + AMD
    // =========================================================

    function renderIntermarket(data) {
        if (!data.intermarket) return;
        var im = data.intermarket;

        // Correlation
        var corrEl = document.getElementById("im-corr");
        if (corrEl && im.correlation != null) {
            var corr = parseFloat(im.correlation);
            corrEl.textContent = corr.toFixed(3);
            corrEl.classList.remove("stat-positive", "stat-negative", "stat-neutral");
            if (corr < 0.80) {
                corrEl.classList.add("stat-negative");
            } else {
                corrEl.classList.add("stat-positive");
            }
        }

        // Delta agreement + gauge
        if (im.delta_agree != null) {
            var agree = parseFloat(im.delta_agree);
            var agreeEl = document.getElementById("im-delta-agree");
            if (agreeEl) {
                agreeEl.textContent = agree.toFixed(2);
            }
            // Gauge
            var agreePct = agree * 100;
            var agreeColor;
            if (agree < 0.4) {
                agreeColor = "gauge-fill-red";
            } else if (agree > 0.8) {
                agreeColor = "gauge-fill-green";
            } else {
                agreeColor = "gauge-fill-cyan";
            }
            setGauge("im-agree-gauge", agreePct, agreeColor);
        }

        // SMT Divergence
        var smtEl = document.getElementById("im-smt");
        if (smtEl && im.smt != null) {
            var smt = parseFloat(im.smt);
            smtEl.classList.remove("stat-positive", "stat-negative", "stat-neutral");
            if (smt > 0) {
                smtEl.textContent = "BULL TRAP";
                smtEl.classList.add("stat-negative");
            } else if (smt < 0) {
                smtEl.textContent = "BEAR TRAP";
                smtEl.classList.add("stat-negative");
            } else {
                smtEl.textContent = "AUCUNE";
                smtEl.classList.add("stat-neutral");
            }
        }

        // Badge AMD phase (toujours visible)
        setText("amd-phase-badge", im.amd_phase || "Accumulation");

        // Premium : details AMD
        if (userTier === "premium") {
            setText("im-amd-phase", im.amd_phase || "--");

            // Bias colore
            var biasEl = document.getElementById("im-bias");
            if (biasEl && im.bias != null) {
                biasEl.textContent = im.bias;
                biasEl.classList.remove("stat-positive", "stat-negative", "stat-neutral");
                var biasUpper = String(im.bias).toUpperCase();
                if (biasUpper.indexOf("BULL") !== -1 || biasUpper.indexOf("LONG") !== -1) {
                    biasEl.classList.add("stat-positive");
                } else if (biasUpper.indexOf("BEAR") !== -1 || biasUpper.indexOf("SHORT") !== -1) {
                    biasEl.classList.add("stat-negative");
                } else {
                    biasEl.classList.add("stat-neutral");
                }
            }

            setText("im-po3", formatNum(im.po3));

            // Judas
            var judasEl = document.getElementById("im-judas");
            if (judasEl) {
                if (im.judas) {
                    judasEl.textContent = "DETECTE";
                    judasEl.className = "kv-value stat-negative";
                } else {
                    judasEl.textContent = "NON";
                    judasEl.className = "kv-value stat-neutral";
                }
            }

            setText("im-manip", formatNum(im.manip));
        }
    }

    // =========================================================
    // Signaux & Journal (premium)
    // =========================================================

    function renderSignals(data) {
        if (!data.signals_journal) return;
        var sj = data.signals_journal;

        // Signal actuel
        var sigEl = document.getElementById("sig-current");
        if (sigEl && sj.signal) {
            sigEl.textContent = sj.signal;
            sigEl.classList.remove("stat-positive", "stat-negative", "stat-neutral");
            var sigUpper = sj.signal.toUpperCase();
            if (sigUpper === "BUY") {
                sigEl.classList.add("stat-positive");
            } else if (sigUpper === "SELL") {
                sigEl.classList.add("stat-negative");
            } else {
                sigEl.classList.add("stat-neutral");
            }
        }

        setText("sig-score", formatNum(sj.score));
        setText("sig-sltp", sj.sltp || "-- / --");
        setText("sig-rr", sj.rr != null ? sj.rr : "--");
        setText("sig-reason", sj.reason || "--");

        // Tableau trades
        var tbody = document.getElementById("sig-trades-body");
        if (tbody && sj.trades && sj.trades.length > 0) {
            tbody.innerHTML = "";
            for (var i = 0; i < sj.trades.length; i++) {
                var t = sj.trades[i];
                var tr = document.createElement("tr");

                var tdTime = document.createElement("td");
                tdTime.textContent = t.time || "--";
                tr.appendChild(tdTime);

                var tdSym = document.createElement("td");
                tdSym.textContent = t.symbol || "--";
                tr.appendChild(tdSym);

                var tdDir = document.createElement("td");
                tdDir.textContent = t.direction || "--";
                tr.appendChild(tdDir);

                var tdPnl = document.createElement("td");
                var tPnl = parseFloat(t.pnl);
                tdPnl.textContent = isNaN(tPnl) ? "--" : "$" + tPnl.toFixed(2);
                tdPnl.className = isNaN(tPnl) ? "" : (tPnl >= 0 ? "stat-positive" : "stat-negative");
                tr.appendChild(tdPnl);

                tbody.appendChild(tr);
            }
        }
    }

    // =========================================================
    // Toast alertes (FOMO pour free users)
    // =========================================================

    function showToast(symbol, direction, time) {
        if (userTier === "premium") return;

        var container = document.getElementById("toast-container");
        if (!container) return;

        var toast = document.createElement("div");
        toast.className = "toast " + (direction === "BUY" ? "toast-buy" : "toast-sell");

        var dotClass = direction === "BUY" ? "dot-green" : "dot-red";
        var dirLabel = direction === "BUY" ? "BUY" : "SELL";
        var timeStr = time || new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

        toast.innerHTML =
            '<span class="dot ' + dotClass + '"></span> ' +
            "Signal " + dirLabel + " " + symbol + " detecte \u2014 " + timeStr +
            ' <a href="/pricing" class="toast-link">Details \u2192</a>';

        container.appendChild(toast);

        // Auto-suppression apres 8 secondes
        setTimeout(function () {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 8000);
    }

    // =========================================================
    // Newsletter
    // =========================================================

    function setupNewsletter() {
        var btn = document.getElementById("newsletter-btn");
        var emailInput = document.getElementById("newsletter-email");
        var msgEl = document.getElementById("newsletter-msg");
        if (!btn || !emailInput) return;

        btn.addEventListener("click", function (e) {
            e.preventDefault();
            var email = emailInput.value.trim();
            if (!email || email.indexOf("@") === -1) {
                if (msgEl) {
                    msgEl.textContent = "Adresse email invalide.";
                    msgEl.style.color = "var(--red)";
                }
                return;
            }

            // Envoi vers webhook Discord
            var payload = {
                embeds: [{
                    title: "Nouvel abonne Newsletter Dashboard",
                    description: email,
                    color: 16766720 // or (#FFD700)
                }]
            };

            fetch(DISCORD_WEBHOOK_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            })
            .then(function (res) {
                if (res.ok || res.status === 204) {
                    if (msgEl) {
                        msgEl.textContent = "Inscription reussie !";
                        msgEl.style.color = "var(--green)";
                    }
                    emailInput.value = "";
                } else {
                    throw new Error("HTTP " + res.status);
                }
            })
            .catch(function (_err) {
                if (msgEl) {
                    msgEl.textContent = "Erreur lors de l'inscription. Reessayez.";
                    msgEl.style.color = "var(--red)";
                }
            });
        });
    }

    // =========================================================
    // Briefing preview
    // =========================================================

    function fetchBriefingPreview() {
        var headers = { "Content-Type": "application/json" };
        var token = getToken();
        if (token) {
            headers["Authorization"] = "Bearer " + token;
        }

        fetch(API_BASE + "/api/briefing/today", { method: "GET", headers: headers })
            .then(function (res) {
                if (!res.ok) throw new Error("HTTP " + res.status);
                return res.json();
            })
            .then(function (data) {
                // Preview briefing
                var previewEl = document.getElementById("briefing-preview");
                if (previewEl && data) {
                    var vix = data.vix != null ? parseFloat(data.vix).toFixed(2) : "--";
                    var regime = data.regime || "--";
                    var desc = data.description || "";
                    previewEl.textContent = "VIX " + vix + " (" + regime + ") \u2014 " + desc;
                }

                // Date du bandeau
                var bannerDate = document.getElementById("banner-date");
                if (bannerDate) {
                    var now = new Date();
                    var dd = String(now.getDate()).padStart(2, "0");
                    var mmDate = String(now.getMonth() + 1).padStart(2, "0");
                    bannerDate.textContent = dd + "/" + mmDate;
                }
            })
            .catch(function (_err) {
                // Silencieux — le briefing n'est pas critique
            });
    }

    // =========================================================
    // Initialisation
    // =========================================================

    function init() {
        userTier = getUserTier();

        // Premier fetch immediat
        fetchDashboard();

        // Polling toutes les 5 secondes
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(fetchDashboard, POLL_INTERVAL);

        // Newsletter
        setupNewsletter();

        // Briefing preview
        fetchBriefingPreview();
    }

    // Lancement
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();
