"""
Labeler.py — MIA Trading System  v2
=====================================
Attribue un label {+1 BUY / -1 SELL / 0 HOLD} à chaque barre RTH
via une SIMULATION DE TRADE réaliste (TP/SL path-aware).

MÉTHODE v2 — Simulation TP/SL sur chemin prix
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pour chaque barre i, on simule simultanément deux trades virtuels :

  BUY  : TP = price[i] + tp_pts  |  SL = price[i] - sl_pts
  SELL : TP = price[i] - tp_pts  |  SL = price[i] + sl_pts

On scanne les closes des barres i+1 à i+N dans l'ordre :
  - Si close[j] >= BUY_TP  → BUY gagne   (label = +1)
  - Si close[j] <= BUY_SL  → BUY perd    (BUY éliminé)
  - Si close[j] <= SELL_TP → SELL gagne  (label = -1)
  - Si close[j] >= SELL_SL → SELL perd   (SELL éliminé)
  - Fin de fenêtre sans décision → HOLD  (label = 0)

Si BUY et SELL gagnent tous les deux (prix remonte et descend) → HOLD.
Si ni l'un ni l'autre ne gagne → HOLD.

LIMITATION CONNUE : on utilise le prix de CLÔTURE comme proxy.
Sans les colonnes high/low par barre (absentes du schéma 3.7.0),
on ne peut pas détecter un touch intrabar de SL/TP.
→ Les labels BUY/SELL sont légèrement optimistes (SL intrabar manqués).
→ Conserver en tête pour l'évaluation des performances ML.

IMPORTANT : Aucune donnée future n'est utilisée au moment de la barre i.
Le look-ahead est appliqué UNIQUEMENT pour construire la cible d'entraînement.

Schéma attendu : 3.7.0 (258 colonnes)
Source : DMP_Main.cpp → JSONL → dmp_reader.py

Auteur : MIA Trading System
Date   : 2026-03-27 (v2 — simulation TP/SL)
"""

import sys
import os
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

# Ajouter le dossier CORE au path si nécessaire
sys.path.insert(0, str(Path(__file__).parent))
from dmp_reader import DmpReader


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

class LabelConfig:
    """Paramètres du labeler — modifier ici pour ajuster."""

    # --- Horizon max de scanning (barres) ---
    FORWARD_BARS        = 20        # Max barres à scanner pour TP/SL
    MARGIN_OPEN_BARS    = 5         # Barres à ignorer après ouverture session
    MARGIN_CLOSE_BARS   = 5         # Barres à ignorer avant fermeture session

    # --- TP et SL par symbole (en ticks, 1 tick = 0.25 pts) ---
    # Calibrés sur données réelles (19-26 mars 2026) :
    #   Critères : RR fixe = 1.8 | HOLD cible 20-35% | SNR > 1.3
    #   ES  : TP=9t (2.25pts) SL=5t (1.25pts) → RR=1.8
    #   NQ  : TP=36t (9.0pts) SL=20t (5.0pts) → RR=1.8
    #   (NQ bouge ~4x plus qu'ES en 10 barres — médiane 18pts vs 4pts)
    TP_TICKS = {
        "ES": 9,    # 9 ticks = 2.25 pts
        "NQ": 36,   # 36 ticks = 9.0 pts
    }
    SL_TICKS = {
        "ES": 5,    # 5 ticks = 1.25 pts  → RR = 1.8
        "NQ": 20,   # 20 ticks = 5.0 pts  → RR = 1.8
    }
    TICK_SIZE = {
        "ES": 0.25,
        "NQ": 0.25,
    }

    # --- Quality score : conviction directionnelle ---
    # quality = |score_buy - score_sell| (différence = conviction)
    # 0 = signal équilibré (confused)  |  5+ = forte conviction directionnelle
    QUALITY_MAX         = 10

    # --- Sessions partielles connues ---
    # Dates où un symbole a fermé plus tôt que l'autre (ex : Vendredi Saint).
    # Les barres de ces jours reçoivent partial_session=True.
    # L'entraînement ML peut les inclure ou les exclure selon le besoin.
    PARTIAL_SESSION_DATES = {
        "20260325",   # Vendredi Saint — NQ a fermé tôt (37 barres ES sans NQ)
    }

    # --- Chemins ---
    DATA_PATH           = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA")
    OUTPUT_PATH         = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/LABELS")


# ═══════════════════════════════════════════════════════════════════════════════
# LABELING FORWARD
# ═══════════════════════════════════════════════════════════════════════════════

