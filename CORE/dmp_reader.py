"""
DMP Reader - Lecture des fichiers JSONL DMP (258-262 colonnes, schema 3.7.0-3.7.2)

Lit les fichiers produits par DMP_Main.cpp (Sierra Chart) et retourne
un DataFrame pandas pret pour l'analyse et le ML.

Usage:
    from dmp_reader import DmpReader

    reader = DmpReader("D:/TRADING_SIERRA_CHART_AUTO/DATA")
    df = reader.load("NQ", "2026-03-05")
    df = reader.load_range("NQ", "2026-03-05", "2026-03-10")
    us = reader.us_only(df)
    clean = reader.drop_constants(df)

Auteur : MIA Trading System
Date   : 2026-03-05
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

import pandas as pd
import numpy as np


class DmpReader:
    """Lecteur de fichiers JSONL produits par le DMP C++."""

    def __init__(self, base_path: str):
        """
        Args:
            base_path: Racine des données DMP.
                       Structure attendue: {base}/{SYM}/YYYYMMDD_{SYM}.jsonl
        """
        self.base = Path(base_path)

    # ─── CHARGEMENT ───────────────────────────────────────────────────

    def load(self, symbol: str, date: str) -> pd.DataFrame:
        """
        Charger un fichier JSONL d'une journée.

        Args:
            symbol: "ES" ou "NQ"
            date:   "2026-03-05" ou "20260305"

        Returns:
            DataFrame avec colonnes plates (214+), index = datetime ET
        """
        dt = self._parse_date(date)
        path = self._filepath(symbol, dt)

        if not path.exists():
            print(f"⚠️ Fichier non trouvé: {path}")
            return pd.DataFrame()

        rows = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = self._dedup_and_sort(df)
        df = self._add_datetime_index(df)
        return df

    def load_range(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Charger plusieurs jours consécutifs."""
        dt_start = self._parse_date(start)
        dt_end = self._parse_date(end)

        frames = []
        current = dt_start
        while current <= dt_end:
            df = self.load(symbol, current.strftime("%Y-%m-%d"))
            if not df.empty:
                frames.append(df)
            current += timedelta(days=1)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames)

    def load_file(self, filepath: str) -> pd.DataFrame:
        """Charger directement depuis un chemin fichier."""
        rows = []
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = self._dedup_and_sort(df)
        df = self._add_datetime_index(df)
        return df

    # ─── DEDUPLICATION ────────────────────────────────────────────────

    def _dedup_and_sort(self, df: pd.DataFrame) -> pd.DataFrame:
        """Deduplique par ts + trie chronologiquement.

        FIX 13/04/2026 : certains fichiers JSONL historiques (20260327,
        20260330, 20260407) contiennent des duplicate timestamps a cause
        du bug thread_local pre-fix 09/04. Cette fonction retire les
        lignes dupliquees (keep='first') et garantit l'ordre chronologique
        strict. Impact negligeable (~6 barres sur 26000) mais propre.
        """
        if "ts" not in df.columns:
            return df
        before = len(df)
        df = df.drop_duplicates(subset="ts", keep="first")
        after = len(df)
        if before != after:
            # Note : pas de print pour eviter le bruit, c'est tres rare
            pass
        df = df.sort_values("ts", ascending=True, kind="stable").reset_index(drop=True)
        return df

    # ─── FILTRES ──────────────────────────────────────────────────────

    def us_only(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filtrer session US (session_id == 'US' ou session == 2)."""
        if "session_id" in df.columns:
            return df[df["session_id"] == "US"].copy()
        if "session" in df.columns:
            return df[df["session"] == 2].copy()
        return df

    def rth_only(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filtrer RTH (9:30-16:00 ET)."""
        if "datetime_et" in df.columns:
            mask = (df["datetime_et"].dt.hour >= 9) & (
                (df["datetime_et"].dt.hour > 9) | (df["datetime_et"].dt.minute >= 30)
            ) & (df["datetime_et"].dt.hour < 16)
            return df[mask].copy()
        return self.us_only(df)

    @staticmethod
    def drop_constants(df: pd.DataFrame, verbose: bool = False) -> pd.DataFrame:
        """
        Supprimer les colonnes constantes (inutiles pour ML).
        Garde les colonnes meta (ts, sym, contract, session_id).
        """
        keep_always = {"ts", "sym", "contract", "session_id", "session",
                       "datetime_utc", "datetime_et"}
        nunique = df.nunique()
        to_drop = [c for c in nunique[nunique <= 1].index
                   if c not in keep_always]
        if verbose and to_drop:
            print(f"  Dropping {len(to_drop)} constant columns: {to_drop[:10]}{'...' if len(to_drop)>10 else ''}")
        return df.drop(columns=to_drop)

    # ─── RÉSUMÉ ───────────────────────────────────────────────────────

    def summary(self, df: pd.DataFrame) -> dict:
        """Résumé rapide d'un DataFrame DMP."""
        if df.empty:
            return {"status": "empty"}

        n = len(df)
        n_cols = len(df.columns)

        # Sessions
        sessions = df["session_id"].value_counts().to_dict() if "session_id" in df.columns else {}

        # Nulls
        null_pct = (df.isnull().sum() / n * 100).sort_values(ascending=False)
        high_null = null_pct[null_pct > 50].to_dict()

        # Constants
        nunique = df.nunique()
        constants = nunique[nunique <= 1].index.tolist()

        # Prix
        p_min = df["price"].min() if "price" in df.columns else None
        p_max = df["price"].max() if "price" in df.columns else None

        # Open type
        ot = df["open_type"].value_counts().to_dict() if "open_type" in df.columns else {}

        info = {
            "barres": n,
            "colonnes": n_cols,
            "sessions": sessions,
            "prix_range": f"{p_min:.2f} → {p_max:.2f}" if p_min else None,
            "open_type": ot,
            "null_>50%": high_null,
            "constants": len(constants),
        }

        # Affichage
        print(f"  {n} barres | {n_cols} colonnes")
        print(f"  Sessions: {sessions}")
        if p_min:
            print(f"  Prix: {p_min:.2f} → {p_max:.2f}")
        if ot:
            print(f"  Open type: {ot}")
        if high_null:
            print(f"  Champs >50% null: {list(high_null.keys())}")
        print(f"  Champs constants: {len(constants)}")

        return info

    # ─── HELPERS PRIVÉS ───────────────────────────────────────────────

    def _filepath(self, symbol: str, dt: datetime) -> Path:
        sym = symbol.upper()
        date_str = dt.strftime("%Y%m%d")
        return self.base / sym / f"{date_str}_{sym}.jsonl"

    def _parse_date(self, date: str) -> datetime:
        date = date.replace("-", "")
        return datetime.strptime(date, "%Y%m%d")

    def _add_datetime_index(self, df: pd.DataFrame) -> pd.DataFrame:
        if "ts" in df.columns:
            df["datetime_utc"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            df["datetime_et"] = df["datetime_utc"].dt.tz_convert("US/Eastern")
            df = df.set_index("datetime_et", drop=False)
            df = df.sort_index()
        return df
