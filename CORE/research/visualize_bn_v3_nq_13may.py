"""visualize_bn_v3_nq_13may.py — Visualisation BN V3 sur chart NQ 13/05/2026.

Mission : annoter le chart envoye par Jackson (NQ 13/05, points 1->10) avec
ce que BN V3 detecte automatiquement. Permet a Jackson de comparer "vision
algo" vs "vision trader" et identifier les ecarts.

Annotations affichees :
  - Swings HH/HL/LH/LL detectes par _detect_swings (numeros + couleur)
  - Ref level "verte la plus basse" du leg actif (bleu pointille)
  - SL initial pullback_low - buffer (rouge pointille)
  - Niveaux Fibonacci 30%/50%/62% du dernier leg (gris pointille)
  - Annotations texte sur chaque swing (HH, HL, LH, LL + prix)
  - Bougies vertes/rouges code couleur classique

Output : DATA/research/bn_v3_nq_13may_annotated.png

Note : utilise donnee synthetique (make_nq_chart_13may2026 du test) car
pas de DMP JSONL reel pour 13/05/2026 (dernier disponible = 07/05).
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bn_v3_engine import BNV3Engine, BNV3State, SL_BUFFER_TICKS
from CORE.tests.test_bn_v3_engine import make_nq_chart_13may2026


def plot_candles(ax, df: pd.DataFrame) -> None:
    """Plot OHLC candles vert/rouge classique."""
    for i, row in df.iterrows():
        is_green = row["close"] > row["open"]
        color = "#26a69a" if is_green else "#ef5350"
        body_h = abs(row["close"] - row["open"])
        body_low = min(row["close"], row["open"])
        # Wick
        ax.plot([i, i], [row["low"], row["high"]], color=color, linewidth=0.6, zorder=1)
        # Body
        rect = patches.Rectangle((i - 0.35, body_low), 0.7, max(body_h, 0.1),
                                  facecolor=color, edgecolor=color, zorder=2)
        ax.add_patch(rect)


def annotate_swings(ax, swings, df: pd.DataFrame) -> None:
    """Annote chaque swing avec son type Dow (HH/HL/LH/LL) et un numero."""
    for i, s in enumerate(swings, start=1):
        y_offset = 12 if s.swing_type == "HIGH" else -18
        color = {"HH": "#1b5e20", "HL": "#2e7d32", "LH": "#b71c1c", "LL": "#c62828"}.get(s.dow, "gray")
        ax.scatter([s.idx], [s.price], s=80, color=color, zorder=5,
                   edgecolor="black", linewidth=1.0)
        ax.annotate(f"{i}\n{s.dow}\n{s.price:.1f}",
                    xy=(s.idx, s.price), xytext=(0, y_offset),
                    textcoords="offset points", ha="center", fontsize=8,
                    color=color, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor=color, alpha=0.9))


def draw_trail_ref_level(ax, engine, state, df, end_idx: int) -> None:
    """Trace la ref_level 'verte la plus basse' a un end_idx donne (= snapshot)."""
    state.active = True
    state.direction = "LONG"
    window = df.iloc[:end_idx + 1]
    r = engine.check_lowest_green_trail(window, state)
    if r["ref_level"] is not None:
        ax.axhline(y=r["ref_level"], xmin=0, xmax=1, color="blue",
                   linestyle="--", linewidth=1.0, alpha=0.4, zorder=3)
        ax.text(end_idx, r["ref_level"] + 1.0,
                f"trail_ref={r['ref_level']:.1f} (bar {end_idx})",
                fontsize=7, color="blue", alpha=0.8)


def draw_fibo_levels(ax, swings, df: pd.DataFrame) -> None:
    """Trace les niveaux Fibo 30%/50%/62% du dernier leg HL->HH."""
    hhs = [s for s in swings if s.dow == "HH"]
    hls = [s for s in swings if s.dow == "HL"]
    if not hhs or not hls:
        return
    last_hh = hhs[-1]
    # Prendre HL juste avant ce HH
    hls_before = [s for s in hls if s.idx < last_hh.idx]
    if not hls_before:
        return
    last_hl = hls_before[-1]
    leg_size = last_hh.price - last_hl.price
    fibos = {
        "30%": last_hh.price - 0.30 * leg_size,
        "50%": last_hh.price - 0.50 * leg_size,
        "62%": last_hh.price - 0.62 * leg_size,
    }
    x_start = last_hh.idx
    x_end = len(df) - 1
    for label, lvl in fibos.items():
        ax.plot([x_start, x_end], [lvl, lvl], color="#9e9e9e",
                linestyle=":", linewidth=0.8, alpha=0.6, zorder=3)
        ax.text(x_end, lvl, f" Fibo {label} = {lvl:.1f}",
                fontsize=7, color="#616161", va="center")


def annotate_jackson_points(ax) -> None:
    """Annotations manuelles correspondant aux points 1-10 sur le chart Jackson."""
    points = [
        (5,   28720, "1\nSTART", "#000"),
        (19,  28805, "2", "#000"),
        (32,  28755, "3", "#000"),
        (54,  28860, "4", "#000"),
        (68,  28820, "5", "#000"),
        (89,  28900, "6", "#000"),
        (103, 28845, "7", "#000"),
        (115, 28920, "8", "#000"),
        (122, 28910, "9", "#000"),
        (128, 28944, "10\nHH", "#000"),
    ]
    for x, y, label, color in points:
        ax.annotate(label, xy=(x, y), xytext=(0, 30),
                    textcoords="offset points", ha="center", fontsize=10,
                    fontweight="bold", color=color,
                    bbox=dict(boxstyle="circle,pad=0.4", facecolor="yellow",
                              edgecolor="black", alpha=0.9))


def main():
    print("[1/4] Generation chart synthetique NQ 13/05/2026...")
    df = make_nq_chart_13may2026()
    print(f"      {len(df)} bars generees, range [{df['low'].min():.1f}, {df['high'].max():.1f}]")

    print("[2/4] Detection swings BN V3 (dow_min_swings=2 pour vue exhaustive)...")
    engine = BNV3Engine(sym="NQ", use_range_filter=False, dow_min_swings=2)
    swings = engine._detect_swings(df)
    print(f"      {len(swings)} swings detectes :")
    for s in swings:
        print(f"        bar {s.idx:3d}  {s.swing_type:5s}  {s.dow:3s}  price={s.price:.2f}")

    print("[3/4] Construction figure annotee...")
    fig, ax = plt.subplots(figsize=(18, 9))
    plot_candles(ax, df)
    annotate_swings(ax, swings, df)
    draw_fibo_levels(ax, swings, df)
    annotate_jackson_points(ax)

    # Trail ref level a 3 snapshots (milieu des replies 2->3, 4->5, 6->7)
    state = BNV3State()
    for snapshot_idx in [29, 64, 99]:  # mid-pullback chaque repli
        draw_trail_ref_level(ax, engine, state, df, snapshot_idx)

    # Diagnostic uptrend Dow
    is_up = engine._is_uptrend_dow(swings)
    ax.text(0.02, 0.97, f"Dow uptrend (>=2 HH+HL) : {'OUI ✓' if is_up else 'NON ✗'}",
            transform=ax.transAxes, fontsize=11, fontweight="bold",
            color="green" if is_up else "red",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.9))

    ax.set_title("BN V3 — vision algo sur chart NQ 13/05/2026 (synthetique)\n"
                 "Pastilles JAUNES = points 1-10 (Jackson)  |  Pastilles VERT/ROUGE = swings detectes BN V3  |  "
                 "Lignes BLEUES = trail 'verte la plus basse'  |  Lignes GRISES = Fibo retracement",
                 fontsize=10)
    ax.set_xlabel("Bar index")
    ax.set_ylabel("Prix NQ")
    ax.grid(alpha=0.2)
    ax.set_xlim(-2, len(df) + 5)

    out_dir = ROOT / "DATA" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "bn_v3_nq_13may_annotated.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()

    print(f"[4/4] Figure sauvee : {out_path}")
    print(f"\n=== RESUME VISION ALGO ===")
    print(f"Total swings detectes : {len(swings)}")
    hhs = [s for s in swings if s.dow == "HH"]
    hls = [s for s in swings if s.dow == "HL"]
    lhs = [s for s in swings if s.dow == "LH"]
    lls = [s for s in swings if s.dow == "LL"]
    print(f"  HH (Higher High) : {len(hhs)}")
    print(f"  HL (Higher Low)  : {len(hls)}")
    print(f"  LH (Lower High)  : {len(lhs)}")
    print(f"  LL (Lower Low)   : {len(lls)}")
    print(f"Uptrend Dow valide (>=2 HH+HL successifs) : {is_up}")

    print(f"\n=== ECARTS VISION JACKSON vs ALGO ===")
    print("Jackson voit 10 points (1=START, 2/4/6/8=swing highs, 3/5/7=swing lows, 9=consolidation, 10=HH final).")
    print(f"Algo detecte {len(swings)} pivots avec swing_min_bars=3 (3 bars sans depassement).")
    if len(swings) != 7:  # 4 highs + 3 lows attendus si algo voit exactement Jackson
        print("ECART potentiel : ajuster swing_min_bars (3 actuel) pour matcher la sensibilite Jackson.")


if __name__ == "__main__":
    main()
