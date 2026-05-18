"""Bot 3 — Definitions des niveaux Market Profile.

Source : DOCS/LEVEL_PROB_V4_NQ.md + ES.md + DOCS/LEVEL_PROB_NQ_RTH.md (Bot 1 DMP)
Validation : 318 jours (avril 2025 - mai 2026), 356K+ barres par instrument.

3 Tiers :
  - TIER 1 : toujours actif, rejection > 58%, n > 5000
  - TIER 2 : actif avec bon contexte (rejection 50-55%)
  - TIER 3 : context-only (PF eleve mais n faible — required_context strict)

NIVEAUX BANNIS : ne PAS coder.
"""
from __future__ import annotations

# ════════════════════════════════════════════════════════════════════════
# TIER 1 — Toujours actifs (5 niveaux)
# ════════════════════════════════════════════════════════════════════════
# Critere generique : rejection > 58% ET n > 5000.
#
# Nuances explicites (Jackson 03/05) :
#   - MQ_PUT_0DTE : n=497 NQ / 343 ES (sous le seuil 5000) MAIS PF 1.80-2.00
#     et confirmation Bot 1 DMP. Tier 1 le plus fragile statistiquement.
#   - OPEN_830 et OPEN_930 : rejection 53-57% V4 all-sessions (sous 58%).
#     Justification : n massif (35K-80K) + Bot 1 DMP RTH 76.4% PF 5.00.
#     La force vient du volume de data, pas du rejection rate brut.
# ════════════════════════════════════════════════════════════════════════
TIER1: dict[str, dict] = {
    "SINGLE_PRINT": {
        "dist_col": "dist_single_print_nearest_pct",
        "proximity_pct": 0.02,          # zone serree (precision)
        "side": "REJECTION",            # rebond direction opposee au cote d'approche
        "tier": 1,
        "symbols": ["NQ", "ES"],        # baselines fortes sur les 2
        "rej_nq": 70.1, "pf_nq": 2.61, "n_nq": 26046,
        "rej_es": 69.1, "pf_es": 2.53, "n_es": 27112,
        "description": (
            "Trou de volume Market Profile = Wyckoff air pocket. "
            "Le prix revient dans le vide, personne pour le pousser, il rebondit."
        ),
    },
    "IB_LOW": {
        "dist_col": "dist_ib_low_pct",
        "proximity_pct": 0.05,
        "side": "LONG",                 # support = rebond = BUY
        "tier": 1,
        "symbols": ["NQ", "ES"],
        "rej_nq": 59.6, "pf_nq": 1.85, "n_nq": 6806,
        "rej_es": 58.9, "pf_es": 1.91, "n_es": 11827,
        "best_session": "LONDON",
        "description": (
            "Support Initial Balance. London = 66.7% rejection (meilleure)."
            "En bull ATH les dips sous IB_LOW sont rachetes par les institutions."
        ),
    },
    "MQ_PUT_0DTE": {
        "dist_col": "dist_mq_put_0dte_pct",
        "proximity_pct": 0.05,
        "side": "LONG",                 # put support = BUY
        "tier": 1,
        "symbols": ["NQ", "ES"],
        "rej_nq": 57.5, "pf_nq": 1.80, "n_nq": 497,    # Tier 1 le plus fragile (n<5K)
        "rej_es": 58.0, "pf_es": 2.00, "n_es": 343,
        "best_session_nq": "US_CASH",
        "best_session_es": "LONDON",
        "description": (
            "Options 0DTE Put wall. Gamma concentre = dealers hedgent agressivement = "
            "support intraday precis. US_CASH NQ = 74% rejection PF 4.38. "
            "n faible mais PF eleve : Tier 1 sous reserve, surveillance Phase 1."
        ),
    },
    "OPEN_830": {
        "dist_col": "dist_open_830_pct",
        "proximity_pct": 0.05,
        "side": "REJECTION",
        "tier": 1,
        "symbols": ["NQ", "ES"],
        "rej_nq": 54.3, "pf_nq": 1.12, "n_nq": 42437,    # rejection<58% mais n massif
        "rej_es": 56.7, "pf_es": 1.25, "n_es": 79646,
        "description": (
            "Open premarket 8:30 ET. Niveau respecte par les algos. "
            "Force = volume de data (35K-80K touches), pas rejection rate brut. "
            "London session = meilleure rejection (60% ES)."
        ),
    },
    "OPEN_930": {
        "dist_col": "dist_open_930_pct",
        "proximity_pct": 0.05,
        "side": "REJECTION",
        "tier": 1,
        "symbols": ["NQ", "ES"],
        "rej_nq": 53.4, "pf_nq": 1.19, "n_nq": 34646,    # idem rejection<58% n massif
        "rej_es": 56.7, "pf_es": 1.26, "n_es": 71603,
        "description": (
            "Cash open RTH. Confirme par Bot 1 DMP NQ RTH = 76.4% rejection PF 5.00 "
            "(n=212). LE setup le plus pur en RTH. V4 all-sessions dilue."
        ),
    },
}

