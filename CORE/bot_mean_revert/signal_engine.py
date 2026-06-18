"""Signal engine Bot Mean Revert VWAP.

Logique mean reversion (sweep v2 valide) :
  Entry LONG :  dist_vwap_d_sdNd_pct <= -threshold  + filtres regime ES/NQ
  Entry SHORT : dist_vwap_d_sdNu_pct >=  threshold  + filtres regime ES/NQ

SL/TP : SL fixe ticks (20 ES / 35 NQ), TP = SL * RR (1.5).

Reference : detect_mean_revert_signal de CORE/research/sweep_bot_mean_revert_v2.py
Pattern : encapsule dans SignalEngine pour reuse propre dans le bot prod.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from CORE.bot_mean_revert.config import BotMRConfig

try:
    from CORE.constants import get_tick_size
except ImportError:  # pragma: no cover - fallback flat sys.path
    from constants import get_tick_size  # type: ignore


# Pre-open US bruit (sweep ES : skip_preopen_us=True ameliore PF)
PREOPEN_US_START_MIN = 11 * 60 + 30  # 11:30 UTC
PREOPEN_US_END_MIN = 13 * 60 + 30    # 13:30 UTC


# Liste exhaustive des champs distance vers niveaux structurels que le bar
# enrichi par Sierra Chart expose. Verifie 18/06 sur :
#   DATA/live_enriched/sierra/ES/20260615_ES_sierra_enriched.jsonl
#   DATA/live_enriched/sierra/NQ/20260615_NQ_sierra_enriched.jsonl
# (symetrie ES/NQ OK, fields identiques).
#
# Convention units :
#   - "pct"  : distance en pourcentage du prix (positif = niveau au-dessus,
#             negatif = niveau en-dessous). Ex: dist_mq_hvl_0dte_pct = -1.63
#             signifie HVL 0DTE est 1.63% en dessous du close courant.
#   - "ticks": distance en ticks (positif = niveau au-dessus, negatif = en-dessous).
#             Ex: dist_1d_max_ticks = 27.92 signifie max du jour 27.92 ticks au-dessus.
#
# Pour le filtre confluence : on compte un niveau "proche" si
#   - unit=pct   et abs(dist_pct) * close / 100 / tick <= radius_ticks
#   - unit=ticks et abs(dist_ticks) <= radius_ticks
#
# Sources :
#   - dist_mq_*_pct : MenthorQ HVL / Call / Put (jour et 0DTE)
#   - dist_gex_nearest_*_pct : GEX strikes nearest up/down
#   - dist_1d_max/min_ticks : range du jour
#   - dist_vwap_d/w_sd1d_pct : VWAP daily / weekly SD1 bands (bonus structurel)
MQ_LEVEL_DIST_FIELDS: tuple = (
    ("dist_mq_hvl_pct", "pct"),
    ("dist_mq_hvl_0dte_pct", "pct"),
    ("dist_mq_call_pct", "pct"),
    ("dist_mq_call_0dte_pct", "pct"),
    ("dist_mq_put_pct", "pct"),
    ("dist_mq_put_0dte_pct", "pct"),
    ("dist_gex_nearest_up_pct", "pct"),
    ("dist_gex_nearest_dn_pct", "pct"),
    ("dist_1d_max_ticks", "ticks"),
    ("dist_1d_min_ticks", "ticks"),
    ("dist_vwap_d_sd1d_pct", "pct"),
    ("dist_vwap_w_sd1d_pct", "pct"),
)


def _f(x, default=0.0) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _b(x) -> bool:
    if x is True or x == 1 or x == "true":
        return True
    return False


@dataclass(frozen=True)
class SignalResult:
    """Resultat evaluation signal mean revert."""
    tradable: bool
    direction: Optional[str] = None  # "LONG" / "SHORT" / None
    skip_reason: str = ""
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    sl_ticks: int = 0
    tp_ticks: int = 0
    rr_ratio: float = 0.0
    sd_level: str = ""
    signal_id: str = ""
    bar_ts: Optional[int] = None
    # Contexte enrichi pour audit JSONL
    vwap_slope_30: float = 0.0
    vix_level: float = 0.0
    rvol_zscore: float = 0.0
    session_id: str = ""
    ctx_trend_day_score: float = 0.0


class SignalEngine:
    """Moteur de detection mean revert + sizing SL/TP.

    Cooldown : 2 modes selon presence du store :
      - store fourni : TIME-BASED (last_trade_ts persiste cross-restart).
        Fix bug 18/06 ou un restart bypassait le cooldown counter-based.
        Convention : 1 bar = 60 sec, cooldown_sec = COOLDOWN_BARS * 60.
      - store=None : LEGACY counter-based (incrementation par bar via
        _bump_bar_counter). Preserve pour backward-compat tests.
    """

    def __init__(
        self,
        symbol: str,
        cfg: BotMRConfig,
        traded_signal_ids: Optional[set] = None,
        store=None,
        on_corrupted_state: Optional[Callable[[str, str], None]] = None,
        regime_classifier=None,
        regime_scorer=None,
    ):
        self.symbol = symbol.upper()
        self.cfg = cfg
        self.store = store
        # R1 code-reviewer 18/06 : callback emit pour tracer ISO corrompu
        # (le SignalEngine reste decouple du bot_log via injection).
        self._on_corrupted_state = on_corrupted_state
        # Phase 3 18/06 : RegimeClassifier optionnel (vote majoritaire 3 signaux).
        # Si None -> bypass check (backward compat tests existants). En prod
        # main.py injecte une instance partagee.
        self.regime_classifier = regime_classifier
        # Phase 3 18/06 (alternative) : RegimeScorer optionnel (score continu pondere).
        # Sortie complementaire/alternative au vote majoritaire. Capture la
        # non-monotonie observee dans calibration empirique deciles slope_30.
        # Bloque uniquement TREND_*_STRONG + PANIC (TREND_*_WEAK et RANGE OK).
        self.regime_scorer = regime_scorer
        self._cooldown_until_ts = 0.0
        # LEGACY counter (fallback si pas de store)
        self._bars_since_last_trade = cfg.COOLDOWN_BARS  # ready immediat au boot
        self._traded_signal_ids: set = set(traded_signal_ids or [])
        # R3 code-reviewer 18/06 : warning visible si instancie sans store en prod.
        # Mode legacy counter-based = vulnerable au bug restart=bypass cooldown
        # detecte 18/06 (trade #3 -22t apres restart bot). Garde le mode actif
        # pour les tests qui s'en servent (backward compat), mais signale clair.
        if store is None:
            logging.getLogger("bot_mr").warning(
                "SignalEngine[%s] instancie sans store : mode counter-based legacy. "
                "Vulnerable au bug restart=bypass cooldown (18/06). "
                "Injecte un PositionStore en prod.",
                self.symbol,
            )

    def register_trade(
        self,
        signal_id: str,
        direction: Optional[str] = None,
        entry_price: Optional[float] = None,
    ) -> None:
        """A appeler apres ordre envoye : reset cooldown + lock signal_id +
        memorise prix d'entry pour anti-clustering.

        Mode time-based (store fourni) : stocke last_trade_ts dans store
        (sauvegarde a charge du caller via store.save()).
        Mode legacy counter (store=None) : reset compteur a 0.

        Args:
            signal_id : ID unique du signal (lock dedup).
            direction : "LONG" / "SHORT" (utilise pour anti-clustering).
                Si None, NO_REENTRY ne sera pas update (backward compat).
            entry_price : prix d'execution (fill_price ou planifie). Si None,
                NO_REENTRY ne sera pas update.
        """
        if signal_id:
            self._traded_signal_ids.add(signal_id)
        if self.store is not None:
            self.store.set_last_trade_ts(
                self.symbol,
                datetime.now(timezone.utc).isoformat(),
            )
            # Anti-clustering : enregistre le dernier prix d'entry pour
            # (symbol, direction). Persiste cross-restart via store.save() caller.
            if direction and entry_price is not None and entry_price > 0:
                self.store.set_last_entry_price(
                    self.symbol, direction, float(entry_price),
                )
        # Reset compteur dans tous les cas (no-op si store mode mais inoffensif).
        self._bars_since_last_trade = 0

    def _bump_bar_counter(self) -> None:
        """LEGACY counter increment (no-op si mode time-based)."""
        if self.store is None:
            self._bars_since_last_trade += 1

    def _is_cooldown_active(self) -> tuple[bool, float]:
        """Retourne (cooldown_actif, elapsed).

        Mode time-based (store) : elapsed = secondes ecoulees depuis last_trade_ts.
        Mode legacy counter (no store) : elapsed = nombre de bars depuis register_trade.
        """
        if self.store is not None:
            last_iso = self.store.get_last_trade_ts(self.symbol)
            if not last_iso:
                return False, 0.0
            try:
                last_dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
            except (ValueError, TypeError, AttributeError):
                # R1 code-reviewer 18/06 : format ISO corrompu = fail-open
                # (anti-pattern silent fallback documente .claude/rules/critical-tasks-review.md).
                # Le callback (injecte par main.py) emet BOTMR_COOLDOWN_ISO_CORRUPTED
                # niveau MAJEUR dans decisions/ pour trace J+1.
                if self._on_corrupted_state is not None:
                    try:
                        self._on_corrupted_state(self.symbol, last_iso or "")
                    except Exception:  # noqa: BLE001
                        # Callback safe-fail : ne jamais propager une erreur de log
                        # vers la decision de trading.
                        pass
                return False, 0.0
            # Tz safety : si last_dt est naive, on assume UTC
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            cooldown_sec = self.cfg.COOLDOWN_BARS * 60.0  # 1 bar = 1 min
            return elapsed < cooldown_sec, elapsed
        # Mode legacy counter
        return (
            self._bars_since_last_trade < self.cfg.COOLDOWN_BARS,
            float(self._bars_since_last_trade),
        )

    def _check_session(self, bar: dict) -> tuple[bool, str, str]:
        """Verifie si la session est tradable pour ce symbole.

        Returns: (allowed, session_phase, reason)
        """
        session_id = (bar.get("session_id") or "").upper()
        is_in_us = bool(bar.get("is_in_us_cash"))
        allowed_sessions = self.cfg.tradable_sessions(self.symbol)

        # Normalisation phase
        if is_in_us or session_id == "US":
            phase = "US"
        elif session_id == "ASIA":
            phase = "ASIA"
        elif session_id == "LONDON":
            phase = "LONDON"
        elif session_id == "US_AFTER":
            phase = "POST_RTH"
        elif session_id:
            phase = session_id
        else:
            phase = "?"

        if phase not in allowed_sessions:
            return False, phase, f"SESSION_NOT_ALLOWED:{phase}"

        # Pre-open US 11:30-13:30 UTC bruit (uniquement si US session active)
        if self.cfg.SKIP_PREOPEN_US and phase == "US":
            ts_ms = bar.get("ts", 0)
            if ts_ms:
                try:
                    dt_utc = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
                    mins = dt_utc.hour * 60 + dt_utc.minute
                    if PREOPEN_US_START_MIN <= mins < PREOPEN_US_END_MIN:
                        return False, phase, "PREOPEN_US_SKIP"
                except (OSError, ValueError, OverflowError):
                    pass

        return True, phase, ""

    def _apply_regime_filter(
        self,
        direction: str,
        slope_30: float,
        vix: float,
        trend_day_score: float,
    ) -> tuple[bool, str]:
        """Filtre regime asymetrique ES (trend_align) / NQ (contrarian).

        Returns: (allow, reject_reason)
        """
        mode = self.cfg.regime_filter_mode(self.symbol)
        if mode == "off":
            return True, ""

        if mode == "trend_align_es":
            # LONG necessite slope_30 > 0, SHORT slope_30 < 0
            if direction == "LONG" and slope_30 <= 0:
                return False, f"REGIME_TREND_ES_LONG_BLOCKED:slope_30={slope_30:.4f}"
            if direction == "SHORT":
                if slope_30 >= 0:
                    return False, f"REGIME_TREND_ES_SHORT_BLOCKED:slope_30={slope_30:.4f}"
                if self.cfg.VIX_MIN_FOR_SHORT > 0 and vix <= self.cfg.VIX_MIN_FOR_SHORT:
                    return False, f"VIX_TOO_LOW_FOR_SHORT:{vix:.2f}<={self.cfg.VIX_MIN_FOR_SHORT:.2f}"
            return True, ""

        if mode == "contrarian_nq":
            # LONG necessite slope_30 < 0, SHORT slope_30 > 0
            if direction == "LONG" and slope_30 >= 0:
                return False, f"REGIME_CONTRA_NQ_LONG_BLOCKED:slope_30={slope_30:.4f}"
            if direction == "SHORT":
                if slope_30 <= 0:
                    return False, f"REGIME_CONTRA_NQ_SHORT_BLOCKED:slope_30={slope_30:.4f}"
                if trend_day_score > self.cfg.NQ_TREND_DAY_MAX:
                    return False, f"NQ_TREND_DAY_TOO_HIGH:{trend_day_score:.2f}>{self.cfg.NQ_TREND_DAY_MAX:.2f}"
            return True, ""

        return True, ""

    def evaluate(self, bar: dict) -> SignalResult:
        """Evalue la bar courante et retourne un SignalResult.

        Tous les paths emettent un SignalResult (jamais None) avec skip_reason
        explicite pour audit JSONL.
        """
        self._bump_bar_counter()
        bar_ts = bar.get("ts")
        session_id = (bar.get("session_id") or "").upper()
        vwap_slope_30 = _f(bar.get("vwap_slope_30"))
        vix = _f(bar.get("vix_level"))
        rvol_z = _f(bar.get("rvol_zscore"))
        trend_day_score = _f(bar.get("ctx_trend_day_score"))

        base_ctx = {
            "bar_ts": bar_ts,
            "session_id": session_id,
            "vwap_slope_30": vwap_slope_30,
            "vix_level": vix,
            "rvol_zscore": rvol_z,
            "ctx_trend_day_score": trend_day_score,
            "sd_level": self.cfg.SD_LEVEL,
        }

        # 0. Circuit breaker (anti-stubbornness 18/06) : si halt actif sur ce sym,
        # bypass total avant tout autre check. Reference carnage 18/06 (-$1025 sur
        # 4 SL LONG ES). Trader pro stoppe a 3 SL pour reassesser regime.
        # Mode store=None : skip check (le mode legacy n'a pas de persistance).
        if self.cfg.CIRCUIT_BREAKER_ENABLED and self.store is not None:
            halt_until = self.store.get_halt_until_ts(self.symbol)
            now_ts = time.time()
            if halt_until > now_ts:
                remaining = int(halt_until - now_ts)
                return SignalResult(
                    tradable=False,
                    skip_reason=f"CIRCUIT_BREAKER_HALT:{remaining}s_remaining",
                    **base_ctx,
                )

        # 1. Cooldown (time-based si store, sinon legacy counter)
        is_cool, elapsed = self._is_cooldown_active()
        if is_cool:
            if self.store is not None:
                cooldown_sec = self.cfg.COOLDOWN_BARS * 60
                skip_reason = f"COOLDOWN:{elapsed:.0f}s/{cooldown_sec:.0f}s"
            else:
                skip_reason = f"COOLDOWN:{int(elapsed)}/{self.cfg.COOLDOWN_BARS}"
            return SignalResult(
                tradable=False,
                skip_reason=skip_reason,
                **base_ctx,
            )

        # 2. Session
        sess_ok, phase, sess_reason = self._check_session(bar)
        base_ctx["session_id"] = phase
        if not sess_ok:
            return SignalResult(
                tradable=False,
                skip_reason=sess_reason,
                **base_ctx,
            )

        # 3. RVOL min
        if rvol_z < self.cfg.RVOL_ZSCORE_MIN:
            return SignalResult(
                tradable=False,
                skip_reason=f"RVOL_TOO_LOW:{rvol_z:.2f}<{self.cfg.RVOL_ZSCORE_MIN:.2f}",
                **base_ctx,
            )

        # 4. Distances SD bands
        if self.cfg.SD_LEVEL == "sd3":
            d_low = _f(bar.get("dist_vwap_d_sd3d_pct"))
            d_high = _f(bar.get("dist_vwap_d_sd3u_pct"))
        else:
            d_low = _f(bar.get("dist_vwap_d_sd2d_pct"))
            d_high = _f(bar.get("dist_vwap_d_sd2u_pct"))

        thr = self.cfg.SD_THRESHOLD_PCT
        direction: Optional[str] = None
        if d_low <= -thr:
            direction = "LONG"
        elif d_high >= thr:
            direction = "SHORT"
        else:
            return SignalResult(
                tradable=False,
                skip_reason=f"NO_EXTENSION:d_low={d_low:.3f} d_high={d_high:.3f} thr={thr:.3f}",
                **base_ctx,
            )

        # 4-orderflow. Confirmation orderflow (Phase 4 18/06 calibration empirique
        # 6 trades : LOSS 3/3 partagent delta_bar negatif, WIN 3/3 partagent
        # delta_bar positif OU exhaustion claire). Variable la + discriminante.
        # Fail-loud : si delta_bar absent, on ne peut pas prouver l'orderflow.
        # Esprit lessons.md "gamma fail-closed" : pas de data = pas de trade.
        if self.cfg.ORDERFLOW_CONFIRM_ENABLED:
            delta_bar_raw = bar.get("delta_bar")
            if delta_bar_raw is None:
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=f"ORDERFLOW_NO_DATA:delta_bar_null",
                    **base_ctx,
                )
            delta_bar = _f(delta_bar_raw)
            rvol_z_of = _f(bar.get("rvol_zscore"))
            bn_absorb_bid = _b(bar.get("bn_absorb_bid"))
            bn_absorb_ask = _b(bar.get("bn_absorb_ask"))
            ctx_delta_exhaustion = _b(bar.get("ctx_delta_exhaustion"))

            if direction == "LONG":
                cond_buyers = delta_bar >= 0
                cond_exhaustion = (
                    (rvol_z_of >= self.cfg.ORDERFLOW_RVOL_EXHAUSTION_MIN and delta_bar < 0)
                    or ctx_delta_exhaustion
                )
                cond_absorb = bn_absorb_bid
                if not (cond_buyers or cond_exhaustion or cond_absorb):
                    return SignalResult(
                        tradable=False, direction=direction,
                        skip_reason=(
                            f"ORDERFLOW_NO_BUYERS_LONG:delta={delta_bar:.0f} "
                            f"rvol_z={rvol_z_of:.2f}"
                        ),
                        **base_ctx,
                    )
            elif direction == "SHORT":
                cond_sellers = delta_bar <= 0
                cond_exhaustion = (
                    (rvol_z_of >= self.cfg.ORDERFLOW_RVOL_EXHAUSTION_MIN and delta_bar > 0)
                    or ctx_delta_exhaustion
                )
                cond_absorb = bn_absorb_ask
                if not (cond_sellers or cond_exhaustion or cond_absorb):
                    return SignalResult(
                        tradable=False, direction=direction,
                        skip_reason=(
                            f"ORDERFLOW_NO_SELLERS_SHORT:delta={delta_bar:.0f} "
                            f"rvol_z={rvol_z_of:.2f}"
                        ),
                        **base_ctx,
                    )

        # 4-anti-top. Eviter entries pres swing high frais + proche HOD/LOD.
        # Calibration empirique 18/06 : LOSS 3/3 partagent bars_since_HH<=5
        # + dist_1d_max_ticks >= -25 (i.e. < 25t sous HOD).
        # Convention dist_1d_max_ticks : negatif si HOD au-dessus, positif si HOD
        # en-dessous. On bloque LONG si proche du HOD (dist >= -threshold).
        if self.cfg.ANTI_TOP_ENABLED:
            bs_high_raw = bar.get("bars_since_last_swing_high")
            bs_low_raw = bar.get("bars_since_last_swing_low")
            dist_1d_max = _f(bar.get("dist_1d_max_ticks"))
            dist_1d_min = _f(bar.get("dist_1d_min_ticks"))

            if direction == "LONG" and bs_high_raw is not None:
                try:
                    bs_high = float(bs_high_raw)
                except (TypeError, ValueError):
                    bs_high = float("inf")
                if (bs_high <= self.cfg.ANTI_TOP_BARS_SINCE_HH_MAX
                    and dist_1d_max >= -self.cfg.ANTI_TOP_DIST_HOD_MAX_TICKS):
                    return SignalResult(
                        tradable=False, direction=direction,
                        skip_reason=(
                            f"ANTI_TOP_LONG:bs_high={bs_high:.0f} "
                            f"dist_1d_max={dist_1d_max:.0f}t"
                        ),
                        **base_ctx,
                    )
            elif direction == "SHORT" and bs_low_raw is not None:
                try:
                    bs_low = float(bs_low_raw)
                except (TypeError, ValueError):
                    bs_low = float("inf")
                # Mirror : bloque si proche LOD (dist_1d_min <= +THRESHOLD)
                if (bs_low <= self.cfg.ANTI_TOP_BARS_SINCE_HH_MAX
                    and dist_1d_min <= self.cfg.ANTI_TOP_DIST_HOD_MAX_TICKS):
                    return SignalResult(
                        tradable=False, direction=direction,
                        skip_reason=(
                            f"ANTI_BOTTOM_SHORT:bs_low={bs_low:.0f} "
                            f"dist_1d_min={dist_1d_min:.0f}t"
                        ),
                        **base_ctx,
                    )

        # 4-momentum. Cap sur slope_10 pour eviter catch-the-knife violent.
        # Calibration 18/06 : LOSS 3/3 partagent slope_10 > 0.77 (momentum overheated).
        # Seuil 1.1 = WIN tolere encore (validation market-analyst tour 2).
        if self.cfg.MOMENTUM_CAP_ENABLED:
            slope_10 = _f(bar.get("vwap_slope_10"))
            if direction == "LONG" and slope_10 > self.cfg.SLOPE_10_MAX_LONG:
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=f"MOMENTUM_CAP_LONG:slope_10={slope_10:.2f}>{self.cfg.SLOPE_10_MAX_LONG}",
                    **base_ctx,
                )
            elif direction == "SHORT" and slope_10 < -self.cfg.SLOPE_10_MAX_LONG:
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=f"MOMENTUM_CAP_SHORT:slope_10={slope_10:.2f}<-{self.cfg.SLOPE_10_MAX_LONG}",
                    **base_ctx,
                )

        # 4bis-classifier. Regime classifier (Phase 3 18/06 - vote majoritaire 3 signaux).
        # Couche supplementaire AVANT le hard filter scalaire 4ter : detecte les
        # regimes TREND/PANIC via combinaison slope + swing structure + panic
        # (3 signaux INDEPENDANTS). Si direction bloquee -> skip avec verdict
        # explicite dans skip_reason pour audit J+1.
        # Bypass si regime_classifier=None (mode test legacy) OU si
        # cfg.REGIME_CLASSIFIER_ENABLED=False (kill-switch runtime).
        if (
            self.regime_classifier is not None
            and getattr(self.cfg, "REGIME_CLASSIFIER_ENABLED", True)
        ):
            verdict = self.regime_classifier.classify(bar, self.symbol)
            if not self.regime_classifier.allows_direction(verdict, direction):
                return SignalResult(
                    tradable=False,
                    direction=direction,
                    skip_reason=(
                        f"REGIME_CLASSIFIER_BLOCKED:{verdict.regime}_blocks_{direction} "
                        f"votes={verdict.votes} signals={verdict.signals}"
                    ),
                    **base_ctx,
                )

        # 4bis-scorer. Regime scorer continu (Phase 3 18/06 alternative score pondere).
        # Approche complementaire au classifier binaire : score [-100, +100] pondere
        # multi-features (slope 30% + swings 25% + delta 15% + trend_day 15%).
        # Capture la non-monotonie observee dans calibration empirique 9j (deciles
        # slope_30 disperses). Bloque uniquement TREND_*_STRONG + PANIC. TREND_*_WEAK
        # et RANGE autorises (regime MR pertinent contre tendance faible).
        # Bypass si regime_scorer=None (mode test legacy) OU REGIME_SCORER_ENABLED=False.
        if (
            self.regime_scorer is not None
            and getattr(self.cfg, "REGIME_SCORER_ENABLED", False)
        ):
            rs = self.regime_scorer.classify(bar, self.symbol)
            if not self.regime_scorer.allows_direction(rs, direction):
                return SignalResult(
                    tradable=False,
                    direction=direction,
                    skip_reason=(
                        f"REGIME_SCORE_BLOCKED:{rs.regime}_blocks_{direction} "
                        f"score={rs.score} features={rs.features}"
                    ),
                    **base_ctx,
                )

        # 4ter. Regime hard filter (anti catch falling knife - 18/06/2026)
        # Reference : carnage 18/06 -$1025 sur 4 LONGs ES en pleine descente.
        # Garde-fou ABSOLU complementaire du mode regime existant (step 7).
        # 3 checks : slope_30 trop bearish LONG, slope_30 trop bullish SHORT,
        # VIX panic intraday (spike % vs open, fallback absolu si pas d'open).
        if self.cfg.REGIME_FILTER_ENABLED:
            # Phase 2 18/06 : seuils par symbole (NQ stdev 6x ES = seuils echelle).
            min_long = self.cfg.slope_30_min_long(self.symbol)
            max_short = self.cfg.slope_30_max_short(self.symbol)
            if direction == "LONG" and vwap_slope_30 < min_long:
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=(
                        f"REGIME_BEARISH_TREND:slope_30={vwap_slope_30:.2f}"
                        f"<{min_long}"
                    ),
                    **base_ctx,
                )
            if direction == "SHORT" and vwap_slope_30 > max_short:
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=(
                        f"REGIME_BULLISH_TREND:slope_30={vwap_slope_30:.2f}"
                        f">{max_short}"
                    ),
                    **base_ctx,
                )
            # VIX spike intraday : check % vs open si dispo, sinon absolu
            vix_open = _f(bar.get("vix_open_session"))
            if vix > 0 and vix_open > 0:
                vix_change_pct = ((vix - vix_open) / vix_open) * 100.0
                if vix_change_pct > self.cfg.VIX_INTRADAY_SPIKE_PCT:
                    return SignalResult(
                        tradable=False, direction=direction,
                        skip_reason=(
                            f"REGIME_VIX_PANIC:{vix_change_pct:.1f}%"
                            f">{self.cfg.VIX_INTRADAY_SPIKE_PCT}"
                        ),
                        **base_ctx,
                    )
            elif vix > 0 and vix >= self.cfg.VIX_ABS_PANIC:
                # Fallback : pas de vix_open_session dans le bar -> seuil absolu
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=(
                        f"REGIME_VIX_PANIC_ABS:{vix:.1f}"
                        f">={self.cfg.VIX_ABS_PANIC}"
                    ),
                    **base_ctx,
                )

        # 4bis. Anti-clustering : si nouvelle entry dans X ticks du dernier entry
        # meme direction sur ce symbole, skip. 3e garde-fou (apres COOLDOWN + MAX_HOLD).
        # Pattern observe 18/06 : 5 LONGs ES dans 13 ticks = -$237.50 sur 1 entry.
        # Mode legacy counter (store=None) : check ignore (pas de persist possible).
        if self.store is not None:
            last_entry_price = self.store.get_last_entry_price(self.symbol, direction)
            if last_entry_price is not None:
                candidate_price = _f(bar.get("close"))
                if candidate_price > 0:
                    tick = get_tick_size(self.symbol)
                    dist_ticks = abs(candidate_price - last_entry_price) / tick
                    min_dist = self.cfg.no_reentry_ticks(self.symbol)
                    if dist_ticks < min_dist:
                        return SignalResult(
                            tradable=False,
                            direction=direction,
                            skip_reason=(
                                f"REENTRY_TOO_CLOSE:{dist_ticks:.0f}t<{min_dist}t"
                                f" last={last_entry_price:.2f}"
                            ),
                            **base_ctx,
                        )

        # 4quater. Confluence niveau MenthorQ : require N levels dans rayon X ticks.
        # Calibre carnage 18/06 : 4 LONGs ES dans le vide entre 2 niveaux structurels
        # (7548, 7554, 7558, 7533) = -$1025 broker. Un trader pro entre uniquement
        # quand HVL/GEX/VWAP SD bands clusterisent dans <10t.
        # Consomme les `dist_*_pct` et `dist_*_ticks` deja pre-calcules par DMP.
        # Mode legacy : si CONFLUENCE_FILTER_ENABLED=False, bypass complet.
        #
        # Bypass implicite : si AUCUN field dist_* present dans le bar (bar test
        # ou bar pre-enrichment), on bypass avec warning silencieux. Au premier
        # field present, le filtre s'applique. Cette regle preserve la non-regression
        # sur tests legacy qui n'injectent pas dist_mq_* et garantit l'activation
        # automatique des le 1er bar live enrichi.
        if self.cfg.CONFLUENCE_FILTER_ENABLED:
            candidate_price = _f(bar.get("close"))
            if candidate_price > 0:
                tick = get_tick_size(self.symbol)
                radius_ticks = self.cfg.confluence_radius_ticks(self.symbol)
                nearby_levels: list[tuple[str, float]] = []
                fields_present = 0
                for field_name, unit in MQ_LEVEL_DIST_FIELDS:
                    raw = bar.get(field_name)
                    # Field absent / None / string non-castable : ignore.
                    if raw is None:
                        continue
                    try:
                        dist_val = float(raw)
                    except (TypeError, ValueError):
                        continue
                    fields_present += 1
                    # Convertit en ticks selon unite
                    if unit == "pct":
                        # dist_pct = (level - close) / close * 100
                        # -> abs(level - close) = abs(dist_pct) * close / 100
                        # -> en ticks = abs(dist_pct) * close / 100 / tick
                        dist_ticks_abs = abs(dist_val) * candidate_price / 100.0 / tick
                    elif unit == "ticks":
                        dist_ticks_abs = abs(dist_val)
                    else:
                        continue  # unit inconnue, skip defensivement
                    if dist_ticks_abs <= radius_ticks:
                        nearby_levels.append((field_name, dist_ticks_abs))
                # Bypass si AUCUN field present (bar pre-enrichment / bar test).
                # Le check est strict : 1 seul field present suffit pour activer.
                if fields_present > 0:
                    n_levels = len(nearby_levels)
                    if n_levels < self.cfg.CONFLUENCE_MIN_LEVELS:
                        return SignalResult(
                            tradable=False,
                            direction=direction,
                            skip_reason=(
                                f"NO_CONFLUENCE:{n_levels}<{self.cfg.CONFLUENCE_MIN_LEVELS}"
                                f"_levels_in_{radius_ticks}t"
                            ),
                            **base_ctx,
                        )

        # 5. Exhaustion ctx (optionnel)
        if self.cfg.REQUIRE_EXHAUSTION:
            climax = _b(bar.get("ctx_climax_signal"))
            failed_auct = _b(bar.get("ctx_failed_auction"))
            delta_exh = _b(bar.get("ctx_delta_exhaustion"))
            mom_exh = _b(bar.get("ctx_momentum_exhaustion"))
            if not (climax or failed_auct or delta_exh or mom_exh):
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason="EXHAUSTION_REQUIRED_NONE", **base_ctx,
                )

        # 6. Delta direction (optionnel)
        if self.cfg.REQUIRE_DELTA_DIRECTION:
            delta_bar = _f(bar.get("delta_bar"))
            if direction == "LONG" and delta_bar <= 0:
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=f"DELTA_NEG_FOR_LONG:{delta_bar:.0f}", **base_ctx,
                )
            if direction == "SHORT" and delta_bar >= 0:
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=f"DELTA_POS_FOR_SHORT:{delta_bar:.0f}", **base_ctx,
                )

        # 7. Regime filter asymetrique
        regime_ok, regime_reason = self._apply_regime_filter(
            direction, vwap_slope_30, vix, trend_day_score,
        )
        if not regime_ok:
            return SignalResult(
                tradable=False, direction=direction,
                skip_reason=regime_reason, **base_ctx,
            )

        # 8. Compute entry/SL/TP
        entry_price = _f(bar.get("close"))
        if entry_price <= 0:
            return SignalResult(
                tradable=False, direction=direction,
                skip_reason="INVALID_CLOSE_PRICE", **base_ctx,
            )

        tick = get_tick_size(self.symbol)
        sl_ticks = self.cfg.sl_ticks(self.symbol)
        tp_ticks = int(round(sl_ticks * self.cfg.RR))

        if direction == "LONG":
            sl_price = entry_price - sl_ticks * tick
            tp_price = entry_price + tp_ticks * tick
        else:
            sl_price = entry_price + sl_ticks * tick
            tp_price = entry_price - tp_ticks * tick

        # signal_id unique : sym+bar_ts+direction (deterministe + uuid suffix)
        sid_base = f"{self.symbol}_{bar_ts}_{direction}"
        signal_id = f"BOTMR_{sid_base}_{uuid.uuid4().hex[:6]}"

        return SignalResult(
            tradable=True,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            sl_ticks=sl_ticks,
            tp_ticks=tp_ticks,
            rr_ratio=self.cfg.RR,
            signal_id=signal_id,
            **base_ctx,
        )
