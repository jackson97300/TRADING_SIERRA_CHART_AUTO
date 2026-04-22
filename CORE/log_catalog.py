"""Catalogue de codes de logs MIA V2.

Pierre angulaire du systeme de logs : chaque log DOIT referencer un code stable
de ce catalogue. Zero prose libre = discipline enforced by architecture.

Usage :
    from core.log_catalog import LOG_CODES, LogLevel
    code, level, template = resolve("KILL_DD_DAILY")
    msg = template.format(pnl=-870, limit=-500)
"""

from enum import Enum


class LogLevel(Enum):
    INFO = "INFO"
    ALERTE = "ALERTE"
    MAJEUR = "MAJEUR"
    CRITIQUE = "CRITIQUE"


LEVEL_ACTIONS = {
    LogLevel.CRITIQUE: {"discord": True, "discord_mention": True, "error_file": True, "snapshot": True},
    LogLevel.MAJEUR:   {"discord": True, "discord_mention": False, "error_file": True, "snapshot": False},
    LogLevel.ALERTE:   {"discord": False, "discord_mention": False, "error_file": False, "snapshot": False},
    LogLevel.INFO:     {"discord": False, "discord_mention": False, "error_file": False, "snapshot": False},
}


LOG_CODES = {
    "SIGNAL_RECEIVED":         (LogLevel.INFO,     "trading", "Signal recu : {sym} {direction} score={score:.2f}"),
    "SIGNAL_DEDUPED":          (LogLevel.INFO,     "trading", "Signal {signal_id} deduplique (deja vu)"),
    "SIGNAL_STALE":            (LogLevel.ALERTE,   "trading", "Signal {signal_id} trop ancien ({age_sec}s > {limit}s)"),
    "TRADE_OPEN":              (LogLevel.INFO,     "trading", "Trade ouvert : {sym} {direction} size={size} @ {price}"),
    "TRADE_CLOSE_TP":          (LogLevel.INFO,     "trading", "Trade ferme TP : {sym} pnl={pnl:.2f}t"),
    "TRADE_CLOSE_SL":          (LogLevel.INFO,     "trading", "Trade ferme SL : {sym} pnl={pnl:.2f}t"),
    "TRADE_CLOSE_TRAIL":       (LogLevel.INFO,     "trading", "Trade ferme trailing : {sym} pnl={pnl:.2f}t"),
    "TRADE_CLOSE_BE":          (LogLevel.INFO,     "trading", "Trade ferme breakeven : {sym} pnl={pnl:.2f}t"),
    "TRADE_CLOSE_MANUAL":      (LogLevel.ALERTE,   "trading", "Trade ferme manuel : {sym} raison={reason}"),
    "TRADE_CLOSE_KILL":        (LogLevel.MAJEUR,   "trading", "Trade flatten force par kill-switch : {sym}"),
    "TRADE_CLOSE_TIMEOUT":     (LogLevel.ALERTE,   "trading", "Trade ferme timeout : {sym} bars_held={bars}"),

    "DTC_CONNECT":             (LogLevel.INFO,     "execution", "DTC connecte sur {host}:{port}"),
    "DTC_DISCONNECT":          (LogLevel.ALERTE,   "execution", "DTC deconnecte : {reason}"),
    "DTC_DISCONNECT_SESSION":  (LogLevel.CRITIQUE, "execution", "DTC deconnecte pendant session trading : {reason}"),
    "DTC_RECONNECT":           (LogLevel.INFO,     "execution", "DTC reconnexion reussie apres {attempts} tentatives"),
    "ORDER_SUBMIT":            (LogLevel.INFO,     "execution", "Ordre envoye : {sym} {type} {direction} qty={qty}"),
    "ORDER_FILL":              (LogLevel.INFO,     "execution", "Fill : order_id={order_id} @ {price} slippage={slip}t"),
    "ORDER_REJECT":            (LogLevel.MAJEUR,   "execution", "Ordre refuse broker : {sym} code={err_code} msg={err_msg}"),
    "ORDER_ACK_TIMEOUT":       (LogLevel.MAJEUR,   "execution", "Timeout ACK broker sur ordre {order_id} apres {timeout}s"),
    "OCO_CANCEL_OPPOSITE":     (LogLevel.INFO,     "execution", "OCO cancel oppose : {order_id}"),
    "OCO_ORPHAN_DETECTED":     (LogLevel.CRITIQUE, "execution", "Position orpheline detectee : {order_id}, cancel force"),
    "TRAILING_ACTIVATED":      (LogLevel.INFO,     "execution", "Trailing actif : {sym} SL {old}->{new}"),
    "BE_HIT":                  (LogLevel.INFO,     "execution", "Break-even atteint : {sym} SL@entry"),

    "KILL_DD_DAILY":           (LogLevel.CRITIQUE, "risk", "Kill-switch DAILY_LOSS : PnL {pnl:.2f}$ < seuil {limit:.2f}$"),
    "KILL_CATASTROPHE":        (LogLevel.CRITIQUE, "risk", "Kill-switch CATASTROPHE : PnL {pnl:.2f}$ < seuil catastrophe"),
    "KILL_INTRADAY_DD":        (LogLevel.CRITIQUE, "risk", "Kill-switch INTRADAY_DD : peak->trough {dd:.2f}$ > {limit:.2f}$"),
    "KILL_MAX_TRADES":         (LogLevel.CRITIQUE, "risk", "Kill-switch MAX_TRADES : {n} trades jour > {limit}"),
    "KILL_RESET_SESSION":      (LogLevel.INFO,     "risk", "Reset session kill-switch : NONE"),
    "RISK_REJECT_PRE_TRADE":   (LogLevel.ALERTE,   "risk", "Signal refuse risk pre-trade : {reason}"),
    "RISK_REJECT_ATR_BOUNDS":  (LogLevel.ALERTE,   "risk", "Signal refuse ATR hors bornes : {atr} pas dans [{lo},{hi}]"),
    "RISK_REJECT_COOLDOWN":    (LogLevel.ALERTE,   "risk", "Signal refuse cooldown : {remaining_sec}s restants"),
    "RISK_REJECT_EXPOSURE":    (LogLevel.ALERTE,   "risk", "Signal refuse exposure : {open_pos} positions deja ouvertes"),
    "POSITION_EXPIRED":        (LogLevel.ALERTE,   "risk", "Position holdee > max_hold_bars ({bars}), flatten"),
    "VOLATILITY_SPIKE":        (LogLevel.ALERTE,   "risk", "Volatility spike : bar_range/atr={ratio:.1f}x > {limit:.1f}x, veto"),
    "DAILY_RESET":             (LogLevel.INFO,     "risk", "Daily reset effectue : nouvelle session"),

    "ML_MODEL_LOADED":         (LogLevel.INFO,     "ml", "Modele LightGBM charge : {version} ({n_features} features)"),
    "ML_MODEL_LOAD_FAIL":      (LogLevel.CRITIQUE, "ml", "Echec chargement modele : {path} {err}"),
    "ML_PREDICT":              (LogLevel.INFO,     "ml", "Prediction : {sym} score={score:.2f} p_primary={p_primary:.2f}"),
    "ML_FEATURES_MISSING":     (LogLevel.MAJEUR,   "ml", "Features manquantes : {missing} (n={n_missing})"),
    "ML_INFERENCE_SLOW":       (LogLevel.ALERTE,   "ml", "Inference lente : {ms}ms > seuil {limit_ms}ms"),
    "ML_META_LABELER_LOAD":    (LogLevel.INFO,     "ml", "Meta-labeler charge : {version}"),
    "ML_DRIFT_DETECTED":       (LogLevel.MAJEUR,   "ml", "Model drift detecte : {feature} {metric}={value}"),
    "ML_PREDICT_FAIL":         (LogLevel.MAJEUR,   "ml", "Echec predict_proba {sym} : {err}"),

    "DMP_JSONL_VALID":         (LogLevel.INFO,     "data", "JSONL valide : {file} ({n_bars} barres)"),
    "DMP_SCHEMA_MISMATCH":     (LogLevel.MAJEUR,   "data", "Schema mismatch : attendu {expected} trouve {found}"),
    "DMP_JSONL_STALE":         (LogLevel.CRITIQUE, "data", "JSONL stale : derniere barre il y a {age}s > {limit}s"),
    "DMP_FEATURE_NAN":         (LogLevel.ALERTE,   "data", "Feature NaN detecte : {feature} sur {n} barres"),
    "MQ_INGESTION_FAIL":       (LogLevel.MAJEUR,   "data", "Echec ingestion MenthorQ : {source} {err}"),
    "MQ_LEVELS_STALE":         (LogLevel.ALERTE,   "data", "MQ levels perimees : age {hours}h"),
    "VALIDATOR_VIOLATION":     (LogLevel.MAJEUR,   "data", "Quality validator violation : {feature} type={type}"),
    "PARQUET_BUILD_OK":        (LogLevel.INFO,     "data", "Parquet build OK : {file} shape=({n},{c})"),
    "PARQUET_BUILD_FAIL":      (LogLevel.MAJEUR,   "data", "Parquet build echec : {err}"),

    "BOOT_START":              (LogLevel.INFO,     "events", "Boot V2 {component} v{version} pid={pid}"),
    "BOOT_READY":              (LogLevel.INFO,     "events", "Boot pret : DTC={dtc} model={model} data={data}"),
    "BOOT_FAIL_PREFLIGHT":     (LogLevel.CRITIQUE, "events", "Boot echec preflight : {check} failed"),
    "SESSION_OPEN":            (LogLevel.INFO,     "events", "Session US RTH ouverte : 09:30 ET"),
    "SESSION_CLOSE":           (LogLevel.INFO,     "events", "Session US RTH fermee : 16:00 ET, EOD"),
    "SESSION_FLATTEN_WINDOW":  (LogLevel.ALERTE,   "events", "Flatten window 15:55 ET : fermeture positions"),
    "HEARTBEAT_V2CLEAN":       (LogLevel.INFO,     "events", "Heartbeat V2CLEAN OK"),
    "HEARTBEAT_V2CLEAN_STALE": (LogLevel.ALERTE,   "events", "V2CLEAN heartbeat stale : {age}s > 30s"),
    "HEARTBEAT_V2CLEAN_DOWN":  (LogLevel.CRITIQUE, "events", "V2CLEAN DOWN : heartbeat absent {age}s > 120s"),
    "HEARTBEAT_V2CLEAN_ZOMBIE": (LogLevel.CRITIQUE, "events", "V2CLEAN ZOMBIE : process alive mais muet {min}min"),
    "BOT_SHUTDOWN":            (LogLevel.INFO,     "events", "Bot arret propre : {reason}"),
    "BOT_CRASH":               (LogLevel.CRITIQUE, "events", "Bot crash : {exc_type} {exc_msg}"),
    "DLL_RELOAD":              (LogLevel.ALERTE,   "events", "DLL Sierra Chart reloadee"),
    "CONFIG_RELOAD":           (LogLevel.INFO,     "events", "Config reloadee depuis disque"),

    "GATE_PASSED_ALL":         (LogLevel.INFO,     "decisions", "Chain of gates OK : {sym} all 5 passed"),
    "GATE_HEALTH_BLOCK":       (LogLevel.ALERTE,   "decisions", "Gate Health block : V2CLEAN status={status}"),
    "GATE_SESSION_BLOCK":      (LogLevel.INFO,     "decisions", "Gate Session block : phase={phase}"),
    "GATE_RISK_BLOCK":         (LogLevel.ALERTE,   "decisions", "Gate Risk block : {reason}"),

    "DISCORD_SEND_OK":         (LogLevel.INFO,     "events", "Discord envoye : channel={channel}"),
    "DISCORD_SEND_FAIL":       (LogLevel.MAJEUR,   "events", "Discord echec : {err}"),
    "DISCORD_RATE_LIMIT":      (LogLevel.ALERTE,   "events", "Discord rate limit : retry {retry_in}s"),

    "GENERIC_INFO":            (LogLevel.INFO,     "events", "{msg}"),
    "GENERIC_ALERTE":          (LogLevel.ALERTE,   "events", "{msg}"),
    "GENERIC_MAJEUR":          (LogLevel.MAJEUR,   "events", "{msg}"),
    "GENERIC_CRITIQUE":        (LogLevel.CRITIQUE, "events", "{msg}"),
    "GENERIC_DEBUG":           (LogLevel.INFO,     "events", "[DEBUG] {msg}"),
}


def resolve(code: str):
    """Retourne (level, category, template) pour un code. KeyError si inconnu."""
    if code not in LOG_CODES:
        raise KeyError(f"Code de log inconnu : {code}. Ajouter a CORE/log_catalog.py")
    level, category, template = LOG_CODES[code]
    return level, category, template


def format_message(code: str, **ctx) -> str:
    """Formate le message fr a partir du code + contexte."""
    _, _, template = resolve(code)
    try:
        return template.format(**ctx)
    except KeyError as e:
        return f"{template} [MISSING_CTX: {e}]"


def get_action(level: LogLevel) -> dict:
    """Retourne les actions auto associees au niveau (discord, mention, etc.)."""
    return LEVEL_ACTIONS[level]


CATEGORIES = ("trading", "execution", "risk", "ml", "data", "errors", "events", "decisions")
