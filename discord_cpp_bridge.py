#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📱 DISCORD BRIDGE - BOT C++ → DISCORD
Surveille les logs du bot C++ et envoie les notifications Discord
"""

import json
import time
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Webhook Discord C++ dédié - Salon "TRADE BOT CPP"
CPP_WEBHOOK_URL = "https://discord.com/api/webhooks/1463720727801893005/INC6erH93Bcdg-Wa10dfYtwTmR-XG5cQbhAZQcL_f_7hpbfqJOVgwit_jp13CZRSqmAT"

# Chemins
PROJECT_ROOT = Path(__file__).parent.parent
EVENTS_DIR = PROJECT_ROOT / "TRADING_SIERRA_CHART_AUTO" / "LOGS" / "DISCORD_EVENTS"
EVENTS_DIR.mkdir(parents=True, exist_ok=True)


def send_discord_webhook(webhook_url: str, payload: dict) -> bool:
    """Envoie un webhook Discord"""
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Erreur Discord: {e}")
        return False


def build_trade_opened_embed_cpp(event: dict) -> dict:
    """Construit un embed Discord pour trade ouvert (format C++)"""
    symbol = event.get("symbol", "?")
    direction = event.get("direction", "?")
    entry = event.get("entry", 0)
    sl = event.get("sl", 0)
    tp = event.get("tp", 0)
    bn_score = event.get("bn_score", 0)
    l4_combo = event.get("l4_combo", 0)
    is_rect = event.get("is_rectangle", False)

    # Couleur selon direction
    color = 0x00B4DC if direction == "LONG" else 0xD4AF37

    # Calculer distances
    tick_size = 0.25 if symbol in ["ES", "NQ"] else 0.25
    if direction == "LONG":
        tp_ticks = int((tp - entry) / tick_size) if tp > entry else 0
        sl_ticks = int((entry - sl) / tick_size) if sl < entry else 0
    else:
        tp_ticks = int((entry - tp) / tick_size) if tp < entry else 0
        sl_ticks = int((sl - entry) / tick_size) if sl > entry else 0

    embed = {
        "title": f"🟢 TRADE OUVERT - {symbol} {direction}",
        "description": f"**Entry:** {entry:.2f} | **SL:** {sl:.2f} | **TP:** {tp:.2f}",
        "color": color,
        "fields": [
            {"name": "📊 Contexte", "value": f"BN Score: {bn_score:+.3f}\nL4 Combo: {l4_combo}/4\nType: {'RECT' if is_rect else 'MQ'}", "inline": True},
            {"name": "📏 Distances", "value": f"TP: {tp_ticks}t\nSL: {sl_ticks}t\nR:R: {tp_ticks/sl_ticks:.2f}" if sl_ticks > 0 else "TP: {tp_ticks}t", "inline": True},
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "MIA Bot C++ - Sierra Chart"}
    }

    return {"embeds": [embed]}


def build_trade_closed_embed_cpp(event: dict) -> dict:
    """Construit un embed Discord pour trade fermé (format C++)"""
    symbol = event.get("symbol", "?")
    direction = event.get("direction", "?")
    entry = event.get("entry", 0)
    exit_price = event.get("exit", 0)
    pnl = event.get("pnl", 0)
    exit_reason = event.get("exit_reason", "?")
    duration = event.get("duration_sec", 0)

    # Couleur selon P&L
    if pnl > 0:
        color = 0x00FF00  # Vert
        emoji = "✅"
    elif pnl < 0:
        color = 0xFF0000  # Rouge
        emoji = "❌"
    else:
        color = 0xFFFF00  # Jaune
        emoji = "⚪"

    # Calculer points/ticks
    tick_size = 0.25 if symbol in ["ES", "NQ"] else 0.25
    points = abs(exit_price - entry)
    ticks = int(points / tick_size)

    embed = {
        "title": f"{emoji} TRADE FERMÉ - {symbol} {direction}",
        "description": f"**Entry:** {entry:.2f} → **Exit:** {exit_price:.2f}",
        "color": color,
        "fields": [
            {"name": "💰 P&L", "value": f"${pnl:+,.2f}", "inline": True},
            {"name": "📏 Points", "value": f"{points:+.2f} ({ticks:+}t)", "inline": True},
            {"name": "⏱️ Durée", "value": f"{duration}s", "inline": True},
            {"name": "🚪 Raison", "value": exit_reason, "inline": False},
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "MIA Bot C++ - Sierra Chart"}
    }

    return {"embeds": [embed]}


def build_daily_summary_embed_cpp(event: dict) -> dict:
    """Construit un embed Discord pour résumé quotidien"""
    date = event.get("date", "?")
    total_trades = event.get("total_trades", 0)
    total_pnl = event.get("total_pnl", 0)
    win_rate = event.get("win_rate", 0) * 100
    trades_es = event.get("trades_es", 0)
    pnl_es = event.get("pnl_es", 0)
    trades_nq = event.get("trades_nq", 0)
    pnl_nq = event.get("pnl_nq", 0)

    # Couleur selon P&L
    color = 0x00FF00 if total_pnl > 0 else 0xFF0000 if total_pnl < 0 else 0x808080

    embed = {
        "title": f"📊 RÉSUMÉ QUOTIDIEN - {date}",
        "color": color,
        "fields": [
            {"name": "📈 Global", "value": f"Trades: {total_trades}\nP&L: ${total_pnl:+,.2f}\nWin Rate: {win_rate:.1f}%", "inline": True},
            {"name": "📊 ES", "value": f"Trades: {trades_es}\nP&L: ${pnl_es:+,.2f}", "inline": True},
            {"name": "📊 NQ", "value": f"Trades: {trades_nq}\nP&L: ${pnl_nq:+,.2f}", "inline": True},
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "MIA Bot C++ - Sierra Chart"}
    }

    return {"embeds": [embed]}


def process_cpp_event(event_data: dict):
    """Traite un événement C++ et envoie Discord"""
    event_type = event_data.get("type")

    try:
        if event_type == "TRADE_OPENED":
            embed = build_trade_opened_embed_cpp(event_data)
            send_discord_webhook(CPP_WEBHOOK_URL, embed)
            print(f"✅ Discord: Trade ouvert {event_data.get('symbol')} {event_data.get('direction')}")

        elif event_type == "TRADE_CLOSED":
            embed = build_trade_closed_embed_cpp(event_data)
            send_discord_webhook(CPP_WEBHOOK_URL, embed)
            print(f"✅ Discord: Trade fermé {event_data.get('symbol')} P&L=${event_data.get('pnl', 0):.2f}")

        elif event_type == "DAILY_SUMMARY":
            embed = build_daily_summary_embed_cpp(event_data)
            send_discord_webhook(CPP_WEBHOOK_URL, embed)
            print(f"✅ Discord: Résumé quotidien {event_data.get('date')}")

        else:
            print(f"⚠️ Type d'événement inconnu: {event_type}")

    except Exception as e:
        print(f"❌ Erreur traitement événement: {e}")


def main():
    """Boucle principale - surveille les logs C++"""
    print("🚀 Discord Bridge C++ démarré")
    print(f"📁 Surveille: {EVENTS_DIR}")
    print(f"🔗 Webhook: {CPP_WEBHOOK_URL[:50]}...")

    processed_lines = set()

    while True:
        try:
            # Lire le fichier du jour
            today = datetime.now().strftime("%Y%m%d")
            events_file = EVENTS_DIR / f"events_{today}.jsonl"

            if events_file.exists():
                with open(events_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                    for line_num, line in enumerate(lines, 1):
                        line_key = f"{today}_{line_num}"
                        if line_key in processed_lines:
                            continue

                        line = line.strip()
                        if not line:
                            continue

                        try:
                            event = json.loads(line)
                            process_cpp_event(event)
                            processed_lines.add(line_key)
                        except json.JSONDecodeError as e:
                            print(f"⚠️ JSON invalide ligne {line_num}: {e}")
                        except Exception as e:
                            print(f"❌ Erreur ligne {line_num}: {e}")

            time.sleep(2)  # Vérifier toutes les 2 secondes

        except KeyboardInterrupt:
            print("\n🛑 Arrêt du bridge Discord")
            break
        except Exception as e:
            print(f"❌ Erreur boucle principale: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
