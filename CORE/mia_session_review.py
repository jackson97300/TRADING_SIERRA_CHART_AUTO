"""mia_session_review.py — Revue post-session des logs dashboard.

Lit les SESSION_LOGS et produit un rapport:
- Combien de minutes le dashboard a dit SHORT/LONG/NEUTRE
- Qualite des divergences detectees
- Est-ce que le conseil etait correct vs le mouvement reel du prix
- Stats aggregees sur N sessions

Usage:
    python CORE/mia_session_review.py                    # derniere session
    python CORE/mia_session_review.py 20260408           # session specifique
    python CORE/mia_session_review.py --all              # toutes les sessions
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DATA")
LOG_DIR = os.path.join(DATA_DIR, "SESSION_LOGS")


def load_session(date_str: str) -> list[dict]:
    """Charge les snapshots d'une session."""
    filepath = os.path.join(LOG_DIR, f"{date_str}.jsonl")
    if not os.path.exists(filepath):
        return []
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                continue
    return rows


def review_session(date_str: str):
    """Analyse une session et imprime le rapport."""
    rows = load_session(date_str)
    if not rows:
        print(f"Pas de logs pour {date_str}")
        return

    print(f"\n{'=' * 70}")
    print(f"REVUE SESSION — {date_str}")
    print(f"{'=' * 70}")
    print(f"Snapshots: {len(rows)} minutes loggees")
    print(f"Debut: {rows[0]['minute']} UTC — Fin: {rows[-1]['minute']} UTC")
    print()

    for sym in ("es", "nq"):
        price_key = f"{sym}_price"
        bias_key = f"{sym}_bias"
        favor_key = f"{sym}_favor"
        div_key = f"{sym}_div_grade"
        div_q_key = f"{sym}_div_quality"
        conf_key = f"{sym}_confidence"

        prices = [r[price_key] for r in rows if r.get(price_key)]
        if not prices:
            continue

        first_price = prices[0]
        last_price = prices[-1]
        high_price = max(prices)
        low_price = min(prices)
        move = last_price - first_price
        move_ticks = move / 0.25

        print(f"--- {sym.upper()} ---")
        print(f"  Prix: {first_price:.2f} -> {last_price:.2f} ({move:+.2f} pts = {move_ticks:+.0f} ticks)")
        print(f"  Range: {low_price:.2f} - {high_price:.2f} ({(high_price-low_price)/0.25:.0f} ticks)")

        # Comptage bias
        bias_counts = Counter(r.get(bias_key, "?") for r in rows)
        print(f"  Bias: {dict(bias_counts)}")

        # Comptage favor
        favor_counts = Counter(r.get(favor_key, "?") for r in rows)
        print(f"  Favor: {dict(favor_counts)}")

        # Divergences
        div_counts = Counter(r.get(div_key, "NONE") for r in rows)
        if any(k != "NONE" for k in div_counts):
            print(f"  Divergences: {dict(div_counts)}")
            div_active_rows = [r for r in rows if r.get(div_key, "NONE") != "NONE"]
            if div_active_rows:
                avg_q = sum(r.get(div_q_key, 0) for r in div_active_rows) / len(div_active_rows)
                print(f"  Div quality moyenne: {avg_q:.1f}/10 sur {len(div_active_rows)} minutes")

        # Confiance moyenne
        confs = [r.get(conf_key, 0) for r in rows]
        avg_conf = sum(confs) / len(confs) if confs else 0
        print(f"  Confiance moyenne: {avg_conf*100:.0f}%")

        # Pertinence du conseil : est-ce que FAVOR SHORT quand prix baisse ?
        correct = 0
        total_with_favor = 0
        for i in range(len(rows) - 5):
            fav = rows[i].get(favor_key, "NEUTRE")
            if fav == "NEUTRE":
                continue
            total_with_favor += 1
            future_price = rows[min(i + 5, len(rows) - 1)].get(price_key, 0)
            current_price = rows[i].get(price_key, 0)
            if not future_price or not current_price:
                continue
            price_move = future_price - current_price
            if (fav == "SHORT" and price_move < 0) or (fav == "LONG" and price_move > 0):
                correct += 1

        if total_with_favor > 0:
            accuracy = correct / total_with_favor * 100
            print(f"  Pertinence conseil (5min forward): {correct}/{total_with_favor} = {accuracy:.0f}%")
        print()

    # Advisory global
    adv_counts = Counter(r.get("adv_favor", "?") for r in rows)
    print(f"Advisory global: {dict(adv_counts)}")

    # SMT
    smt_active = sum(1 for r in rows if r.get("smt_div", 0))
    if smt_active:
        smt_dirs = Counter(r.get("smt_dir", "NONE") for r in rows if r.get("smt_div"))
        print(f"SMT divergence: {smt_active} minutes, directions: {dict(smt_dirs)}")

    print()


def review_all():
    """Analyse toutes les sessions disponibles."""
    if not os.path.exists(LOG_DIR):
        print("Pas de dossier SESSION_LOGS")
        return
    files = sorted(f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl"))
    if not files:
        print("Aucun log de session trouve")
        return

    print(f"Sessions disponibles: {len(files)}")
    for f in files:
        date_str = f.replace(".jsonl", "")
        review_session(date_str)

    # Stats agregees
    print("=" * 70)
    print("STATS AGREGEES")
    print("=" * 70)
    total_correct = 0
    total_signals = 0
    for f in files:
        date_str = f.replace(".jsonl", "")
        rows = load_session(date_str)
        for sym in ("es", "nq"):
            favor_key = f"{sym}_favor"
            price_key = f"{sym}_price"
            for i in range(len(rows) - 5):
                fav = rows[i].get(favor_key, "NEUTRE")
                if fav == "NEUTRE":
                    continue
                total_signals += 1
                future_price = rows[min(i + 5, len(rows) - 1)].get(price_key, 0)
                current_price = rows[i].get(price_key, 0)
                if not future_price or not current_price:
                    continue
                price_move = future_price - current_price
                if (fav == "SHORT" and price_move < 0) or (fav == "LONG" and price_move > 0):
                    total_correct += 1

    if total_signals > 0:
        print(f"Total signaux directionnels: {total_signals}")
        print(f"Corrects (5min forward): {total_correct} = {total_correct/total_signals*100:.1f}%")
    else:
        print("Pas encore assez de donnees pour des stats")
    print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        review_all()
    elif len(sys.argv) > 1:
        review_session(sys.argv[1])
    else:
        # Derniere session
        if os.path.exists(LOG_DIR):
            files = sorted(f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl"))
            if files:
                review_session(files[-1].replace(".jsonl", ""))
            else:
                print("Aucun log de session")
        else:
            print("Dossier SESSION_LOGS inexistant")
