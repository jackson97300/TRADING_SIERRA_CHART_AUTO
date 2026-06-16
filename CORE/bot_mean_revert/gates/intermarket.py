"""IntermarketGate Bot MR - confirmation cross-instrument ES leader pour NQ.

Methodologie Jackson 16/06/2026 (intermarket / lead-lag confirmation):
  - NQ LONG = autorise si ES (leader) touche un niveau structurel et tient (bullish bias)
  - NQ SHORT = autorise si ES touche niveau structurel + bearish bias
  - Trigger principal Jackson : VWAP_W (weekly VWAP) ES
  - Trigger secondaires : VWAP_D, SD1d/SD2d, VAL/VAH, PDL/PDH, MQ_put/call/HVL

Le gate evalue :
  1. PROXIMITY : leader_sym proche d'au moins UN niveau (abs(dist_*_pct) <= proximity_thr)
  2. BIAS : bar leader cohnerent direction trade
     - LONG : bar_color_up == 1 OR delta_bar > 0
     - SHORT : bar_color_dn == 1 OR delta_bar < 0

Si trade_sym n'a pas de leader configure (ex: ES, MGC) : gate transparent (allow).

Hypothese empirique : ce filtre supprime signaux NQ isoles non-confirmes par ES
et pousse PF NQ vers >= 1.20 (vs 0.92 sweep v2 sans filter).

Reference :
  - Hasbrouck 1995 (price discovery, lead-lag info share)
  - Tse 1999 (S&P 500 leads Nasdaq)
  - Methodologie discretionnaire Jackson 16/06/2026
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from CORE.bot_mean_revert.config import BotMRConfig


@dataclass(frozen=True)
class IntermarketVerdict:
    """Verdict du filtre intermarket."""
    allowed: bool
    reason: str = ""
    leader_sym: str = ""
    level_matched: str = ""  # nom du niveau structurel touche (vwap_w, val, etc.)


# Liste des niveaux structurels candidats (par ordre de priorite Jackson 16/06)
# Cle = colonne dist_*_pct dans sierra_enriched
# Valeur = nom court pour reason log
LEADER_LEVELS = (
    ("dist_vwap_w_pct",        "vwap_w"),        # PRINCIPAL Jackson 16/06
    ("dist_vwap_d_pct",        "vwap_d"),
    ("dist_vwap_d_sd1d_pct",   "vwap_d_sd1d"),
    ("dist_vwap_d_sd1u_pct",   "vwap_d_sd1u"),
    ("dist_vwap_d_sd2d_pct",   "vwap_d_sd2d"),
    ("dist_vwap_d_sd2u_pct",   "vwap_d_sd2u"),
    ("dist_cur_val_pct",       "val"),
    ("dist_cur_vah_pct",       "vah"),
    ("dist_pdl_pct",           "pdl"),
    ("dist_pdh_pct",           "pdh"),
    ("dist_mq_put_pct",        "mq_put"),
    ("dist_mq_call_pct",       "mq_call"),
    ("dist_mq_hvl_pct",        "mq_hvl"),
)


def _f(x, default: Optional[float] = None) -> Optional[float]:
    """Cast float safe : retourne default si None/invalide (pas 0.0 par defaut !).

    Important : default=None permet de distinguer "niveau absent" de "niveau a 0%".
    """
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _i(x, default: int = 0) -> int:
    if x is None:
        return default
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


class IntermarketGate:
    """Gate de confirmation cross-instrument (leader -> follower)."""

    def __init__(self, cfg: BotMRConfig):
        self.cfg = cfg

    def leader_for(self, trade_sym: str) -> Optional[str]:
        """Retourne le symbole leader pour ce trade_sym, None si pas de leader."""
        if not self.cfg.INTERMARKET_GATE_ENABLED:
            return None
        return self.cfg.INTERMARKET_LEADER_BY_SYM.get(trade_sym.upper())

    def confirm(
        self,
        trade_sym: str,
        direction: str,
        leader_bar: Optional[dict],
    ) -> IntermarketVerdict:
        """Verifie confirmation cross-instrument.

        Args:
            trade_sym : symbole du trade ("NQ", "ES", "MGC")
            direction : "LONG" / "SHORT"
            leader_bar : derniere bar du leader (dict) ou None si pas trouvee

        Returns:
            IntermarketVerdict(allowed, reason, leader_sym, level_matched)
        """
        # Gate desactive : passe transparent
        if not self.cfg.INTERMARKET_GATE_ENABLED:
            return IntermarketVerdict(allowed=True, reason="gate_disabled")

        # Pas de leader pour ce sym (ex: ES, MGC) : transparent
        leader_sym = self.cfg.INTERMARKET_LEADER_BY_SYM.get(trade_sym.upper())
        if not leader_sym:
            return IntermarketVerdict(allowed=True, reason="no_leader_configured")

        # Self-leader (sanity) : transparent
        if leader_sym.upper() == trade_sym.upper():
            return IntermarketVerdict(allowed=True, reason="self_leader")

        # Leader bar manquante : REJECT (fail-closed - mieux vaut louper qu'erroner)
        if leader_bar is None:
            return IntermarketVerdict(
                allowed=False,
                reason="leader_bar_missing",
                leader_sym=leader_sym,
            )

        # 1. Proximity : leader touche au moins UN niveau structurel
        proximity_thr = float(self.cfg.INTERMARKET_LEVEL_PROXIMITY_PCT)
        nearest_level: Optional[str] = None
        nearest_dist: float = float("inf")
        for col, name in LEADER_LEVELS:
            d = _f(leader_bar.get(col), default=None)
            if d is None:
                continue
            d_abs = abs(d)
            if d_abs <= proximity_thr and d_abs < nearest_dist:
                nearest_level = name
                nearest_dist = d_abs

        if nearest_level is None:
            return IntermarketVerdict(
                allowed=False,
                reason="leader_no_level_proximity",
                leader_sym=leader_sym,
            )

        # 2. Bias coherent direction trade
        delta_bar = _f(leader_bar.get("delta_bar"), default=0.0) or 0.0
        bar_color_up = _i(leader_bar.get("bar_color_up"), default=0)
        bar_color_dn = _i(leader_bar.get("bar_color_dn"), default=0)

        if direction == "LONG":
            bullish = (bar_color_up == 1) or (delta_bar > 0)
            if bullish:
                return IntermarketVerdict(
                    allowed=True,
                    reason=f"{leader_sym}@{nearest_level}+bullish",
                    leader_sym=leader_sym,
                    level_matched=nearest_level,
                )
            return IntermarketVerdict(
                allowed=False,
                reason=f"leader@{nearest_level}_no_bullish_bias",
                leader_sym=leader_sym,
                level_matched=nearest_level,
            )

        if direction == "SHORT":
            bearish = (bar_color_dn == 1) or (delta_bar < 0)
            if bearish:
                return IntermarketVerdict(
                    allowed=True,
                    reason=f"{leader_sym}@{nearest_level}+bearish",
                    leader_sym=leader_sym,
                    level_matched=nearest_level,
                )
            return IntermarketVerdict(
                allowed=False,
                reason=f"leader@{nearest_level}_no_bearish_bias",
                leader_sym=leader_sym,
                level_matched=nearest_level,
            )

        # direction inconnue : fail-closed
        return IntermarketVerdict(
            allowed=False,
            reason=f"unknown_direction:{direction}",
            leader_sym=leader_sym,
        )
