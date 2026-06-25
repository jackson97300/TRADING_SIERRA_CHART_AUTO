"""Bot 4 v2 calibration persistence — P(win) par (scenario, regime, instrument).

Stocke et restore les calibrations isotonic regression / Platt scaling
apprises sur les outcomes 30j+ shadow.

Pattern :
- Phase P6 (sem 9-12) : entraine `IsotonicRegression(heuristic_score → P(win))`
  par scenario, ecrit via `save_calibration()`.
- Phase P7+ (prod) : Bot 4 v2 charge calibrations via `load_calibration()` au
  boot et applique `predict_p_win()` au runtime pour sizing P(scenario_completion).

Garde-fous (spec section 7 + data-mining-trap.md) :
- INTERDIT save() si n_trades < N_MIN_TRADES (defaut 100, Lopez)
- INTERDIT load() si calibration plus ancienne que MAX_AGE_DAYS (defaut 30j)
- Metadata JSON traceable + model binaire joblib persiste

Anti-pattern v1 (refus refonte) :
- Pas de fallback silent : si calibration absente, raise ValueError explicit
- Pas de force=True sans log warning audit
- Path components sanitises (anti path traversal)
"""
from __future__ import annotations

import json
import pickle
import re
from dataclasses import dataclass, field
from dataclasses import FrozenInstanceError  # noqa: F401 (re-exported pour tests)
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot4_v2.observability.telemetry import get_logger

_LOG = get_logger(__name__)

# Garde-fous Lopez AFML ch.7 + memoire feedback_data_mining_trap
N_MIN_TRADES = 100
MAX_AGE_DAYS = 30


class CalibrationError(Exception):
    """Erreur metier calibration (sample trop petit, age trop grand, etc.)."""


@dataclass(frozen=True)
class CalibrationMetadata:
    """Metadata persistee JSON cote du model pickle."""

    scenario_name: str
    symbol: str  # NQ / ES / MGC
    regime: str  # CALM_RANGE / VOLATILE_RANGE / TREND_UP / TREND_DOWN / PANIC
    n_trades: int
    fit_ts: str  # ISO 8601 UTC
    pf: float
    wr: float
    sharpe: float
    dsr: float  # DSR Lopez
    method: str  # "isotonic" / "platt"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "symbol": self.symbol,
            "regime": self.regime,
            "n_trades": self.n_trades,
            "fit_ts": self.fit_ts,
            "pf": self.pf,
            "wr": self.wr,
            "sharpe": self.sharpe,
            "dsr": self.dsr,
            "method": self.method,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationMetadata:
        return cls(
            scenario_name=data["scenario_name"],
            symbol=data["symbol"],
            regime=data["regime"],
            n_trades=int(data["n_trades"]),
            fit_ts=data["fit_ts"],
            pf=float(data["pf"]),
            wr=float(data["wr"]),
            sharpe=float(data["sharpe"]),
            dsr=float(data["dsr"]),
            method=data["method"],
            notes=data.get("notes", ""),
        )


@dataclass
class Calibration:
    """Calibration loaded en memoire : metadata + model callable.

    Model attendu : objet exposant `.predict(score: float) -> float` (P(win)).
    Pour isotonic regression sklearn : `IsotonicRegression` instance.
    """

    metadata: CalibrationMetadata
    model: Any = field(repr=False)


# R3 review : sanitize composants path pour anti traversal
# Caractères autorisés : alphanumeric + underscore + dash. Pas de slash, dot,
# espace, ou autre. Bloque "../../etc/passwd" et compagnie.
_KEY_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_key_component(name: str, kind: str) -> None:
    """Verifie qu'un composant de cle (symbol/scenario/regime) est path-safe.

    Raises:
        CalibrationError : si caracteres interdits detectes
    """
    if not isinstance(name, str) or not _KEY_SAFE_PATTERN.match(name):
        raise CalibrationError(
            f"Invalid {kind}={name!r}: only [A-Za-z0-9_-] allowed (path safety)"
        )


def _key(symbol: str, scenario: str, regime: str) -> str:
    """Cle composite scenario, path-safe.

    Format : `{SYMBOL}_{scenario}_{regime}` (uppercase symbol, scenario tel quel).
    """
    _validate_key_component(symbol, "symbol")
    _validate_key_component(scenario, "scenario")
    _validate_key_component(regime, "regime")
    return f"{symbol.upper()}_{scenario}_{regime}"


def _meta_path(base_dir: Path, symbol: str, scenario: str, regime: str) -> Path:
    return base_dir / f"{_key(symbol, scenario, regime)}.json"


def _model_path(base_dir: Path, symbol: str, scenario: str, regime: str) -> Path:
    return base_dir / f"{_key(symbol, scenario, regime)}.pkl"


