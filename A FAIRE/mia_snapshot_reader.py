"""
MIA Snapshot Reader — Lecture des fichiers JSONL V2 pour backtest & ML
======================================================================
06/02/2026

Usage:
    from mia_snapshot_reader import SnapshotReader
    
    reader = SnapshotReader(r"D:\MIA_IA_system\DATA_SIERRA_CHART\BOT_SNAPSHOTS")
    
    # Charger une journée
    df = reader.load_day("ES", "2026-02-06")
    
    # Charger une plage de dates
    df = reader.load_range("NQ", "2026-02-03", "2026-02-07")
    
    # Extraire les features ML (DataFrame aplati)
    features = reader.to_ml_features(df)
    
    # Filtrer uniquement les ticks avec layers évalués
    signals = reader.get_signals_only(df)
"""

import json
import os
import gzip
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np


class SnapshotReader:
    """Lecteur de fichiers snapshot JSONL V2."""
    
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
    
    # ═══════════════════════════════════════════════════════════════════
    # CHARGEMENT
    # ═══════════════════════════════════════════════════════════════════
    
    def load_day(self, symbol: str, date: str) -> pd.DataFrame:
        """
        Charger tous les snapshots d'une journée.
        
        Args:
            symbol: "ES" ou "NQ"
            date: "2026-02-06" ou "20260206"
        
        Returns:
            DataFrame avec colonnes JSON aplaties
        """
        dt = self._parse_date(date)
        filepath = self._get_filepath(symbol, dt)
        
        if not filepath.exists():
            # Essayer version compressée
            gz_path = filepath.with_suffix('.jsonl.gz')
            if gz_path.exists():
                return self._read_jsonl_gz(gz_path)
            print(f"⚠️ Fichier non trouvé: {filepath}")
            return pd.DataFrame()
        
        return self._read_jsonl(filepath)
    
    def load_range(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Charger plusieurs jours."""
        dt_start = self._parse_date(start)
        dt_end = self._parse_date(end)
        
        frames = []
        current = dt_start
        while current <= dt_end:
            df = self.load_day(symbol, current.strftime("%Y-%m-%d"))
            if not df.empty:
                frames.append(df)
            current += timedelta(days=1)
        
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)
    
    # ═══════════════════════════════════════════════════════════════════
    # FEATURES ML (aplatir le JSON imbriqué)
    # ═══════════════════════════════════════════════════════════════════
    
    def to_ml_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transformer le DataFrame brut en features ML plates.
        Aplatit toutes les colonnes dict en colonnes individuelles.
        
        Résultat: ~180 colonnes numériques prêtes pour sklearn.
        """
        if df.empty:
            return df
        
        flat = pd.json_normalize(df.to_dict('records'), sep='_')
        
        # Convertir les booléens en int pour ML
        bool_cols = flat.select_dtypes(include=['bool']).columns
        for col in bool_cols:
            flat[col] = flat[col].astype(int)
        
        # Supprimer colonnes texte (on garde les numériques)
        text_cols = flat.select_dtypes(include=['object']).columns
        meta_cols = ['_v', 'sym', 'session', 'hms',
                     'layers_l1_level', 'layers_l3_ctx',
                     'sltp_sl_on', 'sltp_tp_on']
        drop_cols = [c for c in text_cols if c in meta_cols]
        
        # Garder les colonnes texte utiles comme catégories
        keep_text = ['session', 'hms', 'layers_l1_level', 'layers_l3_ctx']
        
        return flat
    
    def get_signals_only(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filtrer uniquement les ticks où les layers ont été évalués."""
        if df.empty:
            return df
        
        flat = pd.json_normalize(df.to_dict('records'), sep='_')
        
        # L1 non-null = signal évalué
        mask = flat['layers_l1_pass'].notna() if 'layers_l1_pass' in flat.columns else pd.Series([False] * len(flat))
        return flat[mask].copy()
    
    def get_trades(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filtrer uniquement les ticks avec un SLTP (= trade ouvert)."""
        if df.empty:
            return df
        
        flat = pd.json_normalize(df.to_dict('records'), sep='_')
        
        mask = flat['sltp_sl'].notna() if 'sltp_sl' in flat.columns else pd.Series([False] * len(flat))
        return flat[mask].copy()
    
    # ═══════════════════════════════════════════════════════════════════
    # ANALYSE RAPIDE
    # ═══════════════════════════════════════════════════════════════════
    
    def summary(self, df: pd.DataFrame) -> dict:
        """Résumé rapide d'une journée de données."""
        if df.empty:
            return {"status": "empty"}
        
        flat = pd.json_normalize(df.to_dict('records'), sep='_')
        
        n_total = len(flat)
        n_signals = flat['layers_l1_pass'].notna().sum() if 'layers_l1_pass' in flat.columns else 0
        n_l1_pass = (flat['layers_l1_pass'] == True).sum() if 'layers_l1_pass' in flat.columns else 0
        n_l2_pass = (flat['layers_l2_pass'] == True).sum() if 'layers_l2_pass' in flat.columns else 0
        n_l3_pass = (flat['layers_l3_pass'] == True).sum() if 'layers_l3_pass' in flat.columns else 0
        n_l4_pass = (flat['layers_l4_pass'] == True).sum() if 'layers_l4_pass' in flat.columns else 0
        n_trades = flat['sltp_sl'].notna().sum() if 'sltp_sl' in flat.columns else 0
        
        return {
            "total_snapshots": n_total,
            "duration_hours": n_total / 3600,
            "signals_evaluated": int(n_signals),
            "l1_passed": int(n_l1_pass),
            "l2_passed": int(n_l2_pass),
            "l3_passed": int(n_l3_pass),
            "l4_passed": int(n_l4_pass),
            "trades": int(n_trades),
            "funnel": f"L1:{n_l1_pass} → L2:{n_l2_pass} → L3:{n_l3_pass} → L4:{n_l4_pass} → Trades:{n_trades}",
            "bn_score_mean": flat['bn_sc_score'].mean() if 'bn_sc_score' in flat.columns else None,
            "bn_score_std": flat['bn_sc_score'].std() if 'bn_sc_score' in flat.columns else None,
            "price_range": f"{flat['px'].min():.2f} - {flat['px'].max():.2f}" if 'px' in flat.columns else None,
        }
    
    def correlation_matrix(self, df: pd.DataFrame, target: str = 'layers_l4_pass') -> pd.Series:
        """
        Trouver les features les plus corrélées avec le target.
        Utile pour identifier les patterns cachés.
        
        Args:
            target: Colonne cible (ex: 'layers_l4_pass', 'layers_l1_pass')
        """
        flat = self.to_ml_features(df)
        
        if target not in flat.columns:
            print(f"⚠️ Colonne '{target}' non trouvée")
            return pd.Series()
        
        # Garder uniquement colonnes numériques
        numeric = flat.select_dtypes(include=[np.number])
        
        if target not in numeric.columns:
            numeric[target] = flat[target].astype(float)
        
        corr = numeric.corr()[target].drop(target, errors='ignore')
        return corr.abs().sort_values(ascending=False).head(30)
    
    # ═══════════════════════════════════════════════════════════════════
    # COMPRESSION
    # ═══════════════════════════════════════════════════════════════════
    
    def compress_day(self, symbol: str, date: str, delete_original: bool = False):
        """Compresser un fichier JSONL en .jsonl.gz (ratio ~10:1)."""
        dt = self._parse_date(date)
        filepath = self._get_filepath(symbol, dt)
        
        if not filepath.exists():
            print(f"⚠️ Fichier non trouvé: {filepath}")
            return
        
        gz_path = filepath.with_suffix('.jsonl.gz')
        
        with open(filepath, 'rb') as f_in:
            with gzip.open(gz_path, 'wb', compresslevel=6) as f_out:
                f_out.writelines(f_in)
        
        original_size = filepath.stat().st_size / (1024 * 1024)
        compressed_size = gz_path.stat().st_size / (1024 * 1024)
        ratio = original_size / compressed_size if compressed_size > 0 else 0
        
        print(f"✅ Compressé: {original_size:.1f} MB → {compressed_size:.1f} MB (ratio {ratio:.1f}:1)")
        
        if delete_original:
            filepath.unlink()
            print(f"🗑️ Original supprimé: {filepath}")
    
    # ═══════════════════════════════════════════════════════════════════
    # INTERNES
    # ═══════════════════════════════════════════════════════════════════
    
    def _parse_date(self, date) -> datetime:
        if isinstance(date, datetime):
            return date
        date = date.replace("-", "")
        return datetime.strptime(date, "%Y%m%d")
    
    def _get_filepath(self, symbol: str, dt: datetime) -> Path:
        return (self.base_path / f"{dt.year:04d}" / f"{dt.month:02d}" / 
                f"{dt.year:04d}{dt.month:02d}{dt.day:02d}" /
                f"snapshot_{symbol}_{dt.year:04d}{dt.month:02d}{dt.day:02d}.jsonl")
    
    def _read_jsonl(self, filepath: Path) -> pd.DataFrame:
        records = []
        errors = 0
        with open(filepath, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    errors += 1
                    if errors <= 3:
                        print(f"⚠️ JSON invalide ligne {line_num}")
        
        if errors > 3:
            print(f"⚠️ {errors} lignes JSON invalides au total")
        
        print(f"📊 Chargé {len(records):,} snapshots depuis {filepath.name}")
        return pd.DataFrame(records)
    
    def _read_jsonl_gz(self, filepath: Path) -> pd.DataFrame:
        records = []
        with gzip.open(filepath, 'rt') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        
        print(f"📊 Chargé {len(records):,} snapshots depuis {filepath.name}")
        return pd.DataFrame(records)


# ═══════════════════════════════════════════════════════════════════════
# EXEMPLE D'UTILISATION
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    BASE = r"D:\MIA_IA_system\DATA_SIERRA_CHART\BOT_SNAPSHOTS"
    reader = SnapshotReader(BASE)
    
    # --- Charger une journée ---
    df = reader.load_day("ES", "2026-02-06")
    
    if not df.empty:
        # --- Résumé ---
        info = reader.summary(df)
        print("\n" + "=" * 60)
        print("📊 RÉSUMÉ DE LA JOURNÉE")
        print("=" * 60)
        for k, v in info.items():
            print(f"  {k}: {v}")
        
        # --- Features ML ---
        features = reader.to_ml_features(df)
        print(f"\n📐 Features ML: {features.shape[0]} lignes × {features.shape[1]} colonnes")
        
        # --- Corrélations avec L4 pass ---
        print("\n🔍 Top corrélations avec l4_pass:")
        corr = reader.correlation_matrix(df, 'layers_l4_pass')
        if not corr.empty:
            for feat, val in corr.head(15).items():
                print(f"  {val:.3f}  {feat}")
        
        # --- Signaux uniquement ---
        signals = reader.get_signals_only(df)
        print(f"\n🎯 Signaux évalués: {len(signals)} sur {len(df)} ticks")
        
        # --- Compresser (optionnel) ---
        # reader.compress_day("ES", "2026-02-06", delete_original=False)
