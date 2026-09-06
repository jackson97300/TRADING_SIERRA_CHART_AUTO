"""intermarket_divergence_gate.py — Gate de confirmation inter-marche ES->NQ.

Filtre de CONFIRMATION (pas un bot autonome) pour le Bot 1 continuation NQ.

# Edge (audit 16/06/2026)

Le Bot 1 continuation NQ seul = PF marginal (CONT_NQ_R1p5 PF 1.045, NOGO).
FILTRE par divergence ES/NQ forte -> PF 1.445 (validation backtest databento,
lift +0.32 sur 5/6 variantes R-multiples, multi-mois). Origine = observation
empirique Jackson ("j'ai pris un trade NQ apres qu'ES tienne son VWAP weekly").

Logique mecanique : NQ = maillon faible. Quand ES DIVERGE fort (reste loin de
son VWAP weekly du cote oppose au trade NQ), la continuation NQ a plus de jus
(NQ continue dans sa faiblesse/force relative). Quand ES est aligne, le move
est deja price/epuise -> PF plus faible.

# SCALE-INVARIANT (decision critique 16/06)

Le seuil ABSOLU 0.6% databento NE TRANSFERE PAS a sierra (regime/periode
different : databento mai %|>0.6|=13%, sierra juin =34% meme rééchantillonne).
Le `vwap_w` central est aligne (Spearman 0.9999, code verifie agent) mais la
DISTRIBUTION depend du regime. Solution : gate en PERCENTILE ROLLING causal
(top ~13% de la distribution ES recente) -> s'auto-adapte au regime, transfere
entre sources. Anti-incident Plan C (seuil absolu cross-source).

# Caveat (VALIDATION_MISS — agent)

Aucun jour databento+sierra commun dans live_enriched -> alignement meme-barre
non verifie directement. Validation FORWARD en paper sierra OBLIGATOIRE avant
de faire confiance. PF 1.445 = in-sample databento.

Auteur : MIA Trading V2 — v1.0 (2026-06-16).
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional

import numpy as np

SIDE_LONG = "LONG"
SIDE_SHORT = "SHORT"


class IntermarketDivergenceGate:
    """Gate percentile rolling : autorise une continuation NQ seulement si ES
    diverge fort (dans les `pct`% les plus extremes du COTE OPPOSE au trade, de
    sa distribution recente : bottom pct% pour un LONG, top pct% pour un SHORT).

    # Dual-mecanisme intermarket (decision Jackson 16/06) — NE PAS confondre avec
    # `CORE/bot_mean_revert/gates/intermarket.py` (gate PROXIMITE, logique INVERSE) :
    #   - PROXIMITE (mean-revert)   : ES PROCHE d'un niveau -> confirme un REVERSAL
    #     (ES tient support -> bounce). C'est le trade "ES tient son VWAP weekly".
    #   - DIVERGENCE (ce module)    : ES LOIN de son VWAP -> confirme une CONTINUATION
    #     (ES diverge -> NQ maillon faible continue). C'est l'effet valide backtest.
    # Les deux sont INTENTIONNELS, pour des philosophies opposees (reversal vs
    # continuation). Coherence mecanique assumee, pas une contradiction.

    # CONTRAT D'APPEL (R3a review — ordre fige, ne pas inverser) :
    # Par barre, l'orchestrateur appelle update() AVANT should_allow(). La barre
    # courante est donc incluse dans sa propre distribution de reference (effet
    # 1/window negligeable a window=600). Inverser l'ordre changerait le
    # comportement aux cas-limites.

    Usage (par l'orchestrateur paper) :
        gate = IntermarketDivergenceGate(window=600, pct=13.0)
        # a chaque barre ES live (skip si ES stale — cf integration) :
        gate.update(es_bar.get("dist_vwap_w_pct"))
        # quand le moteur continuation NQ emet une EntryDecision :
        allow, reason = gate.should_allow(decision.side, current_es_dist_vwap_w_pct)
        if not allow: veto le trade (emit log distinct selon reason failsafe/aligned)
    """

    def __init__(
        self,
        window: int = 600,
        pct: float = 13.0,
        min_samples: int = 100,
        fail_safe_block: bool = True,
    ):
        """
        Args:
            window : taille du buffer rolling (barres ES). 600 ~ validation.
            pct : percentile de divergence (13 = top 13%, principe databento).
            min_samples : minimum de barres ES avant d'evaluer le gate.
            fail_safe_block : si ES indispo/buffer insuffisant -> BLOQUER le trade
                (confirmation requise = "premium only"). True par defaut.
        """
        # raise (pas assert : module Trading/Risk, ne pas sauter sous python -O)
        if not 0 < pct < 50:
            raise ValueError(f"pct doit etre dans (0, 50), recu {pct}")
        if window < min_samples:
            raise ValueError(f"window ({window}) >= min_samples ({min_samples})")
        self.window = window
        self.pct = pct
        self.min_samples = min_samples
        self.fail_safe_block = fail_safe_block
        self._buf: Deque[float] = deque(maxlen=window)
        # Stats tracabilite
        self.n_updates = 0
        self.n_eval = 0
        self.n_allow = 0
        self.n_block_diverge = 0
        self.n_block_failsafe = 0

    def update(self, es_dist_vwap_w_pct: Optional[float]) -> None:
        """Pousse la valeur ES courante dans le buffer rolling. Appeler chaque
        barre ES (ignore None/NaN/Inf)."""
        v = self._safe(es_dist_vwap_w_pct)
        if v is not None:
            self._buf.append(v)
            self.n_updates += 1

    def should_allow(
        self, trade_side: str, current_es_dist_vwap_w_pct: Optional[float]
    ) -> tuple[bool, str]:
        """Le trade continuation NQ est-il confirme par une divergence ES forte ?

        Returns:
            (allow, reason). allow=False -> veto (ES n'est pas en divergence forte).
        """
        self.n_eval += 1
        cur = self._safe(current_es_dist_vwap_w_pct)
        # Fail-safe : pas de donnee ES fiable -> on ne confirme pas
        if cur is None or len(self._buf) < self.min_samples:
            block = self.fail_safe_block
            if block:
                self.n_block_failsafe += 1
                return False, f"failsafe_no_es_data:buf={len(self._buf)}"
            self.n_allow += 1
            return True, "failsafe_allow"

        arr = np.fromiter(self._buf, dtype=float)
        p_low, p_high = np.percentile(arr, [self.pct, 100.0 - self.pct])

        if trade_side == SIDE_LONG:
            # LONG NQ : ES diverge = ES tres BAS vs son VWAP weekly (bottom pct%)
            diverge = cur < p_low
        elif trade_side == SIDE_SHORT:
            # SHORT NQ : ES diverge = ES tres HAUT (top pct%)
            diverge = cur > p_high
        else:
            self.n_block_failsafe += 1
            return False, f"invalid_side:{trade_side}"

        if diverge:
            self.n_allow += 1
            return True, f"diverge_ok:es={cur:.3f}:p={p_low:.3f}/{p_high:.3f}"
        self.n_block_diverge += 1
        return False, f"es_aligned:es={cur:.3f}:p={p_low:.3f}/{p_high:.3f}"

    def current_percentiles(self) -> tuple[Optional[float], Optional[float]]:
        """(p_low, p_high) courants du buffer, ou (None, None) si insuffisant.
        Pour le logging des veto (R5)."""
        if len(self._buf) < self.min_samples:
            return None, None
        arr = np.fromiter(self._buf, dtype=float)
        p_low, p_high = np.percentile(arr, [self.pct, 100.0 - self.pct])
        return float(p_low), float(p_high)

    def stats(self) -> dict:
        return {
            "n_updates": self.n_updates,
            "buf_len": len(self._buf),
            "n_eval": self.n_eval,
            "n_allow": self.n_allow,
            "n_block_diverge": self.n_block_diverge,
            "n_block_failsafe": self.n_block_failsafe,
        }

    @staticmethod
    def _safe(v) -> Optional[float]:
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