def save_calibration(
    base_dir: Path,
    metadata: CalibrationMetadata,
    model: Any,
    *,
    force: bool = False,
) -> tuple[Path, Path]:
    """Persiste une calibration sur disque (metadata JSON + model pickle).

    Args:
        base_dir : repertoire racine `cfg.calibration_models_dir`
        metadata : CalibrationMetadata Lopez-compliant
        model : objet calibration (ex: IsotonicRegression sklearn)
        force : True ignore le garde-fou N_MIN_TRADES (USAGE TESTS ONLY)

    Returns:
        (meta_path, model_path) chemins ecrits.

    Raises:
        CalibrationError : n_trades < N_MIN_TRADES et force=False
        OSError : repertoire non-writable
    """
    if metadata.n_trades < N_MIN_TRADES and not force:
        raise CalibrationError(
            f"save_calibration refused: n_trades={metadata.n_trades} "
            f"< N_MIN_TRADES={N_MIN_TRADES} (Lopez AFML ch.7 + data-mining-trap)"
        )
    # R1 review : log warning traçabilite audit si force=True bypass garde-fou
    if metadata.n_trades < N_MIN_TRADES and force:
        _LOG.warning(
            "save_calibration FORCE bypass: n_trades=%d < N_MIN_TRADES=%d "
            "(scenario=%s sym=%s regime=%s) -- TESTS ONLY",
            metadata.n_trades, N_MIN_TRADES,
            metadata.scenario_name, metadata.symbol, metadata.regime,
        )

    base_dir.mkdir(parents=True, exist_ok=True)
    meta_path = _meta_path(
        base_dir, metadata.symbol, metadata.scenario_name, metadata.regime
    )
    model_path = _model_path(
        base_dir, metadata.symbol, metadata.scenario_name, metadata.regime
    )

    meta_path.write_text(
        json.dumps(metadata.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    # Pickle model (joblib ferait pareil sans dependance externe ici)
    with model_path.open("wb") as f:
        pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)

    _LOG.info(
        "save_calibration: %s n_trades=%d dsr=%.3f pf=%.2f -> %s",
        _key(metadata.symbol, metadata.scenario_name, metadata.regime),
        metadata.n_trades,
        metadata.dsr,
        metadata.pf,
        meta_path.name,
    )
    return meta_path, model_path


def load_calibration(
    base_dir: Path,
    symbol: str,
    scenario: str,
    regime: str,
    *,
    max_age_days: int = MAX_AGE_DAYS,
) -> Calibration:
    """Charge une calibration depuis disque.

    Args:
        base_dir : repertoire racine `cfg.calibration_models_dir`
        symbol : NQ / ES / MGC
        scenario : nom scenario (ex "Bearish_Rejection")
        regime : nom regime (ex "CALM_RANGE")
        max_age_days : age max accepte avant CalibrationError

    Returns:
        Calibration(metadata, model) prete a `model.predict(score)`.

    Raises:
        CalibrationError : fichiers absents, JSON corrompu, age trop grand
        FileNotFoundError : meta_path ou model_path absent
    """
    meta_path = _meta_path(base_dir, symbol, scenario, regime)
    model_path = _model_path(base_dir, symbol, scenario, regime)

    if not meta_path.exists():
        raise FileNotFoundError(
            f"Calibration metadata absente: {meta_path} (scenario={scenario})"
        )
    if not model_path.exists():
        raise FileNotFoundError(
            f"Calibration model absent: {model_path} (scenario={scenario})"
        )

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise CalibrationError(f"Metadata JSON corrompu {meta_path}: {exc}") from exc

    try:
        metadata = CalibrationMetadata.from_dict(data)
    except (KeyError, ValueError, TypeError) as exc:
        raise CalibrationError(
            f"Metadata structure invalide {meta_path}: {exc}"
        ) from exc

    # Garde-fou age
    age_days = _age_days(metadata.fit_ts)
    # R4 review : age negatif = fit_ts dans le futur (clock skew VPS / corruption)
    if age_days < 0:
        raise CalibrationError(
            f"Calibration fit_ts in future (clock skew?): age={age_days:.1f}j "
            f"(fit_ts={metadata.fit_ts}). Investigate VPS clock."
        )
    if age_days > max_age_days:
        raise CalibrationError(
            f"Calibration stale: age={age_days:.1f}j > max={max_age_days}j "
            f"(scenario={scenario} sym={symbol} regime={regime}). "
            f"Re-fit obligatoire (data-mining-trap)."
        )

    try:
        with model_path.open("rb") as f:
            model = pickle.load(f)
    except (pickle.UnpicklingError, OSError, EOFError) as exc:
        raise CalibrationError(f"Model pickle corrompu {model_path}: {exc}") from exc

    _LOG.info(
        "load_calibration: %s age=%.1fj dsr=%.3f",
        _key(symbol, scenario, regime),
        age_days,
        metadata.dsr,
    )
    return Calibration(metadata=metadata, model=model)


def list_calibrations(base_dir: Path) -> list[CalibrationMetadata]:
    """Liste toutes les calibrations metadata presentes dans base_dir.

    Args:
        base_dir : repertoire racine

    Returns:
        Liste CalibrationMetadata triee par fit_ts descending (recent first).
        Liste vide si base_dir absent ou aucune calibration.
    """
    if not base_dir.exists():
        return []

    metadatas: list[CalibrationMetadata] = []
    for meta_path in base_dir.glob("*.json"):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            metadatas.append(CalibrationMetadata.from_dict(data))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, OSError) as exc:
            _LOG.warning(
                "list_calibrations: skip %s (corrupt or invalid): %s",
                meta_path.name,
                exc,
            )

    metadatas.sort(key=lambda m: m.fit_ts, reverse=True)
    return metadatas


def _age_days(fit_ts_iso: str) -> float:
    """Calcule age en jours depuis fit_ts ISO 8601 (UTC)."""
    fit_dt = datetime.fromisoformat(fit_ts_iso.replace("Z", "+00:00"))
    if fit_dt.tzinfo is None:
        fit_dt = fit_dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - fit_dt
    return delta.total_seconds() / 86400.0
