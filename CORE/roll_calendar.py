"""roll_calendar.py — Calcul features rollover futures CME.

Phase 3.6 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s3.6

Module reproduit 3 features Databento sur calendrier CME statique :

  1. is_roll_day : bool, True le jour du roll futur (3eme vendredi mois roll)
  2. days_since_roll : int, jours depuis dernier roll. NaN si avant 1er roll.
  3. roll_phase : enum -1/0/+1
     - -1 = pre-roll (semaine avant)
     - 0 = roll-day ou immediate post-roll (J0 a J+1)
     - +1 = post-roll regime stable

Conventions CME standards :
  - ES/NQ : quarterly rolls (Mar/Jun/Sep/Dec, 3eme vendredi)
  - MGC (Gold Micro) : monthly (G/J/M/Q/V/Z avril/juin/aout/oct/dec/fev)
    Code GC monthly mais MGC actif moins liquide -> on suit le contract roll CME

⚠️ CONFLIT SEMANTIQUE EN ATTENTE DECISION JACKSON (review code-reviewer 10/06) :

  `enricher_chain.py:1948-1962` (Phase 3c-C, deployee 18/05) produit DEJA un
  champ `roll_phase` mais avec semantique DIFFERENTE :
    - Phase 3c-C (existant prod) : 0=early / 1=mid / 2=late (basee discontinuity)
    - Phase 3.6 (ici, design doc) : -1=pre-roll / 0=roll-day / +1=stable (calendrier)

  Decision integration enricher_chain attendue : (A) deprecate Phase 3c-C +
  flag dataset retro, OU (B) renommer ici en `roll_phase_calendar` pour
  coexistence. Cf IDEAS_BACKLOG.

⚠️ APPROXIMATION MGC (validation Jackson requise) :

  CME docs officielles disent "First Position Day = trading day prior to first
  business day of contract month". Implementation actuelle = 3eme jeudi du mois
  contrat (G/J/M/Q/V/Z). Peut decaler de ~2 semaines vs realite.
  Action : valider empiriquement sur DMP dumps GC futures 6 mois historique.
  Cf IDEAS_BACKLOG / Phase 3.6.2.

Anti-pattern interdit (cf BN V5 KILL 10/06) :
  - Hardcode dates roll dans bot decision -> AS-IS feature contextuelle uniquement
  - Audit Phase 2 design : roll_phase ks=1.0 leak detected -> PAS UTILISER EN
    FEATURE ML DIRECTE. Garder pour visualisation/debug uniquement.
  - Silent fallback symbol inconnu : FAIL LOUD via ValueError (fix 10/06).

Auteur : MIA Trading V2 (Phase 3.6 Sierra Migration)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

# ────────────────────────────────────────────────────────────────────────────
# Calendrier rolls CME (jours observes empiriquement)
# Source : CME contract specs + verification via DMP dumps historique
# ────────────────────────────────────────────────────────────────────────────

# ES/NQ : quarterly roll = 3eme vendredi Mar/Jun/Sep/Dec
# Ex 2025 : Mar 21, Jun 20, Sep 19, Dec 19
# Ex 2026 : Mar 20, Jun 19, Sep 18, Dec 18
def _third_friday(year: int, month: int) -> date:
    """Calcul 3eme vendredi du mois (rolling day standard CME)."""
    # 1er du mois
    d = date(year, month, 1)
    # Decalage jusqu'au premier vendredi (weekday 4 = vendredi)
    days_until_friday = (4 - d.weekday()) % 7
    first_friday = d + timedelta(days=days_until_friday)
    # 3eme vendredi = +14 jours
    return first_friday + timedelta(days=14)


def get_roll_dates_es_nq(year: int) -> list[date]:
    """Roll dates ES/NQ pour annee donnee (Mar/Jun/Sep/Dec 3eme vendredi)."""
    return [_third_friday(year, m) for m in (3, 6, 9, 12)]


# MGC (Gold Micro) : monthly rolls. Liquide contract suit GC futures.
# Mois de contrat actif : G=Feb, J=Apr, M=Jun, Q=Aug, V=Oct, Z=Dec
# Roll typique : 1-2 semaines avant expiration (= last trading day end of month)
# Approximation : 3eme jeudi des mois G/J/M/Q/V/Z
def _third_thursday(year: int, month: int) -> date:
    """3eme jeudi du mois (utilise pour MGC GC rollover liquidite)."""
    d = date(year, month, 1)
    days_until_thursday = (3 - d.weekday()) % 7
    first_thursday = d + timedelta(days=days_until_thursday)
    return first_thursday + timedelta(days=14)


def get_roll_dates_mgc(year: int) -> list[date]:
    """Roll dates MGC pour annee donnee (G/J/M/Q/V/Z = mois 2/4/6/8/10/12)."""
    return [_third_thursday(year, m) for m in (2, 4, 6, 8, 10, 12)]


# Pre-roll window : 5 jours ouvres avant roll (=1 semaine calendaire) -> phase=-1
PRE_ROLL_DAYS = 5
# Post-roll window : 1 jour apres roll -> phase=0 transition
POST_ROLL_TRANSITION_DAYS = 1


# ────────────────────────────────────────────────────────────────────────────
# API publique
# ────────────────────────────────────────────────────────────────────────────

def compute_roll_features(
    bar_date: date,
    symbol: str = "NQ",
) -> dict:
    """Compute roll features pour une bar date donnee + symbol.

    Args:
        bar_date : date de la bar (UTC ou ET, peu importe pour rolls quarterly)
        symbol : "ES" / "NQ" / "MGC" (default "NQ")

    Returns:
        dict {"is_roll_day": bool, "days_since_roll": int OR NaN,
              "roll_phase": int -1/0/+1}
    """
    symbol_upper = symbol.upper()
    if symbol_upper in ("ES", "NQ"):
        roll_dates = get_roll_dates_es_nq(bar_date.year)
        # Ajout annee precedente pour gerer Q1 (avant 1er roll annee)
        roll_dates = get_roll_dates_es_nq(bar_date.year - 1) + roll_dates
        # Et annee suivante pour pre-roll window cross-year
        roll_dates = roll_dates + get_roll_dates_es_nq(bar_date.year + 1)
    elif symbol_upper == "MGC":
        roll_dates = get_roll_dates_mgc(bar_date.year)
        roll_dates = get_roll_dates_mgc(bar_date.year - 1) + roll_dates
        roll_dates = roll_dates + get_roll_dates_mgc(bar_date.year + 1)
    else:
        # FAIL LOUD : silent fallback supprime (review code-reviewer 10/06).
        # `roll_phase=0` sur symbol inconnu = faux signal "roll-day".
        raise ValueError(
            f"compute_roll_features : symbol inconnu '{symbol}'. "
            f"Supporte : ES, NQ, MGC"
        )

    # is_roll_day : exact match
    is_roll = bar_date in roll_dates

    # days_since_roll : trouve dernier roll <= bar_date
    past_rolls = [r for r in roll_dates if r <= bar_date]
    if not past_rolls:
        # Avant le 1er roll connu -> cold-start NaN
        return {
            "is_roll_day": is_roll,
            "days_since_roll": np.nan,
            "roll_phase": 0,
        }
    last_roll = max(past_rolls)
    days_since = (bar_date - last_roll).days

    # roll_phase :
    # -1 = pre-roll window (5 jours avant prochain roll)
    # 0 = roll day OR juste apres (transition J0/J+1)
    # +1 = regime stable post-roll
    future_rolls = [r for r in roll_dates if r > bar_date]
    next_roll = min(future_rolls) if future_rolls else None
    days_until_next = (next_roll - bar_date).days if next_roll else 999

    if is_roll or days_since <= POST_ROLL_TRANSITION_DAYS:
        phase = 0
    elif days_until_next <= PRE_ROLL_DAYS:
        phase = -1
    else:
        phase = 1

    return {
        "is_roll_day": is_roll,
        "days_since_roll": int(days_since),
        "roll_phase": phase,
    }


def compute_roll_features_batch(
    df: pd.DataFrame,
    symbol: str = "NQ",
    date_col: str = "session_date",
) -> pd.DataFrame:
    """Batch compute (mode backtest dataset).

    Args:
        df : DataFrame avec colonne date (ex 'session_date' format YYYY-MM-DD)
        symbol : "ES" / "NQ" / "MGC"
        date_col : nom colonne date

    Returns:
        DataFrame copie avec 3 colonnes ajoutees.
    """
    if date_col not in df.columns:
        raise ValueError(
            f"compute_roll_features_batch : colonne '{date_col}' manquante"
        )

    result = df.copy()
    is_rolls = []
    days_sinces = []
    phases = []

    for ds in df[date_col].values:
        if pd.isna(ds):
            is_rolls.append(False)
            days_sinces.append(np.nan)
            phases.append(0)
            continue
        # Parse date string YYYY-MM-DD ou datetime
        if isinstance(ds, str):
            bar_date = datetime.fromisoformat(ds).date()
        elif isinstance(ds, (datetime, pd.Timestamp)):
            bar_date = ds.date() if hasattr(ds, "date") else ds
        elif isinstance(ds, date):
            bar_date = ds
        else:
            is_rolls.append(False)
            days_sinces.append(np.nan)
            phases.append(0)
            continue

        features = compute_roll_features(bar_date, symbol)
        is_rolls.append(features["is_roll_day"])
        days_sinces.append(features["days_since_roll"])
        phases.append(features["roll_phase"])

    result["is_roll_day"] = is_rolls
    result["days_since_roll"] = days_sinces
    result["roll_phase"] = phases
    return result
