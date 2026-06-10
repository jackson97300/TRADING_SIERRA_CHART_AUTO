"""banner_utils.py — Helpers centralises lecture banner dashboard.

Mission : eviter regressions silencieuses lors de migration de schema banner
(ex: rename `ts_ms` -> `ts` 07/05/2026 = bug 24h sur Bot 1, fix Bot 2 V6 08/05).

Source de verite producer : `DASHBOARD/api/builders.py::build_price_banner`.
Schema actuel : `{"ts": <ms>, "ts_ms": <ms_alias>, "bar_ts_ms": <ms_alias>, "price", ...}`.

Usage :
    from CORE.banner_utils import read_banner_ts_ms

    for sym in ("ES", "NQ"):
        b = banner.get(sym.lower(), {})
        ts_ms = read_banner_ts_ms(b)
        if ts_ms:
            age_sec = (now_ms - ts_ms) / 1000

Date : 2026-05-08
"""
from __future__ import annotations

from typing import Optional


# Liste ordonnee des alias possibles. Premiere valeur trouvee gagne.
# Ordre choisi : nouveau schema (ts) en premier, anciens en fallback.
_BANNER_TS_FIELDS = ("ts", "ts_ms", "bar_ts_ms")


def read_banner_ts_ms(banner_inst: dict) -> Optional[float]:
    """Retourne le timestamp ms du dernier bar du banner instrument, ou None.

    Args:
        banner_inst: dict banner pour un symbole (ex: banner["es"], banner["nq"]).

    Returns:
        Timestamp en millisecondes (float) si trouve, None sinon.

    Note: La fonction defend contre :
      - dict vide -> None
      - field absent (3 alias testes) -> None
      - valeur falsy (0, "", None) -> None
      - banner_inst non-dict -> None
    """
    if not isinstance(banner_inst, dict):
        return None
    for field in _BANNER_TS_FIELDS:
        val = banner_inst.get(field)
        if val:  # filtre 0/None/""
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def compute_last_bar_age_sec(banner: dict, now_ms: float,
                              symbols: tuple = ("ES", "NQ"),
                              max_age_clamp_sec: float = 86400.0,
                              fallback_sec: float = 99999.0) -> float:
    """Age (sec) de la derniere bar disponible cross-instruments.

    Args:
        banner: dict banner complet (ex: response["banner"]).
        now_ms: timestamp now en millisecondes (datetime.now(utc).timestamp()*1000).
        symbols: instruments a verifier (defaut ES + NQ).
        max_age_clamp_sec: clamp anti outlier (24h).
        fallback_sec: valeur sentinel si aucun ts trouve (default 99999 = STALE CRIT).

    Returns:
        Age max (sec) parmi les instruments. Sentinel fallback_sec si aucun.
    """
    if not isinstance(banner, dict):
        return fallback_sec
    ages = []
    for sym in symbols:
        b = banner.get(sym.lower(), {})
        ts_ms = read_banner_ts_ms(b)
        if ts_ms is None:
            continue
        age = (now_ms - ts_ms) / 1000
        if 0 <= age < max_age_clamp_sec:
            ages.append(age)
    return float(max(ages)) if ages else fallback_sec
