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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict

import numpy as np
import pandas as pd

from bot_config import BotConfig, SignalConfig

logger = logging.getLogger(__name__)

# Systeme logs V2 (22/04/2026) : pattern 11 safe — uniquement primitifs dans ctx
# (jamais features_row complet ni valeurs brutes ML)
try:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("signal_engine", process="bot_legacy")
except Exception:
    _v2log = None

_INFERENCE_SLOW_MS = 50.0  # seuil ML_INFERENCE_SLOW (review agent, LightGBM ~100 features)
_NAN_RATIO_THRESHOLD = 0.20  # seuil DMP_FEATURE_NAN (>20% features NaN/None)
_MAX_SIGNAL_AGE_BARS = 2  # seuil expiration state machine (22/04 fix Jackson)
_POST_CLOSE_COOLDOWN_SEC = 180  # 3 min cooldown post close anti re-entry meme signal


@dataclass
class Signal:
    """Signal de trading genere par le ML."""
    direction: int = 0          # +1 = BUY, -1 = SELL, 0 = HOLD
    score: float = 0.0          # Probabilite LightGBM [0, 1]
    confidence: str = ""        # "HIGH" / "MEDIUM" / "LOW"
    reason: str = ""            # Explication
    features_used: int = 0
    # v1.5 (22/04 fix state machine)
    signal_id: Optional[str] = None      # UUID unique par transition (correlation logs)
    freshness: str = "IDLE"              # NEW | PERSISTENT | EXPIRED | IDLE | COUNTER_TREND_FLIP
    age_bars: int = 0                    # barres depuis first fire


