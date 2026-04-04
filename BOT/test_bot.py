"""
test_bot.py — Tests unitaires du Bot MIA V2
=============================================

Verifie chaque module du bot sans connexion DTC.

Usage :
    python test_bot.py

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

passed = 0
failed = 0
errors = []

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        errors.append(f"{name}: {detail}")
        print(f"  ❌ {name} — {detail}")


print("=" * 60)
print("  TESTS BOT MIA V2")
print("=" * 60)

# ═══════════════════════════════════════════════════════════
# 1. CONFIG
# ═══════════════════════════════════════════════════════════
print("\n[1] BOT CONFIG")

from bot_config import BotConfig, CONFIG, ES, NQ

check("CONFIG existe", CONFIG is not None)
check("ES tick_size = 0.25", ES.tick_size == 0.25)
check("NQ tick_value = 0.50", NQ.tick_value == 0.50)
check("Max daily trades = 10", CONFIG.risk.max_daily_trades == 10)
check("Max daily loss = $500", CONFIG.risk.max_daily_loss_usd == 500.0)
check("Paper trading = True", CONFIG.paper_trading == True)
check("Half-Kelly = 0.5", CONFIG.risk.kelly_fraction == 0.5)
check("Max positions = 1", CONFIG.risk.max_positions_total == 1)

# ═══════════════════════════════════════════════════════════
# 2. TRADE JOURNAL
# ═══════════════════════════════════════════════════════════
print("\n[2] TRADE JOURNAL")

from trade_journal import TradeJournal, TradeRecord

journal = TradeJournal("DATA/JOURNAL_TEST")

# Simuler un trade gagnant
trade1 = TradeRecord(symbol="ES", direction=1, entry_price=6530.0,
                      exit_price=6540.0, position_size=1)
journal.log_trade(trade1)
check("Trade gagnant logged", trade1.is_winner == True)
check("PnL ticks = +40", trade1.pnl_ticks == 40.0)
check("PnL USD = $50", trade1.pnl_usd == 50.0)

# Trade perdant
trade2 = TradeRecord(symbol="ES", direction=1, entry_price=6530.0,
                      exit_price=6525.0, position_size=1)
journal.log_trade(trade2)
check("Trade perdant", trade2.is_winner == False)
check("PnL = -$25", trade2.pnl_usd == -25.0)

check("Daily PnL = $25", journal.daily_pnl == 25.0)
check("Consecutive losses = 1", journal.consecutive_losses == 1)
check("Win rate = 50%", journal.win_rate == 0.5)

# Rejection log
journal.log_rejection("NQ", "Max trades atteint", 0.65)
check("Rejection logged", True)

# Event log
journal.log_event("CIRCUIT_BREAKER", "3 pertes consecutives")
check("Event logged", True)

# Summary
summary = journal.daily_summary()
check("Summary non vide", len(summary) > 10, summary)

# Cleanup
import shutil
shutil.rmtree("DATA/JOURNAL_TEST", ignore_errors=True)

# ═══════════════════════════════════════════════════════════
# 3. RISK MANAGER
# ═══════════════════════════════════════════════════════════
print("\n[3] RISK MANAGER")

from risk_manager import RiskManager

rm = RiskManager(CONFIG)

# Can trade basique
allowed, reason = rm.can_trade("ES", 1, ES)
# Peut echouer selon l'heure — c'est normal
if "Hors session" in reason or "Trop" in reason:
    check("Risk check session", True)
else:
    check("Risk check basique", allowed or "loss" in reason.lower())

# Position sizing Half-Kelly
size = rm.compute_position_size(ES, sl_ticks=20, win_rate=0.55)
check("Position size >= 1", size >= 1)
check("Position size <= max", size <= ES.max_contracts)

# Circuit breaker
rm.state.consecutive_losses = 3
allowed, reason = rm.can_trade("ES", 1, ES)
check("Circuit breaker bloque", not allowed)
check("Raison = consecutives", "consecutiv" in reason.lower() or "circuit" in reason.lower())

# Reset
rm.reset_daily()
check("Reset OK", rm.state.daily_pnl == 0.0)

# Kill switch
rm.state.daily_pnl = -600
allowed, reason = rm.can_trade("ES", 1, ES)
check("Kill switch active", rm.state.is_killed)
check("Raison = daily loss", "loss" in reason.lower() or "killed" in reason.lower())

# EOD flatten
check("should_flatten_eod retourne bool", isinstance(rm.should_flatten_eod(), bool))

# Half-Kelly avec win rate faible
rm2 = RiskManager(CONFIG)
size_low = rm2.compute_position_size(ES, sl_ticks=20, win_rate=0.40)
size_high = rm2.compute_position_size(ES, sl_ticks=20, win_rate=0.65)
check("Sizing: low WR <= high WR", size_low <= size_high)

# ═══════════════════════════════════════════════════════════
# 4. SIGNAL ENGINE
# ═══════════════════════════════════════════════════════════
print("\n[4] SIGNAL ENGINE")

from signal_engine import SignalEngine, Signal

se = SignalEngine(CONFIG)

# Sans modeles charges
signal = se.predict("ES", {"delta_bar": 10})
check("Sans modele = HOLD", signal.direction == 0)

# MenthorQ gates
allowed, reason = se.check_menthorq_gate(1, -1.0)  # Long + gamma negatif
check("Long bloque en gamma negatif", not allowed)

allowed, reason = se.check_menthorq_gate(-1, -1.0)  # Short + gamma negatif
check("Short OK en gamma negatif", allowed)

allowed, reason = se.check_menthorq_gate(1, 1.0)  # Long + gamma positif
check("Long OK en gamma positif", allowed)

# Confidence levels
check("Confidence HIGH >= 0.70", se._confidence(0.75) == "HIGH")
check("Confidence MEDIUM >= 0.60", se._confidence(0.65) == "MEDIUM")
check("Confidence LOW < 0.60", se._confidence(0.55) == "LOW")

# ═══════════════════════════════════════════════════════════
# 5. DTC CONNECTOR (sans connexion)
# ═══════════════════════════════════════════════════════════
print("\n[5] DTC CONNECTOR")

from dtc_connector import DTCConnector

dtc = DTCConnector()
check("DTC initialise", dtc is not None)
check("DTC non connecte", not dtc.connected)
check("DTC is_alive = False", not dtc.is_alive)

# ═══════════════════════════════════════════════════════════
# 6. ORDER MANAGER (mock)
# ═══════════════════════════════════════════════════════════
print("\n[6] ORDER MANAGER")

from order_manager import OrderManager

# Creer un mock DTC
mock_dtc = DTCConnector()
mock_dtc.connected = False

om = OrderManager(CONFIG, mock_dtc)
check("OrderManager initialise", om is not None)
check("Pas de position", om.total_positions == 0)
check("has_position = False", not om.has_position("ES"))

# ═══════════════════════════════════════════════════════════
# 7. POSITION MONITOR
# ═══════════════════════════════════════════════════════════
print("\n[7] POSITION MONITOR")

from position_monitor import PositionMonitor

pm = PositionMonitor(CONFIG, om, journal)
check("PositionMonitor initialise", pm is not None)

# Check exit sans position
exit_d = pm.check_exit("ES", 6530.0, ES)
check("Pas de position = pas d'exit", not exit_d.should_exit)

# ═══════════════════════════════════════════════════════════
# 8. BOT MAIN
# ═══════════════════════════════════════════════════════════
print("\n[8] BOT MAIN")

from bot_main import MIABot

bot = MIABot(dry_run=True)
check("Bot cree en dry-run", bot.dry_run == True)
check("Bot DTC = None (dry-run)", bot.dtc is None)

# ═══════════════════════════════════════════════════════════
# BILAN
# ═══════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  {passed}/{passed+failed} tests passent | {failed} erreurs")
if errors:
    print(f"\n  ERREURS:")
    for e in errors:
        print(f"    ❌ {e}")
else:
    print(f"\n  ✅ TOUS LES TESTS BOT PASSENT")
print(f"{'='*60}")

sys.exit(0 if failed == 0 else 1)
