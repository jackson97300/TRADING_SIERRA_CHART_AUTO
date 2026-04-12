"""
bot_config.py — Configuration centralisee du Bot MIA V2
========================================================

Source unique de tous les parametres de trading.
Modifier ICI, pas dans les modules individuels.

Auteur : MIA Trading System
Date   : 2026-04-01
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class InstrumentConfig:
    """Configuration par instrument."""
    symbol: str
    tick_size: float
    tick_value: float       # Valeur en $ d'1 tick (micro)
    contract: str           # ex: ESM26-CME
    max_contracts: int = 1  # Phase validation = 1 micro
    atr_sl_mult: float = 0.08   # SL = ATR * mult
    rr_ratio: float = 2.0       # TP = SL * R:R


ES = InstrumentConfig(
    symbol="ES",
    tick_size=0.25,
    tick_value=1.25,        # Micro ES = $1.25/tick
    contract="ESM26-CME",
)

NQ = InstrumentConfig(
    symbol="NQ",
    tick_size=0.25,
    tick_value=0.50,        # Micro NQ = $0.50/tick
    contract="NQM26-CME",
)

INSTRUMENTS: Dict[str, InstrumentConfig] = {"ES": ES, "NQ": NQ}


@dataclass
class RiskConfig:
    """Parametres de gestion du risque."""
    # Daily limits
    max_daily_loss_usd: float = 500.0       # Kill switch apres -$500 (si check enabled)
    # NOTE 2026-04-12 : check desactive pour phase collecte (pas de kill journalier
    # pendant la collecte de donnees, sur demande Jackson).
    # Remettre a True avant passage en live reel.
    daily_loss_check_enabled: bool = False  # False = phase collecte (kill desactive)
    max_daily_trades: int = 10              # Max 10 trades/jour par instrument
    max_drawdown_intraday_usd: float = 300.0  # Pause si drawdown > $300

    # Position sizing (Half-Kelly)
    account_size_usd: float = 50000.0       # Taille du compte
    kelly_fraction: float = 0.5             # Half-Kelly (conservateur)
    max_risk_per_trade_pct: float = 1.0     # Max 1% du compte par trade

    # Circuit breaker
    consecutive_losses_pause: int = 3       # 3 pertes → pause
    pause_duration_minutes: int = 30        # Pause 30 minutes
    cooldown_after_win_seconds: int = 120   # 2 min entre les trades

    # Position limits
    max_positions_total: int = 1            # 1 position max (tous instruments)
    max_positions_per_instrument: int = 1   # 1 par instrument

    # Davey backtest-vs-live kill rule (Building Winning Algo Systems, 2014)
    # Si le drawdown live depasse N x le drawdown max observe en backtest,
    # le systeme s'arrete automatiquement — le comportement live a diverge
    # significativement du backtest et le modele n'est probablement plus valide.
    # Mettre a 0.0 pour desactiver cette regle (valeur par defaut = off).
    # A mettre a jour manuellement apres chaque training LightGBM majeur :
    #   backtest_max_dd_usd = metrics_from_train_lightgbm['max_drawdown_usd']
    backtest_max_dd_usd: float = 0.0        # $ max DD observe en backtest (0 = desactive)
    kill_dd_multiplier: float = 1.75        # Davey: 1.5 agressif, 2.0 prudent, 1.75 milieu


@dataclass
class SessionConfig:
    """Parametres de session."""
    # Horaires trading (Eastern Time)
    # H24 = toutes sessions (Asia 18:00-03:00, London 03:00-09:30, US 09:30-16:00)
    rth_start_hour: int = 0
    rth_start_minute: int = 0
    rth_end_hour: int = 23
    rth_end_minute: int = 59
    all_sessions: bool = True               # True = trade Asia/London/US

    # Pre-trade gates
    no_trade_first_minutes: int = 0         # 0 = pas de delai en H24
    eod_flatten_minutes_before: int = 0     # 0 = pas de flatten auto en H24
    time_exit_minutes: int = 90             # Fermer si stagnant > 90 min

    # Regime filter
    min_atr_ticks: float = 10.0             # Pas de trade si ATR < 10 ticks
    max_spread_ticks: float = 2.0           # Pas de trade si spread > 2 ticks


@dataclass
class SignalConfig:
    """Parametres du signal engine."""
    # Seuils LightGBM
    min_score_buy: float = 0.55             # Score minimum pour BUY
    min_score_sell: float = 0.55            # Score minimum pour SELL

    # Seuils GO/NO-GO
    min_profit_factor: float = 1.3
    min_ev_per_trade: float = 1.0           # En ticks
    min_win_rate: float = 0.45

    # MenthorQ gates
    block_long_if_gamma_negative: bool = True    # Pas de long si gamma negatif
    block_short_if_gamma_positive: bool = False  # Short OK meme en gamma positif


@dataclass
class DTCConfig:
    """Parametres de connexion DTC."""
    host: str = "127.0.0.1"
    port: int = 11099
    protocol: str = "json"
    reconnect_delay_seconds: int = 5
    heartbeat_interval_seconds: int = 10
    timeout_seconds: int = 30


@dataclass
class BotConfig:
    """Configuration complete du bot."""
    risk: RiskConfig = field(default_factory=RiskConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    dtc: DTCConfig = field(default_factory=DTCConfig)
    instruments: Dict[str, InstrumentConfig] = field(default_factory=lambda: INSTRUMENTS)

    # Modes
    paper_trading: bool = True              # TOUJOURS paper en Phase 1
    log_level: str = "INFO"
    trade_journal_path: str = "DATA/JOURNAL"
    model_path: str = "DATA/MODELS"

    def get_instrument(self, symbol: str) -> InstrumentConfig:
        return self.instruments.get(symbol.upper(), ES)


# Singleton
CONFIG = BotConfig()
