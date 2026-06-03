"""Trailing SL helper - classe reusable cross-bots avec 7 fixes anti-orphan.

03/06/2026 P4.2 Phase 2 — Refactor du code `_bot3_modify_sl_via_dtc` +
`_bot3_watchdog_verify_sl` de `databento_paper_trader_v2.py` en classe
standalone pour reutilisation par Bot 1 MP, Bot 1 v3, Bot 3 v4.

REDESIGN P4.2 review : code-reviewer NOGO sur version fonctions (14 kwargs +
emit_fn global + force_close_fn untyped + Timer non-cancellable + pas de
shadow mode). Cette version corrige les 5 reserves bloquantes :

  R-A : Classe `TrailingSLModifier` pre-bind 8 deps stables au constructeur.
        Call-site = 6 args metier (sym/contract/pos/new_sl_price/n_contracts/palier).
  R-B : `emit_fn` pre-bind au constructeur (pas a chaque call).
  R-C : `ForceCloseFn` Protocol typage strict (force les 3 bots a aligner).
  R-D : `_watchdog_timers` registry + `cancel_watchdogs(sym)` appele par
        tout chemin de close (TP fill, SL fill, kill switch, EOD).
  R-E : Shadow mode A/B testing OBLIGATOIRE avant migration Bot 1 MP
        (5+ trades helper-compute vs ancien-code-execute, diff logge).

Les 7 fixes anti-orphan preserves (cf `.claude/rules/orphan-prevention.md`
+ reviews code-reviewer 11/05 + 19/05 sur `_bot3_modify_sl_via_dtc`) :
  1. Cancel old SL via Type 203 require_sid=True (abort si False)
  2. Verify position broker AVANT send new SL (anti-trade-inverse)
  3. Bidirectional OCO cleanup (_oco_pairs.pop tp_cid + sl_cid)
  4. STOP order (Type 208 OrderType=3 + StopPrice, PAS Price1)
  5. Idempotence : caller marque executed AVANT call modify()
  6. Modify hors lock principal (pos_lock taken in mini-blocks only)
  7. Verify Type 300 post-send + 4 cas (a/b/c/d) + watchdog T+30s

Ne PAS confondre avec `mia_sltp.py:SLTPEngine` qui est un autre layer
(decision SL/TP initial, pas modification dynamique post-fill).

USAGE EXEMPLE :

```python
# Bot 1 MP (Sim1) au boot :
self._trailing_modifier_mp = TrailingSLModifier(
    dtc=self.dtc,
    pos_lock=self._bot3_pos_lock,
    cid_index=self._bot3_cid_index,
    positions_dict=self._bot3_positions,
    trade_account=TRADE_ACCOUNT_BOT3,
    log_prefix="BOT3_LADDER",
    emit_fn=_emit,
    force_close_fn=self._bot3_force_close_market,
)

# Bot 1 v3 (Sim1) au boot :
self._trailing_modifier_v3 = TrailingSLModifier(
    dtc=self.dtc,
    pos_lock=self._pos_lock,
    cid_index=self._cid_index,
    positions_dict=self._position,
    trade_account="Sim1",
    log_prefix="BOT3_V3_TRAILING",
    emit_fn=_emit,
    force_close_fn=self._force_close_position,
)

# Bot 3 v4 (Sim3) : idem avec log_prefix="BOT3_V4_TRAILING" + "Sim3"

# Call-site (6 args metier) :
ok = self._trailing_modifier_mp.modify(
    sym="NQ", contract="NQM26-CME", pos=pos_dict,
    new_sl_price=new_price, n_contracts=3,
    palier_idx=1, lock_usd=60.0,
)

# Cleanup tout chemin de close (TP fill, SL fill, kill switch, EOD) :
self._trailing_modifier_mp.cancel_watchdogs("NQ")
```
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol


# ════════════════════════════════════════════════════════════════════════
# Protocol : ForceCloseFn (R-C : force les 3 bots a aligner signature)
# ════════════════════════════════════════════════════════════════════════

class ForceCloseFn(Protocol):
    """Signature obligatoire pour force_close_fn du TrailingSLModifier.

    Les 3 bots DOIVENT exposer leur close avec cette signature kwargs-only :
      - Bot 1 MP : `_bot3_force_close_market(*, sym, pos, reason) -> None`
      - Bot 1 v3 : `_force_close_position(*, sym, pos, reason) -> None`
      - Bot 3 v4 : `_force_close_position(*, sym, pos, reason) -> None`

    Si un bot a une autre signature, ETAPE B/C doit ALIGNER (ne pas adapter
    le Protocol = casse contract typage).

    Spec :
      Type 209 SUBMIT_FLATTEN ou Type 208 MARKET CLOSE selon strategie bot.
      Doit nettoyer pos["sl_cid"] = None apres flatten broker confirme.
      Doit emit code log specifique au bot (BOT3_FORCE_CLOSE_* / BOT3_V3_FORCE_CLOSE_*).
    """

    def __call__(self, *, sym: str, pos: dict, reason: str) -> None:
        ...


# ════════════════════════════════════════════════════════════════════════
# VALID PREFIXES (R-A correction : validation au constructeur)
# ════════════════════════════════════════════════════════════════════════

_VALID_LOG_PREFIXES = frozenset({
    "BOT3_LADDER",        # Bot 1 MP (Sim1) ladder profit-locking
    "BOT3_V3_TRAILING",   # Bot 1 v3 NQ Wyckoff (Sim1) trailing actif
    "BOT3_V4_TRAILING",   # Bot 3 v4 NQ data-driven (Sim3) trailing actif
})


# ════════════════════════════════════════════════════════════════════════
# Classe principale : TrailingSLModifier (R-A redesign)
# ════════════════════════════════════════════════════════════════════════

class TrailingSLModifier:
    """Modifier SL via cancel + replace DTC avec 7 fixes anti-orphan.

    Pre-bind 8 dependances stables au constructeur. Le call-site `modify()`
    n'a que 6 args metier (sym/contract/pos/new_sl_price/n_contracts/palier).

    Thread-safety : la classe est thread-safe via pos_lock (injection caller)
    + lock interne `_timers_lock` pour le registry watchdog. Une instance
    est typiquement creee 1 fois au boot du bot.

    Watchdog management (R-D) :
      `modify()` cree un Timer si verify Type 300 retourne open_orders=None.
      Le Timer est stocke dans `_watchdog_timers[sym]`. Tout chemin de close
      (TP fill, SL fill, kill_switch, EOD) DOIT appeler `cancel_watchdogs(sym)`
      pour eviter race POS_GONE / SL_ORPHAN faux positifs.

    Shadow mode (R-E) :
      Avant migration Bot 1 MP de l'ancien code vers cette classe, executer
      en shadow mode : `enable_shadow_mode(legacy_fn)` -> chaque modify() appelle
      LEGACY + helper en parallele, diff logge. Apres 5+ trades stables sans
      divergence, flip = retire shadow + delete legacy.
    """

    def __init__(
        self,
        *,
        dtc: Any,
        pos_lock: threading.Lock,
        cid_index: dict,
        positions_dict: dict,
        trade_account: str,
        log_prefix: str,
        emit_fn: Callable[..., None],
        force_close_fn: ForceCloseFn,
    ) -> None:
        """Pre-bind 8 deps stables. Validation log_prefix au constructeur.

        Args:
            dtc : DTC connector singleton (partage cross-bots)
            pos_lock : threading.Lock pour MAJ pos dict mini-blocks
            cid_index : dict CID -> entry pour register new_sl_cid
            positions_dict : dict sym -> pos pour watchdog re-lookup
            trade_account : "Sim1" (Bot 1 v3+MP) / "Sim3" (Bot 3 v4)
            log_prefix : "BOT3_LADDER" / "BOT3_V3_TRAILING" / "BOT3_V4_TRAILING"
            emit_fn : callable(code, **ctx) pour logs (cf log_catalog.py)
            force_close_fn : ForceCloseFn Protocol pour MARKET CLOSE orphan
        """
        # R-A validation log_prefix au constructeur (anti-typo silencieux)
        assert log_prefix in _VALID_LOG_PREFIXES, (
            f"log_prefix={log_prefix!r} invalide. Doit etre dans {_VALID_LOG_PREFIXES}"
        )

        self.dtc = dtc
        self.pos_lock = pos_lock
        self.cid_index = cid_index
        self.positions_dict = positions_dict
        self.trade_account = trade_account
        self.log_prefix = log_prefix
        self.emit_fn = emit_fn
        self.force_close_fn = force_close_fn

        # R-D : Timer registry pour cancel watchdogs sur close
        self._watchdog_timers: dict[str, threading.Timer] = {}
        self._timers_lock = threading.Lock()

        # R-E : shadow mode A/B testing (optional, default OFF)
        self._shadow_mode_enabled: bool = False
        self._shadow_legacy_fn: Optional[Callable] = None

    # ────────────────────────────────────────────────────────────────────
    # API publique : modify (call-site 6 args metier)
    # ────────────────────────────────────────────────────────────────────

    def modify(
        self,
        *,
        sym: str,
        contract: str,
        pos: dict,
        new_sl_price: float,
        n_contracts: int,
        palier_idx: int = 0,
        lock_usd: float = 0.0,
    ) -> bool:
        """Modify SL via cancel + replace DTC pattern, 7 fixes anti-orphan.

        Args:
            sym : "NQ" / "ES" / "MGC"
            contract : symbole broker (e.g. "NQM26-CME")
            pos : position dict avec sl_cid, tp_cid, side, signal_id, ts_open, level
            new_sl_price : prix nouveau SL
            n_contracts : quantite ordre
            palier_idx : index palier ladder (0 pour trailing non-ladder)
            lock_usd : USD lock par palier (0 pour non-ladder)

        Returns:
            True si modify reussi (new SL place + pos update + OCO re-register)
            False si echec a n'importe quelle etape

        Sequence (7 fixes) :
            STEP A : Cancel old SL via Type 203 require_sid=True
            STEP B : Wait 0.3s + Verify position broker (anti-trade-inverse)
            STEP C : Pre-register OCO + TA + Send new STOP Type 208
            STEP C.5 : Verify Type 300 post-send (4 cas a/b/c/d) + watchdog si timeout
            STEP D : Update pos sl_cid + sl_price + audit trail

        Codes log emis (prefixes par self.log_prefix) :
            {prefix}_MODIFY_DTC_DOWN, _MODIFY_NO_OLD_SL_CID,
            _MODIFY_CONTRACT_LOOKUP_FAIL, _CANCEL_EXCEPTION, _CANCEL_FAILED,
            _POS_VERIFY_EXCEPTION, _POS_VERIFY_TIMEOUT, _POS_CLOSED_DURING_MODIFY,
            _SEND_NEW_SL_EXCEPTION, _VERIFY_TYPE300_EXCEPTION,
            _NEW_SL_VERIFY_TIMEOUT, _NEW_SL_NOT_WORKING,
            _WATCHDOG_SCHEDULE_FAIL, _SL_MODIFIED
            + SL_STOP_PATCHED_V1 (partage tous bots)
        """
        # R-E shadow mode : si active, execute legacy AND helper, diff logge
        if self._shadow_mode_enabled and self._shadow_legacy_fn is not None:
            # TODO Phase 2 Etape A2 : implementer shadow A/B comparison
            pass

        # TODO Phase 2 Etape A2 : copy + adapt code de _bot3_modify_sl_via_dtc
        raise NotImplementedError("Phase 2 Etape A2 : implementation a faire")

    # ────────────────────────────────────────────────────────────────────
    # API publique : cancel_watchdogs (R-D : tout chemin de close DOIT appeler)
    # ────────────────────────────────────────────────────────────────────

    def cancel_watchdogs(self, sym: str) -> int:
        """Cancel tout Timer watchdog pending pour ce sym.

        DOIT etre appele par TOUT chemin de close pour eviter race :
          - TP fill (handle_dtc_fill TP path)
          - SL fill (handle_dtc_fill SL path)
          - Kill switch flatten
          - EOD flatten
          - Timeout force_close_market
          - User FLATTEN_MANUAL

        Args:
            sym : symbole dont les watchdogs sont cancel

        Returns:
            Nombre de Timers cancel (0 si aucun pending)
        """
        with self._timers_lock:
            timer = self._watchdog_timers.pop(sym, None)
        if timer is None:
            return 0
        try:
            timer.cancel()
            return 1
        except Exception as e:
            self.emit_fn(
                f"{self.log_prefix}_WATCHDOG_CANCEL_EXCEPTION",
                sym=sym, exc_type=type(e).__name__, exc_msg=str(e)[:200],
            )
            return 0

    # ────────────────────────────────────────────────────────────────────
    # API publique : enable_shadow_mode (R-E : A/B testing avant flip)
    # ────────────────────────────────────────────────────────────────────

    def enable_shadow_mode(self, legacy_fn: Callable) -> None:
        """Active shadow mode : chaque modify() compare helper vs legacy_fn.

        Legacy_fn execute (action reelle DTC). Helper compute en parallele
        sans toucher DTC. Diff entre les 2 logge -> code {prefix}_SHADOW_DIFF.

        Apres 5+ trades sans divergence, appeler `disable_shadow_mode()` puis
        flip = remplacer legacy_fn calls par self.modify() calls dans le bot.

        Args:
            legacy_fn : fonction legacy (ex: `_bot3_modify_sl_via_dtc`) qui
                        execute l'action reelle pendant phase shadow
        """
        self._shadow_mode_enabled = True
        self._shadow_legacy_fn = legacy_fn
        self.emit_fn(
            f"{self.log_prefix}_SHADOW_MODE_ENABLED",
            msg="A/B testing : helper compute en parallele, legacy execute. "
                "Diff logge via {prefix}_SHADOW_DIFF code.",
        )

    def disable_shadow_mode(self) -> None:
        """Desactive shadow mode (apres 5+ trades validation, pre-flip)."""
        self._shadow_mode_enabled = False
        self._shadow_legacy_fn = None
        self.emit_fn(
            f"{self.log_prefix}_SHADOW_MODE_DISABLED",
            msg="Shadow phase terminee. Flip vers helper exclusif autorise.",
        )

    # ────────────────────────────────────────────────────────────────────
    # Methode privee : _watchdog (R-D : non re-implementer, juste reference)
    # ────────────────────────────────────────────────────────────────────

    def _watchdog_verify_sl(
        self,
        sym: str,
        contract: str,
        new_sl_cid: str,
        expected_sl_price: float,
        palier_idx: int,
    ) -> None:
        """Watchdog T+30s post-VERIFY_TIMEOUT - force re-verify + MARKET CLOSE si orphan.

        Appele via threading.Timer(30, self._watchdog_verify_sl, args=(...)).
        Le Timer est stocke dans self._watchdog_timers[sym] (R-D).

        Codes log emis (prefixes par self.log_prefix) :
            {prefix}_WATCHDOG_DTC_DOWN, _WATCHDOG_POS_QUERY_FAIL,
            _WATCHDOG_POS_FLAT, _WATCHDOG_TYPE300_FAIL,
            _WATCHDOG_SL_WORKING_CONFIRMED, _WATCHDOG_SL_ORPHAN_DETECTED,
            _WATCHDOG_POS_GONE, _WATCHDOG_FORCE_CLOSE_EXCEPTION

        Sequence :
            1. Self-cleanup : retirer ce Timer de self._watchdog_timers
            2. request_position_blocking : si qty=0 -> POS_FLAT OK
            3. request_open_orders_blocking : si new_sl_cid status 2/4 -> SL Working OK
            4. Sinon : ORPHAN -> self.force_close_fn(sym, pos, "WATCHDOG_ORPHAN")
        """
        # R-D : self-cleanup du registry
        with self._timers_lock:
            self._watchdog_timers.pop(sym, None)

        # TODO Phase 2 Etape A2 : copy + adapt code de _bot3_watchdog_verify_sl
        raise NotImplementedError("Phase 2 Etape A2 : implementation a faire")


# ════════════════════════════════════════════════════════════════════════
# Helper : register_trailing_codes (Q10 : factorisation log_catalog.py)
# ════════════════════════════════════════════════════════════════════════

def get_trailing_codes_template() -> dict:
    """Retourne dict {code_suffix: (level, category, template)} pour factoriser
    l'ajout des codes log dans CORE/log_catalog.py.

    Usage dans log_catalog.py Phase 2 Etape A4 :
    ```python
    from CORE.trailing_sl_helper import get_trailing_codes_template
    _TRAILING_CODES_TEMPLATE = get_trailing_codes_template()

    for prefix in ("BOT3_LADDER", "BOT3_V3_TRAILING", "BOT3_V4_TRAILING"):
        for suffix, (level, cat, template) in _TRAILING_CODES_TEMPLATE.items():
            LOG_CATALOG[f"{prefix}_{suffix}"] = (level, cat, template)
    ```

    Evite 40 lignes copier-coller + drift template entre 3 bots.
    """
    # Phase 2 Etape A4 : implementer mapping complet ~14 codes
    return {
        # _MODIFY_DTC_DOWN : (LogLevel.ALERTE, "execution", "..."),
        # _CANCEL_FAILED : (LogLevel.MAJEUR, "execution", "..."),
        # _NEW_SL_NOT_WORKING : (LogLevel.CRITIQUE, "execution", "..."),
        # _WATCHDOG_SL_ORPHAN_DETECTED : (LogLevel.CRITIQUE, "execution", "..."),
        # _SL_MODIFIED : (LogLevel.MAJEUR, "execution", "..."),
        # ... etc
    }
