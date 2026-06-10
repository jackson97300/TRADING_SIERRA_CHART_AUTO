"""
Strategies de trading rule-based — MIA V2 (17/04/2026)

Deux strategies validees empiriquement sur 70j ES + 68j NQ :

  1. DivOptim     : divergence avec entry delay + confirmation volume
                    Best PF stable : ES 1.61 (delay=2), NQ 1.49 (delay=1)

  2. DoubleTopBot : double top / double bottom avec direction CVD alignee
                    Best PF : ES 1.27 (ES only, NQ fragile exclu)

Framework : classes avec contrat (signals, sl_ticks, rr, max_bars).
Consommees par CORE/backtest_strategies.py.

Rules de deploy (CLAUDE.md) :
  - 1 position max par instrument
  - Sessions US only (09:30-16:00 ET)
  - Max 5 trades/jour par instrument
  - SL/TP fixe (pas de trailing phase 1)
  - R:R 1:2 (TP = 2 x SL distance)
  - Max 40 bars timeout (~40 min)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# BASE STRATEGY
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StrategyConfig:
    """Config commune (overridable par strategie)."""
    rr: float = 2.0               # TP = rr * SL
    max_bars: int = 40            # timeout ~40 min
    sl_min_ticks: float = 5.0     # clip bas du SL
    sl_max_ticks: float = 30.0    # clip haut du SL
    entry_delay: int = 0          # nombre de bars a attendre apres signal
    max_trades_per_day: int = 5   # rule CLAUDE.md
    session_filter: bool = True   # US RTH only (09:30-16:00 ET)


class Strategy:
    """Contrat commun : signals + sizing + rules.

    Subclasses doivent implementer :
      - name : str (identifiant unique)
      - applicable_symbols : set[str] (ex: {"ES"} ou {"ES", "NQ"})
      - signals(df) -> pd.Series int : +1 BUY, -1 SELL, 0 NONE
      - sl_ticks(df, pos) -> float : distance SL en ticks pour la barre pos
    """

    name: str = "BASE"
    applicable_symbols: set[str] = {"ES", "NQ"}
    config: StrategyConfig = StrategyConfig()

    def signals(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        raise NotImplementedError

    def confirm_at_entry(self, df: pd.DataFrame, entry_pos: int) -> bool:
        """Defaut : pas de confirmation additionnelle. Overridable."""
        return True

    def can_trade_symbol(self, symbol: str) -> bool:
        return symbol in self.applicable_symbols


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 1 — DIV OPTIM (delay + rvol)
# ─────────────────────────────────────────────────────────────────────────────

class DivOptimStrategy(Strategy):
    """Divergence selective avec entry delay + confirmation volume.

    Entry rules :
      - delta_divergence_clean != 0 (trigger fix 17/04, Daily OHLC Lopez)
      - div_confluence_dmp >= min_confluence (defaut: 2)
      - sur la barre d'entry (t + entry_delay) : rvol >= rvol_min

    SL : div_at_key_level_ticks + sl_buffer, clip [5, 30]
    TP : 2 x SL

    Empirique 70j ES / 68j NQ :
      ES delay=2 rvol>=1.5 : n=120, WR=45.8%, PF=1.61, +39R
      NQ delay=1 rvol>=1.5 : n=145, WR=42.8%, PF=1.49, +41R
    """

    name = "DivOptim"
    applicable_symbols = {"ES", "NQ"}

    def __init__(
        self,
        symbol: str,
        min_confluence: int = 2,
        rvol_min: float = 1.5,
        sl_buffer_ticks: float = 3.0,
        entry_delay: Optional[int] = None,
    ):
        self.symbol = symbol.upper()
        self.min_confluence = min_confluence
        self.rvol_min = rvol_min
        self.sl_buffer_ticks = sl_buffer_ticks
        # Delay tune par instrument (Chantier 1 best stable)
        if entry_delay is None:
            entry_delay = 2 if self.symbol == "ES" else 1
        self.config = StrategyConfig(entry_delay=entry_delay)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        """Retourne +1/-1/0 pour chaque bar (signal brut, sans delay)."""
        required = ["delta_divergence_clean", "div_confluence_dmp",
                    "rvol", "div_at_key_level_ticks"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"{self.name}: features manquantes {missing}")

        dd = pd.to_numeric(df["delta_divergence_clean"], errors="coerce").fillna(0).astype(int)
        conf = pd.to_numeric(df["div_confluence_dmp"], errors="coerce").fillna(0).astype(int)
        base_mask = (dd != 0) & (conf >= self.min_confluence)
        return pd.Series(np.where(base_mask, dd, 0), index=df.index, dtype=int)

    def confirm_at_entry(self, df: pd.DataFrame, entry_pos: int) -> bool:
        """Confirmation rvol sur la barre d'entry (apres delay)."""
        if self.rvol_min <= 0:
            return True
        if entry_pos >= len(df):
            return False
        rv = df["rvol"].iloc[entry_pos]
        if pd.isna(rv):
            return False
        return float(rv) >= self.rvol_min

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        raw = df["div_at_key_level_ticks"].iloc[pos]
        if pd.isna(raw):
            # Fallback : SL moyen si pas de niveau reference
            return 12.0
        val = float(raw) + self.sl_buffer_ticks
        return max(self.config.sl_min_ticks, min(self.config.sl_max_ticks, val))


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 2 — DOUBLE TOP / DOUBLE BOTTOM (retest + cvd direction)
# ─────────────────────────────────────────────────────────────────────────────

