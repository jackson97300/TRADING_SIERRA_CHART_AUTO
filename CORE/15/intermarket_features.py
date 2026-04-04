"""
Intermarket Features - SMT Divergence, Lead-Lag, Cross-Delta ES/NQ

Calcule 8 features cross-asset en synchronisant les JSONL ES et NQ.
Ces features capturent ce qu'un seul instrument ne montre pas :
les divergences de conviction entre les deux marches correles.

Concepts implementes:
  - SMT Divergence : NQ fait un new high mais ES refuse de suivre (piege)
  - Lead-Lag : qui bouge en premier sur le delta et le volume
  - Cross-Delta Agreement : direction + magnitude (confirmation vs exhaustion)
  - Relative Strength : rotation tech vs broad market
  - LTR Slope Diff : les institutionnels migrent d'un symbole a l'autre

Architecture:
    DMP ES.jsonl + DMP NQ.jsonl -> merge sur timestamp -> +8 features
    S'utilise APRES RollingFeatures (qui calcule les ctx_* par symbole)

Usage:
    from dmp_reader import DmpReader
    from rolling_features import RollingFeatures
    from intermarket_features import IntermarketFeatures

    reader = DmpReader("D:/TRADING_SIERRA_CHART_AUTO/DATA")
    df_nq = reader.load("NQ", "2026-03-05")
    df_es = reader.load("ES", "2026-03-05")

    im = IntermarketFeatures()
    df_nq_enriched = im.compute(df_nq, df_es, target="NQ")

Changelog:
    v1 (2026-03-05) : 7 features initiales
    v2 (2026-03-05) : 8 features (+weighted agreement, ltr_slope remplace ltr_brut)
        BUG FIX #1 : drop_duplicates apres merge (ts dupliques polluaient les rolling)
        BUG FIX #2 : colonnes manquantes -> NaN au lieu de Series(0) silencieux
        BUG FIX #3 : nettoyer les im_* du target avant merge (appels doubles)
        BUG FIX #4 : colonnes im_* par defaut (NaN) quand merge echoue
        IMPROVE #1 : im_cross_delta_weighted_5 (signal contrarian, r=-0.303)
        IMPROVE #2 : im_ltr_slope_diff remplace im_ltr_differential (7.7x meilleur)

Auteur : MIA Trading System
Date   : 2026-03-05
"""

import numpy as np
import pandas as pd
from typing import Optional


