# 📱 INTÉGRATION DISCORD - BOT C++

## 🎯 OBJECTIF

Envoyer des notifications Discord similaires au bot Python pour suivre le P&L et les trades en temps réel depuis Discord.

---

## 🔧 SOLUTION PROPOSÉE

### Option 1: Script Python externe (RECOMMANDÉ - Plus simple)

Le bot C++ écrit les événements dans un fichier JSON, un script Python surveille et envoie vers Discord.

**Avantages:**
- ✅ Pas besoin de WinHTTP dans C++
- ✅ Réutilise le code Discord existant
- ✅ Plus facile à maintenir
- ✅ Gestion d'erreurs robuste

**Fichiers à créer:**
1. `discord_cpp_bridge.py` - Script qui surveille les logs C++ et envoie Discord
2. Modification du bot C++ pour écrire des événements JSON

---

### Option 2: WinHTTP direct dans C++

Implémenter l'envoi Discord directement dans le C++ avec WinHTTP.

**Avantages:**
- ✅ Tout intégré dans le bot
- ✅ Pas de dépendance externe

**Inconvénients:**
- ⚠️ Plus complexe à implémenter
- ⚠️ Gestion d'erreurs réseau plus difficile

---

## 📋 IMPLÉMENTATION RECOMMANDÉE (Option 1)

### 1. Structure des événements JSON

Le bot C++ écrit dans: `TRADING_SIERRA_CHART_AUTO/LOGS/DISCORD_EVENTS/events_YYYYMMDD.jsonl`

Format (1 ligne = 1 événement):
```json
{"type":"TRADE_OPENED","time":"15:30:45","symbol":"ES","direction":"LONG","entry":6900.25,"sl":6895.50,"tp":6907.00,"pnl":0,"l1_conf":0.85,"l2_conf":0.12,"l3_conf":0.08,"l4_combo":3,"bn_score":0.189,"vwap_slope":-0.0004,"is_rectangle":false}
{"type":"TRADE_CLOSED","time":"15:32:10","symbol":"ES","direction":"LONG","entry":6900.25,"exit":6907.00,"pnl":+150.00,"exit_reason":"TP","duration_sec":85}
{"type":"DAILY_SUMMARY","time":"23:00:00","date":"20260120","total_trades":4,"total_pnl":+109.10,"win_rate":0.50,"trades_es":2,"pnl_es":+306.50,"trades_nq":2,"pnl_nq":-197.40}
```

### 2. Script Python `discord_cpp_bridge.py`

```python
"""
Bridge entre bot C++ et Discord
Surveille les logs C++ et envoie les notifications Discord
"""
import json
import time
from pathlib import Path
from datetime import datetime
from monitoring.discord_notifier import MultiWebhookDiscordNotifier
from monitoring.discord_styles import build_trade_opened_embed, build_trade_closed_embed, build_daily_summary_embed

# Webhook C++ dédié
CPP_WEBHOOK = "https://discord.com/api/webhooks/1463310218493432024/VlsnkSMAzl_xz3l2wZms--w3yfUdYWn7nCaapL35hm6-Cdwc55PTHHxvgH-fd0enXQvz"

def process_cpp_event(event_data: dict, notifier: MultiWebhookDiscordNotifier):
    """Traite un événement C++ et envoie Discord"""
    event_type = event_data.get("type")

    if event_type == "TRADE_OPENED":
        # Convertir format C++ → format Python
        trade_data = {
            "symbol": event_data["symbol"],
            "side": "BUY" if event_data["direction"] == "LONG" else "SELL",
            "fill_price": event_data["entry"],
            "tp_price": event_data.get("tp", 0),
            "sl_price": event_data.get("sl", 0),
            "strategy": "RECT" if event_data.get("is_rectangle") else "MQ",
            "confluence": event_data.get("l1_conf", 0),
            "ml_confidence": event_data.get("l2_conf", 0),
            "trade_id": f"CPP_{event_data.get('time', '')}"
        }

        embed = build_trade_opened_embed(trade_data)
        # Envoyer vers webhook C++
        send_discord_webhook(CPP_WEBHOOK, embed)

    elif event_type == "TRADE_CLOSED":
        trade_data = {
            "symbol": event_data["symbol"],
            "side": "BUY" if event_data["direction"] == "LONG" else "SELL",
            "entry_price": event_data["entry"],
            "exit_price": event_data["exit"],
            "pnl": event_data["pnl"],
            "exit_reason": event_data.get("exit_reason", "?"),
            "duration_seconds": event_data.get("duration_sec", 0),
            "trade_id": f"CPP_{event_data.get('time', '')}"
        }

        embed = build_trade_closed_embed(trade_data)
        send_discord_webhook(CPP_WEBHOOK, embed)

    elif event_type == "DAILY_SUMMARY":
        summary_data = {
            "date": event_data["date"],
            "total_trades": event_data["total_trades"],
            "total_pnl": event_data["total_pnl"],
            "win_rate": event_data["win_rate"],
            "trades_es": event_data.get("trades_es", 0),
            "pnl_es": event_data.get("pnl_es", 0),
            "trades_nq": event_data.get("trades_nq", 0),
            "pnl_nq": event_data.get("pnl_nq", 0)
        }

        embed = build_daily_summary_embed(summary_data)
        send_discord_webhook(CPP_WEBHOOK, embed)

def send_discord_webhook(webhook_url: str, payload: dict):
    """Envoie un webhook Discord"""
    import requests
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Erreur Discord: {e}")
        return False

def main():
    """Boucle principale - surveille les logs C++"""
    events_dir = Path("D:/MIA_IA_system/TRADING_SIERRA_CHART_AUTO/LOGS/DISCORD_EVENTS")
    events_dir.mkdir(parents=True, exist_ok=True)

    notifier = MultiWebhookDiscordNotifier()
    processed_lines = set()

    while True:
        # Lire le fichier du jour
        today = datetime.now().strftime("%Y%m%d")
        events_file = events_dir / f"events_{today}.jsonl"

        if events_file.exists():
            with open(events_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line_key = f"{today}_{line_num}"
                    if line_key in processed_lines:
                        continue

                    try:
                        event = json.loads(line.strip())
                        process_cpp_event(event, notifier)
                        processed_lines.add(line_key)
                    except Exception as e:
                        print(f"Erreur traitement ligne {line_num}: {e}")

        time.sleep(2)  # Vérifier toutes les 2 secondes

if __name__ == "__main__":
    main()
```

