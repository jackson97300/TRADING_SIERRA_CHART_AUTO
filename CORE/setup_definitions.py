"""setup_definitions.py — 11 setups validés empiriquement (edge_discovery_bot2 sur 1 an V4).

Created : 2026-05-02 dimanche soir.
Source : DOCS/EDGE_REPORT_BOT2_NQ.md + DOCS/EDGE_REPORT_BOT2_ES.md

Architecture :
  - Chaque setup est une fonction pure check_<name>(bar, symbol) -> Optional[dict]
  - Retourne dict avec features matched OU None si pas de trigger
  - Pas de side effect, pas de logging ici (separation of concerns)
  - Le moteur (setup_engine.py) appelle evaluate_all_setups() et resout les conflits

REGLE D'OR : pas de feature forward (fwd1, realized_pts, etc.) — anti-leak strict.

Mode : PAPER_TRADE actif des lundi (Sim2 DTC). NE PAS modifier les seuils sans
  re-backtest sur edge_discovery_bot2.py.
"""
from __future__ import annotations
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# SETUP REGISTRY — metadata uniquement (PF/WR backtest, side, applicabilite)
# ═══════════════════════════════════════════════════════════════════

SETUP_REGISTRY = {
    # ─── GROUPE 1 : UNIVERSELS (NQ + ES) ──────────────────────────
    "SELL_TOP_RANGE": {
        "side": "SHORT",
        "symbols": ("NQ", "ES"),
        "group": "universal",
        "description": "Prix au sommet du range jour + finish faible = rejection",
        "backtest": {
            "NQ": {"pf": 2.27, "wr": 60.1, "n": 1431},
            "ES": {"pf": 2.15, "wr": 57.5, "n": 1684},
        },
    },
    "BUY_CROSS_DELTA_AGREE": {
        "side": "LONG",
        "symbols": ("NQ", "ES"),
        "group": "universal",
        "description": "Cross-instrument ES/NQ d'accord + bas range + delta positif",
        "backtest": {
            "NQ": {"pf": 2.19, "wr": 63.6, "n": 330},
            "ES": {"pf": 2.01, "wr": 60.7, "n": 333},
        },
    },
    "SELL_LATE_SESSION_FADE": {
        "side": "SHORT",
        "symbols": ("NQ", "ES"),
        "group": "universal",
        "description": "Dernier quart session + prix haut + finish faible = fade",
        "backtest": {
            "NQ": {"pf": 2.23, "wr": 61.3, "n": 519},
            "ES": {"pf": 1.86, "wr": 56.5, "n": 628},
        },
    },
    "SELL_1D_MAX_REJECT": {
        "side": "SHORT",
        "symbols": ("NQ", "ES"),
        "group": "universal",
        "description": "Prix proche du 1d max MQ = resistance intraday",
        "backtest": {
            "NQ": {"pf": 2.12, "wr": 57.6, "n": 262},
            "ES": {"pf": 1.56, "wr": 52.5, "n": 387},
        },
    },
    "BUY_CVD_DIVERGENCE": {
        "side": "LONG",
        "symbols": ("NQ", "ES"),
        "group": "universal",
        "description": "Prix bas + CVD positif = divergence bullish",
        "backtest": {
            "NQ": {"pf": 3.51, "wr": 59.6, "n": 166},
            "ES": {"pf": 1.89, "wr": 69.5, "n": 59},
        },
    },
    "BUY_BOTTOM_RANGE": {
        "side": "LONG",
        "symbols": ("NQ", "ES"),
        "group": "universal",
        "description": "Prix au bas range + RVOL spike = reversal",
        "backtest": {
            "NQ": {"pf": 2.88, "wr": 61.1, "n": 36},
            "ES": {"pf": 1.88, "wr": 58.1, "n": 31},
        },
        "warning_low_n": True,
    },
    # ─── GROUPE 2 : NQ EXCLUSIFS ───────────────────────────────────
    "SELL_DELTA_EXHAUSTION": {
        "side": "SHORT",
        "symbols": ("NQ",),
        "group": "nq_only",
        "description": "Delta exhaustion = momentum s'essouffle (NQ robuste)",
        "backtest": {"NQ": {"pf": 1.42, "wr": 52.9, "n": 2524}},
    },
    "SELL_CVD_DIVERGENCE": {
        "side": "SHORT",
        "symbols": ("NQ",),
        "group": "nq_only",
        "description": "Prix haut + CVD negatif = divergence bearish",
        "backtest": {"NQ": {"pf": 1.32, "wr": 55.6, "n": 817}},
    },
    "BUY_VWAP_RECLAIM": {
        "side": "LONG",
        "symbols": ("NQ",),
        "group": "nq_only",
        "description": "Prix traverse VWAP daily + slope positive = trend",
        "backtest": {"NQ": {"pf": 1.50, "wr": 55.3, "n": 47}},
        "warning_low_n": True,
    },
    # ─── GROUPE 3 : ES EXCLUSIFS ───────────────────────────────────
    "BUY_MQ_PUT_SUPPORT": {
        "side": "LONG",
        "symbols": ("ES",),
        "group": "es_only",
        "description": "Prix proche MQ Put = support gamma squeeze",
        "backtest": {"ES": {"pf": 2.55, "wr": 63.0, "n": 305}},
    },
    "BUY_NAKED_POC_MAGNET": {
        "side": "LONG",
        "symbols": ("ES",),
        "group": "es_only",
        "description": "Naked POC actif = prix attire vers POC non retest",
        "backtest": {"ES": {"pf": 2.91, "wr": 70.4, "n": 54}},
        "warning_low_n": True,
        # FIX B-5 (02/05 soir review market-analyst + code-reviewer) :
        # n=54 = data dredging confirme 2x par reviews. Phase 1 = OBSERVE_ONLY :
        # le checker continue de retourner les conditions matched (log) mais
        # SetupEngine.evaluate skipera ce setup pour ne pas trader. Reactivation
        # automatique apres Phase 2 si n_live >= 100 et PF >= 1.3.
        "phase_1_disabled": True,
    },
}


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _get(bar, key: str, default=None):
    """Safe getter avec fallback. Bar peut etre dict, pd.Series ou Mapping."""
    try:
        v = bar.get(key, default) if hasattr(bar, "get") else (
            bar[key] if key in bar else default
        )
    except (KeyError, TypeError):
        return default
    if v is None:
        return default
    # NaN check
    try:
        s = str(v).lower()
        if s == "nan" or s == "<na>":
            return default
    except Exception:
        pass
    return v


