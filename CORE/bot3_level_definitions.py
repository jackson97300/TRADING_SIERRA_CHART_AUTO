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
# 04/06/2026 — BLACKLIST validee par audit backtest 33j Bot 3 MP (Jackson).
# ════════════════════════════════════════════════════════════════════════
# Process : audit profondeur 5 pires jours MP (cumul -$12,778 = 80% pertes
# 33j) -> denominateur commun = 2 levels totalement absents des 5 meilleurs
# jours mais presents 12 fois dans les 5 pires. Backtest valide sur 127
# trades MP reels (hors recovered) sur 33j :
#   - MQ_HVL : 9 trades, WR 11.1%, PF 0.06, PnL -$4500.62
#   - MQ_CALL_POC_FLAT : 5 trades, WR 0.0%, PF 0.00, PnL -$5784.38
# Cumul blacklist : 14 trades (11% du total), WR 7.1%, PnL -$10,285.
# Bot 3 MP baseline -$4,311 -> avec blacklist +$5,974 (Delta +$10,285).
# Walk-forward : MAI +$7,618 / JUIN +$2,668 (les 2 mois positifs).
# Edge concept : HVL = niveau de consolidation institutionnelle (mauvais
# pour dip strategy), POC_FLAT = pas de structure (pas d'edge).
# Activation controlee par BOT3_MP_LEVEL_BLACKLIST_ENABLED (bot3_config).
# ════════════════════════════════════════════════════════════════════════
BACKTEST_BLACKLIST_MP: dict[str, str] = {
    "MQ_HVL":           "9t/WR 11%/-$4500 33j (Bot 3 MP)",
    "MQ_CALL_POC_FLAT": "5t/WR 0%/-$5784 33j (Bot 3 MP)",
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
    "COMBO_PVAH_x_COLOR_DN_ES": {
        "side": "SHORT",
        "applies_to": "ES",                     # ES uniquement (NQ pas testé)
        "cols": ["dist_prev_vah_pct", "dist_color_dn_nearest_pct"],
        "proximity_pct": 0.05,                  # large (Volume Profile + BN extension lines)
        "filter_col": None,
        "filter_op": None,
        "filter_thr": None,
        "tier": 1,
        "bucket": "COMBO_BOOSTED",
        "validation": (
            "n=135, EV +2.96t (estimé via cluster_3plus signature), PF 1.33, "
            "PSR 0.940, WF 10/12 (backtest 03/06 ES 2025-12 -> 2026-05-15 US RTH only, "
            "TP/SL 10t/10t, costs 2t). CI95 rejection [60-73%]. Concentration top fold sain."
        ),
        "description": (
            "Cluster SHORT ES : touche Previous VAH (Volume Profile veille) + "
            "COLOR_DN zone BN proches simultanément. Setup résistance multi-couches : "
            "support veille rejetté = vendeurs prennent la main + COLOR_DN confirme "
            "orderflow bearish. Validé Lopez PSR 0.940. ES uniquement (NQ non testé)."
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
    enable_mirror_observe: bool = False,
    enable_mp_blacklist: bool = True,
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
        enable_mirror_observe : active MIRROR_SHORT_OBSERVE (P1 fix code-reviewer
                                review re-review Phase 4abc). Default False (jusqu'a
                                Phase 5 walk-forward DSR validated). Wire requis
                                cf bot3_config.BOT3_ENABLE_MIRROR_SHORT_OBSERVE.
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
    # P1 fix re-review code-reviewer 18/05 : MIRROR_SHORT_OBSERVE wire flag.
    # Sans ce wire, BOT3_ENABLE_MIRROR_SHORT_OBSERVE est mort architecturalement.
    if enable_mirror_observe:
        candidates.update(MIRROR_SHORT_OBSERVE)
    # 04/06/2026 — BACKTEST_BLACKLIST_MP (Jackson) : filtrer levels backtest
    # invalides AVANT le filtre symbol pour assurer skip multi-symbol.
    if enable_mp_blacklist:
        for blk in BACKTEST_BLACKLIST_MP:
            candidates.pop(blk, None)
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
    """Verifie qu'un niveau autorise le symbole (filtre CUR_VPOC NQ etc.).

    Bug 12 fix code-reviewer 18/05 PM : itere _ALL_LEVEL_DICTS (incl
    TIER2_NEUTRAL + SIDAK + COMBOS + MIRROR) au lieu de hardcoded (TIER1,
    TIER2, TIER3). Sinon API asymetrique vs get_level_nature qui lookup partout.
    """
    for tier_dict in _ALL_LEVEL_DICTS:
        if level_name in tier_dict:
            return symbol in tier_dict[level_name].get("symbols", ["NQ", "ES"])
    return False


# ════════════════════════════════════════════════════════════════════════
# PHASE 4 — Mirror SHORT levels OBSERVE-ONLY (Bot 3 v2 narrative)
# ════════════════════════════════════════════════════════════════════════
# Post-review market-analyst + code-reviewer ULTRATHINK 18/05 PM :
# Verdict initial NOGO (4 bugs critiques + 8 importants). Refactor complet :
#
# SUPPRIMES (3 levels)  :
# - MQ_CALL_0DTE : asymetrie empirique CALL wall vs PUT wall refute mirror
#   (MQ_CALL baseline_rej_nq=33% vs MQ_PUT_0DTE rej_nq=57.5%, 24 points ecart
#   documente ligne 282 du module). Pruden Ch.7 : "asymetrie offre/demande
#   long terme reflete biais structurel". Symetrie mecanique = wishful thinking.
# - IB_HIGH_SHORT : doublon physique avec IB_HIGH TIER2_NEUTRAL (meme dist_col
#   = dist_ib_high_pct). Risque double-fire mp_engine.
# - PVAH_SHORT : doublon physique avec PVAH TIER2_NEUTRAL (meme dist_col).
#
# GARDES (2 levels) tier=3 OBSERVE-ONLY :
# - GEX_UP : gamma flip, asymetrie limitee (dealers hedgent symetrique au-dessus
#   et en-dessous strike). Mirror de GEX_DN OK car gamma = pure structural.
# - VWAP_W_SD1U : vrai mirror bilateral institutionnel weekly rebalancing.
#   Banques re-equilibrent positions a VWAP_W_SD1U comme a VWAP_W_SD1D.
#
# CONTRAT : tier=3 + required_context phase_5_dsr_validated. Pas live consume
# avant Phase 5 walk-forward DSR Lopez N>=100. Flag separe :
#   BOT3_ENABLE_MIRROR_SHORT_OBSERVE (default False).
#
# Backwards-compat : TIER1/2/3 + TIER2_NEUTRAL inchanges. Levels NEUTRAL pour
# IB_HIGH / PVAH / MQ_CALL gardes intacts (orderflow decide direction via
# logique 7 scenarios existante dans bot3_decision_engine).
# ════════════════════════════════════════════════════════════════════════
MIRROR_SHORT_OBSERVE: dict[str, dict] = {
    "GEX_UP": {
        "dist_col": "dist_gex_nearest_up_pct",
        "proximity_pct": 0.05,
        "side": "SHORT",
        "tier": 3,                          # observe-only jusqu'a Phase 5 DSR
        "symbols": ["NQ", "ES"],
        "required_context": {"phase_5_dsr_validated": True},  # gate explicit
        "description": (
            "Mirror SHORT de GEX_DN. GEX up = resistance gamma. "
            "Gamma flip = symetrique structural (dealers hedgent les 2 cotes "
            "strike). OBSERVE-ONLY tier=3 jusqu'a Phase 5 walk-forward "
            "N>=100 DSR Lopez >=0.95."
        ),
        "_mirror_of": "GEX_DN",
    },
    "VWAP_W_SD1U": {
        "dist_col": "dist_vwap_w_sd1u_pct",
        "proximity_pct": 0.05,
        "side": "SHORT",
        "tier": 3,                          # observe-only
        "symbols": ["NQ", "ES"],
        "required_context": {"phase_5_dsr_validated": True},
        "description": (
            "Mirror SHORT de VWAP_W_SD1D. VWAP weekly SD+1 = vrai mirror "
            "institutionnel bilateral (weekly rebalancing symetrique). "
            "OBSERVE-ONLY tier=3 jusqu'a Phase 5 walk-forward."
        ),
        "_mirror_of": "VWAP_W_SD1D",
    },
}


# ════════════════════════════════════════════════════════════════════════
# PHASE 4 — `nature` PARALLELE de `side` (consumer DirectionResolver)
# ════════════════════════════════════════════════════════════════════════
# Post-review market-analyst + code-reviewer ULTRATHINK 18/05 PM.
# Master plan sect 187 (DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md):
# "Ajout clé `nature=` EN PARALLELE de `side=`. NE PAS supprimer `side`."
#
# Mapping canon (Bug 10 fix : NEUTRAL → None, pas structural mort) :
#   - LONG       → "support"     (level ou rebond LONG attendu)
#   - SHORT      → "resistance"  (level ou rebond SHORT attendu)
#   - REJECTION  → "structural"  (rebond bilateral selon cote d'approche)
#   - NEUTRAL    → None          (orderflow decide via 7 scenarios legacy
#                                  bot3_decision_engine, PAS DirectionResolver)
#
# Bug 7 fix code-reviewer : typing.Literal strict (vs str alias floue).
# Bug 6 fix : pre-computed cache `_LEVEL_NATURE_CACHE` au load module (O(1) lookup).
# Bug 12 fix : `_ALL_LEVEL_DICTS` central tuple (consume par helpers).
# ════════════════════════════════════════════════════════════════════════
from typing import Literal

# Bug 7 fix : Literal strict pour mypy + IDE autocomplete.
LevelNature = Literal["support", "resistance", "structural"]

# Bug 12 fix : _ALL_LEVEL_DICTS central tuple. Consume par level_supports_symbol,
# get_level_nature, et helpers futurs Phase 4d+. DRY centralisation.
# Order : TIER1 > TIER2 > TIER3 > TIER2_NEUTRAL > SIDAK > COMBOS > MIRROR (priority lookup).
_ALL_LEVEL_DICTS: tuple = (
    TIER1, TIER2, TIER3, TIER2_LEVELS_NEUTRAL,
    SIDAK_LEVELS, COMBOS_BOOSTED, MIRROR_SHORT_OBSERVE,
)

# Bug 10 fix : OVERRIDES MINIMAL (post review : 5 entries originales etaient
# REDONDANTES avec derive auto REJECTION→structural). Garde dict vide comme
# placeholder pour exceptions canon futures Phase 5+.
# Documentation : "Currently empty. All 5 prior overrides (SINGLE_PRINT,
# CUR_VPOC, MQ_HVL, OPEN_830, OPEN_930) verified redundant 18/05 (side=REJECTION
# auto-derive → structural). Reserved for future levels where nature != derive(side)."
_LEVEL_NATURE_OVERRIDES: dict[str, LevelNature] = {}


def derive_nature_from_side(side: str) -> LevelNature | None:
    """Map legacy_side → nature (Phase 4 mapping canon, Bug 10 fix).

    Args:
        side : "LONG" / "SHORT" / "REJECTION" / "NEUTRAL" (legacy Bot 3 v1)

    Returns:
        nature : "support" / "resistance" / "structural" OR None pour NEUTRAL.
        Bug 10 fix : NEUTRAL retourne None (orderflow decide via 7 scenarios
        legacy bot3_decision_engine, PAS DirectionResolver Phase 3).

    Raises:
        ValueError si side inconnu hors LONG/SHORT/REJECTION/NEUTRAL.
    """
    if not isinstance(side, str):
        raise ValueError(f"derive_nature_from_side: side type invalide '{type(side)}'")
    side_upper = side.upper()
    if side_upper == "LONG":
        return "support"
    if side_upper == "SHORT":
        return "resistance"
    if side_upper == "REJECTION":
        return "structural"
    if side_upper == "NEUTRAL":
        # Bug 10 fix : NEUTRAL = orderflow decide via 7 scenarios legacy.
        # PAS de nature DirectionResolver (sinon castrate 8 TIER2_NEUTRAL levels).
        return None
    raise ValueError(
        f"derive_nature_from_side: side inconnu '{side}'. "
        f"Attendu : LONG / SHORT / REJECTION / NEUTRAL."
    )


def _build_level_nature_cache() -> dict[str, LevelNature]:
    """Bug 6 fix : pre-compute nature mapping au load module (O(1) lookup).

    Itere _ALL_LEVEL_DICTS + applique override + derive. NEUTRAL levels SKIPPES
    (retourne None = pas dans cache). Caller doit lookup explicitement is_neutral_level()
    pour route legacy 7 scenarios.
    """
    cache: dict[str, LevelNature] = {}
    for tier_dict in _ALL_LEVEL_DICTS:
        for level_name, level_def in tier_dict.items():
            # Override has priority
            if level_name in _LEVEL_NATURE_OVERRIDES:
                cache[level_name] = _LEVEL_NATURE_OVERRIDES[level_name]
                continue
            side = level_def.get("side")
            if not isinstance(side, str):
                continue
            try:
                nature = derive_nature_from_side(side)
            except ValueError:
                continue
            if nature is not None:  # NEUTRAL retourne None, skip cache
                cache[level_name] = nature
    return cache


# Bug 6 fix : built at module load. Re-build only on hot-reload (rare).
_LEVEL_NATURE_CACHE: dict[str, LevelNature] = _build_level_nature_cache()


def get_level_nature(level_name: str) -> LevelNature | None:
    """Lookup nature pour un level_name (Bug 6 cache O(1)).

    Returns:
        LevelNature support/resistance/structural si level_name dans
        _ALL_LEVEL_DICTS avec side != NEUTRAL.
        None si :
        - level_name inconnu (pas dans aucun tier)
        - level_name a side=NEUTRAL (Bug 10 fix : route legacy 7 scenarios)

    Args:
        level_name : ex "IB_LOW", "MQ_CALL_0DTE", "VPOC"
    """
    return _LEVEL_NATURE_CACHE.get(level_name)
