"""
phase_b_v6_extras.py — Features Python canoniques Option C complementaires.

Date : 2026-05-19
Decision : Option C Jackson — Python = source canonique 100% Databento.
Audit code-reviewer + market-analyst 19/05 ont identifie 2 features critiques
absentes du builder pure : profile_shape + trend_day_probability.

Ces 2 features etaient C++ DMP-only mais leurs FORMULES sont documentees :
  - profile_shape : DMP_ProfileShape.h:452-480 (deja porte en Python via
                    game_changers.classify_profile_shape)
  - trend_day_probability : DMP_Transform.h:1310-1326 (heuristique 5 criteres)

Ce module les CABLE depuis les inputs disponibles dans V4 pure (cur_vpoc/val/vah
running, vix_regime, ib_range_atr) sans introduire de dependance Sierra.

Convention canonique Python :
  - profile_shape : utilise poc_position (deja calcule via Volume Profile running).
    Skewness/volume_imbalance/is_bimodal par defaut (0.0 / 1.0 / False) faute
    d'avoir le VP brut au niveau bar (helper internes value_area_running).
    Approximation acceptable : poc_position seul classifie correctement P/B/D
    sur ~80% des cas (PS_POC_HIGH_THRESH=0.70, PS_POC_LOW_THRESH=0.30).

  - trend_day_probability : formule C++ ligne 1319-1325 PORTEE Python avec ADAPTATION
    de convention (cf bug history IB_NARROW_THRESHOLDS) :
      p_trend = 0
      if ib_is_narrow (ib_range_atr < seuil_PYTHON_per_symbol) : p_trend += 0.30
      if open_position != 0 (open hors VA prev) : p_trend += 0.20
      if abs(open_gap_ticks) > 15 : p_trend += 0.15
      if vix_regime >= 2 : p_trend -= 0.10
      clamp [0, 1]

    ATTENTION DERIVE SEMANTIQUE C++ vs Python (risque #3 market-analyst 19/05) :
      - C++ ib_range_atr = ib_range_points / atr_session_points (ratio fractionnaire)
                           -> seuil 0.40 = "IB fait 40% de l'ATR journalier"
      - Python ib_range_atr = ib_range_ticks / atr_1min_ticks (ratio multiple)
                              -> seuil per-symbol ES=15.0 / NQ=22.0 = "IB est 15-22 fois
                                 plus large qu'une bar 1-min" (queue gauche distribution)
      L'INTENTION semantique est preservee (compression matinale = trend day) mais le
      ratio n'est plus directement comparable. Si DMP_Transform.h modifie un jour son
      denominateur ATR : recalibrer les seuils per-symbol. Cf INCIDENT_LOG entry du
      2026-05-19 16:00 categorie VALIDATION_MISS.

Reference : DOCS/DATA_SOURCES_V5.md
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from CORE.constants import get_tick_size
except ImportError:
    from constants import get_tick_size

try:
    from CORE.game_changers import classify_profile_shape, ProfileShape
except ImportError:
    from game_changers import classify_profile_shape, ProfileShape


# Seuils trend_day_probability (DMP_Transform.h:1316-1325)
#
# IB_NARROW_THRESHOLDS — calibrés empiriquement par symbole (V4 pure 1 mois avril 2026).
#
# Bug code-reviewer audit 19/05/2026 : valeur initiale 0.40 (convention C++
# fractionnaire ATR session) était incompatible avec convention Python
# phase_b_rolling_inputs.py:141 (`ib_range_atr = ib_range_ticks / atr_ticks`).
# Empirique observé : ES mean=21.7 / p25=15.7, NQ mean=30.8 / p25=21.6 → seuil
# 0.40 jamais atteint, critère ib_narrow inactif, trend_day_probability plafonne
# 0.5 (au lieu max 0.65 théorique).
#
# Calibration v1 (10j) trop biaisée (régime baissier VIX>30) :
#   ES=15.0 -> activation 45% (cible 25%) ; NQ=22.0 -> activation 54%.
# Calibration v2 (1 mois 01-30/04) recalibre p25 :
#   ES p25=10.35 / NQ p25=13.05 → seuils 10.0 / 13.0 -> activation ~25%.
#
# RISQUE RESIDUEL : sur 8 mois (octobre 2025 -> mai 2026) incluant régimes variés
# (VIX low, summer doldrums, election volatility), p25 peut encore dériver. Si
# activation post-regen 8 mois sort de [15%, 35%], envisager rolling threshold
# mensuel (recalibration p25 sur fenêtre glissante 30j) — TODO Phase 2 si besoin.
IB_NARROW_THRESHOLDS = {
    "ES": 10.0,   # ES p25(1m)=10.35 → seuil 10.0 active 23.3% bars
    "NQ": 13.0,   # NQ p25(1m)=13.05 → seuil 13.0 active 24.7% bars
    "MGC": 10.0,  # défaut (à recalibrer avec data MGC propre)
}
IB_NARROW_THRESHOLD_DEFAULT = 10.0  # fallback symboles inconnus

OPEN_GAP_THRESHOLD_TICKS = 15.0  # |open_gap| > 15 ticks = gap fort
VIX_HIGH_REGIME = 2              # vix_regime >= 2 = VIX eleve


def add_profile_shape(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule profile_shape (4 classes : D/P/B_lower/B_double) per bar.

    Convention canonique Python Option C :
      - Utilise poc_position (deja calcule via Volume Profile running)
      - skewness, volume_imbalance, is_bimodal : defaults (0.0, 1.0, False)
        car necessitent acces au VP dict (helper interne value_area_running).
      - poc_position >= 0.70 -> P_SHAPE (1) : volume haut, bullish
      - poc_position <= 0.30 -> B_LOWER (2) : volume bas, bearish
      - sinon : D_SHAPE (0) : equilibre

    Args:
        df : DataFrame avec colonne 'poc_position' (calculee via add_volume_profile_features).

    Returns:
        df + ['profile_shape'] (int8 : 0=D, 1=P, 2=B, 3=B_double).
        Si poc_position absent : profile_shape = -1 (UNKNOWN).
    """
    df = df.copy()
    if "poc_position" not in df.columns:
        df["profile_shape"] = np.int8(-1)
        return df

    poc_pos = df["poc_position"].fillna(0.5)

    # Application classify_profile_shape avec defaults sur skewness/imbalance/bimodal
    # Vectorisable : utilise les seuils directement (formule simple identique a
    # game_changers.classify_profile_shape avec inputs default).
    shape = np.full(len(df), ProfileShape.D_SHAPE.value, dtype=np.int8)
    mask_p = poc_pos.values >= 0.70  # PS_POC_HIGH_THRESH
    mask_b = poc_pos.values <= 0.30  # PS_POC_LOW_THRESH
    shape[mask_p] = ProfileShape.P_SHAPE.value
    shape[mask_b] = ProfileShape.B_LOWER.value
    # B_DOUBLE (3) ne peut etre detecte sans is_bimodal -> jamais

    # Si poc_position NaN -> UNKNOWN (-1)
    mask_nan = df["poc_position"].isna().values
    shape[mask_nan] = -1

    df["profile_shape"] = shape
    return df