class IntermarketFeatures:
    """Calcule 10 features cross-asset ES/NQ."""

    # Colonnes requises dans df_other pour chaque feature
    _REQUIRED_OTHER = {
        "im_smt_divergence": ["dist_sess_high", "dist_sess_low"],
        "im_delta_day_divergence": ["delta_day"],
        "im_ltr_slope_diff": ["large_trader_ratio"],
        "im_cross_open_signal": ["open_type", "open_bias_conf", "open_direction"],
    }

    def __init__(self, short: int = 3, mid: int = 5, long: int = 10):
        self.short = short
        self.mid = mid
        self.long = long

    def compute(
        self,
        df_target: pd.DataFrame,
        df_other: pd.DataFrame,
        target: str = "NQ",
    ) -> pd.DataFrame:
        """
        Calcule les features intermarket et les ajoute au DataFrame cible.

        Args:
            df_target: DataFrame du symbole qu'on trade (ex: NQ)
            df_other:  DataFrame de l'autre symbole (ex: ES)
            target:    "NQ" ou "ES" -- le symbole cible

        Returns:
            df_target enrichi avec 10 colonnes im_* ajoutees
        """
        df_target = df_target.copy()
        other_sym = "es" if target.upper() == "NQ" else "nq"

        # ─── BUG FIX #3 : nettoyer les im_* existantes du target ─────
        # Evite que les anciennes im_* polluent le merge et les rolling
        target_clean = df_target[[c for c in df_target.columns
                                  if not c.startswith("im_")]].copy()

        # ─── MERGE sur timestamp ──────────────────────────────────────

        other_cols = ["ts", "price", "delta_bar", "total_vol", "cvd_day",
                      "delta_day", "dist_sess_high", "dist_sess_low",
                      "large_trader_ratio", "vwap_slope_10",
                      "open_type", "open_bias_conf", "open_direction"]

        available = [c for c in other_cols if c in df_other.columns]
        df_o = df_other[available].copy()

        rename_map = {c: f"{c}_{other_sym}" for c in available if c != "ts"}
        df_o = df_o.rename(columns=rename_map)

        merged = target_clean.merge(df_o, on="ts", how="inner")

        # ─── BUG FIX #1 : dedupliquer les ts apres merge ─────────────
        # Un ts duplique (DMP bug) cree des rows fantomes qui polluent
        # les fenetres glissantes. Dedup + re-tri par ts pour garantir
        # que les rolling windows sont dans le bon ordre.
        merged = (merged.drop_duplicates(subset="ts", keep="last")
                  .sort_values("ts")
                  .reset_index(drop=True))

        # ─── BUG FIX #4 : retour avec colonnes NaN si pas assez ──────
        if len(merged) < 5:
            for col in self.FEATURES:
                df_target[col] = np.nan
            return df_target

        n_lost = len(df_target) - len(merged)
        if n_lost > 0:
            print(f"  Merge: {len(df_target)} -> {len(merged)} barres ({n_lost} perdues)")

        # ─── BUG FIX #2 : verifier les colonnes critiques ────────────
        # Si une colonne manque dans df_other, les features dependantes
        # seront NaN au lieu de faux calculs sur Series(0)
        missing_other = {}
        for feat, required in self._REQUIRED_OTHER.items():
            for col in required:
                suffixed = f"{col}_{other_sym}"
                if suffixed not in merged.columns:
                    missing_other.setdefault(feat, []).append(col)

        if missing_other:
            missing_list = [f"{feat}({','.join(cols)})"
                            for feat, cols in missing_other.items()]
            print(f"  Colonnes manquantes -> NaN: {', '.join(missing_list)}")

        # ─── EXTRACTION COLONNES ──────────────────────────────────────

        price_t = merged["price"]
        price_o = merged[f"price_{other_sym}"]
        delta_t = merged["delta_bar"]
        delta_o = merged[f"delta_bar_{other_sym}"]
        vol_t = merged["total_vol"]
        vol_o = merged[f"total_vol_{other_sym}"]

        # ── 1. CROSS-DELTA AGREEMENT (CRITICAL) ──────────────────────
        # Direction seule : les deux marches poussent-ils du meme cote ?
        # < 0.4 = confusion institutionnelle = DANGER
        # > 0.8 = conviction forte = signal fiable
        delta_dir_t = np.sign(delta_t)
        delta_dir_o = np.sign(delta_o)
        agreement = (delta_dir_t == delta_dir_o).astype(float)
        both_zero = (delta_t == 0) & (delta_o == 0)
        agreement = agreement.where(~both_zero, 0.5)

        merged["im_cross_delta_agreement_5"] = (
            agreement.rolling(self.mid, min_periods=1).mean()
        )

        # ── 2. CROSS-DELTA WEIGHTED (CRITICAL) ───────────────────────
        # IMPROVE #1 : agreement pondere par la magnitude du delta
        # = min(|delta_NQ|, |delta_ES|) * direction_agreement
        #
        # Signal CONTRARIAN (r=-0.303) : quand les deux marchés poussent
        # ensemble avec un gros delta (consensus fort), c'est l'EXHAUSTION
        # → le prix BAISSE ensuite
        #
        # Complementaire de agreement_5 (r=+0.243) qui est un signal
        # de CONTINUATION. Les deux ensemble = confirmation + timing.
        magnitude = np.minimum(delta_t.abs(), delta_o.abs())
        weighted = agreement * magnitude

        merged["im_cross_delta_weighted_5"] = (
            weighted.rolling(self.mid, min_periods=1).mean()
        )

        # ── 3. SMT DIVERGENCE (CRITICAL) ──────────────────────────────
        # NQ fait un new session high/low mais ES ne suit pas
        # +1 = divergence bullish (target piege en bas, other tient)
        # -1 = divergence bearish (target piege en haut, other refuse)
        #  0 = pas de divergence

        if "im_smt_divergence" not in missing_other:
            dist_high_t = merged["dist_sess_high"]
            dist_low_t = merged["dist_sess_low"]
            dist_high_o = merged[f"dist_sess_high_{other_sym}"]
            dist_low_o = merged[f"dist_sess_low_{other_sym}"]

            high_vel_t = dist_high_t - dist_high_t.shift(self.short)
            high_vel_o = dist_high_o - dist_high_o.shift(self.short)
            low_vel_t = dist_low_t - dist_low_t.shift(self.short)
            low_vel_o = dist_low_o - dist_low_o.shift(self.short)

            smt_bear = (high_vel_t < -10) & (high_vel_o > 0)
            smt_bull = (low_vel_t > 10) & (low_vel_o < 0)

            merged["im_smt_divergence"] = np.where(
                smt_bear, -1.0,
                np.where(smt_bull, 1.0, 0.0)
            )
        else:
            merged["im_smt_divergence"] = np.nan

        # ── 4. DELTA DAY DIVERGENCE (HIGH) ────────────────────────────
        # Le delta day d'un symbole flippe de signe mais pas l'autre
        # 0 = alignes, +1 = target pos / other neg, -1 = inverse

        if "im_delta_day_divergence" not in missing_other:
            delta_day_t = merged["delta_day"]
            delta_day_o = merged[f"delta_day_{other_sym}"]
            day_dir_t = np.sign(delta_day_t)
            day_dir_o = np.sign(delta_day_o)
            merged["im_delta_day_divergence"] = (day_dir_t - day_dir_o) / 2.0
        else:
            merged["im_delta_day_divergence"] = np.nan

        # ── 5. PRICE RATIO SLOPE (HIGH) ──────────────────────────────
        # Pente du ratio target/other sur 10 barres
        # Monte = target surperforme | Baisse = other surperforme

        price_ratio = price_t / price_o.replace(0, np.nan)
        merged["im_price_ratio_slope_10"] = self._slope(price_ratio, self.long)

        # ── 6. VOLUME LEAD (HIGH) ────────────────────────────────────
        # Qui a le volume qui accelere en premier ?
        # Positif = target mene | Negatif = other mene

        vol_slope_t = self._slope(vol_t, self.mid)
        vol_slope_o = self._slope(vol_o, self.mid)
        merged["im_volume_lead"] = vol_slope_t - vol_slope_o

        # ── 7. ROLLING CORRELATION (MEDIUM) ──────────────────────────
        # Drop < 0.80 = decouplage structurel = stress ou rotation

        merged["im_rolling_correlation_10"] = (
            price_t.rolling(self.long, min_periods=5).corr(price_o)
        )

        # ── 8. LTR SLOPE DIFFERENTIAL (MEDIUM) ───────────────────────
        # IMPROVE #2 : pente LTR target - pente LTR other (7.7x meilleur
        # que le differentiel brut qui etait du bruit r=+0.008)
        #
        # Positif = gros augmentent plus vite sur target
        # Negatif = gros augmentent plus vite sur other (migration)

        if "im_ltr_slope_diff" not in missing_other:
            ltr_t = merged["large_trader_ratio"]
            ltr_o = merged[f"large_trader_ratio_{other_sym}"]
            ltr_slope_t = self._slope(ltr_t, self.mid)
            ltr_slope_o = self._slope(ltr_o, self.mid)
            merged["im_ltr_slope_diff"] = ltr_slope_t - ltr_slope_o
        else:
            merged["im_ltr_slope_diff"] = np.nan

        # ── 9. CROSS OPEN SIGNAL (HIGH) ──────────────────────────────
        # Le game_changers de l'autre symbole comme signal pour le target.
        # Quand le target est neutre (OAIR/UNKNOWN) mais l'autre a un
        # biais (ex: ES OAOR_DOWN conf=0.65), on PREND le signal de l'autre.
        # Score = direction_other * confidence_other (quand target neutre)
        #       = direction_target * confidence_target (sinon)
        # Positif = signal long, negatif = signal short, 0 = pas de signal.

        if "im_cross_open_signal" not in missing_other:
            conf_t = merged.get("open_bias_conf", pd.Series(0, index=merged.index))
            conf_o = merged.get(f"open_bias_conf_{other_sym}",
                                pd.Series(0, index=merged.index))
            dir_t = merged.get("open_direction", pd.Series(0, index=merged.index))
            dir_o = merged.get(f"open_direction_{other_sym}",
                               pd.Series(0, index=merged.index))

            target_neutral = (conf_t < 0.35)  # OAIR (0.30) ou UNKNOWN (0.00)
            merged["im_cross_open_signal"] = np.where(
                target_neutral,
                dir_o * conf_o,    # prendre le signal de l'autre
                dir_t * conf_t     # sinon garder le sien
            )
        else:
            merged["im_cross_open_signal"] = np.nan

        # ── 10. OPEN TYPE AGREEMENT (MEDIUM) ─────────────────────────
        # Les deux symboles sont-ils d'accord sur la direction d'ouverture ?
        # +1 = meme direction | -1 = directions opposees | 0 = un des deux neutre
        # Directions opposees = CONFLIT = signal tres informatif.

        dir_t_raw = merged.get("open_direction", pd.Series(0, index=merged.index))
        dir_o_raw = merged.get(f"open_direction_{other_sym}",
                               pd.Series(0, index=merged.index))
        merged["im_open_type_agreement"] = np.where(
            (dir_t_raw != 0) & (dir_o_raw != 0),
            np.where(dir_t_raw == dir_o_raw, 1.0, -1.0),
            0.0
        )

        # ─── RECOLLER LES FEATURES AU DATAFRAME CIBLE ────────────────
        im_cols = [c for c in merged.columns if c.startswith("im_")]

        result = df_target.copy()
        for col in im_cols:
            ts_to_val = dict(zip(merged["ts"], merged[col]))
            result[col] = result["ts"].map(ts_to_val)

        return result

    # ─── HELPERS ──────────────────────────────────────────────────────

    @staticmethod
    def _slope(series: pd.Series, window: int) -> pd.Series:
        """Pente lineaire sur une fenetre glissante."""
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

    # ─── RESUME ───────────────────────────────────────────────────────

    @staticmethod
    def summary(df: pd.DataFrame):
        """Affiche un resume des features im_* calculees."""
        im_cols = [c for c in df.columns if c.startswith("im_")]
        if not im_cols:
            print("  Aucune feature im_* trouvee")
            return

        print(f"  {len(im_cols)} intermarket features calculees:")
        print()
        for col in im_cols:
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
        "im_cross_delta_agreement_5",
        "im_cross_delta_weighted_5",
        "im_smt_divergence",
        # HIGH
        "im_delta_day_divergence",
        "im_price_ratio_slope_10",
        "im_volume_lead",
        "im_cross_open_signal",
        # MEDIUM
        "im_rolling_correlation_10",
        "im_ltr_slope_diff",
        "im_open_type_agreement",
    ]