# ════════════════════════════════════════════════════════════════════════
# TIER 2 — Actifs avec bon contexte (5 niveaux)
# ════════════════════════════════════════════════════════════════════════
TIER2: dict[str, dict] = {
    "CUR_VPOC": {
        "dist_col": "dist_cur_vpoc_pct",
        "proximity_pct": 0.03,
        "side": "REJECTION",
        "tier": 2,
        "symbols": ["ES"],              # NQ PF 0.98 = no edge → ES only
        "rej_es": 57.8, "pf_es": 1.27, "n_es": 66350,
        "description": (
            "VPOC developing du jour. ES only (NQ PF 0.98 = no edge)."
        ),
    },
    "GEX_DN": {
        "dist_col": "dist_gex_nearest_dn_pct",
        "proximity_pct": 0.05,
        "side": "LONG",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "rej_nq": 55.1, "pf_nq": 1.34, "n_nq": 2346,
        "rej_es": 54.8, "pf_es": 1.16, "n_es": 5708,
        "best_session_nq": "US_AFTER",
        "best_context": "va_dev=STABLE",
        "description": (
            "GEX down = support gamma. US_AFTER NQ = 79% PF 7.97 (n=81)."
            "va_dev=STABLE NQ = 71% PF 3.10."
        ),
    },
    "VWAP_W_SD1D": {
        "dist_col": "dist_vwap_w_sd1d_pct",
        "proximity_pct": 0.05,
        "side": "LONG",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "rej_es": 53.5, "pf_es": 1.31, "n_es": 15113,
        "rej_nq": 53.1, "pf_nq": 1.22, "n_nq": 11262,
        "description": (
            "VWAP weekly SD-1. Niveau institutionnel. "
            "Les fonds weekly rebalancent ici."
        ),
    },
    "MQ_HVL": {
        "dist_col": "dist_mq_hvl_pct",
        "proximity_pct": 0.05,
        "side": "REJECTION",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "rej_nq": 53.1, "pf_nq": 1.06, "n_nq": 1214,
        "rej_es": 54.0, "pf_es": 1.03, "n_es": 1811,
        "description": (
            "MQ HVL pivot. DMP NQ = 62.8% PF 1.74 (n=172). "
            "V4 montre baseline plus bas mais DMP confirme."
        ),
    },
    "PVAL": {
        "dist_col": "dist_prev_val_pct",
        "proximity_pct": 0.05,
        "side": "LONG",
        "tier": 2,
        "symbols": ["NQ"],              # pas de stat ES dans le doc → NQ only
        "rej_nq": 53.4, "pf_nq": 1.11, "n_nq": 15395,
        "description": (
            "Previous VAL = support de la veille. NQ only (pas de stat ES). "
            "DMP NQ RTH = 75% rejection PF 2.17 (n=24, petit)."
        ),
    },
}