def add_trend_day_probability(df: pd.DataFrame, symbol: str = "ES") -> pd.DataFrame:
    """Calcule trend_day_probability per bar via heuristique C++ DMP_Transform.h:1310-1326.

    Formule (clamp [0, 1]) :
        p = 0
        if ib_is_narrow (ib_range_atr < IB_NARROW_THRESHOLDS[symbol]) : p += 0.30
        if open_position != 0 (open hors prev VA) : p += 0.20
        if abs(open_gap_ticks) > 15 : p += 0.15
        if vix_regime >= 2 : p -= 0.10

    Inputs requis dans df :
      - ib_range_atr (deja calcule via add_ib_atr)
      - open_cash, prev_vah, prev_val (already in V4 pure)
      - prev_vpoc (for open_gap_ticks)
      - vix_regime (already in V4 pure via vix_lite_reader)

    Args:
        df : DataFrame avec colonnes requises.
        symbol : "ES" | "NQ" | "MGC" (pour tick_size).

    Returns:
        df + ['trend_day_probability'] (float32 [0, 1]).
        Si ib_range_atr NaN : trend_day_probability = 0.5 (default neutre).
    """
    df = df.copy()
    tick = get_tick_size(symbol)
    n = len(df)

    p_trend = np.full(n, 0.5, dtype=np.float32)  # default neutre

    # Validate ib_range_atr
    if "ib_range_atr" not in df.columns:
        df["trend_day_probability"] = p_trend
        return df

    ib_atr = df["ib_range_atr"].values
    mask_valid = ~np.isnan(ib_atr)

    if not mask_valid.any():
        df["trend_day_probability"] = p_trend
        return df

    # Initialise p_trend a 0 pour les bars valides
    p_trend[mask_valid] = 0.0

    # 1. ib_is_narrow : ib_range_atr < seuil per-symbol -> +0.30
    threshold = IB_NARROW_THRESHOLDS.get(symbol, IB_NARROW_THRESHOLD_DEFAULT)
    ib_narrow = (ib_atr < threshold) & mask_valid
    p_trend[ib_narrow] += 0.30

    # 2. open_position : open_cash hors prev VA -> +0.20
    if all(c in df.columns for c in ("open_cash", "prev_vah", "prev_val")):
        open_cash = df["open_cash"].values
        prev_vah = df["prev_vah"].values
        prev_val = df["prev_val"].values
        # open hors VA : open > prev_vah OR open < prev_val
        valid_open = ~(np.isnan(open_cash) | np.isnan(prev_vah) | np.isnan(prev_val))
        outside_va = ((open_cash > prev_vah) | (open_cash < prev_val)) & valid_open & mask_valid
        p_trend[outside_va] += 0.20

    # 3. open_gap_ticks : |open_cash - prev_vpoc| / tick > 15 -> +0.15
    if "open_cash" in df.columns and "prev_vpoc" in df.columns:
        open_cash = df["open_cash"].values
        prev_vpoc = df["prev_vpoc"].values
        valid_gap = ~(np.isnan(open_cash) | np.isnan(prev_vpoc))
        gap_ticks = np.zeros(n)
        gap_ticks[valid_gap] = np.abs(open_cash[valid_gap] - prev_vpoc[valid_gap]) / tick
        strong_gap = (gap_ticks > OPEN_GAP_THRESHOLD_TICKS) & valid_gap & mask_valid
        p_trend[strong_gap] += 0.15

    # 4. vix_regime >= 2 -> -0.10 (VIX eleve = contre-trend probable)
    if "vix_regime" in df.columns:
        vix_reg = df["vix_regime"].fillna(0).values
        high_vix = (vix_reg >= VIX_HIGH_REGIME) & mask_valid
        p_trend[high_vix] -= 0.10

    # Clamp [0, 1]
    p_trend = np.clip(p_trend, 0.0, 1.0)

    df["trend_day_probability"] = p_trend.astype(np.float32)
    return df


