"""R4 fix : extract trades day=27 ES+NQ avril 2026 dbn.zst -> parquet.

Re-utilise meme logique que CORE/live_pipeline.py:convert_trades_to_parquet.
"""
from pathlib import Path
import databento as db

ROOT = Path(__file__).resolve().parents[1]
TRADES_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "trades"

DAYS = [
    ("ES.c.0", 2026, 4, 29),
    ("NQ.c.0", 2026, 4, 29),
    ("ES.c.0", 2026, 4, 30),
    ("NQ.c.0", 2026, 4, 30),
]

for sym, y, m, d in DAYS:
    fp = TRADES_ROOT / f"symbol={sym}" / f"year={y}" / f"month={m}" / f"day={d}" / "data.dbn.zst"
    out_fp = fp.with_name("data.parquet")
    if not fp.exists():
        print(f"[MISS] {sym} {y}-{m:02d}-{d:02d} : dbn.zst absent")
        continue
    if out_fp.exists():
        size_kb = out_fp.stat().st_size / 1024
        print(f"[SKIP] {sym} {y}-{m:02d}-{d:02d} : parquet exists ({size_kb:.0f} KB)")
        continue
    try:
        store = db.DBNStore.from_file(str(fp))
        df = store.to_df()
        df.to_parquet(out_fp, compression="zstd", index=True)
        size_kb = out_fp.stat().st_size / 1024
        print(f"[OK]   {sym} {y}-{m:02d}-{d:02d} : {len(df)} trades -> {out_fp.name} ({size_kb:.0f} KB)")
    except Exception as e:
        print(f"[ERR]  {sym} {y}-{m:02d}-{d:02d} : {e}")