### 3. Modifications dans le bot C++

Ajouter une fonction pour écrire les événements:

```cpp
// ═══════════════════════════════════════════════════════════════════════════════
// SECTION: DISCORD INTEGRATION
// ═══════════════════════════════════════════════════════════════════════════════

void WriteDiscordEvent(SCStudyInterfaceRef sc, const char* event_type, const char* json_data) {
    int year, month, day;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, 0, 0, 0);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\MIA_IA_system\\TRADING_SIERRA_CHART_AUTO\\LOGS\\DISCORD_EVENTS\\events_%04d%02d%02d.jsonl",
             year, month, day);

    std::ofstream file(filename, std::ios::app);
    if (!file.is_open()) return;

    file << json_data << "\n";
    file.close();
}

// Appeler après chaque trade ouvert
void NotifyDiscordTradeOpened(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config) {
    char json[1024];
    snprintf(json, sizeof(json),
             "{\"type\":\"TRADE_OPENED\",\"time\":\"%s\",\"symbol\":\"%s\",\"direction\":\"%s\","
             "\"entry\":%.2f,\"sl\":%.2f,\"tp\":%.2f,\"pnl\":0,\"l1_conf\":%.2f,\"l2_conf\":%.2f,"
             "\"l3_conf\":%.2f,\"l4_combo\":%d,\"bn_score\":%.3f,\"vwap_slope\":%.4f,\"is_rectangle\":%s}",
             FormatTime(snap.entry_time), snap.symbol,
             snap.direction == 1 ? "LONG" : "SHORT",
             snap.entry_price, snap.sl_price, snap.tp_price,
             snap.l1_confidence, snap.l2_confidence, snap.l3_confidence,
             snap.l4_combo_aligned, snap.bn_score, snap.vwap_slope,
             snap.is_rectangle_trade ? "true" : "false");

    WriteDiscordEvent(sc, "TRADE_OPENED", json);
}

// Appeler après chaque trade fermé
void NotifyDiscordTradeClosed(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config) {
    char json[1024];
    int duration = (snap.exit_time - snap.entry_time).GetTotalSeconds();

    snprintf(json, sizeof(json),
             "{\"type\":\"TRADE_CLOSED\",\"time\":\"%s\",\"symbol\":\"%s\",\"direction\":\"%s\","
             "\"entry\":%.2f,\"exit\":%.2f,\"pnl\":%.2f,\"exit_reason\":\"%s\",\"duration_sec\":%d}",
             FormatTime(snap.exit_time), snap.symbol,
             snap.direction == 1 ? "LONG" : "SHORT",
             snap.entry_price, snap.exit_price, snap.pnl,
             snap.exit_reason, duration);

    WriteDiscordEvent(sc, "TRADE_CLOSED", json);
}
```

---

## 🚀 UTILISATION

1. **Lancer le script Python en arrière-plan:**
   ```bash
   python discord_cpp_bridge.py
   ```

2. **Le bot C++ écrit automatiquement** les événements dans le fichier JSONL

3. **Le script Python surveille** et envoie vers Discord

---

## 📊 MESSAGES DISCORD ENVOYÉS

1. **Trade Ouvert** - Embed avec entry, SL, TP, contexte
2. **Trade Fermé** - Embed avec P&L, raison, durée
3. **Résumé Quotidien** - Stats du jour (P&L, Win Rate, etc.)

---

## ✅ AVANTAGES

- ✅ Réutilise le code Discord existant (embeds professionnels)
- ✅ Pas de modification complexe du C++
- ✅ Gestion d'erreurs robuste (Python)
- ✅ Facile à maintenir et étendre