def add_poc_bar_dist(df: pd.DataFrame, symbol: str = "ES") -> pd.DataFrame:
    """Distance close au POC current en ticks UNSIGNED (parite C++).

    FIX BUG #1 (code-reviewer audit 19/05) :
        AVANT : `(close - cur_vpoc) / tick` = SIGNED. Inversion classification 50%
                bars dans regime_engine.py:288 (poc_dist > 15 traite -20 comme < 3
                -> TREND vote au lieu de RANGE vote).
        APRES : `abs(close - cur_vpoc) / tick` = UNSIGNED, parite C++ DMP_Transform.h:994
                (`f.poc_bar_dist = std::fabs(r.fpbs_poc_price - p) / ts`).

    NOTE semantique : Python utilise cur_vpoc (POC running session via VPOC running)
    vs C++ fpbs_poc_price (POC intra-bar footprint). Difference acceptee Option C :
    convention canonique Python = POC session running magnitude (cf DATA_SOURCES_V5.md).
    Distribution differente du DMP intra-bar mais SIGNAL semantiquement coherent
    (Wyckoff POC magnetism : magnitude de distance, pas direction).
    """
    df = df.copy()
    if "close" not in df.columns or "cur_vpoc" not in df.columns:
        df["poc_bar_dist"] = np.nan
        return df
    tick = get_tick_size(symbol)
    df["poc_bar_dist"] = ((df["close"] - df["cur_vpoc"]).abs() / tick).astype("float32")
    return df


