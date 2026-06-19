"""Cluster orchestrateur Bot 1 v2.

Orchestre la chaine de decision :
  1. dashboard_mirror.compute_verdict (4 vetos + 7 etoiles)
  2. risk.sl_tp.compute_sl_tp (HARD CAP + buffer anti-hunter)
  3. Gere cooldown + dedup signal_id (anti-spam)
  4. Retourne ClusterDecision avec tout le contexte pour l'ordre

Pattern : 1 instance ClusterEngine par symbole (state isole).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Optional

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.dashboard_mirror import (
    MirrorVerdict, VetoFired, QualityMiss, compute_verdict,
)
from CORE.bot1_v2.risk.sl_tp import SLTPResult, compute_sl_tp


@dataclass(frozen=True)
class ClusterDecision:
    """Decision finale d'un cycle d'evaluation cluster.

    Lecture par main.py :
      - tradable : True ssi tous filtres OK + SL/TP accepted
      - signal_id : hash bar pour dedup
      - direction, entry_price, sl_price, tp_price : ordre a envoyer
      - n_micros : taille position
      - skip_reason : raison rejet (verdict ou SL/TP)
      - mirror : MirrorVerdict complet (snapshot ML)
      - sltp : SLTPResult complet
    """
    tradable: bool
    skip_reason: str = ""
    signal_id: str = ""
    direction: Optional[str] = None
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    sl_ticks: int = 0
    tp_ticks: int = 0
    rr_ratio: float = 0.0
    sl_wall: str = ""
    sl_tier: int = 0
    n_micros: int = 0
    bar_ts: Optional[int] = None
    symbol: str = ""
    mirror: Optional[MirrorVerdict] = None
    sltp: Optional[SLTPResult] = None
    stars_count: int = 0
    stars_total: int = 3
    vetos_active: tuple = field(default_factory=tuple)


def _compute_signal_id(bar: dict, direction: str, symbol: str) -> str:
    """Hash bar ts + direction + symbol = signal_id stable pour dedup."""
    ts = bar.get("ts") or bar.get("bar_ts") or 0
    key = f"{symbol}|{int(ts)}|{direction}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


class ClusterEngine:
    """Engine cluster par symbole.

    Maintient :
      - cooldown_until_ts : timestamp ms minimum avant prochain signal
      - traded_signal_ids : set pour dedup cross-restart (loaded from state)
      - last_decision : derniere ClusterDecision (debugging)
    """

    def __init__(
        self,
        symbol: str,
        cfg: Optional[Bot1V2Config] = None,
        traded_signal_ids: Optional[set] = None,
    ):
        self.symbol = symbol.upper()
        self.cfg = cfg or Bot1V2Config.from_env()
        self.cooldown_until_ts: float = 0.0  # epoch seconds
        self.traded_signal_ids: set = traded_signal_ids or set()
        self.last_decision: Optional[ClusterDecision] = None

    def evaluate(self, bar: dict) -> ClusterDecision:
        """Evalue une bar et retourne la decision finale.

        Args:
            bar : dict sierra_enriched (613 features)

        Returns:
            ClusterDecision avec tradable=True ssi tous filtres OK.
        """
        # 1. Cooldown post-close (anti-revenge)
        now = time.time()
        if now < self.cooldown_until_ts:
            remaining = int(self.cooldown_until_ts - now)
            return self._make_decision(
                bar, tradable=False, skip_reason=f"COOLDOWN_ACTIVE:{remaining}s",
            )

        # 2. Compute verdict miroir dashboard + vetos + etoiles
        mirror = compute_verdict(bar, cfg=self.cfg, symbol=self.symbol)

        if not mirror.ready_to_arm:
            return self._make_decision(
                bar, tradable=False,
                skip_reason=mirror.skip_reason or "MIRROR_NOT_READY",
                mirror=mirror,
            )

        # 3. Dedup signal_id (anti-spam meme signal)
        direction = mirror.direction
        if direction is None:
            return self._make_decision(
                bar, tradable=False, skip_reason="NO_DIRECTION", mirror=mirror,
            )

        signal_id = _compute_signal_id(bar, direction, self.symbol)
        if signal_id in self.traded_signal_ids:
            return self._make_decision(
                bar, tradable=False,
                skip_reason=f"SIGNAL_ALREADY_TRADED:{signal_id}",
                mirror=mirror, signal_id=signal_id, direction=direction,
            )

        # 4. SL/TP calculation avec HARD CAP + buffer anti-hunter
        try:
            entry_price = float(bar.get("close") or bar.get("price") or 0)
        except (TypeError, ValueError):
            entry_price = 0.0
        if entry_price <= 0:
            return self._make_decision(
                bar, tradable=False, skip_reason="ENTRY_PRICE_INVALID",
                mirror=mirror, signal_id=signal_id, direction=direction,
            )

        sltp = compute_sl_tp(
            bar=bar, direction=direction, entry_price=entry_price,
            symbol=self.symbol, cfg=self.cfg,
        )
        if not sltp.accepted:
            return self._make_decision(
                bar, tradable=False,
                skip_reason=f"SLTP_REJECT:{sltp.reject_reason}",
                mirror=mirror, sltp=sltp, signal_id=signal_id, direction=direction,
                entry_price=entry_price,
            )

        # 5. Trade tradable ! Decision finale
        return self._make_decision(
            bar, tradable=True,
            skip_reason="",
            mirror=mirror, sltp=sltp, signal_id=signal_id, direction=direction,
            entry_price=entry_price,
            n_micros=self.cfg.N_MICROS_DEFAULT,
        )

    def register_trade(self, signal_id: str) -> None:
        """Enregistre un signal trade pris (dedup seulement).

        Appele par main.py apres send_order success.
        Le cooldown est applique a la FERMETURE du trade (register_close).
        """
        if signal_id:
            self.traded_signal_ids.add(signal_id)

    def register_close(self, exit_ts: float, was_loss: bool = False) -> None:
        """Appele a la fermeture d'un trade.

        Si was_loss=True, applique cooldown plus strict (anti-tilt Mark Douglas).
        """
        cooldown_min = (
            self.cfg.COOLDOWN_POST_LOSS_MIN if was_loss
            else self.cfg.COOLDOWN_POST_CLOSE_MIN
        )
        self.cooldown_until_ts = exit_ts + cooldown_min * 60

    def _make_decision(
        self,
        bar: dict,
        tradable: bool,
        skip_reason: str = "",
        mirror: Optional[MirrorVerdict] = None,
        sltp: Optional[SLTPResult] = None,
        signal_id: str = "",
        direction: Optional[str] = None,
        entry_price: float = 0.0,
        n_micros: int = 0,
    ) -> ClusterDecision:
        """Construit ClusterDecision en propageant le contexte."""
        # F-1 (18/06) : propager la direction connue du mirror si non passee
        # explicitement (cas QUALITY_INSUFFICIENT / VETO / verdict PRUDENT rejete).
        # Sans ca, les logs catalog affichaient direction="?" sur ~88% des rejets.
        # ATTENDRE garde None (mirror.direction None) = correct.
        if direction is None and mirror is not None:
            direction = mirror.direction
        bar_ts = bar.get("ts")
        decision = ClusterDecision(
            tradable=tradable,
            skip_reason=skip_reason,
            signal_id=signal_id,
            direction=direction,
            entry_price=entry_price,
            sl_price=sltp.sl_price if sltp else 0.0,
            tp_price=sltp.tp_price if sltp else 0.0,
            sl_ticks=sltp.sl_ticks if sltp else 0,
            tp_ticks=sltp.tp_ticks if sltp else 0,
            rr_ratio=sltp.rr_ratio if sltp else 0.0,
            sl_wall=sltp.sl_wall if sltp else "",
            sl_tier=sltp.sl_tier if sltp else 0,
            n_micros=n_micros,
            bar_ts=int(bar_ts) if bar_ts else None,
            symbol=self.symbol,
            mirror=mirror,
            sltp=sltp,
            stars_count=mirror.stars_count if mirror else 0,
            stars_total=mirror.stars_total if mirror else 3,
            vetos_active=mirror.vetos if mirror else (),
        )
        self.last_decision = decision
        return decision
