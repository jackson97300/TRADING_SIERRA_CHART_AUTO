"""
signal_engine.py — Moteur de signaux ML MIA V2
=================================================

Charge les modeles LightGBM (score_buy + score_sell) et genere
les signaux de trading avec seuil de confiance.

Pipeline :
    Barre DMP → features → LightGBM.predict_proba() → score → seuil → signal

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import hashlib
import os
import pickle
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict

import numpy as np
import pandas as pd

from bot_config import BotConfig, SignalConfig

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """Signal de trading genere par le ML."""
    direction: int = 0          # +1 = BUY, -1 = SELL, 0 = HOLD
    score: float = 0.0          # Probabilite LightGBM [0, 1]
    confidence: str = ""        # "HIGH" / "MEDIUM" / "LOW"
    reason: str = ""            # Explication
    features_used: int = 0


class SignalEngine:
    """Moteur de signaux basé sur LightGBM."""

    def __init__(self, config: BotConfig):
        self.cfg = config.signal
        self.model_path = Path(config.model_path)
        self.models: Dict[str, dict] = {}  # {symbol_side: {model, features, threshold}}

    def load_models(self, symbol: str) -> bool:
        """Charge les modeles buy et sell pour un symbole."""
        for side in ["buy", "sell"]:
            model_file = self.model_path / f"{symbol}_{side}_model.pkl"
            hash_file = self.model_path / f"{symbol}_{side}_model.sha256"

            if not model_file.exists():
                return False

            # Verifier le hash SHA256 si disponible (protection pickle)
            if hash_file.exists():
                expected_hash = hash_file.read_text().strip()
                actual_hash = hashlib.sha256(model_file.read_bytes()).hexdigest()
                if actual_hash != expected_hash:
                    logger.error(f"Hash mismatch pour {model_file.name} — fichier corrompu ou modifie")
                    return False

            try:
                with open(model_file, "rb") as f:
                    model_dict = pickle.load(f)
                self.models[f"{symbol}_{side}"] = model_dict
            except Exception as e:
                logger.error(f"Erreur chargement modele {model_file}: {e}")
                return False

        return True

    def predict(self, symbol: str, features_row: dict) -> Signal:
        """
        Genere un signal pour une barre.

        Args:
            symbol: "ES" ou "NQ"
            features_row: dict des features de la barre courante

        Returns:
            Signal avec direction, score, confiance
        """
        buy_key = f"{symbol}_buy"
        sell_key = f"{symbol}_sell"

        if buy_key not in self.models or sell_key not in self.models:
            return Signal(reason="Modeles non charges")

        # Score BUY
        buy_score = self._score(self.models[buy_key], features_row)

        # Score SELL
        sell_score = self._score(self.models[sell_key], features_row)

        # Decision
        if buy_score >= self.cfg.min_score_buy and buy_score > sell_score:
            conf = self._confidence(buy_score)
            return Signal(
                direction=1,
                score=buy_score,
                confidence=conf,
                reason=f"BUY score={buy_score:.3f} > seuil {self.cfg.min_score_buy}",
                features_used=len(self.models[buy_key].get("features", [])),
            )

        elif sell_score >= self.cfg.min_score_sell and sell_score > buy_score:
            conf = self._confidence(sell_score)
            return Signal(
                direction=-1,
                score=sell_score,
                confidence=conf,
                reason=f"SELL score={sell_score:.3f} > seuil {self.cfg.min_score_sell}",
                features_used=len(self.models[sell_key].get("features", [])),
            )

        return Signal(
            direction=0,
            score=max(buy_score, sell_score),
            reason=f"HOLD (buy={buy_score:.3f} sell={sell_score:.3f}, seuils={self.cfg.min_score_buy}/{self.cfg.min_score_sell})",
        )

    def check_menthorq_gate(self, direction: int,
                              gamma_condition: float) -> tuple:
        """
        Verifie les gates MenthorQ avant d'executer.

        Returns:
            (allowed: bool, reason: str)
        """
        if direction == 1 and gamma_condition < 0:
            if self.cfg.block_long_if_gamma_negative:
                return False, "BLOCKED: Long interdit en gamma negatif"

        if direction == -1 and gamma_condition > 0:
            if self.cfg.block_short_if_gamma_positive:
                return False, "BLOCKED: Short interdit en gamma positif"

        return True, "OK"

    def _score(self, model_dict: dict, features_row: dict) -> float:
        """Calcule le score de probabilite pour un modele."""
        features = model_dict.get("features", [])
        model = model_dict.get("model")

        if model is None:
            return 0.0

        # Construire le vecteur de features
        X = []
        for f in features:
            val = features_row.get(f, 0.0)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                val = 0.0
            X.append(float(val))

        X = np.array([X])

        try:
            proba = model.predict_proba(X)
            return float(proba[0, 1])  # P(signal=1)
        except Exception:
            return 0.0

    def _confidence(self, score: float) -> str:
        if score >= 0.70:
            return "HIGH"
        elif score >= 0.60:
            return "MEDIUM"
        else:
            return "LOW"
