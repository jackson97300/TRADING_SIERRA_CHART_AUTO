"""Briefing MIA — Analyse quotidienne generee automatiquement."""
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from DASHBOARD.api.data_reader import get_field, get_int_field, read_bot_status, read_last_bar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/briefing", tags=["briefing"])

BRIEFINGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "briefings"
)

# --- Constantes ---

OPEN_TYPE_LABELS = {
    0: "UNKNOWN",
    1: "Open Drive UP (conf 85%)",
    2: "Open Drive DOWN (conf 85%)",
    3: "Open Test Drive UP (conf 70%)",
    4: "Open Test Drive DOWN (conf 70%)",
    5: "Open Rejection Reversal UP (conf 60%)",
    6: "Open Rejection Reversal DOWN (conf 60%)",
    7: "Open Auction In Range (conf 30%)",
    8: "Open Auction Out of Range UP (conf 65%)",
    9: "Open Auction Out of Range DOWN (conf 65%)",
    10: "Open Drive Failed UP (conf 90%)",
    11: "Open Drive Failed DOWN (conf 90%)",
}

VIX_REGIME_DESC = {
    "LOW": (
        "Regime de faible volatilite — mouvements directionnels favorises, "
        "compression des primes options"
    ),
    "NORMAL": "Regime standard — conditions equilibrees, spreads normaux",
    "HIGH": (
        "Regime de haute volatilite — mouvements amplifies, stops elargis "
        "recommandes, prudence accrue"
    ),
}

DAY_TYPE_LABELS = {
    0: "Non Trend",
    1: "Normal",
    2: "Normal Variation",
    3: "Neutral",
    4: "Trend",
}


# --- Auth stub ---


def get_user_tier(authorization: str | None = None) -> str:
    """Stub auth : free si pas de header, premium sinon."""
    if not authorization:
        return "free"
    return "premium"


# --- Helpers niveaux ---


def _build_niveaux(bar: dict) -> dict:
    """Extrait les niveaux cles depuis une barre JSONL."""
    return {
        "call_wall": get_field(bar, "dist_mq_call", 0.0),
        "put_wall": get_field(bar, "dist_mq_put", 0.0),
        "hvl": get_field(bar, "dist_mq_hvl", 0.0),
        "gex_up": get_field(bar, "dist_gex_nearest_up", 0.0),
        "gex_dn": get_field(bar, "dist_gex_nearest_dn", 0.0),
        "vwap_sd1u": get_field(bar, "dist_vwap_d_sd1u", 0.0),
        "vwap_sd1d": get_field(bar, "dist_vwap_d_sd1d", 0.0),
        "prev_vpoc": get_field(bar, "dist_prev_vpoc", 0.0),
        "ib_high": get_field(bar, "dist_ib_high", 0.0),
        "ib_low": get_field(bar, "dist_ib_low", 0.0),
    }


def _vwap_triple_label(val: int) -> str:
    """Convertit vwap_triple_align en label lisible."""
    if val > 0:
        return "BULL"
    if val < 0:
        return "BEAR"
    return "NEUTRE"


def _smt_label(es_bar: dict, nq_bar: dict) -> str:
    """Detecte SMT divergence entre ES et NQ."""
    es_high = get_int_field(es_bar, "new_swing_high", 0)
    nq_high = get_int_field(nq_bar, "new_swing_high", 0)
    es_low = get_int_field(es_bar, "new_swing_low", 0)
    nq_low = get_int_field(nq_bar, "new_swing_low", 0)

    if es_high and not nq_high:
        return "BULL TRAP"
    if es_low and not nq_low:
        return "BEAR TRAP"
    if nq_high and not es_high:
        return "BULL TRAP"
    if nq_low and not es_low:
        return "BEAR TRAP"
    return "AUCUNE"


# --- Generateur principal ---


