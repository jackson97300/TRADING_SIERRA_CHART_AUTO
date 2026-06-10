"""sessions_fine.py — Features sessions Asia/London/US + opens + IB window.

Phase 3.4 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s4.5

25 features sessions sur OHLCV Sierra natif + horloge ET (timezone) :

## Booleans session active (5)
  1. is_in_asia       : bool, 18:00 ET J-1 -> 03:00 ET J
  2. is_in_london     : bool, 03:00-09:30 ET
  3. is_in_us_cash    : bool, 09:30-16:00 ET (RTH NYSE/NASDAQ)
  4. is_in_us_after   : bool, 16:00-18:00 ET (post-MOC)
  5. is_ib_window     : bool, premiere heure RTH (09:30-10:30 ET)

## Metadonnees temporelles (2)
  6. session_segment  : string enum "asia"/"london"/"us_cash"/"us_after"/"off"
                       ("off" = input NaN bar, sinon une des 4 sessions actives)
  7. mins_et          : int, minutes depuis minuit ET (0-1439)

## Highs/Lows par session (8)
  8.  asia_high, asia_low
  9.  london_high, london_low
  10. us_high, us_low
  11. after_high, after_low

## Opens snapshots (4)
  12. asia_open       : close au 1er bar de la session Asia
  13. london_open     : close au 1er bar London
  14. ny_open         : close au 1er bar US cash (09:30 ET = RTH open)
  15. after_open      : close au 1er bar US after

## Distances aux opens en pct (4)
  16. dist_asia_open_pct    : (close - asia_open) / asia_open * 100
  17. dist_london_open_pct
  18. dist_ny_open_pct
  19. dist_after_open_pct

## Misc (2)
  20. pct_in_range          : (close - day_low) / (day_high - day_low), [0,1]
  21. is_cash_session       : alias is_in_us_cash (compat downstream)

⚠️ DST hell prevention (regle PIVOT pour Phase 3.4) :
  - now_utc tz-aware OBLIGATOIRE -> ValueError si naive
  - Convert UTC -> ET via zoneinfo (auto bascule ete/hiver)
  - JAMAIS hardcode +5h/-5h offset (= bug garanti 2x/an)
  - Tests DST transition mars/novembre inclus

⚠️ CONVENTION CME daily reset 18:00 ET :
  - Asia session demarre a 18:00 ET J-1 (= debut session_date_trading J)
  - Donc bars 18:00 ET J-1 et bars 02:00 ET J = MEME session_date_trading
  - Cross-day reset (PDH/PDL futur) au boundary 18:00 ET (cf prev_levels.py)

Anti-pattern interdit :
  - Composite hardcode "skip if not is_in_us_cash" -> features brutes
  - Silent fallback : NaN propre cold-start, raise inputs invalides

Auteur : MIA Trading V2 (Phase 3.4 Sierra Migration)
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Sessions boundaries (ET)
ASIA_END_ET = time(3, 0)        # Asia : 18:00 ET J-1 -> 03:00 ET
LONDON_END_ET = time(9, 30)     # London : 03:00 -> 09:30 ET
CASH_END_ET = time(16, 0)       # US cash : 09:30 -> 16:00 ET
AFTER_END_ET = time(18, 0)      # US after : 16:00 -> 18:00 ET
# Asia start = 18:00 ET (CME daily reset)
ASIA_START_ET = time(18, 0)

# IB window : premiere heure RTH (09:30 -> 10:30 ET)
IB_END_ET = time(10, 30)


class SessionsFineCalculator:
    """Calculateur stateful 25 features sessions intraday.

    Usage:
        calc = SessionsFineCalculator()
        for bar in bars:
            features = calc.update(
                bar_ts_utc=bar["ts_utc"],
                bar_high=bar["bar_high"],
                bar_low=bar["bar_low"],
                close=bar["close"],
            )

    Reset cross-day automatique : detection nouveau session_date_trading
    a 18:00 ET via etat interne.
    """

    def __init__(self) -> None:
        self._current_trading_date: Optional[date] = None

        # Per-session highs/lows (reset cross-day)
        self._asia_high: Optional[float] = None
        self._asia_low: Optional[float] = None
        self._asia_open: Optional[float] = None
        self._in_asia: bool = False

        self._london_high: Optional[float] = None
        self._london_low: Optional[float] = None
        self._london_open: Optional[float] = None
        self._in_london: bool = False

        self._us_high: Optional[float] = None
        self._us_low: Optional[float] = None
        self._ny_open: Optional[float] = None
        self._in_us_cash: bool = False

        self._after_high: Optional[float] = None
        self._after_low: Optional[float] = None
        self._after_open: Optional[float] = None
        self._in_us_after: bool = False

        # Day-level running (pour pct_in_range)
        self._day_high: Optional[float] = None
        self._day_low: Optional[float] = None

    def reset(self) -> None:
        """Reset complet (test only). Cross-day automatique normalement."""
        self.__init__()

    def update(
        self,
        bar_ts_utc: datetime,
        bar_high: Optional[float],
        bar_low: Optional[float],
        close: Optional[float],
    ) -> dict:
        """Update state + compute 25 features."""
        if bar_ts_utc.tzinfo is None:
            raise ValueError(
                f"SessionsFineCalculator.update : bar_ts_utc doit etre tz-aware UTC, "
                f"obtenu naive {bar_ts_utc}"
            )

        # NaN handling
        if any(v is None or (isinstance(v, float) and np.isnan(v))
               for v in (bar_high, bar_low, close)):
            return self._empty_features()

        bar_high = float(bar_high)
        bar_low = float(bar_low)
        close = float(close)

        ts_et = bar_ts_utc.astimezone(ET)
        trading_date = self._compute_trading_date(ts_et)

        # Cross-day reset detection
        if self._current_trading_date is None:
            self._current_trading_date = trading_date
        elif trading_date != self._current_trading_date:
            # Reset toutes les sessions
            self._asia_high = self._asia_low = self._asia_open = None
            self._london_high = self._london_low = self._london_open = None
            self._us_high = self._us_low = self._ny_open = None
            self._after_high = self._after_low = self._after_open = None
            self._day_high = self._day_low = None
            self._in_asia = self._in_london = False
            self._in_us_cash = self._in_us_after = False
            self._current_trading_date = trading_date

        # Determination session active
        segment = self._compute_segment(ts_et)
        is_in_asia = segment == "asia"
        is_in_london = segment == "london"
        is_in_us_cash = segment == "us_cash"
        is_in_us_after = segment == "us_after"
        is_ib_window = (
            is_in_us_cash and ts_et.time() < IB_END_ET
        )

        # ─── Update per-session running highs/lows + opens ───
        if is_in_asia:
            if not self._in_asia:
                self._asia_open = close
                self._asia_high = bar_high
                self._asia_low = bar_low
                self._in_asia = True
            else:
                self._asia_high = max(self._asia_high, bar_high)
                self._asia_low = min(self._asia_low, bar_low)

        if is_in_london:
            if not self._in_london:
                self._london_open = close
                self._london_high = bar_high
                self._london_low = bar_low
                self._in_london = True
            else:
                self._london_high = max(self._london_high, bar_high)
                self._london_low = min(self._london_low, bar_low)

        if is_in_us_cash:
            if not self._in_us_cash:
                self._ny_open = close
                self._us_high = bar_high
                self._us_low = bar_low
                self._in_us_cash = True
            else:
                self._us_high = max(self._us_high, bar_high)
                self._us_low = min(self._us_low, bar_low)

        if is_in_us_after:
            if not self._in_us_after:
                self._after_open = close
                self._after_high = bar_high
                self._after_low = bar_low
                self._in_us_after = True
            else:
                self._after_high = max(self._after_high, bar_high)
                self._after_low = min(self._after_low, bar_low)

        # Day-level running (somme des sessions trading_date)
        self._day_high = (
            bar_high if self._day_high is None
            else max(self._day_high, bar_high)
        )
        self._day_low = (
            bar_low if self._day_low is None
            else min(self._day_low, bar_low)
        )

        # pct_in_range : position dans la range journaliere
        if self._day_high is not None and self._day_low is not None:
            range_size = self._day_high - self._day_low
            if range_size > 0:
                pct_in_range = (close - self._day_low) / range_size
            else:
                pct_in_range = 0.5
        else:
            pct_in_range = np.nan

        # mins_et = minutes depuis minuit ET
        mins_et = ts_et.hour * 60 + ts_et.minute

        return {
            # Booleans session active
            "is_in_asia": bool(is_in_asia),
            "is_in_london": bool(is_in_london),
            "is_in_us_cash": bool(is_in_us_cash),
            "is_in_us_after": bool(is_in_us_after),
            "is_ib_window": bool(is_ib_window),
            # Metadonnees
            "session_segment": segment,
            "mins_et": int(mins_et),
            # Highs/lows par session
            "asia_high": self._asia_high if self._asia_high is not None else np.nan,
            "asia_low": self._asia_low if self._asia_low is not None else np.nan,
            "london_high": (
                self._london_high if self._london_high is not None else np.nan
            ),
            "london_low": (
                self._london_low if self._london_low is not None else np.nan
            ),
            "us_high": self._us_high if self._us_high is not None else np.nan,
            "us_low": self._us_low if self._us_low is not None else np.nan,
            "after_high": (
                self._after_high if self._after_high is not None else np.nan
            ),
            "after_low": (
                self._after_low if self._after_low is not None else np.nan
            ),
            # Opens
            "asia_open": self._asia_open if self._asia_open is not None else np.nan,
            "london_open": (
                self._london_open if self._london_open is not None else np.nan
            ),
            "ny_open": self._ny_open if self._ny_open is not None else np.nan,
            "after_open": (
                self._after_open if self._after_open is not None else np.nan
            ),
            # Distances pct aux opens
            "dist_asia_open_pct": self._dist_pct(close, self._asia_open),
            "dist_london_open_pct": self._dist_pct(close, self._london_open),
            "dist_ny_open_pct": self._dist_pct(close, self._ny_open),
            "dist_after_open_pct": self._dist_pct(close, self._after_open),
            # Misc
            "pct_in_range": pct_in_range,
            "is_cash_session": bool(is_in_us_cash),
        }

    @staticmethod
    def _compute_trading_date(ts_et: datetime) -> date:
        """Determine session_date_trading CME (reset 18:00 ET)."""
        if ts_et.time() >= ASIA_START_ET:
            return (ts_et + timedelta(days=1)).date()
        return ts_et.date()

    @staticmethod
    def _compute_segment(ts_et: datetime) -> str:
        """Determine session segment active.

        Returns: 'asia' / 'london' / 'us_cash' / 'us_after'
        """
        t = ts_et.time()
        if t < ASIA_END_ET:
            return "asia"  # 00:00-03:00 ET (suite Asia depuis veille 18:00)
        if t < LONDON_END_ET:
            return "london"  # 03:00-09:30 ET
        if t < CASH_END_ET:
            return "us_cash"  # 09:30-16:00 ET
        if t < AFTER_END_ET:
            return "us_after"  # 16:00-18:00 ET
        # 18:00-23:59 ET = Asia (debut nouveau session_date_trading)
        return "asia"

    @staticmethod
    def _dist_pct(close: float, ref: Optional[float]) -> float:
        """(close - ref) / ref * 100. NaN si ref None ou 0."""
        if ref is None or ref == 0:
            return np.nan
        return (close - ref) / ref * 100.0

    @staticmethod
    def _empty_features() -> dict:
        """Features defaut pour input NaN."""
        return {
            "is_in_asia": False,
            "is_in_london": False,
            "is_in_us_cash": False,
            "is_in_us_after": False,
            "is_ib_window": False,
            "session_segment": "off",
            "mins_et": 0,
            "asia_high": np.nan,
            "asia_low": np.nan,
            "london_high": np.nan,
            "london_low": np.nan,
            "us_high": np.nan,
            "us_low": np.nan,
            "after_high": np.nan,
            "after_low": np.nan,
            "asia_open": np.nan,
            "london_open": np.nan,
            "ny_open": np.nan,
            "after_open": np.nan,
            "dist_asia_open_pct": np.nan,
            "dist_london_open_pct": np.nan,
            "dist_ny_open_pct": np.nan,
            "dist_after_open_pct": np.nan,
            "pct_in_range": np.nan,
            "is_cash_session": False,
        }


def compute_sessions_fine_features(
    df: pd.DataFrame,
    ts_col: str = "ts_utc",
) -> pd.DataFrame:
    """Batch compute (mode backtest dataset).

    Args:
        df : DataFrame avec ts_utc, bar_high, bar_low, close.
        ts_col : nom colonne timestamp UTC.

    Returns:
        DataFrame copie + 25 colonnes ajoutees.

    Raises:
        ValueError : si colonne manquante.
    """
    required = [ts_col, "bar_high", "bar_low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"compute_sessions_fine_features : colonnes manquantes {missing}"
        )

    result = df.copy()
    calc = SessionsFineCalculator()
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
        ))

    features_df = pd.DataFrame(rows, index=result.index)
    for col in features_df.columns:
        result[col] = features_df[col].values
    return result
