"""Bot 4 v2 entry point — `python -m bot4_v2.main` lance le bot.

Module NEW Phase P5.3.B (26/06/2026) — wiring complet bot4_v2 deploy paper.

Usage :
    # DRY-RUN (defaut, aucun ordre reel) :
    python -m bot4_v2.main --symbols NQ,ES --build-id sim5_dryrun

    # REPLAY sample JSONL historique (validation pipeline) :
    python -m bot4_v2.main --symbols NQ --replay DATA/live_enriched/sierra/NQ/20260624_NQ_sierra_enriched.jsonl --max-cycles 1000

    # PAPER Sim4 (vrai DTC, demande Jackson Q1-Q4 P5.4 confirmation) :
    python -m bot4_v2.main --symbols NQ,ES --trade-account Sim4 --no-dry-run

Architecture wiring :
    JSONLStream (tail-F OR replay)
      → BotMainLoop
        → context_builder.build(bar, sym) → ScenarioContext
        → DecisionRouter (registry + scenarios + dispatch)
        → PositionReconciler (force-close NAKED + stale + heartbeat)
        → DTCAdapter (dry_run par defaut, vrai DTC backlog P5.4)

SRP : ce module est pur WIRING. Pas de business logic.

EXCLU scope (backlog) :
- Vrai DTC backend Sierra Chart (necessite reuse BOT/dtc_connector + adapter)
- nssm service packaging (P5.4 Jackson Q1-Q4)
- Discord webhook alertes CRITIQUE (P5.4)
- Signal handler SIGINT/SIGTERM = deja dans BotMainLoop (R5.2 ULTRATHINK P5)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from bot4_v2.decision.decision_router import DecisionRouter, RouterSettings
from bot4_v2.decision.scenario_registry import ScenarioRegistry
from bot4_v2.decision.scenarios import (
    BearishRejectionDetector,
    SweepReclaimN1Detector,
)
from bot4_v2.execution.dtc_adapter import DTCAdapter, DTCSettings
from bot4_v2.execution.position_reconciler import (
    PositionReconciler,
    ReconcilerSettings,
)
from bot4_v2.main.bot_main_v2 import (
    BotMainLoop,
    BotMainSettings,
    JSONLStream,
    JSONLTailStream,
    StreamEnded,
)
from bot4_v2.main.context_builder import ContextBuilder
from bot4_v2.observability.telemetry import get_logger

_LOG = get_logger("bot4_v2.main")


# ============================================================
# REPLAY STREAM (sample JSONL historique)
# ============================================================


class ReplayStream:
    """Stream JSONL deterministe pour replay historique (E2E tests + validation).

    Lit fichier ligne-par-ligne, retourne bar dict via next_bar(). Raise
    StreamEnded a EOF (vs JSONLTailStream qui retourne None pour live perpetuel).
    """

    def __init__(self, path: Path, encoding: str = "utf-8"):
        self._path = Path(path)
        self._lines: Optional[list[str]] = None
        self._idx = 0

    def _load_lazy(self) -> None:
        if self._lines is None:
            with open(self._path, "r", encoding="utf-8") as f:
                self._lines = f.readlines()

    def next_bar(self) -> Optional[dict]:
        import json
        self._load_lazy()
        if self._idx >= len(self._lines):
            raise StreamEnded()
        line = self._lines[self._idx]
        self._idx += 1
        if not line.strip():
            return None
        try:
            bar = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None
        return bar if isinstance(bar, dict) else None

    @property
    def n_lines(self) -> int:
        self._load_lazy()
        return len(self._lines)


# ============================================================
# REGISTRY BOOTSTRAP
# ============================================================


def build_registry() -> ScenarioRegistry:
    """Construit registry avec les 2 detectors P3 batch 2 (Bearish + Sweep).

    Les 15 autres scenarios = backlog P6 (post-shadow data 30j).
    Pour Sim4 paper validation, 2 scenarios = suffisant pipeline test.
    """
    registry = ScenarioRegistry()
    registry.register(BearishRejectionDetector())
    registry.register(SweepReclaimN1Detector())
    return registry


# ============================================================
# CLI ENTRY POINT
# ============================================================


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI args.

    Symbols par defaut : NQ seul (config-extensible).
    Dry-run par defaut : TRUE (aucun ordre reel, pipeline validation).
    """
    parser = argparse.ArgumentParser(
        prog="bot4_v2.main",
        description="Bot 4 v2 entry point - paper Sim4 validation pipeline",
    )
    parser.add_argument(
        "--symbols",
        default="NQ",
        help="Symboles cibles (comma-separated). Defaut : NQ",
    )
    parser.add_argument(
        "--trade-account",
        default="Sim4",
        help="Compte DTC TradeAccount (defaut Sim4)",
    )
    parser.add_argument(
        "--build-id",
        default="bot4_v2_p5_3",
        help="Tag identifiant build pour logs",
    )
    parser.add_argument(
        "--max-cycles",
        type=int, default=0,
        help="Stop apres N bars (0 = infini). Defaut 0",
    )
    parser.add_argument(
        "--replay", default=None,
        help="Path JSONL replay (mode E2E test). Sinon tail-F live_enriched.",
    )
    parser.add_argument(
        "--live-enriched-dir",
        default="DATA/live_enriched/sierra",
        help="Repertoire racine live_enriched (mode tail-F)",
    )
    parser.add_argument(
        "--menthorq-dir",
        default="DATA/MENTHORQ",
        help="Repertoire JSON MenthorQ daily",
    )
    parser.add_argument(
        "--no-dry-run", action="store_true",
        help="Active vrai DTC connect + ordres (PAS DEFAUT pour safety).",
    )
    parser.add_argument(
        "--heartbeat-sec", type=float, default=30.0,
        help="Reconciler heartbeat interval seconds. Defaut 30",
    )
    parser.add_argument(
        "--max-concurrent", type=int, default=3,
        help="Max trades concurrent cross-symbol. Defaut 3",
    )
    return parser.parse_args(argv)