def _is_finite(v) -> bool:
    if v is None:
        return False
    try:
        f = float(v)
        return f == f and abs(f) != float("inf")
    except (ValueError, TypeError):
        return False


def _f(v):
    """Cast to float, NaN-safe."""
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ═══════════════════════════════════════════════════════════════════
# SETUP CHECKERS — pure functions returning dict of matched conditions or None
# ═══════════════════════════════════════════════════════════════════

def check_sell_top_range(bar, symbol: str) -> Optional[dict]:
    """Conditions: position_in_range > 0.90 AND finish_strength < -15."""
    pos = _f(_get(bar, "position_in_range"))
    finish = _f(_get(bar, "finish_strength"))
    if pos is None or finish is None:
        return None
    if pos > 0.90 and finish < -15:
        return {
            "position_in_range": pos,
            "finish_strength": finish,
        }
    return None


def check_buy_cross_delta_agree(bar, symbol: str) -> Optional[dict]:
    """Conditions: im_cross_delta_agreement_5 > 0.7 AND position_in_range < 0.30 AND delta_bar > 0."""
    cross = _f(_get(bar, "im_cross_delta_agreement_5"))
    pos = _f(_get(bar, "position_in_range"))
    delta = _f(_get(bar, "delta_bar"))
    if cross is None or pos is None or delta is None:
        return None
    if cross > 0.7 and pos < 0.30 and delta > 0:
        return {
            "im_cross_delta_agreement_5": cross,
            "position_in_range": pos,
            "delta_bar": delta,
        }
    return None


def check_sell_late_session_fade(bar, symbol: str) -> Optional[dict]:
    """Conditions: time_to_session_close_norm < 0.25 AND position_in_range > 0.80 AND finish_strength < 0."""
    ttc = _f(_get(bar, "time_to_session_close_norm"))
    pos = _f(_get(bar, "position_in_range"))
    finish = _f(_get(bar, "finish_strength"))
    if ttc is None or pos is None or finish is None:
        return None
    if ttc < 0.25 and pos > 0.80 and finish < 0:
        return {
            "time_to_session_close_norm": ttc,
            "position_in_range": pos,
            "finish_strength": finish,
        }
    return None


def check_sell_1d_max_reject(bar, symbol: str) -> Optional[dict]:
    """Conditions: |dist_1d_max_ticks_pct| < 0.05 AND finish_strength < 0."""
    dist = _f(_get(bar, "dist_1d_max_ticks_pct"))
    finish = _f(_get(bar, "finish_strength"))
    if dist is None or finish is None:
        return None
    if abs(dist) < 0.05 and finish < 0:
        return {
            "dist_1d_max_ticks_pct": dist,
            "finish_strength": finish,
        }
    return None


