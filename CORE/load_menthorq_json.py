"""
load_menthorq_json.py — Loader MenthorQ depuis fichiers JSON scrapes (Option C).

CONTEXTE :
  Fix R1 audit code-reviewer 19/05/2026 : le builder pure V4 lisait
  `DATA/mq_levels/` (Hive scsf_MIA_MQ_Lite, deploy 28/04/2026) au lieu des
  124 fichiers `DATA/MENTHORQ/{YYYYMMDD}_menthorq_complete.json` (couvrent
  decembre 2025 -> aujourd'hui). Consequence : 95% du backfill 8 mois aurait
  eu `regime_actionable=0` (Bot 2 V6 RegimeGate = code mort).

Ce module charge les niveaux MenthorQ depuis les JSON files daily et produit
un DataFrame compatible avec `load_mq_levels.attach_mq_distances()`.

SCHEMA JSON :
  d[symbol]['structured']['key_levels']['resource']['data'] :
    - 'Call Resistance', 'Call Resistance 0DTE' -> mq_call, mq_call_0dte
    - 'Put Support', 'Put Support 0DTE' -> mq_put, mq_put_0dte
    - 'High Vol Level' -> mq_hvl
    - '1D Max.', '1D Min.' -> mq_1d_max, mq_1d_min
  d[symbol]['structured']['bl_levels']['resource']['text_data'] :
    - "$ES1!: BL 1, 7172.37, BL 2, 7106.16, ..." -> mq_blind (list 10 floats)
  d[symbol]['structured']['netgex']['resource'] :
    - PAS de data brute lisible (image_url seulement) -> mq_gex = [None]*10

DataFrame OUTPUT format (compatible attach_mq_distances) :
  ts_event (datetime UTC naive, daily 00:00)
  mq_call, mq_put, mq_hvl, mq_call_0dte, mq_put_0dte, mq_hvl_0dte (float)
  mq_1d_min, mq_1d_max (float)
  mq_gex (list[float|None] de longueur 10)
  mq_blind (list[float|None] de longueur 10)
  trigger (str : "new_day")
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MENTHORQ_JSON_ROOT = ROOT / "DATA" / "MENTHORQ"

# Symbole Python -> nom dans le JSON (key top-level)
SYMBOL_TO_JSON_KEY = {
    "ES": "ES",
    "NQ": "NQ",
    "GC": "GC",
    "MGC": "GC",  # MGC partage les niveaux GC (Gold)
}

# Pattern parse bl_levels text_data : "$ES1!: BL 1, 7172.37, BL 2, 7106.16, ..."
BL_LEVEL_PATTERN = re.compile(r"BL\s+\d+,\s*([0-9]+\.?[0-9]*)")


def _parse_bl_levels(text_data: str) -> list[Optional[float]]:
    """Parse bl_levels.text_data en liste de 10 floats.

    Format : "$ES1!: BL 1, 7172.37, BL 2, 7106.16, ..."
    Retourne list[float|None] de longueur 10 (padding None si moins).
    """
    if not text_data or not isinstance(text_data, str):
        return [None] * 10
    matches = BL_LEVEL_PATTERN.findall(text_data)
    values = []
    for m in matches[:10]:
        try:
            values.append(float(m))
        except (ValueError, TypeError):
            values.append(None)
    while len(values) < 10:
        values.append(None)
    return values


def _safe_float(v) -> Optional[float]:
    """Cast en float, None si invalide ou string non numerique."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            # Strip suffix "%" si present (ex: "1.02%" → 1.02)
            v = v.replace("%", "").strip()
            return float(v)
        except (ValueError, TypeError):
            return None
    return None