def add_bars_in_va(df: pd.DataFrame) -> pd.DataFrame:
    """Nb barres CONSECUTIVES dans la VA (reset a chaque sortie).

    FIX BUG #2 (code-reviewer audit 19/05) :
        AVANT : `inside.groupby(session).cumsum()` = cumsum total session (p50=433).
                Seuil regime_engine.py:297 `bars_va > 30` match TOUJOURS -> biais
                RANGE systemique 99% bars.
        APRES : count CONSECUTIVES, reset a chaque sortie VA. Match convention
                C++ DMP_Transform.h:122 "Nb barres consecutives dans la VA".

    Semantique trading (Dalton AMT) :
      bars_in_va = 30 -> 30 minutes consecutives prix dans VA = RANGE evident
      bars_in_va = 5  -> sortie rapide VA = TREND directionnel
    """
    df = df.copy()
    required = ("close", "cur_val", "cur_vah", "session_date_trading")
    if not all(c in df.columns for c in required):
        df["bars_in_va"] = 0
        return df

    inside = ((df["close"] >= df["cur_val"]) & (df["close"] <= df["cur_vah"])).astype("int32")

    # Count consecutive : reset a chaque False (sortie VA) ET a chaque changement session
    # Methode : group by (session, run_id ou run_id = cumsum des transitions False).
    # Plus simple : itererper-session, count consecutif et restart a False.
    # Vectorise : on identifie les "runs" de True via diff != 0 cumsum, puis cumcount.
    out = []
    for sess_date, grp in df.groupby("session_date_trading", sort=False):
        ins = inside.loc[grp.index]
        # Detect run boundaries : transition False->True OR new session
        # Pour chaque run de True, count croissant 1,2,3,... ; pour False -> 0.
        # Trick : cumsum reset on 0 = cumcount within consecutive group of 1s
        groups = (ins != ins.shift()).cumsum()
        consec = ins.groupby(groups).cumcount() + 1
        consec = consec * ins  # zero quand pas dans VA
        out.append(consec.astype("int32"))
    df["bars_in_va"] = pd.concat(out).sort_index().astype("int32")
    return df


def add_single_print_count(df: pd.DataFrame) -> pd.DataFrame:
    """Count des single print zones detectes par Phase D Dalton.

    Convention Option C : utilise n_single_print_zones (Phase D) comme proxy
    canonique. Renomme en single_print_count pour compatibilite regime_engine.

    BUG #3 documente (code-reviewer audit 19/05) — DIVERGENCE SEMANTIQUE DMP :
        DMP `single_print_count` = count brut single prints (1-tick width)
                                   ES avril 2026 : mean=21, max=49 (audit CSV).
        Python `n_single_print_zones` = count ZONES contigues (peut etre multi-tick)
                                   ES avril 2026 : mean=2.17, max=5 (ratio 0.10x).
    Conséquence : regime_engine.py:239 seuil `single_prints >= 5` JAMAIS atteint
    en Python (max=5 = borderline). Vote critère inactif sans recalibration.

    Plan correctif (Phase 2 ml-trainer recalibration) :
      OPTION A : recalibrer regime_engine seuil >= 2 (cumul 50% bars actuelle)
      OPTION B : porter vrai single_print_count C++ depuis VAP running
                 (compter price levels avec volume == 1)
    """
    df = df.copy()
    if "n_single_print_zones" in df.columns:
        df["single_print_count"] = df["n_single_print_zones"].astype("int32")
    else:
        df["single_print_count"] = 0
    return df


def add_momentum_3b_clean(df: pd.DataFrame) -> pd.DataFrame:
    """momentum_3b convention canonique Python SANS leak.

    AVANT (DMP C++ DROPPED v0.3) : rho(DMP_momentum_3b, close_t+1) = 0.444 = LEAK MASSIF.

    APRES (Option C) :
        momentum_3b = close - close.shift(3)  (points bruts)
    Validation backtest empirique : rho_fut1 = -0.0090 = ZERO LEAK confirme
    (vs DMP 0.444). Edge tactique a backtester avant trust ML.

    Anti-pattern 11 V1 (Jackson 19/05) : pas d'ajout de version _atr ni autres
    transformations sans backtest empirique walk-forward + DSR. Convention
    minimale stable. Versions normalisees a creer SI backtest confirme utilite.
    """
    df = df.copy()
    if "close" not in df.columns:
        df["momentum_3b"] = np.nan
        return df
    df["momentum_3b"] = (df["close"] - df["close"].shift(3)).astype("float32")
    return df