# ════════════════════════════════════════════════════════════════════════
# TIER 3 — Context-only (3 niveaux) — required_context STRICT
# ════════════════════════════════════════════════════════════════════════
# PF eleve mais n faible. Trader UNIQUEMENT si required_context match.
# Sans contexte = TOUJOURS skip (anti data mining trap, n<100).
# ════════════════════════════════════════════════════════════════════════
TIER3: dict[str, dict] = {
    "CASH_HIGH_CVD_FLAT": {
        "dist_col": "dist_cash_high_pct",
        "proximity_pct": 0.05,
        "side": "SHORT",
        "tier": 3,
        "symbols": ["NQ"],              # n=74 NQ, pas de stat ES
        "required_context": {"cvd_trend": "FLAT"},
        "rej_nq": 79.7, "pf_nq": 11.26, "n_nq": 74,
        "description": (
            "Rejection cash high UNIQUEMENT quand CVD flat. NQ only. "
            "4 des top 10 setups NQ."
        ),
    },
    "TRAPPED_SELL_OD": {
        "dist_col": "dist_trapped_sellers_nearest_pct",
        "proximity_pct": 0.05,
        "side": "LONG",
        "tier": 3,
        "symbols": ["NQ"],              # n=57 NQ, pas de stat ES
        "required_context": {"open_type": 0},  # T0 = Open Drive
        "rej_nq": 87.7, "pf_nq": 13.07, "n_nq": 57,
        "description": (
            "Trapped sellers en Open Drive. NQ only. "
            "Spring Wyckoff : vendeurs pieges + OD = le prix repart fort. 88% rejection."
        ),
    },
    "MQ_CALL_POC_FLAT": {
        "dist_col": "dist_mq_call_pct",
        "proximity_pct": 0.05,
        "side": "SHORT",
        "tier": 3,
        "symbols": ["ES"],              # n=64 ES, pas de stat NQ
        "required_context": {"poc_migration_dir": 0, "position_in_range_above": 0.70},
        "rej_es": 76.6, "pf_es": 5.42, "n_es": 64,
        "description": (
            "MQ Call wall rejette quand POC stable + prix en haut du range. ES only. "
            "Range day = resistance tient. Trend day = casse."
        ),
    },
}

# ════════════════════════════════════════════════════════════════════════
# Niveaux BANNIS — ne JAMAIS trader (mais OBSERVE-only OK Phase 1)
# ════════════════════════════════════════════════════════════════════════
# Jackson 03/05 : seuls OVN_HIGH/OVN_LOW restent strictement bannis
# (bruit overnight pur). Les autres niveaux marginaux peuvent etre
# observed-only Phase 1 pour collecter rejection_rate live et decider.
# ════════════════════════════════════════════════════════════════════════
BANNED_LEVELS: dict[str, str] = {
    "OVN_HIGH":     "34-40% — bruit overnight",
    "OVN_LOW":      "34-37% — idem",
}

