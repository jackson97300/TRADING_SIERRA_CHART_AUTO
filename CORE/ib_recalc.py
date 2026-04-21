"""
ib_recalc.py — Recalcul IB depuis bar_high/bar_low
====================================================
Post-processing Python pour corriger le bug IB du DMP C++
ou sc.High[i] retourne INVALID sur les charts footprint SC.

bar_high et bar_low sont valides (schema 3.7.1+).
On recalcule toutes les features IB en Python.

Usage:
    from ib_recalc import IBRecalc
    recalc = IBRecalc()
    df = recalc.compute(df, symbol="ES")
    recalc.summary(df)

Auteur : MIA Trading System
Date   : 2026-03-30
"""

import numpy as np
import pandas as pd

# Constantes IB (identiques au C++ DMP_Config.h)
IB_NARROW_RATIO = 0.35
IB_WIDE_RATIO = 0.85
IB_START_ET = 9 * 60 + 30   # 9h30 ET en minutes
IB_END_ET = 10 * 60 + 30    # 10h30 ET en minutes
TICK_SIZE = 0.25


class IBRecalc:
    """Recalcule les features IB depuis bar_high/bar_low."""

    def compute(self, df: pd.DataFrame, symbol: str = "ES") -> pd.DataFrame:
        """
        Recalcule toutes les colonnes IB.

        Remplace les valeurs existantes (invalides du DMP C++).
        Fonctionne sur schema 3.7.0 (sans bar_high/low → skip),
        3.7.1 et 3.7.2 (avec bar_high/low).

        Args:
            df: DataFrame DMP avec colonnes ts, price, bar_high, bar_low, atr
            symbol: "ES" ou "NQ"

        Returns:
            DataFrame avec colonnes IB recalculees
        """
        df = df.copy()

        # Verifier bar_high/bar_low disponibles (schema 3.7.1+)
        if "bar_high" not in df.columns or "bar_low" not in df.columns:
            print("  [IBRecalc] bar_high/bar_low absents (schema 3.7.0) — skip")
            return df

        # Convertir en numerique
        for col in ["bar_high", "bar_low", "price", "atr", "ts"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Calculer l'heure ET pour chaque barre
        ts_sec = df["ts"] / 1000.0
        utc_hour = (ts_sec % 86400) / 3600.0

        # DST US : mars 8+ → EDT (UTC-4), sinon EST (UTC-5)
        # Approximation : on utilise le mois/jour du timestamp
        utc_dt = pd.to_datetime(df["ts"], unit="ms", utc=True)
        month = utc_dt.dt.month
        day = utc_dt.dt.day
        is_dst = (
            ((month >= 4) & (month <= 10)) |
            ((month == 3) & (day >= 8)) |
            ((month == 11) & (day <= 7))
        )
        offset = np.where(is_dst, 4, 5)
        h_et = (utc_dt.dt.hour - offset + 24) % 24
        m_et = utc_dt.dt.minute
        time_et = h_et * 60 + m_et

        # Identifier les barres dans la fenetre IB (9h30-10h30 ET)
        in_ib_window = (time_et >= IB_START_ET) & (time_et <= IB_END_ET)

        # Identifier les jours de trading (par date UTC ajustee)
        trading_date = (utc_dt - pd.Timedelta(hours=5)).dt.date

        # Calculer IB high/low par jour de trading
        ib_high_series = pd.Series(np.nan, index=df.index)
        ib_low_series = pd.Series(np.nan, index=df.index)

        for td in trading_date.unique():
            day_mask = trading_date == td
            ib_mask = day_mask & in_ib_window

            # bar_high/low valides dans la fenetre IB
            bh = df.loc[ib_mask, "bar_high"].dropna()
            bl = df.loc[ib_mask, "bar_low"].dropna()
            bh = bh[bh > 100]
            bl = bl[bl > 100]

            if len(bh) == 0 or len(bl) == 0:
                continue

            ib_h = bh.max()
            ib_l = bl.min()

            if ib_h <= ib_l:
                continue

            # IB partielle : pour les barres PENDANT l'IB,
            # utiliser le running max/min jusqu'a cette barre
            ib_indices = df.index[ib_mask]
            for idx in ib_indices:
                bars_up_to = df.loc[ib_indices[ib_indices <= idx]]
                bh_partial = bars_up_to["bar_high"].dropna()
                bl_partial = bars_up_to["bar_low"].dropna()
                bh_partial = bh_partial[bh_partial > 100]
                bl_partial = bl_partial[bl_partial > 100]
                if len(bh_partial) > 0:
                    ib_high_series.at[idx] = bh_partial.max()
                if len(bl_partial) > 0:
                    ib_low_series.at[idx] = bl_partial.min()

            # Apres l'IB (>= 10h30 ET) : IB figee (max/min complets)
            after_ib = day_mask & (time_et > IB_END_ET)
            ib_high_series.loc[after_ib] = ib_h
            ib_low_series.loc[after_ib] = ib_l

        # Forward-fill pour les barres avant l'IB (pas de valeur)
        # Elles restent NaN → les colonnes derivees seront null

        price = df["price"].values
        ib_h = ib_high_series.values
        ib_l = ib_low_series.values
        atr = df["atr"].values if "atr" in df.columns else np.full(len(df), 400.0)
        atr_ticks = atr / TICK_SIZE

        # Recalculer toutes les colonnes IB
        ib_range = np.where(
            np.isfinite(ib_h) & np.isfinite(ib_l) & (ib_h > ib_l),
            (ib_h - ib_l) / TICK_SIZE,
            0.0
        )

        ib_range_atr = np.where(
            (ib_range > 0) & (atr_ticks > 0),
            ib_range / atr_ticks,
            np.nan
        )

        dist_ib_high = np.where(
            np.isfinite(ib_h) & (ib_h > 100),
            (ib_h - price) / TICK_SIZE,
            np.nan
        )

        dist_ib_low = np.where(
            np.isfinite(ib_l) & (ib_l > 100),
            (ib_l - price) / TICK_SIZE,
            np.nan
        )

        # IB complete = seulement en session US (9:30-16:00) apres 10:30
        ib_complete = np.where(
            (time_et >= IB_END_ET) & (time_et < 16 * 60),
            1.0, 0.0
        )

        ib_broken_up = np.where(
            (ib_complete == 1.0) & np.isfinite(ib_h) & (price > ib_h),
            1.0, 0.0
        )

        ib_broken_down = np.where(
            (ib_complete == 1.0) & np.isfinite(ib_l) & (price < ib_l),
            1.0, 0.0
        )

        ib_is_narrow = np.where(
            np.isfinite(ib_range_atr) & (ib_range_atr < IB_NARROW_RATIO),
            1.0, 0.0
        )

        ib_is_wide = np.where(
            np.isfinite(ib_range_atr) & (ib_range_atr > IB_WIDE_RATIO),
            1.0, 0.0
        )

        # Position dans l'IB : [0.0, 1.0] ou NaN si hors range OU IB non-complete.
        # FIX 2026-04-16 : alignement sur C++ DMP_Transform.h:531 PosInRange post-fix.
        #   - Avant : sentinel -1 + echelle x100 (produit [0, 100], -1 hors)
        #   - Apres : NaN hors range + echelle [0, 1] (coherent avec va_position_pct)
        # FIX 2026-04-20 (schema-auditor + code-reviewer) : alignement avec fix C++
        # DMP_Transform.h:848 post-2026-04-20. IB partielle (ib_complete=0) = range
        # non-significatif. Sans ce guard, ib_recalc.py pollue 100% des barres
        # 9:30-10:30 ET du dataset ML (ib_pos calcule sur range en formation),
        # annulant le fix C++ cote JSONL. Coherence C++/Python critique.
        ib_pos = np.full(len(df), np.nan)
        valid_range = np.isfinite(ib_h) & np.isfinite(ib_l) & (ib_h > ib_l)
        in_range = valid_range & (price >= ib_l) & (price <= ib_h) & (ib_complete == 1.0)
        ib_pos[in_range] = (
            (price[in_range] - ib_l[in_range]) /
            (ib_h[in_range] - ib_l[in_range])
        )

        # Ecrire les colonnes
        df["dist_ib_high"] = dist_ib_high
        df["dist_ib_low"] = dist_ib_low
        df["ib_range_ticks"] = ib_range
        df["ib_range_atr"] = ib_range_atr
        df["ib_is_narrow"] = ib_is_narrow
        df["ib_is_wide"] = ib_is_wide
        df["ib_complete"] = ib_complete
        df["ib_broken_up"] = ib_broken_up
        df["ib_broken_down"] = ib_broken_down
        df["ib_position_pct"] = ib_pos

        # Stats
        us_mask = time_et >= IB_START_ET
        us_after = us_mask & (ib_complete == 1.0)
        valid_ib = np.isfinite(dist_ib_high) & us_after
        n_valid = valid_ib.sum()
        n_us = us_after.sum()

        print(f"  [IBRecalc] {symbol}: IB recalculee depuis bar_high/bar_low")
        if n_us > 0:
            ib_vals = ib_range[us_after & (ib_range > 0)]
            if len(ib_vals) > 0:
                print(f"    dist_ib_high: {n_valid}/{n_us} valides apres 10h30")
                print(f"    ib_range: {ib_vals[0]:.0f}t (fige apres IB)")
                ib_h_val = ib_h[us_after & np.isfinite(ib_h)]
                ib_l_val = ib_l[us_after & np.isfinite(ib_l)]
                if len(ib_h_val) > 0 and len(ib_l_val) > 0:
                    print(f"    IB High={ib_h_val[0]:.2f}  IB Low={ib_l_val[0]:.2f}")
            else:
                print(f"    Aucune barre IB trouvee dans la fenetre 9h30-10h30 ET")

        return df

    def summary(self, df: pd.DataFrame) -> None:
        """Affiche les stats IB pour validation."""
        cols = ["dist_ib_high", "dist_ib_low", "ib_range_ticks",
                "ib_range_atr", "ib_complete", "ib_broken_up", "ib_broken_down"]

        print("\n  === IB Recalc Summary ===")
        for col in cols:
            if col not in df.columns:
                print(f"  {col:20s}: ABSENT")
                continue
            vals = pd.to_numeric(df[col], errors="coerce")
            valid = vals.dropna()
            non_zero = (valid != 0).sum()
            if len(valid) == 0:
                print(f"  {col:20s}: tout NaN")
            else:
                print(f"  {col:20s}: {len(valid):>5d} valides, "
                      f"non-zero={non_zero}, "
                      f"range=[{valid.min():+.1f}, {valid.max():+.1f}]")

    def validate(self, df: pd.DataFrame, symbol: str = "ES") -> bool:
        """
        Test de validation IB (pour mia_bench.py).
        Retourne True si PASS, False si FAIL.
        """
        errors = []

        # Barres US apres 10h30
        ts_sec = pd.to_numeric(df["ts"], errors="coerce") / 1000.0
        utc_dt = pd.to_datetime(df["ts"], unit="ms", utc=True)
        month = utc_dt.dt.month
        day = utc_dt.dt.day
        is_dst = (
            ((month >= 4) & (month <= 10)) |
            ((month == 3) & (day >= 8)) |
            ((month == 11) & (day <= 7))
        )
        offset = np.where(is_dst, 4, 5)
        h_et = (utc_dt.dt.hour - offset + 24) % 24
        m_et = utc_dt.dt.minute
        time_et = h_et * 60 + m_et
        us_after_ib = (time_et > IB_END_ET) & (time_et < 16 * 60)

        n_us = us_after_ib.sum()
        if n_us < 10:
            print(f"  [IBRecalc] Pas assez de barres US apres 10h30 ({n_us})")
            return True  # Pas assez de donnees pour juger

        ib_range = pd.to_numeric(df.loc[us_after_ib, "ib_range_ticks"], errors="coerce")
        dist_h = pd.to_numeric(df.loc[us_after_ib, "dist_ib_high"], errors="coerce")

        # Check 1: ib_range > 0 apres 10h30
        valid_range = (ib_range > 0).sum()
        if valid_range < n_us * 0.8:
            errors.append(f"ib_range_ticks=0 sur {n_us - valid_range}/{n_us} barres US")

        # Check 2: ib_range realiste
        if valid_range > 0:
            median_range = ib_range[ib_range > 0].median()
            # Bornes larges pour couvrir VIX 15-35 (volatilite variable)
            if symbol == "ES" and (median_range < 15 or median_range > 400):
                errors.append(f"ib_range ES={median_range:.0f}t hors [15-400]")
            if symbol == "NQ" and (median_range < 50 or median_range > 1500):
                errors.append(f"ib_range NQ={median_range:.0f}t hors [50-1500]")

        # Check 3: dist_ib_high non-null
        valid_h = dist_h.notna().sum()
        if valid_h < n_us * 0.8:
            errors.append(f"dist_ib_high null sur {n_us - valid_h}/{n_us} barres US")

        if errors:
            for e in errors:
                print(f"  [IBRecalc FAIL] {e}")
            return False

        print(f"  [IBRecalc PASS] {n_us} barres US, "
              f"ib_range={ib_range[ib_range>0].median():.0f}t median")
        return True


if __name__ == "__main__":
    import json
    import sys

    base = "D:/TRADING_SIERRA_CHART_AUTO/DATA"
    files = [
        (f"{base}/ES/20260330_ES.jsonl", "ES"),
        (f"{base}/NQ/20260330_NQ.jsonl", "NQ"),
    ]

    recalc = IBRecalc()

    for path, sym in files:
        print(f"\n{'='*60}")
        print(f"  {sym} — {path}")
        print(f"{'='*60}")

        try:
            rows = [json.loads(l) for l in open(path) if l.strip()]
            df = pd.DataFrame(rows)
            print(f"  {len(df)} barres chargees")

            # Avant recalcul
            us_mask = df.get("session_id", pd.Series("", index=df.index)) == "US"
            if us_mask.any():
                ib_h_before = pd.to_numeric(df.loc[us_mask, "dist_ib_high"], errors="coerce")
                print(f"  AVANT: dist_ib_high valides = {ib_h_before.notna().sum()}/{us_mask.sum()}")

            # Recalcul
            df = recalc.compute(df, sym)

            # Apres recalcul
            if us_mask.any():
                ib_h_after = pd.to_numeric(df.loc[us_mask, "dist_ib_high"], errors="coerce")
                print(f"  APRES: dist_ib_high valides = {ib_h_after.notna().sum()}/{us_mask.sum()}")

            recalc.summary(df)

            # Validation
            print()
            recalc.validate(df, sym)

        except Exception as e:
            print(f"  ERREUR: {e}")