class SignalEngine:
    """Moteur de signaux basé sur LightGBM."""

    def __init__(self, config: BotConfig):
        self.cfg = config.signal
        self.model_path = Path(config.model_path)
        self.models: Dict[str, dict] = {}  # {symbol_side: {model, features, threshold}}
        # v1.5 (22/04 fix state machine) : track transitions par symbol
        # Fix Jackson : evite re-entry sur signal persistant + detecte flips BUY/SELL.
        self._signal_state: Dict[str, dict] = {}  # sym → {'direction', 'signal_id', 'first_bar_ts'}
        self._last_traded_signal_id: Dict[str, str] = {}  # sym → signal_id deja trade (dedup)
        self._last_close_ts: Dict[str, float] = {}  # sym → timestamp close (cooldown post-close)

    def register_trade_close(self, symbol: str) -> None:
        """Appele par bot_main._on_trade_close pour enregistrer cooldown.

        Evite re-entry immediate sur meme signal_id apres SL/TP (3 min par defaut).
        Jackson fix : "evite de prendre trades contre-sens" quand marche flip.
        """
        import time as _t
        self._last_close_ts[symbol] = _t.time()

    def register_signal_traded(self, symbol: str, signal_id: str) -> None:
        """Appele par bot_main quand un signal_id est consomme pour un trade.

        Empeche re-trade du meme signal_id en persistance (FOMO fix).
        """
        if signal_id:
            self._last_traded_signal_id[symbol] = signal_id

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
                    # V2 log : hash mismatch = alerte securite CRITIQUE (tampering possible)
                    if _v2log:
                        _v2log.emit("ML_MODEL_LOAD_FAIL",
                                    path=str(model_file), err="hash_mismatch_SHA256")
                    return False

            try:
                with open(model_file, "rb") as f:
                    model_dict = pickle.load(f)
                self.models[f"{symbol}_{side}"] = model_dict
                # V2 log : succes par modele (granularite buy/sell)
                if _v2log:
                    n_feat = len(model_dict.get("features", []))
                    _v2log.emit("ML_MODEL_LOADED",
                                version=f"{symbol}_{side}", n_features=n_feat)
            except Exception as e:
                logger.error(f"Erreur chargement modele {model_file}: {e}")
                if _v2log:
                    _v2log.emit("ML_MODEL_LOAD_FAIL",
                                path=str(model_file), err=str(e)[:100])
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
            # V2 log : predict appele sans models charges en memoire
            if _v2log:
                _v2log.emit("ML_MODEL_LOAD_FAIL",
                            path=f"{symbol}_buy/sell", err="not_loaded_in_memory")
            return Signal(reason="Modeles non charges")

        # Score BUY
        buy_score = self._score(self.models[buy_key], features_row, symbol=symbol)

        # Score SELL
        sell_score = self._score(self.models[sell_key], features_row, symbol=symbol)

        # Decision raw
        if buy_score >= self.cfg.min_score_buy and buy_score > sell_score:
            raw_direction = 1
            raw_score = buy_score
            raw_reason = f"BUY score={buy_score:.3f} > seuil {self.cfg.min_score_buy}"
            feat_count = len(self.models[buy_key].get("features", []))
        elif sell_score >= self.cfg.min_score_sell and sell_score > buy_score:
            raw_direction = -1
            raw_score = sell_score
            raw_reason = f"SELL score={sell_score:.3f} > seuil {self.cfg.min_score_sell}"
            feat_count = len(self.models[sell_key].get("features", []))
        else:
            raw_direction = 0
            raw_score = max(buy_score, sell_score)
            raw_reason = f"HOLD (buy={buy_score:.3f} sell={sell_score:.3f})"
            feat_count = 0

        # v1.5 (22/04 Jackson fix) State machine transition vs persistance
        state = self._evaluate_state(symbol, raw_direction, features_row)

        # EXPIRED / COOLDOWN / ALREADY_TRADED → effective_direction=0 (non tradable)
        effective_direction = raw_direction
        if state["freshness"] in ("EXPIRED", "COOLDOWN", "ALREADY_TRADED"):
            effective_direction = 0
            raw_reason = f"{state['freshness']} age={state['age_bars']}b — {raw_reason}"

        # V2 log : ML_PREDICT uniquement pour NEW (transitions tradable — anti-verbose)
        if _v2log and state["freshness"] == "NEW" and raw_direction != 0:
            _v2log.emit("ML_PREDICT", sym=symbol,
                        score=raw_score, p_primary=raw_score)

        return Signal(
            direction=effective_direction,
            score=raw_score,
            confidence=self._confidence(raw_score) if raw_direction != 0 else "",
            reason=raw_reason,
            features_used=feat_count,
            signal_id=state["signal_id"],
            freshness=state["freshness"],
            age_bars=state["age_bars"],
        )

    def _evaluate_state(self, symbol: str, raw_direction: int, features_row: dict) -> dict:
        """State machine transition vs persistance (fix 22/04 Jackson).

        Retourne {freshness, signal_id, age_bars}.
        Niveaux :
          NEW             transition 0→±1 OU flip BUY↔SELL. Tradable.
          PERSISTENT      meme signal continue, 1-MAX barres. Deja trade (peut etre trade
                          la 1ere fois si pas encore traite, sinon ALREADY_TRADED).
          EXPIRED         meme signal > MAX_AGE barres. Force HOLD.
          COOLDOWN        position vient de fermer < POST_CLOSE_SEC. Force HOLD (anti
                          re-entry contre-sens Jackson).
          ALREADY_TRADED  signal_id deja consomme. Force HOLD.
          IDLE            direction=0 (HOLD nominal).
        """
        import uuid as _uuid
        import time as _t
        prev = self._signal_state.get(symbol, {"direction": 0, "signal_id": None, "first_bar_ts": 0})
        bar_ts_ms = int(features_row.get("ts", int(_t.time() * 1000)))

        if raw_direction == 0:
            self._signal_state[symbol] = {"direction": 0, "signal_id": None, "first_bar_ts": 0}
            return {"freshness": "IDLE", "signal_id": None, "age_bars": 0}

        # COOLDOWN post-close (anti re-entry contre-sens apres SL/TP)
        last_close = self._last_close_ts.get(symbol, 0)
        if _t.time() - last_close < _POST_CLOSE_COOLDOWN_SEC:
            return {"freshness": "COOLDOWN", "signal_id": prev.get("signal_id"), "age_bars": 0}

        # Transition : direction=0→±1 OU flip BUY↔SELL
        if raw_direction != prev["direction"]:
            new_id = _uuid.uuid4().hex[:8]
            self._signal_state[symbol] = {
                "direction": raw_direction, "signal_id": new_id, "first_bar_ts": bar_ts_ms,
            }
            return {"freshness": "NEW", "signal_id": new_id, "age_bars": 0}

        # Persistance
        age_bars = int((bar_ts_ms - prev["first_bar_ts"]) / 60000) if prev["first_bar_ts"] else 0

        # Signal deja trade → ALREADY_TRADED (dedup)
        last_traded = self._last_traded_signal_id.get(symbol)
        if last_traded and last_traded == prev["signal_id"]:
            return {"freshness": "ALREADY_TRADED", "signal_id": prev["signal_id"], "age_bars": age_bars}

        if age_bars > _MAX_SIGNAL_AGE_BARS:
            return {"freshness": "EXPIRED", "signal_id": prev["signal_id"], "age_bars": age_bars}
        return {"freshness": "PERSISTENT", "signal_id": prev["signal_id"], "age_bars": age_bars}

    def check_menthorq_gate(self, direction: int,
                              gamma_condition: float) -> tuple:
        """
        Verifie les gates MenthorQ avant d'executer.

        Returns:
            (allowed: bool, reason: str)
        """
        if direction == 1 and gamma_condition < 0:
            if self.cfg.block_long_if_gamma_negative:
                # V2 log : gate MQ bloque long en gamma negatif
                if _v2log:
                    _v2log.emit("GATE_RISK_BLOCK",
                                reason="mq_long_blocked_gamma_negative")
                return False, "BLOCKED: Long interdit en gamma negatif"

        if direction == -1 and gamma_condition > 0:
            if self.cfg.block_short_if_gamma_positive:
                # V2 log : gate MQ bloque short en gamma positif
                if _v2log:
                    _v2log.emit("GATE_RISK_BLOCK",
                                reason="mq_short_blocked_gamma_positive")
                return False, "BLOCKED: Short interdit en gamma positif"

        return True, "OK"

    def _score(self, model_dict: dict, features_row: dict, symbol: str = "") -> float:
        """Calcule le score de probabilite pour un modele."""
        features = model_dict.get("features", [])
        model = model_dict.get("model")

        if model is None:
            # V2 log : model dict corrompu (present dans self.models mais model=None)
            if _v2log:
                _v2log.emit("ML_MODEL_LOAD_FAIL",
                            path=f"{symbol}_dict", err="model_none_in_dict")
            return 0.0

        # Construire le vecteur de features + compter NaN/None pour data quality
        X = []
        n_nan = 0
        for f in features:
            val = features_row.get(f, 0.0)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                val = 0.0
                n_nan += 1
            X.append(float(val))

        # V2 log : features degradees au-dela du seuil (data quality signal)
        n_total = max(1, len(features))
        if _v2log and (n_nan / n_total) > _NAN_RATIO_THRESHOLD:
            _v2log.emit("DMP_FEATURE_NAN",
                        feature=f"predict_{symbol}", n=n_nan)

        X = np.array([X])

        # V2 : timer predict_proba pour detecter inference lente
        t_start = time.perf_counter()
        try:
            proba = model.predict_proba(X)
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            # Emit ML_INFERENCE_SLOW si depasse seuil (degradation modele ou VPS)
            if _v2log and elapsed_ms > _INFERENCE_SLOW_MS:
                _v2log.emit("ML_INFERENCE_SLOW",
                            ms=int(elapsed_ms), limit_ms=int(_INFERENCE_SLOW_MS))
            return float(proba[0, 1])  # P(signal=1)
        except Exception as e:
            # V2 log : exception silencieuse = BUG cache (bug latent detecte par review agent)
            # Pattern 11 safe : pas de features dans ctx
            if _v2log:
                _v2log.emit("ML_PREDICT_FAIL",
                            sym=symbol, err=f"{e.__class__.__name__}: {str(e)[:80]}", exc=e)
            return 0.0

    def _confidence(self, score: float) -> str:
        if score >= 0.70:
            return "HIGH"
        elif score >= 0.60:
            return "MEDIUM"
        else:
            return "LOW"