# ════════════════════════════════════════════════════════════════════════
# TIER 2 NEUTRAL — Niveaux ex-bannis reintegres en mode NEUTRE (Jackson 03/05)
# ════════════════════════════════════════════════════════════════════════
# Philosophie : le prix arrive au niveau, on regarde l'orderflow + la structure
# (poc_mig + va_dev), et c'est la convergence qui dit quoi faire.
# Le niveau donne le OU, l'orderflow + structure donne le QUOI.
#
# 7 scenarios de decision (cf evaluate_decision section NEUTRAL) :
#   1. Structure UP + Orderflow UP → BREAKOUT LONG
#   2. Structure DOWN + Orderflow DOWN → BREAKOUT SHORT
#   3. Structure neutre + Orderflow contre = REJECTION counter-trend
#   4. Structure faible + Orderflow CONTRE = REJECTION reversal
#   5. Structure FLAT + VA contract = RANGE day fade
#   6. Structure FORTE + VA expand = TREND day same-direction only
#   7. Rien ne converge = SKIP
#
# Ces niveaux sont activables via BOT3_ENABLE_TIER2_NEUTRAL.
# En Phase 1 OBSERVE_ONLY ils sont logges pour audit baseline_rej live.
# ════════════════════════════════════════════════════════════════════════
TIER2_LEVELS_NEUTRAL: dict[str, dict] = {
    "PVAH": {
        "dist_col": "dist_prev_vah_pct",
        "proximity_pct": 0.05,
        "side": "NEUTRAL",                 # ON NE SAIT PAS → orderflow decide
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "baseline_rej_nq": 35.0,            # rejette peu = casse souvent
        "baseline_rej_es": 46.0,
        "description": (
            "Previous VAH. Le prix arrive. "
            "Delta negatif + finish down = rejection SHORT. "
            "Delta positif + finish up + poc_mig UP = breakout LONG. "
            "Delta neutre + finish weak = SKIP."
        ),
    },
    "CUR_VAH": {
        "dist_col": "dist_cur_vah_pct",
        "proximity_pct": 0.05,
        "side": "NEUTRAL",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "baseline_rej_nq": 42.0,
        "baseline_rej_es": 52.0,
        "description": "VAH du jour. Zone de decision. Orderflow decide : rejection ou breakout.",
    },
    "MQ_CALL": {
        "dist_col": "dist_mq_call_pct",
        "proximity_pct": 0.05,
        "side": "NEUTRAL",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "baseline_rej_nq": 33.0,
        "baseline_rej_es": 48.0,
        "description": (
            "MQ Call wall. Gros niveau options. "
            "Si dealers defendent = rejection SHORT. "
            "Si gamma squeeze = breakout LONG."
        ),
    },
    "IB_HIGH": {
        "dist_col": "dist_ib_high_pct",
        "proximity_pct": 0.05,
        "side": "NEUTRAL",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "baseline_rej_nq": 40.0,
        "baseline_rej_es": 54.0,
        "note": "ES rejette mieux (54%) que NQ (40%)",
        "description": (
            "IB High. Range day = rejection. "
            "Trend day = breakout. L'orderflow tranche."
        ),
    },
    "SWING_HIGH": {
        "dist_col": "dist_last_swing_high_pct",
        "proximity_pct": 0.05,
        "side": "NEUTRAL",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "baseline_rej_nq": 47.0,
        "baseline_rej_es": 48.0,
        "description": (
            "Swing high. Structure cle. "
            "Liquidity sweep + rejection = SHORT (ICT). "
            "Vrai breakout + delta = LONG."
        ),
    },
    "VWAP_D_SD1U": {
        "dist_col": "dist_vwap_d_sd1u_pct",
        "proximity_pct": 0.05,
        "side": "NEUTRAL",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "baseline_rej_nq": 47.0,
        "baseline_rej_es": 47.0,
        "description": (
            "VWAP SD+1. Surachete modere. "
            "Mean reversion = SHORT. Trend fort = LONG."
        ),
    },
    "VWAP_D_SD2U": {
        "dist_col": "dist_vwap_d_sd2u_pct",
        "proximity_pct": 0.05,
        "side": "NEUTRAL",
        "tier": 3,                          # extreme = tier 3
        "symbols": ["NQ", "ES"],
        "baseline_rej_nq": 48.0,
        "baseline_rej_es": 46.0,
        "description": (
            "VWAP SD+2. Extreme surachete. "
            "Presque toujours mean reversion SAUF trend day explosif."
        ),
    },
    "PVWAP_SD1U": {
        "dist_col": "dist_pvwap_sd1u_pct",
        "proximity_pct": 0.05,
        "side": "NEUTRAL",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "baseline_rej_nq": 39.0,
        "baseline_rej_es": 51.0,
        "description": (
            "Previous VWAP SD+1. "
            "NQ casse 61% du temps, ES plus equilibre."
        ),
    },
}


# ════════════════════════════════════════════════════════════════════════
# SIDAK_LEVELS — Niveaux validés Sidak strict 09/05/2026 (cross-régime)
# ════════════════════════════════════════════════════════════════════════
# Audit `backtest_levels_strict.py` 6 mois Databento ES + NQ :
#   - 166 tests Sidak strict, PSR ≥ 0.9997, n>1000 par niveau
#   - Validation cross-régime (HAUSSIER/BAISSIER/RANGE) confirmée
#   - Audit MQ pollution : MQ historique PROPRE (boost MQ légitime)
#
# Architecture v2 (Voie B — Jackson 09/05) :
#   - bucket="SIDAK" → BYPASS filter regime_engine (cross-régime validé)
#   - SLTPEngine wall-aware (mia_sltp.py 941 LOC) si mur exploitable
#   - Fallback standard Bot 3 si SLTPEngine reject (sl_base × ATR, tp = sl × 1.2)
#   - timeout 30 min uniforme (cohérent héritage)
# ════════════════════════════════════════════════════════════════════════
SIDAK_LEVELS: dict[str, dict] = {
    "SIDAK_SWING_LOW": {
        "dist_col": "dist_last_swing_low_pct",
        "proximity_pct": 0.02,
        "side": "LONG",
        "tier": 1,
        "bucket": "SIDAK",
        "symbols": ["NQ", "ES"],
        "validation": "Sidak n=166, PSR 1.0000, WF 12/12 ES + 12/12 NQ, EV +4.83t ES / +3.96t NQ",
        "description": "Swing low récent — bounce LONG sur structure prix.",
    },
    "SIDAK_SWING_HIGH": {
        "dist_col": "dist_last_swing_high_pct",
        "proximity_pct": 0.02,
        "side": "SHORT",
        "tier": 1,
        "bucket": "SIDAK",
        "symbols": ["NQ", "ES"],
        "validation": "Sidak n=166, PSR 1.0000, WF 11/12 ES + 11/12 NQ, EV +4.11t ES / +3.35t NQ",
        "description": "Swing high récent — rejet SHORT sur structure prix.",
    },
    "SIDAK_COLOR_UP_zone": {
        "dist_col": "dist_color_up_nearest_pct",
        "proximity_pct": 0.02,
        "side": "LONG",
        "tier": 1,
        "bucket": "SIDAK",
        "symbols": ["NQ", "ES"],
        "validation": "Sidak n=166, PSR 1.0000, WF 12/12 ES + 12/12 NQ, EV +2.83t ES / +3.55t NQ",
        "description": "Retouche zone COLOR_UP active (extension lines BN) — bounce LONG.",
    },
    "SIDAK_COLOR_DN_zone": {
        "dist_col": "dist_color_dn_nearest_pct",
        "proximity_pct": 0.02,
        "side": "SHORT",
        "tier": 1,
        "bucket": "SIDAK",
        "symbols": ["NQ", "ES"],
        "validation": "Sidak n=166, PSR 1.0000, WF 11/12 ES + 12/12 NQ, EV +3.25t ES / +4.28t NQ",
        "description": "Retouche zone COLOR_DN active (extension lines BN) — rejet SHORT.",
    },
}


