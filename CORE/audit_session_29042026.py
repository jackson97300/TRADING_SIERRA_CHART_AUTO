"""Audit complet session 29/04 (CME trading day) sur les 2 bots."""
import json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

PAPER_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")


def load_trades(fp):
    rows = []
    if not fp.exists():
        return pd.DataFrame()
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                try:
                    rows.append(json.loads(s))
                except json.JSONDecodeError:
                    pass
    return pd.DataFrame(rows)


def analyse_bot(name, fp):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    df = load_trades(fp)
    if df.empty:
        print("  Aucun trade")
        return
    print(f"\n  Trades total session : {len(df)}")
    pnl_col = "pnl_ticks" if "pnl_ticks" in df.columns else None
    if not pnl_col:
        print("  WARN no pnl_ticks col")
        return
    df["_pnl"] = pd.to_numeric(df[pnl_col], errors="coerce").fillna(0)
    n_total = len(df)
    n_wins = int((df["_pnl"] > 0).sum())
    n_losses = int((df["_pnl"] <= 0).sum())
    wr = n_wins / n_total if n_total else 0
    sum_wins = float(df.loc[df["_pnl"] > 0, "_pnl"].sum())
    sum_losses = float(df.loc[df["_pnl"] <= 0, "_pnl"].sum())
    pf = (sum_wins / abs(sum_losses)) if sum_losses != 0 else float("inf")
    pnl_total = float(df["_pnl"].sum())
    pnl_usd = float(pd.to_numeric(df.get("pnl_usd", 0), errors="coerce").fillna(0).sum())

    print(f"  WR : {wr*100:.1f}% ({n_wins}W / {n_losses}L)")
    print(f"  PF : {pf:.2f}")
    print(f"  PnL : {pnl_total:+.0f}t / ${pnl_usd:+.2f}")
    if n_wins > 0:
        print(f"  Avg win : +{sum_wins/n_wins:.1f}t")
    if n_losses > 0:
        print(f"  Avg loss : {sum_losses/n_losses:.1f}t")

    # Par symbol
    if "symbol" in df.columns:
        print(f"\n  Par symbol :")
        for sym in sorted(df["symbol"].unique()):
            sub = df[df["symbol"] == sym]
            sub_wins = int((sub["_pnl"] > 0).sum())
            sub_pnl = float(sub["_pnl"].sum())
            print(f"    {sym}: n={len(sub):>2d}  W={sub_wins}  WR={sub_wins/len(sub)*100:.0f}%  pnl={sub_pnl:+.0f}t")

    # Outcomes
    out_col = "outcome" if "outcome" in df.columns else None
    if out_col:
        print(f"\n  Outcomes :")
        for out, cnt in df[out_col].value_counts().items():
            sub_pnl = float(df.loc[df[out_col] == out, "_pnl"].sum())
            print(f"    {out:10s}: n={cnt:>2d}  pnl={sub_pnl:+.0f}t")

    # Direction
    dir_col = "direction" if "direction" in df.columns else None
    if dir_col:
        print(f"\n  Directions :")
        for d, cnt in df[dir_col].value_counts().items():
            sub_pnl = float(df.loc[df[dir_col] == d, "_pnl"].sum())
            print(f"    {d:6s}: n={cnt:>2d}  pnl={sub_pnl:+.0f}t")

    # Walls usage (si dispo)
    if "sl_wall" in df.columns:
        print(f"\n  SL walls top 5:")
        for w, cnt in df["sl_wall"].fillna("missing").value_counts().head(5).items():
            print(f"    {str(w)[:40]:40s} : {cnt}")

    # Premier et dernier trade
    if "entry_time" in df.columns:
        df["_dt"] = pd.to_datetime(df["entry_time"], errors="coerce")
        df_sorted = df.sort_values("_dt")
        first = df_sorted.iloc[0]
        last = df_sorted.iloc[-1]
        print(f"\n  Plage : {str(first['_dt'])[:19]} -> {str(last['_dt'])[:19]}")


# === STATES ACTUELS ===
print("="*70)
print("  POSITIONS LIVE NOW")
print("="*70)
fp1 = PAPER_DIR / "state.json"
fp2 = PAPER_DIR / "databento_paper_state.json"
if fp1.exists():
    s1 = json.loads(fp1.read_text(encoding="utf-8"))
    obs = s1.get("open_by_symbol", {})
    print(f"\nBot 1 Sim3 : {len(obs)} positions ouvertes")
    for sym, p in obs.items():
        unr = p.get("unrealized_pnl_ticks") or 0
        unr_usd = p.get("unrealized_pnl_usd") or 0
        print(f"  {sym} {p.get('direction')} @ {p.get('entry_price')} | unrealized {unr:+.0f}t (${unr_usd:+.2f})")
if fp2.exists():
    s2 = json.loads(fp2.read_text(encoding="utf-8"))
    ap = s2.get("active_positions", {})
    print(f"\nBot 2 Sim2 : {len(ap)} positions ouvertes")
    for sym, p in ap.items():
        print(f"  {sym} {p.get('side')} @ {p.get('entry')} sl={p.get('sl_ticks')}t/{p.get('sl_wall')} tp={p.get('tp_ticks')}t")

# === BOTS TRADES SESSION 29/04 ===
analyse_bot("BOT 1 SIM3 (mia_paper_trader)", PAPER_DIR / "20260429_trades.jsonl")
analyse_bot("BOT 2 SIM2 (databento_paper_trader)", PAPER_DIR / "20260429_databento_trades.jsonl")
