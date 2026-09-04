"""Detecteurs de patterns double bottom / double top.

Multi-session et intraday.
"""
import json
import logging
import os
from glob import glob

from DASHBOARD.config import DATA_DIR

from DASHBOARD.api.readers import (
    TICK_SIZE,
    get_field,
    get_int_field,
    get_bars_source,
    get_latest_jsonl,
)

logger = logging.getLogger(__name__)


def detect_double_pattern(symbol: str, current_price: float) -> dict:
    """Detecte les double bottoms et double tops sur les 7 derniers jours.

    Lit les session lows/highs de chaque fichier JSONL.
    Deux session extremes proches (< TOLERANCE ticks) = double pattern.
    Retourne le pattern le plus recent avec neckline et status.
    """
    # BASCULE 04/09 (#100) : source enrichie prioritaire (cf get_bars_source)
    _src = get_bars_source(symbol)
    files = sorted(glob(os.path.join(*_src)), key=os.path.getmtime) if _src else []
    if len(files) < 3:
        return {"detected": False}

    # Prendre les 7 derniers fichiers non-weekend (>100KB)
    recent = []
    for f in reversed(files):
        try:
            if os.path.getsize(f) > 100000:
                recent.append(f)
                if len(recent) >= 7:
                    break
        except OSError:
            continue
    recent.reverse()

    if len(recent) < 3:
        return {"detected": False}

    # Extraire session high/low de chaque jour
    sessions = []
    for filepath in recent:
        sess_high = 0.0
        sess_low = 999999.0
        sess_high_bar = None
        sess_low_bar = None
        date_str = os.path.basename(filepath).split("_")[0]
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        d = json.loads(s)
                    except json.JSONDecodeError:
                        continue
                    bh = get_field(d, "bar_high", 0.0)
                    bl = get_field(d, "bar_low", 0.0)
                    if bh > sess_high:
                        sess_high = bh
                        sess_high_bar = d
                    if 0 < bl < sess_low:
                        sess_low = bl
                        sess_low_bar = d
        except OSError:
            continue

        if sess_high > 0 and sess_low < 999999:
            sessions.append({
                "date": date_str,
                "high": sess_high,
                "low": sess_low,
                "high_bar": sess_high_bar,
                "low_bar": sess_low_bar,
            })

    if len(sessions) < 2:
        return {"detected": False}

    tick = TICK_SIZE
    # Tolerance adaptee a l'instrument (NQ range ~3x ES)
    tolerance = 100 if symbol == "NQ" else 40  # ticks (reduit pour eviter faux positifs)

    results = []

    # Chercher double bottom : 2 sessions avec des lows proches
    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            low_diff = abs(sessions[i]["low"] - sessions[j]["low"]) / tick
            if low_diff <= tolerance:
                avg_low = (sessions[i]["low"] + sessions[j]["low"]) / 2
                # Neckline = plus haut high entre les 2 bottoms
                neckline = 0.0
                for k in range(i, j + 1):
                    if sessions[k]["high"] > neckline:
                        neckline = sessions[k]["high"]

                dist_to_neckline = round((neckline - current_price) / tick) if current_price else 0
                dist_to_bottom = round((current_price - avg_low) / tick) if current_price else 0

                # Status
                if current_price > neckline:
                    status = "CASSE"
                    signal = "BULL"
                elif current_price > avg_low + (neckline - avg_low) * 0.5:
                    status = "EN ROUTE"
                    signal = "BULL"
                else:
                    status = "FORMATION"
                    signal = "NEUTRE"

                # Retest neckline ?
                retest_neckline = abs(current_price - neckline) / tick <= 30

                results.append({
                    "type": "DOUBLE_BOTTOM",
                    "bottom_1": {"date": sessions[i]["date"], "price": sessions[i]["low"]},
                    "bottom_2": {"date": sessions[j]["date"], "price": sessions[j]["low"]},
                    "avg_price": round(avg_low, 2),
                    "diff_ticks": round(low_diff, 0),
                    "neckline": round(neckline, 2),
                    "dist_neckline": dist_to_neckline,
                    "dist_bottom": dist_to_bottom,
                    "status": status,
                    "signal": signal,
                    "retest_neckline": retest_neckline,
                    "target": round(neckline + (neckline - avg_low), 2),  # mesure classique
                })

    # Chercher double top : 2 sessions avec des highs proches
    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            high_diff = abs(sessions[i]["high"] - sessions[j]["high"]) / tick
            if high_diff <= tolerance:
                avg_high = (sessions[i]["high"] + sessions[j]["high"]) / 2
                # Neckline = plus bas low entre les 2 tops
                neckline = 999999.0
                for k in range(i, j + 1):
                    if sessions[k]["low"] < neckline:
                        neckline = sessions[k]["low"]

                dist_to_neckline = round((current_price - neckline) / tick) if current_price else 0
                dist_to_top = round((avg_high - current_price) / tick) if current_price else 0

                if current_price < neckline:
                    status = "CASSE"
                    signal = "BEAR"
                elif current_price < avg_high - (avg_high - neckline) * 0.5:
                    status = "EN ROUTE"
                    signal = "BEAR"
                else:
                    status = "FORMATION"
                    signal = "NEUTRE"

                retest_neckline = abs(current_price - neckline) / tick <= 30

                results.append({
                    "type": "DOUBLE_TOP",
                    "top_1": {"date": sessions[i]["date"], "price": sessions[i]["high"]},
                    "top_2": {"date": sessions[j]["date"], "price": sessions[j]["high"]},
                    "avg_price": round(avg_high, 2),
                    "diff_ticks": round(high_diff, 0),
                    "neckline": round(neckline, 2),
                    "dist_neckline": dist_to_neckline,
                    "dist_top": dist_to_top,
                    "status": status,
                    "signal": signal,
                    "retest_neckline": retest_neckline,
                    "target": round(neckline - (avg_high - neckline), 2),
                })

    if not results:
        return {"detected": False}

    # Trier par pertinence : CASSE > EN ROUTE > FORMATION, puis par proximite
    priority = {"CASSE": 0, "EN ROUTE": 1, "FORMATION": 2}
    results.sort(key=lambda r: (priority.get(r["status"], 3), abs(r.get("dist_neckline", 9999))))

    return {
        "detected": True,
        "patterns": results,
        "best": results[0],
    }


