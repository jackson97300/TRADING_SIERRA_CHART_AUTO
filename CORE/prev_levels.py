"""prev_levels.py — Features niveaux historiques (PDH/PDL, cash, overnight).

Phase 3.3 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s4.4

Module reproduit 16 features historiques sur OHLCV Sierra natif :

  ## Previous Day (jour precedent)
  1.  pdh : prev day high (absolu)
  2.  pdl : prev day low (absolu)
  3.  dist_pdh_atr : (close - pdh) / atr (signed)
  4.  dist_pdl_atr : (close - pdl) / atr (signed)

  ## Cash session RTH (current day intraday)
  5.  cash_high : max bar_high depuis cash open RTH
  6.  cash_low  : min bar_low depuis cash open RTH
  7.  is_new_cash_high : bool, bar courante = new cash high
  8.  is_new_cash_low  : bool, bar courante = new cash low
  9.  dist_cash_high_atr : (close - cash_high) / atr (signed)
  10. dist_cash_low_atr  : (close - cash_low) / atr (signed)

  ## Open RTH cash
  11. open_cash : prix au RTH open 09:30 ET (snapshot)
  12. above_open_cash : bool, close > open_cash

  ## Overnight (18:00 ET J-1 -> 09:30 ET J)
  13. ovn_high : max bar_high pendant overnight
  14. ovn_low  : min bar_low pendant overnight
  15. ovn_broken_up : bool, close > ovn_high (cassure haussiere)
  16. ovn_broken_dn : bool, close < ovn_low

Convention sessions CME (timezone ET via zoneinfo) :
  - Nouveau session date trading : 18:00 ET (CME daily reset)
  - Overnight : 18:00 ET J-1 -> 09:30 ET J
  - RTH cash : 09:30-16:00 ET
  - Post-MOC : 16:00-18:00 ET (pas trackee ici)

⚠️ DST hell (lecon Phase 3.4) :
  - Bascule ete/hiver gere automatiquement par zoneinfo (recommande)
  - JAMAIS hardcode +5h offset (= bug 2x/an)
  - now_utc tz-aware OBLIGATOIRE (raise si naive)

Source data :
  - bar_ts_utc (datetime tz-aware UTC)
  - bar_high, bar_low, close (OHLCV)
  - atr (pour normalisation dist_*_atr signed)

Garde-fou SIGNE (4 features SIGNEES) :
  - dist_pdh_atr, dist_pdl_atr, dist_cash_high_atr, dist_cash_low_atr
  - Convention : (close - level) / atr -> positive si close > level
  - Validation empirique 10j convergence > 60% reportee Phase 3.3.1

Anti-pattern interdit :
  - Composite hardcode "sell if dist_pdh > 0.5" -> features brutes
  - Silent fallback : NaN propre cold-start, raise inputs invalides

Auteur : MIA Trading V2 (Phase 3.3 Sierra Migration)
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional

import numpy as np
import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # py < 3.9 fallback

ET = ZoneInfo("America/New_York")

# Heures cles RTH cash session (ET)
CASH_OPEN_TIME_ET = time(9, 30)
CASH_CLOSE_TIME_ET = time(16, 0)
# CME daily reset = 18:00 ET (nouveau session date trading)
CME_DAILY_RESET_ET = time(18, 0)


class PrevLevelsCalculator:
    """Calculateur stateful 16 features niveaux historiques.

    Usage:
        calc = PrevLevelsCalculator()
        for bar in bars:
            features = calc.update(
                bar_ts_utc=bar["ts_utc"],
                bar_high=bar["bar_high"],
                bar_low=bar["bar_low"],
                close=bar["close"],
                atr=bar["atr"],
            )

    Reset cross-day automatique : detection nouveau session_date_trading
    a 18:00 ET fait via etat interne (pas besoin d'appeler reset() explicit).
    """

    def __init__(self) -> None:
        # Session tracking
        self._current_trading_date: Optional[date] = None
        # PDH/PDL : snapshot du jour precedent
        self._pdh: Optional[float] = None
        self._pdl: Optional[float] = None
        # Running high/low du jour courant (pour devenir pdh/pdl au prochain reset)
        self._today_high: Optional[float] = None
        self._today_low: Optional[float] = None
        # Cash session RTH
        self._cash_high: Optional[float] = None
        self._cash_low: Optional[float] = None
        self._open_cash: Optional[float] = None
        self._in_cash_session: bool = False
        # Overnight
        self._ovn_high: Optional[float] = None
        self._ovn_low: Optional[float] = None
        self._ovn_broken_up: bool = False
        self._ovn_broken_dn: bool = False

    def reset(self) -> None:
        """Reset complet (test only). Normalement cross-day automatique."""
        self.__init__()

    def update(
        self,
        bar_ts_utc: datetime,
        bar_high: Optional[float],
        bar_low: Optional[float],
        close: Optional[float],
        atr: Optional[float],
    ) -> dict:
        """Update state + compute 16 features."""
        # FAIL LOUD : ts naive interdit (DST hell prevention)
        if bar_ts_utc.tzinfo is None:
            raise ValueError(
                f"PrevLevelsCalculator.update : bar_ts_utc doit etre tz-aware UTC, "
                f"obtenu naive {bar_ts_utc}"
            )

        # NaN handling -> features NaN/False
        if any(v is None or (isinstance(v, float) and np.isnan(v))
               for v in (bar_high, bar_low, close, atr)) or atr == 0:
            return self._empty_features()

        bar_high = float(bar_high)
        bar_low = float(bar_low)
        close = float(close)
        atr = float(atr)

        # Convertir UTC -> ET pour determiner session_date_trading
        ts_et = bar_ts_utc.astimezone(ET)
        trading_date = self._compute_trading_date(ts_et)

        # ─────────────────────────────────────────────────────────
        # Detection nouveau session date trading (18:00 ET reset)
        # ─────────────────────────────────────────────────────────
        if self._current_trading_date is None:
            # Cold-start : init
            self._current_trading_date = trading_date
        elif trading_date != self._current_trading_date:
            # NEW DAY : snapshot day high/low -> pdh/pdl
            self._pdh = self._today_high
            self._pdl = self._today_low
            self._today_high = None
            self._today_low = None
            # Reset cash session
            self._cash_high = None
            self._cash_low = None
            self._open_cash = None
            self._in_cash_session = False
            # Reset overnight
            self._ovn_high = None
            self._ovn_low = None
            self._ovn_broken_up = False
            self._ovn_broken_dn = False
            self._current_trading_date = trading_date

        # Update running today high/low (pour PDH/PDL futur)
        self._today_high = (
            bar_high if self._today_high is None
            else max(self._today_high, bar_high)
        )
        self._today_low = (
            bar_low if self._today_low is None
            else min(self._today_low, bar_low)
        )

        # ─────────────────────────────────────────────────────────
        # RTH cash session (09:30 - 16:00 ET)
        # ─────────────────────────────────────────────────────────
        in_cash = CASH_OPEN_TIME_ET <= ts_et.time() < CASH_CLOSE_TIME_ET
        if in_cash and not self._in_cash_session:
            # Entree session cash : snapshot open
            self._open_cash = close
            self._cash_high = bar_high
            self._cash_low = bar_low
            self._in_cash_session = True
        elif in_cash:
            self._cash_high = max(self._cash_high, bar_high)
            self._cash_low = min(self._cash_low, bar_low)

        is_new_cash_high = (
            in_cash and self._cash_high is not None
            and bar_high >= self._cash_high
        )
        is_new_cash_low = (
            in_cash and self._cash_low is not None
            and bar_low <= self._cash_low
        )

        # ─────────────────────────────────────────────────────────
        # Overnight (avant cash open RTH 09:30 ET, apres CME reset 18:00 ET)
        # ─────────────────────────────────────────────────────────
        in_ovn = ts_et.time() < CASH_OPEN_TIME_ET or ts_et.time() >= CME_DAILY_RESET_ET
        if in_ovn:
            self._ovn_high = (
                bar_high if self._ovn_high is None
                else max(self._ovn_high, bar_high)
            )
            self._ovn_low = (
                bar_low if self._ovn_low is None
                else min(self._ovn_low, bar_low)
            )
        # Cassure overnight (verifiee TOUJOURS, pas juste in_ovn)
        if self._ovn_high is not None and close > self._ovn_high:
            self._ovn_broken_up = True
        if self._ovn_low is not None and close < self._ovn_low:
            self._ovn_broken_dn = True

        # ─────────────────────────────────────────────────────────
        # Build features dict
        # ─────────────────────────────────────────────────────────
        return {
            # Previous Day
            "pdh": self._pdh if self._pdh is not None else np.nan,
            "pdl": self._pdl if self._pdl is not None else np.nan,
            "dist_pdh_atr": (
                (close - self._pdh) / atr if self._pdh is not None else np.nan
            ),
            "dist_pdl_atr": (
                (close - self._pdl) / atr if self._pdl is not None else np.nan
            ),
            # Cash session
            "cash_high": self._cash_high if self._cash_high is not None else np.nan,
            "cash_low": self._cash_low if self._cash_low is not None else np.nan,
            "is_new_cash_high": bool(is_new_cash_high),
            "is_new_cash_low": bool(is_new_cash_low),
            "dist_cash_high_atr": (
                (close - self._cash_high) / atr
                if self._cash_high is not None else np.nan
            ),
            "dist_cash_low_atr": (
                (close - self._cash_low) / atr
                if self._cash_low is not None else np.nan
            ),
            # Open RTH cash
            "open_cash": self._open_cash if self._open_cash is not None else np.nan,
            "above_open_cash": (
                bool(close > self._open_cash)
                if self._open_cash is not None else False
            ),
            # Overnight
            "ovn_high": self._ovn_high if self._ovn_high is not None else np.nan,
            "ovn_low": self._ovn_low if self._ovn_low is not None else np.nan,
            "ovn_broken_up": bool(self._ovn_broken_up),
            "ovn_broken_dn": bool(self._ovn_broken_dn),
        }

    @staticmethod
    def _compute_trading_date(ts_et: datetime) -> date:
        """Determine session_date_trading CME (reset 18:00 ET).

        Convention : si heure ET >= 18:00, le session date trading est J+1.
        Sinon J.
        """
        if ts_et.time() >= CME_DAILY_RESET_ET:
            # 18:00-23:59 ET = nouveau session date trading (J+1)
            from datetime import timedelta
            return (ts_et + timedelta(days=1)).date()
        return ts_et.date()

    @staticmethod
    def _empty_features() -> dict:
        """Features NaN/False pour input invalide (anti silent fallback)."""
        return {
            "pdh": np.nan,
            "pdl": np.nan,
            "dist_pdh_atr": np.nan,
            "dist_pdl_atr": np.nan,
            "cash_high": np.nan,
            "cash_low": np.nan,
            "is_new_cash_high": False,
            "is_new_cash_low": False,
            "dist_cash_high_atr": np.nan,
            "dist_cash_low_atr": np.nan,
            "open_cash": np.nan,
            "above_open_cash": False,
            "ovn_high": np.nan,
            "ovn_low": np.nan,
            "ovn_broken_up": False,
            "ovn_broken_dn": False,
        }


def compute_prev_levels_features(
    df: pd.DataFrame,
    ts_col: str = "ts_utc",
) -> pd.DataFrame:
    """Batch compute (mode backtest dataset).

    Args:
        df : DataFrame avec colonnes ts_utc, bar_high, bar_low, close, atr.
             Trie chronologiquement.
        ts_col : nom colonne timestamp UTC (ISO string ou datetime tz-aware).

    Returns:
        DataFrame copie + 16 colonnes ajoutees.

    Raises:
        ValueError : si colonne requise manque (FAIL LOUD).
    """
    required = [ts_col, "bar_high", "bar_low", "close", "atr"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"compute_prev_levels_features : colonnes manquantes {missing}"
        )

    result = df.copy()
    calc = PrevLevelsCalculator()
    rows = []

    for _, row in df.iterrows():
        ts = row[ts_col]
        if pd.isna(ts):
            rows.append(calc._empty_features())
            continue
        if isinstance(ts, str):
            ts_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, (datetime, pd.Timestamp)):
            ts_utc = pd.Timestamp(ts).to_pydatetime()
        else:
            rows.append(calc._empty_features())
            continue

        if ts_utc.tzinfo is None:
            ts_utc = ts_utc.replace(tzinfo=timezone.utc)

        rows.append(calc.update(
            bar_ts_utc=ts_utc,
            bar_high=row["bar_high"],
            bar_low=row["bar_low"],
            close=row["close"],
            atr=row["atr"],
        ))

    features_df = pd.DataFrame(rows, index=result.index)
    for col in features_df.columns:
        result[col] = features_df[col].values
    return result
