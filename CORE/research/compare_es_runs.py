"""compare_es_runs.py — Tableau comparatif Sprint ES Run 1-N.

Lit tous les configs sauvegardes dans DATA/MODELS/BASELINE_27042026/ES_*
et affiche un tableau synthese pour decision finale.

Usage : python -X utf8 CORE/research/compare_es_runs.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = ROOT / "DATA" / "MODELS" / "BASELINE_27042026"


def load_config_metrics(fp: Path) -> dict:
    """Extract aggregate_metrics from a config.json."""
    with open(fp, "r") as f:
        c = json.load(f)
    m = c.get("aggregate_metrics", {})
    return {
        "name": fp.stem,
        "side": c.get("side", "?"),
        "threshold": c.get("threshold", 0),
        "n_trades": m.get("total_trades", 0),
        "trades_per_day": m.get("trades_per_day", 0),
        "wr": m.get("win_rate", 0),
        "pf": m.get("profit_factor", 0),
        "ev": m.get("ev_per_trade", 0),
        "sharpe": m.get("sharpe", 0),
        "max_dd": m.get("max_drawdown", 0),
        "psr": m.get("psr", 0),
        "dsr": m.get("dsr", 0),
        "verdict": c.get("verdict", "?"),
    }


def main():
    print("=" * 110)
    print("  SPRINT ES — TABLEAU COMPARATIF")
    print("=" * 110)
    print()

    # Detecter tous les ES configs backup (pattern large : tout ES_*.json)
    configs = sorted(BASELINE_DIR.glob("ES_*.json"))
    # Exclure les non-configs (e.g. _model.pkl est .pkl pas .json donc deja exclu)

    print(f"  {len(configs)} configs detectees dans {BASELINE_DIR}")
    print()

    rows = []
    for fp in configs:
        try:
            m = load_config_metrics(fp)
            rows.append(m)
        except Exception as e:
            print(f"  [SKIP] {fp.name} : {e}")

    # Aussi current configs (dernier Run)
    cur_buy = ROOT / "DATA" / "MODELS" / "ES_buy_config.json"
    cur_sell = ROOT / "DATA" / "MODELS" / "ES_sell_config.json"
    for fp in (cur_buy, cur_sell):
        if fp.exists():
            try:
                m = load_config_metrics(fp)
                m["name"] = "[CURRENT] " + fp.stem
                rows.append(m)
            except Exception:
                pass

    # Tableau header
    headers = ["Name", "Side", "Thr", "Trades", "Tr/j", "WR%", "PF", "EV", "Sharpe", "MaxDD", "DSR", "Verdict"]
    fmt = "  {:<45} {:>4} {:>5} {:>6} {:>5} {:>6} {:>6} {:>6} {:>7} {:>6} {:>5} {:<35}"
    print(fmt.format(*headers))
    print("  " + "-" * 108)

    def _safe_fmt(v, spec="{:.2f}", default="?"):
        try:
            return spec.format(float(v))
        except (TypeError, ValueError):
            return default

    for r in rows:
        verdict_short = (r["verdict"] or "?")[:33]
        # Format DSR (peut etre tres petit)
        try:
            dsr_v = float(r["dsr"])
            if dsr_v == 0: dsr_str = "0"
            elif dsr_v >= 0.99: dsr_str = "1.0"
            elif dsr_v < 0.01: dsr_str = "<0.01"
            else: dsr_str = f"{dsr_v:.2f}"
        except (TypeError, ValueError):
            dsr_str = "0"

        print(fmt.format(
            r["name"][:45],
            (r["side"] or "?")[:4].upper(),
            _safe_fmt(r["threshold"], "{:.2f}"),
            r["n_trades"] or 0,
            _safe_fmt(r["trades_per_day"], "{:.1f}", "0"),
            _safe_fmt((r["wr"] or 0) * 100, "{:.1f}", "0"),
            _safe_fmt(r["pf"], "{:.2f}", "0"),
            _safe_fmt(r["ev"], "{:+.1f}", "0"),
            _safe_fmt(r["sharpe"], "{:+.2f}", "0"),
            int(r["max_dd"]) if r["max_dd"] else 0,
            dsr_str,
            verdict_short,
        ))

    print()
    print("=" * 110)

    # Highlight les GO / CAUTION
    print("\n  CHAMPIONS PAR CRITERE :")
    if rows:
        def _ok_pf(r):
            try:
                return r["n_trades"] > 0 and isinstance(r["pf"], (int, float)) and r["pf"] != float("inf")
            except: return False
        valid = [r for r in rows if _ok_pf(r)]
        if valid:
            best_pf = max(valid, key=lambda r: float(r["pf"]))
            print(f"    Best PF        : {best_pf['name'][:50]:<50}  PF={float(best_pf['pf']):.2f}")
            best_sharpe = max(valid, key=lambda r: float(r["sharpe"] or 0))
            print(f"    Best Sharpe    : {best_sharpe['name'][:50]:<50}  Sharpe={float(best_sharpe['sharpe']):+.2f}")
            best_ev = max(valid, key=lambda r: float(r["ev"] or 0))
            print(f"    Best EV/trade  : {best_ev['name'][:50]:<50}  EV={float(best_ev['ev']):+.1f}t")
            try:
                best_dsr = max(valid, key=lambda r: float(r["dsr"] or 0))
                print(f"    Best DSR       : {best_dsr['name'][:50]:<50}  DSR={float(best_dsr['dsr']):.3f}")
            except: pass
            most_trades = max(valid, key=lambda r: r["n_trades"])
            print(f"    Most trades    : {most_trades['name'][:50]:<50}  n={most_trades['n_trades']}")


if __name__ == "__main__":
    main()
