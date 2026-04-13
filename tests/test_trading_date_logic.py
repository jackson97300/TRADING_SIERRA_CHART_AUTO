#!/usr/bin/env python3
"""
TEST trading date logic — port Python de DMP_WR_GetTradingDateInt
====================================================================

Valide la logique **approche E** avant de toucher au C++.

Règle de nommage (CME Globex) : la journée de trading commence à 18h00 ET.
  - Barre < 18h00 ET (h_et in [0, 17])  → trading day = même jour
  - Barre >= 18h00 ET (h_et in [18, 23]) → trading day = jour suivant

Le bug initial (ancien C++) était :
  trading_dt = bar_et_ole + 1.0  // → arrondi flottant via GetDateYMD → +1 jour
Résultat : une barre jeudi 23:59 ET finissait dans le fichier samedi au lieu
de vendredi. Exemple observé : DATA/ES/20260411_ES.jsonl contenait une barre
du jeudi 09/04 23:59:59 ET, alors qu'elle aurait dû être dans 20260410.

Approche E (fix) : recalcul direct depuis les champs `tm` (gmtime), avec
soustraction entière de l'offset DST, gestion rollover UTC→ET arrière, puis
incrémentation entière `dd++` avec gestion fin de mois / bissextile / fin
d'année. **Zéro flottant, zéro `GetDateYMD()` sur une valeur calculée.**

Usage :
    python -X utf8 tests/test_trading_date_logic.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════════════════
# PORT PYTHON DE LA LOGIQUE C++ (approche E)
# ═══════════════════════════════════════════════════════════════════════════════


def _days_in_month(yy: int, mm: int) -> int:
    """Nombre de jours dans un mois — gère l'année bissextile (Grégorien)."""
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if mm == 2:
        leap = (yy % 4 == 0 and yy % 100 != 0) or (yy % 400 == 0)
        return 29 if leap else 28
    return days[mm - 1]


def compute_trading_date(bar_time_utc: datetime) -> int:
    """
    Port Python de `DMP_WR_GetTradingDateInt` C++ avec approche E (sans OLE/float).

    Args:
        bar_time_utc: datetime timezone-aware en UTC (equivalent SCDateTime UTC).

    Returns:
        int YYYYMMDD — date du fichier JSONL où cette barre doit être écrite.

    Raises:
        ValueError si bar_time_utc n'est pas timezone-aware ou pas UTC.
    """
    if bar_time_utc.tzinfo is None:
        raise ValueError("bar_time_utc doit être timezone-aware en UTC")
    if bar_time_utc.tzinfo.utcoffset(bar_time_utc).total_seconds() != 0:
        raise ValueError("bar_time_utc doit être en UTC (offset 0)")

    # Équivalent `gmtime_s(sec)` en C++
    yy_utc = bar_time_utc.year
    mo_utc = bar_time_utc.month
    dy_utc = bar_time_utc.day
    h_utc  = bar_time_utc.hour
    # tm_wday convention : 0=Sunday, 1=Monday, ..., 6=Saturday
    # isoweekday : 1=Monday, ..., 7=Sunday → (%7) donne la même convention que C tm_wday
    wday = bar_time_utc.isoweekday() % 7

    # Détection DST US (2ème dimanche mars → 1er dimanche novembre)
    # Utilise la formule `(dy - wday) >= 8` pour identifier "dimanche précédent >= 8"
    # qui correspond exactement au 2ème dimanche de mars (1-7 = 1er dim, 8-14 = 2ème)
    is_dst = False
    if 4 <= mo_utc <= 10:
        is_dst = True
    elif mo_utc == 3 and (dy_utc - wday) >= 8:
        is_dst = True
    elif mo_utc == 11 and (dy_utc - wday) < 1:
        is_dst = True

    utc_offset = 4 if is_dst else 5

    # Calcul direct en entier — SANS utiliser bar_et_ole ni SCDateTime::GetDateYMD()
    # pour éviter toute imprécision flottante.
    h_et = h_utc - utc_offset  # peut être négatif
    yy = yy_utc
    mm = mo_utc
    dd = dy_utc

    # Rollover arrière UTC→ET : si h_et < 0, la date ET correspond à la veille
    # Exemple : 10/04 00:00 UTC (EDT=-4) → 09/04 20:00 ET → (yy=2026, mm=4, dd=9, h_et=20)
    if h_et < 0:
        h_et += 24
        dd -= 1
        if dd < 1:
            mm -= 1
            if mm < 1:
                mm = 12
                yy -= 1
            dd = _days_in_month(yy, mm)

    # Trading day rule : si h_et >= 18, la barre appartient au trading day suivant
    if h_et >= 18:
        dd += 1
        max_dd = _days_in_month(yy, mm)
        if dd > max_dd:
            dd = 1
            mm += 1
            if mm > 12:
                mm = 1
                yy += 1

    return yy * 10000 + mm * 100 + dd


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

