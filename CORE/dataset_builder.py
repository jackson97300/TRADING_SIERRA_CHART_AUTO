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
    # --- VWAP ---
    "vwap_slope_30", "vwap_m_side", "bool_above_vwap_m",
    "dist_prev_vwap_sd1u", "dist_vwap_d_sd1u",
    "dist_vwap_d_sd3u", "dist_vwap_d_sd3d",  # Schema 3.7.2
    # --- Delta / CVD / Volume ---
    "delta_bar", "delta_bar_vol_norm", "delta_pct", "delta_day",
    "cvd_bar_delta", "cvd_day_dir", "ask_bid_imbalance",
    "ask_pct", "bid_pct", "buy_sell_ratio",
    "rvol", "rvol_absorb_buy", "momentum_5b", "diag_imbalance",
    # --- Big Orders ---
    "big_ask_cluster_20t_t2", "big_ask_cluster_20t_t3", "n_big_ask_t3",
    "dist_blind_nearest_up",
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
    "bn_color_up", "bn_color_dn", "bn_color_dn_2",
    "bar_color_up", "bar_color_dn",
    "bn_pressure_ask", "bn_long_up", "bn_long_dn",
    "bn_volume_up", "bn_volume_dn", "bn_score_bull",
    "dist_ext_color_up", "dist_ext_color_dn",
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

        # 3. Charger labels
        lbl_file = self.labels_path / f"ALL_{symbol}_labels.parquet"
        if not lbl_file.exists():
            raise FileNotFoundError(f"Labels non trouves : {lbl_file}")
        df_lbl = pd.read_parquet(lbl_file)
        df_lbl = df_lbl[df_lbl["valid_bar"] == True][["ts", "label", "partial_session"]].copy()

        # 4. Merge
        merged = df_feat.merge(df_lbl, on="ts", how="inner")
        merged = merged.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        print(f"  Merge: {len(merged)} barres valides")

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
        })
        for col in available:
            result[col] = df_clean[col].values

        print(f"  [OK] Dataset: {len(result)} barres x {len(available)} features")
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
        """Retourne la liste des features dans le dataset (sans ts/label/meta)."""
        return [c for c in df.columns if c not in {"ts", "label", "partial_session", "is_nq"}]

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
        df = self._compute_amd(df)

        # --- Intermarket (10 im_*) ---
        df = self._compute_intermarket(df, symbol, other_symbol)

        n_after = len(df.columns)
        print(f"  Features derivees: +{n_after - n_before} colonnes ({n_before} -> {n_after})")
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
        """Enrichit avec les features macro MenthorQ (Q-Score, GEX, Swing, etc.)."""
        try:
            from mia_menthorq_reader import MenthorQReader
            mq_path = self.data_path.parent / "MENTHORQ"
            if not mq_path.exists():
                mq_path = self.data_path / ".." / "MENTHORQ"
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

    def _compute_amd(self, df: pd.DataFrame) -> pd.DataFrame:
        """AMD ICT Power of 3 features (amd_*)."""
        try:
            from mia_amd import AmdEngine
            engine = AmdEngine()
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

    def _load_features(self, symbol: str) -> pd.DataFrame:
        """Charge tous les JSONL d'un symbole."""
        sym_dir = self.data_path / symbol
        if not sym_dir.exists():
            return pd.DataFrame()

        rows = []
        for f in sorted(os.listdir(sym_dir)):
            if not f.endswith(".jsonl"):
                continue
            with open(sym_dir / f, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

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
    BACKUP_DATA  = "D:/TRADING_SIERRA_CHART_AUTO/DATA/BACKUP/schema_370"
    CURRENT_DATA = "D:/TRADING_SIERRA_CHART_AUTO/DATA"
    LABELS_PATH  = "D:/TRADING_SIERRA_CHART_AUTO/DATA/LABELS"
    OUTPUT_DIR   = "D:/TRADING_SIERRA_CHART_AUTO/DATA/DATASETS"

    use_backup = "--current" not in sys.argv
    data_path  = BACKUP_DATA if use_backup else CURRENT_DATA

    print(f"DatasetBuilder v2 — source: {'BACKUP 3.7.0' if use_backup else 'CURRENT 3.7.1'}")
    print(f"Data: {data_path}")
    print()

    # --- Build avec auto-detection (pas de liste fixe) ---
    builder = DatasetBuilder(
        data_path=data_path,
        labels_path=LABELS_PATH,
        features=None,        # auto-detect toutes les features
        use_derived=True,     # ctx_* + im_* + amd_* + rvol_*
    )

    # ES
    df_es = builder.build("ES")
    validated_es = builder.screen_spearman(df_es, min_rho=0.02)
    print(f"\n=== ES: {len(validated_es)} features validees ===")

    # Rebuild avec features validees seulement
    builder_final = DatasetBuilder(
        data_path=data_path,
        labels_path=LABELS_PATH,
        features=validated_es,
        use_derived=True,
    )
    df_es_final = builder_final.build("ES")
    builder_final.save(df_es_final, f"{OUTPUT_DIR}/ES_dataset_v2.parquet")

    # NQ
    df_nq = builder.build("NQ")
    validated_nq = builder.screen_spearman(df_nq, min_rho=0.02)
    print(f"\n=== NQ: {len(validated_nq)} features validees ===")

    builder_nq = DatasetBuilder(
        data_path=data_path,
        labels_path=LABELS_PATH,
        features=validated_nq,
        use_derived=True,
    )
    df_nq_final = builder_nq.build("NQ")
    builder_nq.save(df_nq_final, f"{OUTPUT_DIR}/NQ_dataset_v2.parquet")

    # Afficher features finales
    for sym, feats in [("ES", validated_es), ("NQ", validated_nq)]:
        print(f"\n=== FEATURES {sym} ({len(feats)}) ===")
        for i, f in enumerate(feats, 1):
            prefix = "ctx_" if f.startswith("ctx_") else \
                     "im_"  if f.startswith("im_")  else \
                     "amd_" if f.startswith("amd_") else \
                     "rvol_" if f.startswith("rvol_") else "dmp"
            print(f"  {i:3d}. [{prefix:>5}] {f}")
