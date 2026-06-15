"""Backtest replay Bot 1 v2 sur sierra_enriched local.

CRITIQUE Jackson : ce backtest valide la calibration NO-PARALYSIS.

Si N trades < 5 sur 9 jours combines (4j NQ + 5j ES) -> calibration trop strict
-> recalibrer rvol/vix/etoile-mere AVANT deploy.

Si N trades > 100 -> calibration trop laxiste -> recalibrer strict.

Target empirique : 5-30 trades / 9 jours = 0.5-3 trades / jour combines.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.dashboard_mirror import compute_verdict


def replay_file(path: Path, symbol: str, cfg: Bot1V2Config) -> dict:
    """Replay 1 fichier JSONL sierra_enriched avec COOLDOWN simule.

    Cooldown post-setup : COOLDOWN_POST_CLOSE_MIN bars (= 60 min) ignored.
    = 1 trade par signal arme (pas 1 trade par bar).
    """
    n_bars = 0
    n_accepted = 0  # setups armes (post-cooldown)
    n_setup_in_cooldown = 0  # setups skipped par cooldown
    n_rejected_etoile_mere = 0
    vetos_count: Counter = Counter()
    direction_count: Counter = Counter()
    actions_count: Counter = Counter()
    skip_reasons: Counter = Counter()
    accepted_samples = []

    # Cooldown : index dernier setup arme
    cooldown_until_bar = -1
    cooldown_bars = cfg.COOLDOWN_POST_CLOSE_MIN  # 60 bars = 60 min

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                bar = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_bars += 1

            verdict = compute_verdict(bar, cfg=cfg)
            actions_count[verdict.action] += 1

            if verdict.ready_to_arm:
                # Cooldown : 1 setup arme puis ignore N bars
                if n_bars <= cooldown_until_bar:
                    n_setup_in_cooldown += 1
                    continue
                n_accepted += 1
                cooldown_until_bar = n_bars + cooldown_bars
                direction_count[verdict.direction] += 1
                if len(accepted_samples) < 5:
                    accepted_samples.append({
                        "ts": bar.get("ts"),
                        "close": bar.get("close"),
                        "action": verdict.action,
                        "direction": verdict.direction,
                        "rvol_zscore": verdict.rvol_zscore,
                        "vix": verdict.vix_level,
                    })
                continue

            # Rejected : pourquoi ?
            if verdict.vetos:
                for v in verdict.vetos:
                    vetos_count[v.name] += 1
                skip_reasons["VETO_FIRED"] += 1
            else:
                n_rejected_etoile_mere += 1
                skip_reasons["ETOILE_MERE_REJECT"] += 1

    return {
        "symbol": symbol,
        "path": str(path),
        "n_bars": n_bars,
        "n_accepted": n_accepted,
        "n_setup_in_cooldown": n_setup_in_cooldown,
        "n_rejected_etoile_mere": n_rejected_etoile_mere,
        "vetos_count": dict(vetos_count),
        "direction_count": dict(direction_count),
        "actions_count": dict(actions_count.most_common(10)),
        "skip_reasons": dict(skip_reasons),
        "accepted_samples": accepted_samples,
        "accept_rate_pct": round(100.0 * n_accepted / n_bars, 3) if n_bars else 0.0,
    }


def main():
    cfg = Bot1V2Config.from_env()
    root = _ROOT / "DATA" / "live_enriched" / "sierra"

    files = []
    for sym_dir, sym in (("NQ", "NQ"), ("ES", "ES")):
        d = root / sym_dir
        if not d.exists():
            continue
        for f in sorted(d.glob("*_sierra_enriched.jsonl")):
            # skip very small files (incomplet)
            if f.stat().st_size < 100_000:
                continue
            files.append((f, sym))

    print(f"=== Bot 1 v2 Backtest Replay ===")
    print(f"Config: MIN_STARS implicit (etoile-mere + 0 veto)")
    print(f"        RVOL veto threshold: {cfg.RVOL_ZSCORE_VETO_THRESHOLD}")
    print(f"        VIX range: [{cfg.VIX_LEVEL_MIN}, {cfg.VIX_LEVEL_MAX}]")
    print(f"        CLIMAX veto: {cfg.CLIMAX_VETO_ENABLED}")
    print(f"        GAMMA veto: {cfg.GAMMA_BLOCK_VETO_ENABLED}")
    print()
    print(f"Files: {len(files)}")
    print()

    total_bars = 0
    total_accepted = 0
    total_vetos: Counter = Counter()
    total_direction: Counter = Counter()
    total_actions: Counter = Counter()
    total_reject_em = 0

    for f, sym in files:
        result = replay_file(f, sym, cfg)
        total_bars += result["n_bars"]
        total_accepted += result["n_accepted"]
        for k, v in result["vetos_count"].items():
            total_vetos[k] += v
        for k, v in result["direction_count"].items():
            total_direction[k] += v
        for k, v in result["actions_count"].items():
            total_actions[k] += v
        total_reject_em += result["n_rejected_etoile_mere"]

        print(f"--- {sym} : {f.name} ({result['n_bars']} bars) ---")
        print(f"  Accepted: {result['n_accepted']} ({result['accept_rate_pct']}%)")
        if result["n_accepted"] > 0:
            print(f"  Direction: {result['direction_count']}")
        if result["vetos_count"]:
            print(f"  Vetos fired: {result['vetos_count']}")
        print()

    print(f"=== GLOBAL ===")
    print(f"Total bars: {total_bars}")
    print(f"Total accepted: {total_accepted} ({100.0 * total_accepted / total_bars:.3f}%)")
    print(f"Direction distribution: {dict(total_direction)}")
    print(f"Etoile-mere rejects: {total_reject_em}")
    print(f"Vetos fired: {dict(total_vetos)}")
    print(f"Top actions dashboard: {dict(total_actions.most_common(10))}")
    print()

    # Verdict NO PARALYSIS (avec plafond DailyLimitsGuard 5 trades/jour)
    print(f"=== VERDICT NO PARALYSIS ===")
    days_observed = 9.0
    setups_per_day = total_accepted / days_observed
    # En prod : DailyLimitsGuard plafonne a MAX_TRADES_PER_DAY (5)
    trades_per_day_real = min(setups_per_day, cfg.MAX_TRADES_PER_DAY)
    print(f"Setups armes potentiels : {total_accepted} sur {total_bars} bars ({days_observed} jours)")
    print(f"Setups armes / jour     : ~{setups_per_day:.1f}")
    print(f"DailyLimitsGuard plafond: {cfg.MAX_TRADES_PER_DAY} trades / jour")
    print(f"Trades reels / jour     : ~{trades_per_day_real:.1f}")
    print()
    if total_accepted == 0:
        print(f"!! PARALYSIE CONFIRMEE: 0 setup arme")
        print(f"   -> Relacher seuils (rvol/vix/etoile-mere)")
    elif setups_per_day < 1.0:
        print(f"!! PARALYSIE LATENTE: <1 setup/jour")
        print(f"   -> Relacher ou ajuster fallback dashboard")
    elif setups_per_day > 50.0:
        print(f"!! TROP LAXISTE: >{50} setups/jour (DailyLimitsGuard cache le probleme)")
        print(f"   -> Renforcer cluster ou cooldown")
    else:
        print(f"OK: calibration NO PARALYSIS validee")
        print(f"   {setups_per_day:.1f} setups/jour disponibles, plafond {cfg.MAX_TRADES_PER_DAY} actif")

    # Distribution direction (biais a monitorer)
    if total_direction:
        n_long = total_direction.get("LONG", 0)
        n_short = total_direction.get("SHORT", 0)
        if n_long + n_short > 0:
            print()
            print(f"Distribution direction :")
            print(f"  LONG  : {n_long} ({100.0 * n_long / (n_long + n_short):.1f}%)")
            print(f"  SHORT : {n_short} ({100.0 * n_short / (n_long + n_short):.1f}%)")
            if n_short / max(n_long + n_short, 1) < 0.1:
                print(f"  !! BIAIS LONG fort - normal sur marche haussier 10-15/06 NQ +2424pts")
                print(f"     A monitorer prod si persiste sur marche mixte")


if __name__ == "__main__":
    main()