PASSED = 0
FAILED = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, expected: int | None = None, got: int | None = None) -> None:
    global PASSED, FAILED
    if cond:
        print(f"  OK  {name}")
        PASSED += 1
    else:
        detail = f" (expected={expected}, got={got})" if expected is not None else ""
        print(f"  FAIL {name}{detail}")
        FAILED += 1
        FAILURES.append(name)


# ── TESTS BASIQUES (5 cas de session normale) ─────────────────────────────────

def test_1_monday_rth_open():
    """Lundi 09:30 EDT → trading day = lundi."""
    print("\n[1] Lundi 09:30 EDT → trading day = lundi")
    # 13 avril 2026 (lundi) 09:30 EDT = 13:30 UTC (EDT = UTC-4)
    bar = datetime(2026, 4, 13, 13, 30, 0, tzinfo=timezone.utc)
    result = compute_trading_date(bar)
    check("Monday 09:30 EDT → 20260413", result == 20260413, 20260413, result)


def test_2_monday_rth_end():
    """Lundi 15:59 EDT → trading day = lundi."""
    print("\n[2] Lundi 15:59 EDT → trading day = lundi")
    bar = datetime(2026, 4, 13, 19, 59, 0, tzinfo=timezone.utc)  # 15:59 EDT
    result = compute_trading_date(bar)
    check("Monday 15:59 EDT → 20260413", result == 20260413, 20260413, result)


def test_3_monday_asia_start():
    """Lundi 18:01 EDT → trading day = mardi."""
    print("\n[3] Lundi 18:01 EDT → trading day = mardi (règle +1)")
    bar = datetime(2026, 4, 13, 22, 1, 0, tzinfo=timezone.utc)  # 18:01 EDT
    result = compute_trading_date(bar)
    check("Monday 18:01 EDT → 20260414", result == 20260414, 20260414, result)


def test_4_sunday_globex_open():
    """Dimanche 18:00 EDT → trading day = lundi (Globex open)."""
    print("\n[4] Dimanche 18:00 EDT → trading day = lundi (Globex open)")
    bar = datetime(2026, 4, 12, 22, 0, 0, tzinfo=timezone.utc)  # 12/04 dimanche 18:00 EDT
    result = compute_trading_date(bar)
    check("Sunday 18:00 EDT → 20260413", result == 20260413, 20260413, result)


def test_5_thursday_23h59_bug_case():
    """CAS DU BUG INITIAL : Jeudi 23:59:59 EDT → trading day = vendredi.

    C'est le cas qui a provoqué le fichier `DATA/ES/20260411_ES.jsonl` contenant
    une barre du jeudi 09/04 23:59:59 ET. Avec l'ancien code buggé, le fichier
    était nommé 20260411 (samedi). Avec le fix (approche E), il doit être
    nommé 20260410 (vendredi, trading day correct).
    """
    print("\n[5] ⚠️  BUG CASE : Jeudi 23:59 EDT → trading day = vendredi")
    # Jeudi 9 avril 2026 23:59:59 EDT = Vendredi 10 avril 03:59:59 UTC
    bar = datetime(2026, 4, 10, 3, 59, 59, tzinfo=timezone.utc)
    result = compute_trading_date(bar)
    check(
        "Thu 09/04 23:59:59 EDT → 20260410 (PAS 20260411)",
        result == 20260410,
        20260410,
        result,
    )


# ── TESTS EDGE (fin de mois, fin d'année, bissextile, rollovers) ────────────

def test_6_end_of_month_april():
    """30 avril 18:01 EDT → 1er mai (rollover fin de mois)."""
    print("\n[6] 30 avril 18:01 EDT → 1er mai (rollover fin de mois)")
    bar = datetime(2026, 4, 30, 22, 1, 0, tzinfo=timezone.utc)
    result = compute_trading_date(bar)
    check("30/04 18:01 EDT → 20260501", result == 20260501, 20260501, result)


def test_7_end_of_year_new_year():
    """31 décembre 18:01 EST → 1er janvier année+1 (rollover année)."""
    print("\n[7] 31 décembre 18:01 EST → 1er janvier N+1 (rollover année)")
    bar = datetime(2026, 12, 31, 23, 1, 0, tzinfo=timezone.utc)
    result = compute_trading_date(bar)
    check("31/12/2026 18:01 EST → 20270101", result == 20270101, 20270101, result)


def test_8_february_end_non_leap():
    """28 février 2027 18:01 EST → 1er mars (année non-bissextile)."""
    print("\n[8] 28 février 2027 18:01 EST (non-bissextile) → 1er mars")
    bar = datetime(2027, 2, 28, 23, 1, 0, tzinfo=timezone.utc)
    result = compute_trading_date(bar)
    check("28/02/2027 18:01 EST → 20270301", result == 20270301, 20270301, result)