# ════════════════════════════════════════════════════════════════════════
# COMBOS_BOOSTED — Combos haute conviction (Priority 1 dans Bot 3 v2)
# ════════════════════════════════════════════════════════════════════════
# Validation : `boost_marginal_combos.py` 09/05/2026 — combos MARGINAL boostés
# par feature additionnelle trader-driven.
#
# Format : touche simultanée de 2 niveaux (cols) + filter contextuel.
# Quand tous critères remplis → priority 1 (avant Sidak simples + héritage).
# bucket="COMBO_BOOSTED" → BYPASS filter regime + SLTPEngine wall-aware.
# ════════════════════════════════════════════════════════════════════════
COMBOS_BOOSTED: dict[str, dict] = {
    "COMBO_LONG_UP_x_SWING_LOW_room1dmax": {
        "side": "LONG",
        "applies_to": "ES",                     # ES uniquement (NQ a aggr_buy)
        "cols": ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"],
        "proximity_pct": 0.02,
        "filter_col": "dist_1d_max_ticks_pct",
        "filter_op": ">",
        "filter_thr": 0.30,
        "tier": 1,
        "bucket": "COMBO_BOOSTED",
        "validation": "n=79, EV +4.53t, PF 1.69, WF 11/12, PSR 0.988 (audit 09/05)",
        "description": (
            "Sniper haute conviction LONG ES : retouche LONG_UP zone + SWING_LOW "
            "support + room >100t vers 1d_max MQ (objectif TP non plafonné). "
            "Setup rare (~1 fois / 1.2 mois) mais expectancy room valide."
        ),
    },
    "COMBO_LONG_UP_x_SWING_LOW_aggrbuy": {
        "side": "LONG",
        "applies_to": "NQ",
        "cols": ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"],
        "proximity_pct": 0.02,
        "filter_col": "aggressor_imbalance",
        "filter_op": ">",
        "filter_thr": 0.30,
        "tier": 1,
        "bucket": "COMBO_BOOSTED",
        "validation": "n=217, EV +3.08t, PF 1.41, WF 10/12, PSR 0.994 (audit 09/05)",
        "description": (
            "Sniper haute conviction LONG NQ : retouche LONG_UP + SWING_LOW + "
            "aggressor flux acheteur dominant (>0.30) à l'instant — confirme "
            "le rebond imminent."
        ),
    },
    "COMBO_LONG_DN_x_COLOR_DN": {
        "side": "SHORT",
        "applies_to": "NQ",                     # NQ uniquement (ES = NOGO)
        "cols": ["dist_long_dn_nearest_pct", "dist_color_dn_nearest_pct"],
        "proximity_pct": 0.02,
        "filter_col": None,                     # pas de filter additionnel
        "filter_op": None,
        "filter_thr": None,
        "tier": 1,
        "bucket": "COMBO_BOOSTED",
        "validation": "n=1222, EV +2.68t, PF 1.35, WF 10/12, PSR 1.000 (audit 09/05)",
        "description": (
            "Cluster BN double SHORT NQ : retouche LONG_DN zone + COLOR_DN zone "
            "simultanées = résistance multi-couches BN forte."
        ),
    },
}


