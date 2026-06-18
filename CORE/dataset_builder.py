"""
DatasetBuilder — MIA Trading System  v2
=========================================
Construit le dataset pret pour LightGBM a partir des fichiers JSONL + labels
+ features derivees (rolling, intermarket, AMD, RVOL).

Pipeline :
    JSONL (DMP 262 colonnes)
        + ib_recalc.py           → fix IB footprint
        + rolling_features.py    → 39 ctx_*
        + intermarket_features.py → 10 im_*
        + mia_amd.py             → 18 amd_*
        + rvol.py                → 10 rvol_*
        + mia_menthorq_reader.py → 37 mq_* (features macro MenthorQ)
        + labels.parquet (valid_bar=True)
        → merge on ts
        → Spearman screening (|rho| >= 0.02)
        → nettoyage + imputation
        → output parquet

Walk-forward validation :
    Toujours chronologique, jamais de split aleatoire.

Auteur : MIA Trading System
Date   : 2026-03-29 (v2 — DMP + derived features, pipeline complet)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

# Ajouter CORE au path pour les imports locaux
sys.path.insert(0, str(Path(__file__).parent))


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 SAVE-OR-DROP (13/04/2026) — Nettoyage des 57 red flags
# ═══════════════════════════════════════════════════════════════════════════════
#
# Implemente le plan valide par l'agent code-reviewer.
# Regle souveraine V2 : qualite donnees > symetrie ES/NQ > screening Spearman.
#
# CATEGORIES :
#   A) NORMALIZE /atr : 26 features converties en _atr (via TO_NORMALIZE)
#   B) DROP cat B : 4 features remplacees par versions _atr deja en C++
#   C) DROP permanents : 12 features META/absolus/mortes
#   D) DROP temporaires : 28 big_*/cluster_* (reinject apres 3+ jours 3.7.3)
#   E) FIX Python : ctx_poor_high + bool_near_level dans rolling_features.py
#
# Total : 57 red flags → 0 red flag attendu apres regeneration.
# Dataset final estime : ~85-90 features propres (vs 129 polluees avant).

TICK_SIZE = 0.25  # ES et NQ

# Features stockees en POINTS (decimales) dans le JSONL C++, pas en ticks.
# Important : ATR est en TICKS dans le JSONL → il faut convertir POINTS → TICKS
# avant la division, sinon ratio 4x plus petit (bug).
POINTS_FEATURES = {
    "dist_vwap_d", "dist_vwap_d_sd1d", "dist_cur_vwap_vp",
    # dist_vwap_m est drop (dist_vwap_m_atr existe en C++)
}

# Features a normaliser par ATR (Phase 1 + extension Option B 13/04)
# Apres suppression du screening Spearman, beaucoup plus de features ticks/points
# sont exposees et doivent etre normalisees. Note : bool_near_level et
# ctx_poor_high sont fixes dans rolling_features.py.
TO_NORMALIZE = [
    # ── Priorite 1 (top V1) ──
    "dist_swing_high", "swing_range_ticks",
    "dist_ib_high", "dist_sess_high", "next_wall_dist_ticks",
    "dist_cur_vpoc", "poc_separation_ticks",
    # ── Priorite 2 (Phase 1 initiale) ──
    "dist_comp_20d_vah", "dist_comp_50d_vah",
    "dist_cur_val", "dist_cur_vwap_vp",   # POINTS
    "dist_vwap_d_sd1d",                    # POINTS
    "dist_gex_nearest_up",
    "dist_session_hvn_above", "dist_session_lvn_above",
    "dist_mq_call_0dte", "dist_mq_put",
    "dist_ext_edge_buy", "dist_ext_long_up",
    "mq_dist_1d_max", "mq_dist_1d_min",
    "amd_asia_range_ticks", "amd_sweep_depth_ticks",
    "ovn_range_ticks", "ctx_va_width", "poc_bar_dist",
    # ── Phase 1 extension Option B (Lopez no-Spearman) ──
    # Note : avg_*_size (volume en lots) droppes dans PROHIBITED (pas normalisables par atr)
    "dist_1d_max_ticks", "dist_1d_min_ticks",
    "dist_blind_nearest_up",
    "dist_comp_20d_val", "dist_comp_20d_vpoc", "dist_comp_20d_vwap",
    "dist_comp_50d_val", "dist_comp_50d_vpoc", "dist_comp_50d_vwap",
    "dist_cur_vah",
    "dist_ib_low",
    "dist_mq_call", "dist_mq_hvl", "dist_mq_put_0dte",
    "dist_open_830", "dist_open_cash",
    "dist_ovn_high", "dist_ovn_low",
    "dist_prev_vah", "dist_prev_val", "dist_prev_vpoc", "dist_prev_vwap",
    "dist_prev_vwap_sd1d", "dist_prev_vwap_sd1u",
    "dist_session_lvn_below",
    "dist_vwap_d_sd1u", "dist_vwap_d_sd2u", "dist_vwap_d_sd3u",
    "dist_vwap_w",
    "mq_dist_call_res", "mq_dist_hvl",
    "mq_dist_call_0dte", "mq_dist_put_0dte",
    "open_gap_ticks",
    "range_size_ticks", "sess_range_ticks",
    "dist_ext_edge_sell", "dist_ext_long_dn",
    # ── Note 18/04/2026 : dist_sess_low, dist_swing_low, dist_vwap_d_sd2d ──
    # Ces 3 features ont un ratio ES/NQ pur (NQ ~4x ES) qui devrait normalement
    # les qualifier pour /atr. MAIS les primary_models (CORE/primary_models/*.py)
    # les utilisent en POINTS BRUTS comme parametres (proximity_pts, range_edge_pts).
    # Compromise : on GARDE les versions brutes + exemption quality_validator
    # (NATURALLY_DIFFERENT + PRICE_LEVEL_EXEMPT set).
    # Reviewer TODO : refactor primary_models pour utiliser _atr versions proprement.
]

# Features WHITELIST : forcees dans le dataset final meme si rho Spearman < 0.02.
#
# Pourquoi : le screening Spearman teste une correlation MONOTONE (lineaire ordonnee).
# Les features CATEGORIELLES (open_type, day_type, profile_shape) et les SCORES
# COMPOSITES (open_bias_conf, trend_day_probability) ont des signaux NON-LINEAIRES
# que Spearman rate. LightGBM les exploite parfaitement via des splits non-lineaires.
#
# Ajoutees par Jackson 13/04/2026 : "open_type aussi serait bien de l'integrer".
# Ces features passent directement dans validated_union_* sans filtre rho.
WHITELIST_BYPASS = {
    # Game Changers — Open Type (Dalton / Steidlmayer market profile)
    "open_type",            # 0=Auction, 1=Drive, 2=Test Drive, 3=Rejection Reverse, 4=Auction Open
    "open_bias_conf",       # Score confiance biais open [0-1]
    "open_direction",       # -1/0/+1 direction probable de la journee
    "open_zone",            # 0/1 dans zone value area apres open

    # Game Changers — Day Type / Profile
    "trend_day_probability",  # [0-1] prob que ce soit une trend day
    "profile_shape",          # 0=D / 1=P / 2=b / 3=B (forme profil)
    "profile_skew",           # [-1,+1] asymetrie volume upper/lower
    "poc_position",           # [0,1] position du POC dans le range

    # Signaux binaires contextuels importants
    "vwap_triple_align",      # 1 si prix > vwap_d/w/m tous alignes
    "bool_gex_flip_zone",     # 1 si dans zone gamma flip

    # AMD composite scores (Lopez AFML chap.3 : scores non-monotones)
    "amd_manip_score",        # [0,1] score manipulation Power of 3
    "amd_po3_score",          # [0,1] score Power of 3
    "amd_session_bias",       # {-1,0,+1} biais session AMD
    # NOTE : rule_80pct et bool_va_confluence retires (quasi-constants post-regen).
}


# Features a DROP (ne passent JAMAIS dans le dataset final)
PROHIBITED_FEATURES = {
    # Note Phase 1 Option B : is_nq, partial_session, atr NE SONT PAS ici.
    # Ils sont exclus par quality_validator.META_COLUMNS et par
    # train_lightgbm.get_features (meta cols). Les drop dans PROHIBITED
    # casserait build() qui les utilise pour construire le result.

    # ── Prix absolus (fuite temporelle/instrument) ───────────────────
    "amd_asia_high", "amd_asia_low", "mq_top_gex_strike_1",

    # ── Mortes ou quasi-constantes (Phase 1 initiale) ───────────────
    "amd_sweep_up", "dist_vwap_d_sd3d", "ctx_momentum_exhaustion",
    "mq_dist_put_sup",      # doublon dist_mq_put
    "gex_cluster_count",    # seuil instrument-specifique
    "retest_low_count",     # seuil ticks non normalise

    # ── Mortes Phase 1 extension Option B (13/04) ────────────────────
    # Event detectors quasi-jamais actives (< 2% positive rate)
    "amd_judas_swing", "amd_manip_dir",
    "amd_po3_bearish", "amd_po3_bullish", "amd_sweep_dn",
    "bn_absorb_ask", "bn_absorb_bid",
    "bool_va_confluence", "comp_vpoc_align_day_20",
    "ctx_div_at_swing", "ctx_double_top_trap", "ctx_failed_auction",
    "im_smt_divergence",
    "new_swing_high", "new_swing_low",
    "retest_high_delta_div", "retest_low_delta_div",
    "rule_80pct",
    "rvol_absorb_buy", "rvol_absorb_sell",
    "rvol_buy", "rvol_sell", "rvol_extreme",

    # ── Prix/niveaux absolus additionnels ────────────────────────────
    "profile_hvn_dominant", "single_print_mid",

    # ── Volumes/CVD absolus ──────────────────────────────────────────
    "cvd_day", "cvd_ohlc_range", "ctx_cvd_session",
    # Volumes en lots non normalisables par atr (avg size per trade)
    "avg_ask_size", "avg_bid_size", "avg_trade_size",

    # ── mq_total_gex_m : unites incoherentes ES vs NQ (ES=509, NQ=10) ─
    "mq_total_gex_m",

    # ── Bugs C++ backlog (a corriger plus tard) ──────────────────────
    "fp_edge_buy", "fp_edge_sell",  # bug SG ACSIL ES
    "bn_pressure_bid",               # NQ 99.7% constant a investiguer

    # ── SumOfAlerts cumul pattern — bug conceptuel 16/04/2026 ────────
    # rotation_up / rotation_dn sont lus via DMP_ReadBN_SumOfAlerts qui
    # retourne le subgraph sg2 "Sum of Alerts" = COMPTEUR CUMULATIF depuis
    # le debut de la session. Des qu'il y a eu au moins 1 alerte up et 1
    # alerte dn dans la session (ce qui arrive quasi toujours apres les
    # premieres minutes), les 2 compteurs sont > 0 -> SafeBool(cumul>0)=1
    # pour les 2 -> 90.1% les 2 a 1 sur ES 14/04 live.
    # Meme effet que le bug Extension Line Count mais mecanique differente.
    # Fix C++ future : lire le DELTA (sg2[t] - sg2[t-1]) > 0 = alerte
    # fraiche cette barre = trigger per-bar. En attendant, blacklistees.
    "rotation_up", "rotation_dn",

    # ── Extension Line Count pattern — bug conceptuel 16/04/2026 ─────
    # Toutes ces features sont lues en C++ via DMP_ReadExtensionLineCount puis
    # converties en booleen via SafeBool(count > 0). Probleme : l'etude SC a
    # quasi toujours des zones bullish ET bearish actives quelque part (marche
    # en balance normale), donc les 2 booleens sont a 1 simultanement :
    #   bar_color_up/dn : 100% les 2 a 1 (feature morte totale)
    #   bar_pressure_ask/bid : 100% les 2 a 1 (feature morte totale)
    #   bn_color_up/dn : 90% les 2 a 1
    #   bn_color_up_2/dn_2 : 75% les 2 a 1
    #   bn_pressure_ask : 36% les 2 a 1 (moins pire mais meme pattern)
    # Verification empirique sur DATA/ES/20260414_ES.jsonl (1382 lignes live).
    # Fix C++ future : remplacer par DMP_ReadNearestExtensionLine + logique
    # directionnelle (compare up vs dn et retourne score +1/-1/0 selon quelle
    # zone est la plus proche du prix courant). En attendant, blacklistees.
    # Les features dist_ext_color_up/dn, dist_ext_long_up/dn, dist_ext_edge_buy/sell
    # contiennent la vraie info directionnelle et doivent etre gardees.
    "bar_color_up", "bar_color_dn",
    "bar_pressure_ask", "bar_pressure_bid",
    "bn_color_up", "bn_color_dn",
    "bn_color_up_2", "bn_color_dn_2",
    "bn_pressure_ask",
    # FIX 2026-04-17 : delta_divergence C++ pollue par bug Extension Line Count.
    # Verifie empiriquement sur collecte propre 20260416 (455 lignes ES + 455 NQ) :
    # 100% des 910 barres ont delta_divergence=1 cote C++. Cause :
    #   d.delta_div_buy  = DMP_ReadExtensionLineCount(chart, DELTA_DIV_BUY)
    #   d.delta_div_sell = DMP_ReadExtensionLineCount(chart, DELTA_DIV_SELL)
    # Les extension lines persistent jusqu'a intersection price (trending market
    # -> jamais intersectees -> count > 0 permanent -> SafeBool = 1 toujours).
    # Formule SC reelle identifiee (captures Jackson 17/04) :
    #   ID33 = "LINKED TO DELTA DIVERGENCE" = Daily OHLC study
    #   SG2 = Daily High cumulatif, SG3 = Daily Low cumulatif
    #   BUY  : AND(daily_low  < daily_low[-1],  AV-BV >= 0)
    #   SELL : AND(daily_high > daily_high[-1], AV-BV <= 0)
    # Reconstruction Python fidele dans CORE/rolling_features.py :
    #   delta_divergence_clean, delta_div_buy/sell_clean, delta_div_strength
    # Validation 20260416 NQ : 2 triggers 06:07/06:10 UTC matchent les 2
    # triangles visibles sur la capture Sierra Chart de Jackson.
    # Fire rate empirique : 0.44% (NQ) / 0.22% (ES) = evenement rare et fort.
    # delta_divergence raw C++ reste blacklistee. Le ML utilisera les 4 features
    # derivees *_clean calculees en Python (rolling_features ligne ~425).
    "delta_divergence",

    # ─────────────────────────────────────────────────────────────────
    # TODO CRITIQUE 15/04/2026 — Bug systemique DMP_Reader.h arr[sz-1]
    # Les fonctions DMP_ReadBN_Trigger / DMP_SafeReadLast / DMP_ReadBN_SumOfAlerts
    # lisent arr[sz-1] (derniere valeur actuelle) au lieu de arr[sc.Index].
    # Correct en LIVE (sc.Index=sz-1) mais POLLUE en BACKFILL Full Recalc :
    # toutes les barres historiques recoivent la valeur courante de l'etude SC
    # source au moment du recalc (constantes 100% ou 0% sur toute la periode).
    #
    # Fix C++ Jackson 15/04 (bn_absorb via Trigger sg0 + IDs NQ_BARRES + fp_edge
    # via Trigger sg0) : marche en LIVE, pollue en BACKFILL.
    #
    # Au PROCHAIN RETRAIN avec nouveau backfill, les features suivantes
    # risquent d'etre actives avec biais temporel massif (mortes sur historique,
    # vivantes sur 12-14 jours live recents). Les garder HORS du dataset v4
    # tant que le bug cross-TF arr[sz-1] -> sc.GetContainingIndexForSCDateTime
    # n'est pas fix architecturalement en C++.
    #
    # Cf. feedback_bug_arr_sz_1_systemique.md pour liste complete des fonctions
    # vulnerables et plan de fix architectural.
    #
    # Features a re-blacklister explicitement si elles reviennent dans v4 :
    #   fp_edge_buy_2, fp_edge_sell_2  (variantes NQ 0DIAG / ES rev1 800%)
    #   bar_edge_buy, bar_edge_sell    (Chart 25 ES / Chart 23 NQ via IDs fixes)
    #   bn_color_up, bn_color_dn, bn_color_up_2, bn_color_dn_2
    #   bn_long_up, bn_long_dn
    #   bn_double_ask, bn_double_bid, bn_triple_ask, bn_triple_bid
    #   ext_edge_buy_px, ext_edge_sell_px
    #   ext_color_up_px, ext_color_dn_px, ext_long_up_px, ext_long_dn_px
    #   dist_ext_edge_buy/sell, dist_ext_color_up/dn, dist_ext_long_up/dn
    # Actuellement toutes deja droppees par screening ou autres mecanismes.
    # ─────────────────────────────────────────────────────────────────

    # ── Versions ticks remplacees par versions _atr en C++ ───────────
    "dist_vwap_d",        # utiliser dist_vwap_d_atr (C++)
    "dist_vwap_m",        # utiliser dist_vwap_m_atr (C++)
    "ib_range_ticks",     # utiliser ib_range_atr (C++)
    "mq_dist_call_0dte",  # doublon de dist_mq_call_0dte normalise

    # ─────────────────────────────────────────────────────────────────
    # AUDIT SPRINT 1 10/06/2026 — Cat 11 Big orders + clusters
    # Audit croise code-reviewer agentId a6e29f5a7fdbddbb4 + claude empirique
    # data NQ 08/06 (1125 bars). Verdict : 14/28 features sauvables.
    #
    # RETIREES de PROHIBITED (14 features) - voir tableau agent :
    #   big_ask_cluster_20t, _50t            : 58-89% nz, mean 5-8 propre
    #   big_bid_cluster_20t, _50t            : symetrique
    #   n_big_ask_t3, n_big_bid_t3           : ES 32%/37%, NQ 23%/11% propre
    #   dist_big_ask_nearest_up/dn           : 100% nz NQ, signal directionnel
    #   dist_big_bid_nearest_up/dn           : idem
    #   dist_cluster_nearest_up/dn           : 65% nz, signal directionnel
    #   n_clusters_20t, n_clusters_50t       : 86-99% nz, vivants
    #
    # LAISSEES MORTES (14 features) - saturation cap C++ buffer NQ :
    #   n_big_ask_t1, n_big_ask_t2, n_big_ask_t4 : NQ cap buffer 20 ou seuil $1000 trop eleve
    #   n_big_bid_t1, n_big_bid_t2, n_big_bid_t4 : symetrique
    #   big_ask_cluster_20t_t1, _t2, _t3, _t4    : tier-specific thresholds = leak
    #   big_bid_cluster_20t_t1, _t2, _t3, _t4    : idem
    # ─────────────────────────────────────────────────────────────────
    # Big orders TIER-SPECIFIC LAISSES MORTES (saturation cap C++ NQ)
    "big_ask_cluster_20t_t1", "big_ask_cluster_20t_t2",
    "big_ask_cluster_20t_t3", "big_ask_cluster_20t_t4",
    "big_bid_cluster_20t_t1", "big_bid_cluster_20t_t2",
    "big_bid_cluster_20t_t3", "big_bid_cluster_20t_t4",
    "n_big_ask_t1", "n_big_ask_t2", "n_big_ask_t4",
    "n_big_bid_t1", "n_big_bid_t2", "n_big_bid_t4",

    # ─────────────────────────────────────────────────────────────────
    # AJOUT 18/04/2026 — suite audit code-reviewer (GO-avec-reserves)
    # ─────────────────────────────────────────────────────────────────
    # RESERVE 1 RESOLUE : bar_long_dn_bar/up_bar + ctx_instant_absorption migres
    # vers EVENT_BASED_FEATURES (quality_validator.py) au lieu de PROHIBITED.
    # Raison : rare events fire rate 1-2% exploitables par LightGBM via splits.
    # Pattern 11 evite (pas de drop par biais completion).

    # RESERVE 4 CORRIGE 18/04 : dist_ext_edge_sell_atr GARDE en PROHIBITED.
    # Erreur precedente : argument "MDA feature-engineer filtrera" est faux
    # temporellement -> le validator bloque AVANT feature-engineer. Biais
    # ES 1.6 / NQ 5.6 persiste malgre /atr = semantic C++ non-resolue.
    # TODO : investiguer code C++ dist_ext_edge_sell (calcul different ES/NQ ?).
    "dist_ext_edge_sell_atr",

    # AUDIT SPRINT 1 10/06/2026 — Cat 13 bar_long_*_bar SAUVES
    # Audit empirique NQ 08/06 : bar_long_up_bar 22.9% nz, bar_long_dn_bar 24.4% nz.
    # Agent code-reviewer ES 05/06 confirme rare-event sain post-fix DMP 3.7.6.
    # Anciennement bloquees par pollution backfill pre-3.7.6 (NQ mean 0.737).
    # Post-rebuild v4 debut mai + 2 mois data propre = securises.
    # RETIREES de PROHIBITED : reincorporees dans dataset ML.
    # (lignes supprimees, plus dans liste PROHIBITED)

    # RESERVE 3 RESOLUE : bn_score_bear + bn_score_raw = composites casses.
    # Audit DMP_Transform.h:1069-1075 : score_bear = sum(bn_color_dn, bn_absorb_bid,
    # bn_pressure_bid, bn_color_dn_2, bn_long_dn) ponderes. 4/5 composants sont
    # PROHIBITED. Avant fix 3.7.6 = satures -> score eleve. Apres fix = events
    # propres -> score s'effondre (ES 0.02 / NQ 0.06 au 17/04). Le score n'est plus
    # interpretable : ce n'est pas un vrai signal bearish, c'est un reliquat de bugs.
    # Prefer composer un score derive post-fix depuis les events propres au besoin.
    "bn_score_bear", "bn_score_raw",

    # ─────────────────────────────────────────────────────────────────
    # AJOUT 11/06/2026 — Audit ULTRATHINK Sierra Migration Phase 4.2.5
    # Bugs Sierra C++ DMP confirmes empiriquement sur 1926 bars NQ 10/06.
    # Sources : code-reviewer + quality-auditor + market-analyst convergent.
    # ─────────────────────────────────────────────────────────────────
    # Features Sierra C++ DMP DEAD 0/1926 (bug emission) - 16 features :
    "dist_ovn_high", "dist_ovn_low", "ovn_high_lvl", "ovn_low_lvl",
    "ib_high", "ib_low",
    "mq_gamma_condition", "mq_call_resistance", "mq_put_support",
    "dist_blind_nearest_up", "dist_blind_nearest_dn",
    "dist_ext_color_up", "dist_ext_color_dn",
    "dist_color_up_nearest_pct", "dist_color_dn_nearest_pct",
    "dist_delta_div_sell_nearest_atr",
    # Features Sierra C++ avec unite buggee (ticks vs points) - loader BROKEN.
    # mean -85856 sur NQ 28800 = absurd. Stored en ticks au lieu de points.
    # FIX Jackson 11/06 : validation empirique ES bar 19:57 UTC close=7402,
    # dist_comp_20d_vpoc=+86556 -> implied level=-14237 (impossible negatif).
    # NQ bar 19:57 UTC close=29485, dist_comp_20d_vpoc=-89140 -> implied
    # level=+51770 (impossible NQ trade 28-30k). vpoc_atr satures +/-20.0
    # constant. Drop EXPLICITE des 20d ET 50d (50d NULL partout = DEAD).
    "dist_comp_20d_vpoc", "dist_comp_20d_vah", "dist_comp_20d_val",
    "dist_comp_20d_vwap", "dist_comp_20d_vpoc_atr",
    "dist_comp_50d_vpoc", "dist_comp_50d_vah", "dist_comp_50d_val",
    "dist_comp_50d_vwap", "dist_comp_50d_vpoc_atr",
    "comp_vpoc_align_20_50", "comp_vpoc_align_day_20",  # derives potentiellement faux
    "inside_comp_20d_va", "inside_comp_50d_va",  # derives potentiellement faux
    # ovn_range_ticks = 0 constant alors que ovn_high - ovn_low > 0
    "ovn_range_ticks",
}


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURES DMP BRUT  (75 validees Spearman v1 sur ES 19-27 mars)
# ═══════════════════════════════════════════════════════════════════════════════

FEATURES_DMP: List[str] = [
    # --- Swing / Structure ---
    "dist_swing_high", "swing_range_ticks", "new_swing_high",
    "bars_since_retest_low", "bars_since_retest_high", "retest_low_delta_div",
    # --- VIX / Options Wall ---
    "dist_vix_call_0dte", "dist_vix_put", "dist_vix_put_0dte",
    "vix_above_hvl_0dte", "dist_vix_gex_nearest_dn",
    "next_wall_dist_ticks", "next_wall_is_call",
    # --- MQ ---
    "dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_call", "bool_above_mq_hvl",
    # --- Composite / Volume Profile ---
    "dist_comp_20d_vah", "dist_comp_50d_vah", "dist_comp_20d_val", "dist_comp_50d_val",
    "comp_vpoc_align_day_20", "vah_touches_20b", "val_touches_20b",
    "poc_separation_ticks", "profile_shape", "dist_cur_vah",
    "dist_session_lvn_above", "dist_session_lvn_below", "dist_session_hvn_above",
    "lvn_confluence_count",
    # --- IB / Session ---
    "ib_broken_up", "ib_complete", "dist_ib_high", "open_zone", "open_in_prev_va",
    "bool_session_early", "bool_va_confluence", "is_double_dist",
    "dist_sess_high", "dist_1d_min_ticks", "dist_open_830",
    # --- Game Changers (Open Type / Day Type / Profile) ---
    "open_type", "open_bias_conf", "open_direction",
    "day_type", "rule_80pct", "trend_day_probability",
    "profile_skew", "poc_position", "volume_imbalance",
    # --- VWAP ---
    "vwap_slope_30", "vwap_m_side", "bool_above_vwap_m",
    "dist_prev_vwap_sd1u", "dist_vwap_d_sd1u",
    "dist_vwap_d_sd3u", "dist_vwap_d_sd3d",  # Schema 3.7.2
    # --- Delta / CVD / Volume ---
    # Fix #73 (18/06) : delta_day et cvd_day_dir RETIRES (etaient ML features).
    # Empirique 18/06 : delta_bar == cvd_bar_delta = MEME metrique source.
    # delta_day (sg9) et cvd_day (sg18) sont cumuls C++ avec baselines reset
    # cassees. Apres override Python (cvd_session_override.py), delta_day == cvd_day
    # = volume absolu cumul session = VIOLE data-quality.md (fuite instrument +
    # fuite volatility). cvd_day_dir = sign(volume cumul) = derive d'absolu.
    # Reserve Q4 : aucun modele LightGBM actuellement en LIVE inference (cf
    # CLAUDE.md Phase 1 collecte). Risque ACTUEL train/serve skew = NUL.
    # Si datasets ML deja produits avec ces features : prochains rebuilds doivent
    # les re-exclure (cf incident #73).
    "delta_bar", "delta_bar_vol_norm", "delta_pct",
    "cvd_bar_delta", "ask_bid_imbalance",
    "ask_pct", "bid_pct", "buy_sell_ratio",
    "rvol", "rvol_absorb_buy", "momentum_5b", "diag_imbalance",
    # --- Big Orders ---
    "big_ask_cluster_20t_t2", "big_ask_cluster_20t_t3", "n_big_ask_t3",
    "dist_blind_nearest_up",
    # --- Schema 3.7.3 : Cluster Volume via VAP (13/04/2026) ---
    "dist_cluster_nearest_up", "dist_cluster_nearest_dn",
    "n_clusters_20t", "n_clusters_50t",
    # --- BN (survivants) ---
    "bn_absorb_bid", "bn_absorb_ask", "bn_pressure_bid",
    "bn_score_raw", "bn_score_bear", "bn_color_up_2",
    "fp_edge_buy", "dist_ext_edge_sell", "dist_ext_edge_buy",
    # --- Bar Signals ---
    "bar_long_dn_bar",
]

# Colonnes a exclure systematiquement (meta, identifiers, leakage, features mortes)
_META_COLS = {
    "ts", "schema", "is_rth_session", "is_nq", "instrument", "date", "time_et",
    "bar_open", "bar_high", "bar_low", "bar_count", "read_errors",
    "label", "valid_bar", "partial_session", "label_quality",
    "setup_type", "score_buy", "score_sell", "realized_pts",
    "tp_pts", "sl_pts", "hl_mode",
    "sample_weight",   # Lopez AFML ch.4 — passe a LightGBM.fit(sample_weight=...)
    # NOTE : exit_offset est dans le parquet labels mais non propage au dataset
    # (utilise uniquement pour calculer sample_weight dans labeler.py, inutile downstream).
    "bn_color_up", "bn_color_dn", "bn_color_dn_2",
    "bar_color_up", "bar_color_dn",
    "bn_pressure_ask", "bn_long_up", "bn_long_dn",
    "bn_volume_up", "bn_volume_dn", "bn_score_bull",
    "dist_ext_color_up", "dist_ext_color_dn",
    # Features collineaires (audit C4-data 2026-04-09)
    # ask_pct == buy_sell_ratio, delta_pct == ask_bid_imbalance == delta_bar_vol_norm
    # On garde delta_bar_vol_norm et ask_pct comme representants, on drop les redondants
    "buy_sell_ratio",        # = ask_pct
    "ask_bid_imbalance",     # = delta_bar_vol_norm = delta_pct
    "delta_pct",             # = delta_bar_vol_norm (identique mathematiquement)
}

_INVALID_THRESHOLD = -100.0


# ═══════════════════════════════════════════════════════════════════════════════
# DATASET BUILDER v2
# ═══════════════════════════════════════════════════════════════════════════════

class DatasetBuilder:
    """
    Construit le dataset ML a partir des fichiers bruts DMP + features derivees + labels.

    Args:
        data_path   : Dossier contenant ES/ et NQ/ avec les JSONL.
        labels_path : Dossier contenant les parquets de labels.
        features    : Liste de features a inclure. None = auto-detect apres screening.
        use_derived : Activer les features derivees (ctx_*, im_*, amd_*, rvol_*).
    """

    def __init__(
        self,
        data_path: str,
        labels_path: str,
        features: Optional[List[str]] = None,
        use_derived: bool = True,
    ):
        self.data_path = Path(data_path)
        self.labels_path = Path(labels_path)
        self.features = features
        self.use_derived = use_derived

    # ─── PUBLIC API ──────────────────────────────────────────────────────────

    def build(self, symbol: str = "ES") -> pd.DataFrame:
        """
        Construit le dataset complet pour un symbole.
        Inclut les features DMP brut + derivees si use_derived=True.
        """
        symbol = symbol.upper()
        other = "NQ" if symbol == "ES" else "ES"

        # 1. Charger features brutes
        df_feat = self._load_features(symbol)
        if df_feat.empty:
            raise ValueError(f"Aucune donnee JSONL pour {symbol} dans {self.data_path}")
        print(f"[DatasetBuilder] {symbol}: {len(df_feat)} barres chargees ({len(df_feat.columns)} colonnes)")

        # 2a. Recalcul IB depuis bar_high/bar_low (fix bug sc.High footprint)
        df_feat = self._compute_ib_recalc(df_feat, symbol)

        # 2b. Calculer features derivees
        if self.use_derived:
            df_feat = self._compute_derived(df_feat, symbol, other)

        # 2c. Enrichir avec MenthorQ (features macro daily)
        df_feat = self._compute_menthorq(df_feat, symbol)

        # 3. Charger labels (+ sample_weight si disponible — Lopez AFML ch.4)
        lbl_file = self.labels_path / f"ALL_{symbol}_labels.parquet"
        if not lbl_file.exists():
            raise FileNotFoundError(f"Labels non trouves : {lbl_file}")
        df_lbl = pd.read_parquet(lbl_file)
        # sample_weight peut etre absent des anciens parquets — fallback a 1.0 (pas de correction)
        lbl_cols = ["ts", "label", "partial_session"]
        if "sample_weight" in df_lbl.columns:
            lbl_cols.append("sample_weight")
        df_lbl = df_lbl[df_lbl["valid_bar"] == True][lbl_cols].copy()
        if "sample_weight" not in df_lbl.columns:
            df_lbl["sample_weight"] = 1.0  # Fallback retro-compatible

        # 4. Merge
        merged = df_feat.merge(df_lbl, on="ts", how="inner")
        merged = merged.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        print(f"  Merge: {len(merged)} barres valides")

        # ═══════════════════════════════════════════════════════════════
        # PHASE 1 (13/04/2026) : _normalize_by_atr applique sur MERGED
        # avant le select features. Garantit que les versions _atr sont
        # creees meme en Pass 2 ou validated_union_* ne contient pas les
        # versions ticks brutes ni atr. Drop PROHIBITED ici aussi.
        # ═══════════════════════════════════════════════════════════════
        merged = self._normalize_by_atr(merged)

        # 5. Selectionner features
        if self.features is not None:
            candidates = self.features
        else:
            # Auto: toutes les colonnes non-meta avec variance
            candidates = [c for c in merged.columns if c not in _META_COLS]

        available = [f for f in candidates if f in merged.columns]

        # 6. Nettoyage invalides + imputation
        df_clean = merged[available].copy()
        for col in available:
            vals = pd.to_numeric(df_clean[col], errors="coerce")
            df_clean[col] = vals
            df_clean.loc[vals < _INVALID_THRESHOLD, col] = np.nan

        # GUARD 02/05 (review code-reviewer GATE A) :
        # fillna(medians) global cree leak look-ahead sur features broadcast
        # daily (mq_*, dist_mq_*, mq_dist_*) avec NaN pre-MenthorQ (15-12-2025).
        # Pipeline V4/V5 doit utiliser build_dataset_v4_dmp_databento.py
        # (pattern attach_mq_distances + fillna cible volumes only).
        # Cf DOCS/BLOCKER_MQ_LEAK_PRE2026.md.
        mq_cols_in_avail = [c for c in available if "mq_" in c.lower()]
        if mq_cols_in_avail:
            raise RuntimeError(
                f"dataset_builder.py:516 fillna(medians) interdit avec mq_* "
                f"({len(mq_cols_in_avail)} cols detectees: {mq_cols_in_avail[:3]}...). "
                f"Utilisez build_dataset_v4_dmp_databento.py (pattern V4 propre). "
                f"Cf DOCS/BLOCKER_MQ_LEAK_PRE2026.md."
            )

        medians = df_clean.median()
        df_clean = df_clean.fillna(medians)

        # 7. Retirer colonnes constantes
        std = df_clean.std()
        dead = std[std < 1e-6].index.tolist()
        if dead:
            print(f"  {len(dead)} colonnes constantes retirees : {dead[:10]}{'...' if len(dead)>10 else ''}")
            df_clean = df_clean.drop(columns=dead)
            available = [c for c in available if c not in dead]

        # 8. Assembler
        result = pd.DataFrame({
            "ts":              merged["ts"],
            "label":           merged["label"].astype(int),
            "partial_session": merged["partial_session"].fillna(False).astype(bool),
            # Lopez AFML ch.4 — uniqueness weights a passer a LightGBMClassifier.fit()
            # Fallback 1.0 si colonne absente des anciens parquets labels
            "sample_weight":   merged.get(
                "sample_weight",
                pd.Series(1.0, index=merged.index)
            ).fillna(1.0).astype(float),
            # Identifiant instrument (boolean) — etait dans _META_COLS mais jamais creee
            # avant ce fix. Utilise en aval si besoin de filtrer ou conditionner par symbol.
            "is_nq":           pd.Series(
                symbol.upper() == "NQ",
                index=merged.index,
                dtype=bool,
            ),
        })
        for col in available:
            result[col] = df_clean[col].values

        # Note : _normalize_by_atr a ete applique sur merged ci-dessus,
        # donc les _atr sont deja dans df_clean → available → result.

        print(f"  [OK] Dataset: {len(result)} barres x {len(result.columns)} cols")
        print(f"       Labels: BUY={int((result.label==1).sum())}  "
              f"SELL={int((result.label==-1).sum())}  "
              f"HOLD={int((result.label==0).sum())}")

        return result

    def screen_spearman(self, df: pd.DataFrame, min_rho: float = 0.02) -> List[str]:
        """
        Screening Spearman de toutes les features vs label.
        Retourne la liste des features avec |rho| >= min_rho, triees par |rho| desc.
        """
        from scipy import stats

        features = self.feature_list(df)
        label = df["label"].values
        results = []

        for col in features:
            vals = df[col].values.astype(float)
            mask = np.isfinite(vals)
            if mask.sum() < 100:
                continue
            v, l = vals[mask], label[mask]
            if np.std(v) < 1e-6:
                continue
            rho, pval = stats.spearmanr(v, l)
            results.append((col, rho, pval))

        results.sort(key=lambda x: abs(x[1]), reverse=True)

        passed = [(col, rho, pval) for col, rho, pval in results if abs(rho) >= min_rho]
        dropped = len(results) - len(passed)

        print(f"\n[Spearman Screening] |rho| >= {min_rho}")
        print(f"  Passed: {len(passed)} / {len(results)}  (dropped: {dropped})")
        print(f"  Top 15:")
        for col, rho, pval in passed[:15]:
            sig = "*" if pval < 0.05 else " "
            print(f"    {sig} {col:<35} rho={rho:+.4f}  p={pval:.4f}")

        return [col for col, rho, pval in passed]

    def save(self, df: pd.DataFrame, output_path: str) -> None:
        """Sauvegarde le dataset en parquet."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)
        print(f"[DatasetBuilder] Sauvegarde: {out}  ({out.stat().st_size // 1024} KB)")

    def feature_list(self, df: pd.DataFrame) -> List[str]:
        """Retourne la liste des features dans le dataset (sans ts/label/meta).

        Utilise _META_COLS (source unique de verite) pour exclure sample_weight,
        exit_offset, hl_mode, etc. qui doivent rester hors features candidates.
        """
        return [c for c in df.columns if c not in _META_COLS]

    def walk_forward_splits(
        self,
        df: pd.DataFrame,
        n_test_days: int = 5,
        min_train_days: int = 10,
    ) -> Iterator[Tuple[pd.DataFrame, pd.DataFrame]]:
        """Walk-forward chronologique. Yield (train_df, test_df)."""
        df = df.sort_values("ts").reset_index(drop=True)
        dates = pd.to_datetime(df["ts"], unit="ms").dt.date
        unique_days = sorted(dates.unique())

        start_test = min_train_days
        while start_test + n_test_days <= len(unique_days):
            test_days = set(unique_days[start_test: start_test + n_test_days])
            train_days = set(unique_days[:start_test])
            yield df[dates.isin(train_days)].reset_index(drop=True), \
                  df[dates.isin(test_days)].reset_index(drop=True)
            start_test += n_test_days

    # ─── DERIVED FEATURES ────────────────────────────────────────────────────

    def _compute_derived(self, df: pd.DataFrame, symbol: str, other_symbol: str) -> pd.DataFrame:
        """Calcule les features derivees (ctx_*, im_*, amd_*, rvol_*)."""
        n_before = len(df.columns)

        # --- Rolling Features (39 ctx_*) ---
        df = self._compute_rolling(df)

        # --- RVOL (10 rvol_*) ---
        df = self._compute_rvol(df)

        # --- AMD (18 amd_*) ---
        df = self._compute_amd(df, symbol)

        # --- Intermarket (10 im_*) ---
        df = self._compute_intermarket(df, symbol, other_symbol)

        # NOTE : _normalize_by_atr est appele depuis build() apres le merge
        # labels + ajout is_nq/partial_session/sample_weight, pour drop toutes
        # les sources de features en un seul endroit (voir build() ligne ~340).

        n_after = len(df.columns)
        print(f"  Features derivees: +{n_after - n_before} colonnes ({n_before} -> {n_after})")
        return df

    def _normalize_by_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise les features en ticks/points par ATR, puis drop PROHIBITED.

        FIX 13/04/2026 Phase 1 save-or-drop :
        - Crée les versions _atr de TO_NORMALIZE (conversion POINTS → TICKS pour
          les features POINTS_FEATURES avant division).
        - Drop la version originale apres normalisation.
        - Drop les features PROHIBITED (META, absolus, mortes, temporaires big_*).

        Note : le drop PROHIBITED s'applique meme si atr absent (Pass 2 ou atr
        a ete filtre par screen_spearman).
        """
        normalized = 0

        # ── 1. Normalisation /atr (seulement si atr disponible) ──
        if "atr" in df.columns:
            # ATR en TICKS dans le JSONL C++ (verifie 13/04/2026 : ES mean 132, NQ 571)
            atr_safe = pd.to_numeric(df["atr"], errors="coerce").replace(0, np.nan)

            for col in TO_NORMALIZE:
                if col not in df.columns:
                    continue
                raw = pd.to_numeric(df[col], errors="coerce")
                # Conversion POINTS → TICKS si necessaire
                raw_ticks = raw / TICK_SIZE if col in POINTS_FEATURES else raw
                new_col = col.replace("_ticks", "_atr") if col.endswith("_ticks") else f"{col}_atr"
                df[new_col] = raw_ticks / atr_safe
                df = df.drop(columns=[col])
                normalized += 1

                # Assert anti-bug : la feature ne doit pas etre constante
                std = df[new_col].std()
                if pd.notna(std) and std < 1e-6:
                    print(f"  [WARN] {new_col} constant apres normalisation (std={std:.2e})")

        # ── 2. Drop PROHIBITED (toujours, meme si atr absent) ──
        to_drop = [c for c in PROHIBITED_FEATURES if c in df.columns]
        if to_drop:
            df = df.drop(columns=to_drop)

        print(f"  _normalize_by_atr: +{normalized} features _atr, -{len(to_drop)} prohibited")
        return df

    def _compute_ib_recalc(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Recalcul IB depuis bar_high/bar_low (fix bug sc.High footprint)."""
        try:
            from ib_recalc import IBRecalc
            recalc = IBRecalc()
            df = recalc.compute(df, symbol)
        except Exception as e:
            print(f"  [WARN] ib_recalc: {e}")
        return df

    def _compute_menthorq(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Enrichit avec les features macro MenthorQ (Q-Score, GEX, Swing, etc.).

        FIX 13/04/2026 : le chemin MENTHORQ etait calcule a l'envers (parent au
        lieu de child), ce qui instanciait MenthorQReader avec un dossier
        inexistant → pas d'exception mais aucune feature mq_* ajoutee (casse
        silencieuse). Impact : 37 features mq_* absentes du dataset V2 depuis
        le refactor qui a introduit ce bug.
        """
        try:
            from mia_menthorq_reader import MenthorQReader
            # DATA/MENTHORQ (meme niveau que DATA/ES et DATA/NQ)
            mq_path = self.data_path / "MENTHORQ"
            if not mq_path.exists():
                # Fallback ancien setup : MENTHORQ a cote de DATA (parent)
                mq_path = self.data_path.parent / "MENTHORQ"
            mq = MenthorQReader(str(mq_path))

            # Extraire les dates uniques depuis les timestamps
            if "ts" in df.columns:
                dates = pd.to_datetime(df["ts"], unit="ms", utc=True)
                # Ajuster pour la date de trading (session commence 18h ET veille)
                trading_dates = (dates - pd.Timedelta(hours=5)).dt.strftime("%Y%m%d").unique()
            elif "date" in df.columns:
                trading_dates = df["date"].unique()
            else:
                print(f"  [WARN] menthorq: pas de colonne ts ou date")
                return df

            tick_size = 0.25

            # Enrichir par date de trading
            enriched_parts = []
            for td in trading_dates:
                mask = None
                if "ts" in df.columns:
                    dates_col = (pd.to_datetime(df["ts"], unit="ms", utc=True)
                                 - pd.Timedelta(hours=5)).dt.strftime("%Y%m%d")
                    mask = dates_col == td
                else:
                    mask = df["date"] == td

                sub = df[mask].copy()
                if len(sub) == 0:
                    continue

                sub = mq.enrich(sub, td, symbol, tick_size)
                enriched_parts.append(sub)

            if enriched_parts:
                df = pd.concat(enriched_parts, ignore_index=True)
            else:
                print(f"  [WARN] menthorq: aucune donnee MenthorQ trouvee")

        except Exception as e:
            print(f"  [WARN] menthorq: {e}")
        return df

    def _compute_rolling(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rolling context features (ctx_*)."""
        try:
            from rolling_features import RollingFeatures
            rf = RollingFeatures()
            df = rf.compute(df)
        except Exception as e:
            print(f"  [WARN] rolling_features: {e}")
        return df

    def _compute_rvol(self, df: pd.DataFrame) -> pd.DataFrame:
        """Relative volume features (rvol_* derivees, pas DMP brut)."""
        try:
            from rvol import RvolEngine
            engine = RvolEngine()
            df = engine.compute(df)
        except Exception as e:
            print(f"  [WARN] rvol: {e}")
        return df

    def _compute_amd(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """AMD ICT Power of 3 features (amd_*).

        FIX 13/04/2026 : AmdEngine avait un default symbol='NQ' et etait
        instancie sans parametre, ce qui faisait que les seuils NQ
        (SWEEP_MIN_TICKS, ACCUM_MIN_TICKS, JUDAS_REENTRY_TICKS) etaient
        utilises pour calculer les signaux AMD cote ES → features AMD
        biaisees. Fix : passer le symbole correct a l'engine.
        """
        try:
            from mia_amd import AmdEngine
            engine = AmdEngine(symbol=symbol)
            df = engine.compute(df)
        except Exception as e:
            print(f"  [WARN] mia_amd: {e}")
        return df

    def _compute_intermarket(self, df: pd.DataFrame, symbol: str, other_symbol: str) -> pd.DataFrame:
        """Intermarket cross-asset features (im_*)."""
        try:
            from intermarket_features import IntermarketFeatures
            df_other = self._load_features(other_symbol)
            if df_other.empty:
                print(f"  [WARN] intermarket: pas de donnees {other_symbol}")
                return df
            engine = IntermarketFeatures()
            df = engine.compute(df, df_other, target=symbol)
        except Exception as e:
            print(f"  [WARN] intermarket: {e}")
        return df

    # ─── LOADERS ─────────────────────────────────────────────────────────────

    MIN_BARS_PER_FILE = 50  # Fichiers avec moins de 50 barres = weekend/jour incomplet

    def _load_features(self, symbol: str) -> pd.DataFrame:
        """Charge tous les JSONL d'un symbole. Exclut weekends/jours incomplets (<50 barres)."""
        sym_dir = self.data_path / symbol
        if not sym_dir.exists():
            return pd.DataFrame()

        rows = []
        skipped = []
        for f in sorted(os.listdir(sym_dir)):
            if not f.endswith(".jsonl"):
                continue
            file_rows = []
            with open(sym_dir / f, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        file_rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            if len(file_rows) < self.MIN_BARS_PER_FILE:
                skipped.append(f"{f} ({len(file_rows)} barres)")
                continue
            rows.extend(file_rows)
        if skipped:
            print(f"  [DatasetBuilder] {symbol}: {len(skipped)} fichiers exclus (weekends/incomplets): {', '.join(skipped)}")

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["ts"] = pd.to_numeric(df["ts"], errors="coerce").astype("int64")
        df = df.dropna(subset=["ts"])
        return df


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    BACKUP_DATA   = "D:/TRADING_SIERRA_CHART_AUTO/DATA/BACKUP/schema_370"
    CURRENT_DATA  = "D:/TRADING_SIERRA_CHART_AUTO/DATA"
    BACKFILL_DATA = "D:/TRADING_SIERRA_CHART_AUTO/DATA_BACKFILL"
    LABELS_PATH   = "D:/TRADING_SIERRA_CHART_AUTO/DATA/LABELS"
    OUTPUT_DIR    = "D:/TRADING_SIERRA_CHART_AUTO/DATA/DATASETS"

    # 3 sources possibles via CLI :
    #   --current  (defaut pour live 12j)  → DATA/
    #   --backfill (backfill historique)    → DATA_BACKFILL/
    #   sinon                               → BACKUP/schema_370 (legacy)
    if "--backfill" in sys.argv:
        data_path = BACKFILL_DATA
        source_label = "BACKFILL (historique DMP)"
    elif "--current" in sys.argv:
        data_path = CURRENT_DATA
        source_label = "CURRENT 3.7.3 (live)"
    else:
        data_path = BACKUP_DATA
        source_label = "BACKUP 3.7.0"

    print(f"DatasetBuilder v2 — source: {source_label}")
    print(f"Data: {data_path}")
    print()

    # --- Build avec auto-detection (pas de liste fixe) ---
    builder = DatasetBuilder(
        data_path=data_path,
        labels_path=LABELS_PATH,
        features=None,        # auto-detect toutes les features
        use_derived=True,     # ctx_* + im_* + amd_* + rvol_*
    )

    # ═══════════════════════════════════════════════════════════════
    # Pass 1 — Build complet ES et NQ pour obtenir les features brutes
    # ═══════════════════════════════════════════════════════════════
    df_es = builder.build("ES")
    df_nq = builder.build("NQ")

    # ═══════════════════════════════════════════════════════════════
    # APPROCHE LOPEZ AFML (13/04/2026) — Pas de feature selection avant training
    # ═══════════════════════════════════════════════════════════════
    # Jackson 13/04 : le screening Spearman rho >= 0.02 droppait 74% des features
    # calculees (338 → 87). Lopez de Prado, Chan et Davey sont unanimes :
    #
    #   "Feature importance analysis should be done BY THE MODEL, not before training."
    #
    # Les garde-fous qui rendent cette approche sure :
    #   1. quality_validator.py : refuse toute feature polluee (fuite instrument,
    #      volatilite, prix absolu, outlier, constante)
    #   2. PROHIBITED_FEATURES : drop explicite META, mortes, doublons, absolus
    #   3. _normalize_by_atr : normalise les features en ticks/points
    #   4. sample_weight uniqueness (Lopez ch.4) : corrige le biais d'overlapping
    #   5. importance_guard : detecte une feature qui domine apres training
    #   6. Purged K-Fold + early stopping + L1 regularization dans train_lightgbm.py
    #   7. Meta-labeling (Lopez ch.3) : 2e niveau de filtrage
    #
    # Union = toutes les features non-META non-PROHIBITED des 2 datasets.
    # LightGBM decide lui-meme via feature_importances_ ce qui compte.

    all_features_es = set(c for c in df_es.columns if c not in _META_COLS)
    all_features_nq = set(c for c in df_nq.columns if c not in _META_COLS)
    union_features = sorted(all_features_es | all_features_nq)

    # WHITELIST_BYPASS est maintenant redondant (plus de filtre Spearman)
    # mais on garde la documentation pour les features critiques.
    whitelisted_missing = WHITELIST_BYPASS - set(union_features)
    if whitelisted_missing:
        print(f"\n[WARN] Features WHITELIST manquantes du dataset : {whitelisted_missing}")

    validated_union_es = [f for f in union_features if f in df_es.columns]
    validated_union_nq = [f for f in union_features if f in df_nq.columns]
    print(f"\n=== Union ES|NQ (sans screening Spearman): {len(union_features)} features ===")
    print(f"    ES: {len(validated_union_es)} presentes")
    print(f"    NQ: {len(validated_union_nq)} presentes")
    print(f"    Approche Lopez AFML : LightGBM decidera via feature_importances_")

    # ═══════════════════════════════════════════════════════════════
    # Pass 2 — Rebuild avec features unionees (symetrie respectee)
    # ═══════════════════════════════════════════════════════════════
    builder_es_final = DatasetBuilder(
        data_path=data_path,
        labels_path=LABELS_PATH,
        features=validated_union_es,
        use_derived=True,
    )
    df_es_final = builder_es_final.build("ES")

    builder_nq_final = DatasetBuilder(
        data_path=data_path,
        labels_path=LABELS_PATH,
        features=validated_union_nq,
        use_derived=True,
    )
    df_nq_final = builder_nq_final.build("NQ")

    # ═══════════════════════════════════════════════════════════════
    # QUALITY VALIDATOR — garde-fou code-level (Jackson 13/04/2026)
    # Regle souveraine : qualite donnees > symetrie > screening Spearman
    # En mode strict, leve QualityViolation si red flags detectes
    #
    # 2026-04-14 : en mode --backfill, le validator est NON-STRICT par defaut
    # parce que les datasets historiques longs (7 mois) exhibent des features
    # qui n'existent pas sur 15 jours de live (compteurs cumulatifs qui atteignent
    # des valeurs enormes, prix absolus non-normalises). On affiche le rapport
    # mais on sauve quand meme. A fixer en fix/drop specifique plus tard.
    # Flag --strict force le mode strict meme en backfill.
    # ═══════════════════════════════════════════════════════════════
    from quality_validator import QualityValidator, QualityViolation

    print("\n" + "=" * 70)
    print("  QUALITY VALIDATOR — audit final avant sauvegarde")
    print("=" * 70)

    strict_mode = True
    if "--backfill" in sys.argv and "--strict" not in sys.argv:
        strict_mode = False
        print("  [INFO] Mode backfill : validator NON-STRICT (rapport info, sauvegarde forcee)")
        print("  [INFO] Utilise --strict pour forcer le mode strict")
    elif "--no-strict" in sys.argv:
        strict_mode = False
        print("  [INFO] Mode --no-strict : validator NON-STRICT (POC training)")
        print("  [INFO] Datasets sauvegardes meme si red flags. NE PAS utiliser pour live.")

    validator = QualityValidator(strict=strict_mode, verbose=True)
    try:
        validator.validate(df_es_final, df_nq_final)
    except QualityViolation as e:
        print(f"\n[FATAL] Dataset REFUSE par quality_validator : {e}")
        print("[FATAL] Les datasets NE SERONT PAS sauvegardes.")
        print("[FATAL] Action : drop/normalize les features flaggees, puis rerun.")
        sys.exit(2)

    # Si on arrive ici, le validator a valide les 2 datasets
    # Suffix de version : v2 pour BACKUP/CURRENT, v3 pour BACKFILL (2026-04-14)
    if "--backfill" in sys.argv:
        version_suffix = "v3"
    else:
        version_suffix = "v2"
    builder_es_final.save(df_es_final, f"{OUTPUT_DIR}/ES_dataset_{version_suffix}.parquet")
    builder_nq_final.save(df_nq_final, f"{OUTPUT_DIR}/NQ_dataset_{version_suffix}.parquet")

    # Afficher features finales (reconstruit depuis les dataframes finaux apres fix 18/04)
    validated_es = [c for c in df_es_final.columns
                    if c not in {"ts", "sym", "label", "label_buy", "label_sell",
                                  "sample_weight", "price", "bar_high", "bar_low",
                                  "valid_bar", "is_nq", "partial_session", "atr",
                                  "datetime_utc", "datetime_et", "session", "session_id"}]
    validated_nq = [c for c in df_nq_final.columns
                    if c not in {"ts", "sym", "label", "label_buy", "label_sell",
                                  "sample_weight", "price", "bar_high", "bar_low",
                                  "valid_bar", "is_nq", "partial_session", "atr",
                                  "datetime_utc", "datetime_et", "session", "session_id"}]
    for sym, feats in [("ES", validated_es), ("NQ", validated_nq)]:
        print(f"\n=== FEATURES {sym} ({len(feats)}) ===")
        for i, f in enumerate(feats, 1):
            prefix = "ctx_" if f.startswith("ctx_") else \
                     "im_"  if f.startswith("im_")  else \
                     "amd_" if f.startswith("amd_") else \
                     "rvol_" if f.startswith("rvol_") else "dmp"
            print(f"  {i:3d}. [{prefix:>5}] {f}")
