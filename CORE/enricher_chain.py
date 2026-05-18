"""enricher_chain.py - Chain commune d'enrichissement (live + batch).

Phase REFACTOR Option B (2026-05-16) - extraction de la chain pure depuis
`live_enricher._process_bar_cycle` pour permettre :
  - Live : `live_enricher.py` wrapper avec readers I/O Databento Live + writer JSONL
  - Batch : `replay_enricher_batch.py` wrapper avec readers historiques Databento parquets

Garantit ZERO drift entre live et batch (meme code = meme output).

Voir DOCS/enricher_chain_side_effects_map.md v1.1 pour la cartographie complete
des side-effects et la frontiere wrapper <-> chain.

Auteur : MIA Trading System V2
  v1.0 (2026-05-16) : version initiale, extract chain pure 1069 LOC depuis
                      live_enricher_v_pre_refactor.py lignes 302-1370.
                      Couvre R1 audit code-reviewer (state.append_bar DANS la
                      chain, partner_state_provider callable injecte, log_fn
                      callable injecte, imports streaming locaux preserves).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable, Optional

# pandas/numpy import top-of-module (deja chargés par live_enricher_state)
import pandas as pd

# Logger dedie module (BUG #1 fix code-reviewer 2026-05-16) : la chain extraite
# utilisait `logger.warning(...)` (lignes ~245, 358, 1061 dans enricher_chain.py)
# mais le `logger` du backup vivait dans live_enricher.py et n'avait pas ete
# extrait. Sans ce logger, NameError au premier crash VIX engine streaming.
logger = logging.getLogger("enricher_chain")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# State type pour typing (import optionnel, pas de cycle)
try:
    from live_enricher_state import LiveEnricherState
except ImportError:
    LiveEnricherState = Any  # type alias fallback

# Logger fallback (si log_fn=None, no-op)
def _default_log_fn(code: str, **kwargs) -> None:
    """No-op log_fn par defaut. Live injecte _emit_log de live_enricher.py."""
    pass


def compose_enriched_payload(
    symbol: str,
    state: "LiveEnricherState",
    inputs: dict,
    log_fn: Optional[Callable] = None,
    partner_state_provider: Optional[Callable[[str], "Optional[LiveEnricherState]"]] = None,
) -> tuple[dict, dict]:
    """Compose le payload enrichi (~430 cols) depuis inputs OHLCV + MQ + VIX + trades.

    PURE function : meme `(state, inputs)` -> meme `payload`. Pas de side-effect
    sur globals modules. Mutations sur `state` explicites via state.lock interne.

    Args:
        symbol : "ES.c.0" / "NQ.c.0" / "MGC.v.0"
        state : LiveEnricherState (mutable, lock interne gere)
        inputs : {
            "ohlcv" : dict (Databento OHLCV bar - close, open, high, low, vol, ts_event_ns),
            "trades_df" : pd.DataFrame (trades alignes bar [ts_event_ns, +60s]),
            "mq_levels" : dict | None (MenthorQ snapshot mq_call/put/hvl/gex[10]/blind[10]),
            "vix" : dict | None (VIX_Lite enrichi),
            "stream_alive" : bool (Databento Live state, True constant en batch),
            "ts_read_ns" : int (wall-clock lecture inputs, ts_event_ns+60e9 en batch),
        }
        log_fn : Callable(code: str, **kwargs) | None (default = no-op)
        partner_state_provider : Callable(partner_symbol) -> LiveEnricherState | None
                                 Pour intermarket ES/NQ cross. Si None, intermarket = NaN.

    Returns:
        payload : dict (~430 cols enriched bar, pret pour JSONL write)
        meta : dict {
            "phase_b_plus_plus_partial" : bool (True si chain crash -> payload revert),
            "failed_lot" : str | None ("LOT_1_trades", "footprint_cells", etc.),
            "engine_name" : str | None ("phase_b_plus_plus_chain", etc.),
            "data_quality_flag" : int (bitmask 7 bits - voir docstring bitmask),
        }
    """
    if log_fn is None:
        log_fn = _default_log_fn

    # Extract inputs locaux (acces lecture, pas mutation)
    ohlcv = inputs["ohlcv"]
    ts_event_ns = ohlcv.get("ts_event_ns", 0)

    with state.lock:
        state.update_mq(inputs["mq_levels"])
        state.update_vix(inputs["vix"])

    # 4. Compose enriched payload (SKELETON Jour 4 : pas d'engines metier).
    # En Phase 3b-d on ajoutera : apply_phase_b_helpers, apply_phase_b_plus,
    # ..., regime_engine_v6.compute_regime_dict, etc.
    payload = dict(ohlcv)  # base : OHLCV
    payload["symbol"] = symbol
    payload["ts_event_ns"] = ts_event_ns

    # Inject MQ snapshot (passthrough Phase 3a)
    if inputs["mq_levels"]:
        payload["mq_snapshot_ts"] = inputs["mq_levels"].get("ts_event")
        for k, v in inputs["mq_levels"].items():
            if k != "ts_event":
                payload[f"mq_{k}" if not k.startswith("mq_") else k] = v

    # Pass 4-P2 : calculer dist_mq_*_pct depuis MQ levels absolus + close
    # Audit feature-engineer 15/05 dette #6 BUG #1 : LOT 4 absorb consomme
    # dist_mq_*_pct (MQ_RESISTANCE_DIST_COLS = ["dist_mq_call_pct",
    # "dist_mq_call_0dte_pct"], MQ_SUPPORT_DIST_COLS = ["dist_mq_put_pct",
    # "dist_mq_put_0dte_pct"], MQ_NEUTRAL_DIST_COLS = ["dist_mq_hvl_pct",
    # "dist_mq_hvl_pct_z"]). Sans : 4 features mortes at_level + cascade
    # LOT 5 trapped_at_resistance/support (Pattern V1 silent).
    #
    # FIX code-reviewer P0+P2 R1 BUG #2 : convention signe BATCH =
    # (level - close) / close * 100 (cf enrich_dataset_v5_htf.py:500).
    # Inverse = parite cassee, ML training a appris signe batch.
    # LOT 4 absorb utilise abs() donc neutre pour at_level, mais
    # autres consumers signe-sensibles (above/below booleans) auraient
    # divergence batch/stream.
    #
    # FIX code-reviewer P0+P2 R1 BUG #1 : dist_mq_hvl_pct_z N'EST PAS
    # un alias de mq_hvl_0dte - c'est un z-score rolling normalise par
    # symbole calcule dans batch (build_dataset_v4_dmp_databento.py:837).
    # Calcul streaming necessite buffer rolling historique long terme.
    # DECISION : NE PAS produire dist_mq_hvl_pct_z en P2 -> LOT 4 absorb
    # tolera NaN (cf MQ_NEUTRAL_DIST_COLS list[1] = "dist_mq_hvl_pct_z"
    # absent du payload -> skip dans boucle ligne 230).
    # IDEAS_BACKLOG : implementer z-score streaming pour parite complete.
    _close = float(ohlcv.get("close")) if ohlcv.get("close") is not None else None
    if _close is not None and _close > 0:
        # P1.4 fix Jackson 15/05/2026 : alignment keys payload MQ_Lite.
        # AVANT fix : code cherchait mq_call_resistance/put_support qui
        # n'existent PAS dans le payload. Donc dist_mq_call/put_pct
        # JAMAIS calcules. Meme pattern que BUG #1 next_wall_dist_ticks.
        # Audit feature-engineer 15/05 : BUG silent dist_mq_call_pct.
        #
        # Decision code-reviewer 15/05 : PAS de fallback HVL silent.
        # LightGBM gere les NaN naturellement (missing handling).
        # Si mq_call_0dte null pendant US RTH = MenthorQ pas update -> laisser
        # NaN honnete plutot que fallback HVL inverse signal.
        for mq_key, dist_key in (
            ("mq_call", "dist_mq_call_pct"),
            ("mq_call_0dte", "dist_mq_call_0dte_pct"),
            ("mq_put", "dist_mq_put_pct"),
            ("mq_put_0dte", "dist_mq_put_0dte_pct"),
            ("mq_hvl", "dist_mq_hvl_pct"),
            ("mq_hvl_0dte", "dist_mq_hvl_0dte_pct"),
            # NOTE : dist_mq_hvl_pct_z REMOVED (BUG #1 fix) - z-score rolling
            # non-trivial, IDEAS_BACKLOG. LOT 4 tolera l'absence.
        ):
            lvl = payload.get(mq_key)
            if lvl is not None:
                try:
                    lvl_f = float(lvl)
                    if not (lvl_f != lvl_f):  # not NaN
                        # BUG #2 fix : convention batch (level - close)/close*100
                        payload[dist_key] = (lvl_f - _close) / _close * 100
                except (TypeError, ValueError):
                    pass

        # Pass 4b : next_wall_dist_ticks (P3 audit dette #6, 15/05)
        # Distance en TICKS vers le nearest wall MQ depuis close.
        # Inputs : 6 niveaux MQ (call/put/hvl regular + 0dte) + close + tick.
        # Consume par rolling_features div_at_key_level_ticks proxy.
        # STATELESS - calcul O(1) par bar.
        try:
            from CORE.constants import get_tick_size as _gts
        except ImportError:
            from constants import get_tick_size as _gts
        symbol_pure_p3 = symbol.split(".")[0]
        tick_p3 = _gts(symbol_pure_p3)
        # Fix Jackson 15/05/2026 audit feature-engineer BUG #1 CRITIQUE :
        # Avant fix, le code cherchait keys `mq_call_resistance/put_support`
        # qui n'existent PAS dans le payload MQ_Lite (qui contient
        # `mq_call/mq_put/mq_hvl` + arrays `mq_gex[10]` + `mq_blind[10]`).
        # Resultat : seuls hvl + hvl_0dte trouves -> next_wall_dist_ticks
        # SUR-ESTIMEE ~7x sur 100% des bars. Bot 3 decisions sur cette
        # feature = data sale (lessons C++ DMP delta_div 0 26j).
        mq_walls = []
        # Scalaires : mq_call/put/hvl + 0DTE variants
        for mq_key in (
            "mq_call", "mq_call_0dte",
            "mq_put", "mq_put_0dte",
            "mq_hvl", "mq_hvl_0dte",
        ):
            lvl = payload.get(mq_key)
            if lvl is not None:
                try:
                    lvl_f = float(lvl)
                    if not (lvl_f != lvl_f):  # not NaN
                        mq_walls.append(lvl_f)
                except (TypeError, ValueError):
                    pass
        # Arrays : mq_gex[10] (gamma strikes) + mq_blind[10] (break levels)
        for mq_array_key in ("mq_gex", "mq_blind"):
            arr = payload.get(mq_array_key)
            if isinstance(arr, list):
                for lvl in arr:
                    if lvl is not None:
                        try:
                            lvl_f = float(lvl)
                            if not (lvl_f != lvl_f):
                                mq_walls.append(lvl_f)
                        except (TypeError, ValueError):
                            pass
        if mq_walls and tick_p3 > 0:
            # min distance en ticks vers nearest wall
            min_dist_ticks = min(abs(w - _close) / tick_p3 for w in mq_walls)
            payload["next_wall_dist_ticks"] = float(min_dist_ticks)
        else:
            payload["next_wall_dist_ticks"] = float("nan")

        # Pass 4 P6b : bool_gex_flip_zone = 1 - mq_gamma_condition
        # Audit feature-engineer 15/05 dette #6 - reconstruction DMP-C++.
        # mq_gamma_condition (menthorq_backfill_injector.py:148) :
        #   = 1 si net_gex > 0 (dealer long gamma = stabilisant)
        #   = 0 si net_gex <= 0 (dealer short gamma = volatile = flip zone)
        # bool_gex_flip_zone (rolling_features div_regime_proxy_ok consumer)
        # = inverse logique : 1 si flip (volatile), 0 si stable.
        # Resout `div_regime_proxy_ok` qui etait constante 0/1.
        gamma_cond = payload.get("mq_gamma_condition")
        if gamma_cond is not None:
            try:
                gc_int = int(gamma_cond)
                payload["bool_gex_flip_zone"] = 1 - gc_int
            except (TypeError, ValueError):
                payload["bool_gex_flip_zone"] = 0  # default stable
        else:
            payload["bool_gex_flip_zone"] = 0  # default stable si MQ absent

    # Inject VIX snapshot (passthrough Phase 3a) + appel engine streaming Jour 5
    # Plug factory pattern : state.get_engine_state("vix_lite", VixLiteState)
    # Validation convention API streaming (Plan agent reframe Jour 5).
    if inputs["vix"]:
        vix_row = dict(inputs["vix"])
        try:
            from vix_lite_reader import enrich_vix_lite_streaming, VixLiteState
            vix_state = state.get_engine_state("vix_lite", factory=VixLiteState)
            vix_enriched = enrich_vix_lite_streaming(vix_row, vix_state)
            # Merge dans payload (sans dupliquer ts_event/schema_version)
            for k, v in vix_enriched.items():
                if k not in ("ts_event", "schema_version"):
                    payload[k] = v
        except Exception as e:
            # Fallback passthrough si engine streaming echoue (fail-loud emit)
            logger.warning(f"vix_lite streaming fail {symbol}: {e}, fallback passthrough")
            for k, v in vix_row.items():
                if k not in ("ts_event", "schema_version"):
                    payload[k] = v

    # Inject trades stats minimales (Phase 3a passthrough)
    # FIX BUG #3 15/05/2026 : trades_df vient de read_trades_window aligne
    # sur la bar OHLCV [ts_event_ns, ts_event_ns+60s], pas une fenetre
    # rolling [now-60s, now]. Maintenant trades_window_n <= volume (parite
    # car volume bar = sum trades meme fenetre temporelle).
    # trades_window_aligned=1 pour audit : si jamais on revient a rolling
    # window, on peut le tracer.
    trades_df = inputs["trades_df"]
    payload["trades_window_n"] = len(trades_df)
    payload["trades_window_sec"] = 60
    payload["trades_window_aligned"] = 1  # aligne sur bar OHLCV start

    # ─── Fix code-reviewer Pass 3b R2 BLOQUANTS ───────────────────────────
    # B3 : inject `ts_event` (pd.Timestamp) - sessions_swings/rvol_inputs
    #      attend cette cle, cache OHLCV livre uniquement ts_event_iso/ns.
    # B2 : produire `delta_bar` depuis trades Databento (= sum signed_size).
    #      LOT 1 et 13+ rolling features ML lisent cette cle, le DMP C++
    #      la produisait. Aucun upstream Live Enricher ne la produit.
    #      Sans ce calcul : pattern V1 26 jours features mortes reproduit.
    import pandas as _pd  # local import (heavy module deja loaded)
    payload["ts_event"] = _pd.Timestamp(ts_event_ns, unit="ns", tz="UTC")
    # delta_bar = sum signed_size (A=BUY +size / B=SELL -size / N=ignore)
    # Fix B8 code-reviewer Round 3 : pd.notna() detecte NaN pandas
    # (not None ne suffit pas - NaN passe None check et propage en
    # float(NaN) = NaN -> cascade silent feature mortes).
    delta_bar_total = 0.0
    if not trades_df.empty and {"size", "side"}.issubset(trades_df.columns):
        for _trade in trades_df[["size", "side"]].itertuples(index=False):
            s = float(_trade.size) if _trade.size is not None and _pd.notna(_trade.size) else 0.0
            if _trade.side == "A":
                delta_bar_total += s
            elif _trade.side == "B":
                delta_bar_total -= s
    payload["delta_bar"] = delta_bar_total

    # ──────────────────────────────────────────────────────────────────────
    # Phase 3c semaine 4 : engines streaming (76 + 4 MGC + 10 ES/NQ = 90 max)
    # Ordre dependance critique (Pass 1 phase_b_plus_plus) :
    #   footprint_cells (helper pur)
    #   -> LOT 1 trades aggregates (produit delta_div_buy/sell, delta_bar)
    #   -> LOT 2 big_v2 (10 features VAP scan)
    #   -> LOT 3 cluster_v2 (5 features runs detection)
    #   -> LOT 4 absorb (produit near_resistance/support_level)
    #   -> LOT 5 trapped (consomme near_*, fail-loud anti Pattern 11)
    #   -> LOT 6 delta_div_ext (consomme delta_div_buy/sell de LOT 1)
    #
    # Pass 2 (cross-asset / cross-symbol) :
    #   -> gold_phase_d (MGC only, 4 features 6E/ZN/ZB) - hors lock target
    #   -> intermarket (ES/NQ partner, 10 features) - lit _states[partner]
    # ──────────────────────────────────────────────────────────────────────
    # FIX P0 code-reviewer post-fix #2 : checkpoint payload avant chain
    # pour eviter JSONL heterogene si crash mid-execution (LOT 1+2 ajoutees
    # avant fail LOT 3 -> payload partiel ecrit downstream).
    # Revert payload pre-chain en cas d'exception fail-soft.
    # Init meta variables (defined in except branch only if chain crashes)
    engine_name = None
    failed_lot = None
    phase_b_plus_plus_partial = False
    payload_pre_chain = dict(payload)
    try:
        from footprint_builder_streaming import build_footprint_cells_streaming
        from phase_b_plus_plus_trades_streaming import (
            add_phase_b_plus_plus_trades_streaming,
            make_phase_b_plus_plus_trades_state,
        )
        from phase_b_plus_plus_big_v2_streaming import (
            add_big_orders_v2_streaming,
            make_big_orders_v2_state,
        )
        from phase_b_plus_plus_cluster_v2_streaming import (
            add_cluster_v2_streaming,
            make_cluster_v2_state,
        )
        from phase_b_plus_plus_absorb_streaming import (
            add_stack_absorb_streaming,
            make_stack_absorb_state,
        )
        from phase_b_plus_plus_trapped_streaming import (
            add_trapped_traders_streaming,
            make_trapped_traders_state,
        )
        from phase_b_plus_plus_delta_div_ext_streaming import (
            add_delta_div_ext_streaming,
            make_delta_div_ext_state,
        )
        try:
            from CORE.constants import get_tick_size as _get_tick_size
        except ImportError:
            from constants import get_tick_size as _get_tick_size

        # symbol_pure : "ES.c.0" -> "ES", "MGC.v.0" -> "MGC"
        symbol_pure = symbol.split(".")[0]
        tick = _get_tick_size(symbol_pure)

        # 1. Build footprint cells (helper pur, sans state)
        #    Convert trades_df -> list[dict] (streaming attend list of dicts).
        #    Colonnes attendues : price, size, side ('A'/'B'/'N'), ts_event optionnel.
        #    Guard fix code-reviewer P0 : ts_event_ns OBLIGATOIRE pour assertion debug
        #    (sanity check tri ASC dans phase_b_plus_plus_trades_streaming). Sans
        #    ts_event_ns -> KeyError silently swallowed par try/except global.
        required_cols = {"price", "size", "side", "ts_event_ns"}
        if not trades_df.empty and required_cols.issubset(trades_df.columns):
            trades_records = trades_df[["price", "size", "side", "ts_event_ns"]].rename(
                columns={"ts_event_ns": "ts_event"}
            ).to_dict(orient="records")
        else:
            if not trades_df.empty:
                missing = required_cols - set(trades_df.columns)
                logger.warning(
                    f"trades_df {symbol} missing cols {missing} -> skip footprint engines"
                )
            trades_records = []

        cells = build_footprint_cells_streaming(trades_records, tick=tick)

        # FIX B1 review Phase 3c-B (18/05) : expose cells au state pour que
        # Phase 3c-B `_apply_phase_3c_B` puisse les passer a edge_zones_streaming.
        # Sans cette ligne, edge_zones recoit None -> 4 features edge mortes
        # silencieusement (pattern feature constante = pattern 11 V1 risque).
        # State per-bar (overwrite a chaque iteration, pas accumule).
        state.engine_states["footprint_cells_current_bar"] = cells

        # P0 REORDER : imports consolides AVANT LOT 1 pour permettre
        # Pass 4c-prereq + Pass 4a inseres entre LOT 1 et LOT 2.
        from phase_b_helpers import (
            add_rvol_inputs_streaming, RvolInputsState,
            add_session_metadata_streaming, SessionMetadataState,
            add_ib_features_streaming, IBState,
            add_session_high_low_streaming, SessionHighLowState,
            add_volume_profile_features_streaming, VolumeProfileState,
            add_open_cash_price1030_streaming, OpenCashPrice1030State,
        )
        from rvol_streaming import add_rvol_engine_streaming, RvolEngineState
        from phase_b_plus_streaming import (
            add_phase_b_plus_streaming, PhaseBPlusState, make_phase_b_plus_state,
        )
        from phase_b_rolling_inputs_streaming import (
            make_phase_b_rolling_inputs_state, apply_rolling_inputs_streaming,
        )
        from game_changers_streaming import (
            add_game_changers_streaming, GameChangersState,
        )
        try:
            from CORE.constants import get_session_boundaries as _get_bounds
        except ImportError:
            from constants import get_session_boundaries as _get_bounds

        # 2-7. Run engines streaming chain (state per engine via factory)
        #      Sous lock state (anti corruption deque concurrent mutation).
        with state.lock:
            # LOT 1 : trades aggregates (foundation, produit delta_div_buy/sell)
            s_trades = state.get_engine_state(
                "phase_b_plus_plus_trades",
                factory=lambda: make_phase_b_plus_plus_trades_state(symbol=symbol_pure),
            )
            payload = add_phase_b_plus_plus_trades_streaming(
                payload, s_trades, trades_in_window=trades_records,
            )

            # ──────────────────────────────────────────────────────────
            # P6c + P6d : proxies streaming pour features DMP-C++ NON-
            # reproductibles. Fix Review #4 NOGO : RENAME avec suffix
            # `_*_proxy` pour eviter collision semantique batch/stream
            # (batch consume DMP-C++ exact via V4 historique, stream produit
            # proxies differents -> drift ML drift garanti si meme nom).
            # Disponibles pour gates/rules engine uniquement, PAS dans
            # critical_keys ML training (cf IDEAS_BACKLOG dette HIGH).
            # P6c : OFI [-1, +1] = delta_bar / volume
            # P6d : ratio max single trade buy/sell
            #
            # Fix Jackson 15/05/2026 audit : avant fix, on lisait `total_vol`
            # qui est injecte par rvol_inputs PLUS TARD dans la chain ->
            # `total_vol`=0 -> diag_imbalance_ofi_proxy=0 CONSTANT (165
            # bars MGC = 0.0 detecte par validator CHECK3).
            # Fix : utiliser `volume` (ohlcv direct, deja dans payload
            # depuis init). volume == total_vol empiriquement (sum trades
            # = OHLCV volume sur memes bar).
            _delta_bar = payload.get("delta_bar", 0.0) or 0.0
            _volume = payload.get("volume", 0.0) or 0.0
            if _volume > 0:
                payload["diag_imbalance_ofi_proxy"] = float(_delta_bar) / float(_volume)
            else:
                payload["diag_imbalance_ofi_proxy"] = 0.0
            _max_buy = payload.get("max_size_buy", 0) or 0
            _max_sell = payload.get("max_size_sell", 0) or 0
            payload["large_trader_max_size_proxy"] = float(_max_buy) / max(float(_max_sell), 1.0)

            # ──────────────────────────────────────────────────────────
            # P0 REORDER (audit feature-engineer 15/05 dette #6) :
            # Pass 4c-prereq + Pass 4a integres ENTRE LOT 1 et LOT 2-6
            # car LOT 4 absorb consomme dist_mq_*_pct (P2 deja inject MQ
            # snapshot), ib_high/low, sess_high/low produits ici.
            # LOT 2-6 voient maintenant : vwap_d, sess_high/low, ib_*,
            # cur_vpoc/vah/val, atr, vwap_slope_10, cvd_day, etc.
            # ──────────────────────────────────────────────────────────

            # Pass 4c-prereq : 5 helpers (sess_metadata + ib + sess_hl + vp + phase_b_plus)
            # Bounds + trades_for_vp deja calcules par P0+P2 plus haut, recalcul ici local.
            _sym_bounds_p0 = _get_bounds(symbol_pure)
            _trades_for_vp_p0 = []
            if not trades_df.empty and {"price", "size"}.issubset(trades_df.columns):
                _trades_for_vp_p0 = trades_df[["price", "size"]].to_dict(orient="records")

            s_meta = state.get_engine_state("session_metadata", factory=SessionMetadataState)
            payload = add_session_metadata_streaming(payload, s_meta, bounds=_sym_bounds_p0)
            s_ib = state.get_engine_state("ib_features", factory=IBState)
            payload = add_ib_features_streaming(payload, s_ib, tick=tick, bounds=_sym_bounds_p0)
            s_sess_hl = state.get_engine_state("session_high_low", factory=SessionHighLowState)
            payload = add_session_high_low_streaming(payload, s_sess_hl, tick=tick)
            s_vp = state.get_engine_state("volume_profile", factory=VolumeProfileState)
            payload = add_volume_profile_features_streaming(
                payload, s_vp, trades_in_window=_trades_for_vp_p0, tick=tick,
            )
            # P1 FIX B1 (code-reviewer P1 NOGO Pattern V1 reproduit) :
            # add_open_cash_price1030 streaming AVANT game_changers.
            # Sans cette injection : open_cash/price_1030 = None -> classify
            # retourne UNKNOWN (0) constant -> 4/5 features mortes + cascade.
            s_open_cash = state.get_engine_state(
                "open_cash_price1030", factory=OpenCashPrice1030State,
            )
            payload = add_open_cash_price1030_streaming(
                payload, s_open_cash, bounds=_sym_bounds_p0,
            )
            s_bp = state.get_engine_state(
                "phase_b_plus", factory=lambda: make_phase_b_plus_state(symbol=symbol_pure),
            )
            payload = add_phase_b_plus_streaming(payload, s_bp, tick=tick)

            # Pass 4a : phase_b_rolling_inputs (6 sous-fonctions, 24 features)
            s_rolling_inputs_p0 = state.get_engine_state(
                "phase_b_rolling_inputs",
                factory=lambda: make_phase_b_rolling_inputs_state(symbol=symbol_pure),
            )
            payload = apply_rolling_inputs_streaming(payload, s_rolling_inputs_p0)

            # P1 : game_changers_streaming (5 features Market Profile)
            # Audit feature-engineer 15/05 dette #6 BUG #2 :
            # add_game_changers_streaming existe (CORE/) mais PAS integre live.
            # Produit : open_type, open_zone, day_type, open_direction,
            # open_bias_conf - dont open_direction/open_bias_conf consommes
            # par intermarket_streaming (im_cross_open_signal,
            # im_open_type_agreement) -> 5-7 features im_* mortes auparavant.
            # Top SHAP : open_type rank #2 (0.4334), day_type rank #4 (0.1109).
            # Inputs : open_cash, price_1030 (Pass 4c-prereq) + ib_high/low/atr
            # (Pass 4c-prereq + Pass 4a) + sess_high/low + prev_vah/val/vpoc +
            # pdh/pdl (Pass 4c-prereq vp) + date_et + mins_et (Pass 4c-prereq
            # sess_metadata) -- TOUS deja produits dans ordre P0 reorder.
            s_game_changers = state.get_engine_state(
                "game_changers",
                factory=GameChangersState,
            )
            payload = add_game_changers_streaming(
                payload, s_game_changers, symbol=symbol_pure,
            )

            # LOT 2 : big orders V2 (10 features VAP scan)
            s_big_v2 = state.get_engine_state(
                "phase_b_plus_plus_big_v2",
                factory=lambda: make_big_orders_v2_state(symbol=symbol_pure),
            )
            payload = add_big_orders_v2_streaming(payload, s_big_v2, footprint_cells=cells)

            # LOT 3 : cluster V2 (5 features runs detection)
            s_cluster_v2 = state.get_engine_state(
                "phase_b_plus_plus_cluster_v2",
                factory=lambda: make_cluster_v2_state(symbol=symbol_pure),
            )
            payload = add_cluster_v2_streaming(payload, s_cluster_v2, footprint_cells=cells)

            # LOT 4 : stack + absorption (produit near_resistance/support_level)
            s_absorb = state.get_engine_state(
                "phase_b_plus_plus_absorb",
                factory=lambda: make_stack_absorb_state(symbol=symbol_pure),
            )
            payload = add_stack_absorb_streaming(payload, s_absorb, footprint_cells=cells)

            # LOT 5 : trapped traders (consomme near_* de LOT 4, fail-loud check)
            s_trapped = state.get_engine_state(
                "phase_b_plus_plus_trapped",
                factory=lambda: make_trapped_traders_state(symbol=symbol_pure),
            )
            payload = add_trapped_traders_streaming(
                payload, s_trapped, footprint_cells=cells,
            )

            # LOT 6 : delta_div extension lines (consomme delta_div_buy/sell de LOT 1)
            s_delta_div = state.get_engine_state(
                "phase_b_plus_plus_delta_div_ext",
                factory=make_delta_div_ext_state,
            )
            payload = add_delta_div_ext_streaming(payload, s_delta_div)

        # ──────────────────────────────────────────────────────────────────
        # Pass 2 Phase 3c semaine 4 : gold_phase_d (MGC) + intermarket (ES/NQ)
        # Hors lock state principal pour eviter deadlock cross-symbol (gold
        # ne touche pas state target, intermarket lit _states[partner] sous
        # son propre lock).
        # ──────────────────────────────────────────────────────────────────

        # Gold Phase D : MGC-specific (4 features cross-asset 6E/ZN/ZB)
        # Pour autres symbols : skip (gold est MGC-only).
        # NOTE dette : closes 6E/ZN/ZB pas trackes dans SYMBOLS Live Enricher
        # actuel -> None passe -> features = NaN. Backfill V4 fournira via
        # parquets Databento. Cf IDEAS_BACKLOG entry "cross-asset MGC live".
        if symbol_pure == "MGC":
            from gold_phase_d_streaming import (
                add_gold_phase_d_streaming,
                GoldPhaseDState,
            )
            with state.lock:
                s_gold = state.get_engine_state(
                    "gold_phase_d",
                    factory=GoldPhaseDState,
                )
                payload = add_gold_phase_d_streaming(
                    payload, s_gold,
                    close_6e=None, close_zn=None, close_zb=None,
                )

        # Intermarket : ES <-> NQ cross-symbol (10 features)
        # Lire derniere bar partner depuis _states[partner]. NaN si absent.
        if symbol_pure in ("ES", "NQ"):
            from intermarket_streaming import (
                add_intermarket_streaming,
                IntermarketState,
            )

            partner_symbol = "NQ.c.0" if symbol_pure == "ES" else "ES.c.0"
            partner_bar = None
            partner_state = (
                partner_state_provider(partner_symbol) if partner_state_provider else None
            )
            if partner_state is not None:
                with partner_state.lock:
                    partner_bar = partner_state.last_bar()

            # Fix code-reviewer P1 #1+#2 : staleness check + no-future guard.
            # - Staleness : reject si partner bar > 120s old (Databento glitch)
            # - No-future : reject si partner_ts_ns > target_ts_ns (NQ deja
            #   process le cycle suivant) -> evite asymetrie temporelle
            #   lookahead artificielle.
            # En cas de reject : other_inputs=None -> features NaN + emit log.
            STALE_NS = 120 * 1_000_000_000  # 120s en ns
            if partner_bar is not None:
                partner_ts_ns = partner_bar.get("ts_event_ns", 0)
                if partner_ts_ns > ts_event_ns:
                    # Partner cycle plus recent que target -> reject (no future)
                    log_fn(
                        "ENRICHER_PARTNER_STALE", sym=symbol,
                        partner=partner_symbol,
                        reason="future",
                        delta_ns=int(partner_ts_ns - ts_event_ns),
                    )
                    partner_bar = None
                elif (ts_event_ns - partner_ts_ns) > STALE_NS:
                    # Partner trop ancien (> 2 min) -> reject (stale stream)
                    log_fn(
                        "ENRICHER_PARTNER_STALE", sym=symbol,
                        partner=partner_symbol,
                        reason="stale",
                        delta_ns=int(ts_event_ns - partner_ts_ns),
                    )
                    partner_bar = None

            # Build other_inputs dict pour intermarket streaming (None si
            # partner absent / stale / future -> features NaN).
            other_inputs = None
            if partner_bar is not None:
                other_inputs = {
                    "price": partner_bar.get("close"),
                    "delta_bar": partner_bar.get("delta_bar"),
                    "total_vol": partner_bar.get("volume"),
                    "delta_day": partner_bar.get("delta_day"),
                    "dist_sess_high": partner_bar.get("dist_sess_high"),
                    "dist_sess_low": partner_bar.get("dist_sess_low"),
                    "large_trader_ratio": partner_bar.get("large_trader_ratio"),
                    "open_bias_conf": partner_bar.get("open_bias_conf"),
                    "open_direction": partner_bar.get("open_direction"),
                    "open_type": partner_bar.get("open_type"),
                }

            # Fix code-reviewer P2 #5 : isoler price alias localement.
            # Le streaming intermarket attend `price` mais le payload final
            # ne doit pas avoir cette colonne dupliquee (bloat JSONL).
            # Build row_for_im local sans muter payload, puis merge uniquement
            # les features im_* dans payload final.
            row_for_im = dict(payload)
            if "price" not in row_for_im and "close" in row_for_im:
                row_for_im["price"] = row_for_im["close"]

            with state.lock:
                s_intermarket = state.get_engine_state(
                    "intermarket",
                    factory=IntermarketState,
                )
                enriched_im = add_intermarket_streaming(
                    row_for_im, s_intermarket, other_inputs=other_inputs,
                )
            # Merger uniquement features im_* dans payload final (pas price)
            for k, v in enriched_im.items():
                if k.startswith("im_"):
                    payload[k] = v

        # ──────────────────────────────────────────────────────────────────
        # Pass 3a Phase 3c semaine 4 : sessions_swings (55 features)
        # SIMPLE (38 features) puis LAG (17 features) - chain dependency :
        # LAG consomme session_id produit par SIMPLE.
        # Audit feature-engineer 14/05 : GREEN Prio 1 (trend_day_probability
        # et open_bias_conf famille = top SHAP).
        # ──────────────────────────────────────────────────────────────────
        from sessions_swings_simple_streaming import (
            add_sessions_swings_simple_streaming,
            make_sessions_swings_simple_state,
        )
        from sessions_swings_lag_streaming import (
            add_sessions_swings_lag_streaming,
            make_sessions_swings_lag_state,
        )

        with state.lock:
            # SIMPLE : produit session_id, is_in_*, opens, premium/discount, mins_et
            s_sess_simple = state.get_engine_state(
                "sessions_swings_simple",
                factory=lambda: make_sessions_swings_simple_state(symbol=symbol_pure),
            )
            payload = add_sessions_swings_simple_streaming(payload, s_sess_simple)

            # Fix Jackson 15/05/2026 audit BUG #5 : recalcul `session` enum
            # APRES sessions_swings_simple qui set is_in_asia/london/us_cash/us_after.
            # Avant fix : rolling_inputs (ligne 637) calculait session AVANT que
            # is_in_us_cash soit set -> session=-1 sur 100% bars us_cash, alors
            # que session_id=2 OK. Pattern V1 cousin (ordre execution silent).
            _is_asia = int(payload.get("is_in_asia", 0) or 0)
            _is_london = int(payload.get("is_in_london", 0) or 0)
            _is_us_cash = int(payload.get("is_in_us_cash", 0) or 0)
            _is_us_after = int(payload.get("is_in_us_after", 0) or 0)
            _sess_final = -1
            if _is_asia == 1:
                _sess_final = 0
            if _is_london == 1:
                _sess_final = 1
            if _is_us_cash == 1:
                _sess_final = 2
            if _is_us_after == 1:
                _sess_final = 3
            payload["session"] = _sess_final

            # P3 Phase 3 (15/05/2026) - 3 features simples DMP-cibles
            # Cible : combler lacunes audit feature-engineer (LIVE vs DMP)
            # P3.2 range_pos + P3.9 bar_body + avg_price (couverture C++)
            _h_p3 = payload.get("high")
            _l_p3 = payload.get("low")
            _c_p3 = payload.get("close")
            _o_p3 = payload.get("open")
            if _h_p3 is not None and _l_p3 is not None and _c_p3 is not None:
                try:
                    h_f = float(_h_p3); l_f = float(_l_p3); c_f = float(_c_p3)
                    rng = h_f - l_f
                    payload["range_pos"] = (c_f - l_f) / rng if rng > 0 else 0.5
                    # avg_price (mean OHLC) - couverture C++ DMP
                    if _o_p3 is not None:
                        try:
                            o_f = float(_o_p3)
                            payload["avg_price"] = (o_f + h_f + l_f + c_f) / 4
                            # bar_body : (close - open) en points + ticks
                            body = c_f - o_f
                            payload["bar_body_pct"] = (body / rng * 100) if rng > 0 else 0.0
                            try:
                                from CORE.constants import get_tick_size as _gts2
                            except ImportError:
                                from constants import get_tick_size as _gts2
                            _tick = _gts2(symbol_pure)
                            if _tick > 0:
                                payload["bar_body_ticks"] = body / _tick
                        except (TypeError, ValueError):
                            pass
                except (TypeError, ValueError):
                    pass

            # P3.1 atr_14m : multi-TF ATR. Notre `atr` deja sur 14 bars 1m
            # = 14 min ATR.
            # FIX BUG E units 15/05/2026 (audit externe + agent confirmation) :
            # `atr` payload (= phase_b_rolling_inputs_streaming.py:153) est
            # en TICKS (atr_points / tick). Mais batch v4
            # (build_dataset_v4_dmp_databento.py:791) calcule atr_14m en
            # POINTS directement (rolling TR sans /tick). Alias TICKS→POINTS
            # cassait la parite : live atr_14m_pct ~0.22% NQ vs batch ~0.04%
            # (skew 4x). Fix : multiplier par tick_size pour aligner POINTS.
            _atr_p3 = payload.get("atr")
            if _atr_p3 is not None:
                try:
                    from CORE.constants import get_tick_size as _gts_atr
                except ImportError:
                    from constants import get_tick_size as _gts_atr
                _tick_atr = _gts_atr(symbol_pure)
                try:
                    atr_ticks = float(_atr_p3)
                    atr_points = atr_ticks * _tick_atr
                    payload["atr_14m"] = atr_points  # POINTS (= batch)
                    if _c_p3 is not None:
                        c_f2 = float(_c_p3)
                        if c_f2 > 0:
                            payload["atr_14m_pct"] = atr_points / c_f2 * 100
                except (TypeError, ValueError):
                    pass

            # P3.5 REVERT 15/05/2026 (code-reviewer NOGO) : profile_shape/skew
            # approximations basees VPOC J-1 non-conformes standard DMP C++
            # (profile_shape=3 = B_DOUBLE PAS trend, seuils 0.70/0.30 pas
            # 0.66/0.33, manque skewness/volume_imbalance/bimodal VAP intra-day).
            # Risque : corruption RegimeGate Bot 1 (winner edge profile_shape=3).
            # Chantier separe necessite VAP intra-day stream + game_changers.classify_profile_shape().
            # Cf errata_audit_market_profile.md:86 (audit precedent rejet).

            # P3.4 V3 dist_vwap_w/m en TICKS (R3 fix code-reviewer 15/05) :
            # V1 emit POINTS (vwap_w - close), C++ DMP emit TICKS. Asymetrie
            # batch/stream. Fix V3 : (vwap - close) / tick_size = TICKS.
            if _c_p3 is not None:
                try:
                    c_v = float(_c_p3)
                    try:
                        from CORE.constants import get_tick_size as _gts_vw
                    except ImportError:
                        from constants import get_tick_size as _gts_vw
                    _tick_vw = _gts_vw(symbol_pure)
                    if _tick_vw > 0:
                        for vw_key, dist_key in (
                            ("vwap_w", "dist_vwap_w"),
                            ("vwap_m", "dist_vwap_m"),
                        ):
                            vw_val = payload.get(vw_key)
                            if vw_val is not None:
                                try:
                                    payload[dist_key] = (float(vw_val) - c_v) / _tick_vw
                                except (TypeError, ValueError):
                                    pass
                except (TypeError, ValueError):
                    pass

            # P4 V4 REFACTOR 15/05/2026 (audit externe + market-analyst) :
            # Convention BATCH v4 (phase_b_rolling_inputs.py:114) =
            #   (level - close) / tick_size / atr_ticks  SANS CLAMP
            # Verification empirique batch NQ avril 2026 dist_vwap_d_atr :
            #   mean=8.4, max=222 → batch NE CLAMPE PAS.
            # Versions precedentes V1/V2/V3 clampaient ±5 → train-serve skew
            # massif (70% des bars saturees, 12/17 features mortes).
            # V4 fix : retirer clamp pour parite batch bit-for-bit.
            # `atr_f` reste en TICKS (cohrent batch `atr` col, pas atr_14m).
            # NaN filter math.isfinite() preserve (V3 fix anti-faux-clamp).
            import math as _math_p4
            if _atr_p3 is not None and _c_p3 is not None:
                try:
                    atr_f = float(_atr_p3)
                    c_atr = float(_c_p3)
                    try:
                        from CORE.constants import get_tick_size as _gts_p4
                    except ImportError:
                        from constants import get_tick_size as _gts_p4
                    _tick_p4 = _gts_p4(symbol_pure)
                    if (atr_f > 0 and _tick_p4 > 0
                            and _math_p4.isfinite(atr_f)
                            and _math_p4.isfinite(c_atr)):
                        for lvl_key, dst in (
                            ("vwap_w", "dist_vwap_w_atr"),
                            ("vwap_m", "dist_vwap_m_atr"),
                            ("ib_high", "dist_ib_high_atr"),
                            ("ib_low", "dist_ib_low_atr"),
                            ("sess_high", "dist_sess_high_atr"),
                            ("sess_low", "dist_sess_low_atr"),
                            ("cur_vpoc", "dist_cur_vpoc_atr"),
                            ("cur_vah", "dist_cur_vah_atr"),
                            ("cur_val", "dist_cur_val_atr"),
                            ("prev_vpoc", "dist_prev_vpoc_atr"),
                            ("prev_vah", "dist_prev_vah_atr"),
                            ("prev_val", "dist_prev_val_atr"),
                            ("pdh", "dist_pdh_atr"),
                            ("pdl", "dist_pdl_atr"),
                            ("mq_call", "dist_mq_call_atr"),
                            ("mq_put", "dist_mq_put_atr"),
                            ("mq_hvl", "dist_mq_hvl_atr"),
                        ):
                            lvl = payload.get(lvl_key)
                            if lvl is None:
                                continue
                            try:
                                lvl_f = float(lvl)
                            except (TypeError, ValueError):
                                continue
                            if not _math_p4.isfinite(lvl_f):
                                continue
                            # V4 : SANS clamp (parite batch v4)
                            payload[dst] = (lvl_f - c_atr) / _tick_p4 / atr_f
                except (TypeError, ValueError):
                    pass

            # LAG : consomme session_id (produit par SIMPLE) -> swings + sweep
            s_sess_lag = state.get_engine_state(
                "sessions_swings_lag",
                factory=lambda: make_sessions_swings_lag_state(symbol=symbol_pure),
            )
            payload = add_sessions_swings_lag_streaming(payload, s_sess_lag)

            # P6a : retest_* streaming minimal (inline state via engine_states).
            # Audit feature-engineer 15/05 dette #6 - reconstruction DMP-C++.
            # Logique : retest_high quand high revient toucher last_swing_high
            # (tolerance 0.05% prix - symbole-aware). retest_high_delta_div =
            # retest + delta_div_sell (exhaustion bull). Symmetric pour retest_low.
            # Consume par rolling_features ctx_double_top_trap (line 1146-1157).
            # Fix Review #4 P6a R2 : warmup bar_idx >= 5 + tolerance pct (vs
            # 5 ticks fixe non-symbole-aware ES vs MGC).
            _retest_state = state.get_engine_state(
                "retest_tracker",
                factory=lambda: {
                    "last_retest_high_bar_idx": None,
                    "last_retest_low_bar_idx": None,
                    "bar_idx": 0,
                },
            )
            _retest_state["bar_idx"] += 1
            _bar_idx = _retest_state["bar_idx"]
            # Recuperer last_swing_*.price via state sessions_swings_lag
            _last_h = s_sess_lag.last_swing_high.price if s_sess_lag.last_swing_high else None
            _last_l = s_sess_lag.last_swing_low.price if s_sess_lag.last_swing_low else None
            _high_bar = payload.get("high")
            _low_bar = payload.get("low")
            _close_retest = payload.get("close")
            # Tolerance % prix (0.05% = 5 bps) - symbole-aware vs ticks fixes
            _tol_pct = 0.0005
            _tol_pts = (_close_retest * _tol_pct) if _close_retest else 0.0
            # Warmup minimum 5 bars (anti faux-positif cold start)
            _warmup_ok = _bar_idx >= 5
            # Detect retest high : high actuel >= last_swing_high - tolerance
            if _warmup_ok and _last_h is not None and _high_bar is not None and _high_bar >= _last_h - _tol_pts:
                _retest_state["last_retest_high_bar_idx"] = _bar_idx
            # Detect retest low : low actuel <= last_swing_low + tolerance
            if _warmup_ok and _last_l is not None and _low_bar is not None and _low_bar <= _last_l + _tol_pts:
                _retest_state["last_retest_low_bar_idx"] = _bar_idx
            # bars_since_retest
            if _retest_state["last_retest_high_bar_idx"] is not None:
                payload["bars_since_retest_high"] = _bar_idx - _retest_state["last_retest_high_bar_idx"]
            else:
                payload["bars_since_retest_high"] = 999  # never retested
            if _retest_state["last_retest_low_bar_idx"] is not None:
                payload["bars_since_retest_low"] = _bar_idx - _retest_state["last_retest_low_bar_idx"]
            else:
                payload["bars_since_retest_low"] = 999
            # retest_*_delta_div : retest detected this bar AND delta_div correspondant
            is_retest_h = payload["bars_since_retest_high"] == 0
            is_retest_l = payload["bars_since_retest_low"] == 0
            payload["retest_high_delta_div"] = 1 if (is_retest_h and payload.get("delta_div_sell", 0) == 1) else 0
            payload["retest_low_delta_div"] = 1 if (is_retest_l and payload.get("delta_div_buy", 0) == 1) else 0

        # ──────────────────────────────────────────────────────────────────
        # Pass 3c Phase 3c semaine 4 : rvol streaming (10 features)
        # Imports consolides plus haut (P0 reorder).
        # ──────────────────────────────────────────────────────────────────
        with state.lock:
            # 1. rvol_inputs : range_size, finish_strength, delta_pct (stateless)
            s_rvol_inputs = state.get_engine_state(
                "rvol_inputs",
                factory=RvolInputsState,
            )
            payload = add_rvol_inputs_streaming(payload, s_rvol_inputs, tick=tick)

            # 2. rvol_engine : 10 features rvol_* (rolling 20 vol)
            s_rvol = state.get_engine_state(
                "rvol_engine",
                factory=RvolEngineState,
            )
            payload = add_rvol_engine_streaming(payload, s_rvol)

        # Pass 4c-prereq + Pass 4a deja integres ENTRE LOT 1 et LOT 2-6
        # (P0 reorder 15/05). Anciens blocs ici supprimes.

        # ──────────────────────────────────────────────────────────────────
        # Pass 3b Phase 3c semaine 4 : rolling_features (45+ ctx_* features)
        # 5 sous-fonctions :
        #   - basic (13 features tier 1)
        #   - medium (tier 2)
        #   - advanced (tier 3)
        #   - delta_div (rolling div)
        #   - session_confluence
        # Inputs : price, delta_bar, total_vol (LOT 1) + vwap_slope_10/cvd_day
        # /va_position_pct (phase_b_plus, pas encore integre - features NaN
        # pour celles-la, par design tolerant batch ligne 88-92).
        # Audit feature-engineer 14/05 : GREEN Prio 1 (ib_extension_ratio,
        # poc_migration_10, va_developing_10 references SHAP historique).
        # ──────────────────────────────────────────────────────────────────
        from rolling_features_streaming import (
            add_rolling_features_basic_streaming,
            add_rolling_features_medium_streaming,
            add_rolling_features_advanced_streaming,
            add_rolling_features_delta_div_streaming,
            add_rolling_features_session_confluence_streaming,
            RollingFeaturesState,
        )

        with state.lock:
            s_rolling = state.get_engine_state(
                "rolling_features",
                factory=RollingFeaturesState,
            )
            # Fix code-reviewer Pass 3b P2 #2 : isoler aliases localement
            # pour eviter pollution payload final ('price' bloat).
            # Fix code-reviewer Pass 3b CRITIQUE #11 : injecter `ts` ms epoch
            # (rolling_features_streaming.add_rolling_features_delta_div_streaming
            # attend `ts` en MILLISECONDES, le payload a `ts_event_ns` en
            # NANOSECONDES). Sans cette conversion : delta_div_*_clean=0
            # constant + cascade biaisee (ctx_div_density_20, bars_since_div,
            # div_at_swing). Reference incident similaire 07/04/2026
            # delta_divergence toujours 0 (lessons.md).
            row_for_rolling = dict(payload)
            if "price" not in row_for_rolling and "close" in row_for_rolling:
                row_for_rolling["price"] = row_for_rolling["close"]
            # Fix code-reviewer Pass 3b concern 11 (3 alias):
            # - ts ms epoch (ns -> ms) pour _ts_to_trading_date_cme
            # - bar_high alias high (delta_div module attend bar_high)
            # - bar_low alias low
            row_for_rolling["ts"] = ts_event_ns / 1_000_000
            if "bar_high" not in row_for_rolling and "high" in row_for_rolling:
                row_for_rolling["bar_high"] = row_for_rolling["high"]
            if "bar_low" not in row_for_rolling and "low" in row_for_rolling:
                row_for_rolling["bar_low"] = row_for_rolling["low"]
            # Chain 5 sous-fonctions partageant le meme state rolling.
            # Warmup periods (concern P1 #4 code-reviewer Pass 3b) :
            #   - basic : ctx_vol_z_5/delta_sum_3 = 5/3 bars warmup
            #   - medium : ctx_va_developing_10 = 10 bars
            #   - advanced : ctx_excess_high_bars_60 = 60 bars (1h)
            #   - delta_div : ctx_div_density_20 = 20 bars
            #   - session_confluence : depend warmup downstream (60 max)
            # Premier ~60 bars du service : features rolling partiellement NaN.
            enriched_rolling = add_rolling_features_basic_streaming(row_for_rolling, s_rolling)
            enriched_rolling = add_rolling_features_medium_streaming(enriched_rolling, s_rolling)
            enriched_rolling = add_rolling_features_advanced_streaming(enriched_rolling, s_rolling)
            enriched_rolling = add_rolling_features_delta_div_streaming(enriched_rolling, s_rolling)
            enriched_rolling = add_rolling_features_session_confluence_streaming(enriched_rolling, s_rolling)
            # Fix code-reviewer Pass 3b R2 B1 : merge par DIFF de cles
            # au lieu de filter whitelist. Capture TOUTES les features
            # produites par les sub-engines rolling sans risquer de perdre
            # les nouvelles (e.g. div_at_key_level_ticks, div_confluence_*
            # qui ne matchent pas startswith("ctx_") ni "delta_div_").
            # Convention : tout ce qui est dans enriched_rolling et pas dans
            # row_for_rolling est une feature produite -> merge dans payload.
            produced_keys = set(enriched_rolling) - set(row_for_rolling)
            for k in produced_keys:
                payload[k] = enriched_rolling[k]
    except (ValueError, KeyError, TypeError, AttributeError, ImportError) as e:
        # Fail-soft restreint (code-reviewer P1) : whitelist exceptions
        # attendues (contract violation, dep manquante, type mismatch). Tout
        # autre Exception (RuntimeError, MemoryError, etc.) remontera pour
        # crash + nssm restart -- evite masquage bugs critiques.
        #
        # FIX P0 code-reviewer post-fix #2 : revert payload pre-chain pour
        # eviter JSONL heterogene (bars partielles si crash mid-execution).
        payload = payload_pre_chain
        phase_b_plus_plus_partial = True  # variable locale meta
        payload["phase_b_plus_plus_partial"] = True  # marker downstream filter
        #
        # Parse traceback pour identifier le LOT defaillant (LOT 1-6).
        # FIX P2 code-reviewer post-fix #2 : ordre INVERSE (LOT 6 -> LOT 1)
        # pour eviter mis-classification cascade. Un fail LOT 6 qui pass
        # par LOT 1 (rare mais possible) etait classifie LOT 1. L'ordre
        # inverse priorise le module le plus profond dans la chain.
        import traceback
        tb = traceback.format_exc()
        failed_lot = "unknown"
        for marker, lot_name in (
            # P1 marker
            ("game_changers_streaming", "game_changers"),
            # Pass 4a marker (deepest first - le plus profond)
            ("phase_b_rolling_inputs_streaming", "phase_b_rolling_inputs"),
            # Pass 4c-prereq markers
            ("phase_b_plus_streaming", "phase_b_plus"),
            # Fix code-reviewer Pass 4c-prereq #9 : marker phase_b_helpers
            # pour J+1 grep correct si crash session_metadata/ib_features/
            # session_high_low/volume_profile (tous dans phase_b_helpers.py).
            ("phase_b_helpers", "phase_b_helpers"),
            ("rolling_features_streaming", "rolling_features"),
            ("rvol_streaming", "rvol_engine"),
            ("sessions_swings_lag_streaming", "sessions_lag"),
            ("sessions_swings_simple_streaming", "sessions_simple"),
            ("intermarket_streaming", "intermarket"),
            ("gold_phase_d_streaming", "gold_phase_d"),
            ("phase_b_plus_plus_delta_div_ext_streaming", "LOT_6_delta_div_ext"),
            ("phase_b_plus_plus_trapped_streaming", "LOT_5_trapped"),
            ("phase_b_plus_plus_absorb_streaming", "LOT_4_absorb"),
            ("phase_b_plus_plus_cluster_v2_streaming", "LOT_3_cluster_v2"),
            ("phase_b_plus_plus_big_v2_streaming", "LOT_2_big_v2"),
            ("phase_b_plus_plus_trades_streaming", "LOT_1_trades"),
            ("footprint_builder_streaming", "footprint_cells"),
        ):
            if marker in tb:
                failed_lot = lot_name
                break
        # Fix code-reviewer Pass 2 P1 #3 : engine name dynamique pour J+1 grep.
        # Phase 3c contient 3 chaines :
        #   - phase_b_plus_plus_chain (LOT 1-6 + footprint)
        #   - cross_asset_chain (gold + intermarket)
        #   - sessions_swings_chain (Pass 3a sessions simple + lag)
        # Differencier dans le log pour audit.
        if failed_lot.startswith("LOT_") or failed_lot in ("footprint_cells", "unknown"):
            engine_name = "phase_b_plus_plus_chain"
        elif failed_lot.startswith("sessions_"):
            engine_name = "sessions_swings_chain"
        elif failed_lot.startswith("rvol_"):
            engine_name = "rvol_chain"
        elif failed_lot == "rolling_features":
            engine_name = "rolling_features_chain"
        elif failed_lot == "phase_b_plus":
            engine_name = "phase_b_plus_chain"
        elif failed_lot == "phase_b_helpers":
            engine_name = "phase_b_helpers_chain"
        elif failed_lot == "phase_b_rolling_inputs":
            engine_name = "phase_b_rolling_inputs_chain"
        elif failed_lot == "game_changers":
            engine_name = "game_changers_chain"
        else:
            engine_name = "cross_asset_chain"
        logger.warning(
            f"{engine_name} fail {symbol} at {failed_lot}: "
            f"{type(e).__name__}: {e} -- payload reverted to pre-chain"
        )
        log_fn(
            "ENRICHER_ENGINE_FAIL", sym=symbol,
            engine=engine_name,
            failed_lot=failed_lot,
            err_type=type(e).__name__,
            err=str(e)[:200],
        )

    # 5. Append bar to state buffer (rolling 60j) - FIX P0-2 sous lock
    with state.lock:
        state.append_bar(payload)

    # Audit externe 15/05/2026 recommandation : data_quality_flag pour
    # ETL/ML drop bars warmup_phase post-cold-restart.
    # FIX code-reviewer 15/05 (3 bugs critiques) :
    #   - bars_since_boot : utiliser state.n_bars_processed (pickle persiste)
    #     au lieu de _n_bars_processed dict module reset au boot process.
    #     Anti-faux-positifs HOT restart (state buffers pleins mais module reset).
    #   - bit 3 : sentinel swing_state vide = -1 (cf sessions_swings_lag_streaming
    #     L246/L259), pas 0 (= Asia legitime). Ancien check `== 0` =
    #     faux positifs systematiques bars Asia.
    #   - bit 4 : ny_open absent serialise en np.nan (cf sessions_swings_simple
    #     L262), converti None par writer APRES bitmask. `_ny is None`
    #     ne match jamais. math.isnan() ou pd.isna() requis.
    import math as _math_flag
    WARMUP_BARS_THRESHOLD = 30  # ~30 min apres cold start = state stable
    # state.n_bars_processed deja incremente par append_bar() ligne 1241.
    # Pickle-persiste donc HOT restart conserve la valeur reelle (buffers
    # pleins). _n_bars_processed dict reste pour tracking module mais
    # ne sert plus au bitmask.
    n_bars_sym = state.n_bars_processed
    payload["bars_since_boot"] = n_bars_sym
    # data_quality_flag bitmask (audit externe 15/05 + recommandations) :
    #   bit 0 (1)  : warmup_phase (n_bars_sym < threshold)
    #   bit 1 (2)  : sentinel detected (bars_since_retest == 999)
    #   bit 2 (4)  : sd_collapse (sd1u == sd1d)
    #   bit 3 (8)  : swing_state_reset (last_swing_high_session == -1
    #                = sentinel "swing state empty", AND n_bars_sym > 21).
    #                NB : session_id 0 = Asia legitime, pas un sentinel.
    #   bit 4 (16) : session_ctx_corrupted (apres reset US session,
    #                london_*/ny_open/asia_low perdus jusqu'au prochain
    #                rollover session). Detection : si en US (sid=2)
    #                ET ny_open NaN/None = corruption. NB : np.nan is not
    #                None == True, donc isnan() check obligatoire.
    #   bit 5 (32) : session_open_approximate (live restart mid-session,
    #                capture fallback sid au lieu de mins_et exact).
    #                Tracking pour parite batch/stream (cf bug #4).
    #   bit 6 (64) : ib_data_missing (ib_complete=1 mais ib_high=NaN).
    #                Live etait down pendant 09:30-10:30 ET ET seed V4
    #                a echoue. Bug #2 fix : seed V4 a chaque boot.
    flag = 0
    if n_bars_sym < WARMUP_BARS_THRESHOLD:
        flag |= 1
    _bsrh = payload.get("bars_since_retest_high")
    _bsrl = payload.get("bars_since_retest_low")
    if (_bsrh == 999 or _bsrl == 999) and n_bars_sym > 5:
        flag |= 2
    _sd1u = payload.get("vwap_d_sd1u")
    _sd1d = payload.get("vwap_d_sd1d")
    if _sd1u is not None and _sd1d is not None and _sd1u == _sd1d:
        flag |= 4
    _lshs = payload.get("last_swing_high_session")
    if _lshs == -1 and n_bars_sym > 21:
        flag |= 8
    # bit 4 : session_ctx_corrupted (US RTH actif mais ny_open NaN/None).
    _sid = payload.get("session_id")
    _ny = payload.get("ny_open")
    _ny_missing = (_ny is None) or (
        isinstance(_ny, float) and _math_flag.isnan(_ny)
    )
    if _sid == 2 and _ny_missing:
        flag |= 16
    # bit 5 (32) : session_open_approximate. Au moins 1 des opens
    # (asia/london/ny/after) a ete capture en fallback mid-session
    # (live restart > start_exact). Trace explicite pour ETL/ML drop
    # selectif. Si tous les *_open_approximate = 0 -> bit 5 = 0.
    # FIX BUG #4 15/05/2026 (code-reviewer GO-AVEC-RESERVES) :
    # preservation signal "boot mid-session" (precedemment bit 4 silent
    # masque par sid-fallback capture).
    if any(
        payload.get(f"{p}_open_approximate") == 1
        for p in ("asia", "london", "ny", "after")
    ):
        flag |= 32
    # bit 6 (64) : ib_data_missing. ib_complete=1 mais ib_high=NaN
    # (live down pendant fenetre IB 09:30-10:30 ET, seed V4 echec car
    # V4 batch Phase B incomplete jour J). FIX BUG #2 15/05 : seed IB
    # depuis V4 reduit ce flag. Si flag persiste -> V4 batch Phase B
    # retard ou bug pipeline upstream a investiguer.
    _ib_complete = payload.get("ib_complete")
    _ib_high = payload.get("ib_high")
    _ib_high_missing = (_ib_high is None) or (
        isinstance(_ib_high, float) and _math_flag.isnan(_ib_high)
    )
    if _ib_complete == 1 and _ib_high_missing:
        flag |= 64
    payload["data_quality_flag"] = flag

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 3c-A (18/05/2026 03:00 Paris) — 17 features (12 base + regime split 7)
    # ═══════════════════════════════════════════════════════════════════════
    try:
        _apply_phase_3c_A(payload, symbol, log_fn)
    except Exception as _e3c:
        log_fn("PHASE_3C_A_FAIL",
               sym=symbol, exc_type=type(_e3c).__name__, exc_msg=str(_e3c)[:200])

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 3c-B (18/05/2026 03:30 Paris) — 8 features WIRE STREAMING
    # ═══════════════════════════════════════════════════════════════════════
    # Wire 2 engines streaming deja existants :
    #   - edge_zones_streaming.add_edge_zones_streaming() → 4 features
    #     (dist_edge_buy_nearest_pct, dist_edge_sell_nearest_pct,
    #      n_edge_buy_active, n_edge_sell_active) — Bot 2 V6 consume
    #   - phase_b_plus_color_streaming.add_phase_b_plus_color_streaming()
    #     → 4 features (dist_color_up_nearest_pct, dist_color_dn_nearest_pct,
    #     n_color_up_cluster_within_0_2pct, n_color_dn_cluster_within_0_2pct) — Bot 3 consume
    # FIX R1 review Phase B/C (18/05) : envelopper sous state.lock pour eviter
    # race condition snapshot pickle pendant mutation engine_states. Phase 3c-B
    # mute state.engine_states["edge_zones"], ["color_bars"]. Phase 3c-C mute
    # ["phase_3c_c"] (deque + counters). Sans lock, pickle.dump peut serializer
    # un deque mid-append (corruption invariant atr_sum == sum(atr_buffer)).
    try:
        with state.lock:
            _apply_phase_3c_B(payload, state, symbol, log_fn)
    except Exception as _e3cb:
        log_fn("PHASE_3C_B_FAIL",
               sym=symbol, exc_type=type(_e3cb).__name__, exc_msg=str(_e3cb)[:200])

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 3c-C (18/05/2026 04:00 Paris) — 7 features ROLLING streaming
    # ═══════════════════════════════════════════════════════════════════════
    # Port en streaming des features rolling V4 batch :
    #   1. atr_regime_zscore_60d   (rolling 60j ATR z-score, Lopez ch.5)
    #   2. dist_naked_poc_nearest_pct (naked POC tracker 7j J-1..J-7)
    #   3. is_roll_day             (instrument_id discontinuity flag session)
    #   4. days_since_roll         (bars_since_roll / 1380, NaN si jamais vu roll)
    #   5. roll_phase              (0=early 0-15j, 1=mid 15-45j, 2=late 45+j)
    #   6. cvd_5d_rolling_ffd      (FFD Lopez d=0.4 sur cvd_day)
    #   7. cur_va_n_buckets, cur_va_total_vol (diagnostics VAP running session)
    try:
        with state.lock:
            _apply_phase_3c_C(payload, state, symbol, log_fn)
    except Exception as _e3cc:
        log_fn("PHASE_3C_C_FAIL",
               sym=symbol, exc_type=type(_e3cc).__name__, exc_msg=str(_e3cc)[:200])

    # Log souverain (regle critical-tasks-review 01/05) : tout flag != 0 doit
    # etre tracable J+1 pour audit ETL/ML drop bars suspectes.
    # BUG #2 fix code-reviewer 2026-05-16 : ce log etait dans live_enricher.py
    # backup ligne 1373-1380 mais n'avait pas ete extrait dans enricher_chain.
    # Sans : J+1 grep ENRICHER_DATA_QUALITY_FLAG_SET = 0 hits -> audit casse.
    if flag != 0:
        log_fn(
            "ENRICHER_DATA_QUALITY_FLAG_SET",
            sym=symbol,
            flag=flag,
            n_bars=n_bars_sym,
            sid=_sid,
        )

    # ── META dict pour caller (instrumentation/logs/quality filter) ───────────
    meta = {
        "phase_b_plus_plus_partial": phase_b_plus_plus_partial,
        "failed_lot": failed_lot,
        "engine_name": engine_name,
        "data_quality_flag": flag,
        "bars_since_boot": n_bars_sym,
        "flag_emit_needed": flag != 0,
    }

    return payload, meta


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3c-A — 12 features TRIVIAL + FACILE (18/05/2026 03:00 Paris)
# ═══════════════════════════════════════════════════════════════════════════════
# Audit cross-bots 18/05 a identifie 27 features V4 consommees par Bot 2 V6 +
# Bot 3 mais absentes du live_enriched 433 cols. Phase A = 12 features dont les
# formules sont triviales (1 ligne depuis OHLCV + champs existants payload) ou
# l'appel direct a un module deja existant.
#
# Sources verifiees :
#   1. bar_upper_wick_pct       : build_dataset_v4_dmp_databento.py:809
#   2. bar_lower_wick_pct       : symetrique upper (formule miroir)
#   3. bar_no_trade             : build_dataset_v4_dmp_databento.py:1121
#   4. position_in_range        : build_dataset_v4_dmp_databento.py:836
#   5. dist_1d_max_ticks        : derive de mq_1d_max + close + tick_size
#   6. dist_1d_max_ticks_pct    : same / close * 100
#   7. dist_1d_min_ticks        : derive de mq_1d_min + close + tick_size
#   8. dist_1d_min_ticks_pct    : same / close * 100
#   9. sess_range_atr           : phase_b_v6_complete.py:171 (sess_range / atr)
#  10. delta_day                : alias cvd_day (deja present) OU formule
#  11. regime_mode              : regime_engine.compute_regime(bar).mode
#  12. regime_favor             : regime_engine.compute_regime(bar).favor
#
# Pattern : function pure (mutation in-place sur payload), exceptions caller-side.

def _apply_phase_3c_A(payload: dict, symbol: str, log_fn: Callable) -> None:
    """Applique 12 features Phase A au payload (mutation in-place).

    Args:
        payload : dict en cours de composition, contient OHLCV + MQ + VIX +
                  champs deja calcules (range_pos, atr_14m, cvd_day, etc.)
        symbol  : "ES.c.0" / "NQ.c.0" / "MGC.v.0" (pour log + tick_size)
        log_fn  : Callable pour emit warnings (TUI ou v2log selon caller)

    Mutations :
        Ajoute 12 cles dans payload. Aucune supprimee. Si une feature ne peut
        etre calculee (inputs manquants), valeur = None ou NaN (pas crash).
    """
    import math as _m

    # Helpers safe get
    def _f(key, default=None):
        v = payload.get(key)
        if v is None:
            return default
        try:
            f = float(v)
            return f if not _m.isnan(f) else default
        except (TypeError, ValueError):
            return default

    # Tick size (constant lookup)
    try:
        from CORE.constants import get_tick_size
    except ImportError:
        from constants import get_tick_size
    # symbol = "ES.c.0" / "NQ.c.0" / "MGC.v.0" — extract base
    sym_base = symbol.split(".")[0] if symbol else "ES"
    tick_size = get_tick_size(sym_base)

    o = _f("open")
    h = _f("high")
    l = _f("low")
    c = _f("close")

    # ──────────────────── 1. bar_upper_wick_pct ────────────────────────────
    # Source : build_dataset_v4_dmp_databento.py:809
    # df["bar_upper_wick_pct"] = ((df["high"] - df[["open","close"]].max(axis=1)) / df["close"] * 100).clip(0, 3)
    if h is not None and o is not None and c is not None and c > 0:
        upper_wick = (h - max(o, c)) / c * 100
        payload["bar_upper_wick_pct"] = max(0.0, min(3.0, upper_wick))
    else:
        payload["bar_upper_wick_pct"] = None

    # ──────────────────── 2. bar_lower_wick_pct ────────────────────────────
    # Symetrique upper : (min(open, close) - low) / close * 100
    if l is not None and o is not None and c is not None and c > 0:
        lower_wick = (min(o, c) - l) / c * 100
        payload["bar_lower_wick_pct"] = max(0.0, min(3.0, lower_wick))
    else:
        payload["bar_lower_wick_pct"] = None

    # ──────────────────── 3. bar_no_trade ──────────────────────────────────
    # Source : build_dataset_v4_dmp_databento.py:1121
    # df["bar_no_trade"] = df["delta_bar"].isna().astype(int)
    delta_bar = payload.get("delta_bar")
    payload["bar_no_trade"] = 1 if delta_bar is None or (
        isinstance(delta_bar, float) and _m.isnan(delta_bar)
    ) else 0

    # ──────────────────── 4. position_in_range (FIX B1 review 18/05) ──────
    # Source : build_dataset_v4_dmp_databento.py:836 — position dans le range
    # JOURNALIER MQ (mq_1d_max - mq_1d_min), PAS la bar 1min !
    # Formule equivalente : (close - mq_1d_min) / (mq_1d_max - mq_1d_min) clip [0,1]
    # NE PAS utiliser range_pos/100 (= bar 1min, semantique fausse :
    # Bot 3 seuil position_in_range_above=0.70 jamais atteint).
    # Consommateur : bot3_level_definitions.py:209 + bot3_gold_decision_engine.
    mq_1d_min_v = _f("mq_1d_min")
    mq_1d_max_v = _f("mq_1d_max")
    if (mq_1d_min_v is not None and mq_1d_max_v is not None
            and c is not None and mq_1d_max_v > mq_1d_min_v):
        payload["position_in_range"] = max(
            0.0, min(1.0, (c - mq_1d_min_v) / (mq_1d_max_v - mq_1d_min_v))
        )
    else:
        payload["position_in_range"] = None

    # ──────────────────── 5-6. dist_1d_max_ticks(_pct) ─────────────────────
    # Formule : (mq_1d_max - close) / tick (ticks signed) + /close*100 (pct)
    if mq_1d_max_v is not None and c is not None and c > 0 and tick_size > 0:
        dist_max_ticks = (mq_1d_max_v - c) / tick_size
        payload["dist_1d_max_ticks"] = round(dist_max_ticks, 1)
        payload["dist_1d_max_ticks_pct"] = round((mq_1d_max_v - c) / c * 100, 6)
    else:
        payload["dist_1d_max_ticks"] = None
        payload["dist_1d_max_ticks_pct"] = None

    # ──────────────────── 7-8. dist_1d_min_ticks(_pct) ─────────────────────
    if mq_1d_min_v is not None and c is not None and c > 0 and tick_size > 0:
        dist_min_ticks = (mq_1d_min_v - c) / tick_size
        payload["dist_1d_min_ticks"] = round(dist_min_ticks, 1)
        payload["dist_1d_min_ticks_pct"] = round((mq_1d_min_v - c) / c * 100, 6)
    else:
        payload["dist_1d_min_ticks"] = None
        payload["dist_1d_min_ticks_pct"] = None

    # ──────────────────── 9. sess_range_atr (FIX B2+B3 review 18/05) ──────
    # Source : phase_b_v6_complete.py:96-171 utilise ATR DAILY WILDER (14j),
    # PAS atr_14m (ATR 14 barres 1min ~6 ticks NQ).
    # Convention DMP (cf DMP_Transform.h:72-73) :
    #   - "atr"     = ATR daily Wilder en POINTS (ex NQ snapshot 24.93)
    #   - "atr_14m" = ATR 14 barres 1min en TICKS (~6 ticks NQ snapshot)
    # Mixer les 2 via fallback = pollue units. ATR daily POINTS only.
    # Convertit en ticks (sess_range_ticks / atr_daily_ticks).
    # Empirique 15/05 NQ : sess_range=1503t / atr_daily=99.7t ≈ 15 (vs 241 bug).
    # Consommateur : bias_calculator_v6.py:396-401 seuil "1.3x ATR".
    sess_high = _f("sess_high")
    sess_low = _f("sess_low")
    atr_daily_points = _f("atr")
    if (sess_high is not None and sess_low is not None
            and atr_daily_points and atr_daily_points > 0 and tick_size > 0):
        sess_range_ticks = (sess_high - sess_low) / tick_size
        atr_daily_ticks = atr_daily_points / tick_size
        payload["sess_range_atr"] = round(sess_range_ticks / atr_daily_ticks, 4)
    else:
        payload["sess_range_atr"] = None

    # ──────────────────── 10. delta_day (FIX M1 review 18/05) ─────────────
    # Toujours ecrire (None safe) pour respecter contrat "12 features ajoutees".
    # Bot 2 V6 (bias_calculator_v6, regime_engine_v6) lit delta_day = alias cvd_day.
    payload["delta_day"] = payload.get("cvd_day")

    # ──────────────────── 10b. session_segment (Phase 1.5 18/05) ──────────
    # Port live equivalent CORE/phase_b_option_c_plus.py:113 add_session_segment.
    # Categoriel 0/1/2/3 :
    #   0 : pre-RTH (hors 09:30-16:00 ET)
    #   1 : RTH early (09:30-11:00 ET, mins_et ∈ [570, 660))
    #   2 : RTH mid (11:00-14:00 ET, mins_et ∈ [660, 840))
    #   3 : RTH late (14:00-16:00 ET, mins_et ∈ [840, 960))
    # Consume par NSM Phase 1 transitions session-aware + Bot 3 v2 context.
    _mins_et = payload.get("mins_et")
    if _mins_et is not None:
        try:
            _me = int(_mins_et)
            if _me < 570 or _me >= 960:
                payload["session_segment"] = 0
            elif _me < 660:
                payload["session_segment"] = 1
            elif _me < 840:
                payload["session_segment"] = 2
            else:
                payload["session_segment"] = 3
        except (TypeError, ValueError):
            payload["session_segment"] = 0
    else:
        payload["session_segment"] = 0

    # ──────────────────── 10c. cvd_session (Phase 1.5 18/05) ──────────────
    # Re-expose ctx_cvd_session (existant dans payload via ctx_*) sous le nom
    # canonical `cvd_session` (consume par NSM + bot3_context_analyzer:95).
    # En batch V4 : cvd_session = cumsum(delta_bar) per session_id chicago.
    # En streaming : ctx_cvd_session deja calcule par ctx engines, juste alias.
    _cvd_sess = payload.get("ctx_cvd_session")
    if _cvd_sess is not None:
        payload["cvd_session"] = _cvd_sess
    else:
        # Fallback : si ctx_cvd_session manque, utiliser cvd_day (proche, session_id != session_date_trading mais accept dégradation)
        payload["cvd_session"] = payload.get("cvd_day")

    # ──────────────────── 11-17. regime_* (FIX M3 review 18/05 : 7 cles) ──
    # Batch produit 7 cles regime_* via compute_regime() (regime_engine.py).
    # Phase 3c-A doit livrer toutes les 7 pour respecter contract V4 :
    #   regime_mode, regime_favor, regime_confidence, regime_trend_votes,
    #   regime_range_votes, regime_vol, regime_actionable
    try:
        from CORE.regime_engine import compute_regime
    except ImportError:
        try:
            from regime_engine import compute_regime
        except ImportError:
            compute_regime = None
    _regime_keys = ("regime_mode", "regime_favor", "regime_confidence",
                    "regime_trend_votes", "regime_range_votes",
                    "regime_vol", "regime_actionable")
    if compute_regime is not None:
        try:
            rr = compute_regime(payload)
            payload["regime_mode"] = getattr(rr, "mode", None)
            payload["regime_favor"] = getattr(rr, "favor", None)
            payload["regime_confidence"] = getattr(rr, "confidence", None)
            payload["regime_trend_votes"] = getattr(rr, "trend_votes", None)
            payload["regime_range_votes"] = getattr(rr, "range_votes", None)
            payload["regime_vol"] = getattr(rr, "vol_regime", None)
            _is_act = getattr(rr, "is_actionable", 0)
            payload["regime_actionable"] = int(_is_act) if _is_act is not None else 0
        except Exception as _e_reg:
            for _k in _regime_keys:
                payload[_k] = None
            log_fn("PHASE_3C_A_REGIME_FAIL", sym=symbol,
                   exc_type=type(_e_reg).__name__, exc_msg=str(_e_reg)[:120])
    else:
        for _k in _regime_keys:
            payload[_k] = None


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3c-B — 8 features WIRE STREAMING (18/05/2026 03:30 Paris)
# ═══════════════════════════════════════════════════════════════════════════════
# Wire 2 engines streaming deja existants pour produire 8 features V4 manquantes :
#
#   1. CORE/edge_zones_streaming.py:add_edge_zones_streaming(row, state, footprint)
#      → 4 features Bot 2 V6 :
#         - dist_edge_buy_nearest_pct, dist_edge_sell_nearest_pct
#         - n_edge_buy_active, n_edge_sell_active
#      Convention : row dict OHLCV + footprint_cells optional. State persistant
#      via state.get_engine_state("edge_zones", EdgeZonesState).
#
#   2. CORE/phase_b_plus_color_streaming.py:add_phase_b_plus_color_streaming(row, state)
#      → 4 features Bot 3 (sur 12 produites par l'engine) :
#         - dist_color_up_nearest_pct, dist_color_dn_nearest_pct
#         - n_color_up_cluster_within_0_2pct, n_color_dn_cluster_within_0_2pct
#      LAG-1 convention : value emitted at bar T = computed for bar T-1.
#
# NOTE : cur_va_n_buckets + cur_va_total_vol (value_area_running) reportes
# Phase C (besoin DataFrame buffer, pas streaming row).

def _apply_phase_3c_B(payload: dict, state: "LiveEnricherState",
                       symbol: str, log_fn: Callable) -> None:
    """Applique 8 features Phase B via streaming engines existants.

    Args:
        payload : dict en cours de composition (mutation in-place)
        state   : LiveEnricherState pour engine_states persistents
        symbol  : "ES.c.0" / "NQ.c.0" / "MGC.v.0"
        log_fn  : Callable pour emit erreurs

    Mutations :
        Ajoute 8 cles. Si engine fail (import ou crash), valeurs = None safe.
    """
    sym_base = symbol.split(".")[0] if symbol else "ES"

    # ──────────────────── 1. edge_zones_streaming (4 features) ────────────
    # FIX B1 review : footprint_cells lu via .get() (pas factory pour eviter
    # creation empty dict). cells est ecrit dans state par compose_enriched_payload
    # juste apres build_footprint_cells_streaming (ligne ~374).
    # FIX M1 review : utiliser make_edge_zones_state(sym) factory officielle
    # qui calcule threshold_pct depuis EDGE_THRESHOLD_PCT[sym] (au lieu default 600).
    try:
        # FIX 18/05 post-deploy : VPS service tourne avec sys.path=CORE/, le
        # prefix `CORE.` casse ModuleNotFoundError. Pattern try/except cf
        # ligne 342-345 pour get_tick_size.
        try:
            from CORE.edge_zones_streaming import (
                add_edge_zones_streaming, make_edge_zones_state,
            )
        except ImportError:
            from edge_zones_streaming import (
                add_edge_zones_streaming, make_edge_zones_state,
            )

        def _edge_factory():
            return make_edge_zones_state(sym_base)

        edge_state = state.get_engine_state("edge_zones", _edge_factory)
        # B1 fix : lecture sans factory pour eviter overwrite avec empty dict.
        footprint_cells = state.engine_states.get(
            "footprint_cells_current_bar"
        ) or None
        edge_out = add_edge_zones_streaming(payload, edge_state, footprint_cells)
        for k in ("dist_edge_buy_nearest_pct", "dist_edge_sell_nearest_pct",
                  "n_edge_buy_active", "n_edge_sell_active"):
            if k in edge_out:
                payload[k] = edge_out[k]
    except Exception as _e_edge:
        for k in ("dist_edge_buy_nearest_pct", "dist_edge_sell_nearest_pct",
                  "n_edge_buy_active", "n_edge_sell_active"):
            payload.setdefault(k, None)
        log_fn("PHASE_3C_B_EDGE_FAIL", sym=symbol,
               exc_type=type(_e_edge).__name__, exc_msg=str(_e_edge)[:200])

    # ──────────────────── 2. phase_b_plus_color_streaming (4 features) ────
    # LAG-1 convention : color de bar T-1 emitted dans row T.
    # FIX M1 review : utiliser make_color_bar_state(sym) factory officielle
    # qui lit COLOR_THRESHOLD_TICKS[sym] et LONG_UPDN_THRESHOLD_TICKS[sym]
    # au lieu de hardcode (MGC tombait sur ES=12t = faux).
    # FIX M2 review : wire restreint aux 4 cles cibles (dist_color_*, n_*_cluster).
    # Les 8 autres features color (fwd1 LEAKY, long_*_pattern collision avec
    # phase_b_plus_long_streaming) NE SONT PAS propagees dans payload.
    try:
        # FIX 18/05 post-deploy : meme pattern que edge_zones (VPS sys.path)
        try:
            from CORE.phase_b_plus_color_streaming import (
                add_phase_b_plus_color_streaming, make_color_bar_state,
            )
        except ImportError:
            from phase_b_plus_color_streaming import (
                add_phase_b_plus_color_streaming, make_color_bar_state,
            )

        def _color_factory():
            return make_color_bar_state(sym_base)

        color_state = state.get_engine_state("color_bars", _color_factory)
        color_out = add_phase_b_plus_color_streaming(payload, color_state)
        # Wire UNIQUEMENT les 4 features cibles (anti-collision M2).
        # Drop : bn_color_*_fwd1 (LEAK ML), long_*_pattern (formule ES vs NQ collision).
        for k in ("dist_color_up_nearest_pct", "dist_color_dn_nearest_pct",
                  "n_color_up_cluster_within_0_2pct",
                  "n_color_dn_cluster_within_0_2pct"):
            if k in color_out:
                payload[k] = color_out[k]
    except Exception as _e_color:
        for k in ("dist_color_up_nearest_pct", "dist_color_dn_nearest_pct",
                  "n_color_up_cluster_within_0_2pct",
                  "n_color_dn_cluster_within_0_2pct"):
            payload.setdefault(k, None)
        log_fn("PHASE_3C_B_COLOR_FAIL", sym=symbol,
               exc_type=type(_e_color).__name__, exc_msg=str(_e_color)[:200])


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3c-C — 7 features ROLLING streaming (18/05/2026 04:00 Paris)
# ═══════════════════════════════════════════════════════════════════════════════
# Port batch -> streaming des features rolling restantes du V4 batch :
#
#   1. atr_regime_zscore_60d   : z-score ATR vs moyenne 60j (CORE/phase_b_option_c_plus.py:93)
#      Streaming : rolling buffer atr_1m + Welford online sum/sum_sq (window 60*1380 bars).
#      min_periods=10 jours = 13800 bars avant emission (sinon NaN).
#
#   2. dist_naked_poc_nearest_pct : naked POC J-1..J-7 (CORE/phase_d_dalton_levels.py:111)
#      Streaming : deque[(sess_date, prev_vpoc)] maxlen=7. Reset active_pocs a chaque
#      session change. Retire poc si bar.low <= poc <= bar.high (tolerance 4 ticks).
#
#   3. is_roll_day, 4. days_since_roll, 5. roll_phase
#      Streaming : detect instrument_id discontinuity + bar counter / 1380 -> phase.
#      is_roll_day = 1 a partir du bar du roll jusqu'a fin session (divergence batch
#      acceptee : batch retro-flagge tout le jour, streaming flagge from-roll-onwards).
#
#   6. cvd_5d_rolling_ffd : Fractional Diff Lopez d=0.4 sur cvd_day
#      Streaming : pre-compute weights une fois (~20-30 terms), ring buffer cvd_day,
#      FFD = dot(weights, window). NaN sur warm-up = len(weights).
#
#   7. cur_va_n_buckets + cur_va_total_vol : diagnostic VAP running
#      Streaming : lecture directe state.engine_states["volume_profile"].price_volume
#      (deja maintenu cumulativement par add_volume_profile_features_streaming).
#      n_buckets = len(price_volume), total_vol = sum(price_volume.values()).
#
# State stocke dans state.engine_states["phase_3c_c"] (dict pickle-safe).

# Constantes streaming
_ATR_Z_WINDOW_BARS = 60 * 1380   # 60 jours * 1380 bars CME 24h
_ATR_Z_MIN_PERIODS = 10 * 1380   # 10 jours warm-up minimum
_NAKED_POC_LOOKBACK_DAYS = 7
_NAKED_POC_TOLERANCE_TICKS = 4
_BARS_PER_TRADING_DAY = 1380
_ROLL_PHASE_EARLY_DAYS = 15
_ROLL_PHASE_MID_DAYS = 45
_FFD_D = 0.4
_FFD_THRESHOLD = 1e-4


def _compute_ffd_weights(d: float = _FFD_D, threshold: float = _FFD_THRESHOLD):
    """Pre-compute FFD weights Lopez AFML ch.5. Identique a build_dataset_v4_dmp_databento._fractional_diff."""
    import numpy as np
    weights = [1.0]
    k = 1
    while True:
        w_k = -weights[-1] * (d - k + 1) / k
        if abs(w_k) < threshold:
            break
        weights.append(w_k)
        k += 1
    return np.array(weights[::-1], dtype="float64")


def _init_phase_3c_c_state(symbol: str) -> dict:
    """Factory state Phase 3c-C. Pickle-safe (no deque cap, dict + list)."""
    from collections import deque
    import numpy as np
    return {
        # ATR z-score 60d (Welford online)
        "atr_buffer": deque(maxlen=_ATR_Z_WINDOW_BARS),
        "atr_sum": 0.0,
        "atr_sum_sq": 0.0,
        "consec_atr_none": 0,   # FIX #3 anti-pattern 11 V1 silent fallback
        # Naked POC
        "sess_pvpoc_history": deque(maxlen=_NAKED_POC_LOOKBACK_DAYS),  # [(sess_date, pvpoc)]
        "naked_pocs_active": [],   # [(price, age_days), ...] for current session
        "current_npoc_sess": None,
        "last_seen_prev_vpoc": None,
        # Roll detection
        "last_instrument_id": None,
        "bars_since_roll": None,   # None until first roll observed
        "current_roll_sess": None,
        "roll_today_flag": 0,
        # CVD 5d FFD
        "cvd_buffer": deque(maxlen=64),  # ample headroom for weights width
        "ffd_weights": _compute_ffd_weights(),
        "consec_cvd_none": 0,   # FIX #3 anti-pattern 11 V1 silent fallback
        "symbol": symbol,
    }


# FIX #3 seuil emit MAJEUR "stale" feature : 30 bars consec None ~30 minutes
_STALE_FEATURE_THRESHOLD_BARS = 30


def _apply_phase_3c_C(payload: dict, state: "LiveEnricherState",
                       symbol: str, log_fn: Callable) -> None:
    """Applique 7 features Phase C ROLLING streaming.

    Args:
        payload : dict en cours de composition (mutation in-place)
        state   : LiveEnricherState pour engine_states persistents
        symbol  : "ES.c.0" / "NQ.c.0" / "MGC.v.0"
        log_fn  : Callable pour emit erreurs (PHASE_3C_C_*_FAIL)

    Lit sur payload :
        atr, session_date_trading, prev_vpoc, high, low, close,
        instrument_id, cvd_day.

    Mutations payload (7 cles + 1 diagnostic) :
        atr_regime_zscore_60d, dist_naked_poc_nearest_pct,
        is_roll_day, days_since_roll, roll_phase,
        cvd_5d_rolling_ffd,
        cur_va_n_buckets, cur_va_total_vol.

    Fail-soft : chaque sous-bloc try/except independant, valeurs = None si crash.
    """
    import math
    import numpy as np
    import pandas as pd
    from collections import deque

    sym_base = symbol.split(".")[0] if symbol else "ES"
    try:
        from CORE.constants import get_tick_size as _get_tick_size_c
    except ImportError:
        try:
            from constants import get_tick_size as _get_tick_size_c
        except ImportError:
            def _get_tick_size_c(_s):
                return 0.25
    tick = _get_tick_size_c(sym_base)

    pc_state = state.get_engine_state(
        "phase_3c_c", factory=lambda: _init_phase_3c_c_state(sym_base),
    )

    sess_date = payload.get("session_date_trading")

    # ──────────────────── 1. atr_regime_zscore_60d ────────────────────────
    try:
        atr_v = payload.get("atr")
        if atr_v is not None and not (isinstance(atr_v, float) and math.isnan(atr_v)):
            # FIX #3 : reset compteur stale a la 1ere valeur valide vue
            pc_state["consec_atr_none"] = 0
            buf = pc_state["atr_buffer"]
            # Welford-style maintenance : si buffer full, soustraire la valeur
            # qui sera evictee. deque.maxlen evite croissance memoire infinie.
            if len(buf) == buf.maxlen:
                old = buf[0]
                pc_state["atr_sum"] -= old
                pc_state["atr_sum_sq"] -= old * old
            buf.append(float(atr_v))
            pc_state["atr_sum"] += float(atr_v)
            pc_state["atr_sum_sq"] += float(atr_v) * float(atr_v)
            n = len(buf)
            if n >= _ATR_Z_MIN_PERIODS:
                mean = pc_state["atr_sum"] / n
                var = pc_state["atr_sum_sq"] / n - mean * mean
                if var > 1e-12:
                    std = math.sqrt(var)
                    payload["atr_regime_zscore_60d"] = float(
                        (float(atr_v) - mean) / std
                    )
                else:
                    payload["atr_regime_zscore_60d"] = None
            else:
                payload["atr_regime_zscore_60d"] = None
        else:
            # FIX #3 anti-pattern 11 V1 silent fallback : tracer atr feed coupe.
            payload.setdefault("atr_regime_zscore_60d", None)
            pc_state["consec_atr_none"] += 1
            if pc_state["consec_atr_none"] == _STALE_FEATURE_THRESHOLD_BARS:
                log_fn("PHASE_3C_C_ATR_STALE", sym=symbol,
                       n_bars=pc_state["consec_atr_none"])
    except Exception as _e_atr_z:
        payload["atr_regime_zscore_60d"] = None
        log_fn("PHASE_3C_C_ATR_Z_FAIL", sym=symbol,
               exc_type=type(_e_atr_z).__name__, exc_msg=str(_e_atr_z)[:200])

    # ──────────────────── 2. dist_naked_poc_nearest_pct ───────────────────
    # Tracker : a chaque nouvelle session, push (prev_sess, prev_vpoc) en
    # history, reset active_pocs depuis history (last 7), retire ceux qui
    # touchent bar [low, high] (tolerance 4 ticks).
    try:
        prev_vpoc = payload.get("prev_vpoc")
        high = payload.get("high")
        low = payload.get("low")
        close = payload.get("close")

        # Detection bascule session : on a passe a une nouvelle session
        # ET l'ancienne session avait un prev_vpoc figé -> push history.
        if sess_date is not None and sess_date != pc_state["current_npoc_sess"]:
            # Push prev_vpoc figé de la session qui vient de finir.
            # NB : a la 1ere bar d'une nouvelle session, payload[prev_vpoc] est
            # deja le VPOC J-1 (compute par volume_profile_streaming au session boundary).
            # Donc on push (current_npoc_sess, last_seen_prev_vpoc) si non-None.
            old_sess = pc_state["current_npoc_sess"]
            old_pv = pc_state["last_seen_prev_vpoc"]
            if old_sess is not None and old_pv is not None:
                pc_state["sess_pvpoc_history"].append((old_sess, float(old_pv)))
            elif old_sess is not None:
                # FIX #5 review : tracer skip pour boot mi-session ou prev_vpoc=None
                log_fn("PHASE_3C_C_NPOC_SESS_SKIP", sym=symbol,
                       old_sess=str(old_sess), new_sess=str(sess_date),
                       reason="last_seen_prev_vpoc=None")
            # Rebuild active_pocs depuis history (J-1, J-2, ..., J-N)
            # age = index inverse (most-recent = age 1)
            hist = list(pc_state["sess_pvpoc_history"])
            actives = []
            for i, (sd, pv) in enumerate(reversed(hist)):
                age_days = i + 1
                actives.append([float(pv), age_days])
            pc_state["naked_pocs_active"] = actives
            pc_state["current_npoc_sess"] = sess_date

        # Track derniere valeur prev_vpoc vue pour la prochaine bascule
        if prev_vpoc is not None and not (
            isinstance(prev_vpoc, float) and math.isnan(prev_vpoc)
        ):
            pc_state["last_seen_prev_vpoc"] = float(prev_vpoc)

        # Retirer les POC retestes par la bar courante (low <= poc <= high)
        if (
            high is not None and low is not None
            and not (isinstance(high, float) and math.isnan(high))
            and not (isinstance(low, float) and math.isnan(low))
        ):
            tolerance = _NAKED_POC_TOLERANCE_TICKS * tick
            lo_b = float(low) - tolerance
            hi_b = float(high) + tolerance
            pc_state["naked_pocs_active"] = [
                p for p in pc_state["naked_pocs_active"]
                if not (lo_b <= p[0] <= hi_b)
            ]

        # Distance au plus proche actif (signed % du close)
        actives = pc_state["naked_pocs_active"]
        if (
            actives and close is not None and not pd.isna(close)
            and float(close) > 0
        ):
            cf = float(close)
            # Plus proche en valeur absolue
            d_signed = min((p[0] - cf for p in actives), key=lambda x: abs(x))
            payload["dist_naked_poc_nearest_pct"] = float(d_signed / cf * 100.0)
        else:
            payload["dist_naked_poc_nearest_pct"] = None
    except Exception as _e_npoc:
        payload["dist_naked_poc_nearest_pct"] = None
        log_fn("PHASE_3C_C_NPOC_FAIL", sym=symbol,
               exc_type=type(_e_npoc).__name__, exc_msg=str(_e_npoc)[:200])

    # ──────────────────── 3-5. roll detection ─────────────────────────────
    try:
        cur_iid = payload.get("instrument_id")
        # Reset roll_today_flag a chaque nouvelle session
        if sess_date is not None and sess_date != pc_state["current_roll_sess"]:
            pc_state["current_roll_sess"] = sess_date
            pc_state["roll_today_flag"] = 0

        # Detection discontinuite instrument_id
        last_iid = pc_state["last_instrument_id"]
        is_roll_now = (
            last_iid is not None and cur_iid is not None and cur_iid != last_iid
        )
        if is_roll_now:
            pc_state["bars_since_roll"] = 0
            pc_state["roll_today_flag"] = 1
        else:
            if pc_state["bars_since_roll"] is not None:
                pc_state["bars_since_roll"] += 1

        if cur_iid is not None:
            pc_state["last_instrument_id"] = cur_iid

        payload["is_roll_day"] = int(pc_state["roll_today_flag"])

        bsr = pc_state["bars_since_roll"]
        if bsr is None:
            payload["days_since_roll"] = None
            payload["roll_phase"] = None
        else:
            dsr = round(bsr / _BARS_PER_TRADING_DAY, 2)
            payload["days_since_roll"] = float(dsr)
            if dsr <= _ROLL_PHASE_EARLY_DAYS:
                payload["roll_phase"] = 0
            elif dsr <= _ROLL_PHASE_MID_DAYS:
                payload["roll_phase"] = 1
            else:
                payload["roll_phase"] = 2
    except Exception as _e_roll:
        payload["is_roll_day"] = 0
        payload["days_since_roll"] = None
        payload["roll_phase"] = None
        log_fn("PHASE_3C_C_ROLL_FAIL", sym=symbol,
               exc_type=type(_e_roll).__name__, exc_msg=str(_e_roll)[:200])

    # ──────────────────── 6. cvd_5d_rolling_ffd ───────────────────────────
    try:
        cvd_v = payload.get("cvd_day")
        weights = pc_state["ffd_weights"]
        width = len(weights)
        buf = pc_state["cvd_buffer"]
        # Resize maxlen on first run si plus grand que default 64
        if buf.maxlen is None or buf.maxlen < width:
            # deque.maxlen est read-only -> reconstruire
            new_buf = deque(buf, maxlen=max(width, 64))
            pc_state["cvd_buffer"] = new_buf
            buf = new_buf

        if cvd_v is not None and not (isinstance(cvd_v, float) and math.isnan(cvd_v)):
            buf.append(float(cvd_v))
            pc_state["consec_cvd_none"] = 0
        else:
            # Pad NaN-safe : si cvd_day manque, on stocke NaN -> window invalide
            buf.append(float("nan"))
            # FIX #3 anti-pattern 11 V1 silent fallback : tracer cvd feed coupe.
            pc_state["consec_cvd_none"] += 1
            if pc_state["consec_cvd_none"] == _STALE_FEATURE_THRESHOLD_BARS:
                log_fn("PHASE_3C_C_CVD_STALE", sym=symbol,
                       n_bars=pc_state["consec_cvd_none"])

        if len(buf) >= width:
            window = np.array(list(buf)[-width:], dtype="float64")
            if not np.isnan(window).any():
                payload["cvd_5d_rolling_ffd"] = float(np.dot(weights, window))
            else:
                payload["cvd_5d_rolling_ffd"] = None
        else:
            payload["cvd_5d_rolling_ffd"] = None
    except Exception as _e_ffd:
        payload["cvd_5d_rolling_ffd"] = None
        log_fn("PHASE_3C_C_FFD_FAIL", sym=symbol,
               exc_type=type(_e_ffd).__name__, exc_msg=str(_e_ffd)[:200])

    # ──────────────────── 7. cur_va_n_buckets, cur_va_total_vol ──────────
    # Lecture directe state.engine_states["volume_profile"].price_volume
    # deja maintenu par add_volume_profile_features_streaming (Pass 4c-prereq).
    try:
        vp_state = state.engine_states.get("volume_profile")
        if vp_state is not None and hasattr(vp_state, "price_volume"):
            pv = vp_state.price_volume or {}
            payload["cur_va_n_buckets"] = int(len(pv))
            payload["cur_va_total_vol"] = float(sum(pv.values())) if pv else 0.0
        else:
            payload["cur_va_n_buckets"] = 0
            payload["cur_va_total_vol"] = 0.0
    except Exception as _e_va:
        payload["cur_va_n_buckets"] = None
        payload["cur_va_total_vol"] = None
        log_fn("PHASE_3C_C_VA_FAIL", sym=symbol,
               exc_type=type(_e_va).__name__, exc_msg=str(_e_va)[:200])
