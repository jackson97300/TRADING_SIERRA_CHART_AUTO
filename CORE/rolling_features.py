"""
Rolling Features - Le "cineaste" qui transforme les snapshots en film

Calcule 25 features derivees sur des fenetres glissantes a partir
du JSONL DMP (214 colonnes). Ces features capturent la DYNAMIQUE
du marche - ce qui change entre les barres, pas le snapshot isole.

Architecture:
    DMP (C++) -> JSONL (214 cols) -> RollingFeatures (Python) -> +26 cols
    Le C++ collecte, le Python analyse.

Usage:
    from dmp_reader import DmpReader
    from rolling_features import RollingFeatures

    reader = DmpReader("D:/TRADING_SIERRA_CHART_AUTO/DATA")
    df = reader.load("NQ", "2026-03-05")

    rf = RollingFeatures()
    df_enriched = rf.compute(df)

Auteur : MIA Trading System
Date   : 2026-03-05
"""

import numpy as np
import pandas as pd
from typing import Optional

from constants import INSTANT_ABSORPTION_DELTA_K, INSTANT_ABSORPTION_WINDOW

# Pattern try/except pour 2 conventions sys.path (ROOT vs CORE)
try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


class RollingFeatures:
    """Calcule 44 features derivees sur fenetres glissantes."""

    def __init__(self, short: int = 3, mid: int = 5, long: int = 10,
                  symbol: str | None = None):
        """
        Args:
            short: Fenêtre courte (3 barres = ~3 min)
            mid:   Fenêtre moyenne (5 barres = ~5 min)
            long:  Fenêtre longue (10 barres = ~10 min)
            symbol: ES, NQ, MGC. Si None, fallback ES + WARNING (16 callers
                legacy avant 10/05/2026 instanciaient sans symbol). Pour MGC,
                OBLIGATOIRE sinon ctx_range_vs_atr_10 sous-estime 2.5x (bug
                audit 09-10/05/2026).
        """
        import logging
        _logger = logging.getLogger(__name__)
        if symbol is None:
            _logger.warning(
                "RollingFeatures() instancie sans symbol — fallback ES (tick=0.25). "
                "Pour MGC (tick=0.10), passer symbol='MGC' explicitement. "
                "Sinon ctx_range_vs_atr_10 sera sous-estime d'un facteur 2.5x."
            )
            symbol = "ES"
        self.short = short
        self.mid = mid
        self.long = long
        self.symbol = symbol.upper()
        self.tick_size = _get_tick_size(self.symbol)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcule toutes les rolling features et les ajoute au DataFrame.

        Args:
            df: DataFrame DMP (214+ colonnes, index datetime)

        Returns:
            DataFrame enrichi avec 17 colonnes ctx_* ajoutées
        """
        df = df.copy()

        # Vérifier les colonnes requises
        required = ["price", "delta_bar", "total_vol", "vwap_slope_10",
                     "dist_vwap_d", "cvd_day", "atr", "diag_imbalance",
                     "finish_strength", "va_position_pct", "ib_position_pct",
                     "vwap_d_side", "large_trader_ratio",
                     "ib_range_atr", "ib_broken_up", "ib_broken_down",
                     "dist_vwap_d_atr", "delta_day_dir",
                     "dist_sess_high", "dist_sess_low", "ib_range_ticks"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            print(f"⚠️ Colonnes manquantes: {missing}")
            return df

        # Fix: JSON null → Python None → pandas object dtype → .abs() crash
        # Convertir TOUTES les colonnes numériques potentielles (None → NaN)
        optional_numeric = [
            "dist_ib_high", "dist_ib_low", "poc_position",
            "dist_cur_vah", "dist_cur_val", "dist_cur_vpoc",
            "inside_cur_va", "dist_mq_put", "dist_mq_call",
            "dist_sess_high", "dist_sess_low",
        ]
        for col in required + optional_numeric:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # ─── CRITICAL (5) ────────────────────────────────────────────

        # 1. Divergence prix/delta sur 3 barres
        #    Prix monte mais delta négatif (ou inverse) = signal institutionnel
        df["ctx_price_delta_div_3"] = self._divergence(
            df["price"], df["delta_bar"], self.short
        )

        # 2. Absorption score sur 5 barres
        #    Nb barres où delta pousse mais prix ne suit pas
        df["ctx_absorption_score_5"] = self._absorption(
            df["price"], df["delta_bar"], self.mid
        )

        # 3. Ratio volume sell/buy sur 5 barres
        #    Vol moyen des barres vendeuses / Vol moyen des barres acheteuses
        df["ctx_vol_sell_buy_ratio_5"] = self._vol_sell_buy_ratio(
            df["total_vol"], df["delta_bar"], self.mid
        )

        # 4. Accélération VWAP slope
        #    vwap_slope_10 maintenant - il y a 5 barres
        df["ctx_vwap_slope_accel"] = (
            df["vwap_slope_10"] - df["vwap_slope_10"].shift(self.mid)
        )

        # 5. Vitesse recovery CVD normalisée
        #    (CVD now - CVD 10 barres) / vol moyen 10 barres
        cvd_delta = df["cvd_day"] - df["cvd_day"].shift(self.long)
        vol_mean = df["total_vol"].rolling(self.long, min_periods=1).mean()
        df["ctx_cvd_recovery_rate"] = cvd_delta / vol_mean.replace(0, np.nan)

        # ─── HIGH (8) ────────────────────────────────────────────────

        # 6. Pente prix sur 5 barres (direction court terme)
        df["ctx_price_slope_5"] = self._slope(df["price"], self.mid)

        # 7. Pente delta sur 5 barres (delta accélère ou s'essouffle)
        df["ctx_delta_slope_5"] = self._slope(df["delta_bar"], self.mid)

        # 8. Somme delta 3 barres (impulsion court terme)
        df["ctx_delta_sum_3"] = df["delta_bar"].rolling(self.short, min_periods=1).sum()

        # 9. Z-score volume sur 5 barres (détecte climax/exhaust)
        vol_roll_mean = df["total_vol"].rolling(self.mid, min_periods=2).mean()
        vol_roll_std = df["total_vol"].rolling(self.mid, min_periods=2).std()
        df["ctx_vol_z_5"] = (
            (df["total_vol"] - vol_roll_mean) / vol_roll_std.replace(0, np.nan)
        )

        # 10. Moyenne diag_imbalance sur 5 barres (footprint lissé)
        df["ctx_diag_imbalance_mean_5"] = (
            df["diag_imbalance"].rolling(self.mid, min_periods=1).mean()
        )

        # 11. Moyenne finish_strength sur 5 barres
        #     Qui finit les barres (acheteurs ou vendeurs) — tendance
        df["ctx_finish_strength_mean_5"] = (
            df["finish_strength"].rolling(self.mid, min_periods=1).mean()
        )

        # 12. Vélocité position dans la VA
        #     va_position_pct now - il y a 5 barres
        #     Descend = prix migre vers bas de VA
        df["ctx_va_position_velocity"] = (
            df["va_position_pct"] - df["va_position_pct"].shift(self.mid)
        )

        # 13. Compteur de flips VWAP side sur 10 barres (chop detection)
        #     Élevé = prix oscille autour du VWAP = range, ne pas trader
        df["ctx_side_flip_count_10"] = self._flip_count(
            df["vwap_d_side"], self.long
        )

        # ─── MEDIUM (4) ──────────────────────────────────────────────

        # 14. Somme delta 10 barres (moyen terme)
        df["ctx_delta_sum_10"] = df["delta_bar"].rolling(self.long, min_periods=1).sum()

        # 15. Vélocité distance VWAP
        #     dist_vwap_d now - il y a 5 barres
        df["ctx_dist_vwap_velocity"] = (
            df["dist_vwap_d"] - df["dist_vwap_d"].shift(self.mid)
        )

        # 16. Range vs ATR sur 10 barres (expansion vs contraction)
        # FIX 10/05/2026 : tick_size depuis self (per-symbole). MGC=0.10 vs ES/NQ=0.25.
        # Avant : tick_size=0.25 hardcoded -> ratio 2.5x trop grand pour MGC.
        price_max = df["price"].rolling(self.long, min_periods=2).max()
        price_min = df["price"].rolling(self.long, min_periods=2).min()
        range_ticks = (price_max - price_min) / self.tick_size
        df["ctx_range_vs_atr_10"] = range_ticks / df["atr"].replace(0, np.nan)

        # 17. Vélocité position dans l'IB
        #     Pertinent après 10:30 quand IB est formée
        df["ctx_ib_position_velocity"] = (
            df["ib_position_pct"] - df["ib_position_pct"].shift(self.mid)
        )

        # ─── AUDIT FIX (05/03/2026) — 3 features ajoutées ────────────

        # 18. Absorption instantanée bar-by-bar signée
        #     Delta fort mais prix oppose = signal institutionnel immédiat
        #     FIX 18/04/2026 (code-reviewer audit) : seuil dynamique base sur
        #     rolling_std(delta_bar, 50) au lieu d'un seuil absolu 30 (arbitraire).
        #     Probleme seuil absolu : NQ Asia/pre-FOMC delta_bar median ~10-15,
        #     seuil 30 inatteignable -> feature morte 30% des sessions.
        #     Apres fix : k*std = s'adapte au regime volatilite local.
        #     Constantes : CORE/constants.py (INSTANT_ABSORPTION_DELTA_K / _WINDOW).
        price_diff = df["price"].diff()
        delta_std = df["delta_bar"].rolling(
            INSTANT_ABSORPTION_WINDOW, min_periods=10
        ).std()
        threshold = delta_std * INSTANT_ABSORPTION_DELTA_K
        df["ctx_instant_absorption"] = np.where(
            (df["delta_bar"] > threshold) & (price_diff < 0), -1.0,   # bear absorption
            np.where(
                (df["delta_bar"] < -threshold) & (price_diff > 0), +1.0,  # bull absorption
                0.0
            )
        )

        # 19. Streak d'absorption sur 5 barres
        #     Somme des absorptions instantanées → persistance du signal
        #     |streak| >= 2 = absorption confirmée
        df["ctx_absorption_streak_5"] = (
            df["ctx_instant_absorption"].rolling(self.mid, min_periods=1).sum()
        )

        # 20. Climax + direction composite
        #     vol_z détecte le climax, delta_sum donne la direction
        #     +1/-1 quand climax détecté, 0 sinon
        #     Seuil 1.0 (calibré: r=-0.100 vs r=-0.011 à 1.5)
        vol_z = df.get("ctx_vol_z_5", pd.Series(0, index=df.index))
        delta_sum = df.get("ctx_delta_sum_3", pd.Series(0, index=df.index))
        df["ctx_climax_signal"] = np.where(
            vol_z.abs() > 1.0,
            np.sign(delta_sum),
            0.0
        )

        # ─── TIER 1 (05/03/2026) — 3 features haute valeur ──────────

        # 21. Pente volume sur 5 barres
        #     Volume accélère ou décélère ? Complète vol_z (spike) avec tendance.
        #     vol_slope > 0 + delta_sum < 0 → vendeurs accélèrent
        #     vol_slope < 0 après climax → épuisement
        df["ctx_vol_slope_5"] = self._slope(df["total_vol"], self.mid)

        # 22. Delta exhaustion — ratio delta actuel vs max récent
        #     Capte le pattern "3 pushes" : chaque push plus faible
        #     < 0.5 = le move s'essouffle, les pics diminuent
        rolling_max_delta = df["delta_bar"].abs().rolling(
            self.long, min_periods=2
        ).max()
        df["ctx_delta_exhaustion"] = (
            df["delta_bar"].abs() / rolling_max_delta.replace(0, np.nan)
        )

        # 23. Pente large_trader_ratio sur 5 barres
        #     Les institutionnels entrent ou sortent ?
        #     Positif = gros augmentent (conviction) | Négatif = gros partent
        df["ctx_large_trader_slope_5"] = self._slope(
            df["large_trader_ratio"], self.mid
        )

        # ─── DYNAMIC SCORES (05/03/2026) — remplacent les constantes C++ ──

        # 24. Trend Day Score dynamique (remplace trend_day_probability=0.15 constant)
        #     Score 0.0→1.0 mis a jour a chaque barre.
        #     5 criteres additifs : IB comprime, extension unilaterale,
        #     volume en acceleration, prix loin du VWAP, delta day aligne.
        _score = pd.Series(0.0, index=df.index)

        # IB comprime = energie potentielle stockee
        _score = _score + (df["ib_range_atr"] < 0.40).astype(float) * 0.20

        # Extension unilaterale (IB casse d'UN seul cote)
        _ib_up = df["ib_broken_up"].astype(bool)
        _ib_dn = df["ib_broken_down"].astype(bool)
        _score = _score + ((_ib_up & ~_ib_dn) | (_ib_dn & ~_ib_up)).astype(float) * 0.25

        # Volume en acceleration (vol_slope_5 > 0)
        if "ctx_vol_slope_5" in df.columns:
            _score = _score + (df["ctx_vol_slope_5"] > 0).astype(float) * 0.15

        # Prix loin du VWAP (|dist_vwap_d_atr| > 0.15)
        _score = _score + (df["dist_vwap_d_atr"].abs() > 0.15).astype(float) * 0.20

        # Delta day aligne avec la direction du move
        # vwap_d_side=-1 (sous VWAP) + delta_day_dir=-1 (vendeurs) = aligne
        _score = _score + (df["vwap_d_side"] == df["delta_day_dir"]).astype(float) * 0.20

        df["ctx_trend_day_score"] = _score.clip(0.0, 1.0)

        # 25. Day Type Intensity — score continu [-1.0, +1.0]
        #     Remplace day_type (enum avec 1 transition sur 239 barres).
        #     Direction = quel cote de l'IB est casse (up/down/both/none).
        #     Magnitude = distance au VWAP en ATR (conviction du move).
        #     -1.0 = trend down pur | +1.0 = trend up pur | 0.0 = rotation
        _up_only = df["ib_broken_up"].astype(bool) & ~df["ib_broken_down"].astype(bool)
        _dn_only = df["ib_broken_down"].astype(bool) & ~df["ib_broken_up"].astype(bool)
        _dir = np.where(_up_only, 1.0, np.where(_dn_only, -1.0, 0.0))
        _mag = df["dist_vwap_d_atr"].abs()
        df["ctx_day_type_intensity"] = (_dir * _mag).clip(-1.0, 1.0)

        # ─── MENTHORQ (comble le trou gamma/options) ──────────────

        # 26. Ratio distance PUT wall / CALL wall
        #     > 1.0 = plus proche du PUT que du CALL → bearish
        #     < 1.0 = plus proche du CALL que du PUT → bullish
        #     Signal structurel indépendant du prix (gamma positioning).
        #     Stable 4/4 datasets (NQ+ES × 2 jours): r=-0.206/-0.265/-0.189/-0.012
        if "dist_mq_put" in df.columns and "dist_mq_call" in df.columns:
            _put = df["dist_mq_put"].abs()
            _call = df["dist_mq_call"].abs().replace(0, np.nan)
            df["ctx_mq_put_call_ratio"] = _put / _call
        else:
            df["ctx_mq_put_call_ratio"] = np.nan

        # ─── MARKET PROFILE AVANCÉ (14/03/2026) ────────────────────────
        # 6 nouvelles features prouvées par la théorie Steidlmayer/Dalton
        # Ajoutées APRÈS les features existantes (pas de régression)

        # 27. POC Migration — Le POC se déplace-t-il ?
        #     Pente du poc_position sur 10 barres.
        #     Positif = POC monte (acheteurs dominent) | Négatif = vendeurs
        #     Utilisé par le Session Planner pour le diagnostic biais.
        if "poc_position" in df.columns:
            df["ctx_poc_migration_10"] = self._slope(
                df["poc_position"], self.long
            )
        else:
            df["ctx_poc_migration_10"] = np.nan

        # 28. VA Developing — La Value Area s'élargit ou se contracte ?
        #     Variation de la largeur VA sur 10 barres.
        #     VA qui s'élargit = acceptance (le marché accepte ces prix)
        #     VA qui se contracte = rejection (le marché cherche autre chose)
        if "dist_cur_vah" in df.columns and "dist_cur_val" in df.columns:
            va_width = df["dist_cur_vah"].abs() + df["dist_cur_val"].abs()
            df["ctx_va_width"] = va_width
            df["ctx_va_developing_10"] = va_width - va_width.shift(self.long)
        else:
            df["ctx_va_width"] = np.nan
            df["ctx_va_developing_10"] = np.nan

        # 29. IB Extension Ratio — Le prix est à combien de fois l'IB ?
        #     Steidlmayer: 70% du temps prix reste dans 1x IB.
        #     > 1.5x = probable trend day | > 2.0x = trend day confirmé
        #     Calculé depuis dist_ib_high/low et ib_range_ticks
        if "ib_range_ticks" in df.columns:
            ib_range = df["ib_range_ticks"].replace(0, np.nan)
            # Distance max depuis l'IB mid (prendre le max de dist_ib_high et dist_ib_low)
            d_high = df.get("dist_ib_high", pd.Series(0, index=df.index)).abs()
            d_low = df.get("dist_ib_low", pd.Series(0, index=df.index)).abs()
            max_ext = pd.concat([d_high, d_low], axis=1).max(axis=1)
            # Extension = distance / half IB range
            df["ctx_ib_extension_ratio"] = max_ext / (ib_range / 2.0)
        else:
            df["ctx_ib_extension_ratio"] = np.nan

        # 30. Rotation Factor — Combien de fois le prix traverse le POC ?
        #     Beaucoup = range day (ping-pong) | Peu = trend day (directional)
        #     Compté sur les 20 dernières barres.
        #     Dalton: > 6 rotations en 1h = range day confirmé.
        if "dist_cur_vpoc" in df.columns:
            vpoc_side = (df["dist_cur_vpoc"] > 0).astype(int)
            vpoc_cross = (vpoc_side != vpoc_side.shift(1)).astype(float)
            df["ctx_rotation_factor_20"] = vpoc_cross.rolling(
                20, min_periods=5
            ).sum()
        else:
            df["ctx_rotation_factor_20"] = np.nan

        # 31. Failed Auction — Le prix sort de la VA puis revient rapidement
        #     Sortie + retour en < 5 barres = "marché a essayé et échoué"
        #     Signal de reversal ultra-fiable (Market Profile classique)
        #     1 = failed auction détecté sur cette barre, 0 sinon
        if "inside_cur_va" in df.columns:
            inside = df["inside_cur_va"].fillna(0).astype(int)
            failed = pd.Series(0, index=df.index)
            for lookback in [3, 4, 5]:
                # Était dedans il y a N barres, sorti entre-temps, revenu maintenant
                was_in = inside.shift(lookback)
                # Au moins 1 barre dehors dans la fenêtre
                min_inside = inside.rolling(lookback, min_periods=1).min()
                # Maintenant dedans et il y avait eu une sortie
                is_failed = (inside == 1) & (was_in == 1) & (min_inside == 0)
                failed = failed | is_failed.astype(int)
            df["ctx_failed_auction"] = failed
        else:
            df["ctx_failed_auction"] = 0

        # 32. Poor Highs/Lows — Approximation Python
        #     Compte les barres dans les 5 ticks du session high/low.
        #     < 3 barres = "poor" = pas de tail/excess = unfinished auction.
        #     Steidlmayer: "The market will always complete the auction."
        #     Si poor_high hier → biais LONG demain (continuation)
        #     Si poor_low hier  → biais SHORT demain
        #
        #     Sera remplacé par la vraie valeur C++ (PersistentFloat)
        #     quand le patch DMP_Main.cpp est appliqué.
        # FIX 13/04/2026 : seuil hardcode "< 5 ticks" remplace par "/atr < 0.04".
        # 5 ticks sur ES atr=132 = 0.038 ratio (intention originale).
        # Sur NQ atr=571, 5 ticks etait ~0.009 → seuil trop strict → feature
        # quasi-constante a 0.997 sur NQ (bug detecte par quality_validator).
        # 0.04 donne ~5 ticks ES et ~23 ticks NQ, coherent avec "prix colle au high".
        if "dist_sess_high" in df.columns and "atr" in df.columns:
            atr_safe = pd.to_numeric(df["atr"], errors="coerce").replace(0, np.nan)
            near_high = (df["dist_sess_high"].abs() / atr_safe < 0.04).astype(float)
            df["ctx_excess_high_bars"] = near_high.rolling(
                60, min_periods=10
            ).sum()
            df["ctx_poor_high"] = (df["ctx_excess_high_bars"] < 3).astype(float)
        else:
            df["ctx_excess_high_bars"] = np.nan
            df["ctx_poor_high"] = 0.0

        if "dist_sess_low" in df.columns and "atr" in df.columns:
            atr_safe = pd.to_numeric(df["atr"], errors="coerce").replace(0, np.nan)
            near_low = (df["dist_sess_low"].abs() / atr_safe < 0.04).astype(float)
            df["ctx_excess_low_bars"] = near_low.rolling(
                60, min_periods=10
            ).sum()
            df["ctx_poor_low"] = (df["ctx_excess_low_bars"] < 3).astype(float)
        else:
            df["ctx_excess_low_bars"] = np.nan
            df["ctx_poor_low"] = 0.0

        # DESACTIVE 24/04/2026 (schema 3.7.11) : override Python supprime.
        # Ancien code reconstruisait `bool_near_level` avec 4 niveaux seulement
        # (vwap_d, ib_high, sess_high, swing_high) et seuil 0.06*ATR.
        # Le C++ DMP_Transform.h::CalcBooleans (fix 24/04) genere desormais
        # `bool_near_level` avec 23 niveaux majeurs et seuil 10 ticks strict.
        # Le dataset ML lit directement la valeur C++ depuis JSONL (plus propre).
        # Cf DOCS/INCIDENT_LOG.md 24/04 et DMP_Config.h changelog 3.7.11.

        # ─── DELTA DIVERGENCE — Reconstruction Python (17/04/2026) ─────────
        # Le C++ delta_divergence est POLLUE (bug Extension Line Count = 100%
        # a 1 sur marche trending, cf feedback_elc_pattern).
        # Reconstruction fidele a Sierra Chart ID33 "LINKED TO DELTA DIVERGENCE"
        # qui est l'etude "Daily OHLC" (SG2=High cumulatif, SG3=Low cumulatif).
        # Formule SC exacte :
        #   BUY  : AND(daily_low  < daily_low[-1],  AV-BV >= 0)
        #          = new session low + buyers en embuscade -> rejection/bounce
        #   SELL : AND(daily_high > daily_high[-1], AV-BV <= 0)
        #          = new session high + sellers en embuscade -> false breakout
        # AV-BV = ask_volume - bid_volume = delta_bar (verifie empiriquement
        # exact match sur ES et NQ 20260416).
        # Validation 20260416 NQ : 2 triggers SELL (06:07, 06:10 UTC) matchent
        # les 2 triangles visibles sur la capture Jackson.

        if all(c in df.columns for c in ["bar_high", "bar_low", "delta_bar", "ts"]):
            # Trading date CME (reset session a 18:00 ET = 22:00 UTC)
            ts_ms = pd.to_numeric(df["ts"], errors="coerce")
            dt_utc = pd.to_datetime(ts_ms, unit="ms", utc=True)
            dt_et = dt_utc.dt.tz_convert("America/New_York")
            # Si hour_ET >= 18, la trading date est le jour suivant
            shift_day = (dt_et.dt.hour >= 18).astype(int)
            trading_date_base = dt_et.dt.normalize()
            trading_date = trading_date_base + pd.to_timedelta(shift_day, unit="D")

            # Running Daily High/Low par trading date (reset a chaque session CME)
            bar_high_num = pd.to_numeric(df["bar_high"], errors="coerce")
            bar_low_num  = pd.to_numeric(df["bar_low"],  errors="coerce")
            daily_high = bar_high_num.groupby(trading_date).cummax()
            daily_low  = bar_low_num.groupby(trading_date).cummin()

            # Formule SC
            dh_prev = daily_high.shift(1)
            dl_prev = daily_low.shift(1)
            delta_b = pd.to_numeric(df["delta_bar"], errors="coerce").fillna(0)

            # Ne trigger que si on est dans la meme trading date que la barre
            # precedente (sinon passage de session = false positive au reset)
            same_session = (trading_date == trading_date.shift(1))

            # WARNING ULTRATHINK 12/06 PM (Phase 2.1 doc)
            #
            # Cette implementation BATCH calcule semantique CUMMAX (running
            # session intra-day, equivalent A mais sans prev_day reference)
            # = SEMANTIQUE C (cf divergences_v2.py docstring section
            # "SEMANTIQUES DES 3 SOURCES").
            #
            # LIVE pipeline (sierra_pipeline.py) utilise SEMANTIQUE B (SLOPE
            # rolling 10b via divergences_v2.py) pour les MEMES clefs
            # delta_div_*_clean.
            #
            # CONSEQUENCE = MISMATCH BATCH (CUMMAX) vs LIVE (SLOPE) :
            #   - Modeles ML entraines sur dataset BATCH (CUMMAX) puis
            #     inference LIVE (SLOPE) = distribution shift PSI >> 0.25
            #     (Lopez AFML ch.7 feature drift)
            #   - Hallucinations predictions ML risque reel
            #
            # PLAN REFACTOR Phase 2.3 (session 3 future) :
            #   - Replace ce code CUMMAX par DivergencesV2Calculator
            #     row-by-row (SLOPE)
            #   - Cohherence BATCH = LIVE = SLOPE partout
            #
            # Cf INCIDENT_LOG #51 (ARCHITECTURAL_MISMATCH 12/06 PM).
            div_buy_raw  = (daily_low  < dl_prev) & (delta_b >= 0) & same_session
            div_sell_raw = (daily_high > dh_prev) & (delta_b <= 0) & same_session

            df["delta_div_buy_clean"]    = div_buy_raw.astype(int)
            df["delta_div_sell_clean"]   = div_sell_raw.astype(int)
            df["delta_divergence_clean"] = df["delta_div_buy_clean"] - df["delta_div_sell_clean"]

            # Intensite (magnitude delta quand divergence active, 0 sinon)
            # Utile pour le ML : differencier div faible vs div forte
            # Winsorization p99.5 : evite outlier explosion (delta spike rare)
            raw_strength = delta_b.abs() * (div_buy_raw | div_sell_raw).astype(int)
            active_vals = raw_strength[raw_strength > 0]
            if len(active_vals) > 20:
                clip_high = float(active_vals.quantile(0.995))
                df["delta_div_strength"] = raw_strength.clip(upper=clip_high)
            else:
                df["delta_div_strength"] = raw_strength
        else:
            df["delta_div_buy_clean"]    = 0
            df["delta_div_sell_clean"]   = 0
            df["delta_divergence_clean"] = 0
            df["delta_div_strength"]     = 0.0

        # Features derivees : on utilise delta_divergence_clean (Python) au lieu
        # de delta_divergence (C++ pollue). Meme semantique, vraies valeurs.
        dd = df["delta_divergence_clean"].fillna(0)

        # 33. Barres depuis la derniere divergence (recence)
        #     Plus c'est recent, plus c'est actionnable
        #     NaN si aucune divergence dans la session
        div_fired = (dd != 0).astype(int)
        cumfire = div_fired.cumsum()
        last_fire_idx = cumfire.where(div_fired == 1).ffill()
        df["ctx_bars_since_div"] = cumfire - last_fire_idx
        df.loc[last_fire_idx.isna(), "ctx_bars_since_div"] = np.nan

        # 34. Nombre de divergences actives sur 20 barres (densite)
        #     Beaucoup = zone de forte divergence, signal renforce
        df["ctx_div_density_20"] = div_fired.rolling(20, min_periods=1).sum()

        # 35. Confluence divergence + niveau cle (swing ou IB)
        #     Divergence qui fire pres d'un swing high/low = setup classique
        #     +1 = div buy pres du swing low, -1 = div sell pres du swing high
        near_swing_low = (df.get("dist_swing_low", pd.Series(np.nan, index=df.index))
                          .abs().fillna(999) < 15)
        near_swing_high = (df.get("dist_swing_high", pd.Series(np.nan, index=df.index))
                           .abs().fillna(999) < 15)
        df["ctx_div_at_swing"] = np.where(
            (dd == 1) & near_swing_low, 1.0,
            np.where(
                (dd == -1) & near_swing_high, -1.0,
                0.0
            )
        )

        # ─── TRAPPED TRADERS (2) ────────────────────────────────────

        # 39. Double top/bottom trap — signal piege directionnel
        #     Retest d'un swing avec divergence delta + confirmation macro
        #     Edge mesure : +10.4t SELL (double top), +7t BUY (double bottom)
        if all(c in df.columns for c in ["retest_high_delta_div", "bars_since_retest_high",
                                          "retest_low_delta_div", "bars_since_retest_low",
                                          "cvd_day_dir", "diag_imbalance"]):
            rhdv = pd.to_numeric(df["retest_high_delta_div"], errors="coerce").fillna(0)
            bsrh = pd.to_numeric(df["bars_since_retest_high"], errors="coerce").fillna(999)
            rldv = pd.to_numeric(df["retest_low_delta_div"], errors="coerce").fillna(0)
            bsrl = pd.to_numeric(df["bars_since_retest_low"], errors="coerce").fillna(999)
            cvd_dir = pd.to_numeric(df["cvd_day_dir"], errors="coerce").fillna(0)
            diag = pd.to_numeric(df["diag_imbalance"], errors="coerce").fillna(0)

            dt_bear = (rhdv == 1) & (bsrh <= 5) & ((cvd_dir == -1) | (diag < 0))
            dt_bull = (rldv == 1) & (bsrl <= 5) & ((cvd_dir == 1) | (diag > 0))
            df["ctx_double_top_trap"] = np.where(dt_bear, -1, np.where(dt_bull, 1, 0)).astype(float)
        else:
            df["ctx_double_top_trap"] = 0.0

        # 40. Momentum exhaustion — vendeurs/acheteurs pieges par epuisement
        #     Mouvement fort suivi d'un rejet contradictoire intra-barre
        #     Edge mesure : +7.0t BUY (bear exhaust, WR=65%)
        if "momentum_5b" in df.columns and "finish_strength" in df.columns:
            mom = pd.to_numeric(df["momentum_5b"], errors="coerce").fillna(0)
            finish = pd.to_numeric(df["finish_strength"], errors="coerce").fillna(0)
            bear_exhaust = (mom < -8) & (finish > 10)   # vendeurs pieges -> BUY
            bull_exhaust = (mom > 8) & (finish < -10)    # acheteurs pieges -> SELL
            df["ctx_momentum_exhaustion"] = np.where(
                bear_exhaust, 1.0, np.where(bull_exhaust, -1.0, 0.0)
            )
        else:
            df["ctx_momentum_exhaustion"] = 0.0

        # ─── SESSION-SPECIFIC FEATURES (3) ──────────────────────────

        # 36. CVD session — cumul delta depuis le debut de la session courante
        #     Reset a chaque changement de session (Asia→London→US)
        if "session" in df.columns and "delta_bar" in df.columns:
            session = pd.to_numeric(df["session"], errors="coerce").fillna(-1).astype(int)
            delta = pd.to_numeric(df["delta_bar"], errors="coerce").fillna(0)
            session_change = session.ne(session.shift()).astype(int)
            groups = session_change.cumsum()
            df["ctx_cvd_session"] = delta.groupby(groups).cumsum()
        else:
            df["ctx_cvd_session"] = 0.0

        # 37. RVOL session — volume relatif normalise par session
        #     Compare le volume courant a la moyenne rolling de la meme session
        if "session" in df.columns and "total_vol" in df.columns:
            session = pd.to_numeric(df["session"], errors="coerce").fillna(-1).astype(int)
            vol = pd.to_numeric(df["total_vol"], errors="coerce").fillna(0)
            session_change = session.ne(session.shift()).astype(int)
            groups = session_change.cumsum()
            # Moyenne rolling 30 barres dans la meme session
            session_avg = vol.groupby(groups).transform(
                lambda x: x.rolling(30, min_periods=5).mean()
            )
            df["ctx_rvol_session"] = np.where(
                session_avg > 0, vol / session_avg, 1.0
            )
        else:
            df["ctx_rvol_session"] = 1.0

        # 38. Session phase — phase fine de la session
        #     0=Asia, 1=Asia_Late, 2=London, 3=Pre_Open, 4=IB_Formation,
        #     5=Mid_AM, 6=Afternoon, 7=Power_Hour
        if "session" in df.columns and "ts" in df.columns:
            ts = pd.to_numeric(df["ts"], errors="coerce")
            session = pd.to_numeric(df["session"], errors="coerce").fillna(0).astype(int)
            # Extraire l'heure ET depuis le timestamp
            hour_et = ((ts / 1000) % 86400 / 3600).astype(int)  # approx
            phase = np.zeros(len(df), dtype=int)
            # Asia (session=0)
            phase[session == 0] = 0
            # Asia Late (session=0, apres minuit = barres tardives)
            # London (session=1)
            phase[session == 1] = 2
            # US (session=2) — subdiviser par heure
            us_mask = session == 2
            phase[us_mask] = 4  # default IB_Formation
            # Utiliser ib_complete pour detecter post-IB
            if "ib_complete" in df.columns:
                ib_done = pd.to_numeric(df["ib_complete"], errors="coerce").fillna(0)
                phase[us_mask & (ib_done == 1)] = 5  # Mid_AM par defaut post-IB
            df["ctx_session_phase"] = phase
        else:
            df["ctx_session_phase"] = 0

        # ═══════════════════════════════════════════════════════════════════
        # DIVERGENCE CONFLUENCE (17/04/2026) - Strategie div pro
        # Testable A (DMP pur) vs B (DMP + proxies regime) pour uplift marginal
        # ═══════════════════════════════════════════════════════════════════

        # 41. div_at_key_level_ticks - distance min aux niveaux cles au bar div
        #     NaN si pas de div active. Seuil < 20t = "div sur niveau" (setup pro)
        dist_cols = [
            "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
            "dist_mq_call_0dte", "dist_mq_put_0dte",
            "dist_swing_high", "dist_swing_low",
            "dist_cur_vah", "dist_cur_val",
            "dist_ib_high", "dist_ib_low",
            "dist_blind_nearest_up", "dist_blind_nearest_dn",
            "next_wall_dist_ticks",
        ]
        available_dist = [c for c in dist_cols if c in df.columns]
        if available_dist:
            dist_mat = df[available_dist].apply(pd.to_numeric, errors="coerce").abs()
            min_dist = dist_mat.min(axis=1, skipna=True)
            df["div_at_key_level_ticks"] = np.where(dd != 0, min_dist, np.nan)
        else:
            df["div_at_key_level_ticks"] = np.nan

        # 42. div_confluence_dmp - score 0-4 (DMP pur, zero dependance MenthorQ JSON)
        #     Composantes: div_active + at_level<20t + absorb_aligned + rvol_extreme
        div_active = (dd != 0).astype(int)

        at_level_series = pd.to_numeric(df["div_at_key_level_ticks"], errors="coerce")
        at_level = ((at_level_series < 20) & (dd != 0)).astype(int)

        if "bn_absorb_bid" in df.columns and "bn_absorb_ask" in df.columns:
            absorb_bid = pd.to_numeric(df["bn_absorb_bid"], errors="coerce").fillna(0)
            absorb_ask = pd.to_numeric(df["bn_absorb_ask"], errors="coerce").fillna(0)
            absorb_buy = (dd == 1) & (absorb_bid > 0)
            absorb_sell = (dd == -1) & (absorb_ask > 0)
            absorb_score = (absorb_buy | absorb_sell).astype(int)
        else:
            absorb_score = pd.Series(0, index=df.index)

        if "rvol_zscore" in df.columns:
            rvz = pd.to_numeric(df["rvol_zscore"], errors="coerce").fillna(0)
            rvol_score = ((rvz.abs() >= 2.0) & (dd != 0)).astype(int)
        elif "rvol" in df.columns:
            rv = pd.to_numeric(df["rvol"], errors="coerce").fillna(0)
            rvol_score = ((rv >= 2.0) & (dd != 0)).astype(int)
        else:
            rvol_score = pd.Series(0, index=df.index)

        df["div_confluence_dmp"] = (
            div_active + at_level + absorb_score + rvol_score
        ).astype(int)

        # 43. div_forward_return_20b - forward return 20 barres, normalise par ATR
        #     Signe aligne sur le sens de la div : positif = div a fonctionne
        #     div buy (dd=+1) -> on veut price[t+20]>price[t] -> signe positif
        #     div sell (dd=-1) -> on veut price[t+20]<price[t] -> * -1 -> positif
        if "price" in df.columns and "atr" in df.columns:
            price_col = pd.to_numeric(df["price"], errors="coerce")
            atr_col = pd.to_numeric(df["atr"], errors="coerce").replace(0, np.nan)
            fwd_20 = price_col.shift(-20) - price_col
            fwd_norm = fwd_20 / atr_col
            df["div_forward_return_20b"] = np.where(
                dd != 0, fwd_norm * dd, np.nan
            )
        else:
            df["div_forward_return_20b"] = np.nan

        # 44. div_regime_proxy_ok - regime favorable reversal (proxies DMP)
        #     1 si vix_regime>=1 (pas low-vix) ET NOT gex_flip_zone (pas transition)
        #     Proxy substitut pour GEX+ / mean-revert sans CTA/Vol Model scrape
        if "vix_regime" in df.columns and "bool_gex_flip_zone" in df.columns:
            vr = pd.to_numeric(df["vix_regime"], errors="coerce").fillna(0)
            gf = pd.to_numeric(df["bool_gex_flip_zone"], errors="coerce").fillna(0)
            df["div_regime_proxy_ok"] = ((vr >= 1) & (gf == 0)).astype(int)
        else:
            df["div_regime_proxy_ok"] = 0

        # 45. div_confluence_with_regime - score 0-5 (DMP + proxies)
        #     Uplift marginal du regime vs DMP pur
        df["div_confluence_with_regime"] = (
            df["div_confluence_dmp"] + df["div_regime_proxy_ok"]
        ).astype(int)

        return df

    # ─── HELPERS PRIVÉS ───────────────────────────────────────────────

    @staticmethod
    def _slope(series: pd.Series, window: int) -> pd.Series:
        """Pente linéaire (regression) sur une fenêtre glissante."""
        def linreg_slope(arr):
            n = len(arr)
            if n < 2:
                return np.nan
            valid = ~np.isnan(arr)
            if valid.sum() < 2:
                return np.nan
            x = np.arange(n)[valid]
            y = arr[valid]
            if len(x) < 2:
                return np.nan
            mx, my = x.mean(), y.mean()
            denom = ((x - mx) ** 2).sum()
            if denom == 0:
                return 0.0
            return ((x - mx) * (y - my)).sum() / denom

        return series.rolling(window, min_periods=2).apply(linreg_slope, raw=True)

    @staticmethod
    def _divergence(price: pd.Series, delta: pd.Series, window: int) -> pd.Series:
        """
        Divergence prix/delta sur N barres.
        +1 = prix monte, delta négatif (bull divergence = absorption)
        -1 = prix baisse, delta positif (bear divergence = distribution)
         0 = pas de divergence
        """
        price_change = price - price.shift(window)
        delta_sum = delta.rolling(window, min_periods=1).sum()

        result = pd.Series(0, index=price.index, dtype=float)
        result[(price_change > 0) & (delta_sum < 0)] = 1.0   # Bull div
        result[(price_change < 0) & (delta_sum > 0)] = -1.0  # Bear div
        return result

    @staticmethod
    def _absorption(price: pd.Series, delta: pd.Series, window: int) -> pd.Series:
        """
        Score d'absorption sur N barres.
        Compte les barres où delta > seuil mais prix baisse (ou inverse).
        Score normalisé 0-1 (0 = aucune absorption, 1 = toutes les barres).
        """
        price_change = price.diff()
        threshold = 10  # delta minimum pour considérer une "poussée"

        # Absorption acheteuse : delta > 0 mais prix ne monte pas
        buy_absorb = ((delta > threshold) & (price_change <= 0)).astype(float)
        # Absorption vendeuse : delta < -threshold mais prix ne baisse pas
        sell_absorb = ((delta < -threshold) & (price_change >= 0)).astype(float)

        total_absorb = buy_absorb + sell_absorb
        score = total_absorb.rolling(window, min_periods=1).sum() / window
        return score

    @staticmethod
    def _vol_sell_buy_ratio(vol: pd.Series, delta: pd.Series, window: int) -> pd.Series:
        """
        Ratio vol moyen barres vendeuses / vol moyen barres acheteuses.
        > 1.0 = vendeurs dominent en volume
        < 1.0 = acheteurs dominent
        = 1.0 = équilibré
        """
        sell_vol = vol.where(delta < 0, np.nan)
        buy_vol = vol.where(delta > 0, np.nan)

        sell_mean = sell_vol.rolling(window, min_periods=1).mean()
        buy_mean = buy_vol.rolling(window, min_periods=1).mean()

        ratio = sell_mean / buy_mean.replace(0, np.nan)
        return ratio.fillna(1.0)

    @staticmethod
    def _flip_count(side: pd.Series, window: int) -> pd.Series:
        """Nombre de changements de signe sur N barres."""
        changes = (side != side.shift(1)).astype(float)
        return changes.rolling(window, min_periods=1).sum()

    # ─── RÉSUMÉ ───────────────────────────────────────────────────────

    @staticmethod
    def summary(df: pd.DataFrame):
        """Affiche un résumé des features ctx_* calculées."""
        ctx_cols = [c for c in df.columns if c.startswith("ctx_")]
        if not ctx_cols:
            print("  Aucune feature ctx_* trouvée")
            return

        print(f"  {len(ctx_cols)} rolling features calculées:")
        print()
        for col in ctx_cols:
            vals = df[col].dropna()
            if len(vals) == 0:
                print(f"  {col:35s}: tout NaN")
                continue
            print(f"  {col:35s}: "
                  f"min={vals.min():+8.3f} "
                  f"mean={vals.mean():+8.3f} "
                  f"max={vals.max():+8.3f} "
                  f"null={df[col].isna().sum()}/{len(df)}")

    # ─── LISTE DES FEATURES ──────────────────────────────────────────

    FEATURES = [
        # CRITICAL
        "ctx_price_delta_div_3",
        "ctx_absorption_score_5",
        "ctx_vol_sell_buy_ratio_5",
        "ctx_vwap_slope_accel",
        "ctx_cvd_recovery_rate",
        # HIGH
        "ctx_price_slope_5",
        "ctx_delta_slope_5",
        "ctx_delta_sum_3",
        "ctx_vol_z_5",
        "ctx_diag_imbalance_mean_5",
        "ctx_finish_strength_mean_5",
        "ctx_va_position_velocity",
        "ctx_side_flip_count_10",
        # MEDIUM
        "ctx_delta_sum_10",
        "ctx_dist_vwap_velocity",
        "ctx_range_vs_atr_10",
        "ctx_ib_position_velocity",
        # AUDIT FIX
        "ctx_instant_absorption",
        "ctx_absorption_streak_5",
        "ctx_climax_signal",
        # TIER 1
        "ctx_vol_slope_5",
        "ctx_delta_exhaustion",
        "ctx_large_trader_slope_5",
        # DYNAMIC SCORES
        "ctx_trend_day_score",
        "ctx_day_type_intensity",
        # MENTHORQ
        "ctx_mq_put_call_ratio",
        # 🆕 14/03/2026: MARKET PROFILE AVANCÉ
        "ctx_poc_migration_10",
        "ctx_va_developing_10",
        "ctx_ib_extension_ratio",
        "ctx_rotation_factor_20",
        "ctx_failed_auction",
        "ctx_poor_high",
        "ctx_poor_low",
        "ctx_excess_high_bars",
        "ctx_excess_low_bars",
        "ctx_va_width",
    ]