def generate_briefing(date_str: str | None = None) -> dict:
    """Genere le briefing complet pour une date donnee.

    Lit le bot status et les dernieres barres ES/NQ, construit 4 sections.
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    bot_data = read_bot_status()
    bar_es = read_last_bar("ES")
    bar_nq = read_last_bar("NQ")
    market_live = bot_data.get("market_live", {})

    # --- Section 1 : Macro ---
    vix = market_live.get("vix", get_field(bar_es, "vix_level", 0.0))
    vix_regime = market_live.get("vix_regime", "NORMAL")
    if isinstance(vix_regime, (int, float)):
        regime_map = {0: "LOW", 1: "NORMAL", 2: "HIGH"}
        vix_regime = regime_map.get(int(vix_regime), "NORMAL")

    macro = {
        "vix": round(vix, 2),
        "vix_regime": vix_regime,
        "vix_desc": VIX_REGIME_DESC.get(vix_regime, VIX_REGIME_DESC["NORMAL"]),
        "atr_es": round(market_live.get("atr_es", get_field(bar_es, "atr", 0.0)), 2),
        "atr_nq": round(market_live.get("atr_nq", get_field(bar_nq, "atr", 0.0)), 2),
        "ovn_range_es": round(get_field(bar_es, "ovn_range_ticks", 0.0), 1),
        "ovn_range_nq": round(get_field(bar_nq, "ovn_range_ticks", 0.0), 1),
        "open_gap_es": round(get_field(bar_es, "open_gap_ticks", 0.0), 1),
        "open_gap_nq": round(get_field(bar_nq, "open_gap_ticks", 0.0), 1),
    }

    # --- Section 2 : Niveaux cles ---
    niveaux_cles = {
        "ES": _build_niveaux(bar_es),
        "NQ": _build_niveaux(bar_nq),
    }

    # --- Section 3 : Biais directionnel ---
    ot_es = get_int_field(bar_es, "open_type", 0)
    ot_nq = get_int_field(bar_nq, "open_type", 0)
    dt_es = get_int_field(bar_es, "day_type", 0)
    dt_nq = get_int_field(bar_nq, "day_type", 0)
    vta_es = get_int_field(bar_es, "vwap_triple_align", 0)
    vta_nq = get_int_field(bar_nq, "vwap_triple_align", 0)

    biais = {
        "open_type_es": OPEN_TYPE_LABELS.get(ot_es, "UNKNOWN"),
        "open_type_nq": OPEN_TYPE_LABELS.get(ot_nq, "UNKNOWN"),
        "day_type_es": DAY_TYPE_LABELS.get(dt_es, "Non Trend"),
        "day_type_nq": DAY_TYPE_LABELS.get(dt_nq, "Non Trend"),
        "amd_bias_es": round(get_field(bar_es, "open_bias_conf", 0.0), 2),
        "amd_bias_nq": round(get_field(bar_nq, "open_bias_conf", 0.0), 2),
        "po3_score_es": round(get_field(bar_es, "trend_day_probability", 0.0), 2),
        "po3_score_nq": round(get_field(bar_nq, "trend_day_probability", 0.0), 2),
        "vwap_triple_es": _vwap_triple_label(vta_es),
        "vwap_triple_nq": _vwap_triple_label(vta_nq),
    }

    # --- Section 4 : Institutionnel ---
    es_dir = get_int_field(bar_es, "delta_day_dir", 0)
    nq_dir = get_int_field(bar_nq, "delta_day_dir", 0)
    cross_delta = 1 if (es_dir == nq_dir and es_dir != 0) else 0

    es_mid = get_field(bar_es, "price_vs_swing_mid", 0.0)
    nq_mid = get_field(bar_nq, "price_vs_swing_mid", 0.0)
    correlation = 1.0 if (es_mid * nq_mid > 0) else -1.0

    institutionnel = {
        "gex_clusters_es": get_int_field(bar_es, "gex_cluster_count", 0),
        "gex_clusters_nq": get_int_field(bar_nq, "gex_cluster_count", 0),
        "gex_flip_es": bool(get_int_field(bar_es, "bool_gex_flip_zone", 0)),
        "gex_flip_nq": bool(get_int_field(bar_nq, "bool_gex_flip_zone", 0)),
        "smt_divergence": _smt_label(bar_es, bar_nq),
        "cross_delta_agree": cross_delta,
        "correlation": round(correlation, 2),
        "large_trader_es": round(get_field(bar_es, "large_trader_ratio", 0.0), 4),
        "large_trader_nq": round(get_field(bar_nq, "large_trader_ratio", 0.0), 4),
    }

    briefing = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": {
            "macro": macro,
            "niveaux_cles": niveaux_cles,
            "biais": biais,
            "institutionnel": institutionnel,
        },
        "commentary": "",
        "disclaimer": (
            "Ceci est un outil d'aide a la decision, PAS un conseil en investissement. "
            "Les performances passees ne garantissent pas les resultats futurs. "
            "Le trading de futures comporte un risque de perte en capital."
        ),
    }

    # Sauvegarde sur disque
    os.makedirs(BRIEFINGS_DIR, exist_ok=True)
    filepath = os.path.join(BRIEFINGS_DIR, f"{date_str}.json")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(briefing, f, ensure_ascii=False, indent=2)
        logger.info("Briefing sauvegarde : %s", filepath)
    except OSError as exc:
        logger.error("Erreur sauvegarde briefing : %s", exc)

    return briefing


# --- Endpoints ---


@router.get("/today")
async def briefing_today(request: Request):
    """Retourne le briefing du jour. Version free = macro seul."""
    auth = request.headers.get("Authorization")
    tier = get_user_tier(auth)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Charger ou generer
    filepath = os.path.join(BRIEFINGS_DIR, f"{today}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                briefing = json.load(f)
        except (json.JSONDecodeError, OSError):
            briefing = generate_briefing(today)
    else:
        briefing = generate_briefing(today)

    # Tier free : macro partiel seulement
    if tier == "free":
        macro = briefing.get("sections", {}).get("macro", {})
        return {
            "date": briefing.get("date", today),
            "preview": True,
            "sections": {
                "macro": {
                    "vix": macro.get("vix", 0.0),
                    "vix_regime": macro.get("vix_regime", "NORMAL"),
                    "vix_desc": macro.get("vix_desc", ""),
                },
            },
            "locked_sections": ["niveaux_cles", "biais", "institutionnel"],
            "disclaimer": briefing.get("disclaimer", ""),
        }

    # Tier starter/premium : briefing complet
    return briefing


@router.get("/archive/{date_str}")
async def briefing_archive(date_str: str, request: Request):
    """Retourne un briefing archive par date (YYYY-MM-DD)."""
    auth = request.headers.get("Authorization")
    tier = get_user_tier(auth)

    if tier == "free":
        return JSONResponse(
            {"error": "Briefings archives reserves aux membres Starter+"},
            status_code=403,
        )

    filepath = os.path.join(BRIEFINGS_DIR, f"{date_str}.json")
    if not os.path.exists(filepath):
        return JSONResponse(
            {"error": f"Briefing du {date_str} non trouve"},
            status_code=404,
        )

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return JSONResponse(
            {"error": f"Erreur lecture briefing : {exc}"},
            status_code=500,
        )
