/**
 * dashboard.js — MIA Dashboard V2
 * Polling 5s + rendering 6 pages + selecteur ES/NQ/Both
 */
(function () {
    "use strict";

    var API_BASE = window.location.origin;
    var POLL_INTERVAL = 5000;
    var POLL_INTERVAL_OFF_HOURS = 30000; // 30s hors session US
    var currentPage = "overview";
    var currentInstrument = "ES";
    var currentLevelFilter = "ALL";
    var data = null;
    var pollTimer = null;
    var authToken = localStorage.getItem("mia_token") || "";
    var currentTier = localStorage.getItem("mia_tier") || "free";

    // ═══════════════════════════════════════════════════════════════
    // Helpers
    // ═══════════════════════════════════════════════════════════════

    function $(id) { return document.getElementById(id); }
    function setHTML(el, html) { if (el && el.innerHTML !== html) el.innerHTML = html; }
    function fmt(v, d) { return v != null ? Number(v).toFixed(d || 2) : "--"; }
    function fmtPrice(v) { return v != null ? Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "--"; }
    function fmtInt(v) { return v != null ? Math.round(Number(v)).toLocaleString("en-US") : "--"; }
    function fmtPct(v) { return v != null ? (Number(v) * 100).toFixed(1) + "%" : "--"; }

    function colorClass(val, pos, neg) {
        if (val > 0) return pos || "green";
        if (val < 0) return neg || "red";
        return "";
    }

    function biasClass(bias) {
        if (bias === "BULLISH") return "bull";
        if (bias === "BEARISH") return "bear";
        return "neutral";
    }

    function modeClass(mode) {
        if (mode === "TREND") return "trend";
        if (mode === "RANGE") return "range";
        return "neutral";
    }

    // ═══════════════════════════════════════════════════════════════
    // SVG Visual Components
    // ═══════════════════════════════════════════════════════════════

    /**
     * Jauge semi-circulaire SVG
     * @param {number} value - Valeur actuelle
     * @param {number} min - Min de l'echelle
     * @param {number} max - Max de l'echelle
     * @param {string} label - Label sous la valeur
     * @param {string} color - Couleur de la jauge
     * @param {string} unit - Unite (%, t, x, etc.)
     * @param {number} size - Taille en px (defaut 120)
     */
    function svgGauge(value, min, max, label, color, unit, size, tooltip) {
        size = size || 140;
        var W = size, H = size * 0.82;
        var cx = W / 2, cy = H * 0.52;
        var r = size * 0.32;
        var strokeW = size * 0.055;
        var pct = Math.max(0, Math.min(1, (value - min) / (max - min)));
        var displayVal;
        if (unit === "%") { displayVal = (value * 100).toFixed(0) + "%"; }
        else if (unit === "pct") { displayVal = Math.round(value) + "%"; }
        else if (unit === "x") { displayVal = Number(value).toFixed(2) + "x"; }
        else { displayVal = Number(value).toFixed(1) + (unit || ""); }

        // Arc 240 degrees (-210 to +30)
        var startAngle = -210 * Math.PI / 180;
        var endAngle = 30 * Math.PI / 180;
        var totalArc = endAngle - startAngle;
        var valAngle = startAngle + pct * totalArc;

        function ap(angle, radius) {
            var rr = radius || r;
            return { x: cx + rr * Math.cos(angle), y: cy + rr * Math.sin(angle) };
        }
        var pStart = ap(startAngle);
        var pEnd = ap(endAngle);
        var pVal = ap(valAngle);

        var bgPath = "M " + pStart.x + " " + pStart.y + " A " + r + " " + r + " 0 1 1 " + pEnd.x + " " + pEnd.y;
        var largeArc = (pct * totalArc) > Math.PI ? 1 : 0;
        var valPath = "M " + pStart.x + " " + pStart.y + " A " + r + " " + r + " 0 " + largeArc + " 1 " + pVal.x + " " + pVal.y;

        // Needle — fine, avec pointe
        var needleLen = r * 0.78;
        var nTip = ap(valAngle, needleLen);
        var nPerp1 = valAngle + Math.PI / 2;
        var nPerp2 = valAngle - Math.PI / 2;
        var nB1 = { x: cx + 2.5 * Math.cos(nPerp1), y: cy + 2.5 * Math.sin(nPerp1) };
        var nB2 = { x: cx + 2.5 * Math.cos(nPerp2), y: cy + 2.5 * Math.sin(nPerp2) };

        // Ticks (5 graduations + valeurs intermediaires)
        var ticks = "";
        for (var i = 0; i <= 8; i++) {
            var ta = startAngle + (i / 8) * totalArc;
            var isMajor = (i % 2 === 0);
            var tLen = isMajor ? strokeW * 1.0 : strokeW * 0.5;
            var tOuter = ap(ta, r + tLen);
            var tInner = ap(ta, r - (isMajor ? 1 : 0));
            ticks += '<line x1="' + tInner.x + '" y1="' + tInner.y + '" x2="' + tOuter.x + '" y2="' + tOuter.y + '" stroke="rgba(255,255,255,' + (isMajor ? '0.2' : '0.08') + ')" stroke-width="' + (isMajor ? '1.5' : '1') + '"/>';
        }

        // Valeurs min/max aux extremites
        var minPos = ap(startAngle, r + strokeW * 1.6);
        var maxPos = ap(endAngle, r + strokeW * 1.6);

        var fs = size * 0.16;
        var ls = size * 0.078;
        var valY = cy + r * 0.45;
        var labelY = valY + fs * 0.85;
        var uid = label.replace(/[^a-zA-Z]/g, '') + Math.random().toString(36).substr(2, 4);

        return '<div class="gauge-wrap">' +
            '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '">' +
            '<defs><filter id="g' + uid + '"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>' +
            // BG arc
            '<path d="' + bgPath + '" fill="none" stroke="rgba(255,255,255,0.05)" stroke-width="' + (strokeW + 2) + '" stroke-linecap="round"/>' +
            // Ticks
            ticks +
            // Value arc
            (pct > 0.01 ? '<path d="' + valPath + '" fill="none" stroke="' + color + '" stroke-width="' + strokeW + '" stroke-linecap="round" filter="url(#g' + uid + ')"/>' : '') +
            // Center circle
            '<circle cx="' + cx + '" cy="' + cy + '" r="4" fill="#1e293b" stroke="' + color + '" stroke-width="1.5"/>' +
            // Needle
            '<polygon points="' + nTip.x.toFixed(1) + ',' + nTip.y.toFixed(1) + ' ' + nB1.x.toFixed(1) + ',' + nB1.y.toFixed(1) + ' ' + nB2.x.toFixed(1) + ',' + nB2.y.toFixed(1) + '" fill="' + color + '" opacity="0.9"/>' +
            // Value
            '<text x="' + cx + '" y="' + valY + '" text-anchor="middle" fill="' + color + '" font-family="JetBrains Mono,monospace" font-weight="800" font-size="' + fs + '">' + displayVal + '</text>' +
            // Label
            '<text x="' + cx + '" y="' + labelY + '" text-anchor="middle" fill="#94a3b8" font-family="Inter,sans-serif" font-weight="600" font-size="' + ls + '">' + label.toUpperCase() + '</text>' +
            // Min
            '<text x="' + minPos.x.toFixed(1) + '" y="' + (minPos.y + 3).toFixed(1) + '" text-anchor="middle" fill="#475569" font-family="JetBrains Mono,monospace" font-size="' + (ls * 0.85) + '">' + min + '</text>' +
            // Max
            '<text x="' + maxPos.x.toFixed(1) + '" y="' + (maxPos.y + 3).toFixed(1) + '" text-anchor="middle" fill="#475569" font-family="JetBrains Mono,monospace" font-size="' + (ls * 0.85) + '">' + max + '</text>' +
            '</svg>' +
            (tooltip ? '<div class="gauge-info" title="' + tooltip.replace(/"/g, "'") + '">i</div>' : '') +
            '</div>';
    }

    /**
     * Barre de corridor visuel (prix entre deux murs)
     * @param {number} putPrice - Mur put (support)
     * @param {number} callPrice - Mur call (resistance)
     * @param {number} price - Prix actuel
     * @param {number} hvl - HVL (milieu)
     */
    function corridorBar(putPrice, callPrice, price, hvl) {
        if (!putPrice || !callPrice || !price) return "";
        var range = callPrice - putPrice;
        if (range <= 0) return "";
        var pricePct = Math.max(0, Math.min(100, ((price - putPrice) / range) * 100));
        var hvlPct = hvl ? Math.max(0, Math.min(100, ((hvl - putPrice) / range) * 100)) : null;
        var distPut = Math.round((price - putPrice) / 0.25);
        var distCall = Math.round((callPrice - price) / 0.25);
        var rangeTicks = Math.round(range / 0.25);

        // Interpretation
        var zone, zoneColor, zoneBg, zoneEmoji, advice;
        if (pricePct >= 80) {
            zone = "PRES DU MUR CALL"; zoneColor = "#ff5252"; zoneBg = "rgba(255,82,82,0.12)"; zoneEmoji = "&#9660;";
            advice = "Le prix touche la resistance des market makers. Forte probabilite de rejet vers le bas.";
        } else if (pricePct >= 60) {
            zone = "MOITIE HAUTE"; zoneColor = "#ff9800"; zoneBg = "rgba(255,152,0,0.10)"; zoneEmoji = "&#9660;";
            advice = "Le hedging des calls freine la hausse. Biais legerement baissier.";
        } else if (pricePct >= 40) {
            zone = "ZONE NEUTRE"; zoneColor = "#00b4dc"; zoneBg = "rgba(0,180,220,0.10)"; zoneEmoji = "&#9644;";
            advice = "Equilibre entre acheteurs et vendeurs. Pas de pression gamma directionnelle.";
        } else if (pricePct >= 20) {
            zone = "MOITIE BASSE"; zoneColor = "#00c853"; zoneBg = "rgba(0,200,83,0.10)"; zoneEmoji = "&#9650;";
            advice = "Les puts soutiennent le prix. Biais legerement haussier.";
        } else {
            zone = "PRES DU MUR PUT"; zoneColor = "#00c853"; zoneBg = "rgba(0,200,83,0.12)"; zoneEmoji = "&#9650;";
            advice = "Le prix touche le support des market makers. Forte probabilite de rebond vers le haut.";
        }

        var h = '';

        // ── Visual bar with 5 colored zones ──
        h += '<div style="position:relative;height:56px;margin:0 0 6px;">';
        // 5 zones background
        h += '<div style="position:absolute;top:20px;left:0;width:20%;height:16px;background:rgba(0,200,83,0.2);border-radius:8px 0 0 8px;"></div>';
        h += '<div style="position:absolute;top:20px;left:20%;width:20%;height:16px;background:rgba(0,200,83,0.08);"></div>';
        h += '<div style="position:absolute;top:20px;left:40%;width:20%;height:16px;background:rgba(0,180,220,0.10);"></div>';
        h += '<div style="position:absolute;top:20px;left:60%;width:20%;height:16px;background:rgba(255,152,0,0.08);"></div>';
        h += '<div style="position:absolute;top:20px;left:80%;width:20%;height:16px;background:rgba(255,82,82,0.2);border-radius:0 8px 8px 0;"></div>';
        // Borders
        h += '<div style="position:absolute;top:20px;left:0;right:0;height:16px;border:1px solid rgba(255,255,255,0.08);border-radius:8px;"></div>';
        // Zone labels top
        h += '<div style="position:absolute;top:4px;left:2px;font-size:0.5rem;color:var(--green);font-weight:700;">PUT WALL</div>';
        h += '<div style="position:absolute;top:4px;left:50%;transform:translateX(-50%);font-size:0.5rem;color:var(--cyan);font-weight:700;">NEUTRE</div>';
        h += '<div style="position:absolute;top:4px;right:2px;font-size:0.5rem;color:var(--red);font-weight:700;">CALL WALL</div>';
        // Put wall line
        h += '<div style="position:absolute;left:0;top:16px;width:3px;height:24px;background:var(--green);border-radius:2px;"></div>';
        // Call wall line
        h += '<div style="position:absolute;right:0;top:16px;width:3px;height:24px;background:var(--red);border-radius:2px;"></div>';
        // HVL
        if (hvlPct != null) {
            h += '<div style="position:absolute;left:' + hvlPct + '%;top:16px;width:2px;height:24px;background:var(--cyan);transform:translateX(-1px);opacity:0.7;"></div>';
        }
        // Price marker — gold dot + line
        h += '<div style="position:absolute;left:' + pricePct + '%;top:12px;transform:translateX(-50%);z-index:3;">';
        h += '<div style="width:14px;height:14px;background:#d4af37;border-radius:50%;border:2px solid #0a0e17;box-shadow:0 0 10px rgba(212,175,55,0.5);margin:0 auto;"></div>';
        h += '<div style="width:2px;height:18px;background:#d4af37;margin:0 auto;"></div>';
        h += '</div>';
        // Price label below
        h += '<div style="position:absolute;left:' + pricePct + '%;top:44px;transform:translateX(-50%);font-size:0.625rem;font-family:var(--font-mono);color:#d4af37;font-weight:700;white-space:nowrap;">' + fmtPrice(price) + '</div>';
        h += '</div>';

        // ── Result box ──
        h += '<div style="display:flex;align-items:stretch;gap:8px;margin-top:8px;">';

        // Left — verdict
        h += '<div style="flex:1;text-align:center;padding:10px;background:' + zoneBg + ';border:1px solid ' + zoneColor + '30;border-radius:8px;">';
        h += '<div style="font-size:1.5rem;line-height:1;">' + zoneEmoji + '</div>';
        h += '<div style="font-size:1rem;font-weight:800;color:' + zoneColor + ';margin:4px 0;">' + zone + '</div>';
        h += '<div style="font-size:0.6875rem;color:var(--text-secondary);line-height:1.3;">' + advice + '</div>';
        h += '</div>';

        // Right — numbers
        h += '<div style="display:flex;flex-direction:column;gap:6px;min-width:140px;">';
        // Put distance
        h += '<div style="background:rgba(0,200,83,0.06);border:1px solid rgba(0,200,83,0.15);border-radius:6px;padding:6px 8px;display:flex;justify-content:space-between;align-items:center;">';
        h += '<div style="font-size:0.625rem;color:var(--green);">PUT WALL</div>';
        h += '<div class="mono" style="font-size:0.75rem;color:var(--green);font-weight:700;">+' + distPut + 't</div>';
        h += '</div>';
        // Position
        h += '<div style="background:rgba(212,175,55,0.06);border:1px solid rgba(212,175,55,0.15);border-radius:6px;padding:6px 8px;text-align:center;">';
        h += '<div style="font-size:0.5625rem;color:var(--text-disabled);">POSITION</div>';
        h += '<div class="mono" style="font-size:1.25rem;font-weight:800;color:' + zoneColor + ';">' + pricePct.toFixed(0) + '%</div>';
        h += '</div>';
        // Call distance
        h += '<div style="background:rgba(255,82,82,0.06);border:1px solid rgba(255,82,82,0.15);border-radius:6px;padding:6px 8px;display:flex;justify-content:space-between;align-items:center;">';
        h += '<div style="font-size:0.625rem;color:var(--red);">CALL WALL</div>';
        h += '<div class="mono" style="font-size:0.75rem;color:var(--red);font-weight:700;">-' + distCall + 't</div>';
        h += '</div>';
        h += '</div>';

        h += '</div>';

        // Footer
        h += '<div style="display:flex;justify-content:space-between;margin-top:6px;font-size:0.5625rem;color:var(--text-disabled);">';
        h += '<span>' + fmtPrice(putPrice) + '</span>';
        h += '<span>Corridor : ' + rangeTicks + 't</span>';
        h += '<span>' + fmtPrice(callPrice) + '</span>';
        h += '</div>';
        return h;
    }

    /**
     * Echelle VWAP visuelle — position du prix dans les SD bands
     */
    function vwapLadder(price, bands) {
        if (!price || !bands || !bands.vwap) return "";
        var items = [
            { label: "SD3+", price: bands.sd3u, color: "var(--red)" },
            { label: "SD2+", price: bands.sd2u, color: "var(--orange)" },
            { label: "SD1+", price: bands.sd1u, color: "var(--text-secondary)" },
            { label: "VWAP", price: bands.vwap, color: "var(--cyan)" },
            { label: "SD1-", price: bands.sd1d, color: "var(--text-secondary)" },
            { label: "SD2-", price: bands.sd2d, color: "var(--orange)" },
            { label: "SD3-", price: bands.sd3d, color: "var(--green)" },
        ];
        var h = '<div style="position:relative;padding:4px 0;">';
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (!item.price) continue;
            var isActive = (i === 0 && price >= item.price) ||
                (i === items.length - 1 && price <= item.price) ||
                (i > 0 && i < items.length - 1 && items[i - 1].price && price < items[i - 1].price && price >= item.price);
            h += '<div style="display:flex;align-items:center;gap:10px;padding:3px 0;' + (isActive ? 'background:rgba(212,175,55,0.1);border-radius:4px;padding:5px 8px;margin:0 -8px;' : '') + '">';
            h += '<span style="width:40px;font-size:0.6875rem;font-weight:600;color:' + item.color + ';">' + item.label + '</span>';
            h += '<div style="flex:1;height:2px;background:' + item.color + ';opacity:0.3;"></div>';
            h += '<span class="mono" style="font-size:0.75rem;font-weight:' + (isActive ? '700' : '500') + ';color:' + (isActive ? 'var(--gold)' : item.color) + ';">' + fmtPrice(item.price) + '</span>';
            if (isActive) h += '<span style="font-size:0.625rem;color:var(--gold);">&#9668; PRIX</span>';
            h += '</div>';
        }
        h += '</div>';
        return h;
    }

    /**
     * Barre horizontale coloree avec valeur
     */
    function hBar(label, value, max, color, displayVal) {
        var pct = max > 0 ? Math.min(100, Math.abs(value) / max * 100) : 0;
        return '<div style="margin:6px 0;">' +
            '<div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:2px;">' +
            '<span style="color:var(--text-secondary);">' + label + '</span>' +
            '<span class="mono" style="color:' + color + ';font-weight:600;">' + (displayVal || fmt(value, 0)) + '</span></div>' +
            '<div class="gauge"><div class="gauge-fill" style="width:' + pct + '%;background:' + color + ';"></div></div></div>';
    }

    // ═══════════════════════════════════════════════════════════════
    // Chart Module (TradingView Lightweight Charts)
    // ═══════════════════════════════════════════════════════════════

    var chart = null;
    var candleSeries = null;
    var volumeSeries = null;
    var deltaSeries = null;
    var chartLines = [];
    var chartSymbol = null;
    var chartTf = 1;

    function initChart() {
        if (!window.LightweightCharts) return;
        var container = $("chart-container");
        if (!container) return;

        chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 450,
            layout: {
                background: { type: "solid", color: "#0a0e17" },
                textColor: "#94a3b8",
                fontSize: 11,
                fontFamily: "JetBrains Mono, monospace",
            },
            grid: {
                vertLines: { color: "rgba(255,255,255,0.03)" },
                horzLines: { color: "rgba(255,255,255,0.03)" },
            },
            crosshair: {
                mode: 0,
                vertLine: { color: "rgba(0,180,220,0.3)", labelBackgroundColor: "#0d1321" },
                horzLine: { color: "rgba(0,180,220,0.3)", labelBackgroundColor: "#0d1321" },
            },
            rightPriceScale: {
                borderColor: "rgba(255,255,255,0.06)",
                scaleMargins: { top: 0.1, bottom: 0.1 },
            },
            timeScale: {
                borderColor: "rgba(255,255,255,0.06)",
                timeVisible: true,
                secondsVisible: false,
            },
        });

        candleSeries = chart.addCandlestickSeries({
            upColor: "#00c853",
            downColor: "#ff5252",
            borderUpColor: "#00c853",
            borderDownColor: "#ff5252",
            wickUpColor: "#00c853",
            wickDownColor: "#ff5252",
        });

        // Volume histogram (sous les bougies)
        volumeSeries = chart.addHistogramSeries({
            priceFormat: { type: "volume" },
            priceScaleId: "vol",
        });
        chart.priceScale("vol").applyOptions({
            scaleMargins: { top: 0.85, bottom: 0 },
        });

        // Delta histogram
        deltaSeries = chart.addHistogramSeries({
            priceFormat: { type: "volume" },
            priceScaleId: "delta",
        });
        chart.priceScale("delta").applyOptions({
            scaleMargins: { top: 0.65, bottom: 0.18 },
        });

        // Resize observer
        var ro = new ResizeObserver(function () {
            chart.applyOptions({ width: container.clientWidth });
        });
        ro.observe(container);
    }

    // ─── Level filter ───
    var ESSENTIAL_GROUPS = ["options", "vwap", "sd12", "sd3", "profile", "prev", "swing", "session", "ib", "ovn", "gex", "0dte"];
    var savedGroups = JSON.parse(localStorage.getItem("mia_level_groups") || "null");
    var levelGroups = (savedGroups && savedGroups.length >= 8) ? savedGroups : ESSENTIAL_GROUPS.slice();
    var rawLevels = [];

    function isGroupActive(grp) { return levelGroups.indexOf(grp) >= 0; }

    function applyLevelFilter() {
        if (!chart || !candleSeries) return;
        chartLines.forEach(function (l) { candleSeries.removePriceLine(l); });
        chartLines = [];
        rawLevels.forEach(function (lvl) {
            if (!isGroupActive(lvl.group)) return;
            var lineStyle = lvl.style === "dashed" ? 1 : 0;
            var line = candleSeries.createPriceLine({
                price: lvl.price,
                color: lvl.color,
                lineWidth: lvl.title.indexOf("WALL") >= 0 || lvl.title === "VPOC" || lvl.title === "HVL" ? 2 : 1,
                lineStyle: lineStyle,
                axisLabelVisible: true,
                title: lvl.title,
            });
            chartLines.push(line);
        });
    }

    function saveLevelGroups() {
        localStorage.setItem("mia_level_groups", JSON.stringify(levelGroups));
    }

    function loadChart(symbol) {
        if (!chart || !candleSeries) return;
        symbol = symbol || "ES";
        if (symbol === "BOTH") symbol = "ES";

        $("chart-symbol-label").textContent = symbol;
        $("chart-symbol-label").className = "badge " + (symbol === "ES" ? "badge-green" : "badge-cyan");

        var savedRange = null;
        try { savedRange = chart.timeScale().getVisibleLogicalRange(); } catch (e) {}

        fetch(API_BASE + "/api/bars/" + symbol + "?n=" + Math.max(300, 60 * chartTf) + "&tf=" + chartTf, { headers: apiHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.bars || !d.bars.length) return;
                candleSeries.setData(d.bars);

                if (volumeSeries) {
                    volumeSeries.setData(d.bars.map(function (b) {
                        return { time: b.time, value: b.volume || 0, color: b.close >= b.open ? "rgba(0,200,83,0.3)" : "rgba(255,82,82,0.3)" };
                    }));
                }
                if (deltaSeries) {
                    deltaSeries.setData(d.bars.map(function (b) {
                        var delta = b.delta || 0;
                        return { time: b.time, value: delta, color: delta >= 0 ? "rgba(0,200,83,0.6)" : "rgba(255,82,82,0.6)" };
                    }));
                }

                rawLevels = d.levels || [];
                applyLevelFilter();

                if (savedRange && chartSymbol === symbol) {
                    try { chart.timeScale().setVisibleLogicalRange(savedRange); } catch (e) {}
                } else {
                    chart.timeScale().fitContent();
                }
                chartSymbol = symbol;
            })
            .catch(function (err) { console.error("Chart load error:", err); });
    }

    var lastClosePrice = null;

    function updateChartBar() {
        if (!chart || !candleSeries || !data || !data.banner) return;
        var sym = chartSymbol || "ES";
        var b = data.banner[sym.toLowerCase()];
        if (!b || !b.ts) return;
        var openPrice = lastClosePrice || b.price;
        candleSeries.update({
            time: Math.floor(b.ts / 1000),
            open: openPrice,
            high: b.bar_high,
            low: b.bar_low,
            close: b.price,
        });
        if (volumeSeries && b.total_vol) {
            volumeSeries.update({ time: Math.floor(b.ts / 1000), value: b.total_vol || 0, color: b.price >= (lastClosePrice || b.price) ? "rgba(0,200,83,0.3)" : "rgba(255,82,82,0.3)" });
        }
        lastClosePrice = b.price;
    }

    function kvRow(key, val, cls) {
        return '<div class="kv-row"><span class="kv-key">' + key + '</span><span class="kv-value ' + (cls || "") + '">' + val + '</span></div>';
    }

    function badgeHtml(text, cls) {
        return '<span class="badge ' + cls + '">' + text + '</span>';
    }

    function boolBadge(val, yesText, noText) {
        return val ? badgeHtml(yesText || "Oui", "badge-green") : badgeHtml(noText || "Non", "badge-gray");
    }

    // ═══════════════════════════════════════════════════════════════
    // Navigation
    // ═══════════════════════════════════════════════════════════════

    function initNav() {
        var links = document.querySelectorAll(".sidebar-nav a[data-page]");
        links.forEach(function (a) {
            a.addEventListener("click", function (e) {
                e.preventDefault();
                var page = a.getAttribute("data-page");
                if (!page) return;

                // Intercept tier-locked nav : ouvre modal au lieu de naviguer
                var required = parseInt(a.getAttribute("data-tier-min") || "0", 10);
                if (required > getTierLevel()) {
                    showPageLockModal(page);
                    return;
                }
                switchPage(page);
            });
        });

        // VP Zoom buttons
        document.querySelectorAll(".vp-zoom-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var target = btn.getAttribute("data-target");
                var action = btn.getAttribute("data-action");
                var st = vpCanvasState[target];
                if (!st) return;
                if (action === "in") {
                    st.zoom = Math.min(10, st.zoom * 1.3);
                    st.initialized = false; // re-centrer sur POC apres zoom
                } else if (action === "out") {
                    st.zoom = Math.max(0.5, st.zoom * 0.7);
                    st.initialized = false; // re-centrer sur POC apres zoom
                } else if (action === "fit") {
                    st.initialized = false;
                    st.zoomInitDone = false; // FIT = recalcul zoom from scratch
                }
                drawVolumeProfileCanvas(target, st.profile, st.levels);
            });
        });

        // Timeframe selector
        var tfBtns = document.querySelectorAll(".tf-btn[data-tf]");
        tfBtns.forEach(function (btn) {
            btn.addEventListener("click", function () {
                chartTf = parseInt(btn.getAttribute("data-tf")) || 1;
                signalsChartsLoaded = false;
                levelsChartsLoaded = false;
                tfBtns.forEach(function (b) { b.classList.remove("active"); });
                btn.classList.add("active");
                loadChart(chartSymbol || currentInstrument);
            });
        });

        // Level filter buttons
        var filterBtns = document.querySelectorAll("[data-filter]");
        filterBtns.forEach(function (btn) {
            btn.addEventListener("click", function () {
                filterBtns.forEach(function (b) { b.classList.remove("active"); });
                btn.classList.add("active");
                currentLevelFilter = btn.getAttribute("data-filter");
                if (data) renderLevels();
            });
        });

        // Fullscreen chart
        var fsBtn = $("chart-fullscreen-btn");
        if (fsBtn) {
            fsBtn.addEventListener("click", function () {
                var card = fsBtn.closest(".card");
                if (!card) return;
                var isFs = card.classList.toggle("chart-fullscreen");
                fsBtn.innerHTML = isFs
                    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18"><path d="M4 14h6v6m10-10h-6V4M4 10h6V4m10 10h-6v6"/></svg>'
                    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>';
                // Resize chart
                setTimeout(function () {
                    if (chart) {
                        var c = $("chart-container");
                        chart.applyOptions({ width: c.clientWidth, height: c.clientHeight });
                    }
                }, 50);
            });
            // Escape to exit
            document.addEventListener("keydown", function (e) {
                if (e.key === "Escape") {
                    var card = fsBtn.closest(".card");
                    if (card && card.classList.contains("chart-fullscreen")) {
                        fsBtn.click();
                    }
                }
            });
        }

        // ─── Levels dropdown ───
        var ddBtn = $("levels-dropdown-btn");
        var ddPanel = $("levels-dropdown");
        if (ddBtn && ddPanel) {
            ddBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                ddPanel.classList.toggle("hidden");
            });
            document.addEventListener("click", function (e) {
                if (!ddPanel.contains(e.target) && e.target !== ddBtn) {
                    ddPanel.classList.add("hidden");
                }
            });
            // Sync checkboxes with state
            ddPanel.querySelectorAll("input[data-grp]").forEach(function (cb) {
                cb.checked = isGroupActive(cb.getAttribute("data-grp"));
                cb.addEventListener("change", function () {
                    var grp = cb.getAttribute("data-grp");
                    if (cb.checked) {
                        if (levelGroups.indexOf(grp) < 0) levelGroups.push(grp);
                    } else {
                        levelGroups = levelGroups.filter(function (g) { return g !== grp; });
                    }
                    saveLevelGroups();
                    applyLevelFilter();
                    syncPresetBtns();
                });
            });
            // Presets
            var ALL_GROUPS = ["options", "0dte", "gex", "vwap", "sd12", "sd3", "profile", "prev", "swing", "session", "ib", "ovn"];
            function syncPresetBtns() {
                ddPanel.querySelectorAll(".levels-dd-preset").forEach(function (b) { b.classList.remove("active"); });
                if (levelGroups.length === 0) {
                    ddPanel.querySelector('[data-preset="none"]').classList.add("active");
                } else if (levelGroups.length === ALL_GROUPS.length) {
                    ddPanel.querySelector('[data-preset="all"]').classList.add("active");
                } else {
                    var ess = ESSENTIAL_GROUPS.slice().sort().join(",");
                    var cur = levelGroups.slice().sort().join(",");
                    if (cur === ess) ddPanel.querySelector('[data-preset="essential"]').classList.add("active");
                }
            }
            ddPanel.querySelectorAll(".levels-dd-preset").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    var preset = btn.getAttribute("data-preset");
                    if (preset === "all") levelGroups = ALL_GROUPS.slice();
                    else if (preset === "none") levelGroups = [];
                    else levelGroups = ESSENTIAL_GROUPS.slice();
                    saveLevelGroups();
                    ddPanel.querySelectorAll("input[data-grp]").forEach(function (cb) {
                        cb.checked = isGroupActive(cb.getAttribute("data-grp"));
                    });
                    applyLevelFilter();
                    syncPresetBtns();
                });
            });
            syncPresetBtns();
        }

        var btns = document.querySelectorAll(".instrument-btn:not(.tf-btn):not(.levels-dd-preset)");
        var instrumentDebounce = null;
        btns.forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (instrumentDebounce) clearTimeout(instrumentDebounce);
                instrumentDebounce = setTimeout(function () {
                    currentInstrument = btn.getAttribute("data-instrument");
                    localStorage.setItem("mia_instrument", currentInstrument);
                    btns.forEach(function (b) { b.classList.remove("active"); });
                    btn.classList.add("active");
                    loadChart(currentInstrument);
                    vpLoaded = false;
                    levelsChartsLoaded = false;
                    signalsChartsLoaded = false;
                    ibChartLoaded = false;
                    lastClosePrice = null;
                    if (data) renderCurrentPage();
                }, 300);
            });
        });
    }

    function switchPage(page) {
        currentPage = page;
        localStorage.setItem("mia_page", page);
        document.querySelectorAll(".page-content").forEach(function (el) {
            el.classList.add("hidden");
        });
        var target = $("page-" + page);
        if (target) target.classList.remove("hidden");

        document.querySelectorAll(".sidebar-nav a[data-page]").forEach(function (a) {
            a.classList.toggle("active", a.getAttribute("data-page") === page);
        });

        if (data) renderCurrentPage();
    }

    // ═══════════════════════════════════════════════════════════════
    // API Fetch
    // ═══════════════════════════════════════════════════════════════

    var fetchErrors = 0;
    var prevEsPrice = null;
    var prevNqPrice = null;
    var ctaLastLoad = 0;

    function apiHeaders() {
        var h = {};
        if (authToken) h["Authorization"] = "Bearer " + authToken;
        return h;
    }

    // ── Auto-refresh token sur 401 ──
    var _refreshPromise = null;

    function _doRefresh() {
        if (_refreshPromise) return _refreshPromise;
        _refreshPromise = fetch(API_BASE + "/api/auth/refresh", {
            method: "POST",
            credentials: "include"
        })
        .then(function (r) {
            if (!r.ok) throw new Error("refresh_failed");
            return r.json();
        })
        .then(function (d) {
            authToken = d.token;
            currentTier = d.tier;
            localStorage.setItem("mia_token", authToken);
            localStorage.setItem("mia_tier", currentTier);
            _refreshPromise = null;
            return d.token;
        })
        .catch(function (err) {
            _refreshPromise = null;
            authToken = "";
            currentTier = "free";
            localStorage.removeItem("mia_token");
            localStorage.removeItem("mia_tier");
            localStorage.removeItem("mia_trial_expires");
            window.location.href = "/welcome";
            return Promise.reject(err);
        });
        return _refreshPromise;
    }

    function fetchWithAuth(url, opts) {
        opts = opts || {};
        opts.headers = Object.assign({}, apiHeaders(), opts.headers || {});
        opts.credentials = "include";
        return fetch(url, opts).then(function (r) {
            if (r.status === 401 && authToken) {
                return _doRefresh().then(function () {
                    opts.headers = Object.assign({}, apiHeaders(), opts.headers || {});
                    return fetch(url, opts);
                });
            }
            return r;
        });
    }

    var currentPollInterval = POLL_INTERVAL;
    var MAX_POLL_INTERVAL = 60000; // 60s max

    function fetchDashboard() {
        fetchWithAuth(API_BASE + "/api/dashboard", { method: "GET" })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                // Succes — reset backoff
                if (fetchErrors > 0) {
                    fetchErrors = 0;
                    currentPollInterval = POLL_INTERVAL;
                    if (pollTimer) clearInterval(pollTimer);
                    pollTimer = setInterval(fetchDashboard, POLL_INTERVAL);
                }
                hideConnError();
                data = d;
                if (d.tier) { currentTier = d.tier; updateTierIndicator(); }
                renderBanner();
                renderCurrentPage();
                renderSidebarStatus();
                renderWarnings();
                updateSignalFeed();
                updateChartBar();
                injectEduIcons();
                fetchPaperTrades();
                // Reset caches avec TTL
                if (Date.now() - ctaLastLoad > 300000) { ctaLoaded = false; }
                if (Date.now() - vpLastLoad > 60000) { vpLoaded = false; }
                if (Date.now() - mqLastLoad > 900000) { mqLoaded = false; }  // 15 min
            })
            .catch(function (err) {
                console.error("Fetch error:", err);
                fetchErrors++;
                if (fetchErrors >= 3) showConnError();
                // Exponential backoff : 5s → 10s → 20s → 40s → 60s max
                currentPollInterval = Math.min(currentPollInterval * 2, MAX_POLL_INTERVAL);
                if (pollTimer) clearInterval(pollTimer);
                pollTimer = setInterval(fetchDashboard, currentPollInterval);
            });
    }

    function showConnError() {
        var el = $("conn-error");
        if (el) el.classList.remove("hidden");
    }
    function hideConnError() {
        var el = $("conn-error");
        if (el) el.classList.add("hidden");
    }

    function renderWarnings() {
        var el = $("warnings-banner");
        if (!el || !data) { if (el) el.classList.add("hidden"); return; }

        var messages = [];

        // News
        var w = data.warnings || {};
        if (w.news_detected) {
            messages.push('<strong>NEWS:</strong> ' + (w.news_message || "Evenement detecte"));
        }

        // Level breaks
        var lb = data.level_breaks || {};
        var sym = currentInstrument === "BOTH" ? "ES" : currentInstrument;
        var breaks = lb[sym.toLowerCase()] || [];
        breaks.forEach(function (b) {
            var icon = b.signal === "BUY" ? "&#9650;" : "&#9660;";
            var color = b.signal === "BUY" ? "var(--green)" : "var(--red)";
            messages.push('<span style="color:' + color + ';">' + icon + ' <strong>' + b.level + '</strong> ' + fmtPrice(b.price) + ' CASSE — ' + b.direction + '</span>');
        });

        if (messages.length > 0) {
            el.innerHTML = messages.join(' &nbsp;|&nbsp; ');
            el.classList.remove("hidden");
        } else {
            el.classList.add("hidden");
        }
    }

    function renderCurrentPage() {
        switch (currentPage) {
            case "overview": renderOverview(); break;
            case "options":
                renderOptions();
                drawGexDistribution();
                break;
            case "orderflow":
                renderOrderFlow();
                drawDomLadder();
                break;
            case "profile": renderProfile(); break;
            case "levels":
                renderLevels();
                if (!levelsChartsLoaded) { loadCorrChart(); levelsChartsLoaded = true; }
                break;
            case "signals":
                renderSignals();
                if (!signalsChartsLoaded) { loadSignalChart(); signalsChartsLoaded = true; }
                break;
            case "cta":
                if (!ctaLoaded) { loadCtaData(); }
                break;
            case "menthorq":
                if (!mqLoaded) { loadMenthorqData(); }
                break;
            case "performance":
                renderPerformance();
                break;
            case "alerts":
                renderAlerts();
                break;
            case "paper":
                renderPaperPage();
                break;
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // Banner (toujours visible)
    // ═══════════════════════════════════════════════════════════════

    function renderBanner() {
        if (!data || !data.banner) return;
        var b = data.banner;
        var esEl = $("banner-es-price");
        var nqEl = $("banner-nq-price");
        esEl.textContent = fmtPrice(b.es.price);
        nqEl.textContent = fmtPrice(b.nq.price);
        // Flash vert/rouge
        if (prevEsPrice !== null && b.es.price !== prevEsPrice) {
            esEl.classList.remove("flash-up", "flash-dn");
            void esEl.offsetWidth;
            esEl.classList.add(b.es.price > prevEsPrice ? "flash-up" : "flash-dn");
        }
        if (prevNqPrice !== null && b.nq.price !== prevNqPrice) {
            nqEl.classList.remove("flash-up", "flash-dn");
            void nqEl.offsetWidth;
            nqEl.classList.add(b.nq.price > prevNqPrice ? "flash-up" : "flash-dn");
        }
        prevEsPrice = b.es.price;
        prevNqPrice = b.nq.price;
        $("banner-es-atr").textContent = "ATR " + fmt(b.es.atr, 1);
        $("banner-nq-atr").textContent = "ATR " + fmt(b.nq.atr, 1);
        $("banner-session").textContent = b.es.session || b.nq.session || "--";
        $("banner-time").textContent = new Date().toLocaleTimeString("fr-FR");
    }

    function renderSidebarStatus() {
        if (!data) return;
        var h = data.health || {};
        var checks = h.checks || {};
        var feed = checks.data_feed || "UNKNOWN";
        var bot = checks.bot || "UNKNOWN";

        var feedEl = $("health-feed");
        feedEl.textContent = feed;
        feedEl.className = "badge " + (feed === "LIVE" ? "badge-green" : feed === "OK" ? "badge-cyan" : "badge-red");

        var botEl = $("health-bot");
        botEl.textContent = bot;
        botEl.className = "badge " + (bot === "OK" ? "badge-green" : bot === "STANDBY" ? "badge-cyan" : "badge-red");

        $("last-update").textContent = new Date().toLocaleTimeString("fr-FR");
    }

    // ═══════════════════════════════════════════════════════════════
    // Helper : get instrument data
    // ═══════════════════════════════════════════════════════════════

    function getInstr(sym) {
        if (!data) return null;
        return sym === "ES" ? data.es : data.nq;
    }

    // ═══════════════════════════════════════════════════════════════
    // PAGE: OVERVIEW
    // ═══════════════════════════════════════════════════════════════

    // ═══════════════════════════════════════════════════════════════
    // Signal Feed — fil d'evenements live sur l'Overview
    // ═══════════════════════════════════════════════════════════════

    var signalFeedHistory = [];
    var MAX_FEED = 20;
    var _prevFeedState = {};

    function updateSignalFeed() {
        if (!data) return;
        var sym = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var symUp = sym.toUpperCase();
        var instr = getInstr(symUp);
        if (!instr) return;
        var reg = instr.regime || {};
        var now = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

        // 1. Level breaks
        var lb = (data.level_breaks || {})[sym] || [];
        lb.forEach(function (b) {
            var key = "lb_" + b.level + "_" + b.direction;
            if (_prevFeedState[key]) return;
            _prevFeedState[key] = true;
            var icon = b.signal === "BUY" ? "&#9650;" : "&#9660;";
            var color = b.signal === "BUY" ? "var(--green)" : "var(--red)";
            var label = b.signal === "BUY" ? "ACHAT" : "VENTE";
            addSignal(now, icon, color, label + " — " + b.level + " " + fmtPrice(b.price) + " casse (" + b.direction + ")", "MAINTENANT");
        });

        // 2. Favor change avec freshness
        var favor = reg.favor || "NEUTRE";
        var freshness = reg.favor_freshness || "FRAIS";
        var moved = reg.favor_moved_ticks || 0;
        var trigger = reg.favor_trigger_price || 0;
        var favorKey = favor + "_" + freshness;
        if (favorKey !== _prevFeedState.favor) {
            _prevFeedState.favor = favorKey;
            if (favor !== "NEUTRE") {
                var icon = favor === "LONG" ? "&#9650;" : "&#9660;";
                var color = favor === "LONG" ? "var(--green)" : "var(--red)";
                var label = favor === "LONG" ? "ACHAT" : "VENTE";
                var fresh = "";
                if (freshness === "FRAIS") fresh = "MAINTENANT";
                else if (freshness === "EN COURS") fresh = "en cours (" + moved + "t)";
                else if (freshness === "AVANCE") fresh = "depuis " + moved + "t — attendre pullback";
                else if (freshness === "EPUISE") fresh = "PASSE depuis " + moved + "t";
                else if (freshness === "CONTRE") fresh = "INVALIDE — prix va contre";
                addSignal(now, icon, color, label + " @ " + fmtPrice(trigger), fresh);
            }
        }

        // 3. Divergence grade change
        var divGrade = reg.div_grade || "NONE";
        if (divGrade !== _prevFeedState.div && divGrade !== "NONE" && divGrade !== "FAIBLE") {
            _prevFeedState.div = divGrade;
            var divColor = divGrade === "EXTREME" ? "var(--red)" : "var(--orange)";
            addSignal(now, "&#9733;", divColor, "DIV " + divGrade + " (" + fmt(reg.div_quality, 0) + "/10)", reg.range_pos >= 70 ? "Favorise VENTE" : reg.range_pos <= 30 ? "Favorise ACHAT" : "Surveiller");
        }

        // 4. MTF flip
        var mtfVerdict = reg.mtf_verdict || "";
        if (mtfVerdict && mtfVerdict !== _prevFeedState.mtf) {
            _prevFeedState.mtf = mtfVerdict;
            var isBull = mtfVerdict.indexOf("ACHAT") >= 0;
            addSignal(now, isBull ? "&#9650;" : "&#9660;", isBull ? "var(--green)" : "var(--red)", "MTF " + mtfVerdict, "");
        }

        // 5. Double pattern
        var patI = (data.patterns_intraday || {})[sym] || {};
        if (patI.detected && patI.best) {
            var bestKey = patI.best.type + "_" + (patI.best.low_1 || patI.best.high_1 || {}).price;
            if (bestKey !== _prevFeedState.pattern) {
                _prevFeedState.pattern = bestKey;
                var isBot = patI.best.type === "DOUBLE_BOTTOM";
                addSignal(now, isBot ? "W" : "M", isBot ? "var(--green)" : "var(--red)",
                    patI.best.type.replace("_", " ") + " Q:" + patI.best.quality + "/8",
                    patI.best.status + (patI.best.vol_confirmed ? " Vol OK" : "") + (patI.best.delta_div ? " +DIV" : ""));
            }
        }

        renderFeed();
    }

    function addSignal(time, icon, color, text, freshness) {
        // Dedup — pas le meme texte dans les 3 derniers signaux
        for (var i = 0; i < Math.min(3, signalFeedHistory.length); i++) {
            if (signalFeedHistory[i].text === text) return;
        }
        signalFeedHistory.unshift({ time: time, icon: icon, color: color, text: text, freshness: freshness });
        if (signalFeedHistory.length > MAX_FEED) signalFeedHistory.pop();
    }

    function renderFeed() {
        var el = $("signal-feed");
        if (!el) return;
        if (signalFeedHistory.length === 0) {
            el.innerHTML = '<div style="color:var(--text-disabled);padding:4px 0;">En attente de signaux...</div>';
            return;
        }
        var h = "";
        signalFeedHistory.forEach(function (s, i) {
            var opacity = i === 0 ? "1" : i < 3 ? "0.8" : "0.5";
            var bg = i === 0 ? "rgba(255,255,255,0.03)" : "transparent";
            h += '<div style="display:flex;align-items:center;gap:8px;padding:3px 0;opacity:' + opacity + ';background:' + bg + ';">';
            h += '<span style="color:var(--text-disabled);min-width:40px;">' + s.time + '</span>';
            h += '<span style="color:' + s.color + ';font-weight:700;min-width:16px;">' + s.icon + '</span>';
            h += '<span style="font-weight:600;color:' + s.color + ';">' + s.text + '</span>';
            if (s.freshness) {
                var fColor = s.freshness === "MAINTENANT" ? "var(--green)" : s.freshness.indexOf("PASSE") >= 0 ? "var(--text-disabled)" : "var(--gold)";
                h += '<span style="font-size:0.6875rem;color:' + fColor + ';margin-left:auto;">' + s.freshness + '</span>';
            }
            h += '</div>';
        });
        el.innerHTML = h;
    }

    function renderOverview() {
        var adv = data.advisory || {};
        var reg = null;

        // Get regime from instrument data or top-level
        var instr = getInstr(currentInstrument === "BOTH" ? "ES" : currentInstrument);
        if (instr && instr.regime) {
            reg = instr.regime;
        } else if (data.regime_es) {
            reg = data.regime_es;
        }
        // Guard : toujours un objet pour eviter les TypeError
        reg = reg || {};

        var bias = (reg && reg.bias) || (adv.bias) || "NEUTRAL";
        var mode = (reg && reg.mode) || (adv.mode) || "NORMAL";
        var favor = (reg && reg.favor) || (adv.favor) || "NEUTRE";
        var vol = (reg && reg.vol_regime) || (adv.vol_regime) || "NORMAL";
        var biasScore = (reg && reg.bias_score) || 0;
        var atr = (reg && reg.atr) || 0;
        var rangePos = (reg && reg.range_pos) || 50;

        // Big boxes — messages specifiques
        var biasMsg = { "BULLISH": "Acheteurs dominent", "BEARISH": "Vendeurs dominent", "NEUTRAL": "Aucune direction" };
        var biasSub = { "BULLISH": "Delta + VWAP + CVD haussiers", "BEARISH": "Delta + VWAP + CVD baissiers", "NEUTRAL": "Facteurs contradictoires" };
        $("box-bias").className = "big-box " + biasClass(bias);
        $("bias-value").textContent = biasMsg[bias] || bias;
        $("bias-value").style.color = bias === "BULLISH" ? "var(--green)" : bias === "BEARISH" ? "var(--red)" : "var(--text-secondary)";
        $("bias-score").textContent = (biasSub[bias] || "") + " (" + fmt(biasScore, 2) + ")";

        var modeMsg = { "TREND": "Marche directionnel", "RANGE": "Marche en consolidation", "NORMAL": "Pas de regime clair" };
        var modeSub2 = { "TREND": "Ne pas fader, suivre le flux", "RANGE": "Acheter support, vendre resistance", "NORMAL": "Attendre un regime clair" };
        $("box-mode").className = "big-box " + modeClass(mode);
        $("mode-value").textContent = modeMsg[mode] || mode;
        $("mode-value").style.color = mode === "TREND" ? "var(--cyan)" : mode === "RANGE" ? "var(--orange)" : "var(--text-secondary)";
        var trendV = reg.mode_trend_votes || 0;
        var rangeV = reg.mode_range_votes || 0;
        $("mode-sub").textContent = (modeSub2[mode] || "") + " | " + trendV + "T/" + rangeV + "R | Pos: " + fmt(rangePos, 0) + "%";

        var favorMsg = { "LONG": "Favoriser ACHAT", "SHORT": "Favoriser VENTE", "NEUTRE": "Pas de preference" };
        var freshness = reg.favor_freshness || "FRAIS";
        var movedTicks = reg.favor_moved_ticks || 0;
        var triggerPrice = reg.favor_trigger_price || 0;

        // Adapter le label selon la fraicheur
        var favorLabel = favorMsg[favor] || favor;
        var favorColor = favor === "LONG" ? "var(--green)" : favor === "SHORT" ? "var(--red)" : "var(--text-secondary)";

        if (favor !== "NEUTRE" && freshness === "EPUISE") {
            favorLabel = "Signal EPUISE";
            favorColor = "var(--text-disabled)";
        } else if (favor !== "NEUTRE" && freshness === "AVANCE") {
            favorLabel = favorMsg[favor] + " (avance)";
            favorColor = "var(--orange)";
        }

        $("box-favor").className = "big-box " + (freshness === "EPUISE" ? "neutral" : biasClass(favor === "LONG" ? "BULLISH" : favor === "SHORT" ? "BEARISH" : "NEUTRAL"));
        $("favor-value").textContent = favorLabel;
        $("favor-value").style.color = favorColor;

        // Sous-texte avec fraicheur
        var favorReason = reg.favor_reason || "";
        var subParts = [];
        if (favorReason) subParts.push(favorReason);
        if (favor !== "NEUTRE" && triggerPrice) {
            subParts.push("@ " + fmtPrice(triggerPrice));
        }
        if (favor !== "NEUTRE" && movedTicks !== 0) {
            var movedDir = movedTicks > 0 ? "+" : "";
            subParts.push(movedDir + movedTicks + "t " + (freshness === "FRAIS" ? "MAINTENANT" : freshness === "EN COURS" ? "en cours" : freshness === "AVANCE" ? "avance — attendre pullback" : freshness === "EPUISE" ? "mouvement consomme" : freshness === "CONTRE" ? "prix va contre" : ""));
        }
        $("favor-sub").textContent = subParts.join(" | ");

        var volMsg = { "EXTREME": "Volatilite extreme !", "HIGH": "Volatilite elevee", "NORMAL": "Volatilite normale", "LOW": "Marche calme" };
        var volSub2 = { "EXTREME": "Reduire taille, stops larges", "HIGH": "Prudence, mouvements rapides", "NORMAL": "Conditions normales", "LOW": "Faible volume, faux signaux" };
        var volColor = vol === "EXTREME" ? "var(--red)" : vol === "HIGH" ? "var(--orange)" : vol === "LOW" ? "var(--cyan)" : "var(--text-secondary)";
        $("box-vol").className = "big-box " + (vol === "EXTREME" ? "bear" : vol === "HIGH" ? "range" : "neutral");
        $("vol-value").textContent = volMsg[vol] || vol;
        $("vol-value").style.color = volColor;
        $("vol-sub").textContent = (volSub2[vol] || "") + " | ATR: " + fmt(atr, 1);

        // Jauges visuelles
        var vix = (reg && reg.vix) || 0;
        var vixColor = vix > 30 ? "var(--red)" : vix > 25 ? "var(--orange)" : vix > 20 ? "var(--gold)" : "var(--green)";
        var biasConf = (reg && reg.bias_confidence) || 0;
        var biasConfColor = bias === "BULLISH" ? "var(--green)" : bias === "BEARISH" ? "var(--red)" : "var(--text-secondary)";
        var rangePosColor = rangePos >= 80 ? "var(--red)" : rangePos <= 20 ? "var(--green)" : "var(--gold)";
        var rvol = 0;
        if (instr && instr.order_flow) rvol = instr.order_flow.rvol || 0;
        var rvolColor = rvol > 2 ? "var(--red)" : rvol > 1 ? "var(--orange)" : "var(--cyan)";
        var sessRangeAtr = (reg && reg.sess_range_atr) || 0;
        var sessColor = sessRangeAtr > 1.2 ? "var(--red)" : sessRangeAtr > 0.5 ? "var(--cyan)" : "var(--orange)";

        $("gauges-row").innerHTML =
            svgGauge(vix, 10, 45, "VIX", vixColor, "", 150,
                "VIX = Indice de peur du marche. <15 = calme (range probable). 15-25 = normal. 25-35 = stress (mouvements rapides, elargir stops). >35 = panique (reduire la taille).") +
            svgGauge(biasConf, 0, 1, "Confiance", biasConfColor, "%", 150,
                "Confiance = consensus des facteurs de decision. >70% = facteurs alignes, signal fiable. 40-70% = conflit entre facteurs, prudence. <40% = trop de contradictions, NE PAS TRADER.") +
            svgGauge(rangePos, 0, 100, "Range Pos", rangePosColor, "pct", 150,
                "Position dans le range de la session. 0% = plus bas du jour (zone achat en range). 50% = milieu (pas de signal). 100% = plus haut (zone vente en range). ATTENTION : en mode TREND, 100% = breakout, pas un top.") +
            svgGauge(rvol, 0, 4, "RVOL", rvolColor, "x", 150,
                "Volume relatif vs moyenne historique a cette heure. <0.5x = marche mort, faux signaux. 1x = normal. >2x = activite inhabituelle, mouvement en cours. >3x = climax, potentiel reversal.") +
            svgGauge(sessRangeAtr, 0, 3, "Sess/ATR", sessColor, "x", 150,
                "Taille de la session vs ATR moyen. <0.5x = compression, explosif a venir. 0.5-1x = normal. >1.2x = expansion, le mouvement est deja avance. >1.5x = session etendue, prudence sur les entrees.");

        // Qui a la main
        var qui = adv.qui_a_la_main || "PERSONNE";
        var force = adv.force || "EQUILIBRE";
        $("hand-who").textContent = qui;
        $("hand-who").style.color = qui === "ACHETEURS" ? "var(--green)" : qui === "VENDEURS" ? "var(--red)" : "var(--text-secondary)";
        $("hand-force").textContent = force;
        $("hand-force").className = "badge " + (qui === "ACHETEURS" ? "badge-green" : qui === "VENDEURS" ? "badge-red" : "badge-gray");

        // Bias factors
        var factorsHtml = "";
        if (reg && reg.bias_factors) {
            reg.bias_factors.forEach(function (f) {
                var icon = f.icon === "bull" ? "green" : f.icon === "bear" ? "red" : "gray";
                factorsHtml += '<div class="kv-row"><span class="kv-key">' + f.text + '</span><span class="badge badge-' + icon + '">' + f.icon.toUpperCase() + '</span></div>';
            });
        }
        $("bias-factors").innerHTML = factorsHtml;

        // Divergence Quality
        var divHtml = "";
        if (reg && reg.div_active) {
            var divColor = reg.div_grade === "EXTREME" ? "var(--red)" : reg.div_grade === "FORTE" ? "var(--orange)" : reg.div_grade === "MODEREE" ? "var(--gold)" : "var(--text-disabled)";
            var divBadge = reg.div_grade === "EXTREME" ? "badge-red" : reg.div_grade === "FORTE" ? "badge-orange" : reg.div_grade === "MODEREE" ? "badge-gold" : "badge-gray";
            divHtml += '<div style="border:1px solid ' + divColor + ';border-radius:8px;padding:10px;margin-bottom:8px;background:rgba(0,0,0,0.3);">';
            divHtml += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">';
            divHtml += '<span style="font-weight:700;color:' + divColor + ';">DIVERGENCE PRIX/DELTA</span>';
            divHtml += badgeHtml(reg.div_grade + " (" + fmt(reg.div_quality, 0) + "/10)", divBadge);
            divHtml += '</div>';
            (reg.div_factors || []).forEach(function (f) {
                divHtml += '<div style="font-size:0.75rem;color:var(--text-secondary);padding:2px 0;">• ' + f + '</div>';
            });
            if (reg.div_grade === "FAIBLE") {
                divHtml += '<div style="font-size:0.6875rem;color:var(--text-disabled);margin-top:4px;">Divergence detectee mais contexte insuffisant — NE PAS trader sur ce signal seul</div>';
            }
            divHtml += '</div>';
        }
        // SMT Divergence intermarket
        var im = data.intermarket || {};
        if (im.smt_divergence && im.smt_direction !== "NONE") {
            var smtColor = im.smt_direction === "BEARISH" ? "var(--red)" : "var(--green)";
            divHtml += '<div style="border:1px solid ' + smtColor + ';border-radius:8px;padding:10px;background:rgba(0,0,0,0.3);">';
            divHtml += '<div style="font-weight:700;color:' + smtColor + ';">SMT DIVERGENCE ES/NQ</div>';
            divHtml += '<div style="font-size:0.8125rem;color:var(--text-secondary);margin-top:4px;">' + (im.smt_detail || "") + '</div>';
            divHtml += '</div>';
        }
        if (im.momentum_divergence) {
            divHtml += '<div style="font-size:0.75rem;color:var(--orange);margin-top:6px;">Divergence momentum ES/NQ — ecart range pos: ' + fmt(im.range_pos_gap, 0) + '%</div>';
        }
        $("div-section").innerHTML = divHtml;

        // Conseils — override FAVORISER si MTF contredit
        var conseilsHtml = "";
        (adv.conseils || []).forEach(function (c) {
            var text = c.text;
            var type = c.type;
            // Override FAVORISER si MTF est charge et contredit
            if (mtfResult && (text.indexOf("FAVORISER ACHAT") >= 0 || text.indexOf("FAVORISER VENTE") >= 0)) {
                var mtfBulls = mtfResult.bulls || 0;
                var mtfBears = mtfResult.bears || 0;
                if (text.indexOf("ACHAT") >= 0 && mtfBears >= 3) {
                    text = "CONFLIT — Le regime suggere ACHAT mais le MTF est BEAR (" + mtfResult.verdict + "). Prudence.";
                    type = "warn";
                } else if (text.indexOf("VENTE") >= 0 && mtfBulls >= 3) {
                    text = "CONFLIT — Le regime suggere VENTE mais le MTF est BULL (" + mtfResult.verdict + "). Prudence.";
                    type = "warn";
                }
            }
            var iconMap = { ok: "&#10003;", warn: "!", danger: "&#10007;", info: "i" };
            conseilsHtml += '<div class="conseil ' + type + '"><div class="conseil-icon">' + (iconMap[type] || "?") + '</div><div>' + text + '</div></div>';
        });
        $("conseils-list").innerHTML = conseilsHtml;

        // Narration du marche
        var narrative = data.narrative || [];
        var narrEl = $("narrative-content");
        var narrTitle = $("narrative-title");
        if (narrEl) {
            var now = new Date();
            var timeStr = now.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            var dateStr = now.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
            if (narrTitle) {
                narrTitle.innerHTML = 'Narration du Marche <span class="badge badge-gold">LIVE</span> <span style="font-size:0.6875rem;font-weight:400;color:var(--text-disabled);margin-left:8px;">' + dateStr + ' ' + timeStr + '</span>';
            }
            if (narrative.length > 0) {
                var narrHtml = "";
                narrative.forEach(function (p, i) {
                    var isLast = i === narrative.length - 1;
                    narrHtml += '<p style="margin-bottom:10px;padding-left:12px;border-left:3px solid ' + (isLast ? 'var(--gold)' : 'rgba(255,255,255,0.06)') + ';' + (isLast ? 'font-weight:600;color:var(--text-primary);' : '') + '">' + p + '</p>';
                });
                narrEl.innerHTML = narrHtml;
            } else {
                narrEl.innerHTML = '<div style="color:var(--text-disabled);font-style:italic;">Narration disponible pendant la session US</div>';
            }
        }

        // Health checks
        var healthHtml = "";
        var h = data.health || {};
        var checks = h.checks || {};
        Object.keys(checks).forEach(function (k) {
            var v = checks[k];
            var cls = (v === "OK" || v === "LIVE" || v === "CLEAR") ? "green" : (v === "STANDBY" || v === "N/A") ? "cyan" : "red";
            healthHtml += kvRow(k, v, cls);
        });
        if (h.health_pct != null) {
            healthHtml += '<div style="margin-top:8px;"><div class="gauge"><div class="gauge-fill gauge-' + (h.health_pct >= 80 ? "green" : h.health_pct >= 50 ? "gold" : "red") + '" style="width:' + h.health_pct + '%;"></div></div><div style="text-align:center;font-size:0.75rem;color:var(--text-disabled);margin-top:4px;">Health: ' + h.health_pct + '%</div></div>';
        }
        $("health-checks").innerHTML = healthHtml;

        // Regime details
        var regHtml = "";
        if (reg) {
            regHtml += kvRow("VIX", fmt(reg.vix, 2), reg.vix > 25 ? "red" : reg.vix > 20 ? "orange" : "green");
            regHtml += kvRow("VIX Regime", reg.vix_regime_label || VIX_REGIME_LABELS[reg.vix_regime] || "--");
            regHtml += kvRow("VWAP Slope 10", fmt(reg.vwap_slope_10, 2), colorClass(reg.vwap_slope_10));
            regHtml += kvRow("VWAP Slope 30", fmt(reg.vwap_slope_30, 2), colorClass(reg.vwap_slope_30));
            regHtml += kvRow("VWAP Daily", reg.vwap_d_side > 0 ? "AU-DESSUS" : "EN-DESSOUS", reg.vwap_d_side > 0 ? "green" : "red");
            regHtml += kvRow("VWAP Weekly", reg.vwap_w_side > 0 ? "AU-DESSUS" : "EN-DESSOUS", reg.vwap_w_side > 0 ? "green" : "red");
            regHtml += kvRow("VWAP Monthly", reg.vwap_m_side > 0 ? "AU-DESSUS" : "EN-DESSOUS", reg.vwap_m_side > 0 ? "green" : "red");
            regHtml += kvRow("Triple Align", boolBadge(reg.vwap_triple_align, "D+W+M alignes", "Desaligne"));
            regHtml += kvRow("Momentum 3b", fmt(reg.momentum_3b, 2), colorClass(reg.momentum_3b));
            regHtml += kvRow("Momentum 5b", fmt(reg.momentum_5b, 2), colorClass(reg.momentum_5b));
            regHtml += kvRow("MA Trend", reg.ma_trend > 0 ? "Haussier" : reg.ma_trend < 0 ? "Baissier" : "Neutre", colorClass(reg.ma_trend));
        }
        $("regime-details").innerHTML = regHtml;

        // Session & Open
        var sess = (instr && instr.session) || {};
        var sessHtml = "";
        if (sess.open_type_label) {
            var col1 = kvRow("Open Type", sess.open_type_label) + kvRow("Direction", sess.open_direction > 0 ? "Haussiere" : sess.open_direction < 0 ? "Baissiere" : "Neutre", colorClass(sess.open_direction)) + kvRow("Open Zone", sess.open_zone) + kvRow("Gap", fmt(sess.open_gap_ticks, 0) + "t") + kvRow("Dans VA prev", boolBadge(sess.open_in_prev_va, "Dans la VA", "Hors VA")) + kvRow("Open Bias", fmt(sess.open_bias_conf, 2));
            var col2 = kvRow("Day Type", sess.day_type_label) + kvRow("Trend Prob", fmt(sess.trend_day_prob, 0) + "%") + kvRow("Session", sess.session_label) + kvRow("Session ID", sess.session_id) + kvRow("Early", boolBadge(sess.bool_session_early, "Debut de session", "Session avancee"));
            var col3 = kvRow("OVN Range", fmt(sess.ovn_range_ticks, 0) + "t") + kvRow("OVN High", fmtPrice(sess.ovn_high_price)) + kvRow("OVN Low", fmtPrice(sess.ovn_low_price)) + kvRow("Open Cash", fmtPrice(sess.open_cash_price)) + kvRow("Open 8:30", fmtPrice(sess.open_830_price)) + kvRow("Sess High", fmtPrice(sess.sess_high_price)) + kvRow("Sess Low", fmtPrice(sess.sess_low_price));
            sessHtml = '<div>' + col1 + '</div><div>' + col2 + '</div><div>' + col3 + '</div>';
        }
        $("session-grid").innerHTML = sessHtml;

        // MTF Bias + Confluence + Conseil Global
        loadMtfBias();
        renderConfluence();
    }

    var VIX_REGIME_LABELS = { 0: "LOW", 1: "NORMAL", 2: "HIGH" };

    // ═══════════════════════════════════════════════════════════════
    // MTF Bias Confluence
    // ═══════════════════════════════════════════════════════════════

    var mtfLastFetch = 0;
    var mtfResult = null;

    function loadMtfBias() {
        if (Date.now() - mtfLastFetch < 10000) return; // throttle 10s
        var sym = currentInstrument === "BOTH" ? "ES" : currentInstrument;
        fetch(API_BASE + "/api/mtf/" + sym, { headers: apiHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                mtfLastFetch = Date.now();
                mtfResult = d;
                renderMtfBias(d);
                reconcileFavorWithMtf();
            })
            .catch(function () {});
    }

    function reconcileFavorWithMtf() {
        if (!mtfResult || !data) return;
        var instr = getInstr(currentInstrument === "BOTH" ? "ES" : currentInstrument);
        if (!instr || !instr.regime) return;

        var favor = instr.regime.favor;
        var mtfVerdict = mtfResult.verdict || "";
        var mtfBulls = mtfResult.bulls || 0;
        var mtfBears = mtfResult.bears || 0;

        // Detecter contradiction
        var contradict = false;
        var overrideFavor = favor;
        if (favor === "SHORT" && mtfBulls >= 3) {
            contradict = true;
            overrideFavor = mtfBulls === 4 ? "LONG" : "NEUTRE";
        } else if (favor === "LONG" && mtfBears >= 3) {
            contradict = true;
            overrideFavor = mtfBears === 4 ? "SHORT" : "NEUTRE";
        }

        if (contradict) {
            $("favor-value").textContent = overrideFavor;
            var color = overrideFavor === "LONG" ? "var(--green)" : overrideFavor === "SHORT" ? "var(--red)" : "var(--gold)";
            $("favor-value").style.color = color;
            $("box-favor").className = "big-box " + biasClass(overrideFavor === "LONG" ? "BULLISH" : overrideFavor === "SHORT" ? "BEARISH" : "NEUTRAL");
            $("favor-sub").innerHTML = overrideFavor === "LONG" ? "Chercher des achats" : overrideFavor === "SHORT" ? "Chercher des ventes" : "Attendre signal";
            $("favor-sub").innerHTML += '<div style="font-size:0.625rem;color:var(--orange);margin-top:2px;">MTF override (' + mtfVerdict + ')</div>';
        }
    }

    function renderMtfBias(d) {
        var verdictEl = $("mtf-verdict");
        var gridEl = $("mtf-grid");
        if (!verdictEl || !gridEl || !d.timeframes) return;

        // Verdict
        var isForte = d.verdict && (d.verdict.indexOf("FORT") >= 0);
        var isBull = d.verdict && (d.verdict.indexOf("ACHAT") >= 0);
        var isBear = d.verdict && (d.verdict.indexOf("VENTE") >= 0);
        var vColor = isBull ? "var(--green)" : isBear ? "var(--red)" : "var(--gold)";
        verdictEl.textContent = d.verdict || "--";
        verdictEl.style.color = vColor;
        if (isForte) {
            verdictEl.style.textShadow = "0 0 12px " + (isBull ? "rgba(0,200,83,0.5)" : "rgba(255,82,82,0.5)");
        } else {
            verdictEl.style.textShadow = "none";
        }

        // Grid : 4 colonnes (1m, 5m, 15m, 1h)
        var tfOrder = ["1m", "5m", "15m", "1h"];
        var html = "";
        tfOrder.forEach(function (tf) {
            var bias = d.timeframes[tf] || {};
            var score = bias.score || 0;
            var label = bias.label || "N/A";
            var factors = bias.factors || {};
            var bgColor = label === "BULL" ? "var(--green-dim)" : label === "BEAR" ? "var(--red-dim)" : "rgba(255,255,255,0.03)";
            var txtColor = label === "BULL" ? "var(--green)" : label === "BEAR" ? "var(--red)" : "var(--text-secondary)";
            var borderColor = label === "BULL" ? "rgba(0,200,83,0.3)" : label === "BEAR" ? "rgba(255,82,82,0.3)" : "var(--border)";

            html += '<div style="background:' + bgColor + ';border:1px solid ' + borderColor + ';border-radius:8px;padding:10px;text-align:center;">';
            html += '<div style="font-size:0.75rem;color:var(--text-disabled);font-weight:600;">' + tf.toUpperCase() + '</div>';
            html += '<div style="font-size:1.25rem;font-weight:800;color:' + txtColor + ';margin:4px 0;">' + label + '</div>';
            html += '<div class="mono" style="font-size:0.75rem;color:' + txtColor + ';">' + (score > 0 ? "+" : "") + score.toFixed(2) + '</div>';
            html += '<div style="margin-top:6px;font-size:0.625rem;color:var(--text-disabled);">';
            html += 'V:' + fmt(factors.vwap, 1) + ' D:' + fmt(factors.delta, 1) + ' M:' + fmt(factors.momentum, 1);
            html += '</div></div>';
        });
        gridEl.innerHTML = html;
    }

    // ═══════════════════════════════════════════════════════════════
    // Confluence Finder + Conseil Global
    // ═══════════════════════════════════════════════════════════════

    function renderConfluence() {
        var instr = getInstr(currentInstrument === "BOTH" ? "ES" : currentInstrument);
        if (!instr) return;
        var banner = data.banner || {};
        var sym = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var price = banner[sym] ? banner[sym].price : 0;
        if (!price) return;

        // Collecter tous les niveaux avec prix
        var levels = [];
        function addLevel(name, p, type) { if (p && p > 0) levels.push({ name: name, price: p, type: type }); }

        if (instr.options) {
            var o = instr.options;
            addLevel("Call Wall", o.call_wall_price, "options");
            addLevel("Put Wall", o.put_wall_price, "options");
            addLevel("HVL", o.hvl_price, "options");
            addLevel("0DTE Call", o.call_0dte_price, "options");
            addLevel("0DTE Put", o.put_0dte_price, "options");
        }
        if (instr.market_profile) {
            var mp = instr.market_profile;
            addLevel("VPOC", mp.cur_vpoc_price, "profile");
            addLevel("VAH", mp.cur_vah_price, "profile");
            addLevel("VAL", mp.cur_val_price, "profile");
            addLevel("pVPOC", mp.prev_vpoc_price, "profile");
            addLevel("pVAH", mp.prev_vah_price, "profile");
            addLevel("pVAL", mp.prev_val_price, "profile");
        }
        if (instr.levels) {
            var lv = instr.levels;
            addLevel("VWAP D", lv.vwap_d_price, "vwap");
            addLevel("SD1+", lv.vwap_d_sd1u_price, "vwap");
            addLevel("SD1-", lv.vwap_d_sd1d_price, "vwap");
            addLevel("SD2+", lv.vwap_d_sd2u_price, "vwap");
            addLevel("SD2-", lv.vwap_d_sd2d_price, "vwap");
            addLevel("Swing H", lv.swing_high_price, "swing");
            addLevel("Swing L", lv.swing_low_price, "swing");
        }
        if (instr.initial_balance) {
            var ib = instr.initial_balance;
            addLevel("IB H", ib.ib_high_price, "ib");
            addLevel("IB L", ib.ib_low_price, "ib");
        }

        // Trouver clusters (niveaux a moins de 8 ticks = 2 points)
        var CLUSTER_TICKS = (currentInstrument === "NQ" || sym === "nq") ? 24 : 8;
        var clusterDist = CLUSTER_TICKS * 0.25;
        levels.sort(function (a, b) { return a.price - b.price; });

        var clusters = [];
        var used = {};
        for (var i = 0; i < levels.length; i++) {
            if (used[i]) continue;
            var cluster = [levels[i]];
            used[i] = true;
            for (var j = i + 1; j < levels.length; j++) {
                if (used[j]) continue;
                if (Math.abs(levels[j].price - levels[i].price) <= clusterDist) {
                    cluster.push(levels[j]);
                    used[j] = true;
                }
            }
            if (cluster.length >= 2) {
                var avgPrice = cluster.reduce(function (s, l) { return s + l.price; }, 0) / cluster.length;
                var distTicks = Math.round((avgPrice - price) / 0.25);
                var types = {};
                cluster.forEach(function (l) { types[l.type] = true; });
                clusters.push({
                    price: avgPrice,
                    count: cluster.length,
                    levels: cluster,
                    dist: distTicks,
                    types: Object.keys(types).length,
                    side: distTicks > 0 ? "RESISTANCE" : "SUPPORT",
                });
            }
        }
        clusters.sort(function (a, b) { return Math.abs(a.dist) - Math.abs(b.dist); });

        // Render
        var el = $("confluence-zones");
        if (!el) return;
        var html = "";
        if (clusters.length === 0) {
            html = '<div style="color:var(--text-disabled);font-size:0.8125rem;">Pas de confluence detectee</div>';
        } else {
            clusters.slice(0, 5).forEach(function (c) {
                var sideColor = c.side === "SUPPORT" ? "var(--green)" : "var(--red)";
                var strength = c.count >= 4 ? "TRES FORT" : c.count >= 3 ? "FORT" : "MODERE";
                var strengthCls = c.count >= 4 ? "badge-red" : c.count >= 3 ? "badge-orange" : "badge-gray";
                html += '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03);">';
                html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
                html += '<span style="color:' + sideColor + ';font-weight:700;">' + c.side + '</span>';
                html += '<span class="mono" style="font-weight:600;">' + c.price.toFixed(2) + ' <span style="color:var(--text-disabled);">(' + (c.dist > 0 ? "+" : "") + c.dist + 't)</span></span>';
                html += badgeHtml(strength + " (" + c.count + ")", strengthCls);
                html += '</div>';
                html += '<div style="font-size:0.6875rem;color:var(--text-disabled);margin-top:2px;">';
                html += c.levels.map(function (l) { return l.name; }).join(" + ");
                html += '</div></div>';
            });
        }
        el.innerHTML = html;

        // Conseil Global
        renderGlobalAdvice(clusters, instr);
    }

    function renderGlobalAdvice(clusters, instr) {
        var banner = data.banner || {};
        var sym = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var price = banner[sym] ? banner[sym].price : 0;
        var of = instr.order_flow || {};
        var reg = instr.regime || {};

        var checks = [];
        var bullPoints = 0;
        var bearPoints = 0;

        // 1. Bias regime
        var bias = reg.bias || "NEUTRAL";
        checks.push({ name: "Bias regime: " + bias, ok: bias !== "NEUTRAL", bull: bias === "BULLISH" });
        if (bias === "BULLISH") bullPoints += 2;
        if (bias === "BEARISH") bearPoints += 2;

        // 2. Delta direction
        var deltaDir = of.delta_day_dir || 0;
        checks.push({ name: "Delta jour: " + (deltaDir > 0 ? "acheteurs" : deltaDir < 0 ? "vendeurs" : "neutre"), ok: deltaDir !== 0, bull: deltaDir > 0 });
        if (deltaDir > 0) bullPoints++;
        if (deltaDir < 0) bearPoints++;

        // 3. RVOL
        var rvol = of.rvol || 0;
        checks.push({ name: "RVOL: " + fmt(rvol, 1) + "x", ok: rvol >= 0.8, bull: true });

        // 4. Support/Resistance proches
        var nearSupport = clusters.filter(function (c) { return c.side === "SUPPORT" && Math.abs(c.dist) <= 30; });
        var nearResist = clusters.filter(function (c) { return c.side === "RESISTANCE" && Math.abs(c.dist) <= 30; });
        if (nearSupport.length > 0) {
            checks.push({ name: "Support proche: " + nearSupport[0].price.toFixed(2) + " (" + nearSupport[0].count + " niveaux)", ok: true, bull: true });
            bullPoints++;
        }
        if (nearResist.length > 0) {
            checks.push({ name: "Resistance proche: " + nearResist[0].price.toFixed(2) + " (" + nearResist[0].count + " niveaux)", ok: true, bull: false });
            bearPoints++;
        }

        // 5. Position range
        var rangePos = reg.range_pos || 50;
        var rpLabel = rangePos >= 70 ? "HAUT (favorise vente)" : rangePos <= 30 ? "BAS (favorise achat)" : "MILIEU";
        checks.push({ name: "Position range: " + Math.round(rangePos) + "% — " + rpLabel, ok: rangePos <= 30 || rangePos >= 70, bull: rangePos <= 30 });
        if (rangePos <= 30) bullPoints++;
        if (rangePos >= 70) bearPoints++;

        // 6. MTF Confluence (poids 2 si 4/4, 1 si 3/4)
        var mtfBulls = reg.mtf_bulls || 0;
        var mtfBears = reg.mtf_bears || 0;
        var mtfVerdict = reg.mtf_verdict || "N/A";
        if (mtfBulls >= 3 || mtfBears >= 3) {
            var mtfWeight = (mtfBulls === 4 || mtfBears === 4) ? 2 : 1;
            checks.push({ name: "MTF: " + mtfVerdict, ok: true, bull: mtfBulls >= 3 });
            if (mtfBulls >= 3) bullPoints += mtfWeight;
            if (mtfBears >= 3) bearPoints += mtfWeight;
        }

        // 7. Divergence forte = signal contrarian
        var divGrade = reg.div_grade || "NONE";
        var divQ = reg.div_quality || 0;
        if (divGrade === "EXTREME" || divGrade === "FORTE") {
            var divBull = rangePos <= 30; // div au bottom = bull
            checks.push({ name: "DIV " + divGrade + " (" + fmt(divQ, 0) + "/10)", ok: true, bull: divBull });
            if (divBull) bullPoints += 2; else bearPoints += 2;
        }

        // Verdict — seuils ajustes pour les nouveaux facteurs
        var action, actionColor;
        var conflict = bullPoints >= 3 && bearPoints >= 3;
        if (conflict) {
            action = "CONFLIT"; actionColor = "var(--orange)";
        } else if (bullPoints >= 5 && bearPoints <= 2) {
            action = "ACHAT"; actionColor = "var(--green)";
        } else if (bearPoints >= 5 && bullPoints <= 2) {
            action = "VENTE"; actionColor = "var(--red)";
        } else if (bullPoints >= 4 && bearPoints <= 2) {
            action = "ACHAT PRUDENT"; actionColor = "var(--green)";
        } else if (bearPoints >= 4 && bullPoints <= 2) {
            action = "VENTE PRUDENTE"; actionColor = "var(--red)";
        } else {
            action = "ATTENDRE"; actionColor = "var(--gold)";
        }

        var reason = bullPoints + " signaux bull / " + bearPoints + " signaux bear";

        // v1.5 (22/04 fix bug Jackson) : freshness backend = NEW/PERSISTENT/EXPIRED/IDLE.
        // Distingue EVENEMENT (transition a l'instant T) de ETAT (persistance).
        // Fix : signal ACHAT ne doit pas etre affiche comme "nouveau" pendant 15 min.
        var symKeyCG = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var cgBackend = (data && data.conseil_global) ? data.conseil_global[symKeyCG] : null;
        var freshness = cgBackend ? (cgBackend.freshness || "IDLE") : "IDLE";
        var ageBars = cgBackend ? (cgBackend.age_bars || 0) : 0;

        var displayAction = action;
        var displayColor = actionColor;
        var freshBadge = "";

        if (freshness === "EXPIRED") {
            displayAction = "ATTENDRE";
            displayColor = "var(--text-disabled)";
            freshBadge = ' <span style="font-size:0.75rem;color:var(--red);background:rgba(213,0,0,0.15);padding:2px 8px;border-radius:4px;margin-left:8px;">&#9888; EXPIRE (' + ageBars + ' barres)</span>';
        } else if (freshness === "PERSISTENT") {
            freshBadge = ' <span style="font-size:0.75rem;color:var(--text-secondary);background:rgba(148,163,184,0.15);padding:2px 8px;border-radius:4px;margin-left:8px;">&#9203; ' + ageBars + ' barre' + (ageBars > 1 ? 's' : '') + '</span>';
        } else if (freshness === "NEW" && (action === "ACHAT" || action === "VENTE" || action === "ACHAT PRUDENT" || action === "VENTE PRUDENTE")) {
            freshBadge = ' <span style="font-size:0.75rem;color:var(--green);background:rgba(0,200,83,0.15);padding:2px 8px;border-radius:4px;margin-left:8px;font-weight:700;animation:pulse 1.2s infinite;">&#9889; NOUVEAU</span>';
        }

        $("global-action").innerHTML = displayAction + freshBadge;
        $("global-action").style.color = displayColor;
        $("global-reason").textContent = reason;

        var checkHtml = "";
        checks.forEach(function (c) {
            var icon = c.ok ? (c.bull ? "&#9650;" : "&#9660;") : "&#8212;";
            var color = c.ok ? (c.bull ? "var(--green)" : "var(--red)") : "var(--text-disabled)";
            checkHtml += '<div style="padding:2px 0;font-size:0.75rem;"><span style="color:' + color + ';margin-right:6px;">' + icon + '</span>' + c.name + '</div>';
        });
        $("global-checklist").innerHTML = checkHtml;

        // Patterns (Double Bottom / Double Top)
        renderPatterns();
    }

    function renderPatterns() {
        var el = $("patterns-section");
        if (!el || !data || !data.patterns) { if (el) el.innerHTML = ""; return; }

        var sym = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var p = data.patterns[sym];
        if (!p || !p.detected) {
            el.innerHTML = '<div style="color:var(--text-disabled);font-size:0.8125rem;">Aucun pattern multi-session detecte</div>';
            return;
        }

        var h = "";
        (p.patterns || []).forEach(function (pat) {
            var isBottom = pat.type === "DOUBLE_BOTTOM";
            var icon = isBottom ? "W" : "M";
            var color = isBottom ? "var(--green)" : "var(--red)";
            var bgColor = isBottom ? "rgba(0,200,83,0.08)" : "rgba(255,82,82,0.08)";
            var borderColor = isBottom ? "rgba(0,200,83,0.3)" : "rgba(255,82,82,0.3)";
            var statusColor = pat.status === "CASSE" ? "var(--green)" : pat.status === "EN ROUTE" ? "var(--gold)" : "var(--text-secondary)";
            var label = isBottom ? "DOUBLE BOTTOM" : "DOUBLE TOP";

            h += '<div style="border:1px solid ' + borderColor + ';border-radius:8px;padding:12px;margin-bottom:8px;background:' + bgColor + ';">';
            h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
            h += '<div style="display:flex;align-items:center;gap:8px;">';
            h += '<span style="font-size:1.5rem;font-weight:900;color:' + color + ';">' + icon + '</span>';
            h += '<span style="font-weight:700;color:' + color + ';">' + label + '</span>';
            h += '</div>';
            h += badgeHtml(pat.status, pat.status === "CASSE" ? "badge-green" : pat.status === "EN ROUTE" ? "badge-gold" : "badge-gray");
            h += '</div>';

            if (isBottom) {
                h += kvRow("Bottom 1", pat.bottom_1.date + " @ " + fmtPrice(pat.bottom_1.price));
                h += kvRow("Bottom 2", pat.bottom_2.date + " @ " + fmtPrice(pat.bottom_2.price));
                h += kvRow("Ecart", fmt(pat.diff_ticks, 0) + " ticks");
            } else {
                h += kvRow("Top 1", pat.top_1.date + " @ " + fmtPrice(pat.top_1.price));
                h += kvRow("Top 2", pat.top_2.date + " @ " + fmtPrice(pat.top_2.price));
                h += kvRow("Ecart", fmt(pat.diff_ticks, 0) + " ticks");
            }
            h += kvRow("Neckline", fmtPrice(pat.neckline) + " (" + (pat.dist_neckline >= 0 ? "+" : "") + pat.dist_neckline + "t)");
            h += kvRow("Target", fmtPrice(pat.target));

            if (pat.retest_neckline) {
                h += '<div style="margin-top:6px;padding:6px;border-radius:4px;background:rgba(212,175,55,0.15);color:var(--gold);font-weight:700;font-size:0.8125rem;text-align:center;">RETEST NECKLINE — Zone d\'entree potentielle</div>';
            }
            if (pat.status === "CASSE") {
                h += '<div style="margin-top:6px;font-size:0.75rem;color:var(--text-secondary);">Neckline cassee — chercher les retests pour entrer dans la direction du pattern</div>';
            }
            h += '</div>';
        });

        // Intraday patterns
        var pi = data.patterns_intraday ? data.patterns_intraday[sym] : null;
        if (pi && pi.detected) {
            h += '<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);">';
            h += '<div style="font-weight:600;font-size:0.8125rem;color:var(--gold);margin-bottom:8px;">Intraday (session du jour)</div>';
            (pi.patterns || []).slice(0, 3).forEach(function (pat) {
                var isBottom = pat.type === "DOUBLE_BOTTOM";
                var color = isBottom ? "var(--green)" : "var(--red)";
                var icon = isBottom ? "W" : "M";
                var volIcon = pat.vol_confirmed ? "&#10003;" : "&#10007;";
                var volColor = pat.vol_confirmed ? "var(--green)" : "var(--red)";
                var divIcon = pat.delta_div ? "&#10003; DIV" : "";

                h += '<div style="border:1px solid rgba(255,255,255,0.06);border-radius:6px;padding:8px;margin-bottom:6px;">';
                h += '<div style="display:flex;justify-content:space-between;align-items:center;">';
                h += '<span style="font-weight:700;color:' + color + ';">' + icon + ' ' + pat.type.replace("_", " ") + '</span>';
                h += badgeHtml("Q:" + pat.quality + "/8", pat.quality >= 6 ? "badge-green" : pat.quality >= 4 ? "badge-gold" : "badge-gray");
                h += '</div>';

                var p1 = isBottom ? pat.low_1 : pat.high_1;
                var p2 = isBottom ? pat.low_2 : pat.high_2;
                h += '<div style="font-size:0.75rem;color:var(--text-secondary);margin-top:4px;">';
                h += fmtPrice(p1.price) + ' → ' + fmtPrice(p2.price) + ' (ecart ' + fmt(pat.diff_ticks, 0) + 't)';
                h += ' | Neck: ' + fmtPrice(pat.neckline);
                h += '</div>';

                // Confirmations
                h += '<div style="display:flex;gap:12px;margin-top:4px;font-size:0.6875rem;">';
                h += '<span style="color:' + volColor + ';">' + volIcon + ' Vol x' + fmt(pat.vol_ratio, 1) + '</span>';
                h += '<span style="color:' + (pat.delta_confirmed ? "var(--green)" : "var(--text-disabled)") + ';">' + (pat.delta_confirmed ? "&#10003;" : "&#10007;") + ' Delta</span>';
                if (pat.delta_div) {
                    h += '<span style="color:var(--gold);font-weight:700;">&#9733; Delta Div</span>';
                }
                h += '<span>' + badgeHtml(pat.status, pat.status === "CASSE" ? "badge-green" : "badge-gold") + '</span>';
                h += '</div>';

                if (pat.delta_div && pat.vol_confirmed) {
                    h += '<div style="margin-top:4px;padding:4px 8px;border-radius:4px;background:rgba(0,200,83,0.1);color:var(--green);font-size:0.75rem;font-weight:600;">SETUP A+ : Volume confirme + Delta Divergence</div>';
                }
                h += '</div>';
            });
            h += '</div>';
        }

        el.innerHTML = h;
    }

    // ═══════════════════════════════════════════════════════════════
    // PAGE: OPTIONS & GAMMA
    // ═══════════════════════════════════════════════════════════════

    function renderOptions() {
        var es = getInstr("ES");
        var nq = getInstr("NQ");
        var ci = currentInstrument;

        // Corridor visuel — suit le selecteur
        var corrEs = $("corridor-es");
        var corrNq = $("corridor-nq");
        if (corrEs) corrEs.innerHTML = "";
        if (corrNq) corrNq.innerHTML = "";

        if ((ci === "ES" || ci === "BOTH") && es && es.options) {
            var eO = es.options;
            var eB = data.banner ? data.banner.es : {};
            corrEs.innerHTML = (ci === "BOTH" ? '<div style="font-weight:600;color:#0fbf84;margin-bottom:4px;font-size:0.75rem;">ES</div>' : '') +
                corridorBar(eO.put_wall_price, eO.call_wall_price, eB.price, eO.hvl_price);
        }
        if ((ci === "NQ" || ci === "BOTH") && nq && nq.options) {
            var nO = nq.options;
            var nB = data.banner ? data.banner.nq : {};
            corrNq.innerHTML = (ci === "BOTH" ? '<div style="font-weight:600;color:#4a9eff;margin-bottom:4px;font-size:0.75rem;">NQ</div>' : '') +
                corridorBar(nO.put_wall_price, nO.call_wall_price, nB.price, nO.hvl_price);
        }

        // Next Wall (from selected instrument)
        var sel = currentInstrument === "BOTH" ? es : getInstr(currentInstrument);
        if (sel && sel.options) {
            var o = sel.options;
            $("nw-price").textContent = fmtPrice(o.next_wall_price);
            $("nw-price").style.color = o.next_wall_side === "PUT" ? "var(--green)" : "var(--red)";
            $("nw-side").textContent = o.next_wall_side;
            $("nw-side").className = "badge " + (o.next_wall_side === "PUT" ? "badge-green" : "badge-red");
            $("nw-dist").textContent = fmt(o.next_wall_dist, 0) + " ticks";
            $("next-wall-box").style.borderColor = o.next_wall_side === "PUT" ? "var(--green)" : "var(--red)";
        }

        function renderOptionsPanel(el, instr) {
            if (!instr || !instr.options) { el.innerHTML = ""; return; }
            var o = instr.options;
            var h = "";
            h += kvRow("Call Wall", fmtPrice(o.call_wall_price), "red");
            h += kvRow("Put Wall", fmtPrice(o.put_wall_price), "green");
            h += kvRow("HVL", fmtPrice(o.hvl_price), "cyan");
            h += kvRow("0DTE Call", fmtPrice(o.call_0dte_price), "red");
            h += kvRow("0DTE Put", fmtPrice(o.put_0dte_price), "green");
            h += kvRow("GEX Up", fmtPrice(o.gex_up_price), "red");
            h += kvRow("GEX Down", fmtPrice(o.gex_dn_price), "green");
            h += kvRow("GEX Clusters", fmtInt(o.gex_cluster_count));
            h += kvRow("GEX Flip Zone", boolBadge(o.gex_flip_zone, "Dans la flip zone", "Hors zone"));
            h += kvRow("Au-dessus HVL", boolBadge(o.bool_above_mq_hvl, "Au-dessus — gamma calme", "En-dessous — gamma amplifie"));
            h += kvRow("Au-dessus Call", boolBadge(o.bool_above_mq_call, "Au-dessus du Call Wall !", "Sous le Call Wall"));
            el.innerHTML = h;
        }

        renderOptionsPanel($("options-es-rows"), es);
        renderOptionsPanel($("options-nq-rows"), nq);

        // VIX Gamma
        var vixHtml = "";
        if (es && es.vix_gamma) {
            var v = es.vix_gamma;
            var col1 = kvRow("VIX Level", fmt(v.vix_level, 2)) + kvRow("Regime", v.vix_regime_label) + kvRow("Call Wall", fmt(v.vix_call_price, 2), "red") + kvRow("Put Wall", fmt(v.vix_put_price, 2), "green") + kvRow("HVL", fmt(v.vix_hvl_price, 2), "cyan") + kvRow("Au-dessus HVL", boolBadge(v.vix_above_hvl, "Zone calme", "Zone volatile"));
            var col2 = kvRow("0DTE Call", fmt(v.vix_call_0dte_price, 2), "red") + kvRow("0DTE Put", fmt(v.vix_put_0dte_price, 2), "green") + kvRow("0DTE HVL", fmt(v.vix_hvl_0dte_price, 2)) + kvRow("GEX Up", fmt(v.vix_gex_up_price, 2), "red") + kvRow("GEX Down", fmt(v.vix_gex_dn_price, 2), "green") + kvRow("Au-dessus HVL 0DTE", boolBadge(v.vix_above_hvl_0dte, "Zone calme 0DTE", "Zone volatile 0DTE"));
            vixHtml = '<div>' + col1 + '</div><div>' + col2 + '</div>';
        }
        $("vix-gamma-grid").innerHTML = vixHtml;

        // GEX comparison
        var gexHtml = "";
        if (es && es.options && nq && nq.options) {
            var eO = es.options, nO = nq.options;
            var col1 = '<div class="card-title" style="margin:0 0 8px;">ES</div>' + kvRow("GEX Up", fmtPrice(eO.gex_up_price) + " (" + fmt(eO.dist_gex_up, 0) + "t)") + kvRow("GEX Dn", fmtPrice(eO.gex_dn_price) + " (" + fmt(eO.dist_gex_dn, 0) + "t)") + kvRow("Clusters", fmtInt(eO.gex_cluster_count)) + kvRow("Flip Zone", boolBadge(eO.gex_flip_zone, "Dans la flip zone", "Hors zone"));
            var col2 = '<div class="card-title" style="margin:0 0 8px;">NQ</div>' + kvRow("GEX Up", fmtPrice(nO.gex_up_price) + " (" + fmt(nO.dist_gex_up, 0) + "t)") + kvRow("GEX Dn", fmtPrice(nO.gex_dn_price) + " (" + fmt(nO.dist_gex_dn, 0) + "t)") + kvRow("Clusters", fmtInt(nO.gex_cluster_count)) + kvRow("Flip Zone", boolBadge(nO.gex_flip_zone, "Dans la flip zone", "Hors zone"));
            gexHtml = '<div>' + col1 + '</div><div>' + col2 + '</div>';
        }
        $("gex-grid").innerHTML = gexHtml;
    }

    // ═══════════════════════════════════════════════════════════════
    // ORDER FLOW — Sub-renderers (pour mode BOTH)
    // ═══════════════════════════════════════════════════════════════

    function renderDomHtml(instr, label) {
        if (!instr || !instr.order_flow) return '<div style="color:var(--text-disabled);">Pas de donnees</div>';
        var of = instr.order_flow;
        var askPct = Math.round((of.ask_pct || 0.5) * 100);
        var bidPct = 100 - askPct;
        var dominant = askPct > 60 ? "Forte pression acheteuse" : askPct > 55 ? "Legere pression acheteuse" : bidPct > 60 ? "Forte pression vendeuse" : bidPct > 55 ? "Legere pression vendeuse" : "Equilibre bid/ask";
        var domColor = askPct > 55 ? "var(--green)" : bidPct > 55 ? "var(--red)" : "var(--text-secondary)";
        return (label ? '<div style="text-align:center;font-weight:700;margin-bottom:8px;color:' + (label === "ES" ? "#0fbf84" : "#4a9eff") + ';">' + label + '</div>' : '') +
            '<div class="dom-grid">' +
            '<div class="dom-side dom-buyers"><div class="dom-label">Acheteurs agressifs</div><div class="dom-pct" style="color:var(--green);">' + askPct + '%</div></div>' +
            '<div class="dom-center"><div class="dom-label">Flux dominant</div><div style="font-size:1.1rem;font-weight:800;color:' + domColor + ';">' + dominant + '</div><div style="margin-top:6px;"><div class="gauge"><div class="gauge-fill" style="width:' + askPct + '%;background:linear-gradient(90deg, var(--red), var(--green));"></div></div></div></div>' +
            '<div class="dom-side dom-sellers"><div class="dom-label">Vendeurs agressifs</div><div class="dom-pct" style="color:var(--red);">' + bidPct + '%</div></div></div>';
    }

    function renderDeltaHtml(instr) {
        if (!instr || !instr.order_flow) return "";
        var of = instr.order_flow;
        var h = "";
        // Barre visuelle delta (0 = neutre, pas bear)
        var deltaPctVal = of.delta_pct || 0;
        var deltaPctAbs = Math.abs(deltaPctVal);
        var deltaColor = deltaPctVal > 0 ? "var(--green)" : deltaPctVal < 0 ? "var(--red)" : "var(--text-secondary)";
        h += '<div style="text-align:center;margin-bottom:8px;">';
        h += '<span style="font-size:1.5rem;font-weight:800;color:' + deltaColor + ';">' + (of.delta_bar > 0 ? "+" : "") + fmtInt(of.delta_bar) + '</span>';
        h += '<span style="font-size:0.75rem;color:var(--text-disabled);margin-left:8px;">delta bar</span>';
        h += '</div>';
        h += hBar("Delta %", deltaPctAbs, 0.5, deltaColor, fmtPct(deltaPctVal));
        h += kvRow("Delta Day", fmtInt(of.delta_day), colorClass(of.delta_day));
        h += kvRow("Delta Dir", of.delta_day_dir > 0 ? "Acheteurs accumulent" : of.delta_day_dir < 0 ? "Vendeurs distribuent" : "Pas de direction", colorClass(of.delta_day_dir));
        h += kvRow("CVD Day", fmtInt(of.cvd_day), colorClass(of.cvd_day));
        // CVD Dir : 0 = neutre (pas "distribution nette")
        h += kvRow("CVD Dir", of.cvd_day_dir > 0 ? "Accumulation nette" : of.cvd_day_dir < 0 ? "Distribution nette" : "Neutre", colorClass(of.cvd_day_dir));
        h += kvRow("Div P/D", of.delta_divergence ? badgeHtml("Divergence detectee !", "badge-orange") : badgeHtml("Prix et delta alignes", "badge-green"));
        // Climax acheteur = exces bull = signal de RETOURNEMENT bearish (warning orange)
        h += kvRow("Climax", of.climax_signal > 0 ? badgeHtml("Climax acheteur — reversal?", "badge-orange") : of.climax_signal < 0 ? badgeHtml("Climax vendeur — reversal?", "badge-orange") : badgeHtml("Pas de climax", "badge-gray"));
        return h;
    }

    function renderRvolHtml(instr) {
        if (!instr || !instr.order_flow) return "";
        var of = instr.order_flow;
        var h = "";
        var rvolPct = Math.min((of.rvol || 0) / 4 * 100, 100);
        h += kvRow("RVOL", fmt(of.rvol, 2), of.rvol > 2 ? "red" : of.rvol > 1 ? "orange" : "");
        h += '<div style="margin:6px 0;"><div class="gauge"><div class="gauge-fill gauge-' + (of.rvol > 2 ? "red" : of.rvol > 1 ? "gold" : "cyan") + '" style="width:' + rvolPct + '%;"></div></div></div>';
        h += kvRow("Regime", badgeHtml(of.rvol_regime_label, of.rvol > 2 ? "badge-red" : of.rvol > 1 ? "badge-orange" : "badge-cyan"));
        h += kvRow("Volume", fmtInt(of.total_vol));
        h += kvRow("Buy/Sell", fmtInt(of.buy_vol) + " / " + fmtInt(of.sell_vol));
        h += kvRow("Ratio", fmtPct(of.buy_sell_ratio));
        h += kvRow("LTR", fmt(of.large_trader_ratio, 2));
        h += kvRow("Finish", fmt(of.finish_strength, 1), colorClass(of.finish_strength));
        return h;
    }

    function renderBnHtml(instr) {
        if (!instr || !instr.battle_navale) return "";
        var bn = instr.battle_navale;
        var h = "";
        h += kvRow("Score Raw", fmt(bn.bn_score_raw, 2), colorClass(bn.bn_score_raw));
        h += kvRow("Bull / Bear", fmt(bn.bn_score_bull, 2) + " / " + fmt(bn.bn_score_bear, 2));
        h += kvRow("Absorb A/B", boolBadge(bn.bn_absorb_ask, "Ask absorbe", "Non") + " " + boolBadge(bn.bn_absorb_bid, "Bid absorbe", "Non"));
        h += kvRow("Pressure A/B", fmt(bn.bn_pressure_ask, 1) + " / " + fmt(bn.bn_pressure_bid, 1));
        h += kvRow("Edge Buy/Sell", boolBadge(bn.bar_edge_buy, "Edge achat", "Non") + " " + boolBadge(bn.bar_edge_sell, "Edge vente", "Non"));
        h += kvRow("Color Up/Dn", boolBadge(bn.bn_color_up, "Signal haussier", "Non") + " " + boolBadge(bn.bn_color_dn, "Signal baissier", "Non"));
        h += kvRow("Rotation", fmt(bn.rotation_up, 0) + " / " + fmt(bn.rotation_dn, 0));
        return h;
    }

    function renderBigOrdersHtml(instr) {
        if (!instr || !instr.big_orders) return "";
        var bo = instr.big_orders;
        var h = '<div class="grid-2"><div>';
        h += '<div style="font-weight:600;margin-bottom:4px;color:var(--green);font-size:0.75rem;">ASK</div>';
        h += kvRow("T1/T2", fmtInt(bo.n_big_ask_t1) + " / " + fmtInt(bo.n_big_ask_t2));
        h += kvRow("T3/T4", fmtInt(bo.n_big_ask_t3) + " / " + fmtInt(bo.n_big_ask_t4));
        h += kvRow("Cluster", fmtInt(bo.big_ask_cluster_20t));
        h += '</div><div>';
        h += '<div style="font-weight:600;margin-bottom:4px;color:var(--red);font-size:0.75rem;">BID</div>';
        h += kvRow("T1/T2", fmtInt(bo.n_big_bid_t1) + " / " + fmtInt(bo.n_big_bid_t2));
        h += kvRow("T3/T4", fmtInt(bo.n_big_bid_t3) + " / " + fmtInt(bo.n_big_bid_t4));
        h += kvRow("Cluster", fmtInt(bo.big_bid_cluster_20t));
        h += '</div></div>';
        return h;
    }

    // ═══════════════════════════════════════════════════════════════
    // PAGE: ORDER FLOW
    // ═══════════════════════════════════════════════════════════════

    function renderOrderFlow() {
        if (currentInstrument === "BOTH") {
            // Mode BOTH : ES a gauche, NQ a droite pour chaque section
            var esI = getInstr("ES"), nqI = getInstr("NQ");
            $("dom-grid").innerHTML = '<div class="grid-2">' +
                '<div>' + renderDomHtml(esI, "ES") + '</div>' +
                '<div>' + renderDomHtml(nqI, "NQ") + '</div></div>';
            $("delta-rows").innerHTML = '<div class="grid-2">' +
                '<div><div style="font-weight:700;color:#0fbf84;margin-bottom:8px;">ES</div>' + renderDeltaHtml(esI) + '</div>' +
                '<div><div style="font-weight:700;color:#4a9eff;margin-bottom:8px;">NQ</div>' + renderDeltaHtml(nqI) + '</div></div>';
            $("rvol-rows").innerHTML = '<div class="grid-2">' +
                '<div><div style="font-weight:700;color:#0fbf84;margin-bottom:8px;">ES</div>' + renderRvolHtml(esI) + '</div>' +
                '<div><div style="font-weight:700;color:#4a9eff;margin-bottom:8px;">NQ</div>' + renderRvolHtml(nqI) + '</div></div>';
            $("bn-grid").innerHTML = '<div class="grid-2">' +
                '<div><div style="font-weight:700;color:#0fbf84;margin-bottom:8px;">ES</div>' + renderBnHtml(esI) + '</div>' +
                '<div><div style="font-weight:700;color:#4a9eff;margin-bottom:8px;">NQ</div>' + renderBnHtml(nqI) + '</div></div>';
            $("big-orders-content").innerHTML = '<div class="grid-2">' +
                '<div><div style="font-weight:700;color:#0fbf84;margin-bottom:8px;">ES</div>' + renderBigOrdersHtml(esI) + '</div>' +
                '<div><div style="font-weight:700;color:#4a9eff;margin-bottom:8px;">NQ</div>' + renderBigOrdersHtml(nqI) + '</div></div>';
            return;
        }

        var instr = getInstr(currentInstrument);
        if (!instr || !instr.order_flow) return;
        var of = instr.order_flow;

        // Single instrument — use sub-renderers
        $("dom-grid").innerHTML = renderDomHtml(instr);
        $("delta-rows").innerHTML = renderDeltaHtml(instr);
        $("rvol-rows").innerHTML = renderRvolHtml(instr);
        $("bn-grid").innerHTML = renderBnHtml(instr);
        $("big-orders-content").innerHTML = renderBigOrdersHtml(instr);
    }

    // ═══════════════════════════════════════════════════════════════
    // PAGE: MARKET PROFILE
    // ═══════════════════════════════════════════════════════════════

    var vpLoaded = false;
    var vpLastLoad = 0;
    var mqLastLoad = 0;
    var vpCanvasState = {}; // zoom/pan state per canvas

    function loadVolumeProfile() {
        var sym = currentInstrument === "BOTH" ? "ES" : currentInstrument;
        fetch(API_BASE + "/api/profile/" + sym, { headers: apiHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                drawVolumeProfileCanvas("vp-today-canvas", d.today, d.today_levels);
                drawVolumeProfileCanvas("vp-yesterday-canvas", d.yesterday, d.yesterday_levels);
                vpLoaded = true;
                vpLastLoad = Date.now();
            })
            .catch(function (err) { console.error("VP error:", err); });
    }

    function drawVolumeProfileCanvas(canvasId, profile, levels) {
        var canvas = $(canvasId);
        if (!canvas || !profile || !profile.length) return;

        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var W = rect.width, H = rect.height;

        var poc = levels ? levels.poc : null;
        var vah = levels ? levels.vah : null;
        var valP = levels ? levels.val : null;
        var vpocPrev = levels ? levels.vpoc_prev : null;
        var vahPrev = levels ? levels.vah_prev : null;
        var valPrev = levels ? levels.val_prev : null;

        // State zoom/pan
        if (!vpCanvasState[canvasId]) {
            vpCanvasState[canvasId] = { zoom: 1, offsetY: 0, dragging: false, lastY: 0, profile: profile, levels: levels, initialized: false };
        }
        var st = vpCanvasState[canvasId];
        st.profile = profile;
        st.levels = levels;

        var marginLeft = 120;
        var marginRight = 80;
        var marginTop = 10;
        var marginBottom = 10;

        var priceMin = profile[profile.length - 1].price;
        var priceMax = profile[0].price;
        var priceRange = priceMax - priceMin;
        if (priceRange <= 0) return;

        // Auto-center on current price at first load
        var bannerData = data && data.banner ? data.banner : {};
        var symKey = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var currentPrice = bannerData[symKey] ? bannerData[symKey].price : null;
        if (!st.initialized && profile.length > 0 && priceRange > 0) {
            var displayH = H - marginTop - marginBottom;
            // Calcul zoom SEULEMENT au premier init (pas apres zoom user)
            if (st.zoomInitDone !== true) {
                var extMin = priceMin, extMax = priceMax;
                if (currentPrice) { extMin = Math.min(extMin, currentPrice); extMax = Math.max(extMax, currentPrice); }
                if (levels) {
                    if (levels.sess_high) extMax = Math.max(extMax, levels.sess_high);
                    if (levels.sess_low) extMin = Math.min(extMin, levels.sess_low);
                    if (levels.ib_high) extMax = Math.max(extMax, levels.ib_high);
                    if (levels.ib_low) extMin = Math.min(extMin, levels.ib_low);
                    if (levels.vpoc_prev) { extMin = Math.min(extMin, levels.vpoc_prev); extMax = Math.max(extMax, levels.vpoc_prev); }
                }
                var viewRange = (extMax - extMin) * 1.15;
                st.zoom = priceRange < 10 ? 1.0 : Math.max(0.5, Math.min(5.0, viewRange / priceRange));
                st.zoomInitDone = true;
            }
            // Re-centrage sur POC a chaque reset init (garantit profile visible apres zoom user)
            var pocCenter = (levels && levels.poc) ? levels.poc : (priceMin + priceMax) / 2;
            var totalHZoomed = displayH * st.zoom;
            var pocYNoOffset = ((priceMax - pocCenter) / priceRange) * totalHZoomed;
            st.offsetY = displayH / 2 - pocYNoOffset;
            st.initialized = true;
        }

        var zoom = Math.max(0.5, Math.min(5.0, st.zoom));
        var offsetY = st.offsetY;
        var barAreaW = W - marginLeft - marginRight;
        var totalH = (H - marginTop - marginBottom) * zoom;

        function priceToY(p) {
            return marginTop + ((priceMax - p) / priceRange) * totalH + offsetY;
        }

        // Clear
        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, W, H);

        // Grid lines
        ctx.strokeStyle = "rgba(255,255,255,0.03)";
        ctx.lineWidth = 1;
        var step = priceRange > 50 ? 5 : priceRange > 20 ? 2 : 1;
        var gridPrice = Math.ceil(priceMin / step) * step;
        while (gridPrice <= priceMax) {
            var gy = priceToY(gridPrice);
            if (gy >= marginTop && gy <= H - marginBottom) {
                ctx.beginPath();
                ctx.moveTo(marginLeft, gy);
                ctx.lineTo(W - marginRight, gy);
                ctx.stroke();
            }
            gridPrice += step;
        }

        // Value Area background
        if (vah && valP) {
            var vaTop = priceToY(vah);
            var vaBot = priceToY(valP);
            ctx.fillStyle = "rgba(0,180,220,0.04)";
            ctx.fillRect(marginLeft, vaTop, barAreaW, vaBot - vaTop);
        }

        // Prev VA background
        if (vahPrev && valPrev) {
            var pvTop = priceToY(vahPrev);
            var pvBot = priceToY(valPrev);
            ctx.fillStyle = "rgba(124,77,255,0.03)";
            ctx.fillRect(marginLeft, pvTop, barAreaW, pvBot - pvTop);
        }

        // Bars
        var barH = Math.max(1, (totalH / profile.length) * 0.85);
        for (var i = 0; i < profile.length; i++) {
            var row = profile[i];
            var y = priceToY(row.price) - barH / 2;
            if (y + barH < 0 || y > H) continue; // clip

            var barW = (row.pct / 100) * barAreaW;
            if (row.is_poc) {
                ctx.fillStyle = "#e040fb";
                ctx.shadowColor = "rgba(224,64,251,0.5)";
                ctx.shadowBlur = 6;
            } else if (row.in_va) {
                ctx.fillStyle = "rgba(0,180,220,0.5)";
                ctx.shadowBlur = 0;
            } else {
                ctx.fillStyle = "rgba(255,255,255,0.1)";
                ctx.shadowBlur = 0;
            }
            ctx.fillRect(marginLeft, y, barW, barH);
            ctx.shadowBlur = 0;
        }

        // Price axis (right side)
        ctx.font = "10px 'JetBrains Mono', monospace";
        ctx.textAlign = "left";
        gridPrice = Math.ceil(priceMin / step) * step;
        while (gridPrice <= priceMax) {
            var ly = priceToY(gridPrice);
            if (ly >= marginTop + 5 && ly <= H - marginBottom - 5) {
                ctx.fillStyle = "#64748b";
                ctx.fillText(gridPrice.toFixed(2), W - marginRight + 6, ly + 3);
            }
            gridPrice += step;
        }

        // Level markers
        function drawLevel(price, label, color, dashed) {
            if (!price) return;
            var y = priceToY(price);
            if (y < 0 || y > H) return;
            ctx.strokeStyle = color;
            ctx.lineWidth = dashed ? 1 : 2;
            ctx.setLineDash(dashed ? [4, 3] : []);
            ctx.beginPath();
            ctx.moveTo(marginLeft, y);
            ctx.lineTo(W - marginRight, y);
            ctx.stroke();
            ctx.setLineDash([]);
            // Label
            ctx.fillStyle = color;
            ctx.font = "bold 9px 'JetBrains Mono', monospace";
            ctx.textAlign = "right";
            ctx.fillText(label + " " + price.toFixed(2), marginLeft - 4, y + 3);
        }

        // ─── Niveaux jour ───
        drawLevel(poc, "POC", "#e040fb", false);
        drawLevel(vah, "VAH", "#4fc3f7", true);
        drawLevel(valP, "VAL", "#4fc3f7", true);
        // VWAP
        drawLevel(levels ? levels.vwap_d : null, "VWAP", "#00b4dc", false);
        drawLevel(levels ? levels.vwap_sd1u : null, "SD1+", "#4dd0e1", true);
        drawLevel(levels ? levels.vwap_sd1d : null, "SD1-", "#4dd0e1", true);
        drawLevel(levels ? levels.vwap_sd2u : null, "SD2+", "#ff9800", true);
        drawLevel(levels ? levels.vwap_sd2d : null, "SD2-", "#ff9800", true);
        drawLevel(levels ? levels.vwap_sd3u : null, "SD3+", "#f44336", true);
        drawLevel(levels ? levels.vwap_sd3d : null, "SD3-", "#f44336", true);
        // Session High/Low
        drawLevel(levels ? levels.sess_high : null, "SESS H", "#ffffff", true);
        drawLevel(levels ? levels.sess_low : null, "SESS L", "#ffffff", true);
        // IB
        var ibH = levels ? levels.ib_high : null;
        var ibL = levels ? levels.ib_low : null;
        drawLevel(ibH, "IB H", "#ffc107", false);
        drawLevel(ibL, "IB L", "#ffc107", false);
        // IB zone shading
        if (ibH && ibL) {
            var ibTop = priceToY(ibH);
            var ibBot = priceToY(ibL);
            if (ibTop < H && ibBot > 0) {
                ctx.fillStyle = "rgba(255,193,7,0.06)";
                ctx.fillRect(marginLeft, ibTop, barAreaW, ibBot - ibTop);
            }
        }
        // OVN
        drawLevel(levels ? levels.ovn_high : null, "OVN H", "#546e7a", true);
        drawLevel(levels ? levels.ovn_low : null, "OVN L", "#546e7a", true);
        // ─── Niveaux veille ───
        drawLevel(vpocPrev, "pPOC", "#7c4dff", true);
        drawLevel(vahPrev, "pVAH", "#9575cd", true);
        drawLevel(valPrev, "pVAL", "#9575cd", true);
        drawLevel(levels ? levels.prev_vwap : null, "pVWAP", "#0090b0", true);

        // Current price marker
        var banner = data && data.banner ? data.banner : {};
        var sym = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var curPrice = banner[sym] ? banner[sym].price : null;
        if (curPrice) {
            var cp = priceToY(curPrice);
            if (cp >= 0 && cp <= H) {
                ctx.strokeStyle = "#d4af37";
                ctx.lineWidth = 2;
                ctx.setLineDash([]);
                ctx.beginPath();
                ctx.moveTo(marginLeft, cp);
                ctx.lineTo(W - marginRight, cp);
                ctx.stroke();
                // Arrow
                ctx.fillStyle = "#d4af37";
                ctx.beginPath();
                ctx.moveTo(W - marginRight, cp);
                ctx.lineTo(W - marginRight + 8, cp - 5);
                ctx.lineTo(W - marginRight + 8, cp + 5);
                ctx.fill();
                // Price label
                ctx.fillStyle = "#0a0e17";
                ctx.fillRect(W - marginRight + 9, cp - 8, 58, 16);
                ctx.fillStyle = "#d4af37";
                ctx.font = "bold 10px 'JetBrains Mono', monospace";
                ctx.textAlign = "left";
                ctx.fillText(curPrice.toFixed(2), W - marginRight + 11, cp + 4);
            }
        }

        // Setup interactions (once)
        if (!canvas._vpInit) {
            canvas._vpInit = true;

            canvas.addEventListener("wheel", function (e) {
                e.preventDefault();
                var delta = e.deltaY > 0 ? 0.9 : 1.1;
                st.zoom = Math.max(0.5, Math.min(10, st.zoom * delta));
                st.initialized = false; // re-centrer sur POC apres zoom (fix bug disparition)
                drawVolumeProfileCanvas(canvasId, st.profile, st.levels);
            }, { passive: false });

            canvas.addEventListener("mousedown", function (e) {
                st.dragging = true;
                st.lastY = e.clientY;
                canvas.style.cursor = "grabbing";
            });

            // Double-click = recentrage total (FIT raccourci)
            canvas.addEventListener("dblclick", function (e) {
                e.preventDefault();
                st.initialized = false;
                st.zoomInitDone = false;
                drawVolumeProfileCanvas(canvasId, st.profile, st.levels);
            });
            // Tooltip overlay
            var tooltip = document.createElement("div");
            tooltip.className = "vp-tooltip";
            tooltip.style.cssText = "position:absolute;display:none;background:rgba(10,14,23,0.92);border:1px solid var(--border-hover);border-radius:4px;padding:4px 8px;font:11px 'JetBrains Mono',monospace;color:#f1f5f9;pointer-events:none;z-index:50;white-space:nowrap;";
            canvas.parentElement.style.position = "relative";
            canvas.parentElement.appendChild(tooltip);

            canvas.addEventListener("mousemove", function (e) {
                if (st.dragging) {
                    var dy = e.clientY - st.lastY;
                    st.offsetY += dy;
                    st.lastY = e.clientY;
                    tooltip.style.display = "none";
                    drawVolumeProfileCanvas(canvasId, st.profile, st.levels);
                    return;
                }
                // Tooltip : convertir Y souris en prix
                var rect = canvas.getBoundingClientRect();
                var mouseY = e.clientY - rect.top;
                var prof = st.profile;
                if (!prof || !prof.length) return;
                var pMin = prof[prof.length - 1].price;
                var pMax = prof[0].price;
                var pRange = pMax - pMin;
                if (pRange <= 0) return;
                var totalH = (rect.height - 20) * st.zoom;
                var hoverPrice = pMax - ((mouseY - 10 - st.offsetY) / totalH) * pRange;
                // Trouver la barre la plus proche
                var closest = null;
                var minDiff = Infinity;
                for (var j = 0; j < prof.length; j++) {
                    var diff = Math.abs(prof[j].price - hoverPrice);
                    if (diff < minDiff) { minDiff = diff; closest = prof[j]; }
                }
                if (closest && minDiff < pRange * 0.05) {
                    tooltip.innerHTML = closest.price.toFixed(2) + " | Vol: " + closest.vol.toLocaleString() + " (" + closest.pct.toFixed(1) + "%)" + (closest.is_poc ? " <b style='color:#e040fb;'>POC</b>" : "") + (closest.in_va ? " <b style='color:#00b4dc;'>VA</b>" : "");
                    tooltip.style.display = "block";
                    tooltip.style.left = (e.clientX - rect.left + 12) + "px";
                    tooltip.style.top = (mouseY - 8) + "px";
                } else {
                    tooltip.style.display = "none";
                }
            });
            // mouseup sur window pour eviter le drag coince quand la souris sort du canvas
            window.addEventListener("mouseup", function () {
                if (st.dragging) {
                    st.dragging = false;
                    canvas.style.cursor = "grab";
                }
            });
            canvas.addEventListener("mouseleave", function () {
                st.dragging = false;
                canvas.style.cursor = "grab";
                tooltip.style.display = "none";
            });
        }
    }

    function renderProfile() {
        // Charger le volume profile si pas encore fait
        if (!vpLoaded) loadVolumeProfile();

        var instr = getInstr(currentInstrument === "BOTH" ? "ES" : currentInstrument);
        if (!instr) return;
        var mp = instr.market_profile || {};
        var ib = instr.initial_balance || {};

        // Range position
        var rangePos = (instr.regime && instr.regime.range_pos) || 50;
        $("range-position").innerHTML =
            '<div style="display:flex;align-items:center;gap:12px;">' +
            '<span class="mono" style="color:var(--green);">0%</span>' +
            '<div style="flex:1;"><div class="gauge" style="height:12px;"><div class="gauge-fill gauge-gradient" style="width:' + rangePos + '%;"></div></div></div>' +
            '<span class="mono" style="color:var(--red);">100%</span>' +
            '</div>' +
            '<div style="text-align:center;margin-top:6px;font-size:0.875rem;font-weight:700;">' +
            (rangePos >= 80 ? '<span style="color:var(--red);">TOP (' + fmt(rangePos, 0) + '%)</span>' : rangePos <= 20 ? '<span style="color:var(--green);">BOTTOM (' + fmt(rangePos, 0) + '%)</span>' : '<span style="color:var(--text-secondary);">MIDDLE (' + fmt(rangePos, 0) + '%)</span>') +
            '</div>';

        // Profile du jour
        var profHtml = "";
        profHtml += kvRow("Profile Shape", mp.profile_shape_label || "--");
        profHtml += kvRow("Day Type", mp.day_type_label || "--");
        profHtml += kvRow("Profile Skew", fmt(mp.profile_skew, 3));
        profHtml += kvRow("Double Dist", boolBadge(mp.is_double_dist, "Profil bimodal", "Profil normal"));
        profHtml += kvRow("POC Position", fmt(mp.poc_position, 1));
        profHtml += kvRow("POC Separation", fmt(mp.poc_separation_ticks, 0) + "t");
        profHtml += kvRow("Rule 80%", boolBadge(mp.rule_80pct, "Active — traversee VA probable", "Inactive"));
        profHtml += kvRow("VA Confluence", boolBadge(mp.bool_va_confluence, "VA jour = VA veille", "VA differentes"));
        profHtml += kvRow("Single Prints", fmtInt(mp.single_print_count));
        $("profile-day").innerHTML = profHtml;

        // IB Mini-chart bougies — refresh chaque 60s (bug #5 fix)
        var now = Date.now();
        if (!ibChartLoaded || (now - ibChartLastLoad) > 60000) {
            loadIbChart();
            ibChartLastLoad = now;
        }

        // IB Canvas visuel
        drawIbCanvas(ib, instr);

        // IB Status badge
        var ibBadge = $("ib-status-badge");
        if (ibBadge) {
            if (!ib.ib_high_price && !ib.ib_low_price) {
                ibBadge.textContent = "PAS ENCORE FORME";
                ibBadge.className = "badge badge-gray";
            } else if (ib.ib_broken_up || ib.ib_broken_down) {
                ibBadge.textContent = ib.ib_broken_up ? "BROKEN UP" : "BROKEN DOWN";
                ibBadge.className = "badge " + (ib.ib_broken_up ? "badge-green" : "badge-red");
            } else {
                ibBadge.textContent = "INTACT";
                ibBadge.className = "badge badge-cyan";
            }
        }

        // IB text data
        var ibHtml = "";
        ibHtml += kvRow("IB High", fmtPrice(ib.ib_high_price), "red");
        ibHtml += kvRow("IB Low", fmtPrice(ib.ib_low_price), "green");
        ibHtml += kvRow("IB Range", fmt(ib.ib_range_ticks, 0) + "t");
        ibHtml += kvRow("IB / ATR", fmt(ib.ib_range_atr, 2));
        ibHtml += kvRow("Broken Up", ib.ib_broken_up ? badgeHtml("Casse a la hausse — trend up", "badge-green") : badgeHtml("Intacte", "badge-gray"));
        ibHtml += kvRow("Broken Down", ib.ib_broken_down ? badgeHtml("Casse a la baisse — trend down", "badge-red") : badgeHtml("Intacte", "badge-gray"));
        ibHtml += kvRow("Type IB", (ib.ib_is_narrow ? badgeHtml("Etroite — breakout probable", "badge-orange") : ib.ib_is_wide ? badgeHtml("Large — range day probable", "badge-cyan") : badgeHtml("Normale", "badge-gray")));
        ibHtml += kvRow("Extension", fmt(ib.ib_extension_ratio, 2) + "x");

        // IB Veille (bug #6 fix 22/04) — comparaison narrow/wide vs aujourd'hui
        if (ibYesterdayInfo.ib_high) {
            var ibYRange = ibYesterdayInfo.ib_range || 0;
            var ibTRange = ib.ib_range_ticks || 0;
            var cmpLabel = "";
            if (ibTRange > 0 && ibYRange > 0) {
                var ratio = ibTRange / ibYRange;
                if (ratio < 0.8) cmpLabel = badgeHtml("Plus etroite que hier (" + fmt(ratio, 2) + "x)", "badge-orange");
                else if (ratio > 1.2) cmpLabel = badgeHtml("Plus large que hier (" + fmt(ratio, 2) + "x)", "badge-cyan");
                else cmpLabel = badgeHtml("Similaire a hier (" + fmt(ratio, 2) + "x)", "badge-gray");
            }
            ibHtml += '<div style="border-top:1px solid var(--border);margin-top:10px;padding-top:8px;">';
            ibHtml += '<div style="font-weight:600;color:var(--gold);margin-bottom:6px;">IB Veille (hier)</div>';
            ibHtml += kvRow("IB High Y", fmtPrice(ibYesterdayInfo.ib_high), "red");
            ibHtml += kvRow("IB Low Y", fmtPrice(ibYesterdayInfo.ib_low), "green");
            ibHtml += kvRow("IB Range Y", fmt(ibYRange, 0) + "t");
            if (cmpLabel) ibHtml += kvRow("Comparaison", cmpLabel);
            ibHtml += '</div>';
        }

        $("ib-content").innerHTML = ibHtml;

        // Value Area
        var vaHtml = "";
        // Current VA
        vaHtml += '<div><div style="font-weight:600;margin-bottom:6px;color:var(--cyan);">Courante</div>';
        vaHtml += kvRow("VPOC", fmtPrice(mp.cur_vpoc_price), "cyan");
        vaHtml += kvRow("VAH", fmtPrice(mp.cur_vah_price), "red");
        vaHtml += kvRow("VAL", fmtPrice(mp.cur_val_price), "green");
        vaHtml += kvRow("Dans VA", boolBadge(mp.inside_cur_va, "Prix dans la VA", "Prix hors VA"));
        vaHtml += kvRow("VA Position", fmtPct(mp.va_position_pct));
        vaHtml += kvRow("VAH Touches", fmtInt(mp.vah_touches_20b));
        vaHtml += kvRow("VAL Touches", fmtInt(mp.val_touches_20b));
        vaHtml += '</div>';

        // Previous VA
        vaHtml += '<div><div style="font-weight:600;margin-bottom:6px;color:var(--gold);">Precedente</div>';
        vaHtml += kvRow("VPOC", fmtPrice(mp.prev_vpoc_price), "gold");
        vaHtml += kvRow("VAH", fmtPrice(mp.prev_vah_price));
        vaHtml += kvRow("VAL", fmtPrice(mp.prev_val_price));
        vaHtml += kvRow("VWAP", fmtPrice(mp.prev_vwap_price));
        vaHtml += kvRow("Dans VA", boolBadge(mp.inside_prev_va, "Prix dans la VA veille", "Prix hors VA veille"));
        vaHtml += '</div>';

        // Composites
        vaHtml += '<div><div style="font-weight:600;margin-bottom:6px;color:var(--purple);">Composites</div>';
        vaHtml += kvRow("20D VPOC", fmtPrice(mp.comp_20d_vpoc_price));
        vaHtml += kvRow("20D VAH", fmtPrice(mp.comp_20d_vah_price));
        vaHtml += kvRow("20D VAL", fmtPrice(mp.comp_20d_val_price));
        vaHtml += kvRow("50D VPOC", fmtPrice(mp.comp_50d_vpoc_price));
        vaHtml += kvRow("Align 20/50", boolBadge(mp.comp_vpoc_align_20_50, "POC 20j et 50j alignes", "POC divergent"));
        vaHtml += kvRow("Align Day/20", boolBadge(mp.comp_vpoc_align_day_20, "POC jour et 20j alignes", "POC divergent"));
        vaHtml += '</div>';

        $("va-grid").innerHTML = vaHtml;

        // HVN/LVN
        var hlHtml = "";
        hlHtml += '<div class="grid-2">';
        hlHtml += '<div>' + kvRow("HVN Above", fmtPrice(mp.session_hvn_above_price)) + kvRow("HVN Below", fmtPrice(mp.session_hvn_below_price)) + kvRow("HVN Count", fmtInt(mp.session_hvn_count)) + kvRow("HVN Between", fmtInt(mp.hvn_between)) + '</div>';
        hlHtml += '<div>' + kvRow("LVN Above", fmtPrice(mp.session_lvn_above_price)) + kvRow("LVN Below", fmtPrice(mp.session_lvn_below_price)) + kvRow("LVN Count", fmtInt(mp.session_lvn_count)) + kvRow("LVN Between", fmtInt(mp.lvn_between)) + kvRow("LVN Confluence", fmtInt(mp.lvn_confluence_count)) + '</div>';
        hlHtml += '</div>';
        $("hvn-lvn-content").innerHTML = hlHtml;
    }

    // ═══════════════════════════════════════════════════════════════
    // PAGE: NIVEAUX & VWAP
    // ═══════════════════════════════════════════════════════════════

    function renderLevels() {
        var instr = getInstr(currentInstrument === "BOTH" ? "ES" : currentInstrument);
        if (!instr || !instr.levels) return;
        var lvl = instr.levels;

        // VWAP Ladder visuelle ES
        var esI = getInstr("ES"), nqI = getInstr("NQ");
        function buildLadder(inst, sym) {
            if (!inst || !inst.levels) return '<div style="color:var(--text-disabled);">Pas de donnees</div>';
            var l = inst.levels;
            var bannerSym = data.banner && data.banner[sym.toLowerCase()];
            var price = bannerSym ? bannerSym.price : 0;
            return vwapLadder(price, {
                sd3u: l.vwap_d_sd3u_price, sd2u: l.vwap_d_sd2u_price, sd1u: l.vwap_d_sd1u_price,
                vwap: l.vwap_d_price,
                sd1d: l.vwap_d_sd1d_price, sd2d: l.vwap_d_sd2d_price, sd3d: l.vwap_d_sd3d_price,
            });
        }
        $("vwap-ladder-es").innerHTML = buildLadder(esI, "ES");
        $("vwap-ladder-nq").innerHTML = buildLadder(nqI, "NQ");

        // VWAP Bands
        var vHtml = '<div class="grid-2"><div>';
        vHtml += '<div style="font-weight:600;margin-bottom:6px;color:var(--cyan);">VWAP Daily</div>';
        vHtml += kvRow("VWAP D", fmtPrice(lvl.vwap_d_price), "cyan");
        vHtml += kvRow("SD1 Up", fmtPrice(lvl.vwap_d_sd1u_price));
        vHtml += kvRow("SD1 Down", fmtPrice(lvl.vwap_d_sd1d_price));
        vHtml += kvRow("SD2 Up", fmtPrice(lvl.vwap_d_sd2u_price));
        vHtml += kvRow("SD2 Down", fmtPrice(lvl.vwap_d_sd2d_price));
        vHtml += kvRow("SD3 Up", fmtPrice(lvl.vwap_d_sd3u_price), "red");
        vHtml += kvRow("SD3 Down", fmtPrice(lvl.vwap_d_sd3d_price), "green");
        vHtml += kvRow("Au-dessus", boolBadge(lvl.bool_above_vwap_d, "Prix au-dessus du VWAP", "Prix sous le VWAP"));
        vHtml += '</div><div>';
        vHtml += '<div style="font-weight:600;margin-bottom:6px;color:var(--gold);">VWAP W/M + Swing</div>';
        vHtml += kvRow("VWAP Weekly", fmtPrice(lvl.vwap_w_price), "gold");
        vHtml += kvRow("VWAP Monthly", fmtPrice(lvl.vwap_m_price), "gold");
        vHtml += kvRow("Swing High", fmtPrice(lvl.swing_high_price), "red");
        vHtml += kvRow("Swing Low", fmtPrice(lvl.swing_low_price), "green");
        vHtml += kvRow("Swing Range", fmt(lvl.swing_range_ticks, 0) + "t");
        vHtml += kvRow("Prev VWAP SD1U", fmtPrice(lvl.prev_vwap_sd1u_price));
        vHtml += kvRow("Prev VWAP SD1D", fmtPrice(lvl.prev_vwap_sd1d_price));
        vHtml += kvRow("OVN High", fmtPrice(lvl.ovn_high_price));
        vHtml += kvRow("OVN Low", fmtPrice(lvl.ovn_low_price));
        vHtml += '</div></div>';
        $("vwap-bands").innerHTML = vHtml;

        // Table all levels
        var levels = [];
        function addLevel(name, price, type) {
            if (price != null && price > 0) {
                var banner = data.banner || {};
                var sym = currentInstrument === "NQ" ? "nq" : "es";
                var curPrice = banner[sym] ? banner[sym].price : 0;
                var dist = curPrice > 0 ? Math.round((price - curPrice) / 0.25) : 0;
                levels.push({ name: name, price: price, dist: dist, type: type });
            }
        }

        addLevel("VWAP D", lvl.vwap_d_price, "VWAP");
        addLevel("VWAP SD1U", lvl.vwap_d_sd1u_price, "VWAP");
        addLevel("VWAP SD1D", lvl.vwap_d_sd1d_price, "VWAP");
        addLevel("VWAP SD2U", lvl.vwap_d_sd2u_price, "VWAP");
        addLevel("VWAP SD2D", lvl.vwap_d_sd2d_price, "VWAP");
        addLevel("VWAP SD3U", lvl.vwap_d_sd3u_price, "VWAP");
        addLevel("VWAP SD3D", lvl.vwap_d_sd3d_price, "VWAP");
        addLevel("VWAP W", lvl.vwap_w_price, "VWAP");
        addLevel("VWAP M", lvl.vwap_m_price, "VWAP");
        addLevel("Swing High", lvl.swing_high_price, "Swing");
        addLevel("Swing Low", lvl.swing_low_price, "Swing");
        addLevel("Sess High", lvl.sess_high_price, "Session");
        addLevel("Sess Low", lvl.sess_low_price, "Session");
        addLevel("OVN High", lvl.ovn_high_price, "OVN");
        addLevel("OVN Low", lvl.ovn_low_price, "OVN");
        addLevel("Open Cash", lvl.open_cash_price, "Session");
        addLevel("Open 830", lvl.open_830_price, "Session");
        addLevel("Blind Up", lvl.blind_up_price, "Options");
        addLevel("Blind Dn", lvl.blind_dn_price, "Options");
        addLevel("Day Max", lvl.day_max_price, "Session");
        addLevel("Day Min", lvl.day_min_price, "Session");

        // Add options/profile levels
        var opts = instr.options || {};
        addLevel("Call Wall", opts.call_wall_price, "Options");
        addLevel("Put Wall", opts.put_wall_price, "Options");
        addLevel("HVL", opts.hvl_price, "Options");
        addLevel("0DTE Call", opts.call_0dte_price, "Options");
        addLevel("0DTE Put", opts.put_0dte_price, "Options");

        var mp = instr.market_profile || {};
        addLevel("VPOC", mp.cur_vpoc_price, "Profile");
        addLevel("VAH", mp.cur_vah_price, "Profile");
        addLevel("VAL", mp.cur_val_price, "Profile");
        addLevel("Prev VPOC", mp.prev_vpoc_price, "Profile");
        addLevel("Prev VAH", mp.prev_vah_price, "Profile");
        addLevel("Prev VAL", mp.prev_val_price, "Profile");
        addLevel("20D VPOC", mp.comp_20d_vpoc_price, "Profile");
        addLevel("20D VAH", mp.comp_20d_vah_price, "Profile");
        addLevel("20D VAL", mp.comp_20d_val_price, "Profile");
        addLevel("50D VPOC", mp.comp_50d_vpoc_price, "Profile");
        addLevel("HVN Above", mp.session_hvn_above_price, "Profile");
        addLevel("HVN Below", mp.session_hvn_below_price, "Profile");
        addLevel("LVN Above", mp.session_lvn_above_price, "Profile");
        addLevel("LVN Below", mp.session_lvn_below_price, "Profile");
        var gexOpts = instr.options || {};
        addLevel("GEX Up", gexOpts.gex_up_price, "Options");
        addLevel("GEX Dn", gexOpts.gex_dn_price, "Options");

        // Sort by distance
        levels.sort(function (a, b) { return Math.abs(a.dist) - Math.abs(b.dist); });

        // Filter
        var filtered = currentLevelFilter === "ALL" ? levels : levels.filter(function (l) { return l.type === currentLevelFilter; });

        var tbodyHtml = "";
        filtered.forEach(function (l) {
            var distColor = l.dist > 0 ? "color:var(--green);" : l.dist < 0 ? "color:var(--red);" : "";
            var typeColor = { Options: "badge-red", VWAP: "badge-cyan", Profile: "badge-gold", Swing: "badge-orange", Session: "badge-green", OVN: "badge-purple" };
            tbodyHtml += '<tr>' +
                '<td style="font-weight:600;">' + l.name + '</td>' +
                '<td class="mono" style="font-weight:600;">' + fmtPrice(l.price) + '</td>' +
                '<td class="mono" style="' + distColor + '">' + (l.dist >= 0 ? "+" : "") + l.dist + 't</td>' +
                '<td>' + badgeHtml(l.type, typeColor[l.type] || "badge-gray") + '</td>' +
                '</tr>';
        });
        $("levels-tbody").innerHTML = tbodyHtml;

        // Intermarket — big visual indicator
        var im = data.intermarket || {};
        var imHtml = "";
        if (im.cross_delta_agreement != null) {
            var corr = im.rolling_correlation || 0;
            var corrAbs = Math.abs(corr);
            var corrLabel, corrColor, corrBg, corrAdvice;
            if (corrAbs >= 0.7) {
                corrLabel = "TRES CORRELE"; corrColor = "var(--green)"; corrBg = "var(--green-dim)";
                corrAdvice = "ES et NQ bougent ensemble — confirme la direction";
            } else if (corrAbs >= 0.4) {
                corrLabel = "PEU CORRELE"; corrColor = "var(--orange)"; corrBg = "var(--orange-dim)";
                corrAdvice = "Correlation faible — un indice pourrait diverger";
            } else {
                corrLabel = "DECORRELE"; corrColor = "var(--red)"; corrBg = "var(--red-dim)";
                corrAdvice = "ES et NQ ne sont PAS alignes — attention SMT divergence";
            }

            // Big correlation box
            imHtml += '<div style="text-align:center;padding:16px;margin-bottom:12px;background:' + corrBg + ';border:2px solid ' + corrColor + '30;border-radius:12px;">';
            imHtml += '<div style="font-size:0.6875rem;color:var(--text-disabled);text-transform:uppercase;font-weight:600;">Correlation ES / NQ</div>';
            imHtml += '<div style="font-size:2rem;font-weight:800;color:' + corrColor + ';margin:6px 0;">' + corrLabel + '</div>';
            imHtml += '<div style="font-size:0.8125rem;color:var(--text-secondary);">' + corrAdvice + '</div>';
            // Gauge
            imHtml += '<div style="max-width:300px;margin:12px auto 0;">';
            imHtml += '<div style="display:flex;justify-content:space-between;font-size:0.5625rem;color:var(--text-disabled);margin-bottom:2px;"><span>DECORRELE</span><span>NEUTRE</span><span>CORRELE</span></div>';
            var gaugePct = ((corr + 1) / 2) * 100; // -1..+1 → 0..100%
            imHtml += '<div style="height:10px;background:linear-gradient(90deg, rgba(255,82,82,0.3) 0%, rgba(255,152,0,0.3) 35%, rgba(0,200,83,0.3) 100%);border-radius:5px;position:relative;">';
            imHtml += '<div style="position:absolute;left:' + gaugePct.toFixed(0) + '%;top:-3px;transform:translateX(-50%);width:16px;height:16px;background:' + corrColor + ';border-radius:50%;border:2px solid #0a0e17;box-shadow:0 0 8px ' + corrColor + ';"></div>';
            imHtml += '</div></div>';
            imHtml += '<div class="mono" style="font-size:0.8125rem;color:' + corrColor + ';margin-top:8px;font-weight:700;">' + fmt(corr, 3) + '</div>';
            imHtml += '</div>';

            // Detail indicators
            var smt = im.smt_divergence;
            var smtColor = smt ? "var(--red)" : "var(--green)";
            var smtLabel = smt ? "DIVERGENCE" : "ALIGNE";

            imHtml += '<div class="grid-2" style="margin-top:4px;">';

            // ES column
            imHtml += '<div style="background:rgba(15,191,132,0.05);border:1px solid rgba(15,191,132,0.15);border-radius:8px;padding:12px;">';
            imHtml += '<div style="font-weight:700;color:#0fbf84;margin-bottom:6px;font-size:0.8125rem;">ES</div>';
            imHtml += kvRow("Delta", im.es_delta_dir > 0 ? badgeHtml("Flux acheteur", "badge-green") : im.es_delta_dir < 0 ? badgeHtml("Flux vendeur", "badge-red") : badgeHtml("Pas de flux", "badge-gray"));
            imHtml += kvRow("Range Pos", fmt(im.es_range_pos, 0) + "%");
            imHtml += kvRow("RVOL", fmt(im.es_rvol, 2));
            imHtml += '</div>';

            // NQ column
            imHtml += '<div style="background:rgba(74,158,255,0.05);border:1px solid rgba(74,158,255,0.15);border-radius:8px;padding:12px;">';
            imHtml += '<div style="font-weight:700;color:#4a9eff;margin-bottom:6px;font-size:0.8125rem;">NQ</div>';
            imHtml += kvRow("Delta", im.nq_delta_dir > 0 ? badgeHtml("Flux acheteur", "badge-green") : im.nq_delta_dir < 0 ? badgeHtml("Flux vendeur", "badge-red") : badgeHtml("Pas de flux", "badge-gray"));
            imHtml += kvRow("Range Pos", fmt(im.nq_range_pos, 0) + "%");
            imHtml += kvRow("RVOL", fmt(im.nq_rvol, 2));
            imHtml += '</div>';

            imHtml += '</div>';

            // Summary row
            imHtml += '<div style="display:flex;justify-content:center;gap:16px;margin-top:10px;flex-wrap:wrap;">';
            imHtml += '<div style="text-align:center;"><div style="font-size:0.5625rem;color:var(--text-disabled);">SMT</div>' + badgeHtml(smtLabel, smt ? "badge-red" : "badge-green") + '</div>';
            imHtml += '<div style="text-align:center;"><div style="font-size:0.5625rem;color:var(--text-disabled);">DELTA</div>' + badgeHtml(im.cross_delta_agreement ? "ES et NQ alignes" : "ES et NQ divergent", im.cross_delta_agreement ? "badge-green" : "badge-red") + '</div>';
            imHtml += '<div style="text-align:center;"><div style="font-size:0.5625rem;color:var(--text-disabled);">VOL LEADER</div>' + badgeHtml(im.volume_lead === "ES" ? "ES mene" : im.volume_lead === "NQ" ? "NQ mene" : "Equilibre", im.volume_lead === "ES" ? "badge-green" : im.volume_lead === "NQ" ? "badge-cyan" : "badge-gray") + '</div>';
            imHtml += '<div style="text-align:center;"><div style="font-size:0.5625rem;color:var(--text-disabled);">RATIO</div><span class="mono" style="font-size:0.75rem;">' + fmt(im.price_ratio, 4) + '</span></div>';
            imHtml += '</div>';
        }
        $("intermarket-content").innerHTML = imHtml;
    }

    // ═══════════════════════════════════════════════════════════════
    // PAGE: SIGNAUX
    // ═══════════════════════════════════════════════════════════════

    function renderSignals() {
        var instr = getInstr(currentInstrument === "BOTH" ? "ES" : currentInstrument);
        if (!instr || !instr.suggestion) return;
        var s = instr.suggestion;

        // Suggestion
        var actionColor = s.action === "GO" ? "var(--green)" : s.action === "WAIT" ? "var(--orange)" : "var(--red)";
        var sHtml = '<div style="text-align:center;padding:16px 0;">';
        sHtml += '<div style="font-size:2rem;font-weight:800;color:' + actionColor + ';">' + (s.action || "--") + '</div>';
        sHtml += '<div style="margin:8px 0;">' + badgeHtml("Grade " + (s.grade || "--"), s.grade === "A" ? "badge-green" : s.grade === "B" ? "badge-cyan" : "badge-red") + ' ' + badgeHtml(s.direction || "--", s.direction === "LONG" ? "badge-green" : s.direction === "SHORT" ? "badge-red" : "badge-gray") + '</div>';
        sHtml += '<div style="display:flex;justify-content:center;gap:24px;margin-top:12px;">';
        sHtml += '<div><span class="text-muted">SL</span><div class="mono" style="font-weight:700;color:var(--red);">' + fmtPrice(s.sl_price) + ' (' + fmt(s.sl_ticks, 1) + 't)</div></div>';
        sHtml += '<div><span class="text-muted">TP</span><div class="mono" style="font-weight:700;color:var(--green);">' + fmtPrice(s.tp_price) + ' (' + fmt(s.tp_ticks, 1) + 't)</div></div>';
        sHtml += '<div><span class="text-muted">R:R</span><div class="mono" style="font-weight:700;color:var(--cyan);">' + fmt(s.rr, 1) + '</div></div>';
        sHtml += '</div></div>';
        $("suggestion-content").innerHTML = sHtml;

        // Checklist
        var cHtml = "";
        (s.checks || []).forEach(function (c) {
            cHtml += '<div class="check-item ' + (c.ok ? "check-ok" : "check-fail") + '">';
            cHtml += '<div class="check-icon">' + (c.ok ? "&#10003;" : "&#10007;") + '</div>';
            cHtml += '<span>' + c.name + '</span></div>';
        });
        if (s.passed != null) {
            cHtml += '<div style="margin-top:8px;font-size:0.8125rem;color:var(--text-secondary);">' + s.passed + '/' + s.total + ' checks passes</div>';
        }
        $("checklist-content").innerHTML = cHtml;

        // Bot status
        var bs = data.bot_status || {};
        var is = (data.instrument_status || {})[currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase()] || {};
        var bsHtml = "";
        bsHtml += kvRow("Statut", bs.global_status || "--");
        bsHtml += kvRow("Running", boolBadge(bs.running, "Bot actif", "Bot arrete"));
        bsHtml += kvRow("Heartbeat", bs.last_heartbeat || "N/A");
        bsHtml += kvRow("Instrument", is.status || "--");
        bsHtml += kvRow("Trades Today", fmtInt(is.trades_today));
        bsHtml += kvRow("Wins / Losses", (is.wins || 0) + " / " + (is.losses || 0));
        bsHtml += kvRow("PnL", "$" + fmt(is.pnl_today, 2), colorClass(is.pnl_today));
        $("bot-status-content").innerHTML = bsHtml;

        // Journal des trades recents
        var sj = data.signals_journal || {};
        var jHtml = "";
        var trades = sj.recent_trades || [];
        if (trades.length > 0) {
            jHtml += '<div class="data-table"><table><thead><tr><th>Heure</th><th>Dir</th><th>Instrument</th><th>PnL</th></tr></thead><tbody>';
            trades.forEach(function (t) {
                var pnlCls = (t.pnl || 0) >= 0 ? "green" : "red";
                jHtml += '<tr><td>' + (t.time || "--") + '</td><td>' + badgeHtml(t.direction || "--", t.direction === "LONG" ? "badge-green" : "badge-red") + '</td><td>' + (t.symbol || "--") + '</td><td class="' + pnlCls + '">$' + fmt(t.pnl, 2) + '</td></tr>';
            });
            jHtml += '</tbody></table></div>';
        } else {
            jHtml += '<div style="color:var(--text-disabled);font-size:0.8125rem;">Aucun trade recent</div>';
        }

        var rejections = sj.recent_rejections || [];
        if (rejections.length > 0) {
            jHtml += '<div style="margin-top:12px;"><div style="font-weight:600;font-size:0.8125rem;color:var(--orange);margin-bottom:6px;">Signaux rejetes</div>';
            rejections.forEach(function (r) {
                jHtml += '<div style="padding:3px 0;font-size:0.75rem;color:var(--text-secondary);border-bottom:1px solid rgba(255,255,255,0.03);">' + (r.time || "--") + ' — ' + (r.reason || "--") + '</div>';
            });
            jHtml += '</div>';
        }
        $("journal-content").innerHTML = jHtml;
    }

    // ═══════════════════════════════════════════════════════════════
    // Init
    // ═══════════════════════════════════════════════════════════════

    // ═══════════════════════════════════════════════════════════════
    // IB Mini-Chart (bougies 30 premieres minutes)
    // ═══════════════════════════════════════════════════════════════

    var ibChart = null;
    var ibCandleSeries = null;
    var ibVolSeries = null;
    var ibChartLoaded = false;
    var ibChartLastLoad = 0; // throttle refresh 60s (bug #5 fix 22/04)
    var ibYesterdayInfo = {}; // IB veille pour affichage panneau (bug #6 fix 22/04)

    function initIbChart() {
        if (!window.LightweightCharts) return;
        var container = $("ib-chart-container");
        if (!container) return;
        if (ibChart) return; // deja init

        ibChart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 220,
            layout: { background: { type: "solid", color: "#0a0e17" }, textColor: "#94a3b8", fontSize: 10, fontFamily: "JetBrains Mono, monospace" },
            grid: { vertLines: { color: "rgba(255,255,255,0.03)" }, horzLines: { color: "rgba(255,255,255,0.03)" } },
            rightPriceScale: { borderColor: "rgba(255,255,255,0.06)", scaleMargins: { top: 0.05, bottom: 0.15 } },
            timeScale: { borderColor: "rgba(255,255,255,0.06)", timeVisible: true, secondsVisible: false },
        });

        ibCandleSeries = ibChart.addCandlestickSeries({
            upColor: "#00c853", downColor: "#ff5252",
            borderUpColor: "#00c853", borderDownColor: "#ff5252",
            wickUpColor: "#00c853", wickDownColor: "#ff5252",
        });

        ibVolSeries = ibChart.addHistogramSeries({
            priceFormat: { type: "volume" },
            priceScaleId: "vol",
        });
        ibChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

        new ResizeObserver(function () { ibChart.applyOptions({ width: container.clientWidth }); }).observe(container);
    }

    function loadIbChart() {
        if (!ibChart) initIbChart();
        if (!ibChart || !ibCandleSeries) return;

        var sym = currentInstrument === "BOTH" ? "ES" : currentInstrument;

        // Charger les barres completes de la session (comme le chart overview) + les niveaux IB
        Promise.all([
            fetch(API_BASE + "/api/bars/" + sym + "?n=200&tf=1", { headers: apiHeaders() }).then(function (r) { return r.json(); }),
            fetch(API_BASE + "/api/ib-bars/" + sym, { headers: apiHeaders() }).then(function (r) { return r.json(); }),
        ]).then(function (results) {
                var barsData = results[0];
                var ibData = results[1];
                var bars = barsData.bars || [];
                var ibInfo = ibData.today_ib && ibData.today_ib.ib_high ? ibData.today_ib : ibData.yesterday_ib || {};
                // Capture IB veille pour affichage panneau (bug #6 fix)
                ibYesterdayInfo = ibData.yesterday_ib || {};

                if (!bars.length) {
                    var container = $("ib-chart-container");
                    if (container) {
                        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;font-size:0.875rem;">Barres non disponibles</div>';
                    }
                    return;
                }

                ibCandleSeries.setData(bars);

                ibVolSeries.setData(bars.map(function (b) {
                    return { time: b.time, value: b.volume || 0, color: b.close >= b.open ? "rgba(0,200,83,0.3)" : "rgba(255,82,82,0.3)" };
                }));

                // Niveaux IB
                if (ibChart._ibLines) {
                    ibChart._ibLines.forEach(function (l) { ibCandleSeries.removePriceLine(l); });
                }
                ibChart._ibLines = [];

                if (ibInfo.ib_high) {
                    ibChart._ibLines.push(ibCandleSeries.createPriceLine({
                        price: ibInfo.ib_high, color: "#ffc107", lineWidth: 2,
                        lineStyle: 0, axisLabelVisible: true, title: "IB HIGH",
                    }));
                }
                if (ibInfo.ib_low) {
                    ibChart._ibLines.push(ibCandleSeries.createPriceLine({
                        price: ibInfo.ib_low, color: "#ffc107", lineWidth: 2,
                        lineStyle: 0, axisLabelVisible: true, title: "IB LOW",
                    }));
                }
                if (ibInfo.sess_high) {
                    ibChart._ibLines.push(ibCandleSeries.createPriceLine({
                        price: ibInfo.sess_high, color: "#ffffff", lineWidth: 1,
                        lineStyle: 1, axisLabelVisible: true, title: "SESS H",
                    }));
                }
                if (ibInfo.sess_low) {
                    ibChart._ibLines.push(ibCandleSeries.createPriceLine({
                        price: ibInfo.sess_low, color: "#ffffff", lineWidth: 1,
                        lineStyle: 1, axisLabelVisible: true, title: "SESS L",
                    }));
                }
                // VPOC + VWAP si disponibles dans les niveaux du chart
                (barsData.levels || []).forEach(function (lvl) {
                    if (lvl.title === "VPOC" || lvl.title === "VWAP D") {
                        ibChart._ibLines.push(ibCandleSeries.createPriceLine({
                            price: lvl.price, color: lvl.color, lineWidth: 1,
                            lineStyle: 1, axisLabelVisible: true, title: lvl.title,
                        }));
                    }
                });

                ibChart.timeScale().fitContent();
                ibChartLoaded = true;
            })
            .catch(function (err) { console.error("IB chart error:", err); });
    }

    // ═══════════════════════════════════════════════════════════════
    // IB Canvas — Schema visuel Initial Balance
    // ═══════════════════════════════════════════════════════════════

    function drawIbCanvas(ib, instr) {
        var canvas = $("ib-canvas");
        if (!canvas) return;

        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var W = rect.width, H = rect.height;

        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, W, H);

        var banner = data && data.banner ? data.banner : {};
        var sym = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var price = banner[sym] ? banner[sym].price : 0;

        // Si IB pas forme, message
        if (!ib.ib_high_price && !ib.ib_low_price) {
            ctx.font = "14px Inter, sans-serif";
            ctx.fillStyle = "#64748b";
            ctx.textAlign = "center";
            ctx.fillText("IB pas encore forme (attendre session US 09:30-10:00 ET)", W / 2, H / 2 - 10);
            ctx.font = "11px 'JetBrains Mono', monospace";
            ctx.fillText("Les donnees seront disponibles apres la premiere heure", W / 2, H / 2 + 15);
            return;
        }

        var ibH = ib.ib_high_price;
        var ibL = ib.ib_low_price;
        var ibRange = ibH - ibL;
        if (ibRange <= 0) return;

        // Session range pour contexte
        var sessH = (instr && instr.levels) ? instr.levels.sess_high_price : ibH;
        var sessL = (instr && instr.levels) ? instr.levels.sess_low_price : ibL;
        var viewMax = Math.max(ibH, sessH || ibH, price || ibH) + ibRange * 0.3;
        var viewMin = Math.min(ibL, sessL || ibL, price || ibL) - ibRange * 0.3;
        var viewRange = viewMax - viewMin;

        var marginL = 70, marginR = 70, marginT = 20, marginB = 20;
        var chartW = W - marginL - marginR;
        var chartH = H - marginT - marginB;

        function pToY(p) { return marginT + ((viewMax - p) / viewRange) * chartH; }

        // IB Zone (rectangle jaune)
        var ibTop = pToY(ibH);
        var ibBot = pToY(ibL);
        ctx.fillStyle = "rgba(255,193,7,0.1)";
        ctx.fillRect(marginL, ibTop, chartW, ibBot - ibTop);
        ctx.strokeStyle = "#ffc107";
        ctx.lineWidth = 2;
        ctx.strokeRect(marginL, ibTop, chartW, ibBot - ibTop);

        // IB label au centre
        ctx.font = "bold 12px Inter, sans-serif";
        ctx.fillStyle = "#ffc107";
        ctx.textAlign = "center";
        ctx.fillText("IB RANGE", W / 2, (ibTop + ibBot) / 2 - 8);
        ctx.font = "bold 14px 'JetBrains Mono', monospace";
        ctx.fillText(fmt(ib.ib_range_ticks, 0) + " ticks", W / 2, (ibTop + ibBot) / 2 + 12);

        // Extension arrows si broken
        if (ib.ib_broken_up && sessH > ibH) {
            ctx.fillStyle = "rgba(0,200,83,0.1)";
            ctx.fillRect(marginL, pToY(sessH), chartW, ibTop - pToY(sessH));
            ctx.strokeStyle = "#00c853";
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 3]);
            ctx.strokeRect(marginL, pToY(sessH), chartW, ibTop - pToY(sessH));
            ctx.setLineDash([]);
            ctx.font = "10px Inter, sans-serif";
            ctx.fillStyle = "#00c853";
            ctx.fillText("EXTENSION UP " + fmt(ib.ib_extension_ratio, 2) + "x", W / 2, pToY(sessH) + 14);
        }
        if (ib.ib_broken_down && sessL < ibL) {
            ctx.fillStyle = "rgba(255,82,82,0.1)";
            ctx.fillRect(marginL, ibBot, chartW, pToY(sessL) - ibBot);
            ctx.strokeStyle = "#ff5252";
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 3]);
            ctx.strokeRect(marginL, ibBot, chartW, pToY(sessL) - ibBot);
            ctx.setLineDash([]);
            ctx.font = "10px Inter, sans-serif";
            ctx.fillStyle = "#ff5252";
            ctx.fillText("EXTENSION DOWN " + fmt(ib.ib_extension_ratio, 2) + "x", W / 2, pToY(sessL) - 6);
        }

        // Price levels (right side)
        function drawPriceLine(p, label, color) {
            if (!p) return;
            var y = pToY(p);
            ctx.strokeStyle = color;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(marginL - 5, y);
            ctx.lineTo(W - marginR + 5, y);
            ctx.stroke();
            ctx.font = "bold 9px 'JetBrains Mono', monospace";
            ctx.fillStyle = color;
            ctx.textAlign = "left";
            ctx.fillText(label, W - marginR + 8, y + 4);
            ctx.textAlign = "right";
            ctx.fillText(fmtPrice(p), marginL - 8, y + 4);
        }

        drawPriceLine(ibH, "IB H", "#ffc107");
        drawPriceLine(ibL, "IB L", "#ffc107");
        if (sessH && sessH !== ibH) drawPriceLine(sessH, "SESS H", "#ffffff80");
        if (sessL && sessL !== ibL) drawPriceLine(sessL, "SESS L", "#ffffff80");

        // Current price
        if (price) {
            var py = pToY(price);
            ctx.strokeStyle = "#d4af37";
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(marginL, py);
            ctx.lineTo(W - marginR, py);
            ctx.stroke();
            // Arrow + label
            ctx.fillStyle = "#d4af37";
            ctx.font = "bold 11px 'JetBrains Mono', monospace";
            ctx.textAlign = "center";
            ctx.fillText("PRIX " + fmtPrice(price), W / 2, py - 6);
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // GEX Distribution Canvas
    // ═══════════════════════════════════════════════════════════════

    function drawGexDistribution() {
        var canvas = $("gex-canvas");
        if (!canvas) return;
        var instr = getInstr(currentInstrument === "BOTH" ? "ES" : currentInstrument);
        if (!instr || !instr.options) return;
        var o = instr.options;
        var banner = data.banner || {};
        var sym = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var price = banner[sym] ? banner[sym].price : 0;
        if (!price) return;

        // Build strike levels from options data
        var strikes = [];
        function addStrike(name, p, type) {
            if (p && p > 0) strikes.push({ name: name, price: p, type: type });
        }
        addStrike("PUT WALL", o.put_wall_price, "put");
        addStrike("0DTE PUT", o.put_0dte_price, "put");
        addStrike("GEX DN", o.gex_dn_price, "gex");
        addStrike("HVL", o.hvl_price, "hvl");
        addStrike("GEX UP", o.gex_up_price, "gex");
        addStrike("0DTE CALL", o.call_0dte_price, "call");
        addStrike("CALL WALL", o.call_wall_price, "call");
        strikes.sort(function (a, b) { return a.price - b.price; });

        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var W = rect.width, H = rect.height;
        var marginL = 80, marginR = 16, marginT = 20, marginB = 30;
        var barAreaW = W - marginL - marginR;
        var barH = Math.min(28, (H - marginT - marginB) / strikes.length - 4);

        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, W, H);

        // Trier par prix pour positionner verticalement
        var allPrices = strikes.map(function (s) { return s.price; });
        allPrices.push(price);
        var pMin = Math.min.apply(null, allPrices);
        var pMax = Math.max.apply(null, allPrices);
        var pRange = pMax - pMin || 1;

        function pToY(p) {
            return marginT + (1 - (p - pMin) / pRange) * (H - marginT - marginB);
        }

        for (var i = 0; i < strikes.length; i++) {
            var s = strikes[i];
            var y = pToY(s.price);
            var distTicks = Math.round((s.price - price) / 0.25);
            var distAbs = Math.abs(distTicks);
            var maxDist = 800;
            var barW = Math.min(barAreaW, (distAbs / maxDist) * barAreaW);
            barW = Math.max(barW, 20);
            var isBelow = s.price < price;

            var color;
            if (s.type === "put") color = "#00c853";
            else if (s.type === "call") color = "#ff5252";
            else if (s.type === "hvl") color = "#00b4dc";
            else color = "#ff9800";

            // Bar
            ctx.fillStyle = color + "40";
            ctx.fillRect(marginL, y - 8, barW, 16);
            ctx.fillStyle = color;
            ctx.fillRect(marginL, y - 8, 3, 16);

            // Label gauche
            ctx.font = "bold 10px 'JetBrains Mono', monospace";
            ctx.textAlign = "right";
            ctx.fillStyle = color;
            ctx.fillText(s.name, marginL - 6, y + 4);

            // Prix + distance en ticks
            ctx.font = "10px 'JetBrains Mono', monospace";
            ctx.textAlign = "left";
            ctx.fillStyle = "#94a3b8";
            ctx.fillText(s.price.toFixed(2) + " (" + (isBelow ? "-" : "+") + distAbs + "t)", marginL + barW + 6, y + 4);
        }

        // Current price line — positionee proportionnellement
        var priceY = pToY(price);
        ctx.strokeStyle = "#d4af37";
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(marginL, priceY);
        ctx.lineTo(W - marginR, priceY);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#d4af37";
        ctx.font = "bold 10px 'JetBrains Mono', monospace";
        ctx.textAlign = "left";
        ctx.fillText("PRIX: " + price.toFixed(2), marginL + 4, priceY - 3);
    }

    // ═══════════════════════════════════════════════════════════════
    // DOM Ladder Canvas
    // ═══════════════════════════════════════════════════════════════

    function drawDomLadder() {
        var canvas = $("dom-ladder-canvas");
        if (!canvas) return;
        var instr = getInstr(currentInstrument === "BOTH" ? "ES" : currentInstrument);
        if (!instr || !instr.order_flow || !instr.battle_navale) return;

        var of = instr.order_flow;
        var bn = instr.battle_navale;
        var banner = data.banner || {};
        var sym = currentInstrument === "BOTH" ? "es" : currentInstrument.toLowerCase();
        var price = banner[sym] ? banner[sym].price : 0;
        if (!price) return;

        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var W = rect.width, H = rect.height;

        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, W, H);

        // DOM ladder : prix central avec bid/ask pressure de chaque cote
        var centerX = W / 2;
        var rowH = 18;
        var nRows = Math.floor(H / rowH);
        var halfRows = Math.floor(nRows / 2);
        var tick = 0.25;

        var bidPct = of.bid_pct || 0.5;
        var askPct = of.ask_pct || 0.5;
        var maxBarW = centerX - 70;

        for (var i = -halfRows; i <= halfRows; i++) {
            var p = Math.round((price + i * tick) / tick) * tick;
            var y = H / 2 - i * rowH;
            if (y < 0 || y > H) continue;

            var isPrice = Math.abs(p - price) < tick * 0.5;

            // Background
            if (isPrice) {
                ctx.fillStyle = "rgba(212,175,55,0.12)";
                ctx.fillRect(0, y - rowH / 2, W, rowH);
            }

            // Bid bar (gauche)
            var bidW = 0;
            if (i <= 0) {
                bidW = bidPct * maxBarW * (1 - Math.abs(i) / halfRows * 0.7);
                ctx.fillStyle = i === 0 ? "rgba(0,200,83,0.5)" : "rgba(0,200,83,0.2)";
                ctx.fillRect(centerX - 35 - bidW, y - rowH / 2 + 1, bidW, rowH - 2);
            }

            // Ask bar (droite)
            var askW = 0;
            if (i >= 0) {
                askW = askPct * maxBarW * (1 - Math.abs(i) / halfRows * 0.7);
                ctx.fillStyle = i === 0 ? "rgba(255,82,82,0.5)" : "rgba(255,82,82,0.2)";
                ctx.fillRect(centerX + 35, y - rowH / 2 + 1, askW, rowH - 2);
            }

            // Price label
            ctx.font = isPrice ? "bold 11px 'JetBrains Mono', monospace" : "10px 'JetBrains Mono', monospace";
            ctx.textAlign = "center";
            ctx.fillStyle = isPrice ? "#d4af37" : (i > 0 ? "#ff5252" : i < 0 ? "#00c853" : "#f1f5f9");
            ctx.fillText(p.toFixed(2), centerX, y + 4);

            // Grid line
            ctx.strokeStyle = "rgba(255,255,255,0.02)";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(0, y + rowH / 2);
            ctx.lineTo(W, y + rowH / 2);
            ctx.stroke();
        }

        // Headers
        ctx.font = "bold 10px Inter, sans-serif";
        ctx.fillStyle = "#00c853";
        ctx.textAlign = "left";
        ctx.fillText("BID " + (bidPct * 100).toFixed(0) + "%", 8, 14);
        ctx.fillStyle = "#ff5252";
        ctx.textAlign = "right";
        ctx.fillText("ASK " + (askPct * 100).toFixed(0) + "%", W - 8, 14);
        ctx.fillStyle = "#94a3b8";
        ctx.textAlign = "center";
        ctx.fillText("PRIX", centerX, 14);

        // Disclaimer
        ctx.font = "8px Inter, sans-serif";
        ctx.fillStyle = "#475569";
        ctx.textAlign = "center";
        ctx.fillText("Estimation pression — pas un vrai DOM", W / 2, H - 4);
    }

    // ═══════════════════════════════════════════════════════════════
    // Correlation Chart ES vs NQ
    // ═══════════════════════════════════════════════════════════════

    var corrChart = null;
    var corrSeriesES = null;
    var corrSeriesNQ = null;

    function initCorrChart() {
        if (!window.LightweightCharts) return;
        var container = $("corr-chart-container");
        if (!container) return;

        corrChart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 250,
            layout: { background: { type: "solid", color: "#0a0e17" }, textColor: "#94a3b8", fontSize: 10, fontFamily: "JetBrains Mono, monospace" },
            grid: { vertLines: { color: "rgba(255,255,255,0.03)" }, horzLines: { color: "rgba(255,255,255,0.03)" } },
            rightPriceScale: { borderColor: "rgba(255,255,255,0.06)" },
            timeScale: { borderColor: "rgba(255,255,255,0.06)", timeVisible: true },
        });

        corrSeriesES = corrChart.addLineSeries({ color: "#0fbf84", lineWidth: 2, title: "ES" });
        corrSeriesNQ = corrChart.addLineSeries({ color: "#4a9eff", lineWidth: 2, title: "NQ", priceScaleId: "nq" });
        corrChart.priceScale("nq").applyOptions({ scaleMargins: { top: 0.05, bottom: 0.05 } });

        new ResizeObserver(function () { corrChart.applyOptions({ width: container.clientWidth }); }).observe(container);
    }

    function loadCorrChart() {
        if (!corrChart) initCorrChart();
        if (!corrChart) return;

        // Fetch both ES and NQ bars
        Promise.all([
            fetch(API_BASE + "/api/bars/ES?n=200&tf=" + chartTf, { headers: apiHeaders() }).then(function (r) { return r.json(); }),
            fetch(API_BASE + "/api/bars/NQ?n=200&tf=" + chartTf, { headers: apiHeaders() }).then(function (r) { return r.json(); }),
        ]).then(function (results) {
            var esData = results[0].bars || [];
            var nqData = results[1].bars || [];
            if (esData.length && nqData.length) {
                // Normaliser les deux au meme base (% change depuis la premiere barre)
                var esBase = esData[0].close;
                var nqBase = nqData[0].close;
                corrSeriesES.setData(esData.map(function (b) { return { time: b.time, value: ((b.close - esBase) / esBase) * 100 }; }));
                corrSeriesNQ.setData(nqData.map(function (b) { return { time: b.time, value: ((b.close - nqBase) / nqBase) * 100 }; }));
                corrChart.timeScale().fitContent();
            }
        });
    }

    // ═══════════════════════════════════════════════════════════════
    // Signal Mini-Chart (Entry / SL / TP)
    // ═══════════════════════════════════════════════════════════════

    var sigChart = null;
    var sigSeries = null;

    function initSignalChart() {
        if (!window.LightweightCharts) return;
        var container = $("signal-chart-container");
        if (!container) return;

        sigChart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 250,
            layout: { background: { type: "solid", color: "#0a0e17" }, textColor: "#94a3b8", fontSize: 10, fontFamily: "JetBrains Mono, monospace" },
            grid: { vertLines: { color: "rgba(255,255,255,0.03)" }, horzLines: { color: "rgba(255,255,255,0.03)" } },
            rightPriceScale: { borderColor: "rgba(255,255,255,0.06)" },
            timeScale: { borderColor: "rgba(255,255,255,0.06)", timeVisible: true },
        });

        sigSeries = sigChart.addCandlestickSeries({
            upColor: "#00c853", downColor: "#ff5252",
            borderUpColor: "#00c853", borderDownColor: "#ff5252",
            wickUpColor: "#00c853", wickDownColor: "#ff5252",
        });

        new ResizeObserver(function () { sigChart.applyOptions({ width: container.clientWidth }); }).observe(container);
    }

    function loadSignalChart() {
        if (!sigChart) initSignalChart();
        if (!sigChart || !sigSeries) return;

        var sym = currentInstrument === "BOTH" ? "ES" : currentInstrument;
        fetch(API_BASE + "/api/bars/" + sym + "?n=50&tf=" + chartTf, { headers: apiHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.bars || !d.bars.length) return;
                sigSeries.setData(d.bars);

                // Remove old lines
                if (sigChart._sigLines) {
                    sigChart._sigLines.forEach(function (l) { sigSeries.removePriceLine(l); });
                }
                sigChart._sigLines = [];

                // Add SL/TP from suggestion
                var instr = getInstr(sym);
                if (instr && instr.suggestion) {
                    var s = instr.suggestion;
                    if (s.sl_price) {
                        sigChart._sigLines.push(sigSeries.createPriceLine({ price: s.sl_price, color: "#ff5252", lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "SL" }));
                    }
                    if (s.tp_price) {
                        sigChart._sigLines.push(sigSeries.createPriceLine({ price: s.tp_price, color: "#00c853", lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "TP" }));
                    }
                    // Entry = current price
                    var banner = data.banner || {};
                    var curP = banner[sym.toLowerCase()] ? banner[sym.toLowerCase()].price : 0;
                    if (curP) {
                        sigChart._sigLines.push(sigSeries.createPriceLine({ price: curP, color: "#d4af37", lineWidth: 2, lineStyle: 1, axisLabelVisible: true, title: "ENTRY" }));
                    }
                }
                sigChart.timeScale().fitContent();
            });
    }

    // ═══════════════════════════════════════════════════════════════
    // Page-specific chart loaders
    // ═══════════════════════════════════════════════════════════════

    var levelsChartsLoaded = false;
    var signalsChartsLoaded = false;
    var ctaLoaded = false;
    var mqLoaded = false;

    // ═══════════════════════════════════════════════════════════════
    // PAGE: CTA POSITIONING
    // ═══════════════════════════════════════════════════════════════

    var CTA_NAMES = {
        "ES": "ES", "NQ": "NQ", "GOLD": "Gold",
        "TREASURY_10Y": "10Y", "TREASURY_2Y": "2Y",
        "BRENT": "Brent", "EUR_USD": "EUR/USD", "CHF_USD": "CHF/USD",
        "GSCI_COMMODITY": "GSCI", "US_TREASURY_BOND": "US Bond",
    };
    var CTA_FULLNAMES = {
        "ES": "E-mini S&P 500", "NQ": "E-mini NASDAQ", "GOLD": "Gold",
        "TREASURY_10Y": "Treasury 10Y", "TREASURY_2Y": "Treasury 2Y",
        "BRENT": "Brent Oil", "EUR_USD": "EUR/USD", "CHF_USD": "CHF/USD",
        "GSCI_COMMODITY": "GSCI Commodity", "US_TREASURY_BOND": "US Treasury Bond",
    };

    function loadCtaData() {
        fetch(API_BASE + "/api/cta", { headers: apiHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                renderCta(d);
                ctaLoaded = true;
                ctaLastLoad = Date.now();
            })
            .catch(function (e) { console.error("CTA error:", e); });
    }

    function renderCta(d) {
        var today = d.today;
        var yesterday = d.yesterday;
        var conclusion = d.conclusion || {};

        // Conclusion / Decryptage
        var concHtml = '<div style="font-size:1.125rem;font-weight:700;margin-bottom:12px;color:var(--gold);">' + (conclusion.summary || "--") + '</div>';
        (conclusion.signals || []).forEach(function (s) {
            var color = s.signal === "LONG" ? "var(--green)" : s.signal === "SHORT" ? "var(--red)" : "var(--text-secondary)";
            concHtml += '<div style="display:flex;align-items:center;gap:8px;padding:4px 0;">';
            concHtml += badgeHtml(s.instrument, s.signal === "LONG" ? "badge-green" : s.signal === "SHORT" ? "badge-red" : "badge-gray");
            concHtml += '<span style="color:' + color + ';font-weight:600;">' + s.text + '</span>';
            concHtml += '</div>';
        });
        $("cta-conclusion").innerHTML = concHtml;

        // Today CTA
        renderCtaTable($("cta-today"), today);

        // Yesterday CTA
        renderCtaTable($("cta-yesterday"), yesterday);

        // Changes
        renderCtaChanges(today, yesterday);

        // Heatmap canvas
        drawCtaHeatmap(today);

        // Advice
        var advHtml = "";
        (conclusion.advice || []).forEach(function (a) {
            var iconMap = { ok: "&#10003;", warn: "!", danger: "&#10007;", info: "i" };
            advHtml += '<div class="conseil ' + a.type + '"><div class="conseil-icon">' + (iconMap[a.type] || "?") + '</div><div>' + a.text + '</div></div>';
        });
        if (!advHtml) advHtml = '<div style="color:var(--text-disabled);">Pas de conseil specifique</div>';
        $("cta-advice").innerHTML = advHtml;
    }

    function renderCtaTable(container, data) {
        if (!container || !data || !data.CTA) {
            if (container) container.innerHTML = '<div style="color:var(--text-disabled);">Pas de donnees</div>';
            return;
        }
        var cta = data.CTA;
        var h = '<div style="font-size:0.6875rem;color:var(--text-disabled);margin-bottom:8px;">Date: ' + (data.date || "--") + '</div>';
        Object.keys(cta).forEach(function (key) {
            var c = cta[key];
            var pos = c.position_today || 0;
            var color = pos > 0.5 ? "var(--green)" : pos < -0.5 ? "var(--red)" : "var(--text-secondary)";
            var label = pos > 0.5 ? "LONG" : pos < -0.5 ? "SHORT" : "NEUTRE";
            var barPct = Math.min(100, Math.abs(pos) / 3 * 100);
            var barColor = pos > 0 ? "var(--green)" : "var(--red)";
            var name = CTA_FULLNAMES[key] || key;

            h += '<div style="padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.03);">';
            h += '<div style="display:flex;justify-content:space-between;align-items:center;">';
            h += '<span style="font-size:0.8125rem;font-weight:500;">' + name + '</span>';
            h += '<span class="mono" style="font-weight:700;color:' + color + ';">' + pos.toFixed(2) + ' ' + badgeHtml(label, pos > 0.5 ? "badge-green" : pos < -0.5 ? "badge-red" : "badge-gray") + '</span>';
            h += '</div>';
            h += '<div class="gauge" style="margin-top:3px;"><div class="gauge-fill" style="width:' + barPct + '%;background:' + barColor + ';"></div></div>';
            h += '<div style="display:flex;justify-content:space-between;font-size:0.625rem;color:var(--text-disabled);margin-top:2px;">';
            h += '<span>z: ' + (c.zscore_3m || 0).toFixed(2) + '</span>';
            h += '<span>1m ago: ' + (c.position_1m_ago || 0).toFixed(2) + '</span>';
            h += '<span>pctl 3m: ' + ((c.percentile_3m || 0) * 100).toFixed(0) + '%</span>';
            h += '</div></div>';
        });
        container.innerHTML = h;
    }

    function renderCtaChanges(today, yesterday) {
        var container = $("cta-changes");
        if (!container || !today || !yesterday || !today.CTA || !yesterday.CTA) {
            if (container) container.innerHTML = '<div style="color:var(--text-disabled);">Pas de comparaison disponible</div>';
            return;
        }
        var h = '';
        Object.keys(today.CTA).forEach(function (key) {
            var tPos = (today.CTA[key] || {}).position_today || 0;
            var yPos = (yesterday.CTA[key] || {}).position_today || 0;
            var delta = tPos - yPos;
            if (Math.abs(delta) < 0.15) return;
            var name = CTA_FULLNAMES[key] || key;
            var arrow = delta > 0 ? "&#9650;" : "&#9660;";
            var color = delta > 0 ? "var(--green)" : "var(--red)";
            var action = delta > 0 ? "Augmentent les LONGS" : "Augmentent les SHORTS";
            h += '<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03);">';
            h += '<span style="font-weight:600;width:120px;">' + name + '</span>';
            h += '<span style="color:' + color + ';font-size:1.125rem;">' + arrow + '</span>';
            h += '<span class="mono" style="color:' + color + ';font-weight:600;">' + (delta > 0 ? "+" : "") + delta.toFixed(2) + '</span>';
            h += '<span style="color:var(--text-secondary);font-size:0.8125rem;">' + action + '</span>';
            h += '</div>';
        });
        if (!h) h = '<div style="color:var(--text-disabled);">Pas de changement significatif</div>';
        container.innerHTML = h;
    }

    function drawCtaHeatmap(data) {
        var canvas = $("cta-heatmap-canvas");
        if (!canvas || !data || !data.CTA) return;

        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var W = rect.width, H = rect.height;

        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, W, H);

        var cta = data.CTA;
        var keys = Object.keys(cta);
        var cellW = (W - 40) / keys.length;
        var cellH = 60;
        var startY = 40;

        // Header
        ctx.font = "bold 10px Inter, sans-serif";
        ctx.textAlign = "center";

        keys.forEach(function (key, i) {
            var c = cta[key];
            var pos = c.position_today || 0;
            var x = 20 + i * cellW + cellW / 2;
            var y = startY;

            // Color based on position
            var r, g, b;
            if (pos > 0) {
                var intensity = Math.min(1, pos / 3);
                r = 0; g = Math.round(200 * intensity); b = Math.round(83 * intensity);
            } else {
                var intensity = Math.min(1, Math.abs(pos) / 3);
                r = Math.round(255 * intensity); g = Math.round(82 * intensity); b = Math.round(82 * intensity);
            }

            // Cell
            ctx.fillStyle = "rgba(" + r + "," + g + "," + b + ",0.3)";
            ctx.fillRect(20 + i * cellW + 2, y, cellW - 4, cellH);
            ctx.strokeStyle = "rgba(" + r + "," + g + "," + b + ",0.5)";
            ctx.lineWidth = 1;
            ctx.strokeRect(20 + i * cellW + 2, y, cellW - 4, cellH);

            // Name
            ctx.fillStyle = "#f1f5f9";
            ctx.font = "bold 9px Inter, sans-serif";
            var shortName = CTA_NAMES[key] || key;
            ctx.fillText(shortName, x, y + 16);

            // Position value
            ctx.font = "bold 14px 'JetBrains Mono', monospace";
            ctx.fillStyle = pos > 0.3 ? "#00c853" : pos < -0.3 ? "#ff5252" : "#94a3b8";
            ctx.fillText((pos > 0 ? "+" : "") + pos.toFixed(1), x, y + 36);

            // Z-score
            ctx.font = "9px 'JetBrains Mono', monospace";
            ctx.fillStyle = "#64748b";
            ctx.fillText("z:" + (c.zscore_3m || 0).toFixed(1), x, y + 52);
        });

        // Legend
        ctx.font = "10px Inter, sans-serif";
        ctx.fillStyle = "#64748b";
        ctx.textAlign = "left";
        ctx.fillText("Position: ", 20, startY + cellH + 30);
        // Gradient bar
        var grd = ctx.createLinearGradient(80, 0, W - 40, 0);
        grd.addColorStop(0, "rgba(255,82,82,0.6)");
        grd.addColorStop(0.5, "rgba(100,100,100,0.2)");
        grd.addColorStop(1, "rgba(0,200,83,0.6)");
        ctx.fillStyle = grd;
        ctx.fillRect(80, startY + cellH + 20, W - 140, 12);
        ctx.fillStyle = "#ff5252";
        ctx.textAlign = "left";
        ctx.fillText("SHORT", 80, startY + cellH + 48);
        ctx.fillStyle = "#00c853";
        ctx.textAlign = "right";
        ctx.fillText("LONG", W - 60, startY + cellH + 48);
    }

    // ══════��════════════════════════════════════════════════════════
    // PAGE: MENTHORQ DETAIL
    // ═════��═════════════════════════════════════════════════════════

    function loadMenthorqData() {
        fetch(API_BASE + "/api/menthorq", { headers: apiHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                renderMenthorq(d);
                mqLoaded = true;
                mqLastLoad = Date.now();
            })
            .catch(function (e) { console.error("MQ error:", e); });
    }

    function renderMenthorq(d) {
        var date = d.date || "--";
        ["es", "nq"].forEach(function (sym) {
            var s = d[sym] || {};
            var prefix = "mq-" + sym;

            // Key Levels
            var kl = s.key_levels || {};
            var klHtml = '<div style="font-size:0.6875rem;color:var(--text-disabled);margin-bottom:6px;">Date: ' + date + '</div>';
            // Gamma Condition — l'info la plus importante
            var gc = kl["Gamma Condition"] || kl["gamma_condition"] || s.gamma_condition;
            if (gc) {
                var gcColor = gc === "Positive" ? "var(--green)" : gc === "Negative" ? "var(--red)" : "var(--text-secondary)";
                var gcBg = gc === "Positive" ? "rgba(0,200,83,0.1)" : gc === "Negative" ? "rgba(255,82,82,0.1)" : "transparent";
                var gcText = gc === "Positive" ? "GAMMA POSITIF — Le marche AMORTIT les mouvements (mean-reversion)" : "GAMMA NEGATIF — Le marche AMPLIFIE les mouvements (trending)";
                klHtml += '<div style="border:2px solid ' + gcColor + ';border-radius:8px;padding:10px;margin-bottom:10px;background:' + gcBg + ';text-align:center;">';
                klHtml += '<div style="font-size:1.25rem;font-weight:800;color:' + gcColor + ';">' + gc.toUpperCase() + ' GAMMA</div>';
                klHtml += '<div style="font-size:0.75rem;color:var(--text-secondary);margin-top:4px;">' + gcText + '</div>';
                klHtml += '</div>';
            }
            // P/C OI Ratio
            var pcoi = kl["Put/Call OI"] || kl["pc_oi"];
            if (pcoi) {
                klHtml += kvRow("Put/Call OI Ratio", fmt(pcoi, 2), pcoi > 1.5 ? "red" : pcoi < 0.8 ? "green" : "");
            }
            var klOrder = ["Call Resistance", "Call Resistance 0DTE", "High Vol Level", "Put Support", "Put Support 0DTE", "1D Max.", "1D Min.", "Implied Vol 30D", "Total GEX", "Net GEX", "Expiring GEX", "Put/Call GEX", "Total DEX", "Net DEX", "Put/Call DEX", "Distance to HVL %"];
            klOrder.forEach(function (key) {
                var val = kl[key];
                if (val == null) return;
                var isPrice = typeof val === "number" && val > 100;
                klHtml += kvRow(key, isPrice ? fmtPrice(val) : String(val));
            });
            $(prefix + "-keylevels").innerHTML = klHtml;

            // BL Levels
            var bls = s.bl_levels || [];
            var blHtml = "";
            if (bls.length > 0) {
                var curBanner = data && data.banner && data.banner[sym];
                var curPrice = curBanner ? curBanner.price : 0;
                bls.sort(function (a, b) { return Math.abs(a.price - curPrice) - Math.abs(b.price - curPrice); });
                bls.forEach(function (bl) {
                    var dist = curPrice > 0 ? Math.round((bl.price - curPrice) / 0.25) : 0;
                    var distColor = dist > 0 ? "var(--green)" : "var(--red)";
                    blHtml += '<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.03);">';
                    blHtml += '<span style="font-weight:600;">' + bl.name + '</span>';
                    blHtml += '<span class="mono">' + fmtPrice(bl.price) + ' <span style="color:' + distColor + ';">(' + (dist >= 0 ? "+" : "") + dist + 't)</span></span>';
                    blHtml += '</div>';
                });
            } else {
                blHtml = '<div style="color:var(--text-disabled);">Pas de donnees</div>';
            }
            $(prefix + "-bl").innerHTML = blHtml;

            // GEX Strikes
            var gex = s.gex_strikes || [];
            var gw = s.gamma_wall_0dte;
            var gexHtml = "";
            if (gw) gexHtml += kvRow("Gamma Wall 0DTE", fmtPrice(gw), "gold");
            var ng = s.netgex || {};
            if (ng["Top Net GEX Strikes"]) {
                var tops = ng["Top Net GEX Strikes"];
                gexHtml += kvRow("Top Strikes", tops.map(function (p) { return fmtPrice(p); }).join(", "), "cyan");
            }
            gex.forEach(function (g) {
                gexHtml += kvRow(g.name, fmtPrice(g.price));
            });
            if (!gexHtml) gexHtml = '<div style="color:var(--text-disabled);">Pas de donnees</div>';
            $(prefix + "-gex").innerHTML = gexHtml;

            // QScores
            var qs = s.qscores || {};
            var qsHtml = "";
            var scoreNames = { option: "Option", momentum: "Momentum", volatility: "Volatility", seasonality: "Seasonality" };
            Object.keys(scoreNames).forEach(function (key) {
                var val = qs[key];
                if (val == null) return;
                var color = val >= 3 ? "var(--green)" : val >= 2 ? "var(--cyan)" : val >= 1 ? "var(--orange)" : "var(--red)";
                var barPct = (val / 5) * 100;
                qsHtml += '<div style="padding:4px 0;">';
                qsHtml += '<div style="display:flex;justify-content:space-between;"><span>' + scoreNames[key] + '</span><span class="mono" style="font-weight:700;color:' + color + ';">' + val + '/5</span></div>';
                qsHtml += '<div class="gauge" style="margin-top:2px;"><div class="gauge-fill" style="width:' + barPct + '%;background:' + color + ';"></div></div>';
                qsHtml += '</div>';
            });
            if (!qsHtml) qsHtml = '<div style="color:var(--text-disabled);">Pas de QScores</div>';
            $(prefix + "-qscores").innerHTML = qsHtml;

            // Blind Spots
            var bs = s.blind_spots || [];
            var bsHtml = "";
            if (bs.length > 0) {
                var curBannerBs = data && data.banner && data.banner[sym];
                var curP = curBannerBs ? curBannerBs.price : 0;
                bs.sort(function (a, b) { return Math.abs(a - curP) - Math.abs(b - curP); });
                bs.forEach(function (price) {
                    var dist = curP > 0 ? Math.round((price - curP) / 0.25) : 0;
                    var distColor = dist > 0 ? "var(--green)" : "var(--red)";
                    bsHtml += '<div style="display:flex;justify-content:space-between;padding:2px 0;">';
                    bsHtml += '<span class="mono">' + fmtPrice(price) + '</span>';
                    bsHtml += '<span class="mono" style="color:' + distColor + ';">' + (dist >= 0 ? "+" : "") + dist + 't</span>';
                    bsHtml += '</div>';
                });
            } else {
                bsHtml = '<div style="color:var(--text-disabled);">Pas de blind spots</div>';
            }
            $(prefix + "-blindspots").innerHTML = bsHtml;
        });
    }

    // ═��════════════════════════════��══════════════════════════���═════
    // PAGE: PERFORMANCE
    // ══════════════��═══════════════════════════════��════════════════

    function renderPerformance() {
        if (!data) return;
        var bs = data.bot_status || {};
        var esIs = (data.instrument_status || {}).es || {};
        var nqIs = (data.instrument_status || {}).nq || {};
        var sj = data.signals_journal || {};

        // Aggregated stats
        var totalTrades = (esIs.trades_today || 0) + (nqIs.trades_today || 0);
        var totalWins = (esIs.wins || 0) + (nqIs.wins || 0);
        var totalLosses = (esIs.losses || 0) + (nqIs.losses || 0);
        var totalPnl = (esIs.pnl_today || 0) + (nqIs.pnl_today || 0);
        var wr = totalTrades > 0 ? ((totalWins / totalTrades) * 100).toFixed(1) + "%" : "--";
        var pf = totalLosses > 0 && totalWins > 0 ? (totalWins / totalLosses).toFixed(2) : "--";

        // Big boxes
        var pnlEl = $("perf-pnl-value");
        pnlEl.textContent = "$" + fmt(totalPnl, 2);
        pnlEl.className = "big-box " + (totalPnl > 0 ? "bull" : totalPnl < 0 ? "bear" : "neutral");

        var trEl = $("perf-trades-value");
        trEl.textContent = totalTrades;
        trEl.className = "big-box neutral";

        $("perf-wr-value").textContent = wr;
        $("perf-pf-value").textContent = pf;

        // Bot detail
        var bHtml = "";
        bHtml += kvRow("Statut global", bs.global_status || "OFFLINE");
        bHtml += kvRow("Running", bs.running ? badgeHtml("Bot actif", "badge-green") : badgeHtml("Bot arrete", "badge-red"));
        bHtml += kvRow("Heartbeat", bs.last_heartbeat || "N/A");
        bHtml += '<div style="margin:8px 0;border-top:1px solid var(--border);"></div>';
        bHtml += '<div style="font-weight:600;margin-bottom:4px;">ES</div>';
        bHtml += kvRow("Trades", fmtInt(esIs.trades_today));
        bHtml += kvRow("W/L", (esIs.wins || 0) + " / " + (esIs.losses || 0));
        bHtml += kvRow("PnL", "$" + fmt(esIs.pnl_today, 2), colorClass(esIs.pnl_today));
        bHtml += kvRow("Consecutive Losses", fmtInt(esIs.consecutive_losses));
        bHtml += '<div style="margin:8px 0;border-top:1px solid var(--border);"></div>';
        bHtml += '<div style="font-weight:600;margin-bottom:4px;">NQ</div>';
        bHtml += kvRow("Trades", fmtInt(nqIs.trades_today));
        bHtml += kvRow("W/L", (nqIs.wins || 0) + " / " + (nqIs.losses || 0));
        bHtml += kvRow("PnL", "$" + fmt(nqIs.pnl_today, 2), colorClass(nqIs.pnl_today));
        bHtml += kvRow("Consecutive Losses", fmtInt(nqIs.consecutive_losses));
        $("perf-bot-detail").innerHTML = bHtml;

        // Trades table
        var trades = sj.recent_trades || [];
        var tHtml = "";
        if (trades.length > 0) {
            tHtml += '<div class="data-table"><table><thead><tr><th>Heure</th><th>Dir</th><th>Instr</th><th>Entry</th><th>Exit</th><th>PnL</th></tr></thead><tbody>';
            trades.forEach(function (t) {
                var c = (t.pnl || 0) >= 0 ? "green" : "red";
                tHtml += '<tr><td>' + (t.time || "--") + '</td><td>' + badgeHtml(t.direction || "--", t.direction === "LONG" ? "badge-green" : "badge-red") + '</td><td>' + (t.symbol || "--") + '</td><td class="mono">' + fmtPrice(t.entry_price) + '</td><td class="mono">' + fmtPrice(t.exit_price) + '</td><td class="mono ' + c + '">$' + fmt(t.pnl, 2) + '</td></tr>';
            });
            tHtml += '</tbody></table></div>';
        } else {
            tHtml = '<div style="color:var(--text-disabled);">Aucun trade enregistre — le bot est en attente de deploiement ML</div>';
        }
        $("perf-trades-table").innerHTML = tHtml;

        // Rejections
        var rejs = sj.recent_rejections || [];
        var rHtml = "";
        if (rejs.length > 0) {
            rejs.forEach(function (r) {
                rHtml += '<div style="padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.03);font-size:0.8125rem;">';
                rHtml += '<span style="color:var(--text-disabled);margin-right:8px;">' + (r.time || "--") + '</span>';
                rHtml += '<span style="color:var(--orange);">' + (r.reason || "--") + '</span>';
                rHtml += '</div>';
            });
        } else {
            rHtml = '<div style="color:var(--text-disabled);">Aucun signal rejete</div>';
        }
        $("perf-rejections").innerHTML = rHtml;
    }

    // ═══════════════════════════════════════════════════════════════
    // PAGE: PAPER TRADING (bridge mia_paper_trader.py via /api/paper_trades)
    // ═══════════════════════════════════════════════════════════════

    var paperData = null;
    var paperFetchErrors = 0;

    // Fix B1 (code-reviewer 22/04) : backend ecrit "LONG"/"SHORT" (string),
    // frontend historiquement teste === 1. Helper accepte les 2 formats.
    function _isLong(d) { return d === 1 || d === "LONG"; }
    function _isShort(d) { return d === -1 || d === "SHORT"; }

    function fetchPaperTrades() {
        fetchWithAuth(API_BASE + "/api/paper_trades", { method: "GET" })
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (d) {
                paperFetchErrors = 0;
                paperData = d;
                renderPaperBadge();
                if (currentPage === "paper") renderPaperPage();
            })
            .catch(function (err) {
                paperFetchErrors++;
                if (paperFetchErrors < 5) console.warn("Paper fetch error:", err);
            });
    }

    function _paperStatBox(label, value, sub, color) {
        color = color || 'var(--text-primary)';
        return '<div style="border:1px solid var(--border);border-radius:6px;padding:10px;text-align:center;background:rgba(255,255,255,0.02);">' +
            '<div style="color:var(--text-secondary);font-size:0.75rem;">' + label + '</div>' +
            '<div style="font-size:1.25rem;font-weight:700;color:' + color + ';margin-top:3px;">' + value + '</div>' +
            (sub ? '<div style="font-size:0.7rem;color:var(--text-disabled);margin-top:2px;">' + sub + '</div>' : '') +
            '</div>';
    }

    function _renderPaperStatsPeriod(el, stats) {
        if (!el) return;
        if (!stats || stats.trades === 0) {
            el.innerHTML = '<div style="color:var(--text-disabled);font-size:0.8125rem;padding:8px;">Pas de donnees historiques</div>';
            return;
        }
        var pnl = stats.pnl_usd || 0;
        var pnlColor = pnl >= 0 ? 'var(--green)' : 'var(--red)';
        var html = '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:6px;font-size:0.8125rem;">' +
            '<div>Trades : <strong>' + (stats.trades || 0) + '</strong></div>' +
            '<div>WR : <strong>' + (stats.wr || 0) + '%</strong></div>' +
            '<div>PF : <strong>' + (stats.pf !== null && stats.pf !== undefined ? stats.pf : '—') + '</strong></div>' +
            '<div>PnL : <strong style="color:' + pnlColor + ';">' + (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2) + '</strong></div>' +
            '</div>';
        if (stats.by_symbol) {
            html += '<div style="margin-top:10px;padding-top:8px;border-top:1px solid var(--border);font-size:0.75rem;">';
            ['ES', 'NQ'].forEach(function (sym) {
                var s = stats.by_symbol[sym] || {};
                var p = s.pnl_usd || 0;
                var c = p >= 0 ? 'var(--green)' : 'var(--red)';
                html += '<div style="display:flex;justify-content:space-between;margin-top:4px;">' +
                    '<span>' + sym + ' : ' + (s.trades || 0) + ' · ' + (s.wr || 0) + '% · PF ' + (s.pf !== null && s.pf !== undefined ? s.pf : '—') + '</span>' +
                    '<span style="color:' + c + ';font-weight:700;">' + (p >= 0 ? '+$' : '-$') + Math.abs(p).toFixed(2) + '</span>' +
                    '</div>';
            });
            html += '</div>';
        }
        el.innerHTML = html;
    }

    function renderPaperBadge() {
        var nav = $("paper-nav-badge");
        var badge = $("paper-trade-badge");
        if (!paperData) return;

        var state = paperData.state || {};
        var openBySymbol = state.open_by_symbol || {};
        var openKeys = Object.keys(openBySymbol);
        var hasOpen = openKeys.length > 0;
        var statsToday = state.stats_today || {};
        var pnlToday = statsToday.pnl_usd || 0;
        var tradesToday = statsToday.trades || 0;

        // Badge nav sidebar
        if (nav) {
            if (hasOpen) {
                nav.style.display = 'inline-block';
                nav.style.background = 'var(--green)';
                nav.style.color = '#000';
                nav.textContent = openKeys.length + ' OPEN';
            } else if (tradesToday > 0) {
                nav.style.display = 'inline-block';
                nav.style.background = pnlToday >= 0 ? 'rgba(0,200,83,0.15)' : 'rgba(255,82,82,0.15)';
                nav.style.color = pnlToday >= 0 ? 'var(--green)' : 'var(--red)';
                nav.textContent = (pnlToday >= 0 ? '+$' : '-$') + Math.abs(Math.round(pnlToday));
            } else {
                nav.style.display = 'none';
            }
        }

        // Badge Conseil Global
        if (badge) {
            if (hasOpen) {
                var sym = openKeys[0];
                var pos = openBySymbol[sym];
                var unrealized = (pos.unrealized_pnl_usd !== undefined && pos.unrealized_pnl_usd !== null) ? pos.unrealized_pnl_usd : 0;
                var positive = unrealized >= 0;
                var dir = _isLong(pos.direction) ? 'BUY' : 'SELL';
                badge.style.display = 'inline-block';
                badge.style.background = positive ? 'rgba(0,200,83,0.2)' : 'rgba(255,82,82,0.2)';
                badge.style.color = positive ? 'var(--green)' : 'var(--red)';
                badge.style.border = '1px solid ' + (positive ? 'var(--green)' : 'var(--red)');
                badge.textContent = (positive ? '🟢 ' : '🔴 ') + sym + ' ' + dir + ' ' + (positive ? '+$' : '-$') + Math.abs(unrealized).toFixed(0);
            } else if (tradesToday > 0) {
                var positiveT = pnlToday >= 0;
                badge.style.display = 'inline-block';
                badge.style.background = positiveT ? 'rgba(0,200,83,0.15)' : 'rgba(255,82,82,0.15)';
                badge.style.color = positiveT ? 'var(--green)' : 'var(--red)';
                badge.style.border = '1px solid ' + (positiveT ? 'var(--green)' : 'var(--red)');
                badge.textContent = '📊 ' + tradesToday + ' trades · ' + (positiveT ? '+$' : '-$') + Math.abs(pnlToday).toFixed(0);
            } else {
                badge.style.display = 'none';
            }
        }
    }

    function renderPaperPage() {
        if (!paperData) return;
        var state = paperData.state || {};

        // ── Statut trader
        var statusEl = $("paper-trader-status");
        if (statusEl) {
            var alive = paperData.paper_trader_alive;
            var age = paperData.state_age_sec;
            if (alive) {
                statusEl.innerHTML = '<span style="color:var(--green);">● Trader actif</span>' +
                    (age !== null && age !== undefined ? ' · maj il y a ' + Math.round(age) + 's' : '');
            } else if (age !== null && age !== undefined) {
                statusEl.innerHTML = '<span style="color:var(--red);">● Trader DOWN</span> · derniere maj il y a ' + Math.round(age) + 's';
            } else {
                statusEl.innerHTML = '<span style="color:var(--text-disabled);">Aucune donnee (trader jamais demarre)</span>';
            }
        }

        // ── Positions ouvertes
        var openEl = $("paper-open-positions");
        var openBySymbol = state.open_by_symbol || {};
        var openKeys = Object.keys(openBySymbol);
        if (openEl) {
            if (openKeys.length === 0) {
                openEl.innerHTML = '<div style="color:var(--text-disabled);grid-column:1/-1;padding:16px;text-align:center;">Aucune position ouverte</div>';
            } else {
                var html = '';
                openKeys.forEach(function (sym) {
                    var p = openBySymbol[sym];
                    var dir = _isLong(p.direction) ? 'BUY' : 'SELL';
                    var dirColor = _isLong(p.direction) ? 'var(--green)' : 'var(--red)';
                    var unrealized = (p.unrealized_pnl_usd !== undefined && p.unrealized_pnl_usd !== null) ? p.unrealized_pnl_usd : 0;
                    var upnlColor = unrealized >= 0 ? 'var(--green)' : 'var(--red)';
                    html += '<div style="border:1px solid ' + dirColor + ';border-radius:8px;padding:12px;background:rgba(255,255,255,0.02);">' +
                        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
                        '<span style="font-weight:800;font-size:1rem;color:' + dirColor + ';">' + sym + ' ' + dir + '</span>' +
                        '<span style="color:' + upnlColor + ';font-weight:700;font-size:1.1rem;">' + (unrealized >= 0 ? '+$' : '-$') + Math.abs(unrealized).toFixed(2) + '</span>' +
                        '</div>' +
                        '<div style="font-size:0.8125rem;display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;">' +
                        '<div>Entry : <strong>' + fmtPrice(p.entry_price) + '</strong></div>' +
                        '<div>Taille : <strong>' + (p.n_micros || 3) + ' micros</strong></div>' +
                        '<div>SL : <strong style="color:var(--red);">' + fmtPrice(p.sl_price) + '</strong>' + (p.sl_ticks ? ' (' + p.sl_ticks + 't)' : '') + '</div>' +
                        '<div>TP : <strong style="color:var(--green);">' + fmtPrice(p.tp_price) + '</strong>' + (p.tp_ticks ? ' (' + p.tp_ticks + 't)' : '') + '</div>' +
                        (p.sl_wall ? '<div style="grid-column:1/-1;color:var(--text-secondary);">Wall SL : <strong>' + p.sl_wall + '</strong>' + (p.sl_tier ? ' (' + p.sl_tier + ')' : '') + '</div>' : '') +
                        (p.rr_ratio ? '<div style="grid-column:1/-1;color:var(--text-secondary);">R:R : <strong>' + p.rr_ratio.toFixed(2) + '</strong>' + (p.expected_payoff_usd !== undefined ? ' · E[$] : <strong>$' + p.expected_payoff_usd.toFixed(2) + '</strong>' : '') + '</div>' : '') +
                        (p.entry_time ? '<div style="grid-column:1/-1;color:var(--text-disabled);font-size:0.75rem;margin-top:4px;">Ouvert : ' + p.entry_time + '</div>' : '') +
                        '</div>' +
                        '</div>';
                });
                openEl.innerHTML = html;
            }
        }

        // ── Stats today
        var statsEl = $("paper-stats-today");
        if (statsEl) {
            var st = state.stats_today || {};
            var pnl = st.pnl_usd || 0;
            var pnlColor = pnl >= 0 ? 'var(--green)' : 'var(--red)';
            statsEl.innerHTML =
                _paperStatBox('Trades', st.trades || 0, (state.trade_count_today || 0) + ' / ' + (state.max_trades_per_day || 10)) +
                _paperStatBox('Win Rate', (st.wr || 0) + '%', (st.wins || 0) + 'W / ' + (st.losses || 0) + 'L') +
                _paperStatBox('Profit Factor', (st.pf !== null && st.pf !== undefined) ? st.pf : '—', '') +
                _paperStatBox('PnL', (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2), (st.pnl_ticks || 0) + ' ticks', pnlColor);
        }

        // ── Closed today
        var closedEl = $("paper-closed-today");
        var closedToday = state.closed_today || [];
        if (closedEl) {
            if (closedToday.length === 0) {
                closedEl.innerHTML = '<div style="color:var(--text-disabled);padding:8px;">Aucun trade ferme aujourd\'hui</div>';
            } else {
                var html = '<table style="width:100%;font-size:0.8125rem;border-collapse:collapse;">' +
                    '<thead><tr style="color:var(--text-secondary);border-bottom:1px solid var(--border);">' +
                    '<th style="text-align:left;padding:6px 4px;">Heure</th><th>Sym</th><th>Dir</th><th>Entry</th><th>Exit</th><th>Exit</th><th>Ticks</th><th>PnL</th><th>Duree</th>' +
                    '</tr></thead><tbody>';
                closedToday.slice().reverse().forEach(function (t) {
                    var dirTxt = _isLong(t.direction) ? 'BUY' : 'SELL';
                    var dirColor = _isLong(t.direction) ? 'var(--green)' : 'var(--red)';
                    var pnl = t.pnl_usd || 0;
                    var pnlC = pnl >= 0 ? 'var(--green)' : 'var(--red)';
                    var reason = t.exit_reason || '?';
                    var reasonColor = reason === 'TP' ? 'var(--green)' : (reason === 'SL' ? 'var(--red)' : 'var(--text-secondary)');
                    var exitTime = t.exit_time ? (t.exit_time.substring(11, 19)) : '?';
                    html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">' +
                        '<td style="padding:5px 4px;color:var(--text-disabled);">' + exitTime + '</td>' +
                        '<td style="text-align:center;font-weight:700;">' + t.symbol + '</td>' +
                        '<td style="text-align:center;color:' + dirColor + ';">' + dirTxt + '</td>' +
                        '<td style="text-align:center;">' + fmtPrice(t.entry_price) + '</td>' +
                        '<td style="text-align:center;">' + fmtPrice(t.exit_price) + '</td>' +
                        '<td style="text-align:center;color:' + reasonColor + ';font-weight:700;">' + reason + '</td>' +
                        '<td style="text-align:center;">' + (t.pnl_ticks || 0) + '</td>' +
                        '<td style="text-align:center;color:' + pnlC + ';font-weight:700;">' + (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2) + '</td>' +
                        '<td style="text-align:center;color:var(--text-disabled);">' + (t.duration_sec ? Math.round(t.duration_sec / 60) + 'min' : '?') + '</td>' +
                        '</tr>';
                });
                html += '</tbody></table>';
                closedEl.innerHTML = html;
            }
        }

        // ── Stats 7d / 30d
        _renderPaperStatsPeriod($("paper-stats-7d"), paperData.stats_7d);
        _renderPaperStatsPeriod($("paper-stats-30d"), paperData.stats_30d);

        // ── Protections (cooldown / circuit breaker)
        var protEl = $("paper-protections");
        if (protEl) {
            var cooldown = state.cooldown_status || {};
            var count = state.trade_count_today || 0;
            var maxTrades = state.max_trades_per_day || 10;
            var html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;">';
            html += '<div style="padding:8px;border:1px solid var(--border);border-radius:6px;">' +
                '<div style="color:var(--text-secondary);font-size:0.75rem;">Trades du jour</div>' +
                '<div style="font-size:1.125rem;font-weight:700;margin-top:3px;">' + count + ' / ' + maxTrades + '</div>' +
                (count >= maxTrades ? '<div style="color:var(--red);font-size:0.75rem;margin-top:2px;">Max atteint</div>' : '') +
                '</div>';
            ['ES', 'NQ'].forEach(function (sym) {
                var cs = cooldown[sym] || {};
                var cd = cs.cooldown_remaining_sec || 0;
                var cb = cs.circuit_breaker_remaining_sec || 0;
                var losses = cs.consec_losses || 0;
                html += '<div style="padding:8px;border:1px solid var(--border);border-radius:6px;">' +
                    '<div style="color:var(--text-secondary);font-size:0.75rem;">' + sym + '</div>';
                if (cb > 0) {
                    html += '<div style="color:var(--red);font-weight:700;margin-top:3px;">⛔ Circuit ' + Math.round(cb / 60) + ' min</div>' +
                        '<div style="font-size:0.75rem;color:var(--text-disabled);">' + losses + ' pertes consec.</div>';
                } else if (cd > 0) {
                    html += '<div style="color:#ff9800;font-weight:700;margin-top:3px;">⏳ Cooldown ' + Math.round(cd / 60) + ' min</div>';
                } else {
                    html += '<div style="color:var(--green);margin-top:3px;">✓ Pret</div>' +
                        (losses > 0 ? '<div style="font-size:0.75rem;color:var(--text-disabled);">' + losses + ' pertes consec.</div>' : '');
                }
                html += '</div>';
            });
            html += '</div>';
            protEl.innerHTML = html;
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // PAGE: ALERTES
    // ═══════════════════════════════════════════════════════════════

    function renderAlerts() {
        if (!data) return;

        var alerts = [];
        var proximity = [];
        var conditions = [];

        // #18 — mode BOTH : collecter alertes des 2 instruments
        var syms = currentInstrument === "BOTH" ? ["es", "nq"] : [currentInstrument.toLowerCase()];
        var instr = getInstr(syms[0].toUpperCase());
        var sym = syms[0];
        var price = data.banner && data.banner[sym] ? data.banner[sym].price : 0;

        // #12 — Level breaks
        syms.forEach(function (s) {
            var lb = (data.level_breaks || {})[s] || [];
            lb.forEach(function (b) {
                var icon = b.signal === "BUY" ? "&#9650;" : "&#9660;";
                var prefix = syms.length > 1 ? s.toUpperCase() + " " : "";
                alerts.push({ level: "warn", text: prefix + b.level + " " + fmtPrice(b.price) + " CASSE — " + b.direction });
            });
        });

        if (instr) {
            var mp = instr.market_profile || {};
            var opts = instr.options || {};
            var of = instr.order_flow || {};
            var vg = instr.vix_gamma || {};
            var lvl = instr.levels || {};
            var im = data.intermarket || {};

            // IB Broken (dans initial_balance, pas market_profile)
            var ibData = instr.initial_balance || {};
            if (ibData.ib_broken_up) alerts.push({ level: "warn", text: "IB casse vers le HAUT — expansion en cours" });
            if (ibData.ib_broken_down) alerts.push({ level: "warn", text: "IB casse vers le BAS — expansion en cours" });

            // VIX
            var vix = vg.vix_level || 0;
            if (vix > 30) alerts.push({ level: "danger", text: "VIX > 30 (" + fmt(vix, 1) + ") — volatilite extreme, reduire la taille" });
            else if (vix > 25) alerts.push({ level: "warn", text: "VIX eleve (" + fmt(vix, 1) + ") — prudence accrue" });

            // RVOL
            var rvol = of.rvol || 0;
            if (rvol > 3) alerts.push({ level: "danger", text: "RVOL extreme (" + fmt(rvol, 1) + ") — climax probable" });
            else if (rvol > 2) alerts.push({ level: "warn", text: "RVOL eleve (" + fmt(rvol, 1) + ") — activite inhabituelle" });

            // Climax
            if (of.climax_signal > 0) alerts.push({ level: "info", text: "Climax BUY detecte — potentiel reversal vendeur" });
            if (of.climax_signal < 0) alerts.push({ level: "info", text: "Climax SELL detecte — potentiel reversal acheteur" });

            // SMT Divergence
            if (im.smt_divergence) alerts.push({ level: "warn", text: "SMT Divergence ES/NQ — les indices ne confirment pas" });

            // News
            var w = data.warnings || {};
            if (w.news_detected) alerts.push({ level: "danger", text: "NEWS detecte : " + (w.news_message || "evenement en cours") });

            // Proximity
            if (opts.call_wall_price && price > 0) {
                var distCall = Math.round((opts.call_wall_price - price) / 0.25);
                if (Math.abs(distCall) < 40) proximity.push({ name: "Call Wall", price: opts.call_wall_price, dist: distCall, color: "var(--red)" });
            }
            if (opts.put_wall_price && price > 0) {
                var distPut = Math.round((opts.put_wall_price - price) / 0.25);
                if (Math.abs(distPut) < 40) proximity.push({ name: "Put Wall", price: opts.put_wall_price, dist: distPut, color: "var(--green)" });
            }
            if (opts.hvl_price && price > 0) {
                var distHvl = Math.round((opts.hvl_price - price) / 0.25);
                if (Math.abs(distHvl) < 20) proximity.push({ name: "HVL", price: opts.hvl_price, dist: distHvl, color: "var(--cyan)" });
            }
            if (mp.cur_vpoc_price && price > 0) {
                var distPoc = Math.round((mp.cur_vpoc_price - price) / 0.25);
                if (Math.abs(distPoc) < 15) proximity.push({ name: "VPOC", price: mp.cur_vpoc_price, dist: distPoc, color: "#e040fb" });
            }
            if (lvl.swing_high_price && price > 0) {
                var distSH = Math.round((lvl.swing_high_price - price) / 0.25);
                if (Math.abs(distSH) < 20) proximity.push({ name: "Swing High", price: lvl.swing_high_price, dist: distSH, color: "#ffffff" });
            }
            if (lvl.swing_low_price && price > 0) {
                var distSL = Math.round((lvl.swing_low_price - price) / 0.25);
                if (Math.abs(distSL) < 20) proximity.push({ name: "Swing Low", price: lvl.swing_low_price, dist: distSL, color: "#ffffff" });
            }
            // IB High/Low
            if (ibData.ib_high_price && price > 0) {
                var distIBH = Math.round((ibData.ib_high_price - price) / 0.25);
                if (Math.abs(distIBH) < 30) proximity.push({ name: "IB High", price: ibData.ib_high_price, dist: distIBH, color: "#ffc107" });
            }
            if (ibData.ib_low_price && price > 0) {
                var distIBL = Math.round((ibData.ib_low_price - price) / 0.25);
                if (Math.abs(distIBL) < 30) proximity.push({ name: "IB Low", price: ibData.ib_low_price, dist: distIBL, color: "#ffc107" });
            }

            // Conditions
            var reg = instr.regime || {};
            conditions.push({ label: "Bias", value: reg.bias || "--", cls: reg.bias === "BULLISH" ? "badge-green" : reg.bias === "BEARISH" ? "badge-red" : "badge-gray" });
            conditions.push({ label: "Mode", value: reg.mode || "--", cls: reg.mode === "TREND" ? "badge-orange" : "badge-cyan" });
            conditions.push({ label: "VIX", value: fmt(vix, 1), cls: vix > 25 ? "badge-red" : vix > 18 ? "badge-orange" : "badge-green" });
            conditions.push({ label: "RVOL", value: fmt(rvol, 2), cls: rvol > 2 ? "badge-red" : rvol > 1 ? "badge-orange" : "badge-green" });
            conditions.push({ label: "Range Pos", value: fmt(reg.range_pos, 0) + "%", cls: "badge-gray" });
            conditions.push({ label: "Delta Dir", value: of.delta_day_dir > 0 ? "Acheteurs" : of.delta_day_dir < 0 ? "Vendeurs" : "Neutre", cls: of.delta_day_dir > 0 ? "badge-green" : of.delta_day_dir < 0 ? "badge-red" : "badge-gray" });
        }

        // Render alerts
        var aHtml = "";
        if (alerts.length === 0) {
            aHtml = '<div style="color:var(--green);font-weight:600;padding:12px;text-align:center;">Aucune alerte — conditions normales</div>';
        } else {
            alerts.forEach(function (a) {
                var iconMap = { danger: "&#10007;", warn: "!", info: "i", ok: "&#10003;" };
                aHtml += '<div class="conseil ' + a.level + '"><div class="conseil-icon">' + (iconMap[a.level] || "?") + '</div><div>' + a.text + '</div></div>';
            });
        }
        $("alerts-active").innerHTML = aHtml;

        // Render proximity
        var pHtml = "";
        if (proximity.length === 0) {
            pHtml = '<div style="color:var(--text-disabled);">Aucun niveau critique a proximite</div>';
        } else {
            proximity.sort(function (a, b) { return Math.abs(a.dist) - Math.abs(b.dist); });
            proximity.forEach(function (p) {
                var arrow = p.dist > 0 ? "&#9650;" : "&#9660;";
                pHtml += '<div style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03);">';
                pHtml += '<span style="font-weight:600;color:' + p.color + ';width:100px;">' + p.name + '</span>';
                pHtml += '<span class="mono">' + fmtPrice(p.price) + '</span>';
                pHtml += '<span class="mono" style="color:' + p.color + ';">' + arrow + ' ' + (p.dist >= 0 ? "+" : "") + p.dist + 't</span>';
                var urgency = Math.abs(p.dist) < 10 ? "badge-red" : Math.abs(p.dist) < 20 ? "badge-orange" : "badge-cyan";
                pHtml += badgeHtml(Math.abs(p.dist) < 10 ? "IMMINENT" : Math.abs(p.dist) < 20 ? "PROCHE" : "APPROCHE", urgency);
                pHtml += '</div>';
            });
        }
        $("alerts-proximity").innerHTML = pHtml;

        // Render conditions
        var cHtml = '<div style="display:flex;flex-wrap:wrap;gap:12px;">';
        conditions.forEach(function (c) {
            cHtml += '<div style="text-align:center;min-width:80px;"><div style="font-size:0.6875rem;color:var(--text-disabled);">' + c.label + '</div><div style="margin-top:4px;">' + badgeHtml(c.value, c.cls) + '</div></div>';
        });
        cHtml += '</div>';
        $("alerts-conditions").innerHTML = cHtml;

        // ── Signaux recents (reuse signalFeedHistory populated by updateSignalFeed)
        var feedEl = $("alerts-signals-feed");
        if (feedEl) {
            if (!signalFeedHistory || signalFeedHistory.length === 0) {
                feedEl.innerHTML = '<div style="color:var(--text-disabled);padding:10px;text-align:center;">Aucun signal recent</div>';
            } else {
                var fHtml = '<div style="max-height:380px;overflow-y:auto;">';
                signalFeedHistory.slice(0, 20).forEach(function (s) {
                    fHtml += '<div style="display:flex;gap:10px;padding:7px 4px;border-bottom:1px solid rgba(255,255,255,0.04);align-items:flex-start;">' +
                        '<span style="color:var(--text-disabled);font-size:0.7rem;min-width:38px;font-family:monospace;">' + (s.time || '--') + '</span>' +
                        '<span style="color:' + (s.color || 'var(--text-primary)') + ';font-weight:700;min-width:16px;text-align:center;">' + (s.icon || '') + '</span>' +
                        '<div style="flex:1;font-size:0.8125rem;">' +
                        '<div style="color:' + (s.color || 'var(--text-primary)') + ';font-weight:600;">' + (s.text || '') + '</div>' +
                        (s.freshness ? '<div style="font-size:0.7rem;color:var(--text-disabled);margin-top:1px;">' + s.freshness + '</div>' : '') +
                        '</div>' +
                        '</div>';
                });
                fHtml += '</div>';
                feedEl.innerHTML = fHtml;
            }
        }

        // ── Paper Events (ouvertures + fermetures du jour + protections actives)
        var peEl = $("alerts-paper-events");
        var peSummary = $("alerts-paper-summary");
        if (peEl) {
            if (!paperData || !paperData.state) {
                peEl.innerHTML = '<div style="color:var(--text-disabled);padding:10px;text-align:center;">Paper trader non demarre</div>';
                if (peSummary) peSummary.textContent = '';
            } else {
                var pState = paperData.state;
                var openSyms = Object.keys(pState.open_by_symbol || {});
                var closed = pState.closed_today || [];
                var events = [];

                // Event : positions ouvertes actives
                openSyms.forEach(function (sym) {
                    var p = pState.open_by_symbol[sym];
                    var dir = _isLong(p.direction) ? 'BUY' : 'SELL';
                    var color = _isLong(p.direction) ? 'var(--green)' : 'var(--red)';
                    var upnl = (p.unrealized_pnl_usd !== undefined && p.unrealized_pnl_usd !== null) ? p.unrealized_pnl_usd : 0;
                    var timeStr = p.entry_time ? p.entry_time.substring(11, 19) : '--';
                    events.push({
                        ts: p.entry_ts || 0,
                        time: timeStr,
                        icon: '►',
                        color: color,
                        text: 'OUVERT ' + sym + ' ' + dir + ' @ ' + fmtPrice(p.entry_price),
                        sub: 'SL ' + fmtPrice(p.sl_price) + ' · TP ' + fmtPrice(p.tp_price) + ' · unrealized ' + (upnl >= 0 ? '+$' : '-$') + Math.abs(upnl).toFixed(2),
                        status: 'EN COURS',
                        statusColor: color,
                    });
                });

                // Event : trades fermes du jour
                closed.forEach(function (t) {
                    var dir = _isLong(t.direction) ? 'BUY' : 'SELL';
                    var pnl = t.pnl_usd || 0;
                    var pnlColor = pnl >= 0 ? 'var(--green)' : 'var(--red)';
                    var reason = t.exit_reason || '?';
                    var reasonColor = reason === 'TP' ? 'var(--green)' : (reason === 'SL' ? 'var(--red)' : 'var(--text-secondary)');
                    var timeStr = t.exit_time ? t.exit_time.substring(11, 19) : '--';
                    events.push({
                        ts: t.exit_ts || 0,
                        time: timeStr,
                        icon: reason === 'TP' ? '✓' : (reason === 'SL' ? '✗' : '●'),
                        color: pnlColor,
                        text: 'FERME ' + t.symbol + ' ' + dir + ' · ' + reason,
                        sub: 'Entry ' + fmtPrice(t.entry_price) + ' → Exit ' + fmtPrice(t.exit_price) + ' · ' + (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2) + ' (' + (t.pnl_ticks || 0) + 't)',
                        status: reason,
                        statusColor: reasonColor,
                    });
                });

                // Tri anti-chronologique
                events.sort(function (a, b) { return (b.ts || 0) - (a.ts || 0); });

                var eHtml = '<div style="max-height:380px;overflow-y:auto;">';
                if (events.length === 0) {
                    eHtml = '<div style="color:var(--text-disabled);padding:10px;text-align:center;">Aucune activite aujourd\'hui</div>';
                } else {
                    events.forEach(function (e) {
                        eHtml += '<div style="padding:8px 4px;border-bottom:1px solid rgba(255,255,255,0.04);">' +
                            '<div style="display:flex;gap:10px;align-items:baseline;">' +
                            '<span style="color:var(--text-disabled);font-size:0.7rem;min-width:55px;font-family:monospace;">' + e.time + '</span>' +
                            '<span style="color:' + e.color + ';font-weight:800;min-width:16px;text-align:center;">' + e.icon + '</span>' +
                            '<span style="flex:1;color:' + e.color + ';font-size:0.8125rem;font-weight:600;">' + e.text + '</span>' +
                            '<span style="font-size:0.65rem;padding:1px 6px;border-radius:3px;background:rgba(255,255,255,0.05);color:' + e.statusColor + ';font-weight:700;">' + e.status + '</span>' +
                            '</div>' +
                            '<div style="font-size:0.7rem;color:var(--text-disabled);margin-left:81px;margin-top:2px;">' + e.sub + '</div>' +
                            '</div>';
                    });
                }

                // Protections actives en bas (cooldown/circuit breaker)
                var cooldown = pState.cooldown_status || {};
                var protMsgs = [];
                ['ES', 'NQ'].forEach(function (sym) {
                    var cs = cooldown[sym] || {};
                    var cb = cs.circuit_breaker_remaining_sec || 0;
                    var cd = cs.cooldown_remaining_sec || 0;
                    if (cb > 0) protMsgs.push('<span style="color:var(--red);font-weight:700;">⛔ ' + sym + ' Circuit ' + Math.round(cb / 60) + ' min</span>');
                    else if (cd > 0) protMsgs.push('<span style="color:#ff9800;font-weight:700;">⏳ ' + sym + ' Cooldown ' + Math.round(cd / 60) + ' min</span>');
                });
                if (protMsgs.length > 0) {
                    eHtml += '<div style="margin-top:10px;padding:8px;background:rgba(255,255,255,0.03);border-radius:4px;font-size:0.8125rem;display:flex;gap:12px;flex-wrap:wrap;">' + protMsgs.join(' · ') + '</div>';
                }
                eHtml += '</div>';
                peEl.innerHTML = eHtml;

                if (peSummary) {
                    var st = pState.stats_today || {};
                    var pnl = st.pnl_usd || 0;
                    var pnlC = pnl >= 0 ? 'var(--green)' : 'var(--red)';
                    peSummary.innerHTML = (st.trades || 0) + ' trades · ' +
                        (openSyms.length > 0 ? '<span style="color:var(--cyan);">' + openSyms.length + ' open</span> · ' : '') +
                        '<span style="color:' + pnlC + ';font-weight:700;">' + (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(0) + '</span>';
                }
            }
        }

        // Badge compteur sidebar
        var badge = $("alerts-badge");
        if (badge) {
            if (alerts.length > 0) {
                badge.textContent = alerts.length;
                badge.style.display = "inline";
            } else {
                badge.style.display = "none";
            }
        }
    }

    // Helpers tier : free=0 / starter=1 / trial=pro=2 / admin=owner=3
    var TIER_LEVELS = { free: 0, starter: 1, trial: 2, pro: 2, premium: 2, admin: 3, owner: 3 };
    function getTierLevel() { return TIER_LEVELS[currentTier] || 0; }
    function isOwner() { return currentTier === "owner" || currentTier === "admin"; }
    function isProOrHigher() { return getTierLevel() >= 2; }
    function isStarterOrHigher() { return getTierLevel() >= 1; }
    function canAccess(requiredLevel) { return getTierLevel() >= requiredLevel; }
    // Compat historique
    function isPremiumOrHigher() { return getTierLevel() >= 2; }

    // ════════ TIER GATING — Pattern D (TradingView-style) ════════
    // Locked sections : badge coin discret (pas d'overlay central)
    // Locked pages : modal elegante au click
    // CTA global unique en bas d'Overview
    function applyTierGating() {
        var level = getTierLevel();

        // 1) Nav links : classe tier-nav-locked (mais cliquable pour ouvrir modal)
        document.querySelectorAll(".sidebar-nav a[data-tier-min]").forEach(function (a) {
            var required = parseInt(a.getAttribute("data-tier-min"), 10) || 0;
            if (level < required) {
                a.classList.add("tier-nav-locked");
                a.setAttribute("data-tier-required", String(required));
            } else {
                a.classList.remove("tier-nav-locked");
                a.removeAttribute("data-tier-required");
            }
        });

        // 2) Sections : floutage leger + badge coin si tier insuffisant
        document.querySelectorAll("[data-tier-min]").forEach(function (el) {
            if (el.tagName === "A") return;  // nav deja traitee
            var required = parseInt(el.getAttribute("data-tier-min"), 10) || 0;
            if (level < required) {
                lockSection(el, required);
            } else {
                unlockSection(el);
            }
        });

        // 3) CTA global Overview : visible uniquement si FREE
        var ctaGlobal = $("overview-cta-global");
        if (ctaGlobal) {
            ctaGlobal.style.display = (level === 0) ? "block" : "none";
            var btnCta = ctaGlobal.querySelector(".overview-cta-global-btn");
            if (btnCta && !btnCta._bound) {
                btnCta._bound = true;
                btnCta.addEventListener("click", function (e) {
                    e.preventDefault();
                    showTrialForm();
                });
            }
        }
    }

    function tierLabelForLevel(lvl) {
        return (lvl >= 2) ? "PRO" : "STARTER";
    }

    function lockSection(el, requiredLevel) {
        if (el.classList.contains("tier-locked")) return;
        el.classList.add("tier-locked");

        // Badge coin discret (pas d'overlay central)
        var badge = document.createElement("div");
        badge.className = "tier-lock-badge";
        var tierName = tierLabelForLevel(requiredLevel);
        badge.setAttribute("data-tier", tierName);
        badge.textContent = tierName;
        badge.title = "Debloquer avec l'essai 7 jours gratuit";
        badge.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            showTrialForm();
        });
        el.appendChild(badge);
    }

    function unlockSection(el) {
        if (!el.classList.contains("tier-locked")) return;
        el.classList.remove("tier-locked");
        var badge = el.querySelector(".tier-lock-badge");
        if (badge) badge.remove();
    }

    // Modal page bloquee (quand user clique sur une page PRO non accessible)
    var PAGE_FEATURES = {
        options: {
            icon: "📊",
            title: "Options & Gamma",
            features: [
                "GEX Distribution en temps reel",
                "Call walls / Put walls / HVL",
                "Niveaux MenthorQ 0DTE",
                "Gamma clusters + VIX 0DTE",
            ],
        },
        orderflow: {
            icon: "📈",
            title: "Order Flow",
            features: [
                "DOM Ladder live",
                "CVD Day + Delta cumule",
                "Footprint bars + Absorption",
                "Climax signals + Large trader ratio",
            ],
        },
        profile: {
            icon: "📐",
            title: "Market Profile",
            features: [
                "VPOC / VAH / VAL du jour",
                "Profile shape (P/b/D/Double)",
                "Open type + Day type",
                "HVN / LVN + Initial Balance",
            ],
        },
        signals: {
            icon: "🎯",
            title: "Signaux & Journal",
            features: [
                "Historique des signaux",
                "Win rate + Profit Factor",
                "Taux de reussite par regime",
                "Chart des performances",
            ],
        },
        cta: {
            icon: "🏦",
            title: "CTA Positioning",
            features: [
                "Exposition CTA long/short",
                "Flux CTA temps reel",
                "Trigger levels de reversal",
                "Positionnement institutionnel",
            ],
        },
        menthorq: {
            icon: "💎",
            title: "MenthorQ Detail",
            features: [
                "Niveaux 0DTE complets",
                "GEX distribution quotidienne",
                "Blind spots gamma",
                "Daily key levels",
            ],
        },
        performance: {
            icon: "📉",
            title: "Performance",
            features: [
                "P&L journalier et cumule",
                "Equity curve",
                "Win rate + Profit Factor",
                "Historique trades complet",
            ],
        },
    };

    function showPageLockModal(pageName) {
        // Supprime modal existante
        var existing = document.querySelector(".page-lock-modal-backdrop");
        if (existing) existing.remove();

        var info = PAGE_FEATURES[pageName] || {
            icon: "🔒",
            title: "Fonctionnalite PRO",
            features: ["Acces complet au dashboard"],
        };

        var backdrop = document.createElement("div");
        backdrop.className = "page-lock-modal-backdrop";
        backdrop.innerHTML =
            '<div class="page-lock-modal">' +
            '<div class="page-lock-modal-icon">' + info.icon + '</div>' +
            '<div class="page-lock-modal-title">' + info.title + ' — Reserve PRO</div>' +
            '<div class="page-lock-modal-sub">Cette page est disponible dans le tier PRO. Essai 7 jours gratuit, sans carte bancaire.</div>' +
            '<ul class="page-lock-modal-features">' +
            info.features.map(function (f) { return '<li>' + f + '</li>'; }).join("") +
            '</ul>' +
            '<button class="page-lock-modal-btn" data-action="trial">DEMARRER L\'ESSAI 7 JOURS</button>' +
            '<button class="page-lock-modal-close">Fermer</button>' +
            '</div>';
        document.body.appendChild(backdrop);

        backdrop.addEventListener("click", function (e) {
            if (e.target === backdrop) backdrop.remove();
        });
        backdrop.querySelector(".page-lock-modal-close").addEventListener("click", function () {
            backdrop.remove();
        });
        backdrop.querySelector(".page-lock-modal-btn").addEventListener("click", function () {
            backdrop.remove();
            showTrialForm();
        });
    }

    function showTrialForm() {
        // Focus sur la section trial dans sidebar
        var trialSection = $("trial-section");
        if (trialSection) {
            trialSection.style.display = "";
            var emailField = $("trial-email");
            if (emailField) emailField.focus();
            // Ouvre la sidebar sur mobile
            var sidebar = $("sidebar");
            if (sidebar && !sidebar.classList.contains("open")) {
                sidebar.classList.add("open");
                var overlay = $("sidebar-overlay");
                if (overlay) overlay.classList.remove("hidden");
            }
        }
    }

    function updateTierIndicator() {
        var el = $("tier-indicator");
        if (!el) return;
        var promoSection = $("promo-section");
        var loginSection = $("login-section");
        var logoutSection = $("logout-section");
        var trialSection = $("trial-section");
        // Cacher le lien "Premium Stripe" pour pro+
        var premiumLink = document.querySelector('a[onclick*="buy.stripe.com"]');
        var isLoggedIn = !!authToken;

        // Trial countdown
        var trialInfo = "";
        if (currentTier === "trial") {
            var expiresAt = parseInt(localStorage.getItem("mia_trial_expires") || "0", 10);
            var secondsLeft = Math.max(0, expiresAt - Math.floor(Date.now() / 1000));
            var daysLeft = Math.ceil(secondsLeft / 86400);
            trialInfo = '<div class="trial-countdown-badge" style="margin-top:6px;">ESSAI ' + daysLeft + 'j</div>';
        }

        if (currentTier === "owner" || currentTier === "admin") {
            el.innerHTML = '<span class="badge" style="font-size:0.75rem;padding:4px 12px;background:linear-gradient(135deg,#d4a017,#ff6b00);color:#000;font-weight:800;letter-spacing:0.5px;">' + currentTier.toUpperCase() + '</span>';
        } else if (currentTier === "pro" || currentTier === "premium") {
            el.innerHTML = '<span class="badge badge-gold" style="font-size:0.75rem;padding:4px 12px;">PRO</span>';
        } else if (currentTier === "trial") {
            el.innerHTML = '<span class="badge" style="font-size:0.75rem;padding:4px 12px;background:#2962ff;color:#fff;font-weight:700;">PRO TRIAL</span>' + trialInfo;
        } else if (currentTier === "starter") {
            el.innerHTML = '<span class="badge" style="font-size:0.75rem;padding:4px 12px;background:#4caf50;color:#fff;font-weight:700;">STARTER</span>';
        } else {
            el.innerHTML = '<span class="badge badge-gray" style="font-size:0.75rem;padding:4px 12px;">FREE</span>';
        }

        // Cache promo + premium link pour tier >= starter
        var hidePaywall = getTierLevel() >= 1;
        if (promoSection) promoSection.style.display = hidePaywall ? "none" : "";
        if (premiumLink) premiumLink.style.display = hidePaywall ? "none" : "";

        // Login/logout
        if (loginSection) loginSection.style.display = isLoggedIn ? "none" : "";
        if (logoutSection) logoutSection.style.display = isLoggedIn ? "" : "none";

        // Trial section : cacher si deja tier>=1
        if (trialSection) trialSection.style.display = hidePaywall ? "none" : "";

        // Upgrade banner (top main content) : visible uniquement en FREE
        var upgradeBanner = $("upgrade-banner");
        if (upgradeBanner) {
            upgradeBanner.style.display = (getTierLevel() === 0) ? "" : "none";
            if (!upgradeBanner._bound) {
                upgradeBanner._bound = true;
                upgradeBanner.addEventListener("click", function () { showTrialForm(); });
            }
        }

        // Appliquer le tier gating (nav + sections)
        applyTierGating();
    }

    function initLogin() {
        var btn = $("login-btn");
        var emailEl = $("login-email");
        var pwdEl = $("login-password");
        var msgEl = $("login-msg");
        var logoutBtn = $("logout-btn");

        function doLogin() {
            var email = (emailEl && emailEl.value || "").trim();
            var pwd = (pwdEl && pwdEl.value || "").trim();
            if (!email || !pwd) {
                if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Email + mot de passe requis"; }
                return;
            }
            if (msgEl) { msgEl.style.color = "var(--text-secondary)"; msgEl.textContent = "Connexion..."; }
            fetch(API_BASE + "/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({ email: email, password: pwd })
            })
                .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
                .then(function (res) {
                    if (res.ok && res.data.token) {
                        authToken = res.data.token;
                        currentTier = res.data.tier || "free";
                        localStorage.setItem("mia_token", authToken);
                        localStorage.setItem("mia_tier", currentTier);
                        if (msgEl) { msgEl.style.color = "var(--green)"; msgEl.textContent = "Connecte (" + currentTier + ")"; }
                        updateTierIndicator();
                        // Reload pour activer les sections admin
                        setTimeout(function () { location.reload(); }, 400);
                    } else {
                        if (msgEl) {
                            msgEl.style.color = "var(--red)";
                            msgEl.textContent = (res.data && res.data.detail) || "Login echoue";
                        }
                    }
                })
                .catch(function () {
                    if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Erreur reseau"; }
                });
        }

        function doLogout() {
            // 1. Stopper le polling AVANT tout (evite race condition)
            if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

            // 2. Reset etat JS local
            authToken = "";
            currentTier = "free";

            // 3. Nettoyer TOUT le localStorage lie a MIA
            localStorage.removeItem("mia_token");
            localStorage.removeItem("mia_tier");
            localStorage.removeItem("mia_trial_expires");
            localStorage.removeItem("mia_utm");

            // 4. Supprimer le cookie HttpOnly mia_session cote serveur
            //    (seul le backend peut supprimer un cookie HttpOnly)
            fetch(API_BASE + "/api/auth/logout", {
                method: "POST",
                credentials: "include"
            }).finally(function () {
                // 5. Redirect vers welcome (pas reload sur /)
                //    Evite de rester sur le dashboard ou le backend renvoie
                //    toutes les donnees meme en tier free
                window.location.href = "/welcome";
            });
        }

        if (btn && !btn._bound) {
            btn._bound = true;
            btn.addEventListener("click", doLogin);
        }
        // Enter key dans password field
        if (pwdEl && !pwdEl._bound) {
            pwdEl._bound = true;
            pwdEl.addEventListener("keydown", function (e) { if (e.key === "Enter") doLogin(); });
        }
        if (emailEl && !emailEl._bound) {
            emailEl._bound = true;
            emailEl.addEventListener("keydown", function (e) { if (e.key === "Enter") doLogin(); });
        }
        if (logoutBtn && !logoutBtn._bound) {
            logoutBtn._bound = true;
            logoutBtn.addEventListener("click", doLogout);
        }
    }

    // Capture UTM params au premier chargement (persistent dans localStorage 30j)
    function captureUtmParams() {
        try {
            var params = new URLSearchParams(window.location.search);
            var utm = {
                utm_source: params.get("utm_source") || "",
                utm_medium: params.get("utm_medium") || "",
                utm_campaign: params.get("utm_campaign") || "",
                referrer: document.referrer || "",
                captured_at: Date.now(),
            };
            // Ne pas ecraser une capture precedente si elle existe et est recente
            var existing = null;
            try { existing = JSON.parse(localStorage.getItem("mia_utm") || "null"); } catch (e) {}
            if (!existing || (Date.now() - (existing.captured_at || 0) > 30 * 86400 * 1000)) {
                if (utm.utm_source || utm.referrer) {
                    localStorage.setItem("mia_utm", JSON.stringify(utm));
                }
            }
        } catch (e) {
            console.warn("[utm] capture failed", e);
        }
    }

    function getStoredUtm() {
        try {
            return JSON.parse(localStorage.getItem("mia_utm") || "{}");
        } catch (e) {
            return {};
        }
    }

    // ── Turnstile (captcha anti-bot) ──
    var turnstileToken = "";
    var turnstileWidgetId = null;

    function initTurnstile() {
        var container = $("turnstile-container");
        if (!container) return;
        var TURNSTILE_SITE_KEY = "0x4AAAAAAC59WSYufqpJqju9";
        function renderWidget() {
            if (!window.turnstile || turnstileWidgetId !== null) return;
            turnstileWidgetId = turnstile.render(container, {
                sitekey: TURNSTILE_SITE_KEY,
                theme: "dark",
                size: "compact",
                callback: function (t) { turnstileToken = t; },
                "expired-callback": function () { turnstileToken = ""; },
                "error-callback": function () { turnstileToken = ""; },
            });
        }
        if (window.turnstile) { renderWidget(); }
        else { setTimeout(renderWidget, 1500); setTimeout(renderWidget, 3000); }
    }

    function resetTurnstile() {
        turnstileToken = "";
        if (turnstileWidgetId !== null && window.turnstile) {
            turnstile.reset(turnstileWidgetId);
        }
    }

    // ── Google Identity Services ──
    function initGoogleSignIn() {
        var btn = $("google-signin-btn");
        if (!btn || btn._bound) return;
        btn._bound = true;
        var GOOGLE_CLIENT_ID = "209489801864-2jpn78qq4lj218fbqauvqluf6jjbnf50.apps.googleusercontent.com";

        function handleGoogleCredential(response) {
            var msgEl = $("trial-msg");
            if (!response.credential) {
                if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Erreur Google Sign-In"; }
                return;
            }
            var utm = getStoredUtm();
            fetch(API_BASE + "/api/auth/google", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({
                    credential: response.credential,
                    rgpd_consent: true,
                    utm_source: utm.utm_source || "",
                    utm_medium: utm.utm_medium || "",
                    utm_campaign: utm.utm_campaign || "",
                    referrer: utm.referrer || ""
                })
            })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.token) {
                    authToken = d.token;
                    currentTier = d.tier || "trial";
                    localStorage.setItem("mia_token", authToken);
                    localStorage.setItem("mia_tier", currentTier);
                    if (d.trial_expires_at) localStorage.setItem("mia_trial_expires", String(d.trial_expires_at));
                    if (msgEl) { msgEl.style.color = "var(--green)"; msgEl.textContent = "Connexion Google reussie !"; }
                    setTimeout(function () { location.reload(); }, 500);
                } else {
                    if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = d.detail || "Erreur Google OAuth"; }
                }
            })
            .catch(function () {
                if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Erreur reseau"; }
            });
        }

        function bindGoogleSDK() {
            if (!window.google || !window.google.accounts) return false;
            google.accounts.id.initialize({
                client_id: GOOGLE_CLIENT_ID,
                callback: handleGoogleCredential,
                auto_select: false,
            });
            // Remplacer le bouton custom par le vrai bouton Google natif (renderButton)
            if (btn) {
                var wrapper = document.createElement("div");
                wrapper.id = "google-btn-wrapper";
                wrapper.style.cssText = "width:100%;margin-bottom:8px;display:flex;justify-content:center;";
                btn.parentNode.replaceChild(wrapper, btn);
                google.accounts.id.renderButton(wrapper, {
                    theme: "outline",
                    size: "large",
                    width: 260,
                    text: "continue_with",
                    locale: "fr",
                });
            }
            return true;
        }

        if (!bindGoogleSDK()) {
            setTimeout(function () {
                if (!bindGoogleSDK()) {
                    // Fallback si SDK echoue (bloqueur pub etc.)
                    btn.addEventListener("click", function (e) {
                        e.preventDefault();
                        var msgEl = $("trial-msg");
                        if (msgEl) { msgEl.style.color = "var(--orange)"; msgEl.textContent = "Google Sign-In indisponible — utilisez email + mot de passe"; }
                    });
                }
            }, 2500);
        }
    }

    function initTrial() {
        var btn = $("trial-btn");
        var firstEl = $("trial-firstname");
        var lastEl = $("trial-lastname");
        var emailEl = $("trial-email");
        var pwdEl = $("trial-password");
        var rgpdEl = $("trial-rgpd");
        var msgEl = $("trial-msg");

        function doTrial() {
            var first = (firstEl && firstEl.value || "").trim();
            var last = (lastEl && lastEl.value || "").trim();
            var email = (emailEl && emailEl.value || "").trim();
            var pwd = (pwdEl && pwdEl.value || "").trim();
            var rgpd = rgpdEl && rgpdEl.checked;

            if (!first || !email || !pwd) {
                if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Prenom, email et mot de passe requis"; }
                return;
            }
            if (first.length < 2) {
                if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Prenom 2+ caracteres"; }
                return;
            }
            if (pwd.length < 6) {
                if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Mot de passe 6+ caracteres"; }
                return;
            }
            if (!rgpd) {
                if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Vous devez accepter les CGU et la confidentialite"; }
                return;
            }
            if (!turnstileToken) {
                if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Completez la verification anti-bot"; }
                return;
            }
            if (msgEl) { msgEl.style.color = "var(--text-secondary)"; msgEl.textContent = "Creation du compte..."; }

            var utm = getStoredUtm();
            var payload = {
                email: email,
                password: pwd,
                first_name: first,
                last_name: last,
                rgpd_consent: true,
                turnstile_token: turnstileToken,
                utm_source: utm.utm_source || "",
                utm_medium: utm.utm_medium || "",
                utm_campaign: utm.utm_campaign || "",
                referrer: utm.referrer || "",
            };

            fetch(API_BASE + "/api/auth/trial", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify(payload)
            })
                .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
                .then(function (res) {
                    if (res.ok && res.data.token) {
                        authToken = res.data.token;
                        currentTier = res.data.tier || "trial";
                        localStorage.setItem("mia_token", authToken);
                        localStorage.setItem("mia_tier", currentTier);
                        if (res.data.trial_expires_at) {
                            localStorage.setItem("mia_trial_expires", String(res.data.trial_expires_at));
                        }
                        if (msgEl) {
                            msgEl.style.color = "var(--green)";
                            msgEl.textContent = "Compte cree — 7 jours PRO !";
                        }
                        resetTurnstile();
                        setTimeout(function () { location.reload(); }, 500);
                    } else {
                        if (msgEl) {
                            msgEl.style.color = "var(--red)";
                            msgEl.textContent = (res.data && res.data.detail) || "Erreur";
                        }
                        resetTurnstile();
                    }
                })
                .catch(function () {
                    if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Erreur reseau"; }
                    resetTurnstile();
                });
        }

        if (btn && !btn._bound) {
            btn._bound = true;
            btn.addEventListener("click", doTrial);
        }
        [firstEl, lastEl, emailEl, pwdEl].forEach(function (el) {
            if (el && !el._bound) {
                el._bound = true;
                el.addEventListener("keydown", function (e) { if (e.key === "Enter") doTrial(); });
            }
        });
    }

    function initPromo() {
        var btn = $("promo-btn");
        var input = $("promo-input");
        var msg = $("promo-msg");
        if (!btn || !input) return;

        function submitPromo() {
            var code = input.value.trim();
            if (!code) return;
            msg.textContent = "Verification...";
            msg.style.color = "var(--text-secondary)";
            fetch(API_BASE + "/api/auth/promo", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({ code: code }),
            })
            .then(function (r) {
                if (!r.ok) throw new Error("invalide");
                return r.json();
            })
            .then(function (d) {
                authToken = d.token;
                currentTier = d.tier;
                localStorage.setItem("mia_token", d.token);
                localStorage.setItem("mia_tier", d.tier);
                msg.textContent = d.message;
                msg.style.color = "var(--green)";
                updateTierIndicator();
                fetchDashboard();
            })
            .catch(function () {
                msg.textContent = "Code invalide";
                msg.style.color = "var(--red)";
            });
        }

        btn.addEventListener("click", submitPromo);
        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") submitPromo();
        });
    }

    // ═══════════════════════════════════════════════════════════════
    // Mode Educatif — Tooltips par card
    // ═══════════════════════════════════════════════════════════════

    var EDU_TIPS = {
        // ─── Overview ───
        "bias-box": {
            title: "Direction du marche",
            body: "Cette case montre la <strong>direction dominante</strong> calculee a partir de 5 facteurs ponderes : ou se situe le prix dans le range du jour (30%), le delta acheteurs/vendeurs (25%), la position par rapport au VWAP (20%), la pente du VWAP (15%) et le cumul des flux (CVD, 10%).",
            action: "Tradez toujours dans le sens indique. Si le bias est neutre, attendez qu'une direction se dessine ou scalpez les deux cotes du range.",
        },
        "mode-box": {
            title: "Type de journee",
            body: "Indique si le marche est en <strong>tendance</strong> (le range depasse 1.2x l'ATR moyen — le prix avance dans une direction) ou en <strong>consolidation</strong> (range &lt; 0.6x ATR — le prix oscille entre support et resistance). La position dans le range (0% = bas, 100% = haut) precise ou on se situe.",
            action: "En tendance : ne jamais aller contre le mouvement, entrer sur les replis. En consolidation : acheter le bas du range, vendre le haut. Le mode determine votre strategie, pas le bias.",
        },
        "gauges-row": {
            title: "Jauges instantanees",
            body: "<strong>VIX</strong> : indice de peur du marche. &lt;15 = calme, 15-20 = normal, 20-25 = eleve, &gt;25 = haute volatilite. <strong>Confiance</strong> : solidite du bias — 80%+ = conviction forte. <strong>Range Pos</strong> : position dans le range du jour (0% = au plus bas, 100% = au plus haut). <strong>RVOL</strong> : volume actuel vs moyenne historique a cette heure (1.0 = normal, &gt;2 = spike). <strong>Sess/ATR</strong> : amplitude du jour vs la moyenne.",
            action: "Lisez les jauges ensemble : VIX eleve + RVOL &gt;2 + Range Pos extreme = zone de retournement probable. Toutes les jauges au milieu = pas de signal fort, attendre.",
        },
        "mtf-section": {
            title: "Alignement multi-timeframe",
            body: "Montre si <strong>les 4 unites de temps</strong> (1min, 5min, 15min, 1h) sont d'accord sur la direction. Chaque TF analyse la position vs VWAP, la direction du delta et le momentum du prix. Quand les 4 sont alignes, le signal est a sa fiabilite maximale.",
            action: "4/4 alignes = signal fort, y aller. 3/4 = acceptable. 2/4 ou moins = conflit entre les TF, ne pas entrer. Le 1h donne la direction macro, le 1min le timing d'entree.",
        },
        "confluence-section": {
            title: "Niveaux en cluster",
            body: "Detecte les zones ou <strong>3 niveaux techniques ou plus</strong> se concentrent dans un rayon de 8 ticks (2 points ES). Plus il y a de niveaux empiles (options, VWAP, profil, swing), plus la zone est difficile a franchir.",
            action: "Un cluster de 4+ niveaux au-dessus du prix = mur de resistance, ne pas acheter la. Un cluster en-dessous = support solide, zone d'achat. Ces zones sont vos cibles de TP et vos placements de SL.",
        },
        "global-section": {
            title: "Verdict global",
            body: "Synthetise <strong>tous les indicateurs</strong> de la page en un seul conseil : regime, delta, volume, niveaux proches et position dans le range. C'est le resume operationnel.",
            action: "Lisez ce verdict en premier quand vous arrivez sur le dashboard. Il vous dit immediatement si c'est le moment de chercher un trade ou d'attendre.",
        },
        "hand-section": {
            title: "Qui controle le marche",
            body: "Identifie en temps reel qui <strong>pousse le prix</strong> : les acheteurs (delta positif, flux agressifs cote Ask) ou les vendeurs (delta negatif, flux cote Bid). La force indique l'intensite de cette domination.",
            action: "Tradez toujours avec le camp dominant, jamais contre. Si la force est faible, la main peut changer a tout moment — attendez une confirmation.",
        },
        // ─── Options ───
        "corridor-section": {
            title: "Corridor de prix options",
            body: "Visualise la <strong>zone de prix defendue par les market makers</strong>. Le Put Wall (support) est le strike ou les dealers achetent pour hedger — ils freinent la baisse. Le Call Wall (resistance) est l'inverse. Le HVL (pivot) separe la zone calme (au-dessus) de la zone volatile (en-dessous).",
            action: "Le prix rebondit generalement entre Put Wall et Call Wall. Un franchissement net d'un des murs = mouvement accelere dans cette direction. Si le prix est sous le HVL, les mouvements sont amplifies.",
        },
        "gex-section": {
            title: "Exposition Gamma des dealers",
            body: "Montre les <strong>7 niveaux d'options cles</strong> tries par distance au prix actuel. Chaque barre represente l'eloignement du strike. Les verts (Put) sont des supports, les rouges (Call) des resistances, le bleu (HVL) est le pivot central.",
            action: "Regardez quel mur est le plus proche : c'est votre prochain obstacle. Si le prix est loin des deux murs, il peut bouger librement. Si un mur 0DTE est proche, attention aux accelerations en fin de journee.",
        },
        // ─── Order Flow ───
        "dom-section": {
            title: "Pression en temps reel",
            body: "Montre le <strong>rapport de force instantane</strong> entre acheteurs et vendeurs. Le % acheteurs = proportion du volume execute au Ask (ordres Market Buy). Le % vendeurs = volume execute au Bid (ordres Market Sell). C'est une photo de la barre en cours.",
            action: "Au-dessus de 55% d'un cote = pression nette. Au-dessus de 60% = forte conviction. Equilibre 45-55% = pas de direction, le prix peut aller dans les deux sens.",
        },
        "delta-section": {
            title: "Flux acheteurs vs vendeurs",
            body: "<strong>Delta bar</strong> = difference Buy Vol - Sell Vol sur la derniere barre. <strong>Delta Day</strong> = cumul depuis l'ouverture. <strong>CVD</strong> = delta cumule total. <strong>Divergence P/D</strong> = le prix et le delta vont dans des directions opposees — signe que le mouvement n'est pas soutenu par le flux reel.",
            action: "Le delta confirme ou infirme le mouvement du prix. Si le prix monte avec un delta negatif, les gros ne suivent pas — le rallye est fragile. La divergence P/D est un des signaux de retournement les plus fiables.",
        },
        "rvol-section": {
            title: "Volume relatif",
            body: "Compare le volume actuel a la <strong>moyenne historique pour cette heure precise</strong>. RVOL 1.0 = volume normal pour ce moment de la journee. &lt;0.5 = marche mort. &gt;2.0 = activite anormale (news, break de niveau). &gt;3.0 = extreme rare (climax, panique).",
            action: "RVOL faible (&lt;0.5) = les signaux techniques sont moins fiables, ne pas forcer de trade. RVOL &gt;2 + delta fort = mouvement soutenu. RVOL &gt;3 = souvent la fin d'un mouvement (climax), pas le debut.",
        },
        "bn-section": {
            title: "Footprint (Bataille Navale)",
            body: "Analyse la <strong>structure interne de chaque barre</strong> : absorptions (gros ordres limites qui bloquent le prix), pression ask/bid (desequilibre directionnel), imbalances (ratio &gt;3:1 entre acheteurs et vendeurs a un prix). Score raw = synthese de tous les signaux footprint.",
            action: "L'absorption elevee a un support confirme que les gros sont la. Le score footprint est un outil de confirmation — ne l'utilisez pas comme signal d'entree seul, mais pour valider un setup technique.",
        },
        // ─── Market Profile ───
        "vp-section": {
            title: "Volume Profile — Distribution du volume par prix",
            body: "Histogramme horizontal montrant <strong>combien de volume a ete echange a chaque prix</strong>. Le POC (ligne magenta) = prix d'equilibre, la ou les participants sont le plus d'accord. La zone cyan = Value Area (70% du volume). Les barres grises = prix ou le marche a passe peu de temps.",
            action: "Le POC agit comme un aimant — le prix revient souvent le tester. Un breakout au-dessus du VAH = les acheteurs acceptent des prix plus hauts. Le POC de la veille (pPOC, violet) est un des niveaux les plus respectes de la journee.",
        },
        "ib-section": {
            title: "Initial Balance — Premiere heure de session",
            body: "Montre le <strong>range de prix de la premiere heure</strong> (9:30-10:30 ET). Ce range definit les attentes du jour. Une IB etroite (&lt;50% ATR) annonce souvent un breakout. Une IB large (&gt;80% ATR) annonce souvent un range day. Le ratio d'extension montre combien le prix a depasse l'IB.",
            action: "IB cassee a la hausse = les acheteurs ont pris le controle, chercher des achats sur repli. IB cassee a la baisse = l'inverse. Extension &gt;1.5x IB = trend day probable, ne pas fader.",
        },
        // ─── Levels ───
        "vwap-section": {
            title: "VWAP et bandes d'ecart-type",
            body: "Le <strong>VWAP = prix moyen paye par tous les participants</strong> pondere par le volume. C'est LE benchmark institutionnel. Les bandes SD1 (±1 ecart-type) contiennent le prix 68% du temps. SD2 = 95%. SD3 = 99.7%. L'echelle visuelle montre dans quelle bande le prix se situe en ce moment.",
            action: "Au-dessus du VWAP = les acheteurs menent. En-dessous = les vendeurs. Toucher SD2 = zone extreme, un retour vers le VWAP est probable. SD3 = zone tres rare, souvent un point de retournement.",
        },
        "levels-table-section": {
            title: "Carte de tous les niveaux",
            body: "Tableau complet de <strong>tous les niveaux techniques</strong> tries par distance au prix actuel. Chaque niveau a un type (Options, VWAP, Profile, Swing, Session) et une couleur. Les plus proches sont les plus pertinents — ce sont vos prochains obstacles ou supports.",
            action: "Cherchez les zones ou 3+ niveaux de types differents se concentrent dans 10 ticks — ce sont les zones de haute probabilite. Utilisez le niveau le plus proche comme cible de TP et le suivant comme SL.",
        },
        // ─── Signals ───
        "suggestion-section": {
            title: "Pre-trade checklist et suggestion",
            body: "Systeme automatique de <strong>6 verifications</strong> avant tout trade : sommes-nous en session US ? Le VIX est-il acceptable ? La volatilite permet-elle un bon R:R ? Le bias a-t-il une direction ? Y a-t-il une divergence prix/delta ? La confiance est-elle suffisante ? Le grade (A/B/C/D) resume le nombre de checks passes.",
            action: "Grade A (6/6) = toutes les conditions sont reunies, feu vert. Grade B (4-5/6) = acceptable avec vigilance. Grade C ou D = trop de risques, ne pas entrer. Le SL/TP est calcule sur l'ATR avec un ratio risque/recompense de 2:1.",
        },
        // ─── CTA ───
        "cta-section": {
            title: "Positionnement des fonds CTA",
            body: "Les CTA (Commodity Trading Advisors) sont des <strong>fonds systematiques qui gerent des centaines de milliards</strong>. Ils suivent les tendances mecaniquement. Ce tableau montre leur position sur 10 instruments : positive = LONG, negative = SHORT. Le z-score 3 mois mesure a quel point leur position est extreme par rapport a l'historique recent.",
            action: "Quand les CTA sont massivement SHORT et le marche monte, ils doivent racheter = short squeeze violent. Un z-score &gt;1.5 = position crowded, risque de retournement. Un changement rapide (&gt;0.3/jour) = les algos detectent un changement de regime.",
        },
    };

    function initEduMode() {
        var toggle = $("edu-mode-toggle");
        if (!toggle) return;

        // Restore from localStorage
        var saved = localStorage.getItem("mia_edu_mode");
        if (saved === "true") {
            toggle.checked = true;
            document.body.classList.add("edu-active");
        }

        toggle.addEventListener("change", function () {
            document.body.classList.toggle("edu-active", toggle.checked);
            localStorage.setItem("mia_edu_mode", toggle.checked ? "true" : "false");
        });

        // Inject edu icons into cards
        injectEduIcons();
    }

    function injectEduIcons() {
        // Match card-title text content -> tooltip key
        var TITLE_MAP = {
            // Overview
            "Confluence Multi-Timeframe": "mtf-section",
            "Zones de Confluence": "confluence-section",
            "Conseil Global": "global-section",
            "Qui a la main": "hand-section",
            // Options
            "corridor gamma": "corridor-section",
            "GEX Distribution": "gex-section",
            "Murs Options": "corridor-section",
            "VIX Gamma": "gex-section",
            "GEX Levels": "gex-section",
            // Order Flow
            "DOM Pressure": "dom-section",
            "Delta & CVD": "delta-section",
            "RVOL & Volume": "rvol-section",
            "Battle Navale": "bn-section",
            "Big Orders": "bn-section",
            // Profile
            "Volume Profile": "vp-section",
            "Initial Balance": "ib-section",
            "Value Area": "vp-section",
            "HVN / LVN": "vp-section",
            "Range 1D": "vp-section",
            "Profil du Jour": "vp-section",
            // Levels
            "Echelle VWAP": "vwap-section",
            "VWAP SD Bands": "vwap-section",
            "Tous les Niveaux": "levels-table-section",
            "Correlation ES vs NQ": "levels-table-section",
            "Intermarket": "levels-table-section",
            // Signals
            "Suggestion Trade": "suggestion-section",
            "Checklist Pre-Trade": "suggestion-section",
            "Setup Visuel": "suggestion-section",
            // CTA
            "Que font les gros": "cta-section",
            "Positions CTA": "cta-section",
            "Changements cles": "cta-section",
            "Heatmap": "cta-section",
            "Conseils Trading": "cta-section",
        };

        var globalTip = $("edu-tooltip-global");
        var eduHideTimer = null;

        // Fermer le tooltip quand le curseur quitte A LA FOIS l'icone ET le tooltip
        if (globalTip) {
            globalTip.addEventListener("mouseenter", function () {
                clearTimeout(eduHideTimer);
            });
            globalTip.addEventListener("mouseleave", function () {
                eduHideTimer = setTimeout(function () {
                    globalTip.style.display = "none";
                }, 80);
            });
        }

        function attachIcon(targetEl, tipKey) {
            if (!targetEl || targetEl.querySelector(".edu-icon")) return;
            var tip = EDU_TIPS[tipKey];
            if (!tip) return;

            var icon = document.createElement("span");
            icon.className = "edu-icon";
            icon.textContent = "i";
            icon.setAttribute("data-edu-key", tipKey);

            icon.addEventListener("mouseenter", function () {
                if (!globalTip) return;
                clearTimeout(eduHideTimer);
                var rect = icon.getBoundingClientRect();
                globalTip.innerHTML =
                    '<div class="edu-tooltip-title">' + tip.title + '</div>' +
                    '<div class="edu-tooltip-body">' + tip.body + '</div>' +
                    '<div class="edu-tooltip-action">' + tip.action + '</div>' +
                    '<div class="edu-tooltip-link"><a href="/lexique" target="_blank" style="color:var(--cyan);text-decoration:none;font-size:0.625rem;">Voir le lexique complet</a></div>';
                globalTip.style.display = "block";
                // Position : sous l'icone, aligne a gauche
                var top = rect.bottom + 8;
                var left = rect.left;
                // Empecher de sortir a droite
                if (left + 320 > window.innerWidth) left = window.innerWidth - 330;
                // Empecher de sortir en bas
                if (top + 200 > window.innerHeight) top = rect.top - 208;
                globalTip.style.top = top + "px";
                globalTip.style.left = left + "px";
            });

            icon.addEventListener("mouseleave", function () {
                eduHideTimer = setTimeout(function () {
                    if (globalTip) globalTip.style.display = "none";
                }, 120);
            });

            targetEl.style.display = "flex";
            targetEl.style.alignItems = "center";
            targetEl.style.gap = "8px";
            targetEl.appendChild(icon);
        }

        // Scan ALL card-titles
        document.querySelectorAll(".card-title").forEach(function (titleEl) {
            var text = titleEl.textContent || "";
            var tipKey = null;
            for (var pattern in TITLE_MAP) {
                if (text.indexOf(pattern) >= 0) {
                    tipKey = TITLE_MAP[pattern];
                    break;
                }
            }
            if (tipKey) attachIcon(titleEl, tipKey);
        });

        // Big boxes
        [{ id: "box-bias", key: "bias-box" }, { id: "box-mode", key: "mode-box" }].forEach(function (m) {
            var el = $(m.id);
            if (!el) return;
            var label = el.querySelector(".big-box-label");
            if (label) attachIcon(label, m.key);
        });
    }

    function init() {
        // Gate : si pas de token, rediriger vers /welcome (page signup/login)
        // Evite d'afficher le dashboard complet a un user non connecte
        if (!authToken) {
            window.location.href = "/welcome";
            return;
        }

        // Verifier que le token est encore valide (expire = redirect welcome)
        fetch(API_BASE + "/api/auth/me", {
            headers: { "Authorization": "Bearer " + authToken },
        }).then(function (r) {
            if (!r.ok) {
                // Token expire ou invalide — nettoyer et rediriger
                localStorage.removeItem("mia_token");
                localStorage.removeItem("mia_tier");
                localStorage.removeItem("mia_trial_expires");
                window.location.href = "/welcome";
            }
        }).catch(function () {
            // Erreur reseau — on laisse le dashboard charger (mode degrade)
        });

        // ── Onboarding Tour (Driver.js) ──
        function initOnboardingTour(autoStart) {
            if (!window.driver || !window.driver.js) return;

            var SKIP_HTML = '<div style="margin-top:10px;text-align:left;"><a id="mia-skip-tour" style="color:#64748B;font-size:0.6875rem;cursor:pointer;text-decoration:underline;">Passer le tour</a></div>';

            var TOUR_STEPS = [
                {
                    element: "#global-card",
                    popover: {
                        title: "<span style='color:#64748B;font-size:0.6875rem;'>1/7</span> Conseil Global",
                        description: "Lisez ca en premier chaque matin. Ce verdict synthetise TOUS les indicateurs en une recommandation : trader ou attendre." + SKIP_HTML,
                        side: "top",
                        align: "center",
                    }
                },
                {
                    element: "#big-boxes",
                    popover: {
                        title: "<span style='color:#64748B;font-size:0.6875rem;'>2/7</span> Resume instantane",
                        description: "4 cases = 1 seconde pour comprendre le marche. BIAS = direction, MODE = type de journee, FAVORISER = action recommandee, VOLATILITE = intensite." + SKIP_HTML,
                        side: "bottom",
                        align: "center",
                    }
                },
                {
                    element: "#chart-container",
                    popover: {
                        title: "<span style='color:#64748B;font-size:0.6875rem;'>3/7</span> Graphique live",
                        description: "Le graphique temps reel avec les niveaux cles superposes. Changez de timeframe (1m, 5m, 15m, 1h) et d'instrument (ES/NQ)." + SKIP_HTML,
                        side: "bottom",
                        align: "center",
                    }
                },
                {
                    element: "#levels-dropdown",
                    popover: {
                        title: "<span style='color:#64748B;font-size:0.6875rem;'>4/7</span> Selection des niveaux",
                        description: "Filtrez les niveaux sur le chart : Options, VWAP, Profile, Swing, Session, 0DTE... Cochez ceux qui comptent pour votre strategie." + SKIP_HTML,
                        side: "bottom",
                        align: "start",
                    }
                },
                {
                    element: "#gauges-row",
                    popover: {
                        title: "<span style='color:#64748B;font-size:0.6875rem;'>5/7</span> Jauges du marche",
                        description: "La sante du marche en un coup d'oeil. VIX, Confiance, Range Position, Volume Relatif. Lisez-les ensemble, pas separement." + SKIP_HTML,
                        side: "top",
                        align: "center",
                    }
                },
                {
                    element: "#edu-mode-toggle",
                    popover: {
                        title: "<span style='color:#64748B;font-size:0.6875rem;'>6/7</span> Mode Educatif",
                        description: "Activez ce toggle pour afficher des explications detaillees sur chaque section du dashboard. Ideal pour apprendre." + SKIP_HTML,
                        side: "right",
                        align: "center",
                    }
                },
                {
                    element: ".sidebar-nav",
                    popover: {
                        title: "<span style='color:#64748B;font-size:0.6875rem;'>7/7</span> Pages specialisees",
                        description: "10 pages : Options & Gamma, Order Flow, Market Profile, Signaux... Explorez selon votre style. Les pages PRO sont incluses dans votre essai." + SKIP_HTML,
                        side: "right",
                        align: "start",
                    }
                },
            ];

            var driverObj = window.driver.js.driver({
                showProgress: false,
                animate: true,
                smoothScroll: true,
                overlayOpacity: 0.7,
                stagePadding: 8,
                stageRadius: 8,
                popoverClass: "mia-tour-popover",
                nextBtnText: "Suivant →",
                prevBtnText: "",
                doneBtnText: "Terminer ✓",
                showButtons: ["next", "close"],
                steps: TOUR_STEPS,
                onHighlightStarted: function (el, step) {
                    var idx = TOUR_STEPS.indexOf(step) + 1;
                    // Track step viewed
                    fetch(API_BASE + "/api/auth/onboarding-event", {
                        method: "POST",
                        headers: apiHeaders(),
                        credentials: "include",
                        body: JSON.stringify({ event: "step_viewed", step: idx, total_steps: 7 })
                    }).catch(function () {});
                },
                onDestroyStarted: function () {
                    // TOUJOURS sauver que le tour a ete vu (que ce soit complete ou skip)
                    localStorage.setItem("mia_onboarding_done", "true");
                    try {
                        var isLast = driverObj.isLastStep && driverObj.isLastStep();
                        var idx = driverObj.getActiveIndex ? driverObj.getActiveIndex() + 1 : 0;
                        if (isLast) {
                            fetch(API_BASE + "/api/auth/onboarding-event", {
                                method: "POST",
                                headers: apiHeaders(),
                                credentials: "include",
                                body: JSON.stringify({ event: "completed", step: 7, total_steps: 7 })
                            }).catch(function () {});
                        } else {
                            localStorage.setItem("mia_onboarding_skipped", "true");
                            localStorage.setItem("mia_onboarding_step", String(idx));
                            fetch(API_BASE + "/api/auth/onboarding-event", {
                                method: "POST",
                                headers: apiHeaders(),
                                credentials: "include",
                                body: JSON.stringify({ event: "skipped", step: idx, total_steps: 7 })
                            }).catch(function () {});
                        }
                    } catch (e) { /* silencieux */ }
                    driverObj.destroy();
                },
            });

            // Event delegation pour "Passer le tour" (le lien est dans le HTML de la description)
            document.addEventListener("click", function (e) {
                if (e.target && e.target.id === "mia-skip-tour") {
                    e.preventDefault();
                    driverObj.destroy();
                }
            });

            if (autoStart) {
                // Track started
                fetch(API_BASE + "/api/auth/onboarding-event", {
                    method: "POST",
                    headers: apiHeaders(),
                    credentials: "include",
                    body: JSON.stringify({ event: "started", step: 1, total_steps: 7 })
                }).catch(function () {});
                driverObj.drive();
            }

            return driverObj;
        }

        // Bouton sidebar "Guide du dashboard"
        var tourBtn = $("btn-tour-guide");
        if (tourBtn) {
            tourBtn.addEventListener("click", function () {
                var d = initOnboardingTour(false);
                if (d) d.drive();
            });
        }

        // Restore preferences
        var savedPage = localStorage.getItem("mia_page");
        var savedInstr = localStorage.getItem("mia_instrument");
        if (savedPage) currentPage = savedPage;
        if (savedInstr) currentInstrument = savedInstr;

        captureUtmParams();
        initNav();
        initEduMode();
        initPromo();
        initLogin();
        initTrial();
        initGoogleSignIn();
        initTurnstile();
        updateTierIndicator();
        initChart();
        loadChart(currentInstrument);
        fetchDashboard();
        pollTimer = setInterval(fetchDashboard, POLL_INTERVAL);

        // Auto-start onboarding tour au premier login (apres que le dashboard ait charge)
        if (!localStorage.getItem("mia_onboarding_done")) {
            setTimeout(function () {
                // Attendre que le DOM soit peuple par le premier fetchDashboard
                if ($("global-card") || $("big-boxes")) {
                    initOnboardingTour(true);
                }
            }, 3000);
        }
        var chartTimer = setInterval(function () { loadChart(chartSymbol || currentInstrument); }, 10000);

        // Polling adaptatif : 5s session US, 30s hors session, pause si onglet cache
        function getAdaptiveInterval() {
            var now = new Date();
            var utcH = now.getUTCHours();
            // Session US : 13:30-21:00 UTC (09:30-17:00 ET)
            var isUS = utcH >= 13 && utcH < 21;
            return isUS ? POLL_INTERVAL : POLL_INTERVAL_OFF_HOURS;
        }

        document.addEventListener("visibilitychange", function () {
            if (document.hidden) {
                if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
                if (chartTimer) { clearInterval(chartTimer); chartTimer = null; }
            } else {
                var interval = getAdaptiveInterval();
                if (!pollTimer) {
                    fetchDashboard();
                    pollTimer = setInterval(fetchDashboard, interval);
                }
                if (!chartTimer) {
                    chartTimer = setInterval(function () { loadChart(chartSymbol || currentInstrument); }, interval * 2);
                }
            }
        });

        // Re-evaluer l'intervalle toutes les 15 min
        setInterval(function () {
            var interval = getAdaptiveInterval();
            if (pollTimer && currentPollInterval !== interval) {
                clearInterval(pollTimer);
                currentPollInterval = interval;
                pollTimer = setInterval(fetchDashboard, interval);
            }
        }, 900000);

        setInterval(function () {
            var el = $("banner-time");
            if (el) el.textContent = new Date().toLocaleTimeString("fr-FR");
        }, 1000);

        // Keyboard shortcuts
        var pages = ["overview", "options", "orderflow", "profile", "levels", "signals", "cta", "menthorq", "performance", "alerts"];
        document.addEventListener("keydown", function (e) {
            if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
            var num = parseInt(e.key);
            if (num >= 1 && num <= pages.length) {
                switchPage(pages[num - 1]);
            }
        });

        // Hamburger toggle
        var hamburger = $("hamburger-btn");
        var sidebar = $("sidebar");
        var overlay = $("sidebar-overlay");

        function openSidebar() {
            sidebar.classList.add("open");
            if (overlay) overlay.classList.remove("hidden");
        }
        function closeSidebar() {
            sidebar.classList.remove("open");
            if (overlay) overlay.classList.add("hidden");
        }

        if (hamburger && sidebar) {
            hamburger.addEventListener("click", function (e) {
                e.stopPropagation();
                if (sidebar.classList.contains("open")) {
                    closeSidebar();
                } else {
                    openSidebar();
                }
            });
            // Close on link click (mobile)
            sidebar.querySelectorAll("a[data-page]").forEach(function (a) {
                a.addEventListener("click", function () { closeSidebar(); });
            });
            // Close on overlay click
            if (overlay) {
                overlay.addEventListener("click", function () { closeSidebar(); });
            }
        }

        // Restore active states
        if (savedPage) switchPage(savedPage);
        if (savedInstr) {
            document.querySelectorAll(".instrument-btn:not(.tf-btn)").forEach(function (b) {
                b.classList.toggle("active", b.getAttribute("data-instrument") === savedInstr);
            });
        }

        // ════════ KILL SWITCH (Bot Control) ════════
        initKillSwitch();
    }

    // ════════ KILL SWITCH ════════
    var killSwitchTimer = null;

    function initKillSwitch() {
        var section = $("killswitch-section");
        if (!section) return;

        // Affichage reserve OWNER uniquement (pas premium/admin)
        if (!isOwner()) {
            section.style.display = "none";
            return;
        }
        section.style.display = "block";

        // Init du panel admin complet (health, users, trades, discord test)
        initAdminPanel();

        var btnStop = $("btn-bot-stop");
        var btnStart = $("btn-bot-start");

        if (btnStop) {
            btnStop.addEventListener("click", function () {
                var reason = prompt("Raison de l'arret (optionnel) :", "manual");
                if (reason === null) return;  // cancel
                if (!confirm("ARRETER LE BOT ?\n\nToutes les positions ouvertes seront fermees au marche.\n\nConfirmer ?")) {
                    return;
                }
                killSwitchAction("stop", reason || "manual");
            });
        }
        if (btnStart) {
            btnStart.addEventListener("click", function () {
                if (!confirm("REDEMARRER LE BOT ?\n\nLe flag STOP sera supprime. Le bot reprendra au prochain cycle.")) {
                    return;
                }
                killSwitchAction("start", "");
            });
        }

        // Poll status toutes les 5s
        fetchKillSwitchStatus();
        killSwitchTimer = setInterval(fetchKillSwitchStatus, 5000);
    }

    function killSwitchAction(action, reason) {
        var msgEl = $("killswitch-msg");
        if (msgEl) {
            msgEl.style.color = "var(--text-secondary)";
            msgEl.textContent = action === "stop" ? "Arret en cours..." : "Redemarrage...";
        }
        var url = API_BASE + "/api/bot/" + action;
        var body = action === "stop" ? JSON.stringify({ reason: reason }) : "{}";
        fetch(url, {
            method: "POST",
            headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders()),
            body: body
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (msgEl) {
                    if (res.ok) {
                        msgEl.style.color = "var(--green)";
                        msgEl.textContent = action === "stop" ? "STOP envoye" : "Redemarre";
                    } else {
                        msgEl.style.color = "var(--red)";
                        msgEl.textContent = (res.data && res.data.error) || "Erreur";
                    }
                }
                fetchKillSwitchStatus();
            })
            .catch(function (err) {
                if (msgEl) {
                    msgEl.style.color = "var(--red)";
                    msgEl.textContent = "Erreur reseau";
                }
                console.error("[killSwitch]", err);
            });
    }

    function fetchKillSwitchStatus() {
        var stateEl = $("killswitch-state");
        var btnStop = $("btn-bot-stop");
        var btnStart = $("btn-bot-start");
        if (!stateEl) return;

        fetch(API_BASE + "/api/bot/status", { method: "GET", headers: apiHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var stopped = d && d.stop_flag_active === true;
                if (stopped) {
                    stateEl.className = "badge badge-red";
                    stateEl.textContent = "ARRETE";
                    if (btnStop) btnStop.style.display = "none";
                    if (btnStart) btnStart.style.display = "block";
                } else {
                    stateEl.className = "badge badge-green";
                    stateEl.textContent = "ACTIF";
                    if (btnStop) btnStop.style.display = "block";
                    if (btnStart) btnStart.style.display = "none";
                }
            })
            .catch(function () {
                stateEl.className = "badge badge-gray";
                stateEl.textContent = "--";
            });
    }

    // ════════ ADMIN PANEL (owner only) ════════
    var adminPanelTimer = null;

    function initAdminPanel() {
        if (!isOwner()) return;
        var panel = $("admin-panel");
        if (panel) panel.style.display = "block";

        var btnDiscord = $("btn-discord-test");
        if (btnDiscord && !btnDiscord._bound) {
            btnDiscord._bound = true;
            btnDiscord.addEventListener("click", testDiscord);
        }
        var btnRefresh = $("btn-admin-refresh");
        if (btnRefresh && !btnRefresh._bound) {
            btnRefresh._bound = true;
            btnRefresh.addEventListener("click", refreshAdminPanel);
        }

        // Premier chargement + polling 30s
        refreshAdminPanel();
        if (adminPanelTimer) clearInterval(adminPanelTimer);
        adminPanelTimer = setInterval(refreshAdminPanel, 30000);
    }

    function refreshAdminPanel() {
        fetchUsersStats();
        fetchBotHealth();
    }

    function fetchUsersStats() {
        fetch(API_BASE + "/api/admin/users/stats", { headers: apiHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                setText("admin-users-total", d.total);
                setText("admin-users-free", (d.tiers && d.tiers.free) || 0);
                setText("admin-users-premium", (d.tiers && d.tiers.premium) || 0);
                setText("admin-users-owner", (d.tiers && d.tiers.owner) || 0);
                setText("admin-users-7d", d.last_7d);
                setText("admin-users-30d", d.last_30d);
            })
            .catch(function () {});
    }

    function fetchBotHealth() {
        fetch(API_BASE + "/api/admin/bot/health", { headers: apiHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                var stateEl = $("admin-bot-state");
                if (stateEl) {
                    if (d.status === "healthy") {
                        stateEl.className = "badge badge-green";
                        stateEl.textContent = "HEALTHY";
                    } else if (d.status === "stale") {
                        stateEl.className = "badge badge-red";
                        stateEl.textContent = "STALE";
                    } else {
                        stateEl.className = "badge badge-gray";
                        stateEl.textContent = "NO_HB";
                    }
                }
                if (d.data) {
                    setText("admin-bot-pid", d.data.pid || "--");
                    var uptime = d.data.uptime_seconds || 0;
                    setText("admin-bot-uptime", formatUptime(uptime));
                    setText("admin-bot-cycles", d.data.cycles || 0);
                    setText("admin-bot-trades", d.data.trades_today || 0);
                    setText("admin-bot-pnl", (d.data.pnl_today || 0).toFixed(2) + "$");
                    setText("admin-bot-positions", d.data.positions_open || 0);
                    var dtc = d.data.dtc_connected;
                    var dtcEl = $("admin-bot-dtc");
                    if (dtcEl) {
                        if (dtc === true) { dtcEl.className = "badge badge-green"; dtcEl.textContent = "UP"; }
                        else if (dtc === false) { dtcEl.className = "badge badge-red"; dtcEl.textContent = "DOWN"; }
                        else { dtcEl.className = "badge badge-gray"; dtcEl.textContent = "--"; }
                    }
                }
                setText("admin-bot-age", d.age_seconds != null ? d.age_seconds.toFixed(0) + "s" : "--");
            })
            .catch(function () {});
    }

    function testDiscord() {
        var msgEl = $("admin-discord-msg");
        if (msgEl) { msgEl.style.color = "var(--text-secondary)"; msgEl.textContent = "Envoi..."; }
        fetch(API_BASE + "/api/admin/discord/test", {
            method: "POST",
            headers: apiHeaders(),
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (msgEl) {
                    if (d.sent) {
                        msgEl.style.color = "var(--green)";
                        msgEl.textContent = "Envoye sur #admin";
                    } else {
                        msgEl.style.color = "var(--red)";
                        msgEl.textContent = d.message || "Echec";
                    }
                }
            })
            .catch(function () {
                if (msgEl) { msgEl.style.color = "var(--red)"; msgEl.textContent = "Erreur reseau"; }
            });
    }

    function formatUptime(seconds) {
        if (!seconds || seconds < 0) return "--";
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        var s = Math.floor(seconds % 60);
        if (h > 0) return h + "h" + (m < 10 ? "0" : "") + m + "m";
        if (m > 0) return m + "m" + (s < 10 ? "0" : "") + s + "s";
        return s + "s";
    }

    function setText(id, value) {
        var el = $(id);
        if (el) el.textContent = value;
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