def detect_intraday_double(symbol: str, current_price: float) -> dict:
    """Detecte les double bottoms/tops INTRADAY dans la session du jour.

    Utilise les champs DMP : new_swing_low, new_swing_high, retest_low_count,
    retest_high_count, retest_low_delta_div, retest_high_delta_div.
    Confirmation par le volume : volume au 2eme test vs volume au 1er test.
    """
    path = get_latest_jsonl(symbol)
    if not path:
        return {"detected": False}

    tick = TICK_SIZE
    bars = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    bars.append(json.loads(s))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return {"detected": False}

    if len(bars) < 30:
        return {"detected": False}

    # Collecter les swing lows et swing highs avec leur contexte
    swing_lows = []
    swing_highs = []

    for i, b in enumerate(bars):
        price = get_field(b, "price", 0.0)
        bar_low = get_field(b, "bar_low", 0.0)
        bar_high = get_field(b, "bar_high", 0.0)
        vol = get_field(b, "total_vol", 0.0)
        delta = get_field(b, "delta_bar", 0.0)
        ts = b.get("ts", 0)

        if get_int_field(b, "new_swing_low", 0):
            swing_low_price = price + get_field(b, "dist_swing_low", 0.0) * tick
            swing_lows.append({
                "idx": i, "ts": ts, "price": bar_low,
                "swing_price": swing_low_price, "vol": vol, "delta": delta,
                "retest_count": get_int_field(b, "retest_low_count", 0),
                "delta_div": get_int_field(b, "retest_low_delta_div", 0),
            })

        if get_int_field(b, "new_swing_high", 0):
            swing_high_price = price + get_field(b, "dist_swing_high", 0.0) * tick
            swing_highs.append({
                "idx": i, "ts": ts, "price": bar_high,
                "swing_price": swing_high_price, "vol": vol, "delta": delta,
                "retest_count": get_int_field(b, "retest_high_count", 0),
                "delta_div": get_int_field(b, "retest_high_delta_div", 0),
            })

    results = []
    tolerance = 120 if symbol == "NQ" else 40  # ticks intraday
    min_bars_between = 30  # 30 barres min = 30 min separation

    # Double bottom intraday : 2 swing lows proches
    for i in range(len(swing_lows)):
        for j in range(i + 1, len(swing_lows)):
            s1 = swing_lows[i]
            s2 = swing_lows[j]
            bars_gap = s2["idx"] - s1["idx"]
            if bars_gap < min_bars_between:
                continue  # trop rapproche = bruit de range
            diff = abs(s1["price"] - s2["price"]) / tick
            if diff > tolerance:
                continue

            avg_low = (s1["price"] + s2["price"]) / 2

            # Neckline = plus haut entre les 2 lows
            neckline = 0.0
            for k in range(s1["idx"], min(s2["idx"] + 1, len(bars))):
                bh = get_field(bars[k], "bar_high", 0.0)
                if bh > neckline:
                    neckline = bh

            # Retracement minimum entre les 2 tests : la neckline doit etre
            # au moins 30% au-dessus des bottoms (sinon c'est un range plat)
            pattern_height = neckline - avg_low
            min_retrace = 30 * tick  # 30 ticks minimum de retrace
            if pattern_height < min_retrace:
                continue  # range plat, pas un vrai double bottom

            # Confirmation volume : pour un BOTTOM, vol AUGMENTE au 2eme test
            # = les acheteurs reviennent avec conviction
            vol_ratio = s2["vol"] / s1["vol"] if s1["vol"] > 0 else 1.0
            vol_confirmed = vol_ratio >= 1.2  # 20% de vol en plus au 2eme test

            # Confirmation delta : delta positif au 2eme bottom = acheteurs
            delta_confirmed = s2["delta"] > 0

            # Delta divergence au retest
            delta_div = s2["delta_div"]

            # Score qualite (strict)
            quality = 0
            if diff <= tolerance / 3:
                quality += 2  # lows tres proches
            elif diff <= tolerance / 2:
                quality += 1
            if vol_confirmed:
                quality += 2  # volume monte au 2eme test
            if delta_confirmed:
                quality += 1
            if delta_div:
                quality += 2  # divergence au retest = signal fort
            if bars_gap >= 60:
                quality += 1  # bonne separation (1h+)

            # Filtre : ignorer les patterns de mauvaise qualite
            if quality < 4:
                continue

            # Status
            dist_neck = round((neckline - current_price) / tick) if current_price else 0
            if current_price > neckline:
                status = "CASSE"
            elif current_price > avg_low + (neckline - avg_low) * 0.5:
                status = "EN ROUTE"
            else:
                status = "FORMATION"

            results.append({
                "type": "DOUBLE_BOTTOM",
                "scope": "INTRADAY",
                "low_1": {"idx": s1["idx"], "price": round(s1["price"], 2), "vol": s1["vol"]},
                "low_2": {"idx": s2["idx"], "price": round(s2["price"], 2), "vol": s2["vol"]},
                "diff_ticks": round(diff, 0),
                "neckline": round(neckline, 2),
                "dist_neckline": dist_neck,
                "target": round(neckline + (neckline - avg_low), 2),
                "status": status,
                "signal": "BULL" if status in ("CASSE", "EN ROUTE") else "NEUTRE",
                "vol_confirmed": vol_confirmed,
                "vol_ratio": round(vol_ratio, 2),
                "delta_confirmed": delta_confirmed,
                "delta_div": bool(delta_div),
                "quality": quality,
                "bars_between": s2["idx"] - s1["idx"],
            })

    # Double top intraday : 2 swing highs proches
    for i in range(len(swing_highs)):
        for j in range(i + 1, len(swing_highs)):
            s1 = swing_highs[i]
            s2 = swing_highs[j]
            bars_gap = s2["idx"] - s1["idx"]
            if bars_gap < min_bars_between:
                continue  # trop rapproche = bruit
            diff = abs(s1["price"] - s2["price"]) / tick
            if diff > tolerance:
                continue

            avg_high = (s1["price"] + s2["price"]) / 2

            neckline = 999999.0
            for k in range(s1["idx"], min(s2["idx"] + 1, len(bars))):
                bl = get_field(bars[k], "bar_low", 0.0)
                if 0 < bl < neckline:
                    neckline = bl

            # Retracement minimum
            pattern_height = avg_high - neckline
            if pattern_height < 30 * tick:
                continue  # range plat

            # Volume : pour un TOP, vol BAISSE au 2eme test = epuisement acheteurs
            vol_ratio = s2["vol"] / s1["vol"] if s1["vol"] > 0 else 1.0
            vol_confirmed = vol_ratio <= 0.8  # 20% de vol EN MOINS au 2eme test
            delta_confirmed = s2["delta"] < 0  # delta negatif au 2eme top = vendeurs
            delta_div = s2["delta_div"]

            quality = 0
            if diff <= tolerance / 3:
                quality += 2  # highs tres proches
            elif diff <= tolerance / 2:
                quality += 1
            if vol_confirmed:
                quality += 2  # volume baisse = epuisement
            if delta_confirmed:
                quality += 1
            if delta_div:
                quality += 2
            if bars_gap >= 60:
                quality += 1

            if quality < 4:
                continue

            dist_neck = round((current_price - neckline) / tick) if current_price else 0
            if current_price < neckline:
                status = "CASSE"
            elif current_price < avg_high - (avg_high - neckline) * 0.5:
                status = "EN ROUTE"
            else:
                status = "FORMATION"

            results.append({
                "type": "DOUBLE_TOP",
                "scope": "INTRADAY",
                "high_1": {"idx": s1["idx"], "price": round(s1["price"], 2), "vol": s1["vol"]},
                "high_2": {"idx": s2["idx"], "price": round(s2["price"], 2), "vol": s2["vol"]},
                "diff_ticks": round(diff, 0),
                "neckline": round(neckline, 2),
                "dist_neckline": dist_neck,
                "target": round(neckline - (avg_high - neckline), 2),
                "status": status,
                "signal": "BEAR" if status in ("CASSE", "EN ROUTE") else "NEUTRE",
                "vol_confirmed": vol_confirmed,
                "vol_ratio": round(vol_ratio, 2),
                "delta_confirmed": delta_confirmed,
                "delta_div": bool(delta_div),
                "quality": quality,
                "bars_between": s2["idx"] - s1["idx"],
            })

    if not results:
        return {"detected": False}

    # Trier par qualite puis par status
    priority = {"CASSE": 0, "EN ROUTE": 1, "FORMATION": 2}
    results.sort(key=lambda r: (priority.get(r["status"], 3), -r["quality"]))

    return {
        "detected": True,
        "patterns": results[:5],  # top 5 max
        "best": results[0],
    }