def get_sidak_levels(symbol: str | None = None) -> dict[str, dict]:
    """Retourne SIDAK_LEVELS filtrés par symbole."""
    if symbol is None:
        return dict(SIDAK_LEVELS)
    return {
        name: defn for name, defn in SIDAK_LEVELS.items()
        if symbol in defn.get("symbols", ["NQ", "ES"])
    }


def get_combos_boosted(symbol: str | None = None) -> dict[str, dict]:
    """Retourne COMBOS_BOOSTED filtrés par symbole (applies_to ES/NQ/BOTH)."""
    if symbol is None:
        return dict(COMBOS_BOOSTED)
    return {
        name: defn for name, defn in COMBOS_BOOSTED.items()
        if defn.get("applies_to", "BOTH") in (symbol, "BOTH")
    }


def is_sidak_level(level_name: str) -> bool:
    """True si le niveau est dans SIDAK_LEVELS (bucket=SIDAK, bypass filter)."""
    return level_name in SIDAK_LEVELS


def is_combo_boosted(level_name: str) -> bool:
    """True si le niveau est dans COMBOS_BOOSTED (priority 1, bypass filter)."""
    return level_name in COMBOS_BOOSTED


def is_bucket_bypass_filter(level_name: str) -> bool:
    """True si bucket SIDAK ou COMBO_BOOSTED (bypass filter regime)."""
    return is_sidak_level(level_name) or is_combo_boosted(level_name)


def get_active_levels(
    enable_tier2: bool,
    enable_tier3: bool,
    symbol: str | None = None,
    enable_tier2_neutral: bool = False,
    enable_sidak: bool = True,
    enable_combos_boosted: bool = True,
) -> dict[str, dict]:
    """Retourne dict des niveaux actifs selon les phase flags + symbole.

    Args:
        enable_tier2 : active Tier 2 (tradable, side fixe)
        enable_tier3 : active Tier 3 (tradable, required_context strict)
        symbol : si fourni, filtre les niveaux selon le champ `symbols`
                 (anti CUR_VPOC NQ PF 0.98).
        enable_tier2_neutral : active TIER2_LEVELS_NEUTRAL (8 niveaux ex-bannis
                               reintegres en mode NEUTRAL — orderflow + structure
                               decide le side via 7 scenarios). En Phase 1 OBSERVE_ONLY
                               on les active aussi pour log baseline_rej live.
    """
    candidates = dict(TIER1)
    if enable_tier2:
        candidates.update(TIER2)
    if enable_tier3:
        candidates.update(TIER3)
    if enable_tier2_neutral:
        candidates.update(TIER2_LEVELS_NEUTRAL)
    if enable_sidak:
        candidates.update(SIDAK_LEVELS)
    # COMBOS_BOOSTED = check séparé dans bot3_mp_engine (priority 1)
    # pas inclus ici car structure différente (cols multiples + filter)
    if symbol is None:
        return candidates
    return {
        name: defn
        for name, defn in candidates.items()
        if symbol in defn.get("symbols", ["NQ", "ES"])
    }


def is_neutral_level(level_name: str) -> bool:
    """True si le niveau est en mode NEUTRAL (side decide par orderflow + structure)."""
    return level_name in TIER2_LEVELS_NEUTRAL


def get_level_baseline_rej(level_name: str, symbol: str) -> float | None:
    """Retourne la rejection_rate baseline du niveau pour le symbole."""
    for tier in (TIER1, TIER2, TIER3):
        if level_name in tier:
            level = tier[level_name]
            key = "rej_nq" if symbol == "NQ" else "rej_es"
            return level.get(key)
    return None


def get_level_baseline_pf(level_name: str, symbol: str) -> float | None:
    """Retourne la PF baseline du niveau pour le symbole."""
    for tier in (TIER1, TIER2, TIER3):
        if level_name in tier:
            level = tier[level_name]
            key = "pf_nq" if symbol == "NQ" else "pf_es"
            return level.get(key)
    return None


def is_banned(level_name: str) -> bool:
    return level_name in BANNED_LEVELS