class DoubleTopBottomStrategy(Strategy):
    """Double top / double bottom avec confirmation direction CVD.

    Entry rules SHORT (double top) :
      - retest_high_delta_div == 1 (retest recent avec delta div)
      - bars_since_retest_high <= max_bars_since
      - cvd_day_dir <= cvd_max_for_short (defaut 0, session baissiere ou neutre)

    Entry rules LONG (double bottom) :
      - retest_low_delta_div == 1
      - bars_since_retest_low <= max_bars_since
      - cvd_day_dir >= cvd_min_for_long (defaut 0)

    SL : div_at_key_level + sl_buffer si dispo, sinon 15 ticks. Clip [8, 30].
    TP : 2 x SL

    Empirique 70j ES : n=750, WR=46.8%, PF=1.27, +93R
    NQ : exclu (edge fragile, PF chute a 1.03 apres filtres)
    """

    name = "DoubleTopBottom"
    applicable_symbols = {"ES"}  # NQ fragile, exclus phase 1

    def __init__(
        self,
        symbol: str,
        max_bars_since: int = 5,
        sl_buffer_ticks: float = 5.0,
        sl_default_ticks: float = 15.0,
    ):
        self.symbol = symbol.upper()
        self.max_bars_since = max_bars_since
        self.sl_buffer_ticks = sl_buffer_ticks
        self.sl_default_ticks = sl_default_ticks
        self.config = StrategyConfig(
            entry_delay=0,
            sl_min_ticks=8.0,  # SL plus large que div
        )

    def signals(self, df: pd.DataFrame) -> pd.Series:
        required = ["retest_high_delta_div", "retest_low_delta_div",
                    "bars_since_retest_high", "bars_since_retest_low",
                    "cvd_day_dir"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"{self.name}: features manquantes {missing}")

        rhdv = pd.to_numeric(df["retest_high_delta_div"], errors="coerce").fillna(0)
        rldv = pd.to_numeric(df["retest_low_delta_div"], errors="coerce").fillna(0)
        bsrh = pd.to_numeric(df["bars_since_retest_high"], errors="coerce").fillna(999)
        bsrl = pd.to_numeric(df["bars_since_retest_low"], errors="coerce").fillna(999)
        cvd = pd.to_numeric(df["cvd_day_dir"], errors="coerce").fillna(0)

        # SHORT (double top) : retest high + div + cvd baissier ou neutre
        short_mask = (rhdv == 1) & (bsrh <= self.max_bars_since) & (cvd <= 0)
        # LONG (double bottom) : retest low + div + cvd haussier ou neutre
        long_mask = (rldv == 1) & (bsrl <= self.max_bars_since) & (cvd >= 0)

        out = pd.Series(0, index=df.index, dtype=int)
        out[long_mask] = 1
        out[short_mask] = -1
        # Safety : si les 2 masks sont True simultanement (theoriquement impossible),
        # priorite au signal dont bars_since est le plus recent
        both = long_mask & short_mask
        if both.any():
            # Choix : le plus recent (bsr min) gagne
            out.loc[both & (bsrl <= bsrh)] = 1
            out.loc[both & (bsrl > bsrh)] = -1
        return out

    def confirm_at_entry(self, df: pd.DataFrame, entry_pos: int) -> bool:
        return True  # pas de confirmation additionnelle apres signal

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        if "div_at_key_level_ticks" in df.columns:
            raw = df["div_at_key_level_ticks"].iloc[pos]
            if pd.notna(raw):
                val = float(raw) + self.sl_buffer_ticks
                return max(self.config.sl_min_ticks,
                           min(self.config.sl_max_ticks, val))
        return self.sl_default_ticks


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 3 — BATTLE NAVALE (score buyer/seller + confluence niveau option)
# ─────────────────────────────────────────────────────────────────────────────

