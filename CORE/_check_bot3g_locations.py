"""Check BOT3G_* dans events + decisions logs VPS."""
import json
from pathlib import Path

logs_dir = Path(r"C:\TRADING_SIERRA_CHART_AUTO\LOGS")
results = {}

for cat in ["events", "decisions", "trading", "execution"]:
    cat_dir = logs_dir / cat
    if not cat_dir.exists():
        continue
    for log in cat_dir.glob("*_20260512_paper_v2.jsonl"):
        n_bot3g = 0
        n_bar_stale_mgc = 0
        n_bar_none_mgc = 0
        n_mgc_any = 0
        sample_codes = set()
        last_mgc_evt = None
        with open(log, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                code = evt.get("code", "")
                ctx = evt.get("ctx") or {}
                sym = ctx.get("sym") or ctx.get("symbol")
                if sym == "MGC":
                    n_mgc_any += 1
                    last_mgc_evt = evt
                    sample_codes.add(code)
                    if code == "BOT3_BAR_STALE":
                        n_bar_stale_mgc += 1
                    if code == "BOT3_BAR_NONE":
                        n_bar_none_mgc += 1
                if code.startswith("BOT3G_"):
                    n_bot3g += 1
                    sample_codes.add(code)
        if n_mgc_any > 0 or n_bot3g > 0:
            results[str(log)] = {
                "n_mgc_any": n_mgc_any,
                "n_bot3g": n_bot3g,
                "n_bar_stale_mgc": n_bar_stale_mgc,
                "n_bar_none_mgc": n_bar_none_mgc,
                "codes": sorted(sample_codes),
                "last_mgc_ts": last_mgc_evt.get("ts") if last_mgc_evt else None,
                "last_mgc_code": last_mgc_evt.get("code") if last_mgc_evt else None,
            }

for log, info in results.items():
    print(f"--- {log} ---")
    for k, v in info.items():
        print(f"  {k}: {v}")
    print()

if not results:
    print("AUCUN event MGC ni BOT3G_* dans events/ decisions/ trading/ execution/")
