"""Replay Solution D2 Ladder sur trades historiques Bot 3.

Pour chaque trade historique :
  - Lire entry_price, mfe_ticks, side, pnl_usd, exit_reason
  - Simuler les paliers : si mfe_ticks atteint palier_N seuil, palier_N est "armed"
  - Calculer impact $$ : si pnl_actuel < lock_usd_du_dernier_palier_armed,
    alors gain Solution D = lock_usd au lieu de pnl_actuel
    Sinon : Solution D = pnl_actuel (TP normal touche)

Cible : prouver empiriquement combien $$ aurait ete sauve si Solution D2 active.

Date : 2026-05-11
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from glob import glob

_ROOT = Path(__file__).parent.parent.parent
_CORE = _ROOT / "CORE"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from bot3_config import GUARD_RAILS_BOT3  # noqa


def replay_ladder(trade: dict, paliers: list, tick_value: float, n_contracts: int) -> dict:
    """Replay la logique D2 sur 1 trade et retourne le PnL Solution D vs reel."""
    mfe_ticks = trade.get("mfe_ticks") or 0.0
    pnl_ticks_actual = trade.get("pnl_ticks") or 0.0
    pnl_usd_actual = trade.get("pnl_usd") or 0.0
    exit_reason = trade.get("exit_reason", "?")

    # Quel palier le plus eleve a ete arme ?
    last_palier_armed = None
    for palier_idx, (mfe_seuil, sl_lock_ticks) in enumerate(paliers):
        if mfe_ticks >= mfe_seuil:
            last_palier_armed = (palier_idx + 1, mfe_seuil, sl_lock_ticks)
        else:
            break

    if last_palier_armed is None:
        # Aucun palier atteint -> SL initial reste -> PnL inchange
        return {
            "pnl_d2_usd": pnl_usd_actual,
            "delta_usd": 0.0,
            "palier_armed": 0,
            "scenario": "NO_PALIER_ARMED",
        }

    palier_n, mfe_seuil, sl_lock_ticks = last_palier_armed
    lock_usd = sl_lock_ticks * tick_value * n_contracts

    # Cas 1 : exit TP (pnl_ticks > 0 et > lock) -> TP touche avant retour vers SL ladder
    if exit_reason == "TP" and pnl_ticks_actual > sl_lock_ticks:
        return {
            "pnl_d2_usd": pnl_usd_actual,
            "delta_usd": 0.0,
            "palier_armed": palier_n,
            "scenario": "TP_BEFORE_RETURN",
            "lock_usd": lock_usd,
        }

    # Cas 2 : exit SL ou TIMEOUT avec pnl_actuel < lock_usd
    # -> Solution D aurait fait toucher le SL ladder = lock_usd
    if pnl_usd_actual < lock_usd:
        delta = lock_usd - pnl_usd_actual
        return {
            "pnl_d2_usd": lock_usd,
            "delta_usd": delta,
            "palier_armed": palier_n,
            "scenario": "LADDER_SL_SAVE",
            "lock_usd": lock_usd,
        }

    # Cas 3 : pnl_actuel >= lock_usd (TP partiel ou TIMEOUT favorable)
    # -> Solution D PRESERVE pnl_actuel
    return {
        "pnl_d2_usd": pnl_usd_actual,
        "delta_usd": 0.0,
        "palier_armed": palier_n,
        "scenario": "ABOVE_LOCK",
        "lock_usd": lock_usd,
    }


def main():
    # Lire tous les trades Bot 3 historiques
    audit_dir = _ROOT / "DATA" / "PAPER_TRADES_V6_AUDIT"
    if not audit_dir.exists():
        # fallback : utiliser DATA/PAPER_TRADES live (si en local)
        audit_dir = _ROOT / "DATA" / "PAPER_TRADES"

    files = sorted(audit_dir.glob("*_databento_v3_trades.jsonl"))
    if not files:
        print(f"Aucun fichier *_databento_v3_trades.jsonl trouve dans {audit_dir}")
        return

    print(f"Lecture {len(files)} fichiers Bot 3 historique :")
    for f in files:
        print(f"  - {f.name}")
    print()

    all_trades = []
    for f in files:
        for line in open(f, encoding="utf-8"):
            if line.strip():
                t = json.loads(line)
                if t.get("invalidated"):
                    continue
                all_trades.append(t)

    print(f"Total trades non-invalides : {len(all_trades)}")
    print()

    # Replay par symbol
    print(f"{'Date':12s} {'Sym':4s} {'Side':6s} {'MFE_t':7s} {'PnL_actuel':12s} "
          f"{'Palier':7s} {'PnL_D2':10s} {'Delta_USD':10s} {'Scenario':20s}")
    print("-" * 110)

    total_actual = 0.0
    total_d2 = 0.0
    n_paliers_armed = 0
    n_saves = 0
    delta_total = 0.0
    by_palier = {}

    for trade in all_trades:
        sym = trade.get("symbol", "?")
        cfg = GUARD_RAILS_BOT3.get(sym, {})
        paliers = cfg.get("ladder_paliers", [])
        tick_value = cfg.get("tick_value", 0.50)
        n_contracts = cfg.get("n_contracts", 3)

        result = replay_ladder(trade, paliers, tick_value, n_contracts)

        ts = (trade.get("exit_time") or trade.get("entry_time") or "?")[:10]
        side = (trade.get("direction") or trade.get("side") or "?")[:6]
        mfe = trade.get("mfe_ticks") or 0
        pnl_actuel = trade.get("pnl_usd") or 0
        palier = result["palier_armed"]
        pnl_d2 = result["pnl_d2_usd"]
        delta = result["delta_usd"]
        scenario = result["scenario"]

        marker = " *" if delta > 0 else ""
        print(f"{ts:12s} {sym:4s} {side:6s} {mfe:7.1f} ${pnl_actuel:+9.2f}     "
              f"{palier:7d} ${pnl_d2:+8.2f}  ${delta:+8.2f}  {scenario:20s}{marker}")

        total_actual += pnl_actuel
        total_d2 += pnl_d2
        delta_total += delta
        if palier > 0:
            n_paliers_armed += 1
            by_palier[palier] = by_palier.get(palier, 0) + 1
        if delta > 0:
            n_saves += 1

    print()
    print("=" * 70)
    print(f"RESUME REPLAY LADDER D2 sur {len(all_trades)} trades historiques :")
    print(f"  PnL TOTAL actuel       : ${total_actual:+10.2f}")
    print(f"  PnL TOTAL Solution D2  : ${total_d2:+10.2f}")
    print(f"  DELTA Solution D2 vs   : ${delta_total:+10.2f}  ({delta_total*100/max(1,abs(total_actual)):+.1f}%)")
    print()
    print(f"  Trades avec palier 1+ arme : {n_paliers_armed} / {len(all_trades)} ({n_paliers_armed*100/max(1,len(all_trades)):.0f}%)")
    print(f"  Trades sauves par ladder    : {n_saves} (cumul ${delta_total:+.2f})")
    print()
    print(f"  Distribution paliers armes :")
    for p in sorted(by_palier.keys()):
        print(f"    Palier {p} : {by_palier[p]} trades")


if __name__ == "__main__":
    main()