def level_supports_symbol(level_name: str, symbol: str) -> bool:
    """Verifie qu'un niveau autorise le symbole (filtre CUR_VPOC NQ etc.)."""
    for tier in (TIER1, TIER2, TIER3):
        if level_name in tier:
            return symbol in tier[level_name].get("symbols", ["NQ", "ES"])
    return False


# ════════════════════════════════════════════════════════════════════════
# PHASE 4 — Symetrie LONG/SHORT mirror levels (Bot 3 v2 narrative)
# ════════════════════════════════════════════════════════════════════════
# Master plan sect 281 (DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md) :
# "Symetrie LONG/SHORT : ajouter MQ_CALL_0DTE SHORT mirror, IB_HIGH SHORT,
# GEX_UP SHORT, VWAP_W_SD1U SHORT, PVAH SHORT"
#
# Justification : Bot 3 v1 a 80% LONG par biais structurel (15+ levels LONG vs
# 0-3 SHORT explicites). DirectionResolver narrative bidirectionnel doit avoir
# acces a mirror levels SHORT explicites pour scenarios S02/S04/S06/S08/S09.
#
# Ces 5 mirror SHORT sont des candidats Phase 4 DirectionResolver. Phase 5
# walk-forward DSR validera empiriquement (n >= 100 par level).
# Backwards-compat : TIER1/2/3 + TIER2_NEUTRAL inchanges (pas de regression Bot 3 v1).
# ════════════════════════════════════════════════════════════════════════
MIRROR_SHORT_TIER1: dict[str, dict] = {
    "MQ_CALL_0DTE": {
        "dist_col": "dist_mq_call_0dte_pct",
        "proximity_pct": 0.05,
        "side": "SHORT",
        "tier": 1,
        "symbols": ["NQ", "ES"],
        "description": (
            "Mirror SHORT de MQ_PUT_0DTE. Options 0DTE Call wall = gamma "
            "concentre dealers hedgent = resistance intraday precise. "
            "Bot 3 v2 narrative DirectionResolver scenario S02 (OD_DOWN) + S09 "
            "(EXHAUSTION_TOP). Empirique paper Phase 4+5 obligatoire avant prod."
        ),
        "_mirror_of": "MQ_PUT_0DTE",
    },
    "IB_HIGH_SHORT": {
        "dist_col": "dist_ib_high_pct",
        "proximity_pct": 0.05,
        "side": "SHORT",
        "tier": 1,
        "symbols": ["NQ", "ES"],
        "description": (
            "Mirror SHORT de IB_LOW. Resistance Initial Balance. "
            "Bot 3 v2 narrative scenarios S04 (TREND_DOWN) + S08 (RANGE_RESPECTED). "
            "Distinct de IB_HIGH TIER2_NEUTRAL (side=NEUTRAL orderflow-decide) :"
            " ce mirror est SIDE explicit pour DirectionResolver."
        ),
        "_mirror_of": "IB_LOW",
    },
    "GEX_UP": {
        "dist_col": "dist_gex_nearest_up_pct",
        "proximity_pct": 0.05,
        "side": "SHORT",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "description": (
            "Mirror SHORT de GEX_DN. GEX up = resistance gamma. "
            "Empirique Phase 5 walk-forward N>=100 obligatoire (Bot 3 v1 n'avait "
            "pas ce level, donc baseline rejection inconnue)."
        ),
        "_mirror_of": "GEX_DN",
    },
    "VWAP_W_SD1U": {
        "dist_col": "dist_vwap_w_sd1u_pct",
        "proximity_pct": 0.05,
        "side": "SHORT",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "description": (
            "Mirror SHORT de VWAP_W_SD1D. VWAP weekly SD+1 = resistance "
            "institutionnelle weekly rebalance side high."
        ),
        "_mirror_of": "VWAP_W_SD1D",
    },
    "PVAH_SHORT": {
        "dist_col": "dist_prev_vah_pct",
        "proximity_pct": 0.05,
        "side": "SHORT",
        "tier": 2,
        "symbols": ["NQ", "ES"],
        "description": (
            "Mirror SHORT de PVAL. Previous VAH = resistance veille. "
            "Distinct de PVAH TIER2_NEUTRAL : ce mirror est SIDE explicit "
            "(consumer DirectionResolver scenarios S04+S08)."
        ),
        "_mirror_of": "PVAL",
    },
}