def test_9_february_leap_year():
    """29 février 2028 18:01 EST → 1er mars (année bissextile)."""
    print("\n[9] 29 février 2028 18:01 EST (bissextile) → 1er mars")
    bar = datetime(2028, 2, 29, 23, 1, 0, tzinfo=timezone.utc)
    result = compute_trading_date(bar)
    check("29/02/2028 18:01 EST → 20280301", result == 20280301, 20280301, result)


def test_10_march_before_dst():
    """1er mars 02:00 EST (avant passage DST) → same day."""
    print("\n[10] 1er mars 02:00 EST (avant DST) → same day")
    # 1er mars 2026 est un dimanche. DST bascule le 8 mars (2ème dimanche).
    # Le 1er est donc encore EST (UTC-5). 02:00 EST = 07:00 UTC.
    bar = datetime(2026, 3, 1, 7, 0, 0, tzinfo=timezone.utc)
    result = compute_trading_date(bar)
    check("1/03/2026 02:00 EST → 20260301", result == 20260301, 20260301, result)


def test_11_utc_rollback_to_previous_day():
    """Rollover UTC→ET arrière : 00:00 UTC = veille 20:00 EDT (trading day suivant)."""
    print("\n[11] Rollover UTC→ET arrière (00:00 UTC = 20:00 EDT veille)")
    # 10 avril 2026 00:00 UTC = 9 avril 20:00 EDT (jeudi 20:00)
    # h_et=20 >= 18 → trading day = vendredi 10/04
    bar = datetime(2026, 4, 10, 0, 0, 0, tzinfo=timezone.utc)
    result = compute_trading_date(bar)
    check(
        "10/04 00:00 UTC → Thu 9/04 20:00 EDT → 20260410",
        result == 20260410,
        20260410,
        result,
    )


def test_12_new_year_rollover_et():
    """31 déc 22:00 EST → 1er janvier trading day (rollover complet)."""
    print("\n[12] 31 déc 2025 22:00 EST → 1er janvier 2026 trading day")
    # 31 déc 2025 22:00 EST = 1er jan 2026 03:00 UTC
    # yy_utc=2026, mo=1, dd=1, h_utc=3 → h_et = 3-5 = -2
    # Rollover arrière : h_et=22, dd=0 → mm=12, yy=2025, dd=31
    # h_et=22 >= 18 → dd++=32 → dd>31 → dd=1, mm=1, yy=2026
    # Résultat final : 20260101 ✅
    bar = datetime(2026, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
    result = compute_trading_date(bar)
    check(
        "1/01/2026 03:00 UTC → 31/12/2025 22:00 EST → 20260101",
        result == 20260101,
        20260101,
        result,
    )


# ── TEST BONUS : reproduction exacte du bug historique ──────────────────────

def test_13_historical_bug_reproduction():
    """Reproduction exacte du bug : fichier DATA/ES/20260411_ES.jsonl.

    Le fichier a été créé avec le nom 20260411 mais contient une seule barre
    dont ts=1775793599000 = Thu 09/04 23:59:59 EDT. Avec le fix approche E,
    cette barre doit aller dans 20260410 (trading day vendredi).
    """
    print("\n[13] Reproduction exacte du bug historique (ts=1775793599000)")
    bar = datetime.fromtimestamp(1775793599, tz=timezone.utc)
    result = compute_trading_date(bar)
    check(
        "ts=1775793599000 → 20260410 (fix) au lieu de 20260411 (bug)",
        result == 20260410,
        20260410,
        result,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=" * 64)
    print("  TEST compute_trading_date — port Python DMP_WR_GetTradingDateInt")
    print("  Approche E : recalcul direct depuis tm (zero float, zero OLE)")
    print("=" * 64)

    # Tests basiques (cas de session normale)
    test_1_monday_rth_open()
    test_2_monday_rth_end()
    test_3_monday_asia_start()
    test_4_sunday_globex_open()
    test_5_thursday_23h59_bug_case()

    # Tests edge (fin de mois, bissextile, rollovers)
    test_6_end_of_month_april()
    test_7_end_of_year_new_year()
    test_8_february_end_non_leap()
    test_9_february_leap_year()
    test_10_march_before_dst()
    test_11_utc_rollback_to_previous_day()
    test_12_new_year_rollover_et()

    # Test bonus : reproduction exacte du bug historique
    test_13_historical_bug_reproduction()

    print()
    print("=" * 64)
    print(f"  {PASSED}/{PASSED + FAILED} tests passent")
    if FAILURES:
        print("  ECHECS :")
        for name in FAILURES:
            print(f"    - {name}")
        print("=" * 64)
        sys.exit(1)
    print("  TOUS LES TESTS PASSENT — logique validée, prêt pour port C++")
    print("=" * 64)


if __name__ == "__main__":
    main()