def build_loop(args: argparse.Namespace) -> BotMainLoop:
    """Wire up tous les composants depuis args. SRP wiring uniquement."""
    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())

    # P5.4.A wire : si --no-dry-run, construit SierraDTCBackend (heritage
    # BOT/dtc_connector validee production-grade). Sinon dry-run safe.
    if args.no_dry_run:
        backend = _build_sierra_backend(args)
        dtc_settings = DTCSettings(
            dry_run=False,
            trade_account=args.trade_account,
        )
    else:
        backend = _DryRunBackend()
        dtc_settings = DTCSettings(
            dry_run=True,
            trade_account=args.trade_account,
        )
    dtc = DTCAdapter(backend=backend, settings=dtc_settings)
    dtc.ensure_connected()

    # Registry + detectors
    registry = build_registry()
    router = DecisionRouter(
        registry=registry,
        dtc_adapter=dtc,
        settings=RouterSettings(
            max_concurrent_trades=args.max_concurrent,
            trade_account=args.trade_account,
        ),
    )

    # Reconciler
    reconciler = PositionReconciler(
        dtc_adapter=dtc,
        settings=ReconcilerSettings(
            heartbeat_interval_sec=args.heartbeat_sec,
        ),
    )

    # Context builder
    builder = ContextBuilder(menthorq_dir=Path(args.menthorq_dir))

    # Stream : replay OR tail-F live
    stream: JSONLStream
    if args.replay:
        stream = ReplayStream(Path(args.replay))
    else:
        # Live tail mode : 1 stream par symbole. Pour V1 simple, 1er symbole.
        # P6 backlog : multi-stream multiplexer (1 stream per symbol + merge).
        if len(symbols) > 1:
            _LOG.warning(
                "Live tail mode : multi-symbol pas supporte V1, on prend %s seul",
                symbols[0],
            )
        live_path = (
            Path(args.live_enriched_dir) / symbols[0]
            / f"{_today_str()}_{symbols[0]}_sierra_enriched.jsonl"
        )
        stream = JSONLTailStream(live_path)

    # Bot main loop settings
    bot_settings = BotMainSettings(
        symbols=symbols,
        heartbeat_interval_sec=args.heartbeat_sec,
        poll_idle_sec=1.0,
        max_cycles=args.max_cycles,
        build_id=args.build_id,
        catch_cycle_exceptions=False,  # R3 ULTRATHINK : fail-loud
        max_consecutive_exceptions=5,
        install_signal_handlers=True,
    )

    return BotMainLoop(
        router=router,
        reconciler=reconciler,
        stream=stream,
        context_builder=lambda bar, sym: builder.build(bar, sym),
        settings=bot_settings,
    )


