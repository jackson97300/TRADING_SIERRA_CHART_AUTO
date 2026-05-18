"""Check qualite des dernieres bars live enriched (NQ/ES/MGC).

Usage : python -X utf8 tools/check_live_data_quality.py [/tmp/last_NQ.json ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CRITICAL_FIELDS = [
    "open", "high", "low", "close", "volume",
    "atr", "atr_14m", "atr_14m_pct", "vol_zscore_20", "rvol_zscore",
    "ib_complete", "ib_broken_up", "ib_broken_dn", "ib_range", "inside_value_area",
    "mq_call", "mq_put", "mq_hvl", "mq_put_0dte", "mq_call_0dte",
    "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
    "open_type", "day_type", "range_pos", "range_size",
    "bar_high", "bar_low", "session_id",
    "poc_migration_dir", "total_vol", "delta_bar",
    "vwap_d", "vwap_d_sd1u", "vwap_d_sd1d",
    "regime_mode", "regime_favor", "regime_actionable",
    "cur_vpoc", "cur_vah", "cur_val", "prev_vah", "prev_val",
    "sess_high", "sess_low", "pct_in_range",
]


def check_bar(sym: str, bar: dict) -> None:
    print(f"=== {sym} ({len(bar)} fields, ts={bar.get('ts_event_iso') or bar.get('ts_event')}) ===")
    print(f"  written_at={bar.get('written_at_iso')}, age_sec={bar.get('age_sec')}")
    nan_critical = []
    for k in CRITICAL_FIELDS:
        v = bar.get(k)
        if v is None or (isinstance(v, float) and v != v):
            nan_critical.append(k)
    print(f"  OK critical: {len(CRITICAL_FIELDS) - len(nan_critical)}/{len(CRITICAL_FIELDS)}")
    if nan_critical:
        print(f"  NaN/None critical ({len(nan_critical)}): {nan_critical}")
    # OHLC sanity
    o, h, lw, c = bar.get("open"), bar.get("high"), bar.get("low"), bar.get("close")
    ohlc_ok = all(x is not None for x in [o, h, lw, c])
    if ohlc_ok:
        h_ok = h >= max(o, c) and lw <= min(o, c) and h >= lw
        print(f"  OHLC: O={o} H={h} L={lw} C={c} {'OK' if h_ok else '!! ANOMALY'}")
    # MQ
    print(f"  MQ levels: call={bar.get('mq_call')} put={bar.get('mq_put')} "
          f"hvl={bar.get('mq_hvl')} put_0dte={bar.get('mq_put_0dte')} call_0dte={bar.get('mq_call_0dte')}")
    print(f"  MQ_1D : max={bar.get('mq_1d_max')} min={bar.get('mq_1d_min')}")
    # ATR sanity
    atr_d, atr_m = bar.get("atr"), bar.get("atr_14m")
    if atr_d and atr_m:
        ratio = atr_d / atr_m
        verdict = "OK (3-5x)" if 2.0 < ratio < 6.0 else "!! ANOMALY scale"
        print(f"  ATR: daily={atr_d:.2f} intraday14m={atr_m:.2f} ratio_d_to_m={ratio:.2f}x {verdict}")
    # IB
    print(f"  IB: complete={bar.get('ib_complete')} range={bar.get('ib_range')} "
          f"broken_up={bar.get('ib_broken_up')} broken_dn={bar.get('ib_broken_dn')}")
    # Volume
    vol = bar.get("volume")
    rvol_z = bar.get("rvol_zscore") or bar.get("vol_zscore_20")
    print(f"  Volume: total={vol} rvol_zscore={rvol_z}")
    # Regime
    print(f"  Regime: mode={bar.get('regime_mode')} favor={bar.get('regime_favor')} "
          f"actionable={bar.get('regime_actionable')} confidence={bar.get('regime_confidence')}")
    # Session
    print(f"  Session: id={bar.get('session_id')} is_cash={bar.get('is_cash_session')} "
          f"is_ib_window={bar.get('is_ib_window')}")
    # Overall stats
    n_nan = sum(1 for v in bar.values() if v is None or (isinstance(v, float) and v != v))
    print(f"  Overall NaN/None: {n_nan}/{len(bar)} ({n_nan / len(bar) * 100:.1f}%)")
    print()


def main():
    TMP = Path("C:/Users/jacks/AppData/Local/Temp")
    paths = [
        ("NQ", str(TMP / "last_nq.json")),
        ("ES", str(TMP / "last_es.json")),
        ("MGC", str(TMP / "last_mgc.json")),
    ]
    for sym, path in paths:
        p = Path(path)
        if not p.exists():
            print(f"--- {sym} : fichier absent {path} ---\n")
            continue
        raw = p.read_text().strip()
        if not raw or raw.startswith("no "):
            print(f"--- {sym} : VIDE (live enricher peut-etre pas active sur ce sym) ---\n")
            continue
        try:
            bar = json.loads(raw)
        except Exception as e:
            print(f"--- {sym} : ERREUR PARSE {e} ---")
            continue
        check_bar(sym, bar)


if __name__ == "__main__":
    main()
