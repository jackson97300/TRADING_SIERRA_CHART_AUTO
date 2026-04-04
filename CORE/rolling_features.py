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


class RollingFeatures:
    """Calcule 26 features derivees sur fenetres glissantes."""

    def __init__(self, short: int = 3, mid: int = 5, long: int = 10):
        """
        Args:
            short: Fenêtre courte (3 barres = ~3 min)
            mid:   Fenêtre moyenne (5 barres = ~5 min)
            long:  Fenêtre longue (10 barres = ~10 min)
        """
        self.short = short
        self.mid = mid
        self.long = long

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
        price_max = df["price"].rolling(self.long, min_periods=2).max()
        price_min = df["price"].rolling(self.long, min_periods=2).min()
        tick_size = 0.25  # NQ et ES
        range_ticks = (price_max - price_min) / tick_size
        df["ctx_range_vs_atr_10"] = range_ticks / df["atr"].replace(0, np.nan)

        # 17. Vélocité position dans l'IB
        #     Pertinent après 10:30 quand IB est formée
        df["ctx_ib_position_velocity"] = (
            df["ib_position_pct"] - df["ib_position_pct"].shift(self.mid)
        )

        # ─── AUDIT FIX (05/03/2026) — 3 features ajoutées ────────────

        # 18. Absorption instantanée bar-by-bar signée
        #     Delta fort mais prix oppose = signal institutionnel immédiat
        #     Corrige le problème de ctx_price_delta_div_3 qui rate les
        #     absorptions post-climax (fenêtre contaminée par le climax)
        price_diff = df["price"].diff()
        df["ctx_instant_absorption"] = np.where(
            (df["delta_bar"] > 30) & (price_diff < 0), -1.0,   # bear absorption
            np.where(
                (df["delta_bar"] < -30) & (price_diff > 0), +1.0,  # bull absorption
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
        if "dist_sess_high" in df.columns:
            near_high = (df["dist_sess_high"].abs() < 5).astype(float)
            # Cumul glissant sur 30 barres (approximation session)
            df["ctx_excess_high_bars"] = near_high.rolling(
                60, min_periods=10
            ).sum()
            df["ctx_poor_high"] = (df["ctx_excess_high_bars"] < 3).astype(float)
        else:
            df["ctx_excess_high_bars"] = np.nan
            df["ctx_poor_high"] = 0.0

        if "dist_sess_low" in df.columns:
            near_low = (df["dist_sess_low"].abs() < 5).astype(float)
            df["ctx_excess_low_bars"] = near_low.rolling(
                60, min_periods=10
            ).sum()
            df["ctx_poor_low"] = (df["ctx_excess_low_bars"] < 3).astype(float)
        else:
            df["ctx_excess_low_bars"] = np.nan
            df["ctx_poor_low"] = 0.0

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
