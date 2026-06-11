"""sierra_pipeline.py — Orchestrateur Phase 4.1 Sierra Full Migration.

Phase 4.1 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s4.

Chain les 9 modules Phase 3 sur les bars Sierra natif (DMP schema 3.7.22).
Output : payload enrichi Sierra (380) + Phase 3 derive (113) = ~493 cols.

Architecture :
  Sierra DMP JSONL (live ou backfill)
       |
       v
  SierraLiveReader (sierra_live_io.py existant)
       |
       v
  SierraPipelineOrchestrator (CE MODULE)
   |- POCMigrationCalculator      (2 features)
   |- SwingsV2Calculator           (6 features)
   |- PrevLevelsCalculator         (18 features)
   |- SessionsFineCalculator       (35 features)
   |- DivergencesV2Calculator      (14 features)
   |- CtxRollingCalculator         (25 features)
   |- compute_roll_features_batch  (3 features, stateless)
   |- compute_eco_news_features    (10 features, stateless)
   |- session_utils helpers        (cross-module)
       |
       v
  JSONL enrichi (Sierra + Phase 3)

Cross-day reset :
  - Detection automatique via session_utils.compute_trading_date
  - Tous les Calculator stateful sont reset au boundary 18:00 ET CME

Mode dual-run (Phase 4.2-4.3) :
  - Compare Sierra+Phase3 vs Databento+enricher_chain actuel
  - Convergence > 95% par feature SIGNED (Sharpe haircut Bonferroni)

Auteur : MIA Trading V2 (Phase 4.1 Sierra Migration)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

try:
    from CORE.poc_migration import POCMigrationCalculator
    from CORE.swings_v2 import SwingsV2Calculator
    from CORE.prev_levels import PrevLevelsCalculator
    from CORE.sessions_fine import SessionsFineCalculator
    from CORE.divergences_v2 import DivergencesV2Calculator
    from CORE.ctx_rolling import CtxRollingCalculator
    from CORE.roll_calendar import compute_roll_features
    from CORE.eco_news_features import compute_eco_news_features
    from CORE.session_utils import get_trading_date_from_utc, utc_to_et
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    # Phase 1 Group A - portage modules Phase B+
    from CORE.phase_b_plus_long_streaming import (
        add_phase_b_plus_long_streaming, make_long_bar_state
    )
    from CORE.phase_b_plus_color_streaming import (
        add_phase_b_plus_color_streaming, make_color_bar_state
    )
    from CORE.bn_composites_streaming import inject_bn_composites
except ImportError:
    # Fallback si on lance depuis CORE/ directement
    from poc_migration import POCMigrationCalculator
    from swings_v2 import SwingsV2Calculator
    from prev_levels import PrevLevelsCalculator
    from sessions_fine import SessionsFineCalculator
    from divergences_v2 import DivergencesV2Calculator
    from ctx_rolling import CtxRollingCalculator
    from roll_calendar import compute_roll_features
    from eco_news_features import compute_eco_news_features
    from session_utils import get_trading_date_from_utc, utc_to_et
    from menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    from aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    # Phase 1 Group A
    from phase_b_plus_long_streaming import (
        add_phase_b_plus_long_streaming, make_long_bar_state
    )
    from phase_b_plus_color_streaming import (
        add_phase_b_plus_color_streaming, make_color_bar_state
    )
    from bn_composites_streaming import inject_bn_composites


# Default tick size par symbole (fallback si manquant)
DEFAULT_TICK_SIZE_BY_SYMBOL = {
    "ES": 0.25, "NQ": 0.25, "MGC": 0.10, "GC": 0.10,
}


class SierraPipelineOrchestrator:
    """Orchestrateur des 9 modules Phase 3 sur bars Sierra natif.

    Usage:
        pipeline = SierraPipelineOrchestrator(symbol="NQ")
        for sierra_bar in stream_bars:
            enriched = pipeline.enrich_bar(sierra_bar)
            write_jsonl(enriched)

    Cross-day reset :
        Detection automatique session_date_trading boundary 18:00 ET CME.
        Tous les Calculator stateful reset au passage de jour.
        Les Calculator batch (roll_calendar, eco_news) sont stateless.

    Concurrency :
        Une instance = un symbole. Pas thread-safe (state interne mutable).
        Pour multi-symbol : creer 1 instance par symbol.
    """

    def __init__(self, symbol: str = "NQ", log_event=None) -> None:
        """
        Args:
            symbol     : ES / NQ / MGC / GC.
            log_event  : Callable(code: str, **kwargs) | None.
                Si fourni, propage aux proxies (gamma_condition, aggressor) pour
                tracabilite J+1 (regle souveraine Jackson 01/05/2026 LOGS
                TRACABILITE). Si None, les proxies ne logguent rien (mode
                offline batch).
        """
        self.symbol = symbol.upper()
        self.tick_size = DEFAULT_TICK_SIZE_BY_SYMBOL.get(self.symbol, 0.25)

        # Log callback pour proxies (Phase 5.0.A + 5.0.B)
        self._log_event = log_event

        # Initialize stateful calculators
        self._poc_migration = POCMigrationCalculator()
        self._swings_v2 = SwingsV2Calculator(tick_size=self.tick_size)
        self._prev_levels = PrevLevelsCalculator()
        self._sessions_fine = SessionsFineCalculator()
        self._divergences_v2 = DivergencesV2Calculator()
        self._ctx_rolling = CtxRollingCalculator()

        # Cross-day tracking
        self._current_trading_date: Optional[date] = None

        # Phase 1 Group A - cvd_session minimal (fix C2 bug NULL)
        # cumsum delta_bar reset par session. Reset au cross-day.
        # Cf rolling_features_streaming.py:1170-1179 (sera porte Group B).
        self._cvd_session_running: float = 0.0

        # Phase 1 Group A - portage modules Phase B+ streaming
        self._long_bar_state = make_long_bar_state(self.symbol)
        self._color_bar_state = make_color_bar_state(self.symbol)

        # Stats orchestrateur (debug + monitoring)
        self._bars_processed: int = 0
        self._bars_skipped_nan: int = 0
        self._cross_day_resets: int = 0

        # Stats proxies Phase 5.0 (fix C2 review code-reviewer 11/06)
        # Permet monitoring J+1 % bars proxy-active
        self._proxy_gamma_injected: int = 0
        self._proxy_gamma_skipped: int = 0
        self._proxy_gamma_preserved: int = 0
        self._proxy_aggressor_injected: int = 0
        self._proxy_aggressor_skipped: int = 0
        self._proxy_aggressor_preserved: int = 0

    def _proxy_log_wrapper(self, code: str, **kwargs) -> None:
        """Wrapper propre counters + forward au log_event externe.

        Incremente les counters pour monitoring J+1, puis emit via log_event
        si fourni. Pattern : compter d'abord, logger ensuite (counters fiables
        meme si log_event raise).
        """
        if code == "MQ_PROXY_INJECTED":
            self._proxy_gamma_injected += 1
        elif code == "MQ_PROXY_SKIPPED_NO_FLIP_ZONE":
            self._proxy_gamma_skipped += 1
        elif code == "MQ_PROXY_PRESERVED_ORIGINAL":
            self._proxy_gamma_preserved += 1
        elif code == "AGGRESSOR_PROXY_INJECTED":
            self._proxy_aggressor_injected += 1
        elif code == "AGGRESSOR_PROXY_SKIPPED_MISSING_INPUTS":
            self._proxy_aggressor_skipped += 1
        elif code == "AGGRESSOR_PROXY_PRESERVED_ORIGINAL":
            self._proxy_aggressor_preserved += 1

        if self._log_event is not None:
            try:
                self._log_event(code, **kwargs)
            except Exception:  # noqa: BLE001
                pass  # log non-bloquant

    def get_proxy_stats(self) -> dict:
        """Stats proxies pour monitoring J+1 (fix C2 review).

        Returns:
            dict : counters par proxy + total bars + % rate.
        """
        total = max(self._bars_processed, 1)
        return {
            "bars_processed": self._bars_processed,
            "gamma": {
                "injected": self._proxy_gamma_injected,
                "skipped": self._proxy_gamma_skipped,
                "preserved": self._proxy_gamma_preserved,
                "injected_pct": 100.0 * self._proxy_gamma_injected / total,
            },
            "aggressor": {
                "injected": self._proxy_aggressor_injected,
                "skipped": self._proxy_aggressor_skipped,
                "preserved": self._proxy_aggressor_preserved,
                "injected_pct": 100.0 * self._proxy_aggressor_injected / total,
            },
        }

    # ─── Whitelist features Sierra placeholders (Phase 0 design v2 B3 + B5) ───
    # Features ou Sierra DMP emet 0/placeholder cassé. Python override autoritatif.
    # Cf DMP_Transform.h:1414-1416 (bn_score_* hardcoded 0.0f volontaire) +
    # 15/MIA_PIPELINE_RECAP.md:434 (trend_day_probability DEAD historique).
    # Decision Jackson 11/06 : BN famille recodee Python pour controle (override
    # verdict 2 agents) - documenter PATTERN_11 vigilance si gate hardcode propose.
    SIERRA_ZERO_NEVER_CALCULATED = frozenset((
        # B3 - bn_score_* placeholder C++ DMP_Transform.h:1397 (desactive 18/04)
        "bn_score_raw", "bn_score_bull", "bn_score_bear",
        # NB : bn_pressure_ask/bid RETIRES de la whitelist 11/06 - signal Sierra
        # VIVANT cf DMP_Transform.h:1393-1395 (Double/Triple Ask). Verif empirique
        # 20260605_ES.jsonl : 0.5%/1.2% bars non-zero. Override Python interdit.
        # B5 - game_changers placeholders Sierra DMP (decision post-Jackson)
        "trend_day_probability",   # remplace downstream par ctx_trend_day_score
        "open_direction",           # recalcul via game_changers.direction()
    ))

    @classmethod
    def _safe_update(cls, enriched: dict, phase3_feats: dict) -> None:
        """Update enriched avec phase3_feats SANS ecraser valeurs Sierra natif non-NaN.

        Fix B6 audit ULTRATHINK 11/06 : Sierra DMP calcule deja certaines
        features (pdh, pdl, ovn_high, asia_high, etc.). Phase 3 Calculator
        re-calculent et retournent NaN/None pendant cold-start, ce qui ECRASE
        les valeurs Sierra correctes.

        Politique :
        - Si Phase 3 retourne None/NaN ET Sierra natif a une valeur, garder Sierra.
        - Sinon utiliser Phase 3 (incluant False/0 explicit).
        - EXCEPTION (Phase 0 B3+B5) : features dans SIERRA_ZERO_NEVER_CALCULATED
          ou Sierra=0.0 est un placeholder casse -> Python override autoritatif
          meme si Phase 3 retourne valeur non-None.
        """
        import math
        for k, phase3_v in phase3_feats.items():
            existing = enriched.get(k)
            # Phase 3 returns NaN/None -> garder Sierra si vivant
            is_p3_nan = (phase3_v is None or
                         (isinstance(phase3_v, float) and math.isnan(phase3_v)))

            # EXCEPTION B3+B5 : Sierra placeholder 0.0 → Python override autoritatif
            if (k in cls.SIERRA_ZERO_NEVER_CALCULATED
                and existing == 0.0
                and not is_p3_nan):
                enriched[k] = phase3_v
                continue

            # Politique standard
            if is_p3_nan and existing is not None:
                continue  # garde Sierra natif
            enriched[k] = phase3_v

    def enrich_bar(
        self,
        sierra_bar: dict,
        bar_ts_utc: Optional[datetime] = None,
    ) -> dict:
        """Enrichit une bar Sierra natif avec les 113 features Phase 3.

        Args:
            sierra_bar : dict bar Sierra natif (380 cols schema 3.7.22).
                Champs requis : close, bar_high, bar_low, delta_bar,
                total_vol, atr, dist_swing_high, dist_swing_low,
                dist_cur_vpoc. Optionnels : vwap_d, finish_strength,
                range_pos, va_position_pct, bn_absorb_ask/bid, buy_vol, sell_vol.
            bar_ts_utc : timestamp UTC tz-aware. Si None, extrait de sierra_bar
                ["ts_event_ns"] ou ["ts_utc"].

        Returns:
            dict : sierra_bar + features Phase 3 (113 ajoutees).

        Raises:
            ValueError : si bar_ts_utc absent ET non extractible.
        """
        # Resolve timestamp
        if bar_ts_utc is None:
            bar_ts_utc = self._extract_ts_utc(sierra_bar)

        if bar_ts_utc.tzinfo is None:
            bar_ts_utc = bar_ts_utc.replace(tzinfo=timezone.utc)

        # Detection cross-day (CME 18:00 ET reset)
        trading_date = get_trading_date_from_utc(bar_ts_utc)
        if self._maybe_cross_day_reset(trading_date):
            self._cross_day_resets += 1

        # Start with Sierra natif bar
        enriched = dict(sierra_bar)
        self._bars_processed += 1

        # FIX BUG #1 audit ULTRATHINK 11/06 : DMP utilise 'price' (pas 'close').
        # Mapping pour Calculator + PERSIST dans enriched (sans persist :
        # downstream Bot 1 V3 / train_lightgbm qui lit bar['close'] casse).
        close = sierra_bar.get("close")
        if close is None:
            close = sierra_bar.get("price")
        bar_high = sierra_bar.get("bar_high") or sierra_bar.get("high")
        bar_low = sierra_bar.get("bar_low") or sierra_bar.get("low")
        total_vol = sierra_bar.get("total_vol")
        if total_vol is None:
            total_vol = sierra_bar.get("volume")

        # Persiste alias dans enriched (fix B1 review code-reviewer + fix Jackson 11/06).
        # Double-aliases pour consumers legacy : 'close'/'price', 'bar_high'/'high',
        # 'bar_low'/'low', 'total_vol'/'volume'. Sans ca, Bot3v4 fait row.get("high")
        # et recoit None alors que bar_high existe.
        if close is not None:
            enriched["close"] = close
            enriched["price"] = close  # alias Sierra DMP natif
        if bar_high is not None:
            enriched["bar_high"] = bar_high
            enriched["high"] = bar_high  # alias Bot3v4 + consumers legacy Databento
        if bar_low is not None:
            enriched["bar_low"] = bar_low
            enriched["low"] = bar_low
        if total_vol is not None:
            enriched["total_vol"] = total_vol
            enriched["volume"] = total_vol

        # ─── Module 3.1 : POC Migration (2 features) ───
        poc_feats = self._poc_migration.update(
            dist_cur_vpoc=sierra_bar.get("dist_cur_vpoc"),
        )
        self._safe_update(enriched,poc_feats)

        # ─── Module 3.2 : Swings V2 Wyckoff/ICT (6 features) ───
        # Fix P2 audit market-analyst + quality-auditor 11/06 :
        # Sierra DMP fournit `new_swing_high/low` natif (18 et 32 events sur 1926
        # bars NQ). Code Phase 3 essayait de detecter via `dist_swing_high == 0`
        # mais Sierra ne reset jamais dist a 0 sur la bar swing -> high DEAD.
        # Bug asymetrique : low fonctionnait par chance (4 zeros aleatoires).
        # Si Sierra fournit new_swing_high/low : substituer dist=0 force pour
        # declencher detection Phase 3.
        dsh = sierra_bar.get("dist_swing_high")
        dsl = sierra_bar.get("dist_swing_low")
        if sierra_bar.get("new_swing_high"):
            dsh = 0.0  # force detection cote Phase 3
        if sierra_bar.get("new_swing_low"):
            dsl = 0.0

        swings_feats = self._swings_v2.update(
            dist_swing_high=dsh,
            dist_swing_low=dsl,
            bar_high=bar_high,
            bar_low=bar_low,
            close=close,
        )
        self._safe_update(enriched,swings_feats)

        # ─── Module 3.3 : Prev Levels (18 features) ───
        prev_feats = self._prev_levels.update(
            bar_ts_utc=bar_ts_utc,
            bar_high=bar_high,
            bar_low=bar_low,
            close=close,
            atr=sierra_bar.get("atr"),
        )
        self._safe_update(enriched,prev_feats)

        # ─── Module 3.4 : Sessions Fine (35 features) ───
        sessions_feats = self._sessions_fine.update(
            bar_ts_utc=bar_ts_utc,
            bar_high=bar_high,
            bar_low=bar_low,
            close=close,
        )
        self._safe_update(enriched,sessions_feats)

        # ─── Module 3.6 : Roll Calendar (3 features, stateless) ───
        try:
            roll_feats = compute_roll_features(
                bar_date=trading_date,
                symbol=self.symbol,
            )
            self._safe_update(enriched,roll_feats)
        except ValueError:
            # Symbol non supporte (ex: MGC partial) -> NaN propre
            self._safe_update(enriched,{
                "is_roll_day": False,
                "days_since_roll": np.nan,
                "roll_phase": 0,
            })

        # ─── Module 3.7 : Eco News Features (10 features, stateless) ───
        try:
            eco_feats = compute_eco_news_features(now_utc=bar_ts_utc)
            self._safe_update(enriched,eco_feats)
        except (RuntimeError, ValueError):
            # Module eco_calendar indispo (ex: tests sans network)
            self._safe_update(enriched,self._empty_eco_features())

        # ─── Module 3.8 : Divergences V2 (14 features) ───
        div_feats = self._divergences_v2.update(
            close=close,
            delta_bar=sierra_bar.get("delta_bar"),
            atr=sierra_bar.get("atr"),
        )
        self._safe_update(enriched,div_feats)

        # ─── Module 3.5 : Ctx Rolling CRITIQUE (25 features) ───
        # Fix BUG #2 + #3 audit ULTRATHINK 11/06 :
        # - Sierra DMP utilise `range_pos_va` (Value Area position), pas `range_pos`.
        # - Sierra emit en SCALE [0, 100] (pourcentage). Le code ctx_rolling
        #   utilise seuils RANGE_POS_EXTREME_HIGH=0.9 / LOW=0.1 (scale [0,1]).
        # Sans normalisation /100 : seuil 0.9 declenche sur ~70% des bars
        # (faux positifs climax). Verification empirique 11/06 NQ.
        range_pos = sierra_bar.get("range_pos")
        if range_pos is None:
            range_pos = sierra_bar.get("range_pos_va")
        # Auto-detect scale : si max observe > 1.5 = [0,100], normaliser /100
        if range_pos is not None and range_pos > 1.5:
            range_pos = range_pos / 100.0

        ctx_feats = self._ctx_rolling.update(
            close=close,
            bar_high=bar_high,
            bar_low=bar_low,
            delta_bar=sierra_bar.get("delta_bar"),
            total_vol=total_vol,
            atr=sierra_bar.get("atr"),
            buy_vol=sierra_bar.get("buy_vol"),
            sell_vol=sierra_bar.get("sell_vol"),
            vwap_d=sierra_bar.get("vwap_d"),
            finish_strength=sierra_bar.get("finish_strength"),
            range_pos=range_pos,
            va_position_pct=sierra_bar.get("va_position_pct"),
            bn_absorb_ask=sierra_bar.get("bn_absorb_ask", 0.0) or 0.0,
            bn_absorb_bid=sierra_bar.get("bn_absorb_bid", 0.0) or 0.0,
        )
        self._safe_update(enriched,ctx_feats)

        # ─── Phase 5.0.A : Proxy MenthorQ Sierra-native (11/06/2026) ───
        # Scraper MenthorQ down depuis 27/05 -> mq_gamma_condition absent.
        # MQ API publique non encore dispo (Jackson liste d'attente).
        # Proxy temporaire : bool_gex_flip_zone (Sierra DMP natif) -> mq_gamma_condition.
        # Cf CORE/menthorq_v2_sierra_proxy.py docstring pour semantique + revert.
        # Fix C1 review 11/06 : log_fn + sym branches pour tracabilite J+1.
        inject_gamma_condition_proxy(
            enriched, log_fn=self._proxy_log_wrapper, sym=self.symbol)

        # ─── Phase 5.0.B : Proxy aggressor_imbalance Sierra-native (11/06/2026) ───
        # Sierra DMP ne fournit pas trade-by-trade aggressor count (PhaseB+ original).
        # Reconstruction count via buy_vol/avg_ask_size + sell_vol/avg_bid_size
        # pour preserver semantique COUNT (vs ask_bid_imbalance volume-weighted).
        # Cf CORE/aggressor_imbalance_proxy.py docstring.
        inject_aggressor_imbalance_proxy(
            enriched, log_fn=self._proxy_log_wrapper, sym=self.symbol)

        # ─── Phase 1 Group A - cvd_session minimal (fix C2 bug NULL) ───
        # cumsum delta_bar reset par cross-day. Convention Sierra confirmee :
        # delta_bar Sierra natif = AskVolume - BidVolume (signe sain post fix 07/06).
        # cvd_session est consomme par bot3_context_analyzer.py:95.
        # NB : portage complet rolling_features_streaming Group B remplacera ce fix.
        delta_bar = sierra_bar.get("delta_bar")
        if delta_bar is not None:
            try:
                self._cvd_session_running += float(delta_bar)
                enriched["cvd_session"] = round(self._cvd_session_running, 2)
            except (TypeError, ValueError):
                pass

        # ─── Phase 1 Group A - phase_b_plus_long_streaming (13 features) ───
        # bn_long_up/dn, bar_body_ticks, range_*, long_*_pattern, extension lines.
        # Necessite open/high/low/close dans enriched (aliases F2 deja faits).
        try:
            long_out = add_phase_b_plus_long_streaming(
                enriched, self._long_bar_state)
            # _safe_update merge avec gestion NaN + whitelist
            self._safe_update(enriched, {k: long_out[k] for k in long_out
                                          if k not in enriched})
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_PHASE_B_PLUS_LONG_OK",
                                     sym=self.symbol)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_PHASE_B_PLUS_LONG_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        # ─── Phase 1 Group A - phase_b_plus_color_streaming (12 features lag-1) ───
        # dist_color_*_pct, n_color_*_cluster (consomme par Bot 3 v3 wrapper).
        try:
            color_out = add_phase_b_plus_color_streaming(
                enriched, self._color_bar_state)
            self._safe_update(enriched, {k: color_out[k] for k in color_out
                                          if k not in enriched})
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_COLOR_BARS_OK",
                                     sym=self.symbol)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_COLOR_BARS_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        # ─── Phase 1 Group A - bn_composites Python (B3 decision Jackson) ───
        # Sierra DMP emet bn_score_* a 0.0 (desactive 18/04/2026 cf DMP_Transform.h:1397).
        # Python recalcule UNIQUEMENT bn_score_raw/bull/bear (PAS bn_pressure_*
        # qui sont Sierra natifs vivants cf DMP_Transform.h:1393-1395).
        # Route via _safe_update strict (whitelist SIERRA_ZERO_NEVER_CALCULATED).
        # PATTERN_11 vigilance : ne PAS hardcoder gate sur bn_score_X sans DSR.
        inject_bn_composites(enriched, safe_update_fn=self._safe_update,
                              log_fn=self._log_event, sym=self.symbol)

        # ─── Fix A4 (11/06/2026) : Reconstruction dist_mq_*_pct manquants ───
        # Bug DMP C++ partiel : sur NQ `dist_mq_put_0dte_pct` est 100% NULL et
        # `dist_mq_call_0dte_pct` 50% NULL alors que les raw (ticks) sont OK.
        # Politique non-overwrite : recalcule UNIQUEMENT si pct est NULL.
        # Formule : pct = (dist_ticks * tick_size / close) * 100
        if close is not None and close > 0:
            _mq_raw_keys = (
                "dist_mq_put", "dist_mq_call", "dist_mq_hvl",
                "dist_mq_put_0dte", "dist_mq_call_0dte", "dist_mq_hvl_0dte",
            )
            for raw_key in _mq_raw_keys:
                pct_key = f"{raw_key}_pct"
                if enriched.get(pct_key) is None:
                    raw_val = enriched.get(raw_key)
                    if raw_val is not None:
                        try:
                            enriched[pct_key] = round(
                                (float(raw_val) * self.tick_size / close) * 100.0,
                                6,
                            )
                        except (TypeError, ValueError, ZeroDivisionError):
                            pass  # garde NULL si calcul echoue

        # ─── Fix anomalies 6+7 (11/06/2026 matin) : OVN + PDH/PDL distances ───
        # OVN : on a ovn_high/ovn_low (Sierra DMP raw) mais dist_ovn_high/low=null
        # et ovn_range_ticks=0 (bug C++). Phase 3 sessions_fine ECRASE
        # ovn_high/low par bar_high/low (premiere bar cold-start) -> on lit
        # depuis sierra_bar original pour avoir les vrais niveaux Sierra DMP.
        # PDH/PDL : pareil, on a dist_pdh_pct/pdl_pct OK mais dist_pdh_atr=null.
        # Convention Sierra confirmee : dist = level - close (cf bar live 09:36 UTC).
        # Politique non-overwrite : recalcule UNIQUEMENT si dist est NULL.
        if close is not None and close > 0 and self.tick_size > 0:
            # Anomalie 6 : OVN. Sierra DMP n'expose PAS ovn_high/low dans le RAW
            # JSONL - ils sont calcules par Phase 3 (sessions_fine). On lit donc
            # depuis enriched (Phase 3 output) pour avoir les vrais niveaux.
            ovn_high_raw = enriched.get("ovn_high")
            ovn_low_raw = enriched.get("ovn_low")
            if enriched.get("dist_ovn_high") is None and ovn_high_raw is not None:
                try:
                    enriched["dist_ovn_high"] = round(
                        (float(ovn_high_raw) - close) / self.tick_size, 4)
                except (TypeError, ValueError):
                    pass
            if enriched.get("dist_ovn_low") is None and ovn_low_raw is not None:
                try:
                    enriched["dist_ovn_low"] = round(
                        (float(ovn_low_raw) - close) / self.tick_size, 4)
                except (TypeError, ValueError):
                    pass
            # ovn_range_ticks : DMP C++ retourne 0 par bug.
            cur_range = enriched.get("ovn_range_ticks")
            if (cur_range in (None, 0, 0.0)
                and ovn_high_raw is not None and ovn_low_raw is not None):
                try:
                    enriched["ovn_range_ticks"] = round(
                        (float(ovn_high_raw) - float(ovn_low_raw)) / self.tick_size, 4)
                except (TypeError, ValueError):
                    pass

            # Anomalie 7 : PDH/PDL ATR-normalises (lecture sierra_bar)
            # prev_levels.PrevLevelsCalculator retourne np.nan en cold-start,
            # ecrit dans enriched. On considere None ET NaN comme "vide".
            import math as _m
            def _is_empty(v):
                if v is None: return True
                if isinstance(v, float) and _m.isnan(v): return True
                return False

            atr_raw = sierra_bar.get("atr")  # Sierra ATR en TICKS
            if atr_raw is not None and atr_raw > 0:
                pdh_raw = sierra_bar.get("pdh")
                pdl_raw = sierra_bar.get("pdl")
                if _is_empty(enriched.get("dist_pdh_atr")) and pdh_raw is not None:
                    try:
                        dist_ticks = (float(pdh_raw) - close) / self.tick_size
                        enriched["dist_pdh_atr"] = round(dist_ticks / atr_raw, 6)
                    except (TypeError, ValueError, ZeroDivisionError):
                        pass
                if _is_empty(enriched.get("dist_pdl_atr")) and pdl_raw is not None:
                    try:
                        dist_ticks = (float(pdl_raw) - close) / self.tick_size
                        enriched["dist_pdl_atr"] = round(dist_ticks / atr_raw, 6)
                    except (TypeError, ValueError, ZeroDivisionError):
                        pass

        # Meta orchestrateur
        enriched["_phase3_enriched"] = True
        enriched["_phase3_bars_processed"] = self._bars_processed

        return enriched

    def _maybe_cross_day_reset(self, trading_date: date) -> bool:
        """Reset cross-day si trading_date change. Returns True si reset effectue."""
        if self._current_trading_date is None:
            self._current_trading_date = trading_date
            self._cvd_session_running = 0.0  # reset cvd_session cumsum
            return False
        if trading_date == self._current_trading_date:
            return False
        # Cross-day : reset tous les Calculator stateful
        # (prev_levels + sessions_fine ont leur propre reset interne via ts,
        # mais on appelle pour safety + pour les autres)
        self._poc_migration.reset()
        self._swings_v2.reset()
        self._divergences_v2.reset()
        self._ctx_rolling.reset()
        # prev_levels et sessions_fine se reset automatiquement
        # Phase 1 Group A : reset cvd_session cumsum cross-day
        self._cvd_session_running = 0.0
        # Reset long/color bar states (factories deja importees top-of-file
        # avec fallback CORE/ - cf review CRITIQUE 3 : pas d'import local).
        self._long_bar_state = make_long_bar_state(self.symbol)
        self._color_bar_state = make_color_bar_state(self.symbol)
        self._current_trading_date = trading_date
        return True

    @staticmethod
    def _extract_ts_utc(sierra_bar: dict) -> datetime:
        """Extrait timestamp UTC depuis sierra_bar.

        Cherche dans cet ordre :
          1. ts_utc (ISO string ou datetime)
          2. ts_event_ns (Databento format)
          3. ts (Sierra DMP format)

        Raises:
            ValueError : si aucun timestamp trouve.
        """
        for key in ("ts_utc", "ts_event_ns", "ts"):
            if key not in sierra_bar:
                continue
            v = sierra_bar[key]
            if v is None:
                continue
            if isinstance(v, datetime):
                return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            if isinstance(v, str):
                # ISO format
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            if isinstance(v, (int, float)):
                # Heuristique multi-unite (Sierra DMP = ms, Databento = ns) :
                #   v > 1e17 -> nanoseconds (Databento ts_event_ns)
                #   v > 1e14 -> microseconds
                #   v > 1e11 -> milliseconds (Sierra DMP "ts")
                #   sinon   -> seconds
                if key == "ts_event_ns" or v > 1e17:
                    return datetime.fromtimestamp(v / 1e9, tz=timezone.utc)
                if v > 1e14:
                    return datetime.fromtimestamp(v / 1e6, tz=timezone.utc)
                if v > 1e11:
                    return datetime.fromtimestamp(v / 1e3, tz=timezone.utc)
                return datetime.fromtimestamp(v, tz=timezone.utc)
        raise ValueError(
            "SierraPipelineOrchestrator : impossible d'extraire timestamp UTC "
            "depuis sierra_bar (chercher ts_utc / ts_event_ns / ts)"
        )

    @staticmethod
    def _empty_eco_features() -> dict:
        """Empty features eco_news (fallback si module indispo)."""
        return {
            "is_news_5m": False,
            "is_news_15m": False,
            "is_news_30m": False,
            "is_news_60m": False,
            "is_critical_news_60m": False,
            "news_seconds_until": np.nan,
            "news_minutes_until": np.nan,
            "is_eco_blocked": False,
            "is_session_blocked": False,
            "is_blocked_combined": False,
        }

    def get_stats(self) -> dict:
        """Statistiques orchestrateur (monitoring + debug)."""
        return {
            "symbol": self.symbol,
            "bars_processed": self._bars_processed,
            "bars_skipped_nan": self._bars_skipped_nan,
            "cross_day_resets": self._cross_day_resets,
            "current_trading_date": (
                self._current_trading_date.isoformat()
                if self._current_trading_date else None
            ),
        }


def enrich_batch_dataframe(
    df: pd.DataFrame,
    symbol: str = "NQ",
    ts_col: str = "ts_utc",
) -> pd.DataFrame:
    """Batch enrichment Sierra historique (mode dataset_builder).

    Args:
        df : DataFrame avec bars Sierra natif (380 cols schema 3.7.22).
             Trie chronologiquement (ts_utc croissant).
        symbol : "ES" / "NQ" / "MGC".
        ts_col : nom colonne timestamp UTC.

    Returns:
        DataFrame copie + 113 colonnes Phase 3 ajoutees.

    Raises:
        ValueError : si ts_col manquant.
    """
    if ts_col not in df.columns:
        raise ValueError(
            f"enrich_batch_dataframe : colonne ts_utc '{ts_col}' manquante"
        )

    pipeline = SierraPipelineOrchestrator(symbol=symbol)
    rows = []

    for _, row in df.iterrows():
        sierra_bar = row.to_dict()
        ts = row[ts_col]
        if pd.isna(ts):
            # Skip bar invalide, append vide
            rows.append(sierra_bar)
            continue
        if isinstance(ts, str):
            bar_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, (datetime, pd.Timestamp)):
            bar_ts = pd.Timestamp(ts).to_pydatetime()
            if bar_ts.tzinfo is None:
                bar_ts = bar_ts.replace(tzinfo=timezone.utc)
        else:
            rows.append(sierra_bar)
            continue
        enriched = pipeline.enrich_bar(sierra_bar, bar_ts_utc=bar_ts)
        rows.append(enriched)

    return pd.DataFrame(rows)
