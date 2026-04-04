"""Pydantic models pour les 6 panels du dashboard MIA."""
from pydantic import BaseModel


class BotStatusBasic(BaseModel):
    """Statut bot simplifie (tier free)."""

    running: bool = False
    global_status: str = "UNKNOWN"
    last_heartbeat: str = ""


class InstrumentStatus(BaseModel):
    """Statut detaille d'un instrument (ES ou NQ)."""

    enabled: bool = False
    in_position: bool = False
    status: str = ""
    trades_today: int = 0
    wins: int = 0
    losses: int = 0
    pnl_today: float = 0.0
    consecutive_losses: int = 0
    last_rejected: str = ""
    signals_rejected: int = 0


class MarketContextBasic(BaseModel):
    """Contexte marche simplifie (tier free)."""

    vix: float = 0.0
    vix_regime: str = "UNKNOWN"
    atr_es: float = 0.0
    atr_nq: float = 0.0
    vwap_slope_es: float = 0.0
    vwap_slope_nq: float = 0.0


class MarketContextFull(MarketContextBasic):
    """Contexte marche complet (tier premium)."""

    open_type: int = 0
    open_type_label: str = "UNKNOWN"
    open_zone: float = 0.0
    day_type: int = 0
    day_type_label: str = "NON TREND"
    ib_range_ticks: float = 0.0
    ib_broken_up: int = 0
    ib_broken_down: int = 0
    ib_extension_ratio: float = 0.0
    profile_shape: int = 0
    profile_shape_label: str = "D-Shape"
    poc_position: float = 0.0
    vwap_d_side: int = 0
    vwap_triple_align: int = 0
    trend_day_probability: float = 0.0
    session_id: int = 0


class OrderFlowPanel(BaseModel):
    """Panel order flow (tier premium)."""

    delta_bar: float = 0.0
    delta_pct: float = 0.0
    cvd_day: float = 0.0
    cvd_day_dir: int = 0
    rvol: float = 0.0
    rvol_regime: int = 0
    rvol_regime_label: str = "Normal"
    absorption_score: float = 0.0
    absorption_streak: float = 0.0
    price_delta_div: float = 0.0
    climax_signal: float = 0.0
    large_trader_ratio: float = 0.0
    ask_bid_imbalance: float = 0.0
    finish_strength: float = 0.0


class OptionsGammaPanel(BaseModel):
    """Panel options/gamma (tier premium)."""

    dist_mq_call: float = 0.0
    dist_mq_put: float = 0.0
    dist_mq_hvl: float = 0.0
    dist_mq_call_0dte: float = 0.0
    dist_mq_put_0dte: float = 0.0
    dist_gex_nearest_up: float = 0.0
    dist_gex_nearest_dn: float = 0.0
    gex_cluster_count: int = 0
    bool_gex_flip_zone: int = 0
    vix_level: float = 0.0
    vix_regime: int = 0
    dist_vix_call: float = 0.0
    dist_vix_put: float = 0.0
    next_wall_dist_ticks: float = 0.0
    next_wall_is_call: int = 0


class IntermarketPanel(BaseModel):
    """Panel intermarket ES/NQ (tier premium)."""

    cross_delta_agreement: int = 0
    smt_divergence: int = 0
    rolling_correlation: float = 0.0
    price_ratio_slope: float = 0.0
    volume_lead: int = 0
    ltr_slope_diff: float = 0.0
    amd_phase: int = 0
    amd_phase_label: str = "Asia"
    amd_session_bias: float = 0.0
    amd_po3_score: float = 0.0
    amd_po3_bullish: int = 0
    amd_po3_bearish: int = 0
    amd_judas_swing: int = 0
    amd_manip_score: float = 0.0


class SignalEntry(BaseModel):
    """Une entree du journal de signaux."""

    ts: str = ""
    symbol: str = ""
    direction: str = ""
    pnl: float | None = None
    reason: str = ""


class SignalsJournalPanel(BaseModel):
    """Panel signaux et journal (tier premium)."""

    current_signal: str | None = None
    signal_score: float | None = None
    signal_reason: str = ""
    sl_ticks: float | None = None
    tp_ticks: float | None = None
    rr_ratio: float | None = None
    recent_trades: list[SignalEntry] = []
    recent_rejections: list[str] = []


class DashboardResponse(BaseModel):
    """Reponse complete du dashboard."""

    timestamp: str = ""
    tier: str = "free"
    bot_status: BotStatusBasic = BotStatusBasic()
    es: InstrumentStatus | None = None
    nq: InstrumentStatus | None = None
    market_context: MarketContextBasic | MarketContextFull = MarketContextBasic()
    order_flow_es: OrderFlowPanel | None = None
    order_flow_nq: OrderFlowPanel | None = None
    options_gamma_es: OptionsGammaPanel | None = None
    options_gamma_nq: OptionsGammaPanel | None = None
    intermarket: IntermarketPanel | None = None
    signals_journal: SignalsJournalPanel | None = None
    warnings: dict | None = None