def _simulate_tpsl(prices: pd.Series, tp_pts: float, sl_pts: float,
                   n_bars: int,
                   highs: pd.Series = None,
                   lows:  pd.Series = None):
    """
    Simulation TP/SL path-aware.

    Schéma 3.7.1+ (bar_high / bar_low disponibles) :
    ──────────────────────────────────────────────────
    Pour chaque barre future j on teste d'abord si SL est touché,
    puis si TP est touché (convention conservatrice : SL prioritaire
    quand les deux niveaux sont dans le range de la même barre).

      BUY  : TP atteint si bar_high[j] >= entry + tp_pts
             SL touché  si bar_low[j]  <= entry - sl_pts
             Si les deux dans la même barre → SL gagne (pire cas)

      SELL : TP atteint si bar_low[j]  <= entry - tp_pts
             SL touché  si bar_high[j] >= entry + sl_pts
             Si les deux dans la même barre → SL gagne (pire cas)

    Schéma 3.7.0 (fallback, bar_high/bar_low absents) :
    ─────────────────────────────────────────────────────
    Utilise price (close) comme unique référence.
    Labels légèrement optimistes (SL intrabar non détectés).
    La colonne `hl_mode` indique le mode utilisé par barre.

    Args:
        prices  : Série de prix close (toujours présent)
        tp_pts  : TP en points
        sl_pts  : SL en points
        n_bars  : Fenêtre max de scan (barres)
        highs   : Série bar_high (None → fallback close)
        lows    : Série bar_low  (None → fallback close)

    Returns:
        labels       : pd.Series int8 (+1 / -1 / 0)
        realized_pts : pd.Series float (tp_pts si win, return brut si timeout)
        hl_mode      : pd.Series bool  (True = high/low utilisés)
    """
    p  = prices.values
    n  = len(p)

    # Construire les arrays high/low avec fallback barre par barre
    # Si highs/lows sont fournis mais ont des NaN → fallback sur close pour ces barres
    has_hl = (highs is not None) and (lows is not None)
    if has_hl:
        h_arr      = highs.reindex(prices.index).values.astype(float)
        l_arr      = lows.reindex(prices.index).values.astype(float)
        # Fallback sur close là où high/low sont NaN ou invalides
        bad_mask   = np.isnan(h_arr) | np.isnan(l_arr) | (h_arr < l_arr)
        h_arr      = np.where(bad_mask, p, h_arr)
        l_arr      = np.where(bad_mask, p, l_arr)
        hl_used    = ~bad_mask   # True = vraies valeurs high/low
    else:
        h_arr      = p.copy()   # fallback : close = high = low
        l_arr      = p.copy()
        hl_used    = np.zeros(n, dtype=bool)

    labels       = np.zeros(n, dtype=np.int8)
    realized_pts = np.full(n, np.nan)
    # Offset (nb de barres apres i) ou le trade virtuel se resout (TP/SL/timeout).
    # Requis pour calculer les sample weights par uniqueness temporelle (Lopez AFML ch.4).
    exit_offset  = np.zeros(n, dtype=np.int32)

    for i in range(n - 1):
        entry   = p[i]
        buy_tp  = entry + tp_pts
        buy_sl  = entry - sl_pts
        sell_tp = entry - tp_pts
        sell_sl = entry + sl_pts

        buy_alive  = True
        sell_alive = True
        buy_won    = False
        sell_won   = False
        last_j     = i  # Derniere barre visitee (sera utilisee pour exit_offset)

        for j in range(i + 1, min(i + 1 + n_bars, n)):
            last_j = j
            h_j = h_arr[j]
            l_j = l_arr[j]

            # ── Évaluation BUY (SL prioritaire si ambiguïté intrabar) ──
            if buy_alive:
                sl_hit = l_j <= buy_sl
                tp_hit = h_j >= buy_tp
                if sl_hit and tp_hit:
                    # Range couvre les deux niveaux → SL en premier (pire cas)
                    buy_alive = False
                elif tp_hit:
                    buy_won   = True
                    buy_alive = False
                elif sl_hit:
                    buy_alive = False

            # ── Évaluation SELL (SL prioritaire si ambiguïté intrabar) ─
            if sell_alive:
                sl_hit = h_j >= sell_sl
                tp_hit = l_j <= sell_tp
                if sl_hit and tp_hit:
                    sell_alive = False
                elif tp_hit:
                    sell_won   = True
                    sell_alive = False
                elif sl_hit:
                    sell_alive = False

            if not buy_alive and not sell_alive:
                break

        exit_offset[i] = last_j - i  # Nb barres avant resolution (>=1 si au moins 1 barre future)

        # ── Attribution du label ────────────────────────────────────────
        if buy_won and not sell_won:
            labels[i]       = 1
            realized_pts[i] = tp_pts

        elif sell_won and not buy_won:
            labels[i]       = -1
            realized_pts[i] = tp_pts

        elif buy_won and sell_won:
            # Les deux gagnent dans la fenêtre → marché en range → ambiguïté
            labels[i]       = 0
            realized_pts[i] = 0.0

        else:
            # Timeout ou double SL → return informatif (non utilisé pour label)
            labels[i]       = 0
            last_j_tm       = min(i + n_bars, n - 1)
            realized_pts[i] = p[last_j_tm] - entry

    return (
        pd.Series(labels,       index=prices.index, dtype=np.int8),
        pd.Series(realized_pts, index=prices.index),
        pd.Series(hl_used,      index=prices.index, dtype=bool),
        pd.Series(exit_offset,  index=prices.index, dtype=np.int32),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SAMPLE WEIGHTS — UNIQUENESS TEMPORELLE (Lopez de Prado AFML ch.4)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_label_uniqueness(labels: pd.Series, exit_offsets: pd.Series) -> pd.Series:
    """
    Calcule les sample weights par uniqueness temporelle (Lopez de Prado, AFML ch.4).

    Pourquoi : Triple Barrier genere des labels dont la duree de vie se chevauche
    (ex: un label BUY a la barre i peut etre encore actif quand un nouveau BUY
    demarre a i+3). LightGBM traite ces labels comme independants et gonfle
    artificiellement l'information disponible → Sharpe in-sample surestime.

    Formule (AFML p.60-61) :
        Pour chaque barre active i avec intervalle de vie [i, i + offset_i] :
            c_t        = nombre de labels actifs a l'instant t (t dans l'intervalle)
            weight_i   = mean(1 / c_t) pour t dans [i, i + offset_i]

    Interpretation :
      - weight = 1.0  → label isole, aucune concurrence temporelle
      - weight < 1.0  → label chevauche avec d'autres (moins d'information unique)
      - weight = 0.5  → en moyenne partage le temps avec 1 autre label

    Resultat attendu : sans correction, le Sharpe IS est gonfle de +0.3 a +0.6
    selon benchmarks MQL5 2024. A passer en argument `sample_weight` de
    `LightGBMModel.fit()`.

    Args:
        labels       : pd.Series int8 (+1/-1/0) — labels Triple Barrier
        exit_offsets : pd.Series int32 — nb barres apres i ou le label se resout

    Returns:
        pd.Series float64 (index = labels.index, name = 'sample_weight').
        Les barres HOLD (label=0) ont un poids de 1.0 (seront filtrees au training).
    """
    n = len(labels)
    if n == 0:
        return pd.Series([], dtype=np.float64, name='sample_weight')

    labels_arr  = labels.values
    offsets_arr = exit_offsets.values
    active_mask = labels_arr != 0

    # Passe 1 : compter les labels actifs a chaque instant t (vectorise par barre)
    concurrent = np.zeros(n, dtype=np.int32)
    for i in range(n):
        if active_mask[i]:
            end = min(i + int(offsets_arr[i]), n - 1)
            concurrent[i:end + 1] += 1

    # Passe 2 : poids = moyenne de 1/c_t sur la fenetre [i, i+offset]
    weights = np.ones(n, dtype=np.float64)
    for i in range(n):
        if active_mask[i]:
            end = min(i + int(offsets_arr[i]), n - 1)
            c_slice = concurrent[i:end + 1]
            # Protection : c_slice[0] >= 1 garanti car i est dans ses propres intervalles
            c_safe = np.where(c_slice > 0, c_slice, 1)
            weights[i] = float(np.mean(1.0 / c_safe))

    return pd.Series(weights, index=labels.index, name='sample_weight', dtype=np.float64)


# ═══════════════════════════════════════════════════════════════════════════════
# SCORING DE CONFLUENCE (12 catégories)
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_col(df: pd.DataFrame, col: str, default=0.0) -> pd.Series:
    """Retourne la colonne si elle existe, sinon une série de zéros."""
    if col in df.columns:
        return df[col].fillna(default)
    return pd.Series(default, index=df.index)


def _score_confluence(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    Calcule score_buy et score_sell (entiers >= 0) pour chaque barre
    en additionnant les signaux des 12 catégories.

    Retourne un DataFrame avec : score_buy, score_sell, setup_type
    """
    sb = pd.Series(0, index=df.index, dtype=np.int16)  # score BUY
    ss = pd.Series(0, index=df.index, dtype=np.int16)  # score SELL

    # ── 1. IMBALANCES ORDER FLOW ─────────────────────────────────────────────
    dvn  = _safe_col(df, "delta_bar_vol_norm")
    abi  = _safe_col(df, "ask_bid_imbalance")
    fs   = _safe_col(df, "finish_strength")
    di   = _safe_col(df, "diag_imbalance")

    sb += (dvn > 0.30).astype(int)
    sb += (abi > 0.20).astype(int)
    sb += (fs > 10).astype(int)
    sb += (di > 0.20).astype(int)

    ss += (dvn < -0.30).astype(int)
    ss += (abi < -0.20).astype(int)
    ss += (fs < -10).astype(int)
    ss += (di < -0.20).astype(int)

    # ── 2. DIVERGENCES ───────────────────────────────────────────────────────
    dd    = _safe_col(df, "delta_divergence")
    cvd_d = _safe_col(df, "cvd_day_dir")
    ddd   = _safe_col(df, "delta_day_dir")
    rab   = _safe_col(df, "rvol_absorb_buy")
    ras   = _safe_col(df, "rvol_absorb_sell")

    sb += (dd == 1).astype(int)
    sb += rab.astype(int)
    sb += ((cvd_d == 1) & (ddd == 1)).astype(int)   # alignement CVD+delta buy

    ss += (dd == -1).astype(int)
    ss += ras.astype(int)
    ss += ((cvd_d == -1) & (ddd == -1)).astype(int) # alignement CVD+delta sell

    # ── 3. DOUBLE TOP / DOUBLE BOTTOM ────────────────────────────────────────
    rh_cnt  = _safe_col(df, "retest_high_count")
    rl_cnt  = _safe_col(df, "retest_low_count")
    rh_div  = _safe_col(df, "retest_high_delta_div")
    rl_div  = _safe_col(df, "retest_low_delta_div")
    bsrh    = _safe_col(df, "bars_since_retest_high", default=999)
    bsrl    = _safe_col(df, "bars_since_retest_low",  default=999)

    # Double Top → SELL setup
    ss += ((rh_cnt >= 2) & (rh_div == 1)).astype(int)
    ss += ((bsrh <= 5) & (rh_cnt >= 2)).astype(int)   # retest récent = +1 bonus

    # Double Bottom → BUY setup
    sb += ((rl_cnt >= 2) & (rl_div == 1)).astype(int)
    sb += ((bsrl <= 5) & (rl_cnt >= 2)).astype(int)

    # ── 4. NIVEAUX CLÉS MENTHORQ ─────────────────────────────────────────────
    dmh    = _safe_col(df, "dist_mq_hvl").abs()
    dmc    = _safe_col(df, "dist_mq_call").abs()
    dmp    = _safe_col(df, "dist_mq_put").abs()
    gfz    = _safe_col(df, "bool_gex_flip_zone")
    nwd    = _safe_col(df, "next_wall_dist_ticks").abs()
    nwc    = _safe_col(df, "next_wall_is_call")

    # HVL proche = zone de flip → favorable dans les deux sens
    sb += (dmh < 20).astype(int)
    ss += (dmh < 20).astype(int)

    # Prix proche Put Support → BUY
    sb += (dmp < 15).astype(int)
    # Prix proche Call Resistance → SELL
    ss += (dmc < 15).astype(int)

    sb += gfz.astype(int)
    ss += gfz.astype(int)

    # Mur gamma proche → signal dans la direction du mur
    sb += ((nwd < 20) & (nwc == 0)).astype(int)   # prochain mur = PUT (support)
    ss += ((nwd < 20) & (nwc == 1)).astype(int)   # prochain mur = CALL (résistance)

    # ── 5. VOLUME PROFILE ────────────────────────────────────────────────────
    dvpoc    = _safe_col(df, "dist_cur_vpoc").abs()
    dvah     = _safe_col(df, "dist_cur_vah").abs()
    dval     = _safe_col(df, "dist_cur_val").abs()
    rp       = _safe_col(df, "range_pos")
    icva     = _safe_col(df, "inside_cur_va")
    dpvpoc   = _safe_col(df, "dist_prev_vpoc").abs()
    bva      = _safe_col(df, "bars_in_va")

    # Magnétisme VPOC
    sb += (dvpoc < 10).astype(int)
    ss += (dvpoc < 10).astype(int)

    # Support VAL → BUY
    sb += (dval < 8).astype(int)
    # Résistance VAH → SELL
    ss += (dvah < 8).astype(int)

    # Position dans le range
    sb += (rp < 20).astype(int)    # bas du range = zone BUY
    ss += (rp > 80).astype(int)    # haut du range = zone SELL

    # Breakout hors VA après consolidation longue
    sb += ((icva == 0) & (bva > 20) & (rp > 50)).astype(int)
    ss += ((icva == 0) & (bva > 20) & (rp < 50)).astype(int)

    # PVPOC = niveau très fort
    sb += (dpvpoc < 15).astype(int)
    ss += (dpvpoc < 15).astype(int)

    # ── 6. VWAP CONTEXT ──────────────────────────────────────────────────────
    vws10  = _safe_col(df, "vwap_slope_10")
    dvwap  = _safe_col(df, "dist_vwap_d").abs()
    vta    = _safe_col(df, "vwap_triple_align")
    abvd   = _safe_col(df, "bool_above_vwap_d")
    abvw   = _safe_col(df, "bool_above_vwap_w")

    sb += (vws10 > 0.5).astype(int)    # slope haussière
    ss += (vws10 < -0.5).astype(int)   # slope baissière

    sb += (dvwap < 5).astype(int)      # sur le VWAP = pivot dans les deux sens
    ss += (dvwap < 5).astype(int)

    sb += (vta == 1).astype(int)       # ultra bullish
    ss += (vta == -1).astype(int)      # ultra bearish

    # Divergence D/W VWAP = signal de rotation
    sb += ((abvd == 1) & (abvw == 0)).astype(int)   # prix > D mais < W → retour probable haut
    ss += ((abvd == 0) & (abvw == 1)).astype(int)   # prix < D mais > W → retour probable bas

    # ── 7. BATAILLE NAVALE (BN) ──────────────────────────────────────────────
    bn_lu  = _safe_col(df, "bn_long_up")
    bn_ld  = _safe_col(df, "bn_long_dn")
    bn_sb  = _safe_col(df, "bn_score_bull")
    bn_sb2 = _safe_col(df, "bn_score_bear")
    bn_cu2 = _safe_col(df, "bn_color_up_2")
    bn_cd2 = _safe_col(df, "bn_color_dn_2")
    bn_aa  = _safe_col(df, "bn_absorb_ask")
    bn_ab  = _safe_col(df, "bn_absorb_bid")
    bn_vu  = _safe_col(df, "bn_volume_up")
    bn_vd  = _safe_col(df, "bn_volume_dn")

    sb += ((bn_lu == 1) & (bn_sb > 0.8)).astype(int)
    ss += ((bn_ld == 1) & (bn_sb2 > 0.8)).astype(int)
    sb += bn_cu2.astype(int)                    # double stack bullish
    ss += bn_cd2.astype(int)                    # double stack bearish
    sb += bn_aa.astype(int)                     # absorption ASK → reversal buy
    ss += bn_ab.astype(int)                     # absorption BID → reversal sell
    sb += bn_vu.astype(int)
    ss += bn_vd.astype(int)

    # ── 8. RVOL ──────────────────────────────────────────────────────────────
    rv      = _safe_col(df, "rvol")
    rvz     = _safe_col(df, "rvol_zscore")
    rvb     = _safe_col(df, "rvol_buy")
    rvs     = _safe_col(df, "rvol_sell")

    sb += ((rv > 2.0) & (rvb == 1)).astype(int)
    ss += ((rv > 2.0) & (rvs == 1)).astype(int)
    sb += ((rvz > 2.0) & (rvb == 1)).astype(int)
    ss += ((rvz > 2.0) & (rvs == 1)).astype(int)

    # ── 9. OPEN TYPE & DAY TYPE ──────────────────────────────────────────────
    ot   = _safe_col(df, "open_type")
    dt   = _safe_col(df, "day_type")
    tdp  = _safe_col(df, "trend_day_probability")
    r80  = _safe_col(df, "rule_80pct")
    od   = _safe_col(df, "open_direction")

    # Open Drive (types 3,4,5 selon DMP_OpenType.h : OD_UP=3 OD_DN=4 OTD_UP=5...)
    sb += ((ot.isin([3, 5])) & (od == 1)).astype(int)
    ss += ((ot.isin([4, 6])) & (od == -1)).astype(int)

    # Open Test Drive → reversal (types 1,2)
    sb += ((ot.isin([1, 2])) & (od == -1)).astype(int)   # OTD sell → reversal buy
    ss += ((ot.isin([1, 2])) & (od == 1)).astype(int)    # OTD buy → reversal sell

    # Trend day
    sb += ((dt == 1) & (od == 1)).astype(int)
    ss += ((dt == 1) & (od == -1)).astype(int)
    sb += (tdp > 0.5).astype(int)
    ss += (tdp > 0.5).astype(int)

    sb += r80.astype(int)
    ss += r80.astype(int)

    # ── 10. SWING / STRUCTURE ────────────────────────────────────────────────
    nsh   = _safe_col(df, "new_swing_high")
    nsl   = _safe_col(df, "new_swing_low")
    dsh   = _safe_col(df, "dist_swing_high")
    dsl   = _safe_col(df, "dist_swing_low")
    pvsm  = _safe_col(df, "price_vs_swing_mid")

    sb += nsh.astype(int)       # breakout haussier
    ss += nsl.astype(int)       # breakout baissier
    sb += (dsh.abs() < 5).astype(int)
    ss += (dsl.abs() < 5).astype(int)
    sb += (pvsm > 0).astype(int)   # prix au-dessus du mid du swing
    ss += (pvsm < 0).astype(int)

    # ── 11. HVN / LVN ────────────────────────────────────────────────────────
    lva  = _safe_col(df, "dist_session_lvn_above")
    hvb  = _safe_col(df, "dist_session_hvn_below")
    lvb  = _safe_col(df, "lvn_between")
    hvbt = _safe_col(df, "hvn_between")

    sb += (lva < 20).astype(int)    # LVN au-dessus = prix traverse vite → BUY
    sb += (hvb < 20).astype(int)    # HVN en-dessous = support fort → BUY
    sb += lvb.astype(int)           # LVN entre prix et TP → chemin dégagé
    ss += hvbt.astype(int)          # HVN entre prix et TP → obstacle SELL

    # ── 12. PROFILE SHAPE ────────────────────────────────────────────────────
    ps    = _safe_col(df, "profile_shape")
    pocp  = _safe_col(df, "poc_position")
    idd   = _safe_col(df, "is_double_dist")
    ps_sk = _safe_col(df, "profile_skew")

    sb += (ps == 1).astype(int)          # P-shape → distribution haussière
    ss += (ps == 2).astype(int)          # b-shape → distribution baissière
    sb += (pocp < 0.3).astype(int)       # POC bas → structure haussière
    ss += (pocp > 0.7).astype(int)       # POC haut → structure baissière
    sb += (idd == 1).astype(int)         # double distribution
    ss += (idd == 1).astype(int)

    sb += (ps_sk < -0.2).astype(int)     # skew négatif = pression baissière → BUY reversal
    ss += (ps_sk > 0.2).astype(int)      # skew positif = pression haussière → SELL reversal

    # ── SETUP TYPE (signal dominant) ─────────────────────────────────────────
    setup_type = _build_setup_type(df, sb, ss)

    return pd.DataFrame({
        "score_buy":  sb,
        "score_sell": ss,
        "setup_type": setup_type,
    }, index=df.index)


def _build_setup_type(df: pd.DataFrame, score_buy: pd.Series,
                      score_sell: pd.Series) -> pd.Series:
    """
    Détermine le type de setup dominant pour chaque barre.
    Logique : premier signal fort identifié dans l'ordre de priorité.
    """
    setup = pd.Series("NONE", index=df.index)

    # Helpers
    def col(c, default=0.0):
        return _safe_col(df, c, default)

    # --- Double Top / Bottom (priorité 1 — setup structurel fort) ---
    dt_sell = (col("retest_high_count") >= 2) & (col("retest_high_delta_div") == 1)
    db_buy  = (col("retest_low_count")  >= 2) & (col("retest_low_delta_div")  == 1)
    setup = setup.where(~dt_sell, "DOUBLE_TOP_DIV")
    setup = setup.where(~db_buy,  "DOUBLE_BOT_DIV")

    # --- Absorption RVOL (priorité 2 — signal institutionnel) ---
    setup = setup.where(~(col("rvol_absorb_buy")  == 1), "RVOL_ABSORB_BUY")
    setup = setup.where(~(col("rvol_absorb_sell") == 1), "RVOL_ABSORB_SELL")

    # --- Open Drive (priorité 3 — setup journalier fort) ---
    ot = col("open_type")
    od = col("open_direction")
    setup = setup.where(~((ot.isin([3, 5])) & (od == 1)),  "OPEN_DRIVE_LONG")
    setup = setup.where(~((ot.isin([4, 6])) & (od == -1)), "OPEN_DRIVE_SHORT")

    # --- Rejet VAH / VAL ---
    setup = setup.where(~(col("dist_cur_vah").abs() < 8),  "VAH_REJECTION")
    setup = setup.where(~(col("dist_cur_val").abs() < 8),  "VAL_BOUNCE")

    # --- BN Long (priorité 5) ---
    setup = setup.where(~((col("bn_long_up") == 1) & (col("bn_score_bull") > 0.8)), "BN_LONG_UP")
    setup = setup.where(~((col("bn_long_dn") == 1) & (col("bn_score_bear") > 0.8)), "BN_LONG_DN")

    # --- Divergence Delta (priorité 6) ---
    setup = setup.where(~(col("delta_divergence") == 1),  "DELTA_DIV_BUY")
    setup = setup.where(~(col("delta_divergence") == -1), "DELTA_DIV_SELL")

    # --- RVOL spike ---
    setup = setup.where(
        ~((col("rvol") > 2.0) & (col("rvol_buy")  == 1)), "RVOL_SPIKE_BUY")
    setup = setup.where(
        ~((col("rvol") > 2.0) & (col("rvol_sell") == 1)), "RVOL_SPIKE_SELL")

    # --- VWAP triple align ---
    setup = setup.where(~(col("vwap_triple_align") == 1),  "VWAP_TRIPLE_BULL")
    setup = setup.where(~(col("vwap_triple_align") == -1), "VWAP_TRIPLE_BEAR")

    # --- Regime par défaut basé sur le score ---
    is_buy_dominated  = (score_buy  > score_sell) & (score_buy  >= 2)
    is_sell_dominated = (score_sell > score_buy)  & (score_sell >= 2)
    setup = setup.where(~((setup == "NONE") & is_buy_dominated),  "CONFLUENCE_BUY")
    setup = setup.where(~((setup == "NONE") & is_sell_dominated), "CONFLUENCE_SELL")

    return setup


# ═══════════════════════════════════════════════════════════════════════════════
# FILTRE RTH + MARGE OPEN/CLOSE
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_rth_margin_filter(df: pd.DataFrame, cfg: LabelConfig) -> pd.Series:
    """
    Retourne un masque booléen True = barre éligible au label.

    Sessions incluses : US + London  (Asia exclue)
    Critères :
    - session_id IN ["US", "London"]  — Asia toujours exclue
    - Pas dans les MARGIN_OPEN_BARS premières barres par session/jour
    - Pas dans les MARGIN_CLOSE_BARS dernières barres par session/jour
    - Pas dans les N dernières barres globales (pas assez de futur)
    """
    # Sessions US + London (Asia exclue)
    VALID_SESSIONS = {"US", "London"}

    if "session_id" in df.columns:
        mask_us = df["session_id"].isin(VALID_SESSIONS)
    elif "session" in df.columns:
        # session == 2 = US, session == 1 = London (convention DMP)
        mask_us = df["session"].isin([1, 2])
    else:
        mask_us = pd.Series(True, index=df.index)

    # Travailler sur les positions (entiers) pour éviter les problèmes d'index dupliqués
    n = len(df)
    valid_arr = mask_us.values.copy()   # bool array positionnel

    # Date par barre (pour grouper par jour)
    if "datetime_et" in df.columns:
        dates = pd.to_datetime(df["datetime_et"]).dt.date.values
    else:
        dates = pd.to_datetime(df.index).date

    # Marge ouverture / fermeture : par jour et par session valide
    # Grouper les positions valides (session US ou London) par date
    from collections import defaultdict
    day_positions = defaultdict(list)
    for i in range(n):
        if valid_arr[i]:
            day_positions[dates[i]].append(i)

    # Appliquer les marges
    for positions in day_positions.values():
        # Exclure les N premières barres de la session
        for i in positions[:cfg.MARGIN_OPEN_BARS]:
            valid_arr[i] = False
        # Exclure les N dernières barres de la session
        for i in positions[-cfg.MARGIN_CLOSE_BARS:]:
            valid_arr[i] = False

    # Exclure les dernières N barres globales (pas assez de futur)
    for i in range(max(0, n - cfg.FORWARD_BARS - 1), n):
        valid_arr[i] = False

    return pd.Series(valid_arr, index=df.index)


# ═══════════════════════════════════════════════════════════════════════════════
# LABELER PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def label_dataframe(df: pd.DataFrame, symbol: str,
                    cfg: LabelConfig = None) -> pd.DataFrame:
    """
    Label un DataFrame complet (multi-jours possible).

    Args:
        df      : DataFrame produit par DmpReader
        symbol  : "ES" ou "NQ"
        cfg     : LabelConfig (utilise les défauts si None)

    Returns:
        DataFrame avec colonnes supplémentaires :
            label               : +1 / -1 / 0
            label_quality       : 0-5 (nb signaux confluents)
            setup_type          : string du setup dominant
            max_favorable_pts   : mouvement max favorable (pts)
            max_adverse_pts     : mouvement max adverse (pts)
            valid_bar           : bool (True = barre éligible RTH)
    """
    if cfg is None:
        cfg = LabelConfig()

    if df.empty:
        return df

    sym      = symbol.upper()
    tick     = cfg.TICK_SIZE.get(sym, 0.25)
    tp_pts   = cfg.TP_TICKS.get(sym, 9)  * tick
    sl_pts   = cfg.SL_TICKS.get(sym, 5)  * tick

    # 1. Simulation TP/SL sur l'ensemble du DataFrame
    #    (toutes sessions pour avoir assez de futur pour les barres de fin de session)
    #    Schéma 3.7.1+ : utilise bar_high/bar_low si disponibles
    #    Schéma 3.7.0  : fallback sur price (close)
    has_hl = ("bar_high" in df.columns) and ("bar_low" in df.columns)
    has_sd3u = "dist_vwap_d_sd3u" in df.columns
    labels, realized_pts, hl_mode, exit_offsets = _simulate_tpsl(
        prices  = df["price"],
        tp_pts  = tp_pts,
        sl_pts  = sl_pts,
        n_bars  = cfg.FORWARD_BARS,
        highs   = df["bar_high"] if has_hl else None,
        lows    = df["bar_low"]  if has_hl else None,
    )
    # schema_str et hl_pct : utilisés dans run_all pour le rapport par fichier
    schema_str = "3.7.2" if has_sd3u else ("3.7.1" if has_hl else "3.7.0")
    hl_pct     = float(hl_mode.mean() * 100)

    # 2. Calcul du score de confluence
    scores = _score_confluence(df, sym)

    # 3. Filtre sessions valides + marges open/close
    valid_mask = _apply_rth_margin_filter(df, cfg)

    # 4. Invalider les labels hors sessions valides → HOLD
    labels_filtered = labels.copy()
    labels_filtered[~valid_mask] = 0

    # 5. Quality = conviction directionnelle = |score_buy - score_sell|
    #    0 = signal équilibré/confus | 5+ = forte conviction directionnelle
    #    C'est plus discriminatif que max(score_buy, score_sell) car une barre
    #    avec score_buy=10 et score_sell=9 n'est PAS un bon signal.
    conviction = (scores["score_buy"] - scores["score_sell"]).abs()
    label_quality = conviction.clip(upper=cfg.QUALITY_MAX).astype(np.int8)
    label_quality[~valid_mask] = 0

    # 6. Détection des sessions partielles
    #    Les jours listés dans PARTIAL_SESSION_DATES ont un symbole croisé
    #    qui a fermé plus tôt (ex: Vendredi Saint — NQ absent 37 barres ES).
    #    On marque toutes leurs barres valid=False pour éviter des features
    #    intermarket NaN dans le pipeline ML.
    if "datetime_et" in df.columns:
        date_strs = pd.to_datetime(df["datetime_et"]).dt.strftime("%Y%m%d")
    else:
        date_strs = pd.to_datetime(df.index).strftime("%Y%m%d")
    partial_mask = date_strs.isin(cfg.PARTIAL_SESSION_DATES).values

    if partial_mask.any():
        valid_mask = valid_mask & ~pd.Series(partial_mask, index=df.index)
        labels_filtered[~valid_mask] = 0
        label_quality[~valid_mask]   = 0

    # 7. Sample weights par uniqueness temporelle (Lopez AFML ch.4)
    #    Calcul fait sur labels_filtered pour exclure les barres hors RTH /
    #    partial session du calcul de concurrence. Les barres invalides auront
    #    weight=1.0 (valeur par defaut, non utilisee au training car label=0).
    sample_weights = compute_label_uniqueness(labels_filtered, exit_offsets)

    # 8. Assembler le résultat
    result = df.copy()
    result["label"]            = labels_filtered
    result["label_quality"]    = label_quality
    result["setup_type"]       = scores["setup_type"]
    result["score_buy"]        = scores["score_buy"]
    result["score_sell"]       = scores["score_sell"]
    result["realized_pts"]     = realized_pts
    result["tp_pts"]           = tp_pts
    result["sl_pts"]           = sl_pts
    result["hl_mode"]          = hl_mode        # True = simulation avec bar_high/bar_low réels
    result["schema"]           = schema_str     # "3.7.0" ou "3.7.1"
    result["valid_bar"]        = valid_mask
    result["partial_session"]  = pd.Series(partial_mask, index=df.index)
    result["sample_weight"]    = sample_weights  # Lopez AFML ch.4
    result["exit_offset"]      = exit_offsets    # Nb barres avant resolution TP/SL/timeout

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# STATISTIQUES DE RAPPORT
# ═══════════════════════════════════════════════════════════════════════════════

def print_stats(df_labeled: pd.DataFrame, symbol: str):
    """Affiche les statistiques de distribution des labels."""
    valid = df_labeled[df_labeled["valid_bar"]]
    n     = len(valid)

    if n == 0:
        print(f"[{symbol}] Aucune barre valide.")
        return

    print(f"\n{'='*60}")
    print(f" STATISTIQUES LABELS — {symbol}  ({n} barres RTH valides)")
    print(f"{'='*60}")

    # Distribution globale
    vc = valid["label"].value_counts().sort_index()
    for lbl, cnt in vc.items():
        name = {1: "BUY (+1)", -1: "SELL (-1)", 0: "HOLD (0)"}.get(lbl, str(lbl))
        pct  = cnt / n * 100
        print(f"  {name:15s}: {cnt:5d}  ({pct:5.1f}%)")

    # Distribution par qualité
    q_max = int(df_labeled["label_quality"].max()) if len(df_labeled) > 0 else 10
    print(f"\n--- Distribution par label_quality (0-{q_max}) ---")
    for q in range(0, q_max + 1):
        sub = valid[valid["label_quality"] == q]
        if len(sub) == 0:
            continue
        vc_q = sub["label"].value_counts()
        b  = vc_q.get(1, 0)
        s  = vc_q.get(-1, 0)
        h  = vc_q.get(0, 0)
        total_bs = b + s
        wr = (b + s) / len(sub) * 100 if len(sub) > 0 else 0
        print(f"  Qualité {q}: {len(sub):4d} barres | "
              f"BUY={b:3d} SELL={s:3d} HOLD={h:4d} | "
              f"Signal={wr:.1f}%")

    # Win rate par setup_type (barres BUY ou SELL uniquement)
    signal_bars = valid[valid["label"] != 0]
    if len(signal_bars) > 0:
        print(f"\n--- Win rate par setup_type (top 10) ---")
        print(f"  (barre labellée BUY ou SELL uniquement, n={len(signal_bars)})")
        by_setup = (
            signal_bars
            .groupby("setup_type")["label"]
            .agg(count="count")
            .sort_values("count", ascending=False)
            .head(10)
        )
        for st, row in by_setup.iterrows():
            print(f"  {st:30s}: {int(row['count']):4d} barres")

    # PnL simulé par label
    tp = valid["tp_pts"].iloc[0] if "tp_pts" in valid.columns else float("nan")
    sl = valid["sl_pts"].iloc[0] if "sl_pts" in valid.columns else float("nan")
    rr = tp / sl if sl > 0 else float("nan")
    print(f"\n--- Simulation TP/SL (TP={tp:.2f}pts SL={sl:.2f}pts RR={rr:.1f}) ---")
    for lbl, name in [(1, "BUY "), (-1, "SELL"), (0, "HOLD")]:
        sub = valid[valid["label"] == lbl]
        if len(sub) == 0:
            continue
        if "realized_pts" in sub.columns:
            avg_r = sub["realized_pts"].dropna().mean()
            print(f"  {name}: {len(sub):4d} barres | PnL_sim avg={avg_r:+.2f}pts")
        else:
            print(f"  {name}: {len(sub):4d} barres")

    # Stats par session (US vs London)
    if "session_id" in df_labeled.columns:
        print(f"\n--- Comparaison par session ---")
        for sess in ["US", "London"]:
            sub_sess = valid[valid["session_id"] == sess]
            if len(sub_sess) == 0:
                continue
            vc_s = sub_sess["label"].value_counts()
            b_s  = vc_s.get(1, 0)
            s_s  = vc_s.get(-1, 0)
            h_s  = vc_s.get(0, 0)
            sig_rate = (b_s + s_s) / len(sub_sess) * 100
            print(f"  {sess:8s}: {len(sub_sess):4d} barres | "
                  f"BUY={b_s:3d} SELL={s_s:3d} HOLD={h_s:4d} | "
                  f"Signal={sig_rate:.1f}%")


# ═══════════════════════════════════════════════════════════════════════════════
# SAUVEGARDE
# ═══════════════════════════════════════════════════════════════════════════════

def save_labels(df_labeled: pd.DataFrame, symbol: str, date_str: str,
                cfg: LabelConfig = None):
    """
    Sauvegarde les labels en parquet et CSV.

    Args:
        df_labeled : DataFrame avec colonnes label_*
        symbol     : "ES" ou "NQ"
        date_str   : "20260326"
        cfg        : LabelConfig
    """
    if cfg is None:
        cfg = LabelConfig()

    out_dir = cfg.OUTPUT_PATH
    out_dir.mkdir(parents=True, exist_ok=True)

    # Colonnes label uniquement + ts pour jointure
    label_cols = [
        "ts", "price", "valid_bar", "partial_session",
        "label", "label_quality", "setup_type",
        "score_buy", "score_sell",
        "realized_pts", "tp_pts", "sl_pts",
        "hl_mode", "schema",
        "sample_weight", "exit_offset",   # Lopez AFML ch.4 — uniqueness weights
    ]
    out = df_labeled[[c for c in label_cols if c in df_labeled.columns]].copy()

    stem = f"{date_str}_{symbol}"
    parquet_path = out_dir / f"{stem}_labels.parquet"
    csv_path     = out_dir / f"{stem}_labels.csv"

    out.to_parquet(parquet_path, index=True)
    out.to_csv(csv_path, index=True)

    print(f"  Sauvegardé: {parquet_path}")
    print(f"  Sauvegardé: {csv_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def run_all(symbol: str = "ES", cfg: LabelConfig = None):
    """
    Lance le labeler sur TOUS les fichiers disponibles pour un symbole.

    Args:
        symbol : "ES" ou "NQ"
        cfg    : LabelConfig (défauts si None)
    """
    if cfg is None:
        cfg = LabelConfig()

    reader  = DmpReader(str(cfg.DATA_PATH))
    data_dir = cfg.DATA_PATH / symbol.upper()

    if not data_dir.exists():
        print(f"[ERREUR] Dossier introuvable: {data_dir}")
        return

    # Lister tous les fichiers JSONL disponibles
    files = sorted(data_dir.glob(f"*_{symbol.upper()}.jsonl"))
    if not files:
        print(f"[ERREUR] Aucun fichier JSONL dans {data_dir}")
        return

    print(f"\n[{symbol}] {len(files)} fichier(s) trouvé(s) dans {data_dir}")

    all_labeled = []

    for fpath in files:
        date_str = fpath.stem.split("_")[0]   # "20260326"
        print(f"\n--- Traitement {date_str}_{symbol}.jsonl ---")

        df = reader.load(symbol, date_str)
        if df.empty:
            print(f"  [SKIP] Fichier vide.")
            continue
        if len(df) < 50:
            print(f"  [SKIP] Jour incomplet ({len(df)} barres < 50) — weekend ou partiel.")
            continue

        n_total = len(df)
        n_us    = (df["session_id"] == "US").sum() if "session_id" in df.columns else 0
        print(f"  {n_total} barres | US={n_us}")

        # Labeling
        df_labeled = label_dataframe(df, symbol, cfg)

        # Rapport par fichier — schema, hl_mode, partial_session
        sch    = df_labeled["schema"].iloc[0] if "schema" in df_labeled.columns else "?"
        hlp    = df_labeled["hl_mode"].mean() * 100 if "hl_mode" in df_labeled.columns else 0
        is_partial = df_labeled["partial_session"].any() if "partial_session" in df_labeled.columns else False
        partial_tag = "  [SESSION PARTIELLE — intermarket NaN probable]" if is_partial else ""

        valid_day = df_labeled[df_labeled["valid_bar"]]
        if len(valid_day) > 0:
            vc = valid_day["label"].value_counts()
            b  = vc.get(1, 0)
            s  = vc.get(-1, 0)
            h  = vc.get(0, 0)
            print(f"  Schema={sch} HL={hlp:.0f}% | "
                  f"Labels valides={len(valid_day)} BUY={b} SELL={s} HOLD={h}{partial_tag}")
        else:
            print(f"  Schema={sch} | Aucune barre valide{partial_tag}")

        # Sauvegarde journalière
        save_labels(df_labeled, symbol, date_str, cfg)
        all_labeled.append(df_labeled)

    if not all_labeled:
        print(f"[{symbol}] Aucune donnée traitée.")
        return

    # DataFrame complet multi-jours
    df_all = pd.concat(all_labeled)
    print_stats(df_all, symbol)

    # Sauvegarde fichier global
    out_path = cfg.OUTPUT_PATH / f"ALL_{symbol}_labels.parquet"
    save_cols = [c for c in [
        "ts", "price", "valid_bar", "partial_session",
        "label", "label_quality", "setup_type",
        "score_buy", "score_sell",
        "realized_pts", "tp_pts", "sl_pts",
        "hl_mode", "schema",
        "sample_weight", "exit_offset",   # Lopez AFML ch.4 — uniqueness weights
    ] if c in df_all.columns]
    df_all[save_cols].to_parquet(out_path, index=True)
    print(f"\n  Global sauvegardé: {out_path}")

    return df_all


# ═══════════════════════════════════════════════════════════════════════════════
# EXÉCUTION DIRECTE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cfg = LabelConfig()

    print("=" * 62)
    print("  MIA Labeler v2 -- Simulation TP/SL path-aware")
    print(f"  ES: TP={cfg.TP_TICKS['ES']}t SL={cfg.SL_TICKS['ES']}t | "
          f"NQ: TP={cfg.TP_TICKS['NQ']}t SL={cfg.SL_TICKS['NQ']}t | "
          f"RR=1.8 | Fwd={cfg.FORWARD_BARS}b")
    print(f"  Schema: 3.7.0 (fallback close) ou 3.7.1 (bar_high/low) auto-detecte")
    print(f"  Sessions: US + London  |  Partielles: {cfg.PARTIAL_SESSION_DATES}")
    print("=" * 62)

    # Lancer sur ES puis NQ
    for sym in ["ES", "NQ"]:
        run_all(sym, cfg)

    print("\n[DONE] Labeling terminé. Fichiers dans DATA/LABELS/")
