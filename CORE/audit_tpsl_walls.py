"""audit_tpsl_walls.py — Audit empirique TP/SL placement vs murs disponibles.

Question : si le bot avait place TP devant le mur le plus proche (Tier 1+2+3
incluant MenthorQ), aurait-il fait mieux que TP actuel (qui skip parfois les
murs Tier 1 < RR 1.5) ?

Strategie :
  1. Charger trades passes (Bot 1 + Bot 2)
  2. Pour chaque trade WIN/LOSS :
     a. Lister les distances aux murs disponibles dans features_at_entry
     b. Trouver le mur le plus proche DEVANT (direction du trade)
     c. Simuler TP = mur - tp_buffer
     d. Comparer avec TP actuel et avec mfe (Bot 1) / outcome (Bot 2)
  3. Aggregat :
     - Combien de trades auraient hit le TP simule ?
     - Quel gain $ vs TP actuel ?
     - Quel mur Tier (1/2/3) le plus utile ?

Output : rapport stdout + CSV `DATA/BACKTEST/audit_tpsl_walls_{date}.csv`
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
PAPER_DIR = ROOT / "DATA" / "PAPER_TRADES"
OUT_DIR = ROOT / "DATA" / "BACKTEST"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TICK_SIZE = 0.25
TICK_VALUE = {"ES": 1.25, "NQ": 0.5}

# Mapping mia_sltp.py walls → dist_*_pct features (Bot 2 features_at_entry)
# Convention : dist_*_pct positif = au-dessus du prix, negatif = en-dessous

# Tier 1 (vrais murs forts) — direction-aware via signe de dist
TIER1_WALLS = {
    "GEX_UP":         "dist_gex_nearest_up_pct",     # resist (pos)
    "GEX_DN":         "dist_gex_nearest_dn_pct",     # support (neg)
    "EDGE_BUY":       "dist_edge_buy_nearest_pct",   # support
    "EDGE_SELL":      "dist_edge_sell_nearest_pct",  # resist
    "SESS_HIGH":      "dist_sess_high_pct",          # resist
    "SESS_LOW":       "dist_sess_low_pct",           # support
}

# Tier 2 (murs solides volume profile + VWAP)
TIER2_WALLS = {
    "CUR_VAH":         "dist_cur_vah_pct",           # resist
    "CUR_VAL":         "dist_cur_val_pct",           # support
    "CUR_VPOC":        "dist_cur_vpoc_pct",          # both
    "PREV_VAH":        "dist_prev_vah_pct",          # resist
    "PREV_VAL":        "dist_prev_val_pct",          # support
    "VWAP+1SD":        "dist_pvwap_sd1u_pct",        # resist
    "VWAP-1SD":        "dist_pvwap_sd1d_pct",        # support
    "1D_MAX":          "dist_1d_max_ticks_pct",      # resist
    "1D_MIN":          "dist_1d_min_ticks_pct",      # support
    "OVN_HIGH":        "dist_ovn_high_pct",          # resist
    "OVN_LOW":         "dist_ovn_low_pct",           # support
    "SWING_HIGH":      "dist_last_swing_high_pct",   # resist
    "SWING_LOW":       "dist_last_swing_low_pct",    # support
    "PDH":             "dist_pdh_pct",               # resist
    "PDL":             "dist_pdl_pct",               # support
}

# Tier 3 (MenthorQ + IB — institutionnels mais parfois penetrables)
TIER3_WALLS = {
    "MQ_CALL":         "dist_mq_call_pct",           # resist (positive)
    "MQ_PUT":          "dist_mq_put_pct",            # support (negative)
    "MQ_CALL_0DTE":    "dist_mq_call_0dte_pct",      # resist
    "MQ_PUT_0DTE":     "dist_mq_put_0dte_pct",       # support
    "MQ_HVL":          "dist_mq_hvl_pct",            # both
    "MQ_HVL_0DTE":     "dist_mq_hvl_0dte_pct",       # both
    "IB_HIGH":         "dist_ib_high_pct",           # resist
    "IB_LOW":          "dist_ib_low_pct",            # support
    "PREV_VPOC":       "dist_prev_vpoc_pct",         # both
    "PVWAP":           "dist_pvwap_pct",             # both
}

ALL_WALLS = [
    (1, TIER1_WALLS),
    (2, TIER2_WALLS),
    (3, TIER3_WALLS),
]

# tp_buffer / sl_buffer (mia_sltp.py)
TP_BUFFER = {"NQ": 4, "ES": 2}
SL_BUFFER = {"NQ": 8, "ES": 4}


def load_trades_jsonl(pattern: str, exclude_databento: bool = False) -> list:
    """Charge trades.jsonl. Si exclude_databento=True, skip fichiers Bot 2."""
    trades = []
    for fp in sorted(PAPER_DIR.glob(pattern)):
        if exclude_databento and "databento" in fp.name:
            continue
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    trades.append(json.loads(s))
                except json.JSONDecodeError:
                    pass
    return trades


def find_nearest_wall(features: dict, direction: str, close: float) -> dict:
    """Trouve mur le plus proche DEVANT le prix dans la direction du trade.

    Pour LONG : mur AU-DESSUS = dist_*_pct > 0
    Pour SHORT : mur EN-DESSOUS = dist_*_pct < 0

    Returns :
        {tier1: (name, dist_ticks), tier2: (name, dist_ticks), tier3: (name, dist_ticks),
         best: (tier, name, dist_ticks)}
    """
    by_tier = {}
    all_candidates = []
    for tier, walls_dict in ALL_WALLS:
        candidates = []
        for name, col in walls_dict.items():
            d_pct = features.get(col)
            if d_pct is None or d_pct == 0:
                continue
            try:
                d_pct = float(d_pct)
            except (TypeError, ValueError):
                continue
            # Skip "_z" features (z-scored)
            if "_z" in col:
                continue
            # Convert pct to absolute ticks
            d_ticks_signed = d_pct / 100 * close / TICK_SIZE
            # Direction filter
            if direction == "LONG" and d_ticks_signed <= 0:
                continue  # mur en-dessous, pas pour TP LONG
            if direction == "SHORT" and d_ticks_signed >= 0:
                continue
            d_ticks_abs = abs(d_ticks_signed)
            # Skip too far (>200 ticks NQ, >80 ticks ES typiques)
            if d_ticks_abs > 250:
                continue
            candidates.append((name, d_ticks_abs, tier))
        if candidates:
            candidates.sort(key=lambda x: x[1])
            by_tier[f"tier{tier}"] = candidates[0]
        all_candidates.extend(candidates)

    if all_candidates:
        all_candidates.sort(key=lambda x: x[1])
        best = all_candidates[0]
        by_tier["best"] = best
    return by_tier


def simulate_tp_at_wall(wall_dist_ticks: float, tp_buffer: float) -> float:
    """TP simule = mur - tp_buffer."""
    return wall_dist_ticks - tp_buffer


def trade_would_hit_tp_simulated(trade: dict, tp_sim_ticks: float) -> bool:
    """Estime si le TP simule aurait ete touche.

    Bot 1 : utilise mfe (max favorable excursion en ticks)
    Bot 2 : utilise pnl_ticks ou outcome
    """
    mfe = trade.get("mfe")
    if mfe is not None:
        try:
            return float(mfe) >= tp_sim_ticks
        except (TypeError, ValueError):
            pass
    # Fallback Bot 2 : si outcome=TP et pnl >= sim → atteint
    outcome = trade.get("outcome")
    pnl_t = trade.get("pnl_ticks", 0) or 0
    if outcome == "TP":
        # Si outcome TP, le marche a atteint au moins le TP actuel
        # Si tp_sim < pnl_t (TP plus serre que TP actuel), aussi atteint
        return tp_sim_ticks <= pnl_t
    if outcome == "TIMEOUT":
        # Timeout = ni TP ni SL touche en N bars. pnl_t = position fermee au close.
        # Si tp_sim <= max favorable observe (proxy pnl_t si > 0, sinon non)
        return tp_sim_ticks <= max(0, pnl_t)
    if outcome == "SL":
        # SL touche = marche est descendu sous SL avant de remonter
        # mfe non dispo → on ne sait pas si TP serre aurait ete hit AVANT le SL
        return False  # pessimist
    return False


def main():
    print("=" * 90)
    print("  AUDIT TP/SL WALLS — placement TP devant mur proche vs TP actuel")
    print("=" * 90)

    # Bot 1 — exclude databento_*_trades.jsonl
    trades_b1 = load_trades_jsonl("*_trades.jsonl", exclude_databento=True)
    # Bot 2
    trades_b2 = load_trades_jsonl("*_databento_trades.jsonl")
    print(f"\nN trades Bot 1 (Sim3) : {len(trades_b1)}")
    print(f"N trades Bot 2 (Sim2) : {len(trades_b2)}")

    rows = []
    stats = defaultdict(int)
    delta_pnl_sum = 0
    n_better = 0
    n_worse = 0
    n_equal = 0
    by_tier_picked = defaultdict(int)

    for bot_label, trades in [("BOT1", trades_b1), ("BOT2", trades_b2)]:
        for t in trades:
            feat = t.get("features_at_entry") or {}
            if not isinstance(feat, dict) or not feat:
                continue
            close = feat.get("close") or t.get("entry_price")
            if not close or close <= 0:
                continue

            direction = t.get("direction", "").upper()
            sym = t.get("symbol", "ES")
            if not direction or sym not in ("ES", "NQ"):
                continue

            sl_ticks = t.get("sl_ticks", 0) or 0
            tp_ticks_actual = t.get("tp_ticks", 0) or 0
            tp_buffer = TP_BUFFER.get(sym, 4)

            # Find walls
            walls = find_nearest_wall(feat, direction, float(close))
            if "best" not in walls:
                continue
            # Best tuple format = (name, dist_abs, tier)
            best_name, best_dist, best_tier = walls["best"]

            # Simulate TP at nearest wall
            tp_sim = simulate_tp_at_wall(best_dist, tp_buffer)
            if tp_sim <= 0:
                continue  # mur trop proche, mange par buffer

            # RR sim
            rr_sim = tp_sim / sl_ticks if sl_ticks else 0

            # Would TP_sim be hit ?
            would_hit_sim = trade_would_hit_tp_simulated(t, tp_sim)

            # Outcome reel
            outcome_actual = t.get("outcome", "?")
            pnl_t_actual = t.get("pnl_ticks", 0) or 0

            # Pnl simule : si TP_sim hit → +tp_sim ticks. Sinon → SL (-sl_ticks)
            #   Approximation : si trade actuel = SL → SL aussi en sim (le marche a baisse)
            #                    si trade actuel = TP/TIMEOUT et TP_sim hit → +tp_sim
            if outcome_actual == "SL":
                pnl_t_sim = -sl_ticks
            elif would_hit_sim:
                pnl_t_sim = tp_sim
            else:
                # Trade aurait time-out, prend le close
                pnl_t_sim = pnl_t_actual

            tv = TICK_VALUE.get(sym, 1.0)
            n_micros = t.get("n_micros", 3)
            pnl_usd_actual = pnl_t_actual * tv * n_micros
            pnl_usd_sim = pnl_t_sim * tv * n_micros
            delta_usd = pnl_usd_sim - pnl_usd_actual

            stats[f"tier{best_tier}_picked"] += 1
            by_tier_picked[best_tier] += 1
            delta_pnl_sum += delta_usd
            if delta_usd > 0.5:
                n_better += 1
            elif delta_usd < -0.5:
                n_worse += 1
            else:
                n_equal += 1

            rows.append({
                "bot": bot_label,
                "entry_time": str(t.get("entry_time", ""))[:19],
                "sym": sym,
                "direction": direction,
                "outcome": outcome_actual,
                "sl_t": sl_ticks,
                "tp_t_actual": tp_ticks_actual,
                "tp_wall_actual": t.get("tp_wall", "?"),
                "best_wall_tier": best_tier,
                "best_wall_name": best_name,
                "best_wall_dist": round(best_dist, 1),
                "tp_t_sim": round(tp_sim, 1),
                "rr_sim": round(rr_sim, 2),
                "tp_sim_hit": would_hit_sim,
                "pnl_t_actual": pnl_t_actual,
                "pnl_t_sim": round(pnl_t_sim, 1),
                "delta_usd": round(delta_usd, 2),
            })

    print(f"\nN trades auditees : {len(rows)}")
    print(f"\n  Distribution mur le plus proche par tier :")
    for tier in (1, 2, 3):
        print(f"    Tier {tier} : {by_tier_picked[tier]}")

    print(f"\n  Trades MEILLEURS avec TP simule devant mur proche : {n_better}")
    print(f"  Trades EQUIVALENTS                                  : {n_equal}")
    print(f"  Trades PIRES                                        : {n_worse}")
    print(f"\n  Delta PnL total simule vs actuel : ${delta_pnl_sum:+.2f}")

    # Top 10 améliorations
    rows_sorted = sorted(rows, key=lambda r: r["delta_usd"], reverse=True)
    print(f"\n  Top 10 trades AMELIORES (delta_usd) :")
    print(f"  {'Time':<19s} {'Bot':<5s} {'Sym':<3s} {'Dir':<5s} {'Out':<8s} "
          f"{'TPwall_actual':<16s} {'TPwall_sim':<14s} {'RR_sim':>7s} "
          f"{'pnl_act':>7s} {'pnl_sim':>7s} {'delta$':>8s}")
    for r in rows_sorted[:10]:
        print(f"  {r['entry_time']:<19s} {r['bot']:<5s} {r['sym']:<3s} "
              f"{r['direction'][:5]:<5s} {r['outcome']:<8s} "
              f"{str(r['tp_wall_actual'])[:16]:<16s} "
              f"T{r['best_wall_tier']}/{r['best_wall_name'][:9]:<10s} "
              f"{r['rr_sim']:>7.2f} "
              f"{r['pnl_t_actual']:>+7.0f} {r['pnl_t_sim']:>+7.0f} "
              f"{r['delta_usd']:>+8.2f}")

    print(f"\n  Top 5 trades PIRES :")
    for r in rows_sorted[-5:]:
        print(f"  {r['entry_time']:<19s} {r['bot']:<5s} {r['sym']:<3s} "
              f"{r['direction'][:5]:<5s} {r['outcome']:<8s} "
              f"{str(r['tp_wall_actual'])[:16]:<16s} "
              f"T{r['best_wall_tier']}/{r['best_wall_name'][:9]:<10s} "
              f"{r['rr_sim']:>7.2f} "
              f"{r['pnl_t_actual']:>+7.0f} {r['pnl_t_sim']:>+7.0f} "
              f"{r['delta_usd']:>+8.2f}")

    # CSV export
    if rows:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        csv_path = OUT_DIR / f"audit_tpsl_walls_{ts}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n  CSV detail : {csv_path}")

    print("\n" + "=" * 90)
    if delta_pnl_sum > 0 and n_better > n_worse:
        print(f"  ✓ TP devant mur proche AURAIT AMELIORE le PnL total de ${delta_pnl_sum:+.2f}")
    elif delta_pnl_sum < 0:
        print(f"  ✗ TP devant mur proche AURAIT DEGRADE le PnL : ${delta_pnl_sum:+.2f}")
    else:
        print(f"  ~ Resultat mitige : {n_better} mieux / {n_worse} pires / {n_equal} equiv")
    print("=" * 90)


if __name__ == "__main__":
    main()
