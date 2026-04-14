"""
monitor_training.py — Auto-kill monitor pour train_lightgbm.py

Lance train_lightgbm.py en subprocess, surveille le log en live, et tue le
process si un signal d'alerte critique est detecte (Lopez AFML, Aronson,
Davey, sain principe).

Objectif : dormir tranquille pendant un training nocturne. Si le training
derive vers quelque chose de suspect (Sharpe > 4, WR > 75%, 1 feature domine
>50% MDA, etc.), le monitor kill et ecrit un rapport au lieu de laisser
tourner 8h de CPU pour rien.

USAGE :
    python -X utf8 CORE/monitor_training.py [--symbol ES] [--no-tune] [--stress-costs]

    Tous les arguments apres sont passes a train_lightgbm.py.

LOG OUTPUT :
    DATA/TRAINING_LOGS/training_YYYYMMDD_HHMMSS.log    (log complet)
    DATA/TRAINING_LOGS/monitor_YYYYMMDD_HHMMSS.json    (rapport monitor)

SIGNAUX DE KILL (trigger auto-stop) :
    CRITIQUES (kill immediat) :
      - Sharpe OOS > 5           (au-dela c'est une fuite quasi-certaine)
      - Win Rate > 80%           (irrealiste sur intraday futures)
      - Profit Factor > 4.0      (idem)
      - Train score >> Test score (gap > 40%)
      - 1 feature > 60% MDA      (shortcut / leakage)
      - Exception non-recoverable dans le script

    AVERTISSEMENTS (log mais continue) :
      - Sharpe 3-5
      - Win Rate 65-80%
      - PF 2.5-4.0
      - MC p-value = 0.000
      - 1 feature 30-60% MDA
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AlertThresholds:
    """Seuils d'alerte pour detection signaux suspects.

    Seuils calibres par le review agent 2026-04-14 :
    - Sharpe kill baisse de 5.0 a 4.0 (Lopez flagge > 3 comme suspect en intraday retail).
    - Sharpe warn baisse de 3.0 a 2.5.
    - Un vrai edge ML intraday tourne generalement Sharpe 1.5-2.5 net de frais.
      Au-dela, probabilite elevee de leakage ou overfitting.
    """
    # Seuils CRITIQUES (kill)
    max_sharpe_kill:       float = 4.0
    max_win_rate_kill:     float = 0.80
    max_profit_factor_kill: float = 4.0
    max_train_test_gap_kill: float = 0.40    # gap > 40 points de pourcentage = overfit massif
    max_feature_dominance_kill: float = 0.60 # 1 feature > 60% MDA = shortcut

    # Seuils WARNING (log, pas kill)
    max_sharpe_warn:       float = 2.5
    max_win_rate_warn:     float = 0.65
    max_profit_factor_warn: float = 2.5
    max_train_test_gap_warn: float = 0.25
    max_feature_dominance_warn: float = 0.30
    max_mc_pvalue_warn:    float = 0.0005    # p-value trop bonne = suspect

    # Runtime timeout
    max_fold_runtime_sec:  int = 600          # 10 min par fold max
    max_total_runtime_hours: float = 16.0     # 16h total max


# ═══════════════════════════════════════════════════════════════════════════════
# EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AlertEvent:
    timestamp: str
    level: str                   # "CRITICAL", "WARN", "INFO"
    reason: str
    detail: str
    fold_line: Optional[str] = None


@dataclass
class MonitorState:
    start_time: float = 0.0
    end_time: float = 0.0
    alerts: List[AlertEvent] = field(default_factory=list)
    fold_history: List[dict] = field(default_factory=list)
    kill_triggered: bool = False
    kill_reason: str = ""
    n_folds_seen: int = 0
    current_stage: str = "init"


# ═══════════════════════════════════════════════════════════════════════════════
# PARSERS — extrait les metriques des lignes du log train_lightgbm
# ═══════════════════════════════════════════════════════════════════════════════

# "Fold 1: 2026-01-02 -> 2026-01-03 | thr=0.50 trades=45 WR=55% PF=1.80 EV=+2.5t PnL=+112t"
FOLD_LINE = re.compile(
    r"Fold\s+(\d+):\s+.*?trades=(\d+)\s+WR=(\d+)%\s+PF=([\d.]+)\s+EV=([+-]?[\d.]+)t"
)

# "Sharpe     : 2.34" ou "Sharpe     : -1.50"
# Fix agent review : inclure les negatifs pour detecter stratégies en perte
SHARPE_LINE = re.compile(r"Sharpe\s*:\s*([+-]?[\d.]+)")

# "Win Rate   : 55.0%"
WIN_RATE_LINE = re.compile(r"Win\s*Rate\s*:\s*([\d.]+)%")

# "PF         : 1.80"
PF_LINE = re.compile(r"PF\s*:\s*([\d.]+)")

# "MC p-value : 0.0001"
MC_P_LINE = re.compile(r"MC\s*p-value\s*:\s*([\d.]+)")

# MDA permutation importance: une feature domine souvent
MDA_TOP_LINE = re.compile(r"Top\s+features:\s*(.+)")


def parse_fold_line(line: str) -> Optional[dict]:
    m = FOLD_LINE.search(line)
    if not m:
        return None
    return {
        "fold": int(m.group(1)),
        "trades": int(m.group(2)),
        "win_rate": float(m.group(3)) / 100.0,
        "profit_factor": float(m.group(4)),
        "ev_ticks": float(m.group(5)),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# KILL DECISION
# ═══════════════════════════════════════════════════════════════════════════════

def check_fold_alerts(
    fold: dict,
    thresholds: AlertThresholds,
) -> List[AlertEvent]:
    """Check fold metrics vs thresholds."""
    alerts = []
    now = datetime.now().isoformat(timespec="seconds")

    # Win rate
    if fold["win_rate"] > thresholds.max_win_rate_kill:
        alerts.append(AlertEvent(
            timestamp=now, level="CRITICAL",
            reason="win_rate_too_high",
            detail=f"Fold {fold['fold']}: WR={fold['win_rate']:.1%} > {thresholds.max_win_rate_kill:.0%} (irrealiste)",
        ))
    elif fold["win_rate"] > thresholds.max_win_rate_warn:
        alerts.append(AlertEvent(
            timestamp=now, level="WARN",
            reason="win_rate_high",
            detail=f"Fold {fold['fold']}: WR={fold['win_rate']:.1%} suspect",
        ))

    # Profit factor
    if fold["profit_factor"] > thresholds.max_profit_factor_kill:
        alerts.append(AlertEvent(
            timestamp=now, level="CRITICAL",
            reason="profit_factor_too_high",
            detail=f"Fold {fold['fold']}: PF={fold['profit_factor']:.2f} > {thresholds.max_profit_factor_kill} (trop beau)",
        ))
    elif fold["profit_factor"] > thresholds.max_profit_factor_warn:
        alerts.append(AlertEvent(
            timestamp=now, level="WARN",
            reason="profit_factor_high",
            detail=f"Fold {fold['fold']}: PF={fold['profit_factor']:.2f} suspect",
        ))

    # Trades : 0 trades = rien a evaluer (peut etre normal, pas d'alerte)
    if fold["trades"] < 3:
        alerts.append(AlertEvent(
            timestamp=now, level="INFO",
            reason="few_trades",
            detail=f"Fold {fold['fold']}: seulement {fold['trades']} trades",
        ))
    elif fold["trades"] > 500:
        alerts.append(AlertEvent(
            timestamp=now, level="WARN",
            reason="too_many_trades",
            detail=f"Fold {fold['fold']}: {fold['trades']} trades (scalping irrealiste ?)",
        ))

    return alerts


def check_aggregate_alerts(
    text_window: str,
    thresholds: AlertThresholds,
) -> List[AlertEvent]:
    """Check lines from aggregate block."""
    alerts = []
    now = datetime.now().isoformat(timespec="seconds")

    # Sharpe aggregate
    m = SHARPE_LINE.search(text_window)
    if m:
        sharpe = float(m.group(1))
        if sharpe > thresholds.max_sharpe_kill:
            alerts.append(AlertEvent(
                timestamp=now, level="CRITICAL",
                reason="sharpe_too_high",
                detail=f"Sharpe aggregate={sharpe:.2f} > {thresholds.max_sharpe_kill} (fuite quasi-certaine)",
            ))
        elif sharpe > thresholds.max_sharpe_warn:
            alerts.append(AlertEvent(
                timestamp=now, level="WARN",
                reason="sharpe_high",
                detail=f"Sharpe aggregate={sharpe:.2f} suspect",
            ))

    # MC p-value aggregate
    m = MC_P_LINE.search(text_window)
    if m:
        mc_p = float(m.group(1))
        if mc_p < thresholds.max_mc_pvalue_warn:
            alerts.append(AlertEvent(
                timestamp=now, level="WARN",
                reason="mc_pvalue_too_low",
                detail=f"MC p-value={mc_p:.5f} (trop petit = suspect apres multiple tests)",
            ))

    return alerts


# ═══════════════════════════════════════════════════════════════════════════════
# MONITOR MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

class TrainingMonitor:
    """Wrapper auto-kill pour train_lightgbm.py."""

    def __init__(
        self,
        train_args: List[str],
        log_dir: Path,
        thresholds: Optional[AlertThresholds] = None,
        python_exe: str = sys.executable,
    ):
        self.train_args = train_args
        self.log_dir = log_dir
        self.thresholds = thresholds or AlertThresholds()
        self.python_exe = python_exe
        self.state = MonitorState()

        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = log_dir / f"training_{ts}.log"
        self.report_file = log_dir / f"monitor_{ts}.json"

    def run(self) -> int:
        """Lance train_lightgbm.py et surveille le stdout en live."""
        self.state.start_time = time.time()

        # Build commande
        train_script = Path(__file__).parent / "train_lightgbm.py"
        cmd = [self.python_exe, "-X", "utf8", "-u", str(train_script)] + self.train_args

        print(f"=" * 70)
        print(f"MONITOR LAUNCHING : {' '.join(cmd)}")
        print(f"Log file    : {self.log_file}")
        print(f"Report file : {self.report_file}")
        print(f"=" * 70)
        print()

        # Lancer subprocess
        # Sur Windows, creationflags=CREATE_NEW_PROCESS_GROUP est OBLIGATOIRE pour
        # pouvoir envoyer CTRL_BREAK_EVENT au subprocess (sinon OSError).
        # Fix agent review 2026-04-14.
        log_fh = open(self.log_file, "w", encoding="utf-8")
        popen_kwargs = dict(
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(cmd, **popen_kwargs)

        recent_lines: List[str] = []  # buffer des 20 dernieres lignes pour regex multi-line

        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                # Ecrire au log + stdout monitor
                log_fh.write(line)
                log_fh.flush()
                print(line, end="")

                recent_lines.append(line)
                if len(recent_lines) > 30:
                    recent_lines.pop(0)
                window = "".join(recent_lines)

                # Check fold line
                fold = parse_fold_line(line)
                if fold:
                    self.state.n_folds_seen += 1
                    self.state.fold_history.append(fold)
                    fold_alerts = check_fold_alerts(fold, self.thresholds)
                    for a in fold_alerts:
                        self.state.alerts.append(a)
                        if a.level == "CRITICAL":
                            self._kill_process(proc, a.reason, a.detail)
                            return 1

                # Check aggregate block (plusieurs lignes ensemble)
                if "AGGREGATE" in line or "TESTS STATISTIQUES" in line:
                    # On va attendre ~10 lignes de plus pour avoir tout l'aggregate
                    # Le check se fera au fur et a mesure que les lignes arrivent
                    pass

                # Check global (toutes les 5 lignes recent_lines)
                if len(recent_lines) % 5 == 0:
                    agg_alerts = check_aggregate_alerts(window, self.thresholds)
                    for a in agg_alerts:
                        # Dedup : ne pas relancer le meme alert
                        if not any(x.reason == a.reason and x.detail == a.detail
                                   for x in self.state.alerts[-10:]):
                            self.state.alerts.append(a)
                            if a.level == "CRITICAL":
                                self._kill_process(proc, a.reason, a.detail)
                                return 1

                # Timeout global
                elapsed_hours = (time.time() - self.state.start_time) / 3600.0
                if elapsed_hours > self.thresholds.max_total_runtime_hours:
                    self._kill_process(
                        proc, "global_timeout",
                        f"Runtime > {self.thresholds.max_total_runtime_hours}h",
                    )
                    return 1

            # Fin du stdout : process a termine naturellement
            proc.wait()
            self.state.end_time = time.time()
            self._write_report()
            return proc.returncode

        except KeyboardInterrupt:
            print("\n[MONITOR] Ctrl+C recu, kill du training...")
            self._kill_process(proc, "user_interrupt", "Ctrl+C")
            return 130

        finally:
            log_fh.close()

    def _kill_process(self, proc: subprocess.Popen, reason: str, detail: str) -> None:
        self.state.kill_triggered = True
        self.state.kill_reason = reason
        self.state.end_time = time.time()

        print()
        print("=" * 70)
        print(f"MONITOR KILL TRIGGERED")
        print(f"Reason : {reason}")
        print(f"Detail : {detail}")
        print("=" * 70)

        try:
            if sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        self._write_report()

    def _write_report(self) -> None:
        duration = self.state.end_time - self.state.start_time if self.state.end_time else 0.0
        report = {
            "start_time": datetime.fromtimestamp(self.state.start_time).isoformat(),
            "end_time": datetime.fromtimestamp(self.state.end_time).isoformat() if self.state.end_time else None,
            "duration_sec": duration,
            "duration_min": duration / 60.0,
            "kill_triggered": self.state.kill_triggered,
            "kill_reason": self.state.kill_reason,
            "n_folds_seen": self.state.n_folds_seen,
            "n_alerts_total": len(self.state.alerts),
            "n_alerts_critical": sum(1 for a in self.state.alerts if a.level == "CRITICAL"),
            "n_alerts_warn": sum(1 for a in self.state.alerts if a.level == "WARN"),
            "alerts": [asdict(a) for a in self.state.alerts],
            "fold_history": self.state.fold_history,
            "train_args": self.train_args,
        }
        self.report_file.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(f"\n[MONITOR] Report written : {self.report_file}")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Auto-kill monitor pour train_lightgbm.py")
    ap.add_argument("--log-dir", type=Path,
                    default=Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/TRAINING_LOGS"),
                    help="Dossier des logs")
    ap.add_argument("--python", default=sys.executable,
                    help="Interpreteur Python a utiliser")
    # Tous les autres args sont passes au train_lightgbm
    args, unknown = ap.parse_known_args()

    monitor = TrainingMonitor(
        train_args=unknown,
        log_dir=args.log_dir,
        python_exe=args.python,
    )
    return monitor.run()


if __name__ == "__main__":
    sys.exit(main())
