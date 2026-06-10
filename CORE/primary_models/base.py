"""
Primary Model base class — MIA V2

Chaque strategie de trading (VWAP Reversion, ORB, VA Failure, Absorption, etc.)
herite de PrimaryModel. Un primary model genere un signal BUY/SELL/HOLD deterministe
a partir d'une barre de features. Le filtrage probabiliste est fait APRES par le
meta-labeler LightGBM.

Usage :
    class VwapReversionModel(PrimaryModel):
        name = "vwap_reversion"
        def required_features(self):
            return ["dist_vwap_d_atr", "dist_vwap_d_sd2u_atr", ...]

        def generate_signal(self, row, context=None):
            if row["dist_vwap_d_sd2u_atr"] > 0 and row["delta_slope"] < 0:
                return Signal(type=SignalType.SELL, sl_ticks=20, tp_ticks=36, ...)
            return Signal(type=SignalType.HOLD)

Auteur : MIA Trading System
Date   : 2026-04-14
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    """Signal atomique genere par un primary model."""
    type: SignalType = SignalType.HOLD
    sl_ticks: int = 0
    tp_ticks: int = 0
    reason: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def is_trade(self) -> bool:
        return self.type in (SignalType.BUY, SignalType.SELL)


class PrimaryModel(ABC):
    """
    Classe abstraite pour toute strategie primary MIA V2.

    Contrat :
      - `name` : identifiant unique (snake_case)
      - `required_features()` : liste des features necessaires (verif au runtime)
      - `generate_signal(row, context)` : genere un Signal deterministe

    Optionnel :
      - `validate_context(context)` : veto additionnel (regime, session, etc.)
      - `description()` : texte court pour les rapports
    """

    name: str = "base"

    @abstractmethod
    def required_features(self) -> list[str]:
        ...

    @abstractmethod
    def generate_signal(self, row: pd.Series, context: Optional[dict] = None) -> Signal:
        ...

    def description(self) -> str:
        return self.__doc__ or self.__class__.__name__

    def validate_context(self, context: Optional[dict]) -> bool:
        return True

    def check_features(self, df: pd.DataFrame) -> None:
        missing = [f for f in self.required_features() if f not in df.columns]
        if missing:
            raise ValueError(f"{self.name}: features manquantes {missing}")

    def run(self, df: pd.DataFrame, context: Optional[dict] = None) -> pd.DataFrame:
        """Applique generate_signal sur chaque ligne du dataset. Utilise pour backtest.

        Si validate_context(context) retourne False, tous les signaux sont forces a HOLD.
        Le champ meta du Signal est serialise dans la colonne 'meta' de sortie.
        """
        self.check_features(df)
        context_valid = self.validate_context(context)
        signals = []
        for _, row in df.iterrows():
            if not context_valid:
                sig = Signal(type=SignalType.HOLD, reason="context_invalid")
            else:
                sig = self.generate_signal(row, context)
            signals.append({
                "ts": row.get("ts"),
                "signal": sig.type.value,
                "sl_ticks": sig.sl_ticks,
                "tp_ticks": sig.tp_ticks,
                "reason": sig.reason,
                "meta": sig.meta,
            })
        return pd.DataFrame(signals)