def check_buy_cvd_divergence(bar, symbol: str) -> Optional[dict]:
    """Conditions: delta_day_dir == 1 AND position_in_range < 0.30 AND dist_vwap_d_pct > 0.05."""
    ddd = _f(_get(bar, "delta_day_dir"))
    pos = _f(_get(bar, "position_in_range"))
    dvwap = _f(_get(bar, "dist_vwap_d_pct"))
    if ddd is None or pos is None or dvwap is None:
        return None
    if ddd == 1 and pos < 0.30 and dvwap > 0.05:
        return {
            "delta_day_dir": int(ddd),
            "position_in_range": pos,
            "dist_vwap_d_pct": dvwap,
        }
    return None


def check_buy_bottom_range(bar, symbol: str) -> Optional[dict]:
    """Conditions: position_in_range < 0.10 AND rvol > 1.2 AND delta_bar > 0."""
    pos = _f(_get(bar, "position_in_range"))
    rvol = _f(_get(bar, "rvol"))
    delta = _f(_get(bar, "delta_bar"))
    if pos is None or rvol is None or delta is None:
        return None
    if pos < 0.10 and rvol > 1.2 and delta > 0:
        return {
            "position_in_range": pos,
            "rvol": rvol,
            "delta_bar": delta,
        }
    return None


def check_sell_delta_exhaustion(bar, symbol: str) -> Optional[dict]:
    """NQ ONLY. Conditions: ctx_delta_exhaustion > 0.5 AND position_in_range > 0.70."""
    if symbol != "NQ":
        return None
    exh = _f(_get(bar, "ctx_delta_exhaustion"))
    pos = _f(_get(bar, "position_in_range"))
    if exh is None or pos is None:
        return None
    if exh > 0.5 and pos > 0.70:
        return {
            "ctx_delta_exhaustion": exh,
            "position_in_range": pos,
        }
    return None


def check_sell_cvd_divergence(bar, symbol: str) -> Optional[dict]:
    """NQ ONLY. Conditions: delta_day_dir == -1 AND position_in_range > 0.70 AND dist_vwap_d_pct < -0.05."""
    if symbol != "NQ":
        return None
    ddd = _f(_get(bar, "delta_day_dir"))
    pos = _f(_get(bar, "position_in_range"))
    dvwap = _f(_get(bar, "dist_vwap_d_pct"))
    if ddd is None or pos is None or dvwap is None:
        return None
    if ddd == -1 and pos > 0.70 and dvwap < -0.05:
        return {
            "delta_day_dir": int(ddd),
            "position_in_range": pos,
            "dist_vwap_d_pct": dvwap,
        }
    return None


def check_buy_vwap_reclaim(bar, symbol: str) -> Optional[dict]:
    """NQ ONLY. Conditions: |dist_vwap_d_pct| < 0.05 AND vwap_slope_10 > 1 AND rvol > 0.5."""
    if symbol != "NQ":
        return None
    dvwap = _f(_get(bar, "dist_vwap_d_pct"))
    slope = _f(_get(bar, "vwap_slope_10"))
    rvol = _f(_get(bar, "rvol"))
    if dvwap is None or slope is None or rvol is None:
        return None
    if abs(dvwap) < 0.05 and slope > 1 and rvol > 0.5:
        return {
            "dist_vwap_d_pct": dvwap,
            "vwap_slope_10": slope,
            "rvol": rvol,
        }
    return None


def check_buy_mq_put_support(bar, symbol: str) -> Optional[dict]:
    """ES ONLY. Conditions: dist_mq_put_pct > -1.0 AND delta_bar > 0 AND rvol > 0.6."""
    if symbol != "ES":
        return None
    dmq = _f(_get(bar, "dist_mq_put_pct"))
    delta = _f(_get(bar, "delta_bar"))
    rvol = _f(_get(bar, "rvol"))
    if dmq is None or delta is None or rvol is None:
        return None
    if dmq > -1.0 and delta > 0 and rvol > 0.6:
        return {
            "dist_mq_put_pct": dmq,
            "delta_bar": delta,
            "rvol": rvol,
        }
    return None


