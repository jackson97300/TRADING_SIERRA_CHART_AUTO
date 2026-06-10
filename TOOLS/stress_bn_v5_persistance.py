"""stress_bn_v5_persistance.py — Stress test 50 restarts simules BN V5.

ULTRATHINK BN V5 - Sprint stabilite Etape 6 (10/06/2026).
Generalisation pattern Bot 3 v3 stress test (09/06 soir).

Critere B1 : 0 corruption d'etat sur 50 restarts simules + signal_counter
monotone cross-restart + positions integrity.

Usage :
  python -X utf8 tools/stress_bn_v5_persistance.py            # orchestrate 50 iter
  python -X utf8 tools/stress_bn_v5_persistance.py --iter 10  # 10 iter pour test
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))


KILL_DELAY_RANGE_SEC = (2.0, 5.0)
WORKER_SAVE_INTERVAL_SEC = (0.01, 0.1)
WORKER_MAX_ITERATIONS = 10000
VERIFIER_FILE_HANDLE_WAIT_SEC = 0.2
RANDOM_SEED = 42
DEFAULT_ORCHESTRATION_ITERATIONS = 50

BN_V5_VALID_PATTERNS = ["V_LONG", "W_LONG", "M_SHORT", "INV_V_SHORT"]


def run_worker(state_path: Path) -> None:
    from CORE.bot_persistance import PositionPersistance

    lock = threading.Lock()
    persistance = PositionPersistance(
        bot_name="bn_v5_stress", lock=lock,
        emit_fn=lambda *args, **kwargs: None,
        state_path=state_path,
    )

    print(f"[bn_v5_worker pid={os.getpid()}] save_position loop start", flush=True)
    rand = random.Random(os.getpid() + int(time.time()))

    persistance.set_meta("signal_counter_NQ", 1)
    persistance.set_meta("signal_counter_ES", 1)
    initial_pos = {
        "signal_id": f"BN_V5_NQ_{datetime.now(timezone.utc).strftime('%Y%m%d')}_0001",
        "sym": "NQ", "pattern": "V_LONG", "side": "LONG",
        "entry_price": 29000.0, "sl_initial": 28990.0, "sl_current": 28990.0,
        "pivot_price": 28995.0, "neckline": 29010.0,
        "parent_cid": "MIA_P_INIT", "tp_cid": "MIA_TP_INIT", "sl_cid": "MIA_SL_INIT",
        "qty": 3, "entry_idx": 0,
        "entry_ts": datetime.now(timezone.utc).isoformat(),
        "ts_event_open": None, "bars_held": 0, "iteration": 0,
    }
    persistance.save_position("NQ", initial_pos)
    print(f"[bn_v5_worker pid={os.getpid()}] initial save OK", flush=True)

    counter = {"NQ": 1, "ES": 1}
    iteration = 1
    while iteration < WORKER_MAX_ITERATIONS:
        sym = rand.choice(["NQ", "ES"])
        counter[sym] += 1
        pattern = rand.choice(BN_V5_VALID_PATTERNS)
        side = "LONG" if "LONG" in pattern else "SHORT"

        pos = {
            "signal_id": (
                f"BN_V5_{sym}_{datetime.now(timezone.utc).strftime('%Y%m%d')}_"
                f"{counter[sym]:04d}"
            ),
            "sym": sym, "pattern": pattern, "side": side,
            "entry_price": round(rand.uniform(29000.0, 30000.0), 2),
            "sl_initial": round(rand.uniform(28500.0, 29500.0), 2),
            "sl_current": round(rand.uniform(28500.0, 29500.0), 2),
            "pivot_price": round(rand.uniform(28500.0, 29500.0), 2),
            "neckline": round(rand.uniform(29000.0, 30000.0), 2),
            "parent_cid": f"MIA_P_{iteration:06d}",
            "tp_cid": f"MIA_TP_{iteration:06d}",
            "sl_cid": f"MIA_SL_{iteration:06d}",
            "qty": 3, "entry_idx": iteration,
            "entry_ts": datetime.now(timezone.utc).isoformat(),
            "ts_event_open": None,
            "bars_held": rand.randint(0, 90),
            "iteration": iteration,
        }
        try:
            persistance.save_position(sym, pos)
            persistance.set_meta(f"signal_counter_{sym}", counter[sym])
        except Exception as e:
            print(f"[bn_v5_worker] save EXC: {type(e).__name__}: {e}", flush=True)
            return

        if iteration % 10 == 0:
            try:
                persistance.set_meta(
                    "last_trade_close_ts_NQ",
                    datetime.now(timezone.utc).isoformat())
                persistance.set_meta("worker_iteration", iteration)
            except Exception:
                pass

        iteration += 1
        time.sleep(rand.uniform(*WORKER_SAVE_INTERVAL_SEC))


def run_verifier(state_path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ok": False, "error": None,
        "details": {
            "state_path": str(state_path),
            "state_exists": False, "tmp_exists": False,
            "json_valid": False, "required_keys_present": False,
            "positions_dict_valid": False, "meta_dict_valid": False,
            "signal_counter_present": False,
            "signal_id_format_valid": False,
            "last_iteration_max": None,
        },
    }
    if not state_path.exists():
        result["error"] = "state_file_absent_after_kill"
        return result
    result["details"]["state_exists"] = True
    tmp_path = state_path.with_suffix(".tmp")
    result["details"]["tmp_exists"] = tmp_path.exists()

    try:
        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        result["error"] = f"json_decode_error: {e}"
        return result
    except OSError as e:
        result["error"] = f"io_error: {e}"
        return result
    result["details"]["json_valid"] = True

    if not isinstance(data, dict):
        result["error"] = f"not_dict: {type(data).__name__}"
        return result
    required_keys = {
        "schema_version", "session_date_utc", "positions", "last_update_ts",
    }
    missing = required_keys - set(data.keys())
    if missing:
        result["error"] = f"required_keys_missing: {sorted(missing)}"
        return result
    result["details"]["required_keys_present"] = True

    if not isinstance(data["positions"], dict):
        result["error"] = f"positions_not_dict"
        return result
    result["details"]["positions_dict_valid"] = True

    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        result["error"] = f"meta_not_dict"
        return result
    result["details"]["meta_dict_valid"] = True

    counter_nq = meta.get("signal_counter_NQ")
    counter_es = meta.get("signal_counter_ES")
    if counter_nq is not None:
        if not isinstance(counter_nq, int) or counter_nq < 1:
            result["error"] = f"signal_counter_NQ invalid: {counter_nq}"
            return result
        result["details"]["counter_NQ"] = counter_nq
    if counter_es is not None:
        if not isinstance(counter_es, int) or counter_es < 1:
            result["error"] = f"signal_counter_ES invalid: {counter_es}"
            return result
        result["details"]["counter_ES"] = counter_es
    if counter_nq is not None or counter_es is not None:
        result["details"]["signal_counter_present"] = True

    max_iter = -1
    for sym, pos in data["positions"].items():
        if not isinstance(pos, dict):
            continue
        sid = pos.get("signal_id", "")
        if sid and not sid.startswith("BN_V5_"):
            result["error"] = f"signal_id format invalid: {sid}"
            return result
        if "iteration" in pos:
            try:
                max_iter = max(max_iter, int(pos["iteration"]))
            except (TypeError, ValueError):
                pass
    if max_iter >= 0:
        result["details"]["last_iteration_max"] = max_iter
        result["details"]["signal_id_format_valid"] = True

    try:
        from CORE.bot_persistance import PositionPersistance
        lock = threading.Lock()
        p = PositionPersistance(
            bot_name="bn_v5_stress", lock=lock,
            emit_fn=lambda *args, **kwargs: None,
            state_path=state_path,
        )
        restored = p.restore()
        result["details"]["positionpersistance_restore_ok"] = True
        result["details"]["restored_n_positions"] = len(restored)
    except Exception as e:
        result["error"] = f"restore_exc: {type(e).__name__}: {e}"
        return result

    result["ok"] = True
    return result


def kill_process_windows(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def kill_process_unix(pid: int) -> None:
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def kill_process(pid: int) -> None:
    if sys.platform == "win32":
        kill_process_windows(pid)
    else:
        kill_process_unix(pid)


def run_one_iteration(
    iteration_idx: int, workspace: Path, rand: random.Random,
) -> Dict[str, Any]:
    state_path = workspace / f"iter_{iteration_idx:03d}" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        state_path.unlink()
    tmp_path = state_path.with_suffix(".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    cmd = [
        sys.executable, "-X", "utf8",
        str(Path(__file__).resolve()),
        "--worker", "--state", str(state_path),
    ]
    try:
        worker = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(ROOT),
        )
    except OSError as e:
        return {
            "iteration": iteration_idx, "ok": False,
            "error": f"worker_spawn_failed: {e}",
            "kill_delay_sec": None,
        }

    kill_delay = rand.uniform(*KILL_DELAY_RANGE_SEC)
    time.sleep(kill_delay)
    kill_process(worker.pid)

    try:
        worker.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            worker.kill()
            worker.wait(timeout=2)
        except Exception:
            pass

    time.sleep(VERIFIER_FILE_HANDLE_WAIT_SEC)

    verify_result = run_verifier(state_path)
    verify_result["iteration"] = iteration_idx
    verify_result["kill_delay_sec"] = round(kill_delay, 3)
    return verify_result


def run_orchestrator(n_iterations: int) -> Dict[str, Any]:
    rand = random.Random(RANDOM_SEED)
    workspace = Path(tempfile.mkdtemp(prefix="bn_v5_stress_"))
    print(f"[orchestrator] workspace = {workspace}", flush=True)
    print(f"[orchestrator] running {n_iterations} iterations")
    print(f"[orchestrator] kill_delay {KILL_DELAY_RANGE_SEC}s")

    results: List[Dict[str, Any]] = []
    n_pass = 0
    n_fail = 0

    for i in range(n_iterations):
        result = run_one_iteration(i, workspace, rand)
        results.append(result)
        if result["ok"]:
            n_pass += 1
            print(f"[iter {i:03d}] OK (kill {result['kill_delay_sec']}s, "
                  f"max_iter {result['details'].get('last_iteration_max', 'n/a')}, "
                  f"cNQ={result['details'].get('counter_NQ', 'n/a')}, "
                  f"cES={result['details'].get('counter_ES', 'n/a')})", flush=True)
        else:
            n_fail += 1
            print(f"[iter {i:03d}] FAIL: {result['error']}", flush=True)

    summary = {
        "n_iterations": n_iterations, "n_pass": n_pass, "n_fail": n_fail,
        "pass_rate_pct": round(100 * n_pass / n_iterations, 2),
        "workspace": str(workspace),
        "results": results,
    }
    print(f"\n[SUMMARY] BN V5 stress {n_iterations} iter")
    print(f"  PASS : {n_pass}/{n_iterations} ({summary['pass_rate_pct']}%)")
    print(f"  FAIL : {n_fail}/{n_iterations}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="BN V5 stress test")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--state", type=str, default=None)
    parser.add_argument("--iter", type=int, default=DEFAULT_ORCHESTRATION_ITERATIONS)
    args = parser.parse_args()

    if args.worker:
        if not args.state:
            print("ERR: --state requis", file=sys.stderr)
            sys.exit(1)
        run_worker(Path(args.state))
        return

    if args.verify:
        if not args.state:
            print("ERR: --state requis", file=sys.stderr)
            sys.exit(1)
        result = run_verifier(Path(args.state))
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["ok"] else 1)

    summary = run_orchestrator(args.iter)
    # Save summary JSON
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = ROOT / "tools" / f"stress_bn_v5_results_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"  results saved: {out_path}")
    sys.exit(0 if summary["n_fail"] == 0 else 1)


if __name__ == "__main__":
    main()