# ════════════════════════════════════════════════════════════════════════
# PHASE 4 — `nature` PARALLELE de `side` (consumer DirectionResolver)
# ════════════════════════════════════════════════════════════════════════
# Master plan sect 187 (DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md):
# "Ajout clé `nature=` (support/resistance/structural) EN PARALLELE de `side=`.
# NE PAS supprimer `side`."
#
# Mapping canon Bot 3 v1 legacy_side → Bot 3 v2 nature pour DirectionResolver :
#   - LONG       → support     (level ou rebond LONG attendu)
#   - SHORT      → resistance  (level ou rebond SHORT attendu)
#   - REJECTION  → structural  (rebond bilateral selon cote d'approche)
#   - NEUTRAL    → structural  (orderflow decide direction, level = magnet/pivot)
#
# Implementation : helper `derive_nature_from_side()` + lookup `get_level_nature()`.
# Approche DRY (vs 30+ entries explicit edits) car :
#   1. Mapping deterministe legacy_side → nature (zero ambiguite)
#   2. Phase 5+ ajouts levels auto-mappes sans modification
#   3. Override possible via `_LEVEL_NATURE_OVERRIDES` si exception canon
# ════════════════════════════════════════════════════════════════════════

# Type alias pour clarte (Phase 5+ pourra migrer en Enum strict)
LevelNature = str  # "support" / "resistance" / "structural"

# Override explicite pour levels avec semantique nature ≠ derivation auto.
# Exemple : niveaux structural-only sans direction biais (VPOC, naked POC).
_LEVEL_NATURE_OVERRIDES: dict[str, LevelNature] = {
    # SINGLE_PRINT est REJECTION bilaterale = magnet/air pocket Wyckoff
    # Mais semantiquement c'est structural (trou de volume = pas un support/resistance)
    "SINGLE_PRINT": "structural",
    # VPOC = developing point of control = magnet structural pur
    "CUR_VPOC": "structural",
    # HVL = High Volume Level = pivot structural bilateral
    "MQ_HVL": "structural",
    # OPEN_830 / OPEN_930 = niveaux temporels (open premarket/cash) = structural
    # (Pas un support OU resistance, c'est un PIVOT temporel)
    "OPEN_830": "structural",
    "OPEN_930": "structural",
}


def derive_nature_from_side(side: str) -> LevelNature:
    """Map legacy_side → nature (Phase 4 mapping canon).

    Args:
        side : "LONG" / "SHORT" / "REJECTION" / "NEUTRAL" (legacy Bot 3 v1)

    Returns:
        nature : "support" / "resistance" / "structural"

    Raises:
        ValueError si side inconnu (fail-loud anti silent fallback)
    """
    side_upper = side.upper() if isinstance(side, str) else ""
    if side_upper == "LONG":
        return "support"
    if side_upper == "SHORT":
        return "resistance"
    if side_upper in ("REJECTION", "NEUTRAL"):
        return "structural"
    raise ValueError(
        f"derive_nature_from_side: side inconnu '{side}'. "
        f"Attendu : LONG / SHORT / REJECTION / NEUTRAL."
    )


def get_level_nature(level_name: str) -> LevelNature | None:
    """Lookup nature pour un level_name.

    Priority:
        1. `_LEVEL_NATURE_OVERRIDES` (exception canon explicite)
        2. `derive_nature_from_side(level_def['side'])` (mapping auto)
        3. None si level_name inconnu (caller decide)

    Args:
        level_name : ex "IB_LOW", "MQ_CALL_0DTE", "VPOC"

    Returns:
        LevelNature ou None si level_name pas dans TIER1/TIER2/TIER3/TIER2_NEUTRAL/
        SIDAK/COMBOS.
    """
    # 1. Override explicit
    if level_name in _LEVEL_NATURE_OVERRIDES:
        return _LEVEL_NATURE_OVERRIDES[level_name]

    # 2. Lookup dans tous les tiers (incl TIER2_NEUTRAL + SIDAK + COMBOS + MIRROR Phase 4)
    for tier_dict in (TIER1, TIER2, TIER3, TIER2_LEVELS_NEUTRAL,
                      SIDAK_LEVELS, COMBOS_BOOSTED, MIRROR_SHORT_TIER1):
        if level_name in tier_dict:
            side = tier_dict[level_name].get("side")
            if side is None:
                return None
            try:
                return derive_nature_from_side(side)
            except ValueError:
                return None

    # 3. Pas trouve
    return None