def _extract_historical_schema(d: dict, symbol: str, ts_event: pd.Timestamp) -> Optional[dict]:
    """Extrait niveaux depuis schema HISTORIQUE (avant mai 2026) :
        d['key_levels'][symbol]['call_resistance', 'put_support', 'hvl', 'hvl_0dte', '1d_max', '1d_min', ...]
        d['vol_model'][symbol]['top_gex_strikes' (list float), 'bl_levels' (list dict {'level': float})]
    """
    json_key = SYMBOL_TO_JSON_KEY.get(symbol)
    if json_key is None:
        return None

    kl = d.get("key_levels", {})
    if not isinstance(kl, dict) or json_key not in kl:
        return None
    sym_kl = kl[json_key]
    if not isinstance(sym_kl, dict):
        return None

    # Extract GEX strikes + BL levels depuis vol_model
    vm = d.get("vol_model", {})
    sym_vm = vm.get(json_key, {}) if isinstance(vm, dict) else {}
    if not isinstance(sym_vm, dict):
        sym_vm = {}

    gex_strikes = sym_vm.get("top_gex_strikes", [])
    if isinstance(gex_strikes, list):
        gex_list = [_safe_float(x) for x in gex_strikes[:10]]
        while len(gex_list) < 10:
            gex_list.append(None)
    else:
        gex_list = [None] * 10

    bl_levels = sym_vm.get("bl_levels", [])
    if isinstance(bl_levels, list):
        bl_list = []
        for item in bl_levels[:10]:
            if isinstance(item, dict) and "level" in item:
                bl_list.append(_safe_float(item["level"]))
            else:
                bl_list.append(_safe_float(item))
        while len(bl_list) < 10:
            bl_list.append(None)
    else:
        bl_list = [None] * 10

    row = {
        "ts_event": ts_event,
        "mq_call": _safe_float(sym_kl.get("call_resistance")),
        "mq_call_0dte": _safe_float(sym_kl.get("call_resistance_0dte")),
        "mq_put": _safe_float(sym_kl.get("put_support")),
        "mq_put_0dte": _safe_float(sym_kl.get("put_support_0dte")),
        "mq_hvl": _safe_float(sym_kl.get("hvl")),
        "mq_hvl_0dte": _safe_float(sym_kl.get("hvl_0dte")),
        "mq_1d_max": _safe_float(sym_kl.get("1d_max")),
        "mq_1d_min": _safe_float(sym_kl.get("1d_min")),
        "mq_gex": gex_list,
        "mq_blind": bl_list,
        "trigger": "new_day",
    }
    n_valid = sum(1 for k in ("mq_call", "mq_put", "mq_hvl", "mq_1d_max", "mq_1d_min")
                  if row[k] is not None)
    return row if n_valid >= 3 else None


def _extract_structured_schema(d: dict, symbol: str, ts_event: pd.Timestamp) -> Optional[dict]:
    """Extrait niveaux depuis schema STRUCTURED (post mai 2026) :
        d[symbol]['structured']['key_levels']['resource']['data']['Call Resistance', ...]
        d[symbol]['structured']['bl_levels']['resource']['text_data'] = "BL 1, X, BL 2, Y, ..."
    """
    json_key = SYMBOL_TO_JSON_KEY.get(symbol)
    if json_key is None or json_key not in d:
        return None
    sym_data = d[json_key]
    if not isinstance(sym_data, dict) or "structured" not in sym_data:
        return None
    struct = sym_data["structured"]
    if not isinstance(struct, dict):
        return None

    kl_data = (struct.get("key_levels", {}) or {}).get("resource", {}) or {}
    levels_dict = kl_data.get("data", {}) if isinstance(kl_data.get("data"), dict) else {}

    bl_text = (struct.get("bl_levels", {}) or {}).get("resource", {}) or {}
    bl_text_data = bl_text.get("text_data", "") if isinstance(bl_text, dict) else ""

    row = {
        "ts_event": ts_event,
        "mq_call": _safe_float(levels_dict.get("Call Resistance")),
        "mq_call_0dte": _safe_float(levels_dict.get("Call Resistance 0DTE")),
        "mq_put": _safe_float(levels_dict.get("Put Support")),
        "mq_put_0dte": _safe_float(levels_dict.get("Put Support 0DTE")),
        "mq_hvl": _safe_float(levels_dict.get("High Vol Level")),
        # mq_hvl_0dte : pas dans le schema structured (TODO si MenthorQ ajoute)
        "mq_hvl_0dte": None,
        "mq_1d_max": _safe_float(levels_dict.get("1D Max.")),
        "mq_1d_min": _safe_float(levels_dict.get("1D Min.")),
        # mq_gex : netgex.image_url seulement (TODO Phase 2)
        "mq_gex": [None] * 10,
        # mq_blind : parse bl_levels.text_data
        "mq_blind": _parse_bl_levels(bl_text_data),
        "trigger": "new_day",
    }
    n_valid = sum(1 for k in ("mq_call", "mq_put", "mq_hvl", "mq_1d_max", "mq_1d_min")
                  if row[k] is not None)
    return row if n_valid >= 3 else None