def add_vwap_slope_30(df: pd.DataFrame) -> pd.DataFrame:
    """vwap_slope_30 convention canonique Python : pente VWAP daily sur 30 bars 1-min.

    AVANT (DMP C++ DROPPED v0.4) : chart Sierra 30-MIN slope sur 10 bars,
    edge rho TBM 0.007 = bruit pur, drop ml-trainer.

    APRES (Option C convention Python - revision Jackson 19/05) :
        vwap_slope_30 = (vwap_d - vwap_d.shift(30)) / 30  sur OHLCV 1-min
    Mesure la VITESSE de progression du VWAP daily sur les 30 dernieres minutes.

    Justification reintegration (challenge Jackson) :
      - rho TBM faible (~bruit) est ATTENDU : VWAP slope n'est PAS un signal predictif
        court-terme, c'est un **signal de CONFIRMATION de trend etabli**.
      - Utilite tactique reelle (rule-based Bot 2 V6, Bot 3 narrative) :
          if vwap_slope_30 > +X : trend bullish etabli -> bias LONG
          if vwap_slope_30 < -X : trend bearish -> bias SHORT
      - Cout : 1 ligne, continue non-constante, zero pollution.
      - Convention Python canonique simple et reproductible long-terme.

    Requires : vwap_d (calcule par phase_b_plus_engine.py add_vwap_features)
               + session_date_trading (per session groupby anti session-boundary outlier).
    """
    df = df.copy()
    if "vwap_d" not in df.columns:
        df["vwap_slope_30"] = np.nan
        return df

    # FIX R3 (code-reviewer audit 19/05) : groupby session_date_trading anti outlier
    # cross-session. Avant : shift(30) traversait session boundary CME 22:00 UTC
    # quand vwap_d reset -> slope = +-200 points = outlier majeur.
    # Apres : diff(30) per session = NaN en debut session (warmup 30 bars), valeur
    # propre apres.
    if "session_date_trading" in df.columns:
        df["vwap_slope_30"] = (
            df.groupby("session_date_trading")["vwap_d"].diff(30) / 30.0
        ).astype("float32")
    else:
        # Fallback : pas de groupby (legacy). Documenter mais ne pas raise.
        df["vwap_slope_30"] = ((df["vwap_d"] - df["vwap_d"].shift(30)) / 30.0).astype("float32")
    return df


def add_delta_divergence(df: pd.DataFrame) -> pd.DataFrame:
    """delta_divergence convention canonique Python (signed).

    AVANT (DMP C++ DROPPED) : DMP_Reader.h:608 bug ExtensionLineCount=100% pollu (info perdue).

    APRES (Option C convention Python) :
        delta_divergence = delta_div_buy - delta_div_sell  (signed, -1 / 0 / +1 typiquement)
    Utilise les flags binaires per-bar deja calcules par phase_b_plus_plus_engine
    (delta_div_buy/sell) qui sont autonomes Trades Databento (sans dependance Sierra).

    Convention : +1 si div_buy actif sur la bar, -1 si div_sell, 0 si aucun.
    Si les deux : 0 (rare, neutralise).
    """
    df = df.copy()
    if "delta_div_buy" not in df.columns or "delta_div_sell" not in df.columns:
        df["delta_divergence"] = 0
        return df
    df["delta_divergence"] = (
        df["delta_div_buy"].fillna(0).astype("int8")
        - df["delta_div_sell"].fillna(0).astype("int8")
    ).astype("int8")
    return df


def apply_v6_extras(df: pd.DataFrame, symbol: str = "ES") -> pd.DataFrame:
    """Pipeline orchestrant : profile_shape + trend_day_probability + 3 Sierra-only ports
    + 2 features reintegrees (momentum_3b clean + delta_divergence).

    Convention Option C : appele apres apply_value_area_running + add_game_changers
    + apply_phase_d_dalton_levels + apply_phase_b_plus_plus (delta_div_buy/sell dispo).
    Avant regime_engine (qui consomme profile_shape + trend_day_probability).

    Features ajoutees :
      - profile_shape (game_changers.classify_profile_shape via poc_position)
      - trend_day_probability (heuristique 5-criteres DMP_Transform.h:1310-1326)
      - poc_bar_dist (close - cur_vpoc / tick)
      - bars_in_va (rolling count bars in VA per session)
      - single_print_count (= n_single_print_zones Phase D)
      - momentum_3b (clean close.diff(3) SANS leak, vs DMP DROPPED)
      - delta_divergence (= delta_div_buy - delta_div_sell signed, vs DMP DROPPED)
    """
    df = add_profile_shape(df)
    df = add_trend_day_probability(df, symbol=symbol)
    df = add_poc_bar_dist(df, symbol=symbol)
    df = add_bars_in_va(df)
    df = add_single_print_count(df)
    df = add_momentum_3b_clean(df)
    df = add_delta_divergence(df)
    df = add_vwap_slope_30(df)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# Tests inline