def check_buy_naked_poc_magnet(bar, symbol: str) -> Optional[dict]:
    """ES ONLY. Conditions: n_naked_poc_within_0_5pct > 0 AND position_in_range < 0.50 AND delta_bar > 0."""
    if symbol != "ES":
        return None
    n_naked = _f(_get(bar, "n_naked_poc_within_0_5pct"))
    pos = _f(_get(bar, "position_in_range"))
    delta = _f(_get(bar, "delta_bar"))
    if n_naked is None or pos is None or delta is None:
        return None
    if n_naked > 0 and pos < 0.50 and delta > 0:
        return {
            "n_naked_poc_within_0_5pct": n_naked,
            "position_in_range": pos,
            "delta_bar": delta,
        }
    return None


# ═══════════════════════════════════════════════════════════════════
# DISPATCHER : map nom -> fonction
# ═══════════════════════════════════════════════════════════════════

SETUP_CHECKERS = {
    "SELL_TOP_RANGE":           check_sell_top_range,
    "BUY_CROSS_DELTA_AGREE":    check_buy_cross_delta_agree,
    "SELL_LATE_SESSION_FADE":   check_sell_late_session_fade,
    "SELL_1D_MAX_REJECT":       check_sell_1d_max_reject,
    "BUY_CVD_DIVERGENCE":       check_buy_cvd_divergence,
    "BUY_BOTTOM_RANGE":         check_buy_bottom_range,
    "SELL_DELTA_EXHAUSTION":    check_sell_delta_exhaustion,
    "SELL_CVD_DIVERGENCE":      check_sell_cvd_divergence,
    "BUY_VWAP_RECLAIM":         check_buy_vwap_reclaim,
    "BUY_MQ_PUT_SUPPORT":       check_buy_mq_put_support,
    "BUY_NAKED_POC_MAGNET":     check_buy_naked_poc_magnet,
}

# Sanity check at import time : tous les noms du registry doivent avoir un checker
assert set(SETUP_REGISTRY.keys()) == set(SETUP_CHECKERS.keys()), \
    "REGISTRY <-> CHECKERS mismatch"


# ═══════════════════════════════════════════════════════════════════
# EVAL ALL — main public API
# ═══════════════════════════════════════════════════════════════════

def evaluate_all_setups(bar, symbol: str) -> list[dict]:
    """Evalue tous les setups applicables au symbole sur 1 bar.

    Args:
        bar: dict-like (pd.Series, dict, Mapping) avec features V4 enriched
        symbol: "NQ" ou "ES"

    Returns:
        list of dicts {name, side, group, conditions} pour les setups triggered.
        Skip les setups marques `phase_1_disabled = True` (FIX B-5 02/05).
    """
    if symbol not in ("NQ", "ES"):
        return []
    triggered = []
    for name, checker in SETUP_CHECKERS.items():
        meta = SETUP_REGISTRY[name]
        if symbol not in meta["symbols"]:
            continue
        # FIX B-5 (02/05) : skip setups disabled Phase 1 (data dredging confirme)
        if meta.get("phase_1_disabled", False):
            continue
        match = checker(bar, symbol)
        if match is not None:
            triggered.append({
                "name": name,
                "side": meta["side"],
                "group": meta["group"],
                "conditions": match,
            })
    return triggered


def get_setups_for_symbol(symbol: str) -> list[str]:
    """Retourne la liste des noms de setups applicables au symbole."""
    return [name for name, meta in SETUP_REGISTRY.items()
            if symbol in meta["symbols"]]


# ═══════════════════════════════════════════════════════════════════
# Smoke test
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Bar synthetique : SELL_TOP_RANGE conditions
    sample = {
        "position_in_range": 0.94,
        "finish_strength": -22,
        "im_cross_delta_agreement_5": 0.5,
        "delta_bar": -10,
        "rvol": 1.0,
        "time_to_session_close_norm": 0.50,
        "dist_1d_max_ticks_pct": 0.20,
        "delta_day_dir": -1,
        "dist_vwap_d_pct": -0.10,
        "ctx_delta_exhaustion": 0.3,
        "vwap_slope_10": 0.5,
        "dist_mq_put_pct": -2.0,
        "n_naked_poc_within_0_5pct": 0,
    }
    triggers_nq = evaluate_all_setups(sample, "NQ")
    triggers_es = evaluate_all_setups(sample, "ES")
    print(f"Setups Bot 2 V4 : {len(SETUP_REGISTRY)} definis")
    print(f"  NQ : {len(get_setups_for_symbol('NQ'))} applicables")
    print(f"  ES : {len(get_setups_for_symbol('ES'))} applicables")
    print(f"\nSample bar (pos=0.94, finish=-22) :")
    print(f"  Triggers NQ : {[t['name'] for t in triggers_nq]}")
    print(f"  Triggers ES : {[t['name'] for t in triggers_es]}")