class BattleNavaleStrategy(Strategy):
    """Score Battle Navale V2 — refactor 18/04/2026 apres diagnostic agent.

    Concept V1 (doc DOCUMENTATION_BATAILLE_NAVALE_4_CHARTS.md) :
    setup pro = CLUSTER de conviction + EDGE imbalance + NIVEAU directionnel.
    Jackson trade ca manuellement depuis des mois (edge confirme en live).

    Refactor cle (diagnostic 18/04) :
      V1 ancien (echec PF 0.18 NQ) : score instantane barre-par-barre, 14
      niveaux melanges (pas de direction), SL fixe 12t qui massacre NQ.

      V2 nouveau :
        1. CLUSTER : rolling window (window barres), min K events de conviction
        2. EDGE RECENT : fp_edge_buy/sell dans 3 dernieres barres (plus selectif
           que bar_edge : 36% vs 63% NQ)
        3. CONTRE-INDICATION : pas d'edge oppose recent (= faux signal)
        4. NIVEAU DIRECTIONNEL : LONG proche support (dist negative proche 0)
           SHORT proche resistance (dist positive proche 0)
        5. SL derriere le NIVEAU qui a valide l'entry (pas un fixe) + buffer

    Composantes conviction (features event-based VIVANTES) :
      UP  = bn_absorb_bid + bn_long_up + bar_long_up_bar    (clip 0/1 presence)
      DN  = bn_absorb_ask + bn_long_dn + bar_long_dn_bar

    Apres validation fix 3.7.6 (5-7 jours post-18/04), activer use_full_features :
      UP += bn_color_up + bn_color_up_2 + rotation_up
      DN += bn_color_dn + bn_color_dn_2 + rotation_dn

    Empirique V1 : PF 2.63 train / 1.49 test. A reproduire.
    """

    name = "BattleNavale"
    applicable_symbols = {"ES", "NQ"}

    # Niveaux directionnels : SUPPORT (LONG entry) vs RESISTANCE (SHORT entry)
    SUPPORT_COLS = [
        "dist_mq_put", "dist_mq_put_0dte", "dist_mq_hvl",
        "dist_gex_nearest_dn", "dist_swing_low",
        "dist_cur_val", "dist_prev_val",
        "dist_blind_nearest_dn",
    ]
    RESISTANCE_COLS = [
        "dist_mq_call", "dist_mq_call_0dte",
        "dist_gex_nearest_up", "dist_swing_high",
        "dist_cur_vah", "dist_prev_vah",
        "dist_blind_nearest_up",
    ]

    def __init__(
        self,
        symbol: str,
        window: int = 5,              # fenetre cluster (bars)
        min_cluster: int = 2,         # min events dans la fenetre
        max_dist_ticks: Optional[float] = None,  # default scale ATR par symbol
        use_full_features: bool = False,  # True = + color/rotation apres 3.7.6
        sl_buffer_ticks: float = 3.0,
    ):
        self.symbol = symbol.upper()
        self.window = window
        self.min_cluster = min_cluster
        self.use_full_features = use_full_features
        self.sl_buffer_ticks = sl_buffer_ticks
        # Scale par symbol (ATR NQ ~2x ES)
        if max_dist_ticks is None:
            max_dist_ticks = 15.0 if self.symbol == "ES" else 30.0
        self.max_dist_ticks = max_dist_ticks
        # SL adaptatif : niveau + buffer. Limites pour eviter cas extremes.
        sl_min = 8.0  if self.symbol == "ES" else 15.0
        sl_max = 25.0 if self.symbol == "ES" else 50.0
        self.config = StrategyConfig(
            entry_delay=0,
            sl_min_ticks=sl_min,
            sl_max_ticks=sl_max,
        )

    def _num(self, df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    def _compute_conviction(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Retourne (conviction_up, conviction_dn) : presence 0/1 par barre."""
        up_raw = (self._num(df, "bn_absorb_bid").astype(int)
                  + self._num(df, "bn_long_up").astype(int)
                  + self._num(df, "bar_long_up_bar").astype(int))
        dn_raw = (self._num(df, "bn_absorb_ask").astype(int)
                  + self._num(df, "bn_long_dn").astype(int)
                  + self._num(df, "bar_long_dn_bar").astype(int))
        if self.use_full_features:
            up_raw = (up_raw
                      + self._num(df, "bn_color_up").astype(int)
                      + self._num(df, "bn_color_up_2").astype(int)
                      + self._num(df, "rotation_up").astype(int))
            dn_raw = (dn_raw
                      + self._num(df, "bn_color_dn").astype(int)
                      + self._num(df, "bn_color_dn_2").astype(int)
                      + self._num(df, "rotation_dn").astype(int))
        # Clip 0/1 : presence sur la barre (pas intensite)
        conviction_up = up_raw.clip(0, 1)
        conviction_dn = dn_raw.clip(0, 1)
        return conviction_up, conviction_dn

    def _near_level_directional(self, df: pd.DataFrame,
                                 cols: list[str], side: int) -> pd.Series:
        """True si au moins un niveau directionnel est proche du prix.

        side = -1 : support (dist<0 = niveau sous prix). On veut dist proche 0
                    depuis le cote negatif, ou juste au-dessus (buffer +2t).
        side = +1 : resistance (dist>0 = niveau au-dessus). On veut proche 0
                    depuis le cote positif, ou juste en-dessous (buffer -2t).
        """
        ok = pd.Series(False, index=df.index)
        for c in cols:
            if c not in df.columns:
                continue
            v = pd.to_numeric(df[c], errors="coerce")
            if side == -1:
                # Support : dist dans [-max_dist, +2t] (sous ou juste au-dessus)
                ok = ok | ((v >= -self.max_dist_ticks) & (v <= 2))
            else:
                # Resistance : dist dans [-2t, +max_dist]
                ok = ok | ((v >= -2) & (v <= self.max_dist_ticks))
        return ok

    def _nearest_support_dist(self, df: pd.DataFrame, pos: int) -> Optional[float]:
        """Distance abs au support le plus proche pour SL LONG (ticks)."""
        dists = []
        for c in self.SUPPORT_COLS:
            if c not in df.columns:
                continue
            v = df[c].iloc[pos]
            if pd.isna(v):
                continue
            v = float(v)
            # Support valide = dist dans la fenetre (sous prix ou au-dessus <=2t)
            if -self.max_dist_ticks <= v <= 2:
                dists.append(abs(v))
        return min(dists) if dists else None

    def _nearest_resistance_dist(self, df: pd.DataFrame, pos: int) -> Optional[float]:
        dists = []
        for c in self.RESISTANCE_COLS:
            if c not in df.columns:
                continue
            v = df[c].iloc[pos]
            if pd.isna(v):
                continue
            v = float(v)
            if -2 <= v <= self.max_dist_ticks:
                dists.append(abs(v))
        return min(dists) if dists else None

    def signals(self, df: pd.DataFrame) -> pd.Series:
        """Retourne +1 (LONG) / -1 (SHORT) / 0 (NONE) par barre."""
        conviction_up, conviction_dn = self._compute_conviction(df)
        cluster_up = conviction_up.rolling(self.window, min_periods=1).sum()
        cluster_dn = conviction_dn.rolling(self.window, min_periods=1).sum()

        # Edge recent (3 barres) — fp_edge plus selectif (36%) que bar_edge (63%)
        edge_buy_recent  = (self._num(df, "fp_edge_buy").astype(int)
                            .rolling(3, min_periods=1).sum() >= 1)
        edge_sell_recent = (self._num(df, "fp_edge_sell").astype(int)
                            .rolling(3, min_periods=1).sum() >= 1)

        # Niveau directionnel
        near_support    = self._near_level_directional(df, self.SUPPORT_COLS, -1)
        near_resistance = self._near_level_directional(df, self.RESISTANCE_COLS, +1)

        # Signal LONG : cluster up >= min ET edge_buy recent ET near support
        # ET PAS edge_sell recent (contradiction) ET pas de cluster oppose
        long_mask = (
            (cluster_up >= self.min_cluster)
            & edge_buy_recent
            & (~edge_sell_recent)
            & near_support
            & (cluster_dn < self.min_cluster)
        )
        short_mask = (
            (cluster_dn >= self.min_cluster)
            & edge_sell_recent
            & (~edge_buy_recent)
            & near_resistance
            & (cluster_up < self.min_cluster)
        )

        out = pd.Series(0, index=df.index, dtype=int)
        out[long_mask] = 1
        out[short_mask] = -1
        return out

    def confirm_at_entry(self, df: pd.DataFrame, entry_pos: int) -> bool:
        return True

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        """SL derriere le niveau qui a valide l'entry + buffer.

        LONG : SL = distance au support le plus proche + buffer
               (exemple : support a 8 ticks sous prix, SL a 11 ticks = 8+3)
        SHORT : SL = distance resistance + buffer
        """
        # Direction de la barre du signal
        # On n'a pas direct acces au direction ici, on deduit de conviction
        conviction_up, conviction_dn = self._compute_conviction(df)
        cu = conviction_up.rolling(self.window, min_periods=1).sum().iloc[pos]
        cd = conviction_dn.rolling(self.window, min_periods=1).sum().iloc[pos]

        if cu >= self.min_cluster and cu > cd:
            # LONG : SL sous le support
            dist = self._nearest_support_dist(df, pos)
        else:
            # SHORT : SL au-dessus resistance
            dist = self._nearest_resistance_dist(df, pos)

        if dist is None:
            # Fallback : SL median (ne devrait pas arriver car signals filtre deja)
            fallback = 12.0 if self.symbol == "ES" else 25.0
            return fallback

        sl = dist + self.sl_buffer_ticks
        return max(self.config.sl_min_ticks,
                   min(self.config.sl_max_ticks, sl))


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 4 — TREND HVN REBOUND (agent market-analyst)
# ─────────────────────────────────────────────────────────────────────────────

class TrendHVNReboundStrategy(Strategy):
    """Trend day confirme + rebond sur HVN defendu + absorption cluster.

    NOTE : n'utilise PAS ma_trend (feature cassee 330/331=-1 selon agent).
    Trend = cvd_day_dir + vwap_ma_align + trend_day_probability.
    """
    name = "TrendHVNRebound"
    applicable_symbols = {"ES", "NQ"}

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        sl_min = 8.0  if self.symbol == "ES" else 15.0
        sl_max = 20.0 if self.symbol == "ES" else 40.0
        self.hvn_ticks = 6 if self.symbol == "ES" else 12
        self.config = StrategyConfig(entry_delay=0, sl_min_ticks=sl_min,
                                     sl_max_ticks=sl_max)

    def _num(self, df, col, default=0.0):
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        cvd_dir = self._num(df, "cvd_day_dir").astype(int)
        vwap_align = self._num(df, "vwap_ma_align").astype(int)
        trend_prob = self._num(df, "trend_day_probability")
        delta_norm = self._num(df, "delta_bar_vol_norm")
        rvol = self._num(df, "rvol")
        # HVN proche
        dist_hvn_above = self._num(df, "dist_session_hvn_above", 999).abs()
        dist_hvn_below = self._num(df, "dist_session_hvn_below", 999).abs()
        # Absorption cluster (3 bars)
        absorb_buy = (self._num(df, "bn_absorb_bid").astype(int)
                      + self._num(df, "rvol_absorb_buy").astype(int)).clip(0, 1)
        absorb_sell = (self._num(df, "bn_absorb_ask").astype(int)
                       + self._num(df, "rvol_absorb_sell").astype(int)).clip(0, 1)
        cluster_buy = absorb_buy.rolling(3, min_periods=1).sum() >= 1
        cluster_sell = absorb_sell.rolling(3, min_periods=1).sum() >= 1

        trend_up = (cvd_dir == 1) & (vwap_align == 1) & (trend_prob >= 0.55)
        trend_dn = (cvd_dir == -1) & (vwap_align == -1) & (trend_prob >= 0.55)

        long_mask = (trend_up & (dist_hvn_below <= self.hvn_ticks)
                     & cluster_buy & (delta_norm > 0.15) & (rvol >= 1.2))
        short_mask = (trend_dn & (dist_hvn_above <= self.hvn_ticks)
                      & cluster_sell & (delta_norm < -0.15) & (rvol >= 1.2))
        out = pd.Series(0, index=df.index, dtype=int)
        out[long_mask] = 1
        out[short_mask] = -1
        return out

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        # SL derriere HVN + 3t buffer
        signals = self.signals(df)
        direction = int(signals.iloc[pos])
        if direction > 0:
            dist = df["dist_session_hvn_below"].iloc[pos] if "dist_session_hvn_below" in df.columns else None
        else:
            dist = df["dist_session_hvn_above"].iloc[pos] if "dist_session_hvn_above" in df.columns else None
        if pd.isna(dist):
            return 12.0 if self.symbol == "ES" else 25.0
        sl = abs(float(dist)) + 3.0
        return max(self.config.sl_min_ticks, min(self.config.sl_max_ticks, sl))


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 5 — DELTA ACCUMULATION SUPPORT (agent feature-engineer)
# ─────────────────────────────────────────────────────────────────────────────

class DeltaAccumSupportStrategy(Strategy):
    """Absorption bid rare + delta retourne + niveau support + cvd bull.

    LONG only (symetrique SHORT moins fiable selon agent 3).
    """
    name = "DeltaAccumSupport"
    applicable_symbols = {"ES", "NQ"}

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        sl_min = 6.0 if self.symbol == "ES" else 12.0
        sl_max = 15.0 if self.symbol == "ES" else 28.0
        self.config = StrategyConfig(entry_delay=0, sl_min_ticks=sl_min,
                                     sl_max_ticks=sl_max)

    def _num(self, df, col, default=0.0):
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        cvd_day = self._num(df, "cvd_day")
        cvd_dir = self._num(df, "cvd_day_dir").astype(int)
        absorb_bid = self._num(df, "bn_absorb_bid").astype(int)
        absorb_ask = self._num(df, "bn_absorb_ask").astype(int)
        delta_norm = self._num(df, "delta_bar_vol_norm")
        diag_imb = self._num(df, "diag_imbalance")
        # Support proche (dist negative entre -10 et 0)
        support_cols = ["dist_mq_put", "dist_mq_hvl",
                        "dist_gex_nearest_dn", "dist_swing_low"]
        near_support = pd.Series(False, index=df.index)
        for c in support_cols:
            if c in df.columns:
                v = self._num(df, c, 0)
                near_support |= ((v >= -10) & (v < 0))
        # Resistance proche (pour SHORT)
        resist_cols = ["dist_mq_call", "dist_gex_nearest_up", "dist_swing_high"]
        near_resist = pd.Series(False, index=df.index)
        for c in resist_cols:
            if c in df.columns:
                v = self._num(df, c, 0)
                near_resist |= ((v > 0) & (v <= 10))
        # Wall check (pas coince entre murs proches)
        next_wall = self._num(df, "next_wall_dist_ticks", 999)
        wall_ok = next_wall >= 8

        long_mask = ((cvd_dir == 1) & (cvd_day > 0) & (absorb_bid == 1)
                     & (delta_norm > 0.15) & (diag_imb > 0.2)
                     & near_support & wall_ok)
        short_mask = ((cvd_dir == -1) & (cvd_day < 0) & (absorb_ask == 1)
                      & (delta_norm < -0.15) & (diag_imb < -0.2)
                      & near_resist & wall_ok)
        out = pd.Series(0, index=df.index, dtype=int)
        out[long_mask] = 1
        out[short_mask] = -1
        return out

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        signals = self.signals(df)
        direction = int(signals.iloc[pos])
        support_cols = (["dist_mq_put", "dist_mq_hvl", "dist_gex_nearest_dn", "dist_swing_low"]
                        if direction > 0
                        else ["dist_mq_call", "dist_gex_nearest_up", "dist_swing_high"])
        dists = []
        for c in support_cols:
            if c not in df.columns: continue
            v = df[c].iloc[pos]
            if pd.notna(v): dists.append(abs(float(v)))
        if not dists:
            return 10.0 if self.symbol == "ES" else 20.0
        sl = min(dists) + 4.0
        return max(self.config.sl_min_ticks, min(self.config.sl_max_ticks, sl))


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 6 — WINNER MORNING SELL (agent backtest-runner, empirique)
# ─────────────────────────────────────────────────────────────────────────────

class WinnerMorningSellStrategy(Strategy):
    """Signature empirique winners existants : SELL 9-11 ET + rvol + vix_regime=1.

    DECOUVERT par analyse des 131 winners actuels vs 229 losers.
    profile_shape=2 TOXIQUE (6% winners vs 16% losers).
    """
    name = "WinnerMorningSell"
    applicable_symbols = {"ES", "NQ"}

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        sl_min = 10.0 if self.symbol == "ES" else 18.0
        sl_max = 22.0 if self.symbol == "ES" else 40.0
        self.config = StrategyConfig(entry_delay=0, sl_min_ticks=sl_min,
                                     sl_max_ticks=sl_max)

    def _num(self, df, col, default=0.0):
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        # Heure ET depuis ts (UTC -> ET = -5 EST ou -4 EDT)
        if "ts" in df.columns:
            ts_utc = pd.to_datetime(pd.to_numeric(df["ts"], errors="coerce"),
                                    unit="ms", utc=True, errors="coerce")
            hour_et = ts_utc.dt.tz_convert("America/New_York").dt.hour
        else:
            hour_et = pd.Series(12, index=df.index)
        in_morning = (hour_et >= 9) & (hour_et <= 11)

        rvol = self._num(df, "rvol")
        vix_reg = self._num(df, "vix_regime").astype(int)
        profile = self._num(df, "profile_shape", -1).astype(int)
        # Niveau resistance proche (SELL = shortable)
        resist_cols = ["dist_mq_call", "dist_gex_nearest_up", "dist_swing_high",
                       "dist_cur_vah"]
        near_resist = pd.Series(False, index=df.index)
        for c in resist_cols:
            if c in df.columns:
                v = self._num(df, c, 0)
                near_resist |= ((v > 0) & (v <= 12))
        # Absorption ask (confirmation)
        absorb_ask = self._num(df, "bn_absorb_ask").astype(int)
        absorb_recent = absorb_ask.rolling(3, min_periods=1).sum() >= 1

        short_mask = (in_morning & (rvol >= 1.2) & (vix_reg == 1)
                      & (profile != 2) & near_resist & absorb_recent)
        out = pd.Series(0, index=df.index, dtype=int)
        out[short_mask] = -1
        return out

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        resist_cols = ["dist_mq_call", "dist_gex_nearest_up",
                       "dist_swing_high", "dist_cur_vah"]
        dists = []
        for c in resist_cols:
            if c not in df.columns: continue
            v = df[c].iloc[pos]
            if pd.notna(v) and float(v) > 0:
                dists.append(float(v))
        if not dists:
            return 15.0 if self.symbol == "ES" else 25.0
        sl = min(dists) + 4.0
        return max(self.config.sl_min_ticks, min(self.config.sl_max_ticks, sl))


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 7 — REVERSAL RARE CAPITULATION (agent feature-engineer)
# ─────────────────────────────────────────────────────────────────────────────

class ReversalRareStrategy(Strategy):
    """bar_long_dn_up (0.4% events) + cvd bear + rvol spike = capitulation LONG.

    Rare mais edge fort theorique. LONG only.
    """
    name = "ReversalRare"
    applicable_symbols = {"ES", "NQ"}

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        sl_min = 5.0 if self.symbol == "ES" else 10.0
        sl_max = 15.0 if self.symbol == "ES" else 25.0
        self.config = StrategyConfig(entry_delay=0, sl_min_ticks=sl_min,
                                     sl_max_ticks=sl_max)

    def _num(self, df, col, default=0.0):
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        reversal = self._num(df, "bar_long_dn_up").astype(int) == 1
        cvd_day = self._num(df, "cvd_day")
        cvd_dir = self._num(df, "cvd_day_dir").astype(int)
        rvol_z = self._num(df, "rvol_zscore")
        delta_norm = self._num(df, "delta_bar_vol_norm")
        diag_imb = self._num(df, "diag_imbalance")
        # Support proche
        support_cols = ["dist_mq_put", "dist_mq_hvl", "dist_swing_low"]
        near_support = pd.Series(False, index=df.index)
        for c in support_cols:
            if c in df.columns:
                v = self._num(df, c, 0)
                near_support |= ((v >= -6) & (v < 0))

        long_mask = (reversal & (cvd_day < 0) & (cvd_dir == -1)
                     & (rvol_z > 1.5) & (delta_norm > 0.25)
                     & (diag_imb > 0.3) & near_support)
        out = pd.Series(0, index=df.index, dtype=int)
        out[long_mask] = 1
        return out

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        support_cols = ["dist_mq_put", "dist_mq_hvl", "dist_swing_low"]
        dists = []
        for c in support_cols:
            if c not in df.columns: continue
            v = df[c].iloc[pos]
            if pd.notna(v): dists.append(abs(float(v)))
        if not dists:
            return 8.0 if self.symbol == "ES" else 15.0
        sl = min(dists) + 3.0
        return max(self.config.sl_min_ticks, min(self.config.sl_max_ticks, sl))


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 8 — EDGE IMBALANCE NQ (agent feature-engineer, NQ only)
# ─────────────────────────────────────────────────────────────────────────────

class EdgeImbalanceNQStrategy(Strategy):
    """fp_edge + niveau directionnel + pas de signal oppose + volume spike.

    NQ only (fp_edge 36% NQ vs 0.6% ES = asymetrie trop forte).
    """
    name = "EdgeImbalanceNQ"
    applicable_symbols = {"NQ"}

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.config = StrategyConfig(entry_delay=0, sl_min_ticks=8.0,
                                     sl_max_ticks=20.0)

    def _num(self, df, col, default=0.0):
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        edge_buy = self._num(df, "fp_edge_buy").astype(int)
        edge_sell = self._num(df, "fp_edge_sell").astype(int)
        rvol_z = self._num(df, "rvol_zscore")
        cvd_day = self._num(df, "cvd_day")
        # Pas de signal oppose dans 3 dernieres barres
        no_opp_sell = edge_sell.rolling(3, min_periods=1).max() == 0
        no_opp_buy = edge_buy.rolling(3, min_periods=1).max() == 0
        # Niveau support proche
        support_cols = ["dist_mq_put", "dist_gex_nearest_dn", "dist_swing_low",
                        "dist_cur_val"]
        near_support = pd.Series(False, index=df.index)
        for c in support_cols:
            if c in df.columns:
                v = self._num(df, c, 0)
                near_support |= ((v >= -8) & (v < 0))
        # Niveau resistance proche
        resist_cols = ["dist_mq_call", "dist_gex_nearest_up",
                       "dist_swing_high", "dist_cur_vah"]
        near_resist = pd.Series(False, index=df.index)
        for c in resist_cols:
            if c in df.columns:
                v = self._num(df, c, 0)
                near_resist |= ((v > 0) & (v <= 8))
        # Espace pour courir
        next_wall = self._num(df, "next_wall_dist_ticks", 999)
        next_wall_is_call = self._num(df, "next_wall_is_call").astype(int)
        room_up = (next_wall_is_call == 0) | (next_wall >= 12)
        room_dn = (next_wall_is_call == 1) | (next_wall >= 12)

        long_mask = ((edge_buy == 1) & no_opp_sell & (rvol_z > 0.5)
                     & (cvd_day >= 0) & near_support & room_up)
        short_mask = ((edge_sell == 1) & no_opp_buy & (rvol_z > 0.5)
                      & (cvd_day <= 0) & near_resist & room_dn)
        out = pd.Series(0, index=df.index, dtype=int)
        out[long_mask] = 1
        out[short_mask] = -1
        return out

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        signals = self.signals(df)
        direction = int(signals.iloc[pos])
        cols = (["dist_mq_put", "dist_gex_nearest_dn", "dist_swing_low", "dist_cur_val"]
                if direction > 0
                else ["dist_mq_call", "dist_gex_nearest_up", "dist_swing_high", "dist_cur_vah"])
        dists = []
        for c in cols:
            if c not in df.columns: continue
            v = df[c].iloc[pos]
            if pd.notna(v): dists.append(abs(float(v)))
        if not dists:
            return 15.0
        sl = min(dists) + 5.0
        return max(self.config.sl_min_ticks, min(self.config.sl_max_ticks, sl))


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN DISCOVERY STRATEGIES (17/04/2026 post-leakage)
# Patterns trouves par scanner direct (PAS de ML intermediaire = pas de leakage)
# ─────────────────────────────────────────────────────────────────────────────

class ESContrarianShortStrategy(Strategy):
    """ES SHORT : IB cassé UP + prix au-dessus MQ Call + proche résistance.

    Pattern trouvé par pattern_discovery.py le 17/04 (n=225, WR 58.2%, PF 1.99
    in-sample sur dataset complet). Contrarian : breakout UP qui rejette le wall
    d'options = retour vers la moyenne. Pas de ML = pas de leakage structurel.
    """
    name = "ESContrarianShort"
    applicable_symbols = {"ES"}

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.config = StrategyConfig(entry_delay=0, sl_min_ticks=8.0,
                                      sl_max_ticks=18.0)

    def _num(self, df, col, default=0.0):
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        ib_up = self._num(df, "ib_broken_up").astype(int)
        above_mq_call = self._num(df, "bool_above_mq_call").astype(int)
        # near_resist = min |dist_*| pour niveaux au-dessus, <= 10 ticks
        resist_cols = ["dist_mq_call", "dist_gex_nearest_up", "dist_swing_high",
                       "dist_cur_vah"]
        near_resist = pd.Series(False, index=df.index)
        for c in resist_cols:
            if c in df.columns:
                v = self._num(df, c, 999)
                near_resist |= ((v > -2) & (v <= 10))
        short_mask = (ib_up == 1) & (above_mq_call == 1) & near_resist
        out = pd.Series(0, index=df.index, dtype=int)
        out[short_mask] = -1
        return out

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        # SL au-dessus de la résistance la plus proche + 4t buffer
        resist_cols = ["dist_mq_call", "dist_gex_nearest_up",
                       "dist_swing_high", "dist_cur_vah"]
        dists = []
        for c in resist_cols:
            if c not in df.columns: continue
            v = df[c].iloc[pos]
            if pd.notna(v) and float(v) > 0:
                dists.append(float(v))
        if not dists:
            return 12.0
        sl = min(dists) + 4.0
        return max(self.config.sl_min_ticks, min(self.config.sl_max_ticks, sl))


class ESTrendVPOCLongStrategy(Strategy):
    """ES LONG : prix au-dessus cur_vpoc + trend up confirmé.

    Pattern trouvé par pattern_discovery.py (n=158, WR 60.8%, PF 2.63 IS).
    Trend continuation classique : prix structurellement au-dessus du point
    de contrôle volume (VPOC) et trend global haussier.
    """
    name = "ESTrendVPOCLong"
    applicable_symbols = {"ES"}

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.config = StrategyConfig(entry_delay=0, sl_min_ticks=8.0,
                                      sl_max_ticks=20.0)

    def _num(self, df, col, default=0.0):
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        above_vpoc = self._num(df, "bool_above_cur_vpoc").astype(int)
        cvd_dir = self._num(df, "cvd_day_dir").astype(int)
        vwap_align = self._num(df, "vwap_ma_align").astype(int)
        trend_up = (cvd_dir == 1) & (vwap_align == 1)
        long_mask = (above_vpoc == 1) & trend_up
        out = pd.Series(0, index=df.index, dtype=int)
        out[long_mask] = 1
        return out

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        # SL sous le VPOC ou swing low
        support_cols = ["dist_cur_vpoc", "dist_swing_low", "dist_cur_val",
                        "dist_session_hvn_below"]
        dists = []
        for c in support_cols:
            if c not in df.columns: continue
            v = df[c].iloc[pos]
            if pd.notna(v):
                vv = float(v)
                if vv < 0:
                    dists.append(abs(vv))
        if not dists:
            return 12.0
        sl = min(dists) + 4.0
        return max(self.config.sl_min_ticks, min(self.config.sl_max_ticks, sl))


class NQPullbackLongStrategy(Strategy):
    """NQ LONG : IB cassé UP + is_double_dist + proche support.

    Pattern trouvé par pattern_discovery.py (n=64, WR 64.1%, PF 3.08 IS).
    Pullback post-breakout IB qui trouve un support sur niveau structurel.
    """
    name = "NQPullbackLong"
    applicable_symbols = {"NQ"}

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.config = StrategyConfig(entry_delay=0, sl_min_ticks=15.0,
                                      sl_max_ticks=35.0)

    def _num(self, df, col, default=0.0):
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        ib_up = self._num(df, "ib_broken_up").astype(int)
        double_dist = self._num(df, "is_double_dist").astype(int)
        support_cols = ["dist_mq_put", "dist_mq_hvl", "dist_gex_nearest_dn",
                        "dist_swing_low"]
        near_support = pd.Series(False, index=df.index)
        for c in support_cols:
            if c in df.columns:
                v = self._num(df, c, -999)
                near_support |= ((v >= -10) & (v <= 2))
        long_mask = (ib_up == 1) & (double_dist == 1) & near_support
        out = pd.Series(0, index=df.index, dtype=int)
        out[long_mask] = 1
        return out

    def sl_ticks(self, df: pd.DataFrame, pos: int) -> float:
        support_cols = ["dist_mq_put", "dist_mq_hvl", "dist_gex_nearest_dn",
                        "dist_swing_low"]
        dists = []
        for c in support_cols:
            if c not in df.columns: continue
            v = df[c].iloc[pos]
            if pd.notna(v) and float(v) < 0:
                dists.append(abs(float(v)))
        if not dists:
            return 22.0
        sl = min(dists) + 5.0
        return max(self.config.sl_min_ticks, min(self.config.sl_max_ticks, sl))


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

def build_strategies_for(symbol: str) -> list[Strategy]:
    """Retourne les strategies applicables a un symbole."""
    strats: list[Strategy] = []
    div = DivOptimStrategy(symbol=symbol)
    if div.can_trade_symbol(symbol):
        strats.append(div)
    dt = DoubleTopBottomStrategy(symbol=symbol)
    if dt.can_trade_symbol(symbol):
        strats.append(dt)
    bn = BattleNavaleStrategy(symbol=symbol, use_full_features=False)
    if bn.can_trade_symbol(symbol):
        strats.append(bn)
    return strats
