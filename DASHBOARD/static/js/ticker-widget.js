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
            { proName: "AMEX:SPY", title: "SPY (ES)" },
            { proName: "NASDAQ:QQQ", title: "QQQ (NQ)" },
            { proName: "AMEX:IWM", title: "IWM (RTY)" },
            { proName: "AMEX:USO", title: "Petrole" },
            { proName: "AMEX:GLD", title: "Or" },
            { proName: "BITSTAMP:BTCUSD", title: "BTC" },
            { proName: "FX_IDC:EURUSD", title: "EUR/USD" },
            { proName: "NASDAQ:AAPL", title: "AAPL" },
            { proName: "NASDAQ:MSFT", title: "MSFT" },
            { proName: "NASDAQ:NVDA", title: "NVDA" },
            { proName: "NASDAQ:AMZN", title: "AMZN" },
            { proName: "NASDAQ:GOOGL", title: "GOOGL" },
            { proName: "NASDAQ:META", title: "META" },
            { proName: "NASDAQ:TSLA", title: "TSLA" }
        ],
        showSymbolLogo: false,
        isTransparent: true,
        displayMode: "compact",
        colorTheme: "dark",
        locale: "fr"
    });
    widget.appendChild(script);
})();
