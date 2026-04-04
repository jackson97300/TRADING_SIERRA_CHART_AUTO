/**
 * ticker-widget.js — Widget TradingView ticker tape
 * Injecte le widget embed dans #tv-ticker
 */
(function () {
    var container = document.getElementById("tv-ticker");
    if (!container) return;

    var widget = document.createElement("div");
    widget.className = "tradingview-widget-container";
    widget.innerHTML = '<div class="tradingview-widget-container__widget"></div>';
    container.appendChild(widget);

    var script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js";
    script.async = true;
    script.textContent = JSON.stringify({
        symbols: [
            { proName: "CME_MINI:ES1!", title: "ES" },
            { proName: "CME_MINI:NQ1!", title: "NQ" },
            { proName: "CME_MINI:RTY1!", title: "RTY" },
            { proName: "SP:SPX", title: "SPX" },
            { proName: "CBOE:VIX", title: "VIX" },
            { proName: "NYMEX:CL1!", title: "Petrole" },
            { proName: "COMEX:GC1!", title: "Or" },
            { proName: "BITSTAMP:BTCUSD", title: "BTC" }
        ],
        showSymbolLogo: false,
        isTransparent: true,
        displayMode: "compact",
        colorTheme: "dark",
        locale: "fr"
    });
    widget.appendChild(script);
})();