# ═══════════════════════════════════════════════════════════════════════════════

def _test_profile_shape():
    """Test classification profile_shape vs poc_position."""
    df = pd.DataFrame({
        "poc_position": [0.10, 0.30, 0.50, 0.70, 0.85, np.nan],
    })
    df_out = add_profile_shape(df)
    expected = [ProfileShape.B_LOWER.value, ProfileShape.B_LOWER.value,
                ProfileShape.D_SHAPE.value, ProfileShape.P_SHAPE.value,
                ProfileShape.P_SHAPE.value, -1]
    actual = df_out["profile_shape"].tolist()
    assert actual == expected, f"Expected {expected}, got {actual}"
    print(f"  profile_shape: OK (expected={expected}, got={actual})")


def _test_trend_day_probability():
    """Test heuristique trend_day_probability (convention ES seuil ib_narrow=10.0)."""
    df = pd.DataFrame({
        # ES seuil=10.0. Bar 0/2 narrow (ib<10), bar 1 large (ib>=10), bar 3 NaN.
        "ib_range_atr": [5.0, 15.0, 5.0, np.nan],
        "open_cash":    [4500, 4500, 4500, 4500],
        "prev_vah":     [4480, 4480, 4480, 4480],
        "prev_val":     [4450, 4450, 4450, 4450],
        "prev_vpoc":    [4470, 4470, 4470, 4470],
        "vix_regime":   [1, 1, 3, 1],
    })
    df_out = add_trend_day_probability(df, symbol="ES")
    # Bar 0 : ib_narrow(+0.30) + open hors VA (+0.20, open=4500>vah=4480) + gap (open-vpoc=30, 30/0.25=120 ticks>15, +0.15) + vix_normal = 0.65
    # Bar 1 : not narrow + open hors VA (+0.20) + gap fort (+0.15) + vix_normal = 0.35
    # Bar 2 : ib_narrow (+0.30) + open hors VA (+0.20) + gap fort (+0.15) + vix_high (-0.10) = 0.55
    # Bar 3 : NaN ib_range_atr -> default 0.5
    expected = [0.65, 0.35, 0.55, 0.5]
    actual = df_out["trend_day_probability"].tolist()
    for i, (e, a) in enumerate(zip(expected, actual)):
        assert abs(a - e) < 0.01, f"Bar {i}: expected {e}, got {a}"
    print(f"  trend_day_probability: OK (expected={expected}, got={actual})")


def _test_trend_day_probability_per_symbol():
    """Verifie seuil per-symbol ES=10 vs NQ=13 (isole le critère ib_narrow)."""
    df = pd.DataFrame({
        "ib_range_atr": [11.5],   # > seuil ES (10) MAIS < seuil NQ (13)
        "open_cash":    [4490.0], # dans VA (4480-4495) → pas de +0.20
        "prev_vah":     [4495.0],
        "prev_val":     [4480.0],
        "prev_vpoc":    [4490.0], # gap = 0 < 15 ticks → pas de +0.15
        "vix_regime":   [1],      # vix normal → pas de -0.10
    })
    # ES : ib_atr=11.5 > seuil 10 -> not narrow -> 0.0 + 0 + 0 = 0.0
    df_es = add_trend_day_probability(df, symbol="ES")
    assert abs(df_es["trend_day_probability"].iloc[0] - 0.0) < 0.01, \
        f"ES: expected 0.0, got {df_es['trend_day_probability'].iloc[0]}"
    # NQ : ib_atr=11.5 < seuil 13 -> narrow -> +0.30 + 0 + 0 = 0.30
    df_nq = add_trend_day_probability(df, symbol="NQ")
    assert abs(df_nq["trend_day_probability"].iloc[0] - 0.30) < 0.01, \
        f"NQ: expected 0.30, got {df_nq['trend_day_probability'].iloc[0]}"
    print(f"  trend_day_probability per-symbol: OK (ES=0.0, NQ=0.30)")


def _run_tests():
    print("=" * 60)
    print("TESTS phase_b_v6_extras.py")
    print("=" * 60)
    _test_profile_shape()
    _test_trend_day_probability()
    _test_trend_day_probability_per_symbol()
    print("OK All tests pass")


if __name__ == "__main__":
    _run_tests()