def _extract_levels_from_json(d: dict, symbol: str, ts_event: pd.Timestamp) -> Optional[dict]:
    """Extrait une row de niveaux pour 1 symbole + 1 date depuis fichier JSON.

    Supporte LES 2 SCHEMAS :
      - HISTORIQUE (avant mai 2026) : key_levels top-level + vol_model
      - STRUCTURED (post mai 2026)  : d[symbol].structured.key_levels.resource.data

    Essaie historique en premier (plus riche : hvl_0dte + gex_strikes structures),
    fallback structured si historique absent ou vide.
    """
    row = _extract_historical_schema(d, symbol, ts_event)
    if row is not None:
        return row
    return _extract_structured_schema(d, symbol, ts_event)


def load_menthorq_json(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Load tous les MenthorQ JSON files dans la fenetre [start, end].

    Args:
        symbol : "ES", "NQ", "MGC", "GC"
        start, end : range inclusif (date objects)

    Returns:
        DataFrame compatible attach_mq_distances() :
          - ts_event (datetime UTC naive, daily 00:00)
          - mq_call/put/hvl + _0dte (float ou None)
          - mq_1d_min/max (float)
          - mq_gex (list[None]*10 : Phase 2 TODO)
          - mq_blind (list[float|None] de longueur 10)
          - trigger ("new_day")

        DataFrame vide si aucun fichier valide trouve.
    """
    if symbol not in SYMBOL_TO_JSON_KEY:
        raise ValueError(f"symbol must be in {list(SYMBOL_TO_JSON_KEY.keys())}, got {symbol!r}")

    rows = []
    cur = start
    while cur <= end:
        # Cherche d'abord le fichier standard "{YYYYMMDD}_menthorq_complete.json"
        # Puis "gold" variant pour GC/MGC (fichiers contenant gold scrape)
        ymd = cur.strftime("%Y%m%d")
        candidate_files = [
            MENTHORQ_JSON_ROOT / f"{ymd}_menthorq_complete.json",
        ]
        if symbol in ("GC", "MGC"):
            candidate_files.append(MENTHORQ_JSON_ROOT / f"{ymd}_gold_menthorq_complete.json")

        # ts_event = minuit UTC du jour (broadcast asof backward sur bars du jour)
        ts_event = pd.Timestamp(cur, tz="UTC").tz_localize(None)

        for fp in candidate_files:
            if not fp.exists():
                continue
            try:
                with open(fp, encoding="utf-8") as f:
                    d = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [WARN] load_menthorq_json: {fp.name} unreadable ({e})")
                continue

            row = _extract_levels_from_json(d, symbol, ts_event)
            if row is not None:
                rows.append(row)
                break  # 1 row par jour suffit, on prend le 1er fichier valide

        cur += timedelta(days=1)

    if not rows:
        print(f"[WARN] load_menthorq_json({symbol}): 0 rows valides on [{start},{end}] "
              f"dans {MENTHORQ_JSON_ROOT} — features MQ seront NaN/0.")
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("ts_event").reset_index(drop=True)
    return df


def _test_load_one_day():
    """Test integration : load 1 jour ES 30/04/2026 doit retourner 1 row valide."""
    d = date(2026, 4, 30)
    df = load_menthorq_json("ES", d, d)
    print(f"Test ES 2026-04-30 : {len(df)} rows")
    if len(df) == 1:
        r = df.iloc[0]
        print(f"  mq_call={r['mq_call']}, mq_put={r['mq_put']}, mq_hvl={r['mq_hvl']}")
        print(f"  mq_1d_max={r['mq_1d_max']}, mq_1d_min={r['mq_1d_min']}")
        print(f"  mq_blind sample 3: {r['mq_blind'][:3]}")
        assert r["mq_call"] is not None
        assert r["mq_put"] is not None
        print("  OK")
    else:
        print(f"  FAIL : attendu 1 row, obtenu {len(df)}")


if __name__ == "__main__":
    _test_load_one_day()