# ============================================================
# SIERRA DTC BACKEND FACTORY (P5.4.A wire heritage BOT/dtc_connector)
# ============================================================


def _build_sierra_backend(args):
    """Construit SierraDTCBackend pour paper Sim4 reel.

    Lazy import BOT.dtc_connector + bot_config (anti import cycle tests).

    Raises:
        ImportError : si BOT/dtc_connector indisponible (deps manquantes)
        ConnectionError : si DTC connect echoue
    """
    # Lazy import heritage prod (anti import lourd pour tests dry-run)
    import sys
    from pathlib import Path
    bot_path = Path(__file__).resolve().parent.parent.parent / "BOT"
    if str(bot_path) not in sys.path:
        sys.path.insert(0, str(bot_path))

    try:
        from BOT.dtc_connector import DTCConnector  # noqa: F401
        from BOT.bot_config import DTCConfig  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            f"BOT/dtc_connector + bot_config requis pour --no-dry-run "
            f"(import fail : {exc})"
        )

    from bot4_v2.execution.dtc_backend_sierra import SierraDTCBackend

    # Override client_name pour eviter collision avec Bot 1/2/3 (cf bot_config.py:147)
    config = DTCConfig(client_name="MIA_Bot_4_V2")
    dtc_conn = DTCConnector(config)
    return SierraDTCBackend(dtc_conn)


# ============================================================
# DRY-RUN BACKEND (stub IDTCBackend Protocol)
# ============================================================


class _DryRunBackend:
    """Stub IDTCBackend pour dry_run. DTCAdapter retourne DRYRUN results
    avant d'appeler ce backend, donc les methodes ne sont jamais reellement
    invoquees. Mais doit implementer Protocol pour pass isinstance check.

    R5 ULTRATHINK : lifecycle _connected mutable pour respecter Protocol
    semantique (anti mensonge Protocol). Un backend reel passe par les states
    True (post connect) -> False (post disconnect) cycle.
    """

    def __init__(self):
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def send_market_with_stop_only(self, symbol, side, quantity, sl_price,
                                   trade_account, signal_ref_price=0.0):
        # Jamais appele en dry_run, mais retour safe
        return ("DRYRUN_PARENT", "DRYRUN_SL", signal_ref_price or 20000.0)

    def send_close_market(self, symbol, side, quantity, trade_account):
        return "DRYRUN_CLOSE"

    def cancel_order(self, client_order_id, server_order_id="", trade_account=None):
        return True


# ============================================================
# HELPERS
# ============================================================


def _today_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point. Returns exit code."""
    args = parse_args(argv)
    try:
        loop = build_loop(args)
    except NotImplementedError as exc:
        _LOG.error("build_loop NotImplementedError : %s", exc)
        print(f"ERROR : {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("build_loop fatal exc=%s", type(exc).__name__)
        print(f"FATAL : {exc}", file=sys.stderr)
        return 1

    try:
        loop.run()
    except KeyboardInterrupt:
        _LOG.warning("KeyboardInterrupt - graceful stop")
        loop.stop()
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("run fatal exc=%s", type(exc).__name__)
        return 1

    _LOG.info(
        "bot4_v2.main exit OK processed_bars=%d total_dispatches=%d",
        loop.processed_bars, loop.total_dispatches,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
