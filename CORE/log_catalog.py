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
    # PATCH R4 (02/05) — Track fill PARENT pour entry_price reel (vs signal_price)
    # Avant patch : pos["entry"] = signal_price → biais slippage entry sur tous trades
    # Apres patch : pos["entry"] = fill_price reel + slip_entry_ticks mesure
    "PARENT_FILL_RECORDED":    (LogLevel.INFO,     "execution", "Parent fill recorded : {sym} fill={fill_price} signal={old_entry} slip={slip_ticks}t parent={parent_id}"),
    # 01/05 soir DEBUG TEMPORAIRE — Verifier que Sierra Chart envoie TOUJOURS Symbol natif
    # dans s_OrderUpdate Filled. Si confirme N>=3 trades : adopter Option 5 (utiliser
    # fill.symbol au lieu de _order_to_symbol) — race condition entry_price disparait.
    # A retirer apres validation (commit dedie).
    "DTC_FILL_SYMBOL_DEBUG":   (LogLevel.INFO,     "execution", "DTC fill debug : cid={cid} symbol_raw={symbol_raw} present={symbol_present} acct={trade_account} fill={fill_price} parent={is_parent} keys={msg_keys}"),
    "ORDER_REJECT":            (LogLevel.MAJEUR,   "execution", "Ordre refuse broker : {sym} code={err_code} msg={err_msg}"),
    "ORDER_ACK_TIMEOUT":       (LogLevel.MAJEUR,   "execution", "Timeout ACK broker sur ordre {order_id} apres {timeout}s"),
    # 12/05 FIX entry_price (cf INCIDENT_LOG 2026-05-12 03:30) — race condition resolue
    "BOT_ENTRY_FILL_RECORDED": (LogLevel.INFO,     "execution", "Entry fill enregistre : {sym} {direction} signal={signal_price} fill={fill_price} drift={drift_ticks}t bot={bot}"),
    "BOT_DRIFT_WARNING":       (LogLevel.ALERTE,   "execution", "Drift entry eleve mais sous seuil : {sym} {direction} drift={drift_ticks}t threshold={threshold}t (50-100%) bot={bot}"),
    "BOT_DRIFT_REJECT":        (LogLevel.MAJEUR,   "execution", "Trade refuse drift excessif : {sym} {direction} drift={drift_ticks}t threshold={threshold}t bot={bot}"),
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
    "CIRCUIT_BREAKER_TRIP":    (LogLevel.MAJEUR,   "risk", "Circuit breaker {sym} : {consec_losses} pertes consecutives, pause {pause_min} min"),
    # 🆕 08/06/2026 Jackson Fix #1 + Fix #3 mia_paper_trader (3 BUY -$1210 ce matin)
    "ANTI_REVENGE_COOLDOWN_SET": (LogLevel.MAJEUR, "risk", "Anti-revenge cooldown {sym} : SL {sl_ticks}t > {threshold_ticks}t, pause {cooldown_min} min"),
    "VOL_VETO_HIGH_ATR":       (LogLevel.MAJEUR,  "decisions", "Veto vol high ATR {sym} : atr={atr_ticks}t > limit={limit_ticks}t"),
    # 🆕 08/06/2026 Jackson Fixes BN V5 (4 SL -$2117 ce matin)
    "BN_V5_DAILY_STOP_TRIGGERED": (LogLevel.MAJEUR, "risk", "BN V5 daily stop triggered {sym} : reason={reason} pnl={pnl_session_usd}usd threshold={threshold_usd}usd"),
    "BN_V5_TRAIL_BE_ARMED": (LogLevel.MAJEUR, "execution", "BN V5 breakeven armed {sym} {side} : entry={entry_price} sl_init={sl_initial} risk={risk_ticks}t mfe={mfe_ticks}t bars={bars_held}"),
    "BN_V5_SESSION_ROTATE": (LogLevel.INFO, "events", "BN V5 session rotate {sym} : {prev_date}->{new_date} (prev pnl {prev_pnl_usd}usd)"),
    "ORDER_PARTIAL_FILL":      (LogLevel.MAJEUR,   "execution", "Fill partiel {sym} : {filled}/{expected} ({pct:.0f}%), SL/TP places pour qty originale"),
    "PARENT_FILL_TIMEOUT":     (LogLevel.MAJEUR,   "execution", "Parent {order_id} NOT FILLED in {timeout}s, bracket abort"),
    "CANCEL_FAILED_RETRY":     (LogLevel.MAJEUR,   "execution", "Cancel {order_id} echoue apres {retry_count} tentatives, re-cancel lance"),

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
    "MQ_REGIME_LOADED":        (LogLevel.INFO,     "data", "Regime MenthorQ charge {sym} : {regime} net_gex={net_gex} ratio={ratio}"),
    "MQ_REGIME_MISSING":       (LogLevel.ALERTE,   "data", "JSON MenthorQ absent pour {date} — regime inconnu ({sym})"),
    "VALIDATOR_VIOLATION":     (LogLevel.MAJEUR,   "data", "Quality validator violation : {feature} type={type}"),
    "PARQUET_BUILD_OK":        (LogLevel.INFO,     "data", "Parquet build OK : {file} shape=({n},{c})"),
    "PARQUET_BUILD_FAIL":      (LogLevel.MAJEUR,   "data", "Parquet build echec : {err}"),
    "BAR_PROCESSING_ERROR":    (LogLevel.ALERTE,   "data", "Erreur processing bar {sym} : {err}"),
    "BAR_SKIPPED_KILL":        (LogLevel.ALERTE,   "data", "Bar {sym} skippe (kill-switch actif) : {reason}"),
    "FUNDED_FLATTEN":          (LogLevel.MAJEUR,   "risk", "Flatten prop firm force : {reason}"),

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
    "BOT_KILL_SWITCH_ACTIVATED": (LogLevel.MAJEUR, "events", "STOP.flag detecte : flatten + pause (positions closed: {n_closed}, bot2_open={n_bot2_open}, bot3_open={n_bot3_open})"),
    "BOT_KILL_SWITCH_RELEASED": (LogLevel.INFO,    "events", "STOP.flag supprime : reprise trading"),
    # FIX 19/05 (incident #10) : kill_switch flatten Bot 3 via _bot3_check_timeout(force=True)
    "BOT_KILL_SWITCH_FLATTEN_DONE": (LogLevel.MAJEUR, "events", "Kill switch flatten complet : total={n_closed_total} (bot2={bot2_closed}, bot3={bot3_closed}) residual_bot3={bot3_remaining}"),
    "BOT3_KILL_SWITCH_FLATTEN_EXCEPTION": (LogLevel.CRITIQUE, "events", "Kill switch Bot 3 exception : {exc_type} {exc_msg}"),
    "BOT_KILL_SWITCH_BOT3_RESIDUAL_ORPHAN_RISK": (LogLevel.CRITIQUE, "events", "Kill switch : {remaining} positions Bot 3 toujours ouvertes ({remaining_syms}) - ORPHELIN_RISK"),
    # FIX 19/05 (incident #10) : 5 fixes ladder long terme
    "BOT3_LADDER_NEW_SL_NOT_WORKING": (LogLevel.CRITIQUE, "events", "Ladder SL fantome detecte : new_sl_cid={new_sl_cid} absent Type 300 post-send {sym} palier={palier}. Position SANS SL broker - {msg}"),
    "BOT3_LADDER_VERIFY_TYPE300_EXCEPTION": (LogLevel.ALERTE, "events", "Ladder verify Type 300 exception : {sym} palier={palier} new_sl_cid={new_sl_cid} {exc} {msg}"),
    "BOT3_LADDER_TICK_TOO_YOUNG": (LogLevel.INFO, "events", "Ladder tick refuse : trade age {age_sec}s < min_age {min_age}s (race protection) sym={sym} mfe={mfe}"),
    # FIX 19/05 PM (review agent R3+Q2 + Q3) : 5 nouveaux codes ladder Phase 2
    "BOT3_LADDER_NEW_SL_VERIFY_TIMEOUT": (LogLevel.ALERTE, "events", "Verify Type 300 timeout (lock OR DTC slow) : sym={sym} palier={palier} new_sl_cid={new_sl_cid} - retry optimiste pos[sl_cid] preserve - {msg}"),
    "BOT3_FORCE_CLOSE_DTC_DOWN": (LogLevel.CRITIQUE, "events", "Force close DTC down : sym={sym} reason={reason} - {msg}"),
    "BOT3_FORCE_CLOSE_CONTRACT_LOOKUP_FAIL": (LogLevel.CRITIQUE, "events", "Force close contract lookup fail : sym={sym} reason={reason}"),
    "BOT3_FORCE_CLOSE_POS_QUERY_FAIL": (LogLevel.ALERTE, "events", "Force close position query fail : sym={sym} reason={reason} {exc} {msg}"),
    "BOT3_FORCE_CLOSE_POS_TIMEOUT": (LogLevel.ALERTE, "events", "Force close position query timeout : sym={sym} reason={reason} - {msg}"),
    "BOT3_FORCE_CLOSE_SENT": (LogLevel.MAJEUR, "events", "Force close envoye : sym={sym} reason={reason} close_cid={close_cid} qty={qty}"),
    "BOT3_FORCE_CLOSE_FAIL": (LogLevel.CRITIQUE, "events", "Force close send FAIL : sym={sym} reason={reason} {err}"),
    "BOT3_FORCE_FLUSH_FAIL": (LogLevel.ALERTE, "events", "Force flush Type 209 fail : sym={sym} reason={reason} {err}"),
    "BOT3_LADDER_FORCE_CLOSE_EXCEPTION": (LogLevel.CRITIQUE, "events", "Ladder force close exception : sym={sym} palier={palier} {exc_type} {exc_msg}"),
    # FIX 19/05 PM (review agent R1) : worker thread async modify_sl
    "BOT3_LADDER_JOB_ENQUEUED": (LogLevel.INFO, "events", "Ladder job enqueue : sym={sym} palier={palier} level={level} new_sl_price={new_sl_price} lock_usd={lock_usd} queue_size={queue_size}"),
    "BOT3_LADDER_ENQUEUE_FAIL": (LogLevel.ALERTE, "events", "Ladder enqueue FAIL (queue full?) : sym={sym} palier={palier} {exc_type} - {msg}"),
    "BOT3_LADDER_WORKER_JOB_START": (LogLevel.INFO, "events", "Ladder worker job start : sym={sym} palier={palier} new_sl_price={new_sl_price}"),
    "BOT3_LADDER_WORKER_POS_GONE": (LogLevel.INFO, "events", "Ladder worker pos gone : sym={sym} palier={palier} - {msg}"),
    "BOT3_LADDER_WORKER_EXCEPTION": (LogLevel.CRITIQUE, "events", "Ladder worker exception : sym={sym} palier={palier} {exc_type} {exc_msg}"),
    # FIX 19/05 PM (review agent patch 1 + 2) : watchdog 30s + split flush logs
    "BOT3_FORCE_FLUSH_NO_POS_QUERY": (LogLevel.INFO, "events", "Force flush Type 209 sans pos query : sym={sym} reason={reason} flush_cid={flush_cid} - {msg}"),
    "BOT3_FORCE_FLUSH_AFTER_CLOSE": (LogLevel.INFO, "events", "Force flush Type 209 apres MARKET CLOSE : sym={sym} reason={reason} flush_cid={flush_cid}"),
    "BOT3_LADDER_WATCHDOG_SCHEDULE_FAIL": (LogLevel.ALERTE, "events", "Watchdog T+30s schedule fail : sym={sym} palier={palier} new_sl_cid={new_sl_cid} {exc_type} {msg}"),
    "BOT3_LADDER_WATCHDOG_DTC_DOWN": (LogLevel.CRITIQUE, "events", "Watchdog T+30s DTC down : sym={sym} palier={palier} new_sl_cid={new_sl_cid}"),
    "BOT3_LADDER_WATCHDOG_POS_QUERY_FAIL": (LogLevel.ALERTE, "events", "Watchdog pos query fail : sym={sym} palier={palier} new_sl_cid={new_sl_cid} {exc} {msg}"),
    "BOT3_LADDER_WATCHDOG_POS_FLAT": (LogLevel.INFO, "events", "Watchdog T+30s pos flat : sym={sym} palier={palier} new_sl_cid={new_sl_cid} - {msg}"),
    "BOT3_LADDER_WATCHDOG_TYPE300_FAIL": (LogLevel.ALERTE, "events", "Watchdog Type 300 fail : sym={sym} palier={palier} new_sl_cid={new_sl_cid} {exc} {msg}"),
    "BOT3_LADDER_WATCHDOG_SL_WORKING_CONFIRMED": (LogLevel.INFO, "events", "Watchdog T+30s SL working confirme : sym={sym} palier={palier} new_sl_cid={new_sl_cid} expected_sl_price={expected_sl_price} - {msg}"),
    "BOT3_LADDER_WATCHDOG_SL_ORPHAN_DETECTED": (LogLevel.CRITIQUE, "events", "Watchdog T+30s SL ORPHAN detecte : sym={sym} palier={palier} new_sl_cid={new_sl_cid} open_orders_none={open_orders_none} open_orders_count={open_orders_count} - {msg}"),
    "BOT3_LADDER_WATCHDOG_POS_GONE": (LogLevel.INFO, "events", "Watchdog T+30s pos gone : sym={sym} palier={palier} new_sl_cid={new_sl_cid} - {msg}"),
    "BOT3_LADDER_WATCHDOG_FORCE_CLOSE_EXCEPTION": (LogLevel.CRITIQUE, "events", "Watchdog force close exception : sym={sym} palier={palier} new_sl_cid={new_sl_cid} {exc_type} {exc_msg}"),
    # FIX 19/05 PM (Jackson bouton FLATTEN) : exit reason FLATTEN_MANUAL distinct.
    # NB : BOT2_* est emis par service paper_v2 (process MIA-DataBento-Paper-V2,
    # tracking self.positions = Bot 2 V2 SetupEngine). BOT2V6_* est emis par service
    # MIA-Brain-V6 (Bot 2 V6 reel qui trade en prod). FIX 19/05 nuit : ajoute Brain-V6
    # qui ne lisait pas le flag (cause "FLATTEN MANUEL A PAS FONCTOINNER SUR LE BOT 2").
    "BOT2_FLATTEN_MANUAL_EXECUTED": (LogLevel.MAJEUR, "events", "Bot 2 V2 FLATTEN_MANUAL execute (paper_v2 SetupEngine) : sym={sym} price={price}"),
    "BOT2_FLATTEN_MANUAL_EXCEPTION": (LogLevel.CRITIQUE, "events", "Bot 2 V2 FLATTEN_MANUAL exception (paper_v2) : sym={sym} {exc_type} {exc_msg}"),
    "BOT2_FLATTEN_MANUAL_FLAG_STALE": (LogLevel.ALERTE, "events", "Bot 2 FLATTEN_MANUAL flag stale GC (paper_v2) : sym={sym} age_sec={age_sec}"),
    "BOT2V6_FLATTEN_MANUAL_EXECUTED": (LogLevel.MAJEUR, "events", "Bot 2 V6 FLATTEN_MANUAL execute (Brain-V6 prod) : sym={sym} price={price}"),
    "BOT2V6_FLATTEN_MANUAL_EXCEPTION": (LogLevel.CRITIQUE, "events", "Bot 2 V6 FLATTEN_MANUAL exception (Brain-V6) : sym={sym} {exc_type} {exc_msg}"),
    "BOT2V6_FLATTEN_MANUAL_FLAG_STALE": (LogLevel.ALERTE, "events", "Bot 2 V6 FLATTEN_MANUAL flag stale GC (Brain-V6) : sym={sym} age_sec={age_sec}"),
    "BOT3_FLATTEN_MANUAL_EXECUTED": (LogLevel.MAJEUR, "events", "Bot 3 MP FLATTEN_MANUAL execute : sym={sym} level={level} signal_id={signal_id}"),
    "BOT3_FLATTEN_MANUAL_EXCEPTION": (LogLevel.CRITIQUE, "events", "Bot 3 MP FLATTEN_MANUAL exception : sym={sym} {exc_type} {exc_msg}"),
    # 03/06 ajout fix FLATTEN mapping P1 (alignement archi 28/05) + P1.review (bugs critique reviewer)
    "BOT3_V3_FLATTEN_MANUAL_EXECUTED":  (LogLevel.MAJEUR,   "events", "Bot 3 v3 FLATTEN_MANUAL execute : sym={sym} level={level} signal_id={signal_id}"),
    "BOT3_V3_FLATTEN_MANUAL_EXCEPTION": (LogLevel.CRITIQUE, "events", "Bot 3 v3 FLATTEN_MANUAL exception : sym={sym} {exc_type} {exc_msg}"),
    "BOT3_V4_FLATTEN_MANUAL_EXECUTED":  (LogLevel.MAJEUR,   "events", "Bot 3 v4 FLATTEN_MANUAL execute : sym={sym} level={level} signal_id={signal_id}"),
    "BOT3_V4_FLATTEN_MANUAL_EXCEPTION": (LogLevel.CRITIQUE, "events", "Bot 3 v4 FLATTEN_MANUAL exception : sym={sym} {exc_type} {exc_msg}"),
    "BOT1_FLATTEN_FLAG_NO_POS":         (LogLevel.INFO,     "events", "Bot 1 FLATTEN_MANUAL flag consume mais aucune position : sym={sym} msg={msg}"),
    "BOT3_V4_FLATTEN_FLAG_NO_POS":      (LogLevel.INFO,     "events", "Bot 3 v4 FLATTEN_MANUAL flag consume mais aucune position : sym={sym} msg={msg}"),
    "BOT1_FLATTEN_MANUAL_FLAG_STALE":   (LogLevel.ALERTE,   "events", "Bot 1 FLATTEN_MANUAL flag stale (TTL expire) : sym={sym} age_sec={age_sec}"),
    "BOT3_V4_FLATTEN_MANUAL_FLAG_STALE":(LogLevel.ALERTE,   "events", "Bot 3 v4 FLATTEN_MANUAL flag stale (TTL expire) : sym={sym} age_sec={age_sec}"),
    "GATE_MTF_BULL_DESERT":     (LogLevel.INFO,    "decisions", "SHORT reject : mtf_bulls<=1 ({mtf_bulls}/4) edge negatif prouve"),
    # --- Paper trader gates funnel (enrichissement log V2 - 25/04) ---
    "GATE_CONSEIL_ATTENDRE":    (LogLevel.INFO,    "decisions", "Conseil ATTENDRE : {sym} bull={bull_pts} bear={bear_pts} bias={bias} mtf={mtf_bulls}/{mtf_bears} rangepos={range_pos}%"),
    "GATE_CONSEIL_CONFLIT":     (LogLevel.INFO,    "decisions", "Conseil CONFLIT : {sym} bull={bull_pts} bear={bear_pts}"),
    "GATE_SELL_AUTO_DISABLED":  (LogLevel.ALERTE,  "decisions", "SELL auto-disabled : {sym} reason={reason}"),
    "GATE_FRESHNESS_EXPIRED":   (LogLevel.INFO,    "decisions", "Freshness expire : {sym} state={freshness}"),
    # Option B 05/05 : signal RESCUED par seuil EXECUTION (4 bars) qui aurait ete
    # bloque par seuil DISPLAY (2 bars). Permet audit J+1 : combien de trades
    # debloques par le fix vs ancien comportement.
    "GATE_CONSEIL_EXEC_RESCUED":(LogLevel.INFO,    "decisions", "Signal RESCUED Option B : {sym} dir={direction} bull={bull_pts} bear={bear_pts} age_bars={age_bars} (UI=EXPIRED, EXEC=PERSISTENT)"),
    # ChaseTopGate 05/05 (walk-forward Lopez DSR=0.72) : bloque LONG range_pos>=60.
    "GATE_CHASE_TOP_LONG_BLOCK":(LogLevel.INFO,    "decisions", "Chase top bloque : {sym} {direction} range_pos={range_pos}% >= {threshold}% (walk-forward DSR=0.72)"),
    # R2 : audit RESCUED offline J+7 — emit par audit_chase_top_rescued.py (script
    # post-hoc qui parse les blocks et matche prix t+30min). Mesure false-block rate.
    "GATE_CHASE_TOP_LONG_RESCUED":(LogLevel.INFO, "decisions", "Chase top RESCUED audit : {sym} block_ts={block_ts} price_ref={price_ref} mfe_30min={mfe_ticks}t (filter rate des TPs)"),
    # Observe-only tracker SHORT au bottom (05/05 — risque miroir ChaseTopGate).
    # Audit n=32 dit NOGO block, mais sample sous Lopez seuil n>=100.
    # Track SHORT pris a range_pos<=30 sur 2-4 semaines pour valider l'asymetrie.
    # Si WR_chase_bottom < WR_baseline - 15% => deployer ChaseBottomGate SHORT.
    "SHORT_AT_BOTTOM_OBSERVED":(LogLevel.INFO,    "decisions", "SHORT au bottom observe : {sym} range_pos={range_pos}% entry={entry_price} (audit J+14 vs WR baseline)"),
    # Edge zones retest observe-only (06/05 — V4 Phase B+++ Edge Zones).
    # Setup ICT : push violent cree une zone edge -> prix revient -> rebond/rejet.
    # Track les bars qui touchent une zone edge (|dist|<=0.10%) pour audit J+14
    # WR vs baseline. Si fort signal -> proposer setup actif sur Bot V6.
    "EDGE_SELL_RETEST_OBSERVED":(LogLevel.INFO,   "decisions", "Edge SELL retest observe : {sym} dist={dist_pct}% n_active={n_active} entry={entry_price} (SHORT setup ICT)"),
    "EDGE_BUY_RETEST_OBSERVED":(LogLevel.INFO,    "decisions", "Edge BUY retest observe : {sym} dist={dist_pct}% n_active={n_active} entry={entry_price} (LONG setup ICT)"),
    "GATE_SIGNAL_DEDUPED":      (LogLevel.INFO,    "decisions", "Signal dedup : {sym} signal_id={signal_id}"),
    "GATE_CONF_TOO_LOW":        (LogLevel.INFO,    "decisions", "Confidence too low : {sym} conf={confidence} < {min_conf_required}"),
    "GATE_MTF_INSUFFICIENT":    (LogLevel.INFO,    "decisions", "MTF insuffisant : {sym} dir={direction} bulls={mtf_bulls}/{mtf_bears} need>={min_required}"),
    "GATE_BAR_DMP_MISSING":     (LogLevel.ALERTE,  "decisions", "Bar DMP absente : {sym} dir={direction}"),
    "GATE_SLTP_REJECT":         (LogLevel.INFO,    "decisions", "SLTP reject : {sym} dir={direction} raison={reason_fine}"),
    "GATE_PAYOFF_TOO_LOW":      (LogLevel.INFO,    "decisions", "Payoff insuffisant : {sym} expected=${expected_payoff_usd} < min=${min_required}"),
    # Plan C 08/06 : instrumentation Gate 0 Regime Engine (audit NQ LONG drift).
    # Emit dans _funnel_reject pour step "0_regime" — permet audit J+1 quels regimes
    # bloquent et quelles directions. Cf .claude/rules/critical-tasks-review.md sect Logs.
    "GATE_REGIME_NOT_ACTIONABLE":  (LogLevel.INFO,  "decisions", "Regime non actionable : {sym} regime_mode={regime_mode} regime_favor={regime_favor} regime_vol={regime_vol} trend_votes={regime_trend_votes}"),
    "GATE_REGIME_NEUTRE":          (LogLevel.INFO,  "decisions", "Regime NEUTRE : {sym} regime_mode={regime_mode} regime_favor=NEUTRE — direction LONG/SHORT non favorisee"),
    "GATE_REGIME_BIAS_NEUTRAL":    (LogLevel.INFO,  "decisions", "Regime bias neutral : {sym} regime_mode={regime_mode} regime_favor={regime_favor} (regime actionable mais bias_calculator NEUTRAL)"),
    "GATE_REGIME_CONTRAIRE_SIGNAL":(LogLevel.INFO,  "decisions", "Regime CONTRAIRE au signal : {sym} conseil_action={conseil_action_pre} regime_favor={regime_favor} regime_mode={regime_mode}"),
    # BUG #1 FIX 08/06 : MTF boost preserve ancien bias en zone neutre.
    # Audit J+7 quels symboles tombent dans fallback (bias amont fort -0.40 + MTF 4/4 contraire = score reste BEARISH preserve, ancien bug forcait BULLISH).
    "BIAS_NEUTRAL_ZONE_FALLBACK": (LogLevel.INFO, "decisions", "Bias fallback zone neutre : {sym} old_bias={old_bias} old_score={old_score} new_score={new_score} mtf_bulls={mtf_bulls} mtf_bears={mtf_bears} (boost insuffisant pour basculer bias amont)"),
    # 🆕 Plan A1 (08/06/2026) — refactor BLOC 5 bias_calculator (PTS_CVD 0.10->0.25 + divergence flag + vwap_m veto).
    # Tracabilite divergence delta vs cvd (signal qualite degradee). INFO car frequent (jusqu'a 65% des bars NQ 03/06).
    # Veto vwap_m_side push direction NEUTRE (signal contre ancrage long-terme). ALERTE car critique pour audit.
    "BIAS_DELTA_CVD_DIVERGENCE": (LogLevel.INFO, "decisions", "Bias delta vs cvd divergence : {sym} delta_dir={delta_dir} cvd_dir={cvd_dir} bias_score={bias_score} bias_dir={bias_dir} (signal qualite degradee, retournement potentiel)"),
    "BIAS_VWAP_M_VETO": (LogLevel.ALERTE, "decisions", "Bias VWAP_M veto applique : {sym} proposed_dir={proposed_dir} vwap_m_side={vwap_m_side} bias_score={bias_score} -> NEUTRE (ancrage long-terme contraire)"),
    # BUG #4 FIX 08/06 : MTF 4/4 poids 2->1 dans build_conseil_global (anti double-comptage).
    # Audit J+7 : grep CONSEIL_MTF_PERFECT_DOWNWEIGHT pour mesurer combien de cas seraient
    # auparavant declenches ACHAT/VENTE PRUDENT a tort via MTF 4/4 SEUL.
    "CONSEIL_MTF_PERFECT_DOWNWEIGHT": (LogLevel.INFO, "decisions", "MTF perfect attenue : {sym} bulls={mtf_bulls} bears={mtf_bears} bull_pts={bull_pts} bear_pts={bear_pts} (poids 2->1 anti double-comptage BUG#4)"),
    # 09/06 — FIX #54 Veto ATR Bot 1 Continuation (Bot 3 v3 + Bot 3 MP).
    # Aligne avec mia_paper_trader.py STEP 2 VOL_VETO_HIGH_ATR (deja existant Bot 1 Paper).
    # Incident 08/06 19:08 NQ ATR=580t > 400 limit -> trade pris -$500 + slippage 75t.
    # Pattern systemique slippage 70-83t P95 quand ATR extreme (BUG #16 audit).
    "BOT3_VOL_VETO_HIGH_ATR": (LogLevel.MAJEUR, "decisions", "Bot 3 veto vol high ATR : {sym} {side} level={level} atr={atr_ticks}t > limit={limit_ticks}t signal_id={signal_id}"),
    # 09/06 — FIX #55 SL Min ATR-aware Bot 1 Continuation (Couche 3).
    # SL serré 25t etendu a max(SL_MIN, atr*0.10). Anti-slippage + bruit.
    "BOT3_SL_MIN_ATR_EXTENDED": (LogLevel.ALERTE, "decisions", "Bot 3 SL etendu ATR-aware : {sym} {side} sl_orig={sl_orig_ticks}t -> sl_eff={sl_eff_ticks}t (atr={atr_ticks}t) signal_id={signal_id}"),
    # 10/06 — FIX #56 SL RISK HARDCAP USD (Jackson directive ultrathink anti slip catastrophe).
    # VETO trade si sl_risk_usd > MAX_SL_RISK_USD_BOT3 (default $50 virtuel micro Python).
    # Couvre auto-reprice slip parent etendant SL au-dela du cap.
    # ⚠️ DECOUPLING : cap USD virtuel micro Python. Risk SC reel = x10 (E-mini exec).
    "BOT3_SL_RISK_VETO": (LogLevel.MAJEUR, "decisions", "Bot 3 SL risk USD VETO : {sym} {side} level={level} sl_ticks={sl_ticks}t tv={tick_value} qty={n_contracts} -> risk_usd={sl_risk_usd} > cap={max_allowed_usd} - trade SKIP signal_id={signal_id} reason={reason}"),
    # 10/06 ULTRATHINK BN V5 Phase 5 — Couches protection (parite Bot 3 v3 FIX #54/55/56)
    "BN_V5_VOL_VETO_HIGH_ATR": (LogLevel.MAJEUR, "decisions", "BN V5 VETO vol high ATR : {sym} {pattern} {side} atr={atr_ticks}t > limit={limit_ticks}t"),
    "BN_V5_SL_MIN_ATR_EXTENDED": (LogLevel.ALERTE, "decisions", "BN V5 SL etendu ATR-aware : {sym} {pattern} {side} sl_orig={sl_orig_ticks}t -> sl_eff={sl_eff_ticks}t (atr={atr_ticks}t)"),
    "BN_V5_SL_RISK_VETO": (LogLevel.MAJEUR, "decisions", "BN V5 SL risk USD VETO : {sym} {pattern} {side} sl_ticks={sl_ticks}t tv={tick_value} qty={n_contracts} -> risk_usd={sl_risk_usd} > cap={max_allowed_usd} - trade SKIP reason={reason}"),
    # 10/06 ULTRATHINK BN V5 Phase G+H — Regime veto + daily stop preventif
    "BN_V5_REGIME_VETO": (LogLevel.MAJEUR, "decisions", "BN V5 regime VETO : {sym} {pattern} {side} regime_favor={regime_favor} trend_score={trend_score} - reason={reason}"),
    "BN_V5_DAILY_STOP_PREVENTIF_VETO": (LogLevel.MAJEUR, "decisions", "BN V5 daily stop preventif VETO : {sym} {pattern} {side} pnl={pnl_session_usd} - risk={perte_max_potentielle_usd} = cumul_apres={cumul_apres_perte} < limite={limite_loss_usd} - reason={reason}"),
    "BN_V5_POSITIONS_RESTORED": (LogLevel.MAJEUR, "events", "BN V5 positions restored : n={n_positions} symbols={symbols}"),
    "BN_V5_CID_INDEX_REBUILT": (LogLevel.INFO, "events", "BN V5 cid_index rebuilt : n_cids={n_cids}"),
    "BN_V5_SIGNAL_COUNTER_RESTORED": (LogLevel.INFO, "events", "BN V5 signal counter restored : sym={sym} counter={counter}"),
    "BN_V5_HALT_BOOT_REQUIRES_HUMAN": (LogLevel.CRITIQUE, "events", "BN V5 HALT BOOT requires human : case={case} symbol={symbol} message={message}"),
    "BN_V5_POLL_SKIP_HALT": (LogLevel.MAJEUR, "events", "BN V5 poll skip HALT : reason={halt_reason} details={halt_details}"),
    "BN_V5_POLL_SKIP_RECONCILE": (LogLevel.INFO, "events", "BN V5 poll skip - not reconciled yet"),
    "BN_V5_FORCE_FLAT_FLAG_CONSUMED": (LogLevel.MAJEUR, "events", "BN V5 force_flat flag consumed"),
    # 10/06 ULTRATHINK BN V5 Phase E — Trailing DTC reel (cancel+replace SL)
    "BN_V5_TRAIL_DTC_MODIFY_OK": (LogLevel.MAJEUR, "execution", "BN V5 trail DTC modify OK : {sym} old_sl_cid={old_sl_cid} new_sl_cid={new_sl_cid} new_sl_price={new_sl_price}"),
    "BN_V5_TRAIL_DTC_MODIFY_FAIL": (LogLevel.MAJEUR, "execution", "BN V5 trail DTC modify FAIL : {sym} err={err}"),
    "BN_V5_TRAIL_DTC_CANCEL_FAIL": (LogLevel.MAJEUR, "execution", "BN V5 trail DTC cancel FAIL : {sym} old_sl_cid={old_sl_cid}"),
    "BN_V5_TRAIL_DTC_SEND_FAIL": (LogLevel.MAJEUR, "execution", "BN V5 trail DTC send new SL FAIL : {sym} new_sl_cid={new_sl_cid} err={err}"),
    # 09/06 — FIX #56 Couche 4 STOP_LIMIT (Jackson valide). Audit J+7 shadow + activation.
    "DTC_SL_LIMIT_CALC": (LogLevel.INFO, "execution", "DTC SL_LIMIT calc : {sym} sl_cid={sl_cid} stop={stop_price} limit={limit_price} offset={offset_ticks}t mode={mode}"),
    # AUDIT TRACABILITE COMPLETE 08/06 (Jackson "tracker tous les blocages a tous les niveaux") :
    # 11 nouveaux codes pour combler les trous d'instrumentation. Avant : ~70% des steps loggees.
    # Apres : 100% steps + reasons (avec lookup prefix pour reasons dynamiques anti_revenge/vol_veto/eco).
    # STEP 1 — position deja ouverte / max trades jour
    "GATE_POSITION_ALREADY":   (LogLevel.INFO, "decisions", "Position deja ouverte : {sym}"),
    "GATE_MAX_TRADES_DAY":     (LogLevel.INFO, "decisions", "Max trades jour atteint : {sym}"),
    # STEP 2 — cooldown / circuit breaker / anti-revenge / vol veto / eco block
    "GATE_COOLDOWN_ACTIVE":    (LogLevel.INFO, "decisions", "Cooldown post-close actif : {sym}"),
    "GATE_CIRCUIT_BREAKER":    (LogLevel.ALERTE, "decisions", "Circuit breaker actif (2 SL consec, pause 4h) : {sym}"),
    "GATE_ANTI_REVENGE_ACTIVE":(LogLevel.INFO, "decisions", "Anti-revenge cooldown actif : {sym} (apres gros SL)"),
    "GATE_VOL_VETO_ATR":       (LogLevel.ALERTE, "decisions", "Veto vol ATR extreme : {sym} atr={atr} (marche trop volatile)"),
    "GATE_ECO_BLOCK":          (LogLevel.INFO, "decisions", "Eco calendar block : {sym} (FOMC/NFP/CPI/open US/MOC)"),
    # STEP 6ter — RangeGate
    "GATE_RANGE_EXTREME":      (LogLevel.INFO, "decisions", "Range extreme : {sym} dir={direction} reason={skip_reason}"),
    # STEP 6quart — RegimeGate losers
    "GATE_REGIME_LOSER_PROFILE_SHAPE": (LogLevel.INFO, "decisions", "Regime loser profile_shape : {sym} dir={direction} shape={profile_shape}"),
    "GATE_REGIME_LOSER_DAY_TYPE":      (LogLevel.INFO, "decisions", "Regime loser day_type : {sym} dir={direction} day_type={day_type}"),
    # STEP 6cinq — EntryQualityGate
    "GATE_ENTRY_QUALITY_BOTH_CONTRA": (LogLevel.INFO, "decisions", "Entry quality both contra : {sym} dir={direction} momentum={momentum_5b} cvd={cvd_bar_delta}"),
    # STEP -1 (Bot 1) / Gate 0 (Bot 3) — DailyLimitsGuard (Mark Douglas 08/06)
    # Souverain : grille feedback_douglas_consistency_principles.md.
    # daily_stop_loss : kill switch -$200 strict (incident Bot 1 08/06 -$2010 sur 7 trades).
    # daily_stop_win : lock-in profits +$150.
    # daily_max_trades : anti overtrading 5/jour.
    # Niveau CRITIQUE pour stop_loss (Discord notif + error_file), ALERTE pour win/max
    # (Discord off, journal ALERTE niveau warning).
    "GATE_DAILY_STOP_LOSS_TRIGGERED":  (LogLevel.CRITIQUE, "decisions", "DailyLimitsGuard STOP LOSS atteint : {bot_id} {sym} cumul={cumul_usd}$ <= seuil {limit_usd}$ (trades={trades}) — bot bloque pour la journee"),
    "GATE_DAILY_STOP_WIN_TRIGGERED":   (LogLevel.ALERTE,   "decisions", "DailyLimitsGuard STOP WIN atteint : {bot_id} {sym} cumul={cumul_usd}$ >= seuil {limit_usd}$ (trades={trades}) — lock-in profits"),
    "GATE_DAILY_MAX_TRADES_TRIGGERED": (LogLevel.ALERTE,   "decisions", "DailyLimitsGuard MAX TRADES atteint : {bot_id} {sym} trades={trades} >= limit {limit} (cumul={cumul_usd}$)"),
    "DAILY_LIMITS_RESET":              (LogLevel.INFO,     "events",    "DailyLimitsGuard reset rollover : {bot_id} {prev_date} -> {new_date} (prev_cumul={prev_cumul_usd}$ prev_trades={prev_trades})"),
    "DAILY_PNL_UPDATE":                (LogLevel.INFO,     "events",    "DailyLimitsGuard PnL update : {bot_id} {date} cumul={cumul_usd}$ delta={delta_usd}$ trades={trades}"),
    "DAILY_LIMITS_REBUILT":            (LogLevel.INFO,     "events",    "DailyLimitsGuard rebuild from trades file : {bot_id} {date} cumul={cumul_usd}$ trades={trades} stop_loss_triggered={stop_loss_triggered} stop_win_triggered={stop_win_triggered} max_trades_triggered={max_trades_triggered}"),
    # Wrappers Bot 3 MP / Bot 3 v3 / Bot 4 — block emit dedie (ALERTE, decisions).
    # Le code parent (GATE_DAILY_*_TRIGGERED) est CRITIQUE/ALERTE emit par on_trade_close
    # cross seuil. Cet emit est lui dedie au veto entry (un emit par signal bloque).
    "BOT3_DAILY_LIMITS_BLOCK":         (LogLevel.ALERTE,   "decisions", "Bot3 daily limits block : {sym} side={side} level={level} reason={reason} bot_id={bot_id}"),
    "BOT3_V3_DAILY_LIMITS_BLOCK":      (LogLevel.ALERTE,   "decisions", "Bot3 v3 daily limits block : {sym} side={side} level={level} reason={reason}"),
    "DLL_RELOAD":              (LogLevel.ALERTE,   "events", "DLL Sierra Chart reloadee"),
    "CONFIG_RELOAD":           (LogLevel.INFO,     "events", "Config reloadee depuis disque"),

    # databento_live_stream_v2 (refactor reconnect natif SDK 28/05/2026)
    "STREAM_RECONNECTED":              (LogLevel.MAJEUR,   "events", "Databento stream reconnect SDK natif #{count} gap_sec={gap_sec} (mapping purged: {mapping_purged})"),
    "STREAM_RECONNECT_EXCEPTION":      (LogLevel.ALERTE,   "events", "Exception dans reconnect callback Databento : {exc}"),
    "STREAM_SESSION_CLOSED_UNEXPECTEDLY": (LogLevel.CRITIQUE, "events", "Databento session closed inattendu (timeout 10min epuise) — sys.exit(3) pour nssm restart : bars={bars_received} trades={trades_received} reconnects={reconnect_count}"),
    # 29/05 FIX V2 racine (block_for_close timeout=None) : nouveau code distinct
    # de UNEXPECTEDLY pour tracer le vrai cas "gateway disconnect permanent".
    # Garde UNEXPECTEDLY dormant pour back-compat audits historiques.
    "STREAM_SESSION_CLOSED_PERMANENT":  (LogLevel.CRITIQUE, "events", "Databento session closed PERMANENT (SDK reconnect 10min exhausted OR gateway disconnect) — sys.exit(3) pour nssm restart : bars={bars_received} trades={trades_received} reconnects={reconnect_count}"),

    # 01/06 FIX DTC STOP order : retirer Price1 (interprete STOP_LIMIT par SC).
    # Emit a chaque SL STOP envoye (pas d'idempotence, volume ~50 INFO/jour).
    # Permet tracer empiriquement J+1 que le patch est actif (vs ancien backup) +
    # detecter regressions sur tous trades, pas seulement le premier.
    # Format kind = "sl_initial" / "sl_ladder" / "sl_trailing" / "sl_bn_v4_modify".
    "SL_STOP_PATCHED_V1":              (LogLevel.INFO,     "execution", "SL STOP patched v1 (Price1 removed, specs DTC OrderType=3) : kind={kind} sl_cid={sl_cid} sl_price={sl_price} ta={trade_account}"),
    # 02/06 NOTE : Voie B (STOP_LIMIT offset 0 + watchdog 30s) ETUDIEE et REVERT
    # apres review code-reviewer NOGO 7 bloquants (poll 30s = exposition 60s vs claim 30s,
    # LIMIT=STOP non valide empiriquement Sim1, couverture incomplete bots, etc).
    # Solution durable = migration prop firm mi-juin (vrais fills broker).
    # En attendant : SL_STOP_PATCHED_V1 v1 reste actif, slip Sim1 +4.2t accepte (biais connu).

    # Bot 4 L3 BN v2 rehabilitation 28/05/2026 (decision souveraine Jackson bypass INCIDENT_LOG #22)
    "BOT4_L3_TRIGGERED_LONG":          (LogLevel.INFO,     "decisions", "Bot4 L3 BN spring LONG trigger : PIR={pir} cluster={has_cluster} weight={weight} (trigger={trigger})"),
    "BOT4_L3_TRIGGERED_SHORT":         (LogLevel.INFO,     "decisions", "Bot4 L3 BN upthrust SHORT trigger : PIR={pir} cluster={has_cluster} weight={weight} (trigger={trigger})"),
    "BOT4_L3_REGIME_NEUTRE_SKIP":      (LogLevel.INFO,     "decisions", "Bot4 L3 skip car regime_favor={regime_favor} != LONG/SHORT"),
    "BOT4_L3_KILL_SWITCH_ENABLED":     (LogLevel.ALERTE,   "decisions", "Bot4 L3 kill switch active (MIA_BOT4_L3_DISABLED=1) -> rollback runtime"),

    "WATCHDOG_START":          (LogLevel.INFO,     "events", "Watchdog demarre : auto_restart={auto_restart} interval={interval}s"),
    "WATCHDOG_RESTART":        (LogLevel.MAJEUR,   "events", "Restart bot dans {delay}s : raison={reason}"),
    "WATCHDOG_MAX_RESTARTS":   (LogLevel.CRITIQUE, "events", "Max restarts atteint ({limit}/h) — intervention manuelle requise"),
    "WATCHDOG_RECOVERED":      (LogLevel.INFO,     "events", "Bot revenu en bonne sante apres incident ({duration}s unhealthy)"),
    "BOT_HEARTBEAT_STALE":     (LogLevel.MAJEUR,   "events", "Bot heartbeat stale : PID={pid} age={age}s > {limit}s"),
    "BOT_HEARTBEAT_MISSING":   (LogLevel.MAJEUR,   "events", "Heartbeat absent : fichier inexistant"),
    "BOT_PROCESS_DEAD":        (LogLevel.CRITIQUE, "events", "Bot process mort : PID={pid}"),
    "BOT_KILLED_BY_WATCHDOG":  (LogLevel.MAJEUR,   "events", "Bot tue par watchdog : PID={pid}"),

    "GATE_PASSED_ALL":         (LogLevel.INFO,     "decisions", "Chain of gates OK : {sym} all 5 passed"),
    "GATE_HEALTH_BLOCK":       (LogLevel.ALERTE,   "decisions", "Gate Health block : V2CLEAN status={status}"),
    "GATE_SESSION_BLOCK":      (LogLevel.INFO,     "decisions", "Gate Session block : phase={phase}"),
    "GATE_RISK_BLOCK":         (LogLevel.ALERTE,   "decisions", "Gate Risk block : {reason}"),
    "ECO_BLOCK":               (LogLevel.INFO,     "decisions", "Eco/Session block : {sym} {reason} (jusqu'a {until_utc})"),
    "VETO_BUY_COLOR_WALL":     (LogLevel.INFO,     "decisions", "Veto BUY {sym} : color_dn wall a {dist_color_dn_pct}% (seuil {threshold}%)"),
    "VETO_SHORT_NO_WALL":      (LogLevel.INFO,     "decisions", "Veto SHORT {sym} : {reason} (sl={sl_ticks}t tp={tp_ticks}t)"),
    "GATE_RANGE_BLOCK":        (LogLevel.INFO,     "decisions", "RangeGate block : {sym} {direction} reason={reason} (high={high_count}/4 low={low_count}/4)"),
    "GATE_REGIME_BLOCK":       (LogLevel.INFO,     "decisions", "RegimeGate block : {sym} {direction} reason={reason} ps={profile_shape} dt={day_type} ot={open_type}"),
    "GATE_ENTRY_QUALITY_BLOCK": (LogLevel.INFO,    "decisions", "EntryQualityGate block : {sym} {direction} reason={reason} mom={momentum_5b} cvd={cvd_bar_delta}"),

    "DISCORD_SEND_OK":         (LogLevel.INFO,     "events", "Discord envoye : channel={channel}"),
    "DISCORD_SEND_FAIL":       (LogLevel.MAJEUR,   "events", "Discord echec : {err}"),
    "DISCORD_RATE_LIMIT":      (LogLevel.ALERTE,   "events", "Discord rate limit : retry {retry_in}s"),

    "GENERIC_INFO":            (LogLevel.INFO,     "events", "{msg}"),
    "GENERIC_ALERTE":          (LogLevel.ALERTE,   "events", "{msg}"),
    "GENERIC_MAJEUR":          (LogLevel.MAJEUR,   "events", "{msg}"),
    "GENERIC_CRITIQUE":        (LogLevel.CRITIQUE, "events", "{msg}"),
    "GENERIC_DEBUG":           (LogLevel.INFO,     "events", "[DEBUG] {msg}"),

    # --- BOT 2 DB databento_paper_trader codes (28/04/2026) ---
    "BOT_START":                 (LogLevel.INFO,     "events", "Bot demarre : account={account} qty={quantity} rth={rth_only}"),
    "BOT_STOP":                  (LogLevel.INFO,     "events", "Bot stop : account={account} positions_open={positions_open_at_stop}"),
    "DTC_CONNECT_FAIL":          (LogLevel.MAJEUR,   "execution", "DTC connect fail : account={account}"),
    "DTC_CONNECTED":             (LogLevel.INFO,     "execution", "DTC connect OK : account={account}"),
    "GATE_POSITION_BLOCK":       (LogLevel.INFO,     "decisions", "Position block : {sym} reason={reason}"),
    "ORDER_DTC_ERROR":           (LogLevel.MAJEUR,   "execution", "Order DTC error : {sym} {error}"),
    # FIX C2 review : renomme pour eviter collision avec ORDER_REJECT V2CLEAN bot
    "ORDER_REJECT_BOT2":         (LogLevel.MAJEUR,   "execution", "Order reject BOT2 : {sym} dir={direction} entry={entry}"),

    # --- ENRICHISSEMENT comprehension comportement bot (28/04 soir) ---
    # 1. Decision tracking (chaque bar processed)
    "BAR_PROCESSED":             (LogLevel.INFO,     "decisions", "Bar : {sym} ts={bar_ts} close={close} bull={bull_pts} bear={bear_pts} dir={direction}"),
    "THRESHOLD_NEAR_MISS":       (LogLevel.INFO,     "decisions", "Near miss : {sym} bull={bull_pts} bear={bear_pts} besoin_de={missing_for_signal}"),
    "HOLD_REASON_AGGREGATE":     (LogLevel.INFO,     "decisions", "Aggregate {n_bars}b ({sym}) : bull max={bull_max} bear max={bear_max} hold={n_hold} buy={n_buy} sell={n_sell} conflit={n_conflit}"),

    # 2. Heartbeat & alertes pipeline/data
    "BOT_HEARTBEAT":             (LogLevel.INFO,     "events", "Heartbeat : account={account} positions={n_positions} bars_processed_total={total_bars} last_bar_age_sec={last_bar_age}"),
    "BAR_STALE_WARNING":         (LogLevel.ALERTE,   "events", "Bar stale : {sym} last_bar_age_sec={age} > {threshold}s"),
    "BAR_STALE_SKIP":            (LogLevel.ALERTE,   "events", "Bar stale SKIP : {sym} bar_ts={bar_ts} age={age}s > {threshold}s"),
    "BAR_ALREADY_TRADED":        (LogLevel.INFO,     "events", "Bar deja tradee (dedup cross-restart) : {sym} key={bar_key}"),
    "BAR_KEY_PARSE_FAIL":        (LogLevel.MAJEUR,   "events", "Bar key parse fail (SKIP) : {sym} bar_ts={bar_ts} err={err}"),
    "BAR_KEY_PARSE_FAIL_STORM":  (LogLevel.CRITIQUE, "events", "Storm BAR_KEY_PARSE_FAIL : {n_fails} fails en {window_sec}s — pipeline upstream casse ?"),
    "OCO_RECOVERY_BOOT":         (LogLevel.MAJEUR,   "events", "OCO recovery au boot : {n_positions} positions pending symbols={symbols}"),
    "OCO_RECOVERY_RESTORED":     (LogLevel.MAJEUR,   "events", "OCO recovery RESTORE : {sym} {side} entry={entry} sl={sl_price} tp={tp_price} (broker confirme position active)"),
    "OCO_ORPHAN_CANCELED":       (LogLevel.MAJEUR,   "execution", "OCO orphan cancel : {sym} {cid_field}={cid}"),
    "CLEANUP_DEFENSIVE_BOOT":    (LogLevel.MAJEUR,   "events", "Cleanup defensif boot : {n_archives} archives <24h, {n_cids} CIDs candidats"),
    "CLEANUP_DEFENSIVE_DONE":    (LogLevel.MAJEUR,   "events", "Cleanup defensif termine : {n_sent}/{n_total} cancels envoyes"),
    "STALE_POSITION_WARNING":    (LogLevel.MAJEUR,   "events", "Position stale : {sym} {side} ouverte depuis {age_min}min sans fill TP/SL — {msg_fr}"),
    # ── Game changers signatures gate (30/04 nuit, brainstorm timing entry) ──
    "SIGNATURES_COMPUTED":       (LogLevel.INFO,     "decisions", "Signatures : {sym} {direction} t1={tier1}/{tier1_max} t2={tier2}/{tier2_max} t3={tier3}/{tier3_max} score={total}"),
    "SIGNATURES_GATE_TIER1_BLOCK": (LogLevel.MAJEUR, "decisions", "Gate signatures BLOCK Tier1 (pression directionnelle insuffisante) : {sym} {direction} t1={tier1}/{tier1_max} signaux_present={signals_on}"),
    "SIGNATURES_GATE_TIER3_BLOCK": (LogLevel.MAJEUR, "decisions", "Gate signatures BLOCK Tier3 (invalidateur present) : {sym} {direction} t3={tier3}/{tier3_max} invalidateurs={invalidators}"),
    "SIGNATURES_GATE_PASS":      (LogLevel.INFO,     "decisions", "Gate signatures PASS : {sym} {direction} score={total}/{max} t1={tier1} t2={tier2} t3={tier3} → entry autorisee"),
    "CHECK_EXIT_DTC_HIT":        (LogLevel.MAJEUR,   "execution", "Check exit DTC hit : {sym} {outcome} live_price={live_price} sl={sl} tp={tp} age_s={age_s} → cancel brackets proactif"),
    "DAY_ROLLOVER":              (LogLevel.INFO,     "events", "Rollover UTC date : {prev_date} -> {new_date} (dedup_keys_dropped={dedup_keys_dropped})"),
    "SL_ANCHOR_BUDGET_OVERFLOW": (LogLevel.ALERTE,   "execution", "SL ancre depasse budget : {sym} risk=${risk_usd} > ${budget} (extra={sl_extra_ticks}t) → fallback close"),
    "SL_ANCHOR_BAR_MISSING":     (LogLevel.MAJEUR,   "execution", "SL ancre bar_low/high MISSING : {sym} err={err} ({msg}) → fallback price"),
    "SL_ANCHOR_APPLIED":         (LogLevel.INFO,     "execution", "SL ancre applique : {sym} {direction} anchor={sl_anchor} vs close={close} (+{extra_ticks}t, fallback={is_fallback})"),
    "PIPELINE_LAG":              (LogLevel.ALERTE,   "events", "Pipeline lag : last_iter_age_sec={age} > {threshold}s"),
    "DTC_HEARTBEAT_LOST":        (LogLevel.MAJEUR,   "execution", "DTC heartbeat absent depuis {age}s"),
    "SCORING_NULL_FEATURES":     (LogLevel.ALERTE,   "decisions", "Scoring degrade : {sym} null_pct={null_pct}% > 50%"),

    # 3. Context marche
    "MARKET_REGIME_CHANGE":      (LogLevel.INFO,     "events", "Regime change : {sym} {from_regime} -> {to_regime} (cvd_ffd={cvd_ffd})"),
    "MARKET_VOLATILITY_SHIFT":   (LogLevel.INFO,     "events", "Volatility shift : {sym} atr_pct={atr_pct} bucket={bucket}"),
    "SESSION_TRANSITION":        (LogLevel.INFO,     "events", "Session : {from_session} -> {to_session}"),
    "MQ_LEVELS_UPDATE":          (LogLevel.INFO,     "events", "MQ levels updated : {sym} call={mq_call} put={mq_put} hvl={mq_hvl}"),

    # ─────────────────────────────────────────────────────────────────────
    # 30/04/2026 : tracking anomalies pour les nouvelles features
    # ─────────────────────────────────────────────────────────────────────

    # Bot 1 trailing TR40_20 NQ (mia_paper_trader.py)
    # Permet de tracker : armement, updates, anomalies tick-align, blocage favorable
    "TRAILING_TR40_ARMED":       (LogLevel.INFO,     "execution", "Trailing TR40_20 ARM : {sym} mfe={mfe}t >= {arming_thr}t (40% × SL_init={sl_init}t)"),
    "TRAILING_TR40_UPDATED":     (LogLevel.INFO,     "execution", "Trailing TR40_20 UPDATE : {sym} sl={old_sl}->{new_sl} (give_back={give_back}t, count={count})"),
    "TRAILING_TR40_NOT_ALIGNED": (LogLevel.MAJEUR,   "execution", "Trailing TR40_20 TICK MISALIGN : {sym} sl_raw={sl_raw} sl_aligned={sl_aligned} delta={delta_ticks}t"),
    "TRAILING_TR40_LOOSEN_BLOCK":(LogLevel.ALERTE,   "execution", "Trailing TR40_20 LOOSEN BLOCKED : {sym} new_sl={new_sl} en defaveur de pos (current_sl={current_sl}, dir={direction})"),

    # SLTPEngine MQ walls + CAS 4 (mia_sltp.py)
    # Permet de tracker : utilisation effective des MQ walls, frequence CAS 4
    "SLTP_MQ_WALL_USED":         (LogLevel.INFO,     "decisions", "SLTP MQ wall used : {sym} dir={direction} role={role} wall={wall_name} dist={dist_ticks}t tier={tier}"),
    "SLTP_CAS4_TRIGGERED":       (LogLevel.MAJEUR,   "decisions", "SLTP CAS 4 trigger : {sym} dir={direction} TP capote DEVANT {wall_name} a {tp_ticks}t (was {tp_standard}t derriere mur a {wall_dist}t) — R:R sacrifie a {rr:.2f}"),
    "SLTP_FALLBACK_STANDARD":    (LogLevel.INFO,     "decisions", "SLTP fallback STANDARD : {sym} dir={direction} reason={reason_fallback} sl={sl_ticks}t tp={tp_ticks}t"),
    "SLTP_NO_VALID_WALL":        (LogLevel.ALERTE,   "decisions", "SLTP no valid wall : {sym} dir={direction} → fallback FIXED applique sl={sl_fixed}t tp={tp_fixed}t reject_reason={reject_reason}"),
    "SLTP_TP_BEHIND_WALL_DETECTED": (LogLevel.CRITIQUE, "decisions", "ANOMALIE TP DERRIERE MUR : {sym} dir={direction} tp_price={tp_price} mur={wall_name}@{wall_price} delta={delta_ticks}t — bug pre-CAS4 ?"),
    # FIX 07/05 (Jackson "voyants verts mais bot mort") : codes manquants causant
    # EMIT_FAIL en boucle sur MIA-DataBento-Paper -> service crash silencieux.
    # SLTP_CAS4_T2_OBSERVED : mur T2 hors structurel qui aurait capote (observability).
    # SLTP_CAS4_CAUSED_REJECT : capot CAS 4 a fait chuter R:R sous MIN_RR_RATIO -> reject.
    "SLTP_CAS4_T2_OBSERVED":     (LogLevel.INFO,     "decisions", "SLTP CAS 4 T2 OBSERVED : {sym} dir={direction} mur T2 hors structurel {wall_name}@{wall_dist}t aurait capote tp_devant={tp_devant}t tp_actual={tp_actual}t"),
    "SLTP_CAS4_CAUSED_REJECT":   (LogLevel.MAJEUR,   "decisions", "SLTP CAS 4 reject : {sym} dir={direction} capot {subtier} {wall_name} ({wall_col}@{wall_dist}t) a fait chuter R:R {rr_pre:.2f} -> {rr_post:.2f} (< MIN_RR_RATIO 0.8). reason={reject_reason}"),

    # ════════════════════════════════════════════════════════════════════
    # QualityGate v3 (Bot 2 step 6.5 — 01/05/2026)
    # ════════════════════════════════════════════════════════════════════
    # Filtre data-driven 9 dimensions (zones+flow+pieges+color+swing+div+imbalances+clusters+big)
    # 5 vetos absolus + score composite + hierarchie tier sizing.
    # Validation 42 trades : WR 23.8% → 42.9% (+$1,945 evite paper).
    "QUALITY_GATE_PASS":         (LogLevel.INFO,     "decisions", "QualityGate v3 PASS : {sym} dir={direction} tier={tier} score={score} sizing={sizing}"),
    "QUALITY_GATE_BLOCK":        (LogLevel.MAJEUR,   "decisions", "QualityGate v3 BLOCK : {sym} dir={direction} tier={tier} score={score} veto={veto} reason={reason}"),
    "QUALITY_GATE_ERROR":        (LogLevel.CRITIQUE, "decisions", "QualityGate v3 ERROR (degraded mode) : {sym} {error}"),

    # ════════════════════════════════════════════════════════════════════
    # Close trade Bot 1 v2 (anti-naked + anti-fantome — 01/05/2026)
    # ════════════════════════════════════════════════════════════════════
    # Pattern aligne Bot 2 _check_exit_dtc : poll broker via Type 305 puis
    # send_close_market (OpenCloseTrade=2) si position active. Skip si flat.
    "CLOSE_TRADE_ALREADY_FLAT":  (LogLevel.INFO,     "execution", "Close skip : {sym} broker deja FLAT (outcome={outcome} bot_qty={bot_qty} broker_qty={broker_qty}) — anti-fantome, brackets cancel idempotent"),

    # ════════════════════════════════════════════════════════════════════
    # Trailing TR40 (Bot 1 — desactive 01/05 jusqu'a fix cancel+replace broker)
    # ════════════════════════════════════════════════════════════════════
    "TRAILING_BROKER_REPLACE_FAILED": (LogLevel.MAJEUR, "execution", "Trailing broker replace FAILED : {sym} old_sl_cid={old_sl_cid} new_sl={new_sl} error={error} — trailing virtuel actif sans broker = risque naked"),

    # ════════════════════════════════════════════════════════════════════
    # Watchdog data feed stale (Bot 2 — 01/05/2026)
    # ════════════════════════════════════════════════════════════════════
    # Detecte si bars v4_enriched retardes (ex: bug pipeline MIA-LivePipeline
    # 30 min retard 01/05). 2 niveaux : WARNING (5 min) + CRITICAL (15 min).
    # CRITICAL declenche STOP.flag automatique pour eviter trades sur conditions
    # de marche obsoletes (bar 12:06 UTC traitee a 12:36 UTC = 30 min stale).
    "DATA_FEED_STALE_WARNING":   (LogLevel.MAJEUR,   "events", "Data feed STALE WARNING : {account} last_bar_age={last_age_sec}s > seuil {threshold_sec}s (no action, monitoring)"),
    "DATA_FEED_STALE_CRITICAL":  (LogLevel.CRITIQUE, "events", "Data feed STALE CRITICAL : {account} last_bar_age={last_age_sec}s > seuil {threshold_sec}s — {action}"),
    # 01/05 Jackson : recovery auto data feed apres reconnexion stream Databento.
    # Emis quand N heartbeats consecutifs avec last_bar_age <= THR_FRESH apres
    # un STOP_DATABENTO.flag actif. Permet reprise trading sans intervention humaine.
    "DATA_FEED_RECOVERED":       (LogLevel.MAJEUR,   "events", "Data feed RECOVERED : {account} last_bar_age={last_age_sec}s apres {consec_fresh_hb} hb consec fresh — {action}"),
    # 01/05 Jackson "INADMISSIBLE 33 min" : Bot 2 lit close LIVE_CACHE pour scoring.
    # Emit max 1x/min/symbole pour audit drift live vs parquet.
    "LIVE_BAR_OVERRIDE":         (LogLevel.INFO,     "events", "Live bar override : {sym} close_parquet={close_parquet} close_live={close_live} delta={delta_ticks}t live_age={live_age_sec}s"),
    # 04/05 Jackson — Etape 1 anti-slippage long terme. Bot 2 V2 + Bot 3 utilisent
    # live_cache.get_signal_entry_ref() au lieu de signal.price (parquet 30s+ retard).
    # Emit chaque trade pour audit drift signal vs prix de reference live utilise.
    "LIVE_REF_USED":             (LogLevel.INFO,     "events", "Live ref used : {sym} bot={bot} signal_price={signal_price} live_ref={live_ref} src={ref_source} drift={drift_ticks}t"),
    # 04/05 — Politique STRICT : si live cache stale > 180s, bot skip le trade.
    # Indique que la chaine live cache est cassee, signal a investiguer.
    "LIVE_CACHE_STALE_SKIP":     (LogLevel.MAJEUR,   "decisions", "Live cache stale SKIP trade : {sym} bot={bot} signal_price={signal_price} fallback={fallback_mode}"),
    # 04/05 — Etape 2 anti-slippage : metric slip systematique (signal_ref vs fill).
    # Permet audit J+1 du slippage reel et regression du fix live cache.
    "BRACKET_SLIP_METRIC":       (LogLevel.INFO,     "execution", "Bracket slip {sym} {side} parent={parent_id} ref={signal_ref_price} fill={fill_price} slip={slip_ticks}t"),
    # 04/05 — Etape 2 : reprice declenche si slip > seuil (default 5t). Recalc
    # SL/TP depuis fill_price reel AVANT envoi childs. Conforme FIX B-1 (02/05).
    "BRACKET_REPRICE":           (LogLevel.MAJEUR,   "execution", "Bracket reprice {sym} parent={parent_id} slip={slip_ticks}t signal_ref={signal_ref} fill={fill_price} old_sl={old_sl}->new_sl={new_sl} old_tp={old_tp}->new_tp={new_tp}"),
    # 01/05 soir FIX C : recalcul dist_* aux walls T1+T2 avec close LIVE.
    # SLTP_NO_VALID_WALL x10.8 post-deploy LIVE override → distances parquet
    # incoherentes avec close LIVE → SLTPEngine ne trouvait plus les walls.
    "LIVE_BAR_DIST_RECALC":      (LogLevel.INFO,     "events", "Live bar dist recalc : {sym} delta={delta_ticks}t n_walls_recalc={n_walls_recalc} n_from_pct={n_from_pct}"),
    # 01/05 soir HTF Multi-tf alignment OBSERVE-ONLY (J+0 → J+7)
    # Code-reviewer NOGO sur deploy VETO (Pattern 11 N=15). Mode observe seul.
    # Audit J+7 sur N reel ~50-60 trades production puis decision activation.
    "HTF_OBSERVE_PASS":          (LogLevel.INFO,     "decisions", "HTF observe PASS : {sym} {direction} aligned slope_5m={slope_5m:+.2f}"),
    "HTF_OBSERVE_COUNTER_SHORT": (LogLevel.INFO,     "decisions", "HTF observe COUNTER SHORT : {sym} signal contre HTF uptrend slope_5m={slope_5m:+.2f} (no-block J+0)"),
    "HTF_OBSERVE_COUNTER_LONG":  (LogLevel.INFO,     "decisions", "HTF observe COUNTER LONG : {sym} signal contre HTF downtrend slope_5m={slope_5m:+.2f} (no-block J+0)"),
    "HTF_OBSERVE_NO_DATA":       (LogLevel.ALERTE,   "decisions", "HTF observe NO DATA : {sym} bars_1m={n_bars_1m} insufficient (besoin >=125)"),
    "HTF_BLOCK_COUNTER_SHORT":   (LogLevel.MAJEUR,   "decisions", "HTF BLOCK SHORT counter-trend : {sym} slope_5m={slope_5m:+.2f} (active post J+7)"),
    "HTF_BLOCK_COUNTER_LONG":    (LogLevel.MAJEUR,   "decisions", "HTF BLOCK LONG counter-trend : {sym} slope_5m={slope_5m:+.2f} (active post J+7)"),
    # 01/05 Jackson "TRACK TOUT" : tracage exhaustif des rejets silencieux
    "BAR_LOAD_NONE":             (LogLevel.ALERTE,   "decisions", "Bar load None : {sym} {reason}"),
    "GATE_RTH_BLOCK":            (LogLevel.INFO,     "decisions", "Gate RTH BLOCK : {sym} hors RTH (heure UTC={hour_utc:.2f}h) — {reason}"),
    "GATE_DTC_UNAVAILABLE":      (LogLevel.ALERTE,   "decisions", "Gate DTC UNAVAILABLE : {sym} dtc_ok={dtc_ok} in_instruments={in_instruments} — {reason}"),
    # 01/05 Jackson "PAS DE VETO DIVERGENCE, ELLE ARRIVE TRES PEU" : Vetos 4+5
    # divergence retires de quality_gate_v3 (N=3+0 = noise). Observe-only audit WR.
    # Format flexible : delta_div_buy ou delta_div_sell selon direction (kwargs).
    "VETO_DELTA_DIV_OBSERVED":   (LogLevel.INFO,     "decisions", "Veto divergence observed : {sym} dir={direction} — {note}"),

    # ─── PHASE 1 OBSERVE-ONLY widgets V4 (Bot 1 / mia_paper_trader 04/05) ───
    # Audit market-analyst : ne pas integrer en gate avant n>=100 + DSR>=0.95.
    # Logs en mode OBSERVE pour audit empirique J+7 / J+14.
    "MANUAL_VWAP_TRIPLE_ALIGN_OBSERVED": (LogLevel.INFO,  "decisions", "VWAP triple align : {sym} dir={direction} D={d}/W={w}/M={m} slope_dir={slope_dir} action={action}"),
    "MANUAL_RVOL_EXCEPTIONAL_OBSERVED":  (LogLevel.INFO,  "decisions", "RVOL exceptionnel : {sym} z={zscore} zone={zone} action={action}"),
    "MANUAL_DIVERGENCE_OBSERVED":        (LogLevel.INFO,  "decisions", "Delta divergence observed : {sym} signal={signal} strength={strength} action={action}"),
    "MANUAL_NEXT_WALL_REACTION_OBSERVED":(LogLevel.INFO,  "decisions", "Next wall reaction zone : {sym} side={side} dist={dist}t action={action}"),
    "MANUAL_TRAP_OBSERVED":              (LogLevel.INFO,  "decisions", "Trapped traders @ niveau : {sym} signal={signal} zones_buy={buy} zones_sell={sell} action={action}"),
    "MANUAL_POC_MIGRATING_OBSERVED":     (LogLevel.INFO,  "decisions", "POC migration : {sym} state={state} speed={speed} pos={pos} action={action}"),
    "MANUAL_ABSORB_OBSERVED":            (LogLevel.INFO,  "decisions", "Absorption @ niveau : {sym} signal={signal} action={action}"),
    "OFA_CLUSTER_TRAP_OBSERVED":         (LogLevel.MAJEUR,"decisions", "Cluster TRAP @ niveau : {sym} signal={signal} side={side} dist_pct={dist_pct} trap_buy={trap_buy} trap_sell={trap_sell} action={action}"),
    "OFA_BIG_AGGRESSIVE_OBSERVED":       (LogLevel.INFO,  "decisions", "Big orders aggressive : {sym} signal={signal} side={side} buy_dom={buy_dom} sell_dom={sell_dom} t1_buy={t1_buy} t1_sell={t1_sell} action={action}"),
    "OFA_SMT_DIVERGENCE_OBSERVED":       (LogLevel.INFO,  "decisions", "SMT divergence ES/NQ : {sym} signal={signal} value={value} delta_day={delta_day} action={action}"),
    "OFA_NPOC_MAGNET_OBSERVED":          (LogLevel.MAJEUR,"decisions", "Naked POC magnet : {sym} signal={signal} dist_pct={dist_pct} age_days={age_days} action={action}"),
    "V4_STALE_OBSERVED":                 (LogLevel.ALERTE,"decisions", "V4 staleness detected : {sym} v4_ts={v4_ts} dmp_ts={dmp_ts} stale_sec={stale_sec}"),

    # ─── BOT 1 anti-orphelin sequence 8 etapes (Option B 04/05 soir) ─────
    # Port de la sequence databento_paper_trader_v2.py:_bot3_check_timeout
    # vers mia_paper_trader.py:_close_trade. Sim3 multi-positions -> PAS Type 210.
    "BOT1_CLEANUP_CANCEL_FAIL":          (LogLevel.MAJEUR, "execution", "Bot 1 cleanup cancel failed : {sym} failed={failed} (orphan risk)"),
    "BOT1_CLEANUP_FLATTEN_SYM":          (LogLevel.INFO,   "execution", "Bot 1 Type 209 flatten symbol : {sym} cid={cid}"),
    "BOT1_CLEANUP_FLATTEN_FAIL":         (LogLevel.ALERTE, "execution", "Bot 1 Type 209 flatten fail : {sym} err={err}"),
    "BOT1_CLEANUP_VERIFY_OK":            (LogLevel.INFO,   "execution", "Bot 1 cleanup verified flat : {sym} qty_final={qty}"),
    "BOT1_CLEANUP_VERIFY_FAIL":          (LogLevel.CRITIQUE,"execution","Bot 1 cleanup verify FAIL : {sym} qty_final={qty} ORPHAN_RISK"),
    "BOT1_CLEANUP_VERIFY_TIMEOUT":       (LogLevel.ALERTE, "execution", "Bot 1 cleanup verify timeout : {sym} broker_qty=None"),

    # ─── LEVIER A Trailing TP MFE-based (Bot 1 anti-TIMEOUT 04/05 backtest +$620) ─
    # Capture les MFE ratees : ES seuil 40t / NQ seuil 60t, drawback 25t = close.
    # Audit 28 TIMEOUT : 13 trades MFE>=20t mais final capture 30-50% seulement.
    "TRAILING_TP_ARMED":                 (LogLevel.INFO,   "execution", "Trailing TP armed : {sym} mfe={mfe}t threshold={threshold}t"),
    "TRAILING_TP_TRIGGERED":             (LogLevel.MAJEUR, "execution", "Trailing TP triggered : {sym} mfe_peak={mfe}t current={current}t drawback={drawback}t captured={captured_pct}%"),
    "TRAILING_TP_OBSERVED_VALIDATED":    (LogLevel.INFO,   "decisions", "Trailing TP Option 1 OBSERVE (40/60/25) : {sym} mfe_peak={mfe}t current={current}t drawback={drawback}t captured={captured_pct}% — pas trigger live (Option 2 active)"),
    # Audit Bot 2 SetupEngine 04/05 soir : trace bars evaluees sans trigger
    "SETUP_NO_TRIGGER":                  (LogLevel.INFO,   "decisions", "SetupEngine evaluated, aucun trigger : {sym} bar_ts={bar_ts}"),

    # ─── 22 codes manquants Bot 2/3 detectes 04/05 soir ─────────────────
    # Cause : Bot 3 logs trades non ecrits, dashboard PnL=$0 alors que trades reels.
    # Emit echouent en silence (log_catalog incomplet) → trade tracking casse.
    # Audit + ajout massif pour fix logging Bot 2/3 anti-orphelin sequence + regime.
    # Templates alignes sur kwargs reels du code (databento_paper_trader_v2.py:1003-1182)
    "BOT2_REGIME_OBSERVE":               (LogLevel.INFO,    "decisions", "Bot 2 regime : {sym} mode={regime_mode} favor={regime_favor} vol={regime_vol} actionable={regime_actionable} conf={regime_confidence}"),
    "BOT2_REGIME_SKIP":                  (LogLevel.INFO,    "decisions", "Bot 2 regime SKIP : {sym} side={sig_side} setup={setup} regime_favor={regime_favor} regime_mode={regime_mode} conf={regime_confidence}"),
    "BOT2_REGIME_ERROR":                 (LogLevel.ALERTE,  "decisions", "Bot 2 regime ERROR : {sym} err_type={err_type} err_msg={err_msg}"),
    "BOT3_REGIME_OBSERVE":               (LogLevel.INFO,    "decisions", "Bot 3 regime : {sym} mode={regime_mode} favor={regime_favor} vol={regime_vol} actionable={regime_actionable} conf={regime_confidence}"),
    "BOT3_REGIME_SKIP":                  (LogLevel.INFO,    "decisions", "Bot 3 regime SKIP : {sym} side={sig_side} level={level} regime_favor={regime_favor} regime_mode={regime_mode} conf={regime_confidence}"),
    "BOT3_REGIME_ERROR":                 (LogLevel.ALERTE,  "decisions", "Bot 3 regime ERROR : {sym} err_type={err_type} err_msg={err_msg}"),
    # BOT3 anti-orphelin sequence 8 etapes (documente dans .claude/rules/orphan-prevention.md)
    "BOT3_DTC_DOWN_ORPHAN_RISK":         (LogLevel.CRITIQUE, "execution", "Bot 3 DTC DOWN — orphan risk : {sym} level={level} age_min={age_min}"),
    "BOT3_TIMEOUT_FORCE_CLOSE":          (LogLevel.MAJEUR,   "execution", "Bot 3 timeout force close : {sym} level={level} close_cid={close_cid} qty={qty} age_min={age_min}"),
    "BOT3_TIMEOUT_CLOSE_FAIL":           (LogLevel.CRITIQUE, "execution", "Bot 3 timeout close FAIL : {sym} err={err}"),
    "BOT3_TIMEOUT_CANCEL_EXCEPTION":     (LogLevel.ALERTE,   "execution", "Bot 3 timeout cancel exception : {sym} label={label} cid={cid} err={err}"),
    "BOT3_TIMEOUT_CANCEL_FAIL_ORPHAN_RISK":(LogLevel.CRITIQUE, "execution", "Bot 3 timeout cancel fail — ORPHAN RISK : {sym} level={level} failed={failed}"),
    "BOT3_TIMEOUT_ALREADY_FLAT":         (LogLevel.INFO,     "execution", "Bot 3 timeout : deja flat : {sym} level={level} age_min={age_min}"),
    "BOT3_TIMEOUT_POSITION_UNKNOWN":     (LogLevel.ALERTE,   "execution", "Bot 3 timeout position unknown : {sym} level={level} age_min={age_min}"),
    "BOT3_TIMEOUT_REQUEST_POS_FAIL":     (LogLevel.ALERTE,   "execution", "Bot 3 timeout request_position fail : {sym} err={err}"),
    "BOT3_TIMEOUT_FLATTEN_SYM":          (LogLevel.INFO,     "execution", "Bot 3 timeout Type 209 flatten symbole : {sym} cid={cid}"),
    "BOT3_TIMEOUT_FLATTEN_FAIL":         (LogLevel.ALERTE,   "execution", "Bot 3 timeout Type 209 flatten FAIL : {sym} err={err}"),
    "BOT3_TIMEOUT_FLATTEN_ACCOUNT":      (LogLevel.MAJEUR,   "execution", "Bot 3 timeout Type 210 flatten account : account={account} cid={cid}"),
    "BOT3_TIMEOUT_FLATTEN_ACCOUNT_FAIL": (LogLevel.CRITIQUE, "execution", "Bot 3 timeout Type 210 flatten account FAIL : err={err}"),
    # BOT3 boot recovery (apres restart si position orpheline broker)
    "BOT3_RECOVER_POSITION_RESTORED":    (LogLevel.MAJEUR,   "execution", "Bot 3 recovery boot : position restauree depuis broker : {sym} qty={qty} side={side} avg_price={avg_price} has_tp={has_tp} has_sl={has_sl}"),
    "BOT3_RECOVER_QUERY_FAIL":           (LogLevel.ALERTE,   "execution", "Bot 3 recovery query fail : {sym} err={err}"),
    "BOT3_RECOVER_QUERY_TIMEOUT":        (LogLevel.ALERTE,   "execution", "Bot 3 recovery query timeout : {sym}"),
    "BOT3_RECOVER_SKIP_ALREADY_TRACKED": (LogLevel.INFO,     "execution", "Bot 3 recovery skip : position deja trackee : {sym}"),
    # P0.2 (06/05) : reconstruction CIDs reels via Type 300 OPEN_ORDERS au boot
    "BOT3_RECOVER_OPEN_ORDERS_QUERY_FAIL":(LogLevel.ALERTE,   "execution", "Bot 3 recovery OPEN_ORDERS query fail : err={err}"),
    "BOT3_RECOVER_FULL_BRACKET":         (LogLevel.MAJEUR,   "execution", "Bot 3 recovery FULL bracket reconstruit : {sym} qty={qty} side={side} avg_price={avg_price} tp_cid={tp_cid} sl_cid={sl_cid} tp_price={tp_price} sl_price={sl_price}"),
    "BOT3_RECOVER_PARTIAL_BRACKET":      (LogLevel.CRITIQUE, "execution", "Bot 3 recovery PARTIAL bracket : {sym} qty={qty} side={side} tp_cid={tp_cid} sl_cid={sl_cid} n_working_total={n_working_total} - asymetrie SL/TP, timeout immediat"),
    "BOT3_RECOVER_NO_BRACKET_FOUND":     (LogLevel.CRITIQUE, "execution", "Bot 3 recovery NO bracket trouve : {sym} qty={qty} side={side} n_working_total={n_working_total} - position broker nue, P0.3 cancel-all + flatten"),
    "BOT3_RECOVER_AMBIGUOUS_BRACKET":    (LogLevel.CRITIQUE, "execution", "Bot 3 recovery AMBIGUOUS bracket : {sym} qty={qty} n_limit={n_limit} n_stop={n_stop} n_total_working={n_total_working} msg={msg}"),
    # FIX 06/05 soir : capture fill Type 209 SUBMIT_FLATTEN_POSITION_ORDER
    # (anti pnl=null bug observe sur les 5 trades du 06/05).
    "BOT3_FLATTEN_FILL_CAPTURED":        (LogLevel.MAJEUR,   "execution", "Bot 3 fill Type 209 capture : {sym} level={level} fill_price={fill_price} entry={entry} pnl_ticks={pnl_ticks} pnl_usd={pnl_usd} reason={reason} cid={cid}"),
    "BOT3_FLATTEN_FILL_NO_ENTRY":        (LogLevel.ALERTE,   "execution", "Bot 3 fill Type 209 sans entry_price snapshot : {sym} fill_price={fill_price} cid={cid} msg={msg}"),
    "BOT3_RECOVER_OCO_REGISTER_FAIL":    (LogLevel.ALERTE,   "execution", "Bot 3 recovery OCO register fail : {sym} tp_cid={tp_cid} sl_cid={sl_cid} err={err}"),
    "BOT3_RECOVER_ORPHANS_FOUND_QTY_ZERO":(LogLevel.CRITIQUE, "execution", "Bot 3 recovery ORPHANS trouves position=0 : {sym} n_orphans={n_orphans} cids={cids} - cleanup automatique"),
    "BOT3_RECOVER_CANCEL_ORPHAN_FAIL":   (LogLevel.CRITIQUE, "execution", "Bot 3 recovery cancel orphan FAIL : {sym} cid={cid} err={err}"),
    # P0.3 (06/05) : etape 6.5 cancel-all-working dans _bot3_check_timeout
    "BOT3_TIMEOUT_CANCEL_ALL_WORKING_FOUND":(LogLevel.MAJEUR, "execution", "Bot 3 timeout cancel-all-working : {sym} n={n} cids={cids}"),
    "BOT3_TIMEOUT_CANCEL_ALL_FAIL":      (LogLevel.ALERTE,   "execution", "Bot 3 timeout cancel-all FAIL : {sym} cid={cid} err={err}"),
    "BOT3_TIMEOUT_CANCEL_ALL_QUERY_FAIL":(LogLevel.ALERTE,   "execution", "Bot 3 timeout cancel-all query fail : {sym} err={err}"),
    # P0.4 (06/05) : etape 9 verification post-cleanup
    "BOT3_ORPHAN_DETECTED_POST_CLEANUP": (LogLevel.CRITIQUE, "execution", "Bot 3 ORPHAN PERSISTANT post-cleanup : {sym} level={level} n={n} cids={cids} msg={msg}"),
    "BOT3_ORPHAN_RECANCEL_FAIL":         (LogLevel.CRITIQUE, "execution", "Bot 3 orphan re-cancel FAIL : {sym} cid={cid} err={err}"),
    "BOT3_ORPHAN_VERIFY_QUERY_FAIL":     (LogLevel.ALERTE,   "execution", "Bot 3 orphan verify query fail : {sym} err={err}"),
    "BOT3_TIMEOUT_CLEANUP_VERIFIED_CLEAN":(LogLevel.INFO,    "execution", "Bot 3 cleanup verifie clean : {sym} level={level}"),
    # FIX 07/05 (Jackson "C SUSPECT 0 PILE") : Solution A v2 pnl approximatif
    # via tail JSONL DMP du jour quand fill 209 ne remonte jamais (31 attempts /
    # 0 captures sur 4 jours). Bar age max 90s. Flag pnl_estimated=True dans
    # JSONL trades + dashboard (suffix "*") pour distinguer du pnl_known via fill.
    "BOT3_TIMEOUT_PNL_APPROX":           (LogLevel.MAJEUR,   "execution", "Bot 3 timeout pnl approx via DMP close : {sym} entry={entry} exit_approx={exit_approx} pnl_ticks_approx={pnl_ticks_approx} pnl_usd_approx={pnl_usd_approx} bar_age_s={bar_age_s} mfe={mfe} mae={mae}"),
    "BOT3_TIMEOUT_PNL_APPROX_SKIP_STALE":(LogLevel.ALERTE,   "execution", "Bot 3 timeout pnl approx skip - bar trop stale : {sym} bar_age_s={bar_age_s}"),
    "BOT3_TIMEOUT_PNL_APPROX_FAIL":      (LogLevel.ALERTE,   "execution", "Bot 3 timeout pnl approx FAIL : {sym} err={err}"),
    # 08/05 Health Checker (Controle General Bots) - Jackson directive
    # Apres incident 08/05 Bot 2 V6 STALE 24h+ silently. Auto-run + Discord alert.
    "HEALTH_CHECK_RUN":                  (LogLevel.INFO,     "events",    "Health check lance trigger={trigger} score={score} worst={worst}"),
    "HEALTH_CHECK_FAIL":                 (LogLevel.MAJEUR,   "events",    "Health check FAIL : check={check_name} status={status} details={details}"),
    "HEALTH_CHECK_CRIT":                 (LogLevel.CRITIQUE, "events",    "Health check CRITIQUE : check={check_name} details={details} fix={fix}"),
    "HEALTH_CHECK_RECOVERED":            (LogLevel.INFO,     "events",    "Health check OK apres alerte : check={check_name} prev_status={prev_status}"),
    "HEALTH_CHECK_RUNNER_DOWN":          (LogLevel.CRITIQUE, "events",    "Health check auto-runner inactif depuis {age_min}min - watchdog defaillant"),
    # 07/05 Bot 3 cooldown + circuit breaker (Jackson directive "ANALYSE COOLDOWN BOT 1+2 APPLIQUE BOT 3")
    # Apres incident 2 SL consec en 4 min sans cooldown -> -$801. Aligne Bot 1+Bot 2 (15min/3SL/60min).
    "BOT3_COOLDOWN_BLOCK":               (LogLevel.MAJEUR,   "decisions", "Bot 3 cooldown block (re-entry < 15 min post-close) : {sym} {side} level={level} reason={reason} cooldown_min={cooldown_min}"),
    "BOT3_CIRCUIT_BREAKER_BLOCK":        (LogLevel.MAJEUR,   "decisions", "Bot 3 circuit breaker block (3 SL consec + pause 60min) : {sym} {side} level={level} reason={reason} consec_sl={consec_sl}/{max_consec_sl}"),
    "BOT3_CIRCUIT_BREAKER_TRIGGERED":    (LogLevel.CRITIQUE, "decisions", "Bot 3 circuit breaker TRIGGERED (3 SL consec) : {sym} consec_sl={consec_sl} pause_min={pause_min} until={breaker_until} last_pnl_ticks={last_pnl_ticks}"),
    # 07/05 BN V3 paper loop (Bot 2 Sim2 Databento) - Jackson directive 2 contrats + recharge Long Up/Dn Bar
    "BN_V3_LOOP_START":                  (LogLevel.INFO,     "events",    "BN V3 paper loop start : sym={sym} dry_run={dry_run} recharge_enabled={recharge_enabled} trade_account={trade_account}"),
    "BN_V3_LOOP_ERROR":                  (LogLevel.CRITIQUE, "events",    "BN V3 paper loop error : sym={sym} err={err}"),
    "BN_V3_ENTRY":                       (LogLevel.MAJEUR,   "decisions", "BN V3 entry : sym={sym} dir={direction} entry={entry_price} sl={sl} tp_partial={tp_partial} qty={qty} dry_run={dry_run}"),
    "BN_V3_RECHARGE":                    (LogLevel.MAJEUR,   "decisions", "BN V3 recharge : sym={sym} dir={direction} entry={entry_price} n_recharges={n_recharges}/{max_recharges} dry_run={dry_run}"),
    "BN_V3_SCALE_OUT_50":                (LogLevel.INFO,     "execution", "BN V3 scale out 50% : sym={sym} dir={direction} tp_price={tp_price} qty_close={qty_close} new_sl_be={new_sl} dry_run={dry_run}"),
    "BN_V3_FLATTEN":                     (LogLevel.INFO,     "execution", "BN V3 flatten : sym={sym} reason={reason} dir={direction} dry_run={dry_run}"),
    # ════════════════════════════════════════════════════════════════════════
    # BN V4 paper Bot 2 Sim2 (23/05/2026 Jackson directive remplacement Bot 2 V2)
    # Setup zone confluence + density A++ + edge_buy + footprint (5 signaux, seuil >=1).
    # Source data JSONL live_enriched (lag 60s, source unique de verite).
    # Mode dual : A++ trade reel / A observation log only.
    # ════════════════════════════════════════════════════════════════════════
    # Lifecycle / events
    "BN_V4_BOOT_START":                  (LogLevel.INFO,     "events",    "BN V4 paper boot start : sym={sym} dry_run={dry_run} trade_account={trade_account} mode={mode}"),
    "BN_V4_CONFIG_LOADED":               (LogLevel.INFO,     "events",    "BN V4 config loaded : grade_min={grade_min} observation_grade_min={observation_grade_min} require_open={require_open} require_trend_align={require_trend_align} footprint_min={footprint_min} n_levels_min={n_levels_min} vol_ratio_min={vol_ratio_min} max_risk_ticks={max_risk_ticks} min_risk_ticks={min_risk_ticks}"),
    "BN_V4_BOOT_READY":                  (LogLevel.INFO,     "events",    "BN V4 paper boot ready : sym={sym} dtc_state={dtc_state} reader_state={reader_state}"),
    "BN_V4_SHUTDOWN":                    (LogLevel.MAJEUR,   "events",    "BN V4 paper shutdown : reason={reason} positions_open={positions_open}"),
    "BN_V4_LOOP_ERROR":                  (LogLevel.CRITIQUE, "events",    "BN V4 paper loop error : sym={sym} err={err}"),
    "BN_V4_BAR_STALE":                   (LogLevel.ALERTE,   "events",    "BN V4 bar stale (skip cycle) : sym={sym} age_sec={age_sec} threshold_sec={threshold_sec}"),
    "BN_V4_FEATURE_DEGRADED":            (LogLevel.MAJEUR,   "events",    "BN V4 feature degraded (NaN 3 bars consec) : sym={sym} feature={feature} bars_nan={bars_nan}"),
    # Fix P0#2 reviewer iter3 23/05 : BN_V4_DTC_LOST_DURING_OPEN RETIRE.
    # Pas de detection DTC down/reconnect implementee actuellement.
    # A re-ajouter si on code reco DTC dedie (cf IDEAS_BACKLOG).
    # Decisions (gates + setups + observation)
    # Fix P0 BIS code-reviewer iter2 23/05 : BN_V4_BAR_PROCESSED RETIRE du
    # catalog general. Volume 1440/jour ne convient ni a INFO (spam decisions/)
    # ni a ALERTE (corrompt semantique). Solution : tracage des bars deja
    # gere par BNV4Logger.log_bar_processed() qui ecrit dans LOGS/bn_v4/
    # daily JSONL dedie. Plus de double-comptabilite.
    # Fix P0 templates : retire constantes config (move vers CONFIG_LOADED).
    # Templates simplifies : valeurs courantes uniquement, pas de constantes.
    "BN_V4_GATE_TREND_BLOCK":            (LogLevel.MAJEUR,   "decisions", "BN V4 gate TREND block : sym={sym} dir={direction} slope_mean={slope_mean} threshold={threshold}"),
    "BN_V4_GATE_OPEN_WINDOW_BLOCK":      (LogLevel.INFO,     "decisions", "BN V4 gate OPEN_WINDOW block (hors fenetre) : sym={sym} ts_et={ts_et} mins_et={mins_et}"),
    "BN_V4_GATE_TREND_LONG_ALIGN_BLOCK": (LogLevel.MAJEUR,   "decisions", "BN V4 gate TREND_LONG_ALIGN block (SHORT only) : sym={sym} dir={direction} slope_240={slope_240}"),
    "BN_V4_GATE_LEVELS_BLOCK":           (LogLevel.MAJEUR,   "decisions", "BN V4 gate LEVELS block : sym={sym} dir={direction} n_levels={n_levels}"),
    "BN_V4_GATE_DENSITY_BLOCK":          (LogLevel.MAJEUR,   "decisions", "BN V4 gate DENSITY block : sym={sym} dir={direction} density={density} grade={grade}"),
    "BN_V4_GATE_EDGE_BLOCK":             (LogLevel.MAJEUR,   "decisions", "BN V4 gate EDGE block : sym={sym} dir={direction} feature={feature}"),
    "BN_V4_GATE_VOLUME_BLOCK":           (LogLevel.MAJEUR,   "decisions", "BN V4 gate VOLUME block : sym={sym} dir={direction} current_vol={current_vol} baseline={baseline} ratio={ratio}"),
    "BN_V4_GATE_FOOTPRINT_BLOCK":        (LogLevel.MAJEUR,   "decisions", "BN V4 gate FOOTPRINT block : sym={sym} dir={direction} n_signals={n_signals}"),
    # 29/05 FIX BETA Jackson : anti stop-hunt momentum slope 60bars (backtest +$40 save sur 28/05)
    "BN_V4_GATE_MOMENTUM_SLOPE_60_BLOCK": (LogLevel.MAJEUR,   "decisions", "BN V4 gate MOMENTUM_SLOPE_60 block : sym={sym} dir={direction} slope_mean_60={slope_mean_60} threshold={threshold}"),
    "BN_V4_PARAM_OVERRIDE_ENV":          (LogLevel.MAJEUR,   "events", "BN V4 param override depuis env var : param={param} override_value={override_value} source={source}"),
    "BN_V4_PARAM_OVERRIDE_ENV_FAIL":     (LogLevel.ALERTE,   "events", "BN V4 param override env var FAIL parse : param={param} raw_value={raw_value} err={err}"),
    # ═══ BN V5 (Battle Navale V5 — paradigme swing + trailing V/W) ═══
    "BN_V5_BOOT_START":                  (LogLevel.INFO,     "events",    "BN V5 paper boot start : sym={sym} dry_run={dry_run} trade_account={trade_account}"),
    "BN_V5_BOOT_READY":                  (LogLevel.INFO,     "events",    "BN V5 paper boot ready : sym={sym} dtc_state={dtc_state}"),
    "BN_V5_SHUTDOWN":                    (LogLevel.MAJEUR,   "events",    "BN V5 paper shutdown : sym={sym} n_trades_executed={n_trades_executed} pnl_session_usd={pnl_session_usd}"),
    "BN_V5_HEARTBEAT":                   (LogLevel.INFO,     "events",    "BN V5 heartbeat : sym={sym} uptime_min={uptime_min} bars={n_bars} setups={n_setups} trades={n_trades} pnl_usd={pnl_usd}"),
    "BN_V5_SETUP_DETECTED":              (LogLevel.MAJEUR,   "decisions", "BN V5 setup detected : sym={sym} pattern={pattern} side={side} entry={entry_price} sl={sl_price} pivot={pivot_price} neckline={neckline} conf_level={conf_level} conf_dist_pct={conf_dist_pct}"),
    # 03/06 fix pollution autopsie BN V5 : 99K events MAJEUR/jour pour des
    # decisions NORMALES du gate (pas des vraies erreurs). Reclassifie INFO.
    # Le bug calibration range_drift_min_pct=0.20% est traite separement
    # via backtest empirique + recalibration. Cf rapport autopsie 03/06.
    "BN_V5_GATE_RANGE_BLOCK":            (LogLevel.INFO,     "decisions", "BN V5 gate RANGE block (consolidation) : sym={sym} pattern={pattern} drift_pct={drift_pct} threshold={threshold}"),
    "BN_V5_GATE_BAR_REVERSAL_BLOCK":     (LogLevel.INFO,     "decisions", "BN V5 gate BAR_REVERSAL block : sym={sym} pattern={pattern} reason={reason}"),
    "BN_V5_TRADE_OPEN":                  (LogLevel.MAJEUR,   "execution", "BN V5 trade ouvert : sym={sym} pattern={pattern} side={side} entry={entry_price} sl={sl_price} risk_ticks={risk_ticks} qty={qty}"),
    "BN_V5_BRACKET_PLACED":              (LogLevel.INFO,     "execution", "BN V5 bracket OCO place : sym={sym} parent_cid={parent_cid} sl_cid={sl_cid} tp_cid={tp_cid}"),
    "BN_V5_TRAIL_SL_UPDATE":             (LogLevel.INFO,     "execution", "BN V5 trailing SL update : sym={sym} side={side} old_sl={old_sl} new_sl={new_sl} pullback_extreme={pullback_extreme}"),
    "BN_V5_TRADE_CLOSE_SL":              (LogLevel.INFO,     "execution", "BN V5 trade close SL : sym={sym} side={side} exit={exit_price} pnl_usd={pnl_usd} duration_bars={duration_bars} pattern={pattern}"),
    "BN_V5_TRADE_CLOSE_TIMEOUT":         (LogLevel.MAJEUR,   "execution", "BN V5 trade close timeout : sym={sym} side={side} exit={exit_price} pnl_usd={pnl_usd} duration_bars={duration_bars} pattern={pattern}"),
    "BN_V5_LOOP_ERROR":                  (LogLevel.CRITIQUE, "events",    "BN V5 loop error (exception captured) : sym={sym} err={err}"),
    "BN_V5_BAR_STALE":                   (LogLevel.ALERTE,   "events",    "BN V5 bar stale (skip cycle) : sym={sym} age_sec={age_sec} threshold_sec={threshold_sec}"),
    # 09/06 FIX BUG #1 persistance daily_stop (review code-reviewer 7 reserves integrees) :
    # 3 daily_stops NQ declenches 09/06 puis 3 restarts = re-trade post-stop = -$1140 cumul reel.
    # Persistance state.json DATA/PAPER_TRADES/bn_v5_session_state.json avec FAIL-CLOSED.
    "BN_V5_STATE_RESTORED":              (LogLevel.MAJEUR,   "events",    "BN V5 state restored : session_date_utc={session_date_utc} pnl={pnl_session_usd}usd daily_stop={daily_stop_triggered} reason={daily_stop_reason} n_trades={n_trades_executed} age_h={age_hours}"),
    "BN_V5_STATE_NEW_SESSION":           (LogLevel.INFO,     "events",    "BN V5 state new session (init vierge) : reason={reason}"),
    "BN_V5_STATE_LOAD_FAILED":           (LogLevel.CRITIQUE, "events",    "BN V5 state load FAILED (FAIL-CLOSED) : err={err} file={file}"),
    "BN_V5_STATE_SAVE_FAILED":           (LogLevel.ALERTE,   "events",    "BN V5 state save failed (best-effort) : err={err} file={file}"),
    "BN_V5_STATE_SAVED":                 (LogLevel.INFO,     "events",    "BN V5 state saved : pnl={pnl_session_usd}usd daily_stop={daily_stop_triggered} n_trades={n_trades_executed} trigger={trigger}"),
    # 09/06 SOIR SPRINT STABILITE BOT 3 V3 - PHASE 1 : helper centralise CORE/bot_persistance.py
    # Sprint decide avec Jackson : 1 bot a la fois, stabiliser puis discipline puis performance.
    # Cible : Bot 3 v3 NQ Wyckoff (PF 1.045 backtest n=1611) comme premier candidat.
    # 12 codes BOT_STATE_* + RECONCILE_* + SIGNAL_ID_* a registrer AVANT code (regle critical-tasks-review.md).
    "BOT_STATE_LOAD_FAILED":             (LogLevel.CRITIQUE, "events",    "Bot state load FAILED (FAIL-CLOSED) : bot={bot} err={err} file={file}"),
    "BOT_STATE_SAVE_FAILED":             (LogLevel.ALERTE,   "events",    "Bot state save failed (best-effort) : bot={bot} err={err} file={file}"),
    "BOT_STATE_RESTORED":                (LogLevel.MAJEUR,   "events",    "Bot state restored : bot={bot} session_date_utc={session_date_utc} age_h={age_hours}"),
    "BOT_STATE_NEW":                     (LogLevel.INFO,     "events",    "Bot state new (init vierge) : bot={bot} reason={reason}"),
    "BOT_STATE_SCHEMA_MAJOR_MISMATCH":   (LogLevel.CRITIQUE, "events",    "Bot state schema MAJOR mismatch (FAIL-CLOSED) : bot={bot} file_major={file_major} expected_major={expected_major} file={file}"),
    "BOT_STATE_SCHEMA_MINOR_MISMATCH":   (LogLevel.ALERTE,   "events",    "Bot state schema MINOR mismatch (WARN, accept) : bot={bot} file_minor={file_minor} expected_minor={expected_minor}"),
    "RECONCILE_OK_FLAT":                 (LogLevel.INFO,     "events",    "Reconcile OK flat : bot={bot} symbol={symbol}"),
    "RECONCILE_OK_RESTORED":             (LogLevel.INFO,     "events",    "Reconcile OK restored : bot={bot} symbol={symbol} py_qty={py_qty} py_side={py_side} broker_qty={broker_qty}"),
    "RECONCILE_UNKNOWN_BROKER_POS":      (LogLevel.CRITIQUE, "execution", "Reconcile CRITIQUE broker pos sans tracking Python : bot={bot} symbol={symbol} broker_qty={broker_qty} broker_side={broker_side} action={action}"),
    "RECONCILE_PYTHON_GHOST":            (LogLevel.ALERTE,   "events",    "Reconcile Python ghost (broker flat, Python avait pos) : bot={bot} symbol={symbol} py_pos={py_pos}"),
    "RECONCILE_DIVERGENCE":              (LogLevel.CRITIQUE, "execution", "Reconcile CRITIQUE divergence Python vs broker : bot={bot} symbol={symbol} py_qty={py_qty} py_side={py_side} broker_qty={broker_qty} broker_side={broker_side} action={action}"),
    "RECONCILE_FORCE_FLAT_OVERRIDE":     (LogLevel.MAJEUR,   "execution", "Reconcile force-flat override (Jackson env var) : bot={bot} symbol={symbol} action={action}"),
    "SIGNAL_ID_COUNTER_LOADED":          (LogLevel.INFO,     "events",    "Signal ID counter loaded : bot={bot} symbol={symbol} last_seq={last_seq}"),
    "SIGNAL_ID_COLLISION_DETECTED":      (LogLevel.MAJEUR,   "decisions", "Signal ID collision DETECTED : bot={bot} symbol={symbol} signal_id={signal_id} reason={reason}"),
    # 09/06 SOIR ETAPE 2.A integration Bot 3 v3 - restore positions au boot via PositionPersistance.
    # Scope minimal (pas de reconcile DTC = etape 2.B).
    "BOT3_V3_POSITIONS_RESTORED":        (LogLevel.MAJEUR,   "events",    "Bot 3 v3 positions restored from state file : n_positions={n_positions} symbols={symbols} signal_counter_restored={signal_counter_restored}"),
    "BOT3_V3_CID_INDEX_REBUILT":         (LogLevel.INFO,     "events",    "Bot 3 v3 _cid_index rebuilt from restored positions : n_cids={n_cids}"),
    "BOT3_V3_HALT_BOOT_REQUIRES_HUMAN":  (LogLevel.CRITIQUE, "events",    "Bot 3 v3 HALT BOOT - intervention humaine requise : reason={reason} symbol={symbol} details={details}. Reset : creer flag STATE/bot3_v3/force_flat.flag puis restart"),
    "BOT3_V3_RECONCILE_DTC_UNREACHABLE": (LogLevel.CRITIQUE, "events",    "Bot 3 v3 reconcile DTC unreachable apres {n_retries} retries - bot HALT"),
    "BOT3_V3_TRADE_CLOSE_EXTERNAL":      (LogLevel.MAJEUR,   "events",    "Bot 3 v3 trade close EXTERNE detecte (cas d reconcile) : symbol={symbol} signal_id={signal_id} exit_price_estimated={exit_price_estimated} pnl_estimated_usd={pnl_estimated_usd}"),
    "BOT3_V3_PNL_UNCERTAIN":             (LogLevel.ALERTE,   "events",    "Bot 3 v3 PnL session incertain (cas d trade close external) : need MIA_BOT3_V3_PNL_ACK=1 pour reprendre trading"),
    "BOT3_V3_POLL_SKIP_HALT_BOOT":       (LogLevel.ALERTE,   "decisions", "Bot 3 v3 poll skip : HALT BOOT reason={halt_reason} (rate-limited 5min)"),
    "BOT3_V3_POLL_SKIP_NOT_RECONCILED":  (LogLevel.ALERTE,   "decisions", "Bot 3 v3 poll skip : not reconciled yet (DTC pending)"),
    "BOT3_V3_COOLDOWN_RESTORED":         (LogLevel.INFO,     "events",    "Bot 3 v3 cooldown restore depuis state : symbol={symbol} last_trade_close_ts={last_trade_close_ts} cooldown_until={cooldown_until}"),
    # 09/06 SOIR Backlog R1 etape 4 : tracabilite flatten_bot.py auto-sync dashboard
    # (BUG #4 fix append TRADE_CLOSE synthetic dans bot logger JSONL apres flatten DTC OK).
    "FLATTEN_SYNC_APPENDED":             (LogLevel.MAJEUR,   "events",    "Flatten sync TRADE_CLOSE appende JSONL : trade_account={trade_account} symbol={symbol} signal_id={signal_id} log_path={log_path}"),
    "FLATTEN_SYNC_SKIPPED":              (LogLevel.INFO,     "events",    "Flatten sync skipped : trade_account={trade_account} symbol={symbol} reason={reason}"),
    # Traçabilité fine (Jackson 02/06 SOIR : "on doit tout tracker pour debug")
    "BN_V5_CYCLE_SUMMARY":               (LogLevel.INFO,     "decisions", "BN V5 cycle : sym={sym} bars={n_bars_in_window} n_pl={n_pivot_lows} n_ph={n_pivot_highs} cand_v={n_cand_v} cand_w={n_cand_w} cand_inv_v={n_cand_inv_v} cand_m={n_cand_m} filtered_conf={n_filt_conf} filtered_range={n_filt_range} filtered_bar={n_filt_bar} filtered_prox={n_filt_prox} setups_emitted={n_setups}"),
    # 04/06 P1 R3 reviewer : 2 codes ajoutes pour tracking BN V5 granulaire.
    # Retire PIVOT_DETECTED (redundant CYCLE_SUMMARY n_pl/n_ph) et CANDIDATE_REJECTED
    # (couvert par GATE_*_BLOCK existants) pour eviter VALIDATION_MISS.
    "BN_V5_BAR_PROCESSED":               (LogLevel.INFO,     "decisions", "BN V5 bar : sym={sym} idx={idx} close={close} drift_pct={drift_pct} atr={atr}"),
    "BN_V5_GATE_CONFLUENCE_BLOCK":       (LogLevel.INFO,     "decisions", "BN V5 gate CONFLUENCE block : sym={sym} pattern={pattern} dist_pct={dist_pct} threshold={threshold} nearest_level={nearest_level}"),
    # 04/06 Jackson souverain : VETO proximity_swing symetrique LONG/SHORT.
    # Refuse entry LONG si swing_high recent < entry + threshold_ticks ;
    # refuse entry SHORT si swing_low recent > entry - threshold_ticks.
    # Source : feedback_swing_proximity_veto.md (11/05), trade ES W LONG @7547.5
    # bloque @ swing_high 7549.75 (dist 2.25t < 12t threshold ES).
    "BN_V5_GATE_PROXIMITY_SWING_BLOCK":   (LogLevel.MAJEUR,   "decisions", "BN V5 gate PROXIMITY_SWING block : sym={sym} pattern={pattern} side={side} entry={entry_price} swing_price={swing_price} dist_ticks={dist_ticks} threshold_ticks={threshold_ticks}"),
    "BN_V5_CONFLUENCE_NEAR":             (LogLevel.INFO,     "decisions", "BN V5 confluence proche : sym={sym} pivot_idx={pivot_idx} side={side} level={level} dist_pct={dist_pct}"),
    "BN_V5_PATTERN_CANDIDATE":           (LogLevel.INFO,     "decisions", "BN V5 pattern candidate : sym={sym} pattern={pattern} side={side} pivot1={pivot1} pivot2={pivot2} neckline={neckline}"),
    "BN_V5_PATTERN_REJECTED":            (LogLevel.INFO,     "decisions", "BN V5 pattern rejected : sym={sym} pattern={pattern} side={side} reason={reason} detail={detail}"),
    "BN_V5_POSITION_UPDATE":             (LogLevel.INFO,     "execution", "BN V5 position update : sym={sym} side={side} bars_held={bars_held} sl_current={sl_current} mfe_ticks={mfe_ticks} mae_ticks={mae_ticks} close={close}"),
    "BN_V5_TRAIL_PULLBACK_CONFIRMED":    (LogLevel.INFO,     "execution", "BN V5 pullback confirme : sym={sym} side={side} pullback_extreme={pullback_extreme} running_extreme={running_extreme} bars_since={bars_since}"),
    "BN_V5_DTC_CANCEL_FAIL":             (LogLevel.ALERTE,   "execution", "BN V5 DTC cancel FAIL : sym={sym} cid={cid} kind={kind} err={err}"),
    "BN_V5_DTC_FILL_RECEIVED":           (LogLevel.INFO,     "execution", "BN V5 DTC fill received : sym={sym} cid={cid} kind={kind} fill_price={fill_price} signal_id={signal_id}"),
    "BN_V5_KILL_SWITCH":                 (LogLevel.CRITIQUE, "events",    "BN V5 kill switch active : sym={sym} reason={reason} pnl_session_usd={pnl_session_usd}"),
    # Fix P0#5 code-reviewer 23/05 : ajout gate TOP_LEVEL_BLOCK manquant.
    # find_top_level_price=None rejetait sans trace - maintenant traceable.
    "BN_V4_GATE_TOP_LEVEL_BLOCK":        (LogLevel.MAJEUR,   "decisions", "BN V4 gate TOP_LEVEL block (aucun niveau institutionnel proche) : sym={sym} dir={direction} close={close} max_dist_pct={max_dist_pct}"),
    "BN_V4_SETUP_DETECTED":              (LogLevel.MAJEUR,   "decisions", "BN V4 setup detected : sym={sym} dir={direction} grade={grade} density={density} n_levels={n_levels} mode={mode} entry={entry_price}"),
    "BN_V4_OBSERVATION_LOG":             (LogLevel.INFO,     "decisions", "BN V4 observation log (grade A non-trade) : sym={sym} dir={direction} density={density} entry_simul={entry_price} pnl_simul_R={pnl_simul_R}"),
    # Execution (orders, fills, trail)
    # BN_V4_DTC_CONNECTED RETIRE (doublon avec DTC_CONNECT generique).
    "BN_V4_TRADE_OPEN":                  (LogLevel.MAJEUR,   "execution", "BN V4 trade ouvert : sym={sym} dir={direction} grade={grade} entry={entry_price} sl={sl} risk_ticks={risk_ticks} qty={qty}"),
    "BN_V4_BRACKET_PLACED":              (LogLevel.INFO,     "execution", "BN V4 bracket OCO place : sym={sym} parent_cid={parent_cid} sl_cid={sl_cid} tp_cid={tp_cid}"),
    "BN_V4_TRAIL_SL_UPDATED":            (LogLevel.INFO,     "execution", "BN V4 trailing SL update : sym={sym} dir={direction} old_sl={old_sl} new_sl={new_sl} n_pivots={n_pivots}"),
    "BN_V4_TRAIL_SL_CANCEL_REPLACE":     (LogLevel.MAJEUR,   "execution", "BN V4 trailing SL cancel+replace DTC : sym={sym} old_sl_cid={old_sl_cid} new_sl_cid={new_sl_cid} new_sl_price={new_sl_price}"),
    "BN_V4_TRADE_CLOSE_SL":              (LogLevel.INFO,     "execution", "BN V4 trade close SL : sym={sym} dir={direction} exit={exit_price} pnl_R={pnl_R:.3f} duration_bars={duration_bars}"),
    "BN_V4_TRADE_CLOSE_TIMEOUT":         (LogLevel.MAJEUR,   "execution", "BN V4 trade close timeout 90 bars : sym={sym} dir={direction} exit={exit_price} pnl_R={pnl_R:.3f}"),
    "BN_V4_TRADE_CLOSE_MANUAL":          (LogLevel.MAJEUR,   "execution", "BN V4 trade close manuel (flatten kill) : sym={sym} dir={direction} exit={exit_price} pnl_R={pnl_R:.3f} reason={reason}"),
    "BN_V4_ORPHAN_DETECTED":             (LogLevel.CRITIQUE, "execution", "BN V4 ordre orphelin detecte : sym={sym} order_cid={order_cid} type={order_type} action=cancel_force"),
    # Risk / kill switches
    "BN_V4_RISK_MAX_DD_HIT":             (LogLevel.CRITIQUE, "execution", "BN V4 RISK max DD hit : pnl_session={pnl_session} threshold={threshold} kill_switch=ON"),
    "BN_V4_RISK_3_SL_CONSEC":            (LogLevel.MAJEUR,   "execution", "BN V4 RISK 3 SL consecutifs : sym={sym} dir={direction} cooldown_min={cooldown_min}"),
    "BN_V4_KILL_SWITCH_ACTIVATED":       (LogLevel.CRITIQUE, "events",    "BN V4 KILL SWITCH active : reason={reason} positions_flat={positions_flat} orders_canceled={orders_canceled}"),
    # BN_V4_RISK_KILL_GLOBAL RETIRE (doublon avec BN_V4_KILL_SWITCH_ACTIVATED).
    # Ajout 23/05 Jackson directive "TOUT TRAKER" - enrichissement logs traceability
    "BN_V4_SKIP_COOLDOWN":               (LogLevel.MAJEUR,   "decisions", "BN V4 trade SKIP cooldown actif (3 SL consec) : sym={sym} dir={direction} cooldown_remaining_min={remaining_min}"),
    "BN_V4_SKIP_KILL_SWITCH":            (LogLevel.MAJEUR,   "decisions", "BN V4 trade SKIP kill switch actif : sym={sym} dir={direction} reason={reason}"),
    "BN_V4_SKIP_POSITION_ACTIVE":        (LogLevel.INFO,     "decisions", "BN V4 setup SKIP : position deja ouverte sym={sym} dir_new={direction} dir_pos={direction_pos}"),
    "BN_V4_OUTSIDE_WINDOW_CANDIDATE":    (LogLevel.INFO,     "decisions", "BN V4 candidate setup HORS open_window (WINDOW_OBSERVE mode) : sym={sym} ts_et={ts_et}"),
    "BN_V4_OUTSIDE_WINDOW_LOG":          (LogLevel.INFO,     "decisions", "BN V4 setup A++ HORS window logge dans JSONL dedie : sym={sym} dir={direction} grade={grade} density={density} entry={entry_price} signal_id={signal_id}"),
    "BN_V4_OUTSIDE_WINDOW_LOG_FAIL":     (LogLevel.MAJEUR,   "events",    "BN V4 _log_outside_window_setup CRASH (defensif, bot continue) : sym={sym} err={err}"),
    "BN_V4_SKIP_DRY_RUN":                (LogLevel.INFO,     "decisions", "BN V4 trade SKIP dry_run : sym={sym} dir={direction} entry={entry_price}"),
    "BN_V4_SKIP_ECO_BLOCK":              (LogLevel.MAJEUR,   "decisions", "BN V4 trade SKIP eco_calendar block : sym={sym} dir={direction} grade={grade} reason={reason}"),
    "BN_V4_WARMUP_IN_PROGRESS":          (LogLevel.INFO,     "events",    "BN V4 warmup en cours : sym={sym} bars={bars}/{target} ({pct}%) - edge engine pas encore actif"),
    "BN_V4_FILL_PRICE_INVALID":          (LogLevel.CRITIQUE, "execution", "BN V4 DTC fill INVALID (status!=7 ou fill_price<=0) : sym={sym} cid={cid} kind={kind} signal_id={signal_id} status={msg_status} type={order_type} qty={qty_filled} last={last_fill_price} avg={avg_fill_price} keys={msg_keys} - close ABORT (anti ghost trade)"),
    "BOT3_V3_FILL_PRICE_INVALID":        (LogLevel.CRITIQUE, "execution", "Bot3v3 DTC fill INVALID (status!=7 ou fill_price<=0) : sym={sym} cid={cid} kind={kind} signal_id={signal_id} status={msg_status} type={order_type} qty={qty_filled} last={last_fill_price} avg={avg_fill_price} keys={msg_keys} - close ABORT (anti ghost trade)"),
    "BOT3_V3_ENTRY_SLIP_ANOMALY":        (LogLevel.MAJEUR,   "execution", "Bot3v3 entry slip ANORMAL (>2t) : sym={sym} signal_id={signal_id} direction={direction} entry_planned={entry_planned} entry_filled={entry_filled} slip_ticks={slip_ticks}"),
    "BOT3_V3_FILL_SLIPPAGE_REPORT":      (LogLevel.INFO,     "execution", "Bot3v3 fill slippage report (Phase 1 28/05) : sym={sym} signal_id={signal_id} direction={direction} kind={kind} entry_planned={entry_planned} entry_filled={entry_filled} entry_slip_t={entry_slip_t} exit_planned={exit_planned} exit_filled={exit_filled} sl_slip_t={sl_slip_t} tp_slip_t={tp_slip_t} pnl_R_planned={pnl_R_planned} pnl_R_real={pnl_R_real} pnl_R_slip_delta={pnl_R_slip_delta}"),
    "BOT3_V4_FILL_PRICE_INVALID":        (LogLevel.CRITIQUE, "execution", "Bot3v4 DTC fill INVALID (status!=7 ou fill_price<=0) : sym={sym} cid={cid} kind={kind} signal_id={signal_id} status={msg_status} type={order_type} qty={qty_filled} last={last_fill_price} avg={avg_fill_price} keys={msg_keys} - close ABORT (anti ghost trade)"),
    # 03/06 ajout fix DTC FILL_INVALID : status 6=Rejected / 8=Cancelled = etat terminal a tracer pour audit OCO cancel + rejects (level INFO, pas CRITIQUE)
    "BOT3_V3_ORDER_TERMINAL":            (LogLevel.INFO,     "execution", "Bot3v3 ordre terminal status={msg_status} : sym={sym} cid={cid} kind={kind} signal_id={signal_id} (6=Rejected, 8=Cancelled)"),
    "BOT3_V4_ORDER_TERMINAL":            (LogLevel.INFO,     "execution", "Bot3v4 ordre terminal status={msg_status} : sym={sym} cid={cid} kind={kind} signal_id={signal_id} (6=Rejected, 8=Cancelled)"),
    "BN_V4_SKIP_POST_TRADE_COOLDOWN":    (LogLevel.MAJEUR,   "decisions", "BN V4 trade SKIP post-trade cooldown : sym={sym} dir={direction} grade={grade} reason={reason} remaining={remaining_sec}s"),
    "BOT3_V3_ENTRY_VETO_POST_TRADE_COOLDOWN": (LogLevel.MAJEUR, "decisions", "Bot3v3 entry VETO post-trade cooldown : sym={sym} level={level} side={side} reason={reason} remaining={remaining_sec}s"),
    "BOT3_V4_ENTRY_VETO_POST_TRADE_COOLDOWN": (LogLevel.MAJEUR, "decisions", "Bot3v4 entry VETO post-trade cooldown : sym={sym} level={level} side={side} reason={reason} remaining={remaining_sec}s"),
    "BOT3_V4_TOUCH_FILTERED_TREND":      (LogLevel.MAJEUR,   "decisions", "Bot3v4 touch FILTERED trend : sym={sym} level={level} side={side} vwap_slope={vwap_slope} thr={threshold} session_id={session_id}"),
    "BOT3_V4_SL_OVERRIDE_RECENT_EXTREME":(LogLevel.MAJEUR,   "decisions", "Bot3v4 SL OVERRIDE recent extreme : sym={sym} level={level} side={side} sl_old={sl_old} sl_new={sl_new} new_sl_ticks={new_sl_ticks} session_id={session_id}"),
    "BOT3_V4_SL_ABSOLUTE_CAP_HIT":       (LogLevel.MAJEUR,   "decisions", "Bot3v4 SL ABSOLUTE CAP hit : sym={sym} level={level} side={side} sl_old={sl_old} sl_new={sl_new} old_sl_ticks={old_sl_ticks} new_sl_ticks={new_sl_ticks} cap={absolute_cap} session_id={session_id}"),
    "BOT3_V4_TOUCH_FILTERED_FOOTPRINT":  (LogLevel.MAJEUR,   "decisions", "Bot3v4 touch FILTERED footprint confirmation : sym={sym} level={level} side={side} n_cluster={n_cluster_dn}{n_cluster_up} long_bar={long_dn_bar}{long_up_bar} min={min_cluster} session_id={session_id}"),
    "BOT3_V4_TOUCH_FILTERED_TREND_MISALIGN": (LogLevel.MAJEUR, "decisions", "Bot3v4 touch FILTERED trend misalign : sym={sym} level={level} side={side} vwap_slope={vwap_slope} (SHORT exige slope<0, LONG exige slope>0) session_id={session_id}"),
    # 29/05 FIX Jackson : TOUCH != TRADE (F1 buffer=15t) + aggressor opposite (F2 thr=0.30). Backtest +$117 delta sur 9 trades.
    "BOT3_V4_TOUCH_FILTERED_CLOSE_UNFAVORABLE": (LogLevel.MAJEUR, "decisions", "Bot3v4 touch FILTERED close unfavorable (TOUCH!=TRADE) : sym={sym} level={level} side={side} close={close} level_price={level_price} buffer_ticks={buffer_ticks} session_id={session_id}"),
    "BOT3_V4_TOUCH_FILTERED_AGGRESSOR_OPPOSITE": (LogLevel.MAJEUR, "decisions", "Bot3v4 touch FILTERED aggressor opposite : sym={sym} level={level} side={side} aggressor_imbalance={aggressor_imbalance} threshold={threshold} session_id={session_id}"),
    "BOT3_V4_TOUCH_F1_BYPASSED_NO_LEVEL_PRICE": (LogLevel.ALERTE, "decisions", "Bot3v4 F1 BYPASS no level_price : sym={sym} level={level} side={side} level_col={level_col} (anti VALIDATION_MISS) session_id={session_id}"),
    "BOT3_V4_TOUCH_F2_BYPASSED_NO_AGGRESSOR": (LogLevel.ALERTE, "decisions", "Bot3v4 F2 BYPASS no aggressor_imbalance : sym={sym} level={level} side={side} (anti VALIDATION_MISS) session_id={session_id}"),
    # 29/05 FIX F3 Jackson : state machine confirmation post-TOUCH (require_confirmation_next_bar)
    "BOT3_V4_TOUCH_PENDING_CONFIRMATION": (LogLevel.INFO, "decisions", "Bot3v4 TOUCH PENDING confirmation : sym={sym} level={level} side={side} close={close} level_price={level_price} bar_idx={bar_idx} session_id={session_id}"),
    "BOT3_V4_TOUCH_CONFIRMED_ENTRY":     (LogLevel.MAJEUR, "decisions", "Bot3v4 TOUCH CONFIRMED entry : sym={sym} level={level} side={side} close={close} level_price={level_price} age_bars={age_bars} session_id={session_id}"),
    "BOT3_V4_TOUCH_CONFIRMATION_INVALIDATED": (LogLevel.MAJEUR, "decisions", "Bot3v4 TOUCH confirmation INVALIDATED : sym={sym} level={level} side={side} close={close} level_price={level_price} buffer_ticks={buffer_ticks} session_id={session_id}"),
    # 03/06/2026 Jackson : combo filter pre-entry (anti falling knife / rallye persistent)
    "BOT3_V4_VETO_COMBO_PRE_PRICE":        (LogLevel.MAJEUR, "decisions", "Bot3v4 VETO combo pre_price (falling knife/rallye) : sym={sym} level={level} side={side} pre_price_chg_t={pre_price_chg_t} threshold={threshold}"),
    "BOT3_V4_VETO_COMBO_SLOPE":            (LogLevel.MAJEUR, "decisions", "Bot3v4 VETO combo slope (trend violent contraire) : sym={sym} level={level} side={side} slope={slope} threshold={threshold}"),
    "BOT3_V4_VETO_COMBO_AGGRESSOR":        (LogLevel.MAJEUR, "decisions", "Bot3v4 VETO combo aggressor LONG (vendeurs forts) : sym={sym} level={level} side={side} aggressor={aggressor} threshold={threshold}"),
    "BOT3_V4_VETO_COMBO_DELTA_SHORT":      (LogLevel.MAJEUR, "decisions", "Bot3v4 VETO combo delta SHORT (acheteurs forts) : sym={sym} level={level} side={side} delta_bar={delta_bar} threshold={threshold}"),
    "BOT3_V4_TOUCH_CONFIRMATION_TIMEOUT": (LogLevel.ALERTE, "decisions", "Bot3v4 TOUCH confirmation TIMEOUT : sym={sym} level={level} side={side} age_bars={age_bars} max_age={max_age} session_id={session_id}"),
    # 29/05 FIX Jackson : SLOPE ALIGNMENT GATE Bot 1 (V3 + MP via paper_v2)
    "BOT1_SLOPE_GATE_VETO_LONG_AGAINST_DOWNTREND": (LogLevel.MAJEUR, "decisions", "Bot1 SLOPE GATE veto LONG contre downtrend : sym={sym} level={level} side={side} vslp={vslp} signal_id={signal_id}"),
    "BOT1_SLOPE_GATE_VETO_SHORT_AGAINST_UPTREND": (LogLevel.MAJEUR, "decisions", "Bot1 SLOPE GATE veto SHORT contre uptrend : sym={sym} level={level} side={side} vslp={vslp} signal_id={signal_id}"),
    "BOT1_SLOPE_GATE_BYPASS_NO_DATA":    (LogLevel.ALERTE,   "decisions", "Bot1 SLOPE GATE BYPASS no vwap_slope_10 (anti VALIDATION_MISS) : sym={sym} level={level} side={side} signal_id={signal_id}"),
    "BOT3_V4_PARAM_OVERRIDE_ENV":        (LogLevel.MAJEUR,   "events", "Bot3v4 param override env var : param={param} override_value={override_value} source={source}"),
    "BOT3_V4_PARAM_OVERRIDE_ENV_FAIL":   (LogLevel.ALERTE,   "events", "Bot3v4 param override env var FAIL parse : param={param} raw_value={raw_value} err={err}"),
    "BOT3_V3_RETEST_FILTERED_TREND_MISALIGN": (LogLevel.MAJEUR, "decisions", "Bot3v3 retest FILTERED trend : sym={sym} level={level} side={side} vwap_slope={vwap_slope} veto_reason={veto_reason} min_slope_abs={min_slope_abs} session_id={session_id}"),
    "BOT3_V3_VETO_SLOPE_DIVERGENCE":     (LogLevel.MAJEUR, "decisions", "Bot3v3 VETO L2 slope divergence : sym={sym} level={level} side={side} slope_10={slope_10} slope_5={slope_5} threshold={threshold} session_id={session_id}"),
    "BOT3_V3_VETO_NO_SLOPE5_DATA":       (LogLevel.MAJEUR, "decisions", "Bot3v3 VETO L2 fail-CLOSED : ctx_price_slope_5 absent sym={sym} level={level} side={side} session_id={session_id}"),
    "BOT3_V3_SL_FIXED_MODE":             (LogLevel.INFO,     "decisions", "Bot3v3 SL/TP FIXE mode actif : sym={sym} side={side} sl_ticks={sl_ticks} tp_ticks={tp_ticks} RR={rr}"),
    "BOT3_V3_VETO_NO_SLOPE_DATA":        (LogLevel.MAJEUR,   "decisions", "Bot3v3 retest VETO no slope data : sym={sym} level={level} side={side} (vwap_slope_10 absent en mode trend_alignment_required, fail-closed par securite)"),
    "BN_V4_GATE_SL_RISK_BLOCK":          (LogLevel.MAJEUR,   "decisions", "BN V4 gate SL_RISK block : sym={sym} dir={direction} entry={entry} err={err} (setup skip propre, pas crash)"),
    "BOT3_V3_SL_FALLBACK_REASON":        (LogLevel.INFO,     "decisions", "Bot3v3 SL fallback reason : sym={sym} side={side} reason={reason} sl_ticks={sl_ticks} swing_raw={swing_raw_ticks} sl_max={sl_max} sl_fallback={sl_fallback} atr_pts={atr_pts}"),
    "BOT3_V4_SL_FALLBACK_REASON":        (LogLevel.INFO,     "decisions", "Bot3v4 SL fallback reason : sym={sym} side={side} reason={reason} sl_ticks={sl_ticks} swing_raw={swing_raw_ticks} sl_max={sl_max} sl_fallback={sl_fallback} atr_pts={atr_pts}"),
    "BOT3_V3_TOUCH_FILTERED_FOOTPRINT":  (LogLevel.MAJEUR,   "decisions", "Bot3v3 retest FILTERED footprint confirmation : sym={sym} level={level} side={side} n_cluster={n_cluster} long_bar={long_bar} session_id={session_id}"),
    "ECO_CALENDAR_FAIL_FAILCLOSED":      (LogLevel.CRITIQUE, "events",    "eco_calendar module FAIL (import/runtime) : sym={sym} bot={bot} err={err} -> fail-closed (refuse trade par securite)"),
    "BN_V4_RISK_COOLDOWN_ACTIVATED":     (LogLevel.MAJEUR,   "execution", "BN V4 RISK cooldown ACTIVATED : sym={sym} consec_sl={consec_sl} cooldown_min={cooldown_min} expires={expires_iso}"),
    "BN_V4_RISK_COOLDOWN_EXPIRED":       (LogLevel.INFO,     "events",    "BN V4 RISK cooldown EXPIRED : sym={sym} trades reprises"),
    "BN_V4_DTC_DOWN":                    (LogLevel.CRITIQUE, "events",    "BN V4 DTC down (connexion broken) : sym={sym} action=skip_cycle_until_reconnect"),
    # BN_V4_DTC_RECONNECT RETIRE (pas de detection auto reconnect implementee).
    "BN_V4_SETUP_DTC_ABORT":             (LogLevel.MAJEUR,   "execution", "BN V4 setup detected mais bracket DTC abort : sym={sym} dir={direction} reason={reason}"),
    "BN_V4_HEARTBEAT":                   (LogLevel.INFO,     "events",    "BN V4 heartbeat : sym={sym} uptime_min={uptime_min} bars={n_bars} setups={n_setups} trades={n_trades} pnl_usd={pnl_usd}"),
    "BN_V4_DATA_STATS":                  (LogLevel.INFO,     "events",    "BN V4 data stats periodic : sym={sym} bars_buffer={bars_buffer} last_close={last_close} last_bar_age_sec={age_sec}"),
    # BN_V4_GATE_OBSERVE_LIMIT RETIRE (couvert par check_zone return None
    # quand grade_value < observe_threshold, pas besoin de code distinct).
    # ════════════════════════════════════════════════════════════════════════
    # BOT 3 v3 CONTINUATION (Sim1 NQ — paper deploy 24/05/2026)
    # Backtest baseline : n=1611 WR43% PF1.045 DSR0.21 PF_min_fold=0.75 sur 130j.
    # State machine 4 etats : WAITING_TOUCH → ARMED → BREAKOUT → WAITING_RETEST → CONFIRMATION → ENTRY
    # 22 niveaux V1_LONG + V4_SHORT, SL swing-based, TP 1.5R, news veto fail-closed.
    # Source data unique : JSONL live_enriched (lag 60s).
    # ════════════════════════════════════════════════════════════════════════
    # Lifecycle (Bot 3 v3)
    "BOT3_V3_BOOT_START":                (LogLevel.INFO,     "events",    "Bot3v3 boot start : sym={sym} dry_run={dry_run} trade_account={trade_account} mode={mode}"),
    "BOT3_V3_CONFIG_LOADED":             (LogLevel.INFO,     "events",    "Bot3v3 config loaded : touch_buf={touch_buf} breakout_buf={breakout_buf} retest_buf={retest_buf} w_touch_brk={w1} w_brk_retest={w2} w_retest_conf={w3} target_R={target_R} sl_fallback_t={sl_fallback} max_risk_t={max_risk_t}"),
    "BOT3_V3_BOOT_READY":                (LogLevel.INFO,     "events",    "Bot3v3 boot ready : sym={sym} dtc_state={dtc_state} reader_state={reader_state} levels_loaded={n_levels}"),
    "BOT3_V3_SHUTDOWN":                  (LogLevel.MAJEUR,   "events",    "Bot3v3 shutdown : reason={reason} positions_open={positions_open}"),
    "BOT3_V3_LOOP_ERROR":                (LogLevel.CRITIQUE, "events",    "Bot3v3 loop error : sym={sym} err={err}"),
    "BOT3_V3_HEARTBEAT":                 (LogLevel.INFO,     "events",    "Bot3v3 heartbeat : sym={sym} uptime_min={uptime_min} bars={n_bars} touches={n_touches} entries={n_entries} trades={n_trades} pnl_usd={pnl_usd}"),
    "BOT3_V3_BAR_STALE":                 (LogLevel.ALERTE,   "events",    "Bot3v3 bar stale skip cycle : sym={sym} age_sec={age_sec} threshold_sec={threshold_sec}"),
    # State machine transitions
    "BOT3_V3_TOUCH_DETECTED":            (LogLevel.INFO,     "decisions", "Bot3v3 TOUCH detected : sym={sym} level={level} side={side} dist_pct={dist_pct} touch_idx={touch_idx}"),
    "BOT3_V3_STATE_ARMED":               (LogLevel.INFO,     "decisions", "Bot3v3 state ARMED (post-touch) : sym={sym} level={level} side={side} level_price={level_price}"),
    "BOT3_V3_BREAKOUT_CONFIRMED":        (LogLevel.INFO,     "decisions", "Bot3v3 BREAKOUT confirmed : sym={sym} level={level} side={side} close={close} threshold={threshold} bars_since_touch={bars_since_touch}"),
    "BOT3_V3_RETEST_DETECTED":           (LogLevel.INFO,     "decisions", "Bot3v3 RETEST detected : sym={sym} level={level} side={side} close={close} bars_since_breakout={bars_since_breakout}"),
    "BOT3_V3_CONFIRMATION_OK":           (LogLevel.MAJEUR,   "decisions", "Bot3v3 CONFIRMATION OK (entry signal) : sym={sym} level={level} side={side} confirm_bar={confirm_bar} entry_close={entry_close}"),
    "BOT3_V3_STATE_TIMEOUT":             (LogLevel.INFO,     "decisions", "Bot3v3 state TIMEOUT (reset) : sym={sym} level={level} state={state} bars_in_state={bars}"),
    # Entry / DTC / Trade lifecycle
    "BOT3_V3_ENTRY_VETO_NEWS":           (LogLevel.MAJEUR,   "decisions", "Bot3v3 entry VETO news : sym={sym} level={level} side={side} mins_since={mins_since} mins_to_next={mins_to_next}"),
    "BOT3_V3_ENTRY_VETO_ECO_BLOCK":      (LogLevel.MAJEUR,   "decisions", "Bot3v3 entry VETO eco_calendar : sym={sym} level={level} side={side} reason={reason}"),
    "BOT3_V3_ENTRY_VETO_POSITION":       (LogLevel.INFO,     "decisions", "Bot3v3 entry VETO position active : sym={sym} level={level} side_new={side} side_pos={side_pos}"),
    "BOT3_V3_ENTRY_VETO_KILL_SWITCH":    (LogLevel.MAJEUR,   "decisions", "Bot3v3 entry VETO kill switch : sym={sym} level={level} side={side} reason={reason}"),
    "BOT3_V3_ENTRY_VETO_DRY_RUN":        (LogLevel.INFO,     "decisions", "Bot3v3 entry SKIP dry_run : sym={sym} level={level} side={side} entry_close={entry_close} sl={sl} tp={tp}"),
    "BOT3_V3_TRADE_OPEN":                (LogLevel.MAJEUR,   "execution", "Bot3v3 trade ouvert : sym={sym} level={level} side={side} entry={entry_price} sl={sl_price} tp={tp_price} sl_ticks={sl_ticks} qty={qty}"),
    "BOT3_V3_BRACKET_PLACED":            (LogLevel.INFO,     "execution", "Bot3v3 bracket OCO place : sym={sym} parent_cid={parent_cid} tp_cid={tp_cid} sl_cid={sl_cid} trade_account={trade_account}"),
    "BOT3_V3_SETUP_DTC_ABORT":           (LogLevel.MAJEUR,   "execution", "Bot3v3 setup detected mais bracket DTC abort : sym={sym} level={level} side={side} reason={reason}"),
    "BOT3_V3_TRADE_CLOSE_TP":            (LogLevel.INFO,     "execution", "Bot3v3 trade close TP : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R} pnl_usd={pnl_usd} duration_bars={duration_bars}"),
    "BOT3_V3_TRADE_CLOSE_SL":            (LogLevel.INFO,     "execution", "Bot3v3 trade close SL : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R} pnl_usd={pnl_usd} duration_bars={duration_bars}"),
    "BOT3_V3_TRADE_CLOSE_TIMEOUT":       (LogLevel.MAJEUR,   "execution", "Bot3v3 trade close timeout {timeout_bars}b : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R}"),
    "BOT3_V3_TRADE_CLOSE_EOD":           (LogLevel.INFO,     "execution", "Bot3v3 trade close EOD : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R}"),
    "BOT3_V3_TRADE_CLOSE_MANUAL":        (LogLevel.MAJEUR,   "execution", "Bot3v3 trade close manuel (kill flatten) : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R} reason={reason}"),
    # DTC / anti-orphan (sequence 9 etapes cf orphan-prevention.md)
    "BOT3_V3_DTC_DOWN":                  (LogLevel.CRITIQUE, "events",    "Bot3v3 DTC down (connexion broken) : sym={sym} action=skip_cycle_until_reconnect"),
    "BOT3_V3_ORPHAN_DETECTED":           (LogLevel.CRITIQUE, "execution", "Bot3v3 ordre orphelin detecte : sym={sym} order_cid={order_cid} type={order_type} action=cancel_force"),
    "BOT3_V3_ORPHAN_CLEANUP_OK":         (LogLevel.MAJEUR,   "execution", "Bot3v3 orphan cleanup OK : sym={sym} canceled_cids={canceled_cids} qty_final={qty_final}"),
    "BOT3_V3_ORPHAN_CLEANUP_FAIL":       (LogLevel.CRITIQUE, "execution", "Bot3v3 orphan cleanup FAIL : sym={sym} failed_cids={failed_cids} qty_residual={qty_residual} action=manual_intervention"),
    "BOT3_V3_POSITION_FANTOME":          (LogLevel.CRITIQUE, "execution", "Bot3v3 position fantome detectee (no tracking) : sym={sym} qty_broker={qty_broker} action=force_flatten"),
    # Risk / kill switches
    "BOT3_V3_KILL_DD_DAILY":             (LogLevel.CRITIQUE, "execution", "Bot3v3 KILL daily DD hit : pnl_session={pnl_session} threshold={threshold} kill_switch=ON"),
    "BOT3_V3_KILL_DD_CUMULATIVE":        (LogLevel.CRITIQUE, "execution", "Bot3v3 KILL cumulative DD hit (paper) : pnl_cumulative_R={pnl_cumulative_R} threshold_R={threshold_R}"),
    "BOT3_V3_KILL_MANUAL":               (LogLevel.MAJEUR,   "events",    "Bot3v3 KILL manual : reason={reason} positions_flat={positions_flat} orders_canceled={orders_canceled}"),

    # ════════════════════════════════════════════════════════════════════════
    # BOT 3 v4 DATA-DRIVEN (Sim3 NQ — paper deploy 24/05/2026)
    # Backtest baseline : n=1110 WR30% PF1.033 DSR0.13 PF_min_fold=0.51 sur 130j.
    # 6 triggers asymetriques empiriques (analyse 54K bounces) :
    #   LONG : SWING_LOW (81%), VWAP_D_SD2D (72%), CUR_VAL (61%)
    #   SHORT : SWING_HIGH (76%), VWAP_D_SD2U (72%), CUR_VAH (63%)
    # TP CUR_VPOC magnet (CRITIQUE : R1.5 fixe detruit signal, PF 0.74 vs 1.03).
    # ════════════════════════════════════════════════════════════════════════
    # Lifecycle (Bot 3 v4)
    "BOT3_V4_BOOT_START":                (LogLevel.INFO,     "events",    "Bot3v4 boot start : sym={sym} dry_run={dry_run} trade_account={trade_account} mode={mode}"),
    "BOT3_V4_CONFIG_LOADED":             (LogLevel.INFO,     "events",    "Bot3v4 config loaded : touch_buf={touch_buf} cooldown_bars={cooldown_bars} max_per_day={max_per_day} sl_fallback_t={sl_fallback} tp_mode={tp_mode} timeout_bars={timeout_bars}"),
    "BOT3_V4_BOOT_READY":                (LogLevel.INFO,     "events",    "Bot3v4 boot ready : sym={sym} dtc_state={dtc_state} reader_state={reader_state} triggers_long={n_triggers_long} triggers_short={n_triggers_short}"),
    "BOT3_V4_SHUTDOWN":                  (LogLevel.MAJEUR,   "events",    "Bot3v4 shutdown : reason={reason} positions_open={positions_open}"),
    "BOT3_V4_LOOP_ERROR":                (LogLevel.CRITIQUE, "events",    "Bot3v4 loop error : sym={sym} err={err}"),
    "BOT3_V4_HEARTBEAT":                 (LogLevel.INFO,     "events",    "Bot3v4 heartbeat : sym={sym} uptime_min={uptime_min} bars={n_bars} touches={n_touches} entries={n_entries} trades={n_trades} pnl_usd={pnl_usd}"),
    "BOT3_V4_BAR_STALE":                 (LogLevel.ALERTE,   "events",    "Bot3v4 bar stale skip cycle : sym={sym} age_sec={age_sec} threshold_sec={threshold_sec}"),
    # Touch detection
    "BOT3_V4_TOUCH_DETECTED":            (LogLevel.INFO,     "decisions", "Bot3v4 TOUCH first-time detected : sym={sym} level={level} side={side} dist_pct={dist_pct} asym_prob={asym_prob}"),
    "BOT3_V4_TOUCH_FILTERED_COOLDOWN":   (LogLevel.INFO,     "decisions", "Bot3v4 touch filtered cooldown : sym={sym} level={level} bars_since_last={bars_since_last} cooldown={cooldown}"),
    "BOT3_V4_TOUCH_FILTERED_DAILY_CAP":  (LogLevel.INFO,     "decisions", "Bot3v4 touch filtered daily cap : sym={sym} level={level} count_today={count_today} cap={cap}"),
    # TP magnet logic
    "BOT3_V4_TP_VPOC_MAGNET":            (LogLevel.INFO,     "decisions", "Bot3v4 TP cur_vpoc magnet used : sym={sym} side={side} entry={entry} vpoc={vpoc} tp={tp_price}"),
    "BOT3_V4_TP_FALLBACK_R15":           (LogLevel.INFO,     "decisions", "Bot3v4 TP fallback R1.5 (vpoc too close/far) : sym={sym} side={side} entry={entry} vpoc={vpoc} tp_r15={tp_r15} reason={reason}"),
    # Entry / DTC / Trade
    "BOT3_V4_ENTRY_VETO_NEWS":           (LogLevel.MAJEUR,   "decisions", "Bot3v4 entry VETO news : sym={sym} level={level} side={side} mins_since={mins_since} mins_to_next={mins_to_next}"),
    "BOT3_V4_ENTRY_VETO_ECO_BLOCK":      (LogLevel.MAJEUR,   "decisions", "Bot3v4 entry VETO eco_calendar : sym={sym} level={level} side={side} reason={reason}"),
    "BOT3_V4_ENTRY_VETO_POSITION":       (LogLevel.INFO,     "decisions", "Bot3v4 entry VETO position active : sym={sym} level={level} side_new={side} side_pos={side_pos}"),
    "BOT3_V4_ENTRY_VETO_KILL_SWITCH":    (LogLevel.MAJEUR,   "decisions", "Bot3v4 entry VETO kill switch : sym={sym} level={level} side={side} reason={reason}"),
    "BOT3_V4_ENTRY_VETO_DRY_RUN":        (LogLevel.INFO,     "decisions", "Bot3v4 entry SKIP dry_run : sym={sym} level={level} side={side} entry_close={entry_close} sl={sl} tp={tp}"),
    "BOT3_V4_TRADE_OPEN":                (LogLevel.MAJEUR,   "execution", "Bot3v4 trade ouvert : sym={sym} level={level} side={side} entry={entry_price} sl={sl_price} tp={tp_price} sl_ticks={sl_ticks} qty={qty}"),
    "BOT3_V4_BRACKET_PLACED":            (LogLevel.INFO,     "execution", "Bot3v4 bracket OCO place : sym={sym} parent_cid={parent_cid} tp_cid={tp_cid} sl_cid={sl_cid} trade_account={trade_account}"),
    "BOT3_V4_SETUP_DTC_ABORT":           (LogLevel.MAJEUR,   "execution", "Bot3v4 setup detected mais bracket DTC abort : sym={sym} level={level} side={side} reason={reason}"),
    "BOT3_V4_TRADE_CLOSE_TP":            (LogLevel.INFO,     "execution", "Bot3v4 trade close TP : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R} pnl_usd={pnl_usd} duration_bars={duration_bars}"),
    "BOT3_V4_TRADE_CLOSE_SL":            (LogLevel.INFO,     "execution", "Bot3v4 trade close SL : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R} pnl_usd={pnl_usd} duration_bars={duration_bars}"),
    "BOT3_V4_TRADE_CLOSE_TIMEOUT":       (LogLevel.MAJEUR,   "execution", "Bot3v4 trade close timeout {timeout_bars}b : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R}"),
    "BOT3_V4_TRADE_CLOSE_EOD":           (LogLevel.INFO,     "execution", "Bot3v4 trade close EOD : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R}"),
    "BOT3_V4_TRADE_CLOSE_MANUAL":        (LogLevel.MAJEUR,   "execution", "Bot3v4 trade close manuel (kill flatten) : sym={sym} level={level} side={side} exit={exit_price} pnl_R={pnl_R} reason={reason}"),
    # DTC / anti-orphan
    "BOT3_V4_DTC_DOWN":                  (LogLevel.CRITIQUE, "events",    "Bot3v4 DTC down (connexion broken) : sym={sym} action=skip_cycle_until_reconnect"),
    "BOT3_V4_ORPHAN_DETECTED":           (LogLevel.CRITIQUE, "execution", "Bot3v4 ordre orphelin detecte : sym={sym} order_cid={order_cid} type={order_type} action=cancel_force"),
    "BOT3_V4_ORPHAN_CLEANUP_OK":         (LogLevel.MAJEUR,   "execution", "Bot3v4 orphan cleanup OK : sym={sym} canceled_cids={canceled_cids} qty_final={qty_final}"),
    "BOT3_V4_ORPHAN_CLEANUP_FAIL":       (LogLevel.CRITIQUE, "execution", "Bot3v4 orphan cleanup FAIL : sym={sym} failed_cids={failed_cids} qty_residual={qty_residual} action=manual_intervention"),
    "BOT3_V4_POSITION_FANTOME":          (LogLevel.CRITIQUE, "execution", "Bot3v4 position fantome detectee (no tracking) : sym={sym} qty_broker={qty_broker} action=force_flatten"),
    # Risk / kill switches
    "BOT3_V4_KILL_DD_DAILY":             (LogLevel.CRITIQUE, "execution", "Bot3v4 KILL daily DD hit : pnl_session={pnl_session} threshold={threshold} kill_switch=ON"),
    "BOT3_V4_KILL_DD_CUMULATIVE":        (LogLevel.CRITIQUE, "execution", "Bot3v4 KILL cumulative DD hit (paper) : pnl_cumulative_R={pnl_cumulative_R} threshold_R={threshold_R}"),
    "BOT3_V4_KILL_MANUAL":               (LogLevel.MAJEUR,   "events",    "Bot3v4 KILL manual : reason={reason} positions_flat={positions_flat} orders_canceled={orders_canceled}"),

    # P1.1 (06/05) : shutdown pre-emptive cancel
    "BOT3_SHUTDOWN_PREEMPTIVE_CANCEL":   (LogLevel.MAJEUR,   "execution", "Bot 3 shutdown pre-emptive cancel : {sym} label={label} cid={cid}"),
    "BOT3_SHUTDOWN_CANCEL_FAIL":         (LogLevel.ALERTE,   "execution", "Bot 3 shutdown cancel fail : {sym} label={label} err={err}"),
    # P1.2 (06/05) : drain disconnect
    "DTC_DISCONNECT_DRAIN_TIMEOUT":      (LogLevel.ALERTE,   "execution", "DTC disconnect drain timeout : drain_sec={drain_sec} thread non-termine"),
    # P0.1 (06/05) : query OPEN_ORDERS partial timeout
    "OPEN_ORDERS_QUERY_TIMEOUT":         (LogLevel.ALERTE,   "execution", "DTC Type 300 OPEN_ORDERS timeout : trade_account={trade_account} partial_count={partial_count}"),
    "OPEN_ORDERS_QUERY_LOCK_TIMEOUT":    (LogLevel.ALERTE,   "execution", "DTC Type 300 lock timeout (concurrent query) : trade_account={trade_account}"),
    # FIX 06/05 soir : on_order_update callback (consume msg dict brut Type 301)
    "ON_ORDER_UPDATE_CALLBACK_ERR":      (LogLevel.ALERTE,   "execution", "DTC on_order_update callback exception : cid={cid} err={err}"),
    # 07/05 audit walk-forward TREND DAY override pour ChaseTopGate
    "GATE_CHASE_TOP_TREND_DAY_BYPASS":   (LogLevel.INFO,     "decisions", "ChaseTopGate BYPASS TREND DAY : {symbol} {direction} range_pos={range_pos}% trend_votes={trend_votes} favor={regime_favor} median_range_pos={median_range_pos}% n_history={n_history}"),
    # 07/05 PHASE 1 OBSERVATION trailing + BE Bot 3 (Jackson directive)
    "BOT3_TRAILING_BE_OBSERVED":         (LogLevel.INFO,     "execution", "Bot 3 trailing BE trigger OBSERVED : {sym} {side} level={level} entry={entry_price} mfe={current_mfe_ticks}t >= {be_trigger_ticks}t → SL hypothetique BE={sl_hypothetical_be} (sl_actuel={sl_current})"),
    "BOT3_TRAILING_UPDATE_OBSERVED":     (LogLevel.INFO,     "execution", "Bot 3 trailing UPDATE OBSERVED : {sym} {side} level={level} mfe={current_mfe_ticks}t mfe_price={mfe_price} → SL hypothetique trailing={sl_hypothetical_trailing} (sl_actuel={sl_current} dist={trailing_distance_ticks}t)"),
    # 11/05 SOLUTION D2 LADDER PROFIT-LOCKING Bot 3 (Jackson directive "pas gourmand")
    "BOT3_LADDER_TICK":                  (LogLevel.INFO,     "execution", "Bot 3 ladder TICK : {sym} mfe={mfe}t entry={entry} n_paliers={n_paliers} executed={executed_count} mode={mode}"),
    "BOT3_LADDER_WOULD_LOCK":            (LogLevel.MAJEUR,   "execution", "Bot 3 ladder WOULD LOCK palier {palier} : {sym} {side} mfe={mfe_ticks}t >= seuil {mfe_seuil_ticks}t → SL new={sl_new_price} lock=${lock_usd}"),
    "BOT3_LADDER_ACTION_NOT_IMPLEMENTED_YET": (LogLevel.ALERTE, "execution", "Bot 3 ladder ACTION mode not implemented yet (Phase 1b) : {sym} palier={palier} {msg}"),
    "BOT3_LADDER_INVALID_MODE":          (LogLevel.ALERTE,   "execution", "Bot 3 ladder INVALID MODE : {sym} mode={mode} {msg}"),
    # 11/05 17:00 PHASE 1b ACTION — vrai cancel/replace SL via DTC avec 7 fixes anti-orphan
    "BOT3_LADDER_SL_MODIFIED":           (LogLevel.MAJEUR,   "execution", "Bot 3 ladder SL MODIFIED palier {palier} : {sym} {side} level={level} old_cid={old_sl_cid} new_cid={new_sl_cid} new_sl={new_sl_price} lock=${lock_usd}"),
    "BOT3_LADDER_NO_SL_ALERT":           (LogLevel.CRITIQUE, "execution", "Bot 3 ladder NO SL ALERT — position sans SL = ORPHAN RISK : {sym} palier={palier} level={level} old_sl_cid={old_sl_cid} entry={entry} attempted_new_sl={attempted_new_sl} {msg}"),
    "BOT3_LADDER_MODIFY_DTC_DOWN":       (LogLevel.CRITIQUE, "execution", "Bot 3 ladder MODIFY DTC DOWN : {sym} palier={palier} {msg}"),
    "BOT3_LADDER_MODIFY_NO_OLD_SL_CID":  (LogLevel.ALERTE,   "execution", "Bot 3 ladder MODIFY skip — pos.sl_cid manquant : {sym} palier={palier} {msg}"),
    "BOT3_LADDER_MODIFY_CONTRACT_LOOKUP_FAIL": (LogLevel.CRITIQUE, "execution", "Bot 3 ladder MODIFY contract lookup FAIL : {sym} palier={palier}"),
    "BOT3_LADDER_CANCEL_EXCEPTION":      (LogLevel.CRITIQUE, "execution", "Bot 3 ladder CANCEL exception : {sym} palier={palier} old_sl_cid={old_sl_cid} exc={exc} msg={msg}"),
    "BOT3_LADDER_CANCEL_FAILED":         (LogLevel.CRITIQUE, "execution", "Bot 3 ladder CANCEL returned False : {sym} palier={palier} old_sl_cid={old_sl_cid} {msg}"),
    "BOT3_LADDER_SEND_NEW_SL_EXCEPTION": (LogLevel.CRITIQUE, "execution", "Bot 3 ladder SEND new SL exception : {sym} palier={palier} new_sl_cid={new_sl_cid} exc={exc} msg={msg}"),
    # 11/05 17:30 PHASE 1b ACTION review code-reviewer — fix #2 race condition (request_position_blocking)
    "BOT3_LADDER_POS_VERIFY_EXCEPTION":  (LogLevel.CRITIQUE, "execution", "Bot 3 ladder POS verify exception : {sym} palier={palier} exc={exc} msg={msg}"),
    "BOT3_LADDER_POS_VERIFY_TIMEOUT":    (LogLevel.CRITIQUE, "execution", "Bot 3 ladder POS verify TIMEOUT : {sym} palier={palier} {msg}"),
    "BOT3_LADDER_POS_CLOSED_DURING_MODIFY": (LogLevel.CRITIQUE, "execution", "Bot 3 ladder POS CLOSED pendant modify (anti trade inverse) : {sym} palier={palier} old_sl_cid={old_sl_cid} {msg}"),
    # 11/05 Jackson "met a jour les log on dois pouvoir suivre tout les blocage"
    # 5 blocages silencieux dans _bot3_poll_cycle + _bot3_execute_trade
    # Niveaux affines apres review code-reviewer 11/05 (anti-spam Discord)
    "BOT3_BAR_NONE":             (LogLevel.INFO,     "execution", "Bot 3 blocage bar manquante : {sym} load_last_bar=None (throttle 60s)"),
    "BOT3_BAR_STALE":            (LogLevel.ALERTE,   "execution", "Bot 3 blocage bar stale : {sym} age={age}s > limit={limit}s (throttle 300s)"),
    "BOT3_OBSERVE_ONLY_SKIP":    (LogLevel.INFO,     "execution", "Bot 3 blocage OBSERVE_ONLY actif (paper desactive) : {sym} {side} level={level}"),
    "BOT3_EXECUTE_DTC_DOWN":     (LogLevel.MAJEUR,   "execution", "Bot 3 blocage execute_trade abort DTC down : {sym} {side} level={level}"),
    "BOT3_ALREADY_IN_POSITION":  (LogLevel.INFO,     "execution", "Bot 3 blocage deja en position : {sym} level={level} side={side} mfe={mfe_ticks}t (throttle 300s)"),
    # 11/05 J3 FIX BUG COOLDOWN : persistance _bot3_risk state au restart
    "BOT3_RISK_STATE_RESTORED":  (LogLevel.INFO,     "events",    "Bot 3 risk state restore au boot : n_last_close={n_last_close} consec_sl NQ={consec_sl_nq} ES={consec_sl_es}"),
    # 11/05 audit code-reviewer post-incident ES.c.0 ohlcv-1m stuck 2h+
    # 12/05 fix v3 ajustement niveaux post observation midnight UTC false positifs :
    # - EMPTY_RESPONSE CRITIQUE (garde-fou ES stuck 2h+ original)
    # - NON_RETRY_EXC CRITIQUE (exception non-recuperable = vrai signal)
    # - STALE_POST_FETCH MAJEUR (peut etre transient midnight UTC) au lieu de CRITIQUE
    #   pour eviter spam widget health_checker.check_recent_errors (filtre CRITIQUE).
    #   Logique : si vraiment grave (ES stuck heures), DMP_JSONL_STALE deja CRITIQUE alerte.
    "DOWNLOAD_EMPTY_RESPONSE":   (LogLevel.CRITIQUE, "data", "Databento API empty response (0 records) : {schema} {symbol} {day} end={end} - DBN preserve (pas overwrite vide)"),
    "DOWNLOAD_NON_RETRY_EXC":    (LogLevel.CRITIQUE, "data", "Databento download exception non-retry : {schema} {symbol} {day} type={exc_type} msg={exc_msg}"),
    "DOWNLOAD_TOO_EARLY":        (LogLevel.INFO,     "data", "Databento download trop tot (fenetre vide debut de journee) : {schema} {symbol} {day} start={start} end={end} - skip, rien a telecharger"),
    "DOWNLOAD_STALE_POST_FETCH": (LogLevel.MAJEUR,   "data", "Post-DL : fichier non refresh apres call API : {schema} {symbol} reason={reason}"),

    # Anomalies generiques python (paper_trader)
    # Permet de tracker exceptions Python uncaught dans hot paths
    "PY_EXCEPTION_HOT_PATH":     (LogLevel.CRITIQUE, "events", "Exception Python hot path : {sym} fn={fn_name} type={exc_type} msg={exc_msg}"),
    "FUNNEL_REJECT_CONTRACT_BUG":(LogLevel.MAJEUR,   "events", "Funnel reject API misuse : {sym} step={step} kwargs_overlap={overlap_keys}"),

    # Mismatch state.json vs broker (position fantome)
    "STATE_VS_BROKER_MISMATCH":  (LogLevel.CRITIQUE, "execution", "State vs broker mismatch : {sym} state={state_pos} broker={broker_pos} → cleanup attendu"),

    # ─── SETUP ENGINE V1 (Bot 2 Sim2 PAPER_TRADE actif, 2026-05-02) ─────
    # 11 setups validés empiriquement sur 1 an V4 enriched.
    # cf DOCS/EDGE_REPORT_BOT2_NQ.md + DOCS/EDGE_REPORT_BOT2_ES.md
    "SETUP_TRIGGERED":           (LogLevel.INFO,    "decisions", "Setup triggered : {sym} {side} setup={setup} bar_ts={bar_ts} price={price}"),
    "SETUP_CONFLUENCE":          (LogLevel.INFO,    "decisions", "Setup confluence : {sym} {side} setups={setups} bar_ts={bar_ts} price={price}"),
    "SETUP_CONFLICT_SKIP":       (LogLevel.ALERTE,  "decisions", "Setup conflict SKIP : {sym} long={setups_long} short={setups_short} bar_ts={bar_ts}"),
    "SETUP_TRADE_OPEN":          (LogLevel.INFO,    "execution", "Setup trade OPEN : {sym} {side} setup={setup} entry={entry_price} sl={sl_price} tp_cap={tp_cap_price}"),
    "SETUP_TRADE_CLOSE":         (LogLevel.INFO,    "execution", "Setup trade CLOSE : {sym} {side} setup={setup} reason={exit_reason} pnl_ticks={pnl_ticks} pnl_dollars={pnl_dollars} mfe={mfe_ticks}t mae={mae_ticks}t"),
    "TRAILING_TRIGGERED":        (LogLevel.INFO,    "execution", "Trailing trigger EXIT : {sym} {side} trailing_stop={trailing_stop} mfe={mfe_ticks}t pnl={pnl_ticks}t"),
    # FIX B-2 (02/05) : router success/exception cancel+replace SL DTC
    "TRAILING_BROKER_REPLACED_OK": (LogLevel.INFO,   "execution", "Trailing SL broker replaced OK : {sym} old_sl={old_sl} new_sl={new_sl} new_sl_cid={new_sl_cid}"),
    # Risk isolé par symbole (NQ et ES indépendants)
    "GATE_RISK_FLAT_BY_LOSSES":  (LogLevel.MAJEUR,  "decisions", "Risk flat by losses : {sym} n_losses={n_losses}/{max_losses} — flat reste session"),
    "GATE_RISK_KILL_SWITCH":     (LogLevel.CRITIQUE, "decisions", "Risk kill switch : {sym} daily_pnl={daily_pnl}$ <= {limit}$ — flat reste session"),
    "DEDUP_BAR_TS":              (LogLevel.INFO,    "decisions", "Dedup bar_ts : {sym} bar_ts={bar_ts} (deja evaluee, skip re-trigger)"),

    # ═══════════════════════════════════════════════════════════════════════
    # BOT 3 — Market Profile Trader (03/05/2026)
    # ═══════════════════════════════════════════════════════════════════════
    "BOT3_BOOT_READY":          (LogLevel.INFO,    "events",    "Bot3 boot pret : phase={phase} tier1={tier1} tier2={tier2} tier3={tier3} observe={observe}"),
    # 04/06/2026 (Jackson) - Blacklist backtest-validated MP levels boot log.
    # Emit 1x au boot du paper_v2 pour tracability config blacklist active/inactive.
    # Permet grep J+1 "BOT3_MP_BLACKLIST_LOADED" pour audit deploiement.
    # Q5 review code-reviewer 04/06 : emit log obligatoire (regle log-tracabilite 01/05).
    "BOT3_MP_BLACKLIST_LOADED": (LogLevel.MAJEUR,  "events",    "Bot3 MP blacklist chargee : enabled={enabled} levels={levels} n_levels={n_levels} pnl_evite_backtest_33j_usd={pnl_evite_usd}"),
    "BOT3_LEVEL_CONTACT":       (LogLevel.INFO,    "decisions", "Bot3 contact niveau : {sym} {level} dist={dist:.4f}% tier={tier}"),
    "BOT3_DECISION_GO":         (LogLevel.INFO,    "decisions", "Bot3 GO : {sym} {level} side={side} action={action} conf={conf} sl={sl}t"),
    "BOT3_DECISION_SKIP":       (LogLevel.INFO,    "decisions", "Bot3 SKIP : {sym} {level} reason={reason}"),
    "BOT3_VETO_ROLL_DAY":       (LogLevel.MAJEUR,  "decisions", "Bot3 veto ROLL_DAY : {sym} jour de roll, no trade"),
    "BOT3_VETO_NEWS":           (LogLevel.MAJEUR,  "decisions", "Bot3 veto NEWS : {sym} reason={reason} mins_since={mins_since}"),
    "BOT3_VETO_VOL_DEAD":       (LogLevel.ALERTE,  "decisions", "Bot3 veto VOLUME_MORT : {sym} rvol={rvol:.2f} < {limit}"),
    "BOT3_TIER3_MISS":          (LogLevel.INFO,    "decisions", "Bot3 Tier3 required_context miss : {sym} {level} {detail}"),
    "BOT3_TRADE_OPEN":          (LogLevel.INFO,    "trading",   "Bot3 trade ouvert : {sym} {level} {side} {action} qty={qty} @ {price} sl={sl}t conf={conf}"),
    "BOT3_TRADE_CLOSE":         (LogLevel.INFO,    "trading",   "Bot3 trade ferme : {sym} {level} reason={reason} pnl={pnl:.1f}t mfe={mfe:.0f}t mae={mae:.0f}t dur={dur}s"),
    "BOT3_TRAILING_ACTIVATED":  (LogLevel.INFO,    "execution", "Bot3 trailing actif : {sym} sl_old={sl_old} -> sl_new={sl_new}"),
    "BOT3_OBSERVE_RECORD":      (LogLevel.INFO,    "decisions", "Bot3 observe-only : {sym} {level} would_GO={would_go} side={side} conf={conf} (no trade)"),
    # --- Bot 3 GOLD (MGC) - 12/05/2026 ---
    "BOT3G_BOOT_READY":         (LogLevel.INFO,    "events",    "Bot3 Gold boot pret : phase={phase} observe_only={observe_only} tier2={tier2} hedge={hedge}"),
    "BOT3G_LEVEL_CONTACT":      (LogLevel.INFO,    "decisions", "Bot3G contact niveau : {level} tier={tier} dist={dist} prox={prox}"),
    "BOT3G_DECISION_GO":        (LogLevel.INFO,    "decisions", "Bot3G GO : {level} {side} scenario={scenario} conf={conf} sl={sl_ticks}t macro={macro}"),
    "BOT3G_DECISION_SKIP":      (LogLevel.INFO,    "decisions", "Bot3G SKIP : {level} reason={reason} macro={macro}"),
    "BOT3G_MACRO_OVERRIDE":     (LogLevel.MAJEUR,  "decisions", "Bot3G macro override : {level} side_propose={side} macro_bias={macro} -> action={action}"),
    "BOT3G_VETO_LONDON_FIX":    (LogLevel.MAJEUR,  "decisions", "Bot3G VETO London Fix : {level} window={window} ts={ts}"),
    "BOT3G_TRADE_OPEN":         (LogLevel.INFO,    "trading",   "Bot3G trade ouvert : MGC {level} {side} scenario={scenario} qty={qty} @ {price} sl={sl}t tp_cap={tp_cap}t"),
    "BOT3G_TRADE_CLOSE":        (LogLevel.INFO,    "trading",   "Bot3G trade ferme : MGC {level} reason={reason} pnl={pnl:.1f}t dur={dur}s"),
    "BOT3G_INTERMARKET":        (LogLevel.INFO,    "decisions", "Bot3G intermarket : DXY_corr={dxy} real_yield={ry} gs_z={gsz} oil_g={og} macro={macro}"),
    "BOT3G_HEDGE_TRIGGER":      (LogLevel.MAJEUR,  "decisions", "Bot3G HEDGE actif : Bot2 NQ={nq} ES={es} macro={macro} -> LONG MGC qty={qty}"),
    # ─── 🆕 09/05 (Bot 3 v2 — bucket SIDAK/COMBO_BOOSTED) ───
    "BOT3_FILTER_BYPASS_SIDAK_COMBO": (LogLevel.INFO, "decisions", "Bot3 v2 BYPASS filter regime (bucket validé cross-régime) : {sym} {level} bucket={bucket} side={sig_side} regime_favor={regime_favor} mode={regime_mode} conf={regime_confidence}"),
    "BOT3_SIDAK_SLTP_WALL_AWARE": (LogLevel.INFO, "execution", "Bot3 v2 SLTPEngine WALL-AWARE : {sym} {level} bucket={bucket} {side} sl={sl_ticks}t tp={tp_ticks}t sl_wall={sl_wall} tp_wall={tp_wall} rr={rr}"),
    "BOT3_SIDAK_SLTP_FALLBACK": (LogLevel.MAJEUR, "execution", "Bot3 v2 SLTPEngine REJECT → fallback standard : {sym} {level} bucket={bucket} {side} reject={reject_reason} fallback_sl={fallback_sl_ticks}t fallback_tp={fallback_tp_ticks}t"),
    "BOT3_COMBO_BOOSTED_FIRE":  (LogLevel.MAJEUR, "decisions", "Bot3 v2 COMBO_BOOSTED FIRE (priority 1 haute conviction) : {sym} {level} side={side} cols_touched={cols_touched} filter_passed={filter_passed}"),
    # FIX C-3 (review code-reviewer 03/05) : code dedie pour bug config niveau invalide
    "BOT3_LEVEL_DEF_INVALID":   (LogLevel.CRITIQUE, "decisions", "Bot3 level def invalide : {sym} {level} side_value={side_value} (config bug)"),
    # FIX M-2 (review code-reviewer 03/05) : trading window parse fail (fail-CLOSED)
    "BOT3_TRADING_WINDOW_PARSE_FAIL": (LogLevel.MAJEUR, "decisions", "Bot3 trading window parse fail : ts={ts} err={err} (fail-CLOSED, no trade)"),
    # FIX market-analyst Section 4 (03/05) : tracker inversions theoriques (BREAKOUTS off)
    "BOT3_ACCEPTANCE_DETECTED": (LogLevel.INFO,    "decisions", "Bot3 acceptance detected (theorique, BREAKOUTS off) : {sym} {level} would_invert {old_side}->{new_side} delta={delta} finish={finish}"),
    # FIX M-6 (review code-reviewer 03/05) : feature missing au boot (degraded mode)
    "BOT3_FEATURE_MISSING":     (LogLevel.MAJEUR,  "events",    "Bot3 feature missing : {feature} (impact={impact})"),
    # Skip OBSERVE_ONLY tier 99 (Section 6 market-analyst) — anti-trade automatique
    "BOT3_OBSERVE_LEVEL_LOGGED":(LogLevel.INFO,    "decisions", "Bot3 observe-only tier99 : {sym} {level} dist={dist:.4f}% (no decision_engine call)"),
    # BREAKOUT_RETEST state machine (Steidlmayer/Dalton) — Jackson Option B (03/05)
    "BOT3_BREAKOUT_PENDING":     (LogLevel.INFO,    "decisions", "Bot3 breakout PENDING acceptance : {sym} {level} side_break={side} (3 bars to confirm)"),
    "BOT3_BREAKOUT_ACCEPTED":    (LogLevel.INFO,    "decisions", "Bot3 breakout ACCEPTED : {sym} {level} side_break={side} confirms={confirms}/{required} (waiting retest)"),
    "BOT3_BREAKOUT_CRUSH_ABSORBED": (LogLevel.INFO, "decisions", "Bot3 breakout CRUSH_ABSORBED : {sym} {level} confirms={confirms}/{required} (Wyckoff spring filtre)"),
    "BOT3_BREAKOUT_RETEST_ENTRY":(LogLevel.INFO,    "trading",   "Bot3 BREAKOUT_RETEST ENTRY : {sym} {level} side={side} entry={entry_price} bars_touch_to_retest={n_bars}"),
    "BOT3_BREAKOUT_RETEST_TIMEOUT": (LogLevel.INFO, "decisions", "Bot3 breakout RETEST_TIMEOUT : {sym} {level} pas de retest dans {max_bars} bars"),
    # Bonus 2 (Jackson 03/05) : MQ stale veto
    "BOT3_VETO_MQ_STALE":        (LogLevel.MAJEUR,  "decisions", "Bot3 veto MQ STALE : {sym} {level} dist > 5% sur tous walls (ingestion failed?)"),
    # FIX round 5 (Jackson 03/05 soir)
    "BOT3_ECO_EXCEPTION":        (LogLevel.CRITIQUE, "errors",   "Bot3 eco_calendar exception : {err} {msg} (FAIL-CLOSED)"),
    "BOT3_CAP_TRADES_REACHED":   (LogLevel.MAJEUR,  "decisions", "Bot3 cap trades atteint : {sym} n_trades={n_trades}/{max} (data quality)"),
    "BOT3_CAP_LOSSES_REACHED":   (LogLevel.MAJEUR,  "decisions", "Bot3 cap losses atteint : {sym} n_losses={n_losses}/{max} (circuit breaker)"),

    # ============================================================
    # Phase 1.7b Bot 3 v2 (17/05/2026) — BLOCK + BOOST combos Session × Level
    # ============================================================
    # Source : audit Phase 1.0 post-enrichissement v4 (454 cols)
    # DSR Lopez Bonferroni n_trials=1064, walk-forward 12-fold, n>=100/combo
    # Reviews : ml-trainer GO + market-analyst GO + code-reviewer GO
    "BOT3_BLOCK_COMBO":          (LogLevel.MAJEUR,  "decisions", "Bot3 BLOCK combo : {sym} session={session} level={level} pf={pf} n={n}"),
    "BOT3_BOOST_APPLIED":        (LogLevel.INFO,    "decisions", "Bot3 BOOST applique : {sym} session={session} level={level} boost=+{boost} pf={pf} n={n}"),
    # Phase 1.7d (17/05) — Swing × Color confluence boost
    "BOT3_SWING_COLOR_BOOST":    (LogLevel.INFO,    "decisions", "Bot3 SWING_COLOR boost : {sym} level={level} bucket={bucket} boost=+{boost}"),
    # Audit log tracabilite Jackson 17/05 — 5 GAPS detectes + fixes
    # GAP 2 : funnel NEUTRAL 7 scenarios persiste pour audit "quelle feature bloque"
    "BOT3_NEUTRAL_FUNNEL":       (LogLevel.INFO,    "decisions", "Bot3 NEUTRAL funnel : {sym} level={level} reason={reason} matched={matched}"),
    # GAP 3 : PENDING_BREAKOUT register depuis bot3_mp_engine (avant acceptance state machine).
    # Code DEDIE (pas BOT3_BREAKOUT_PENDING qui est emis par _bot3_emit_breakout_events ligne 568).
    # Evite collision placeholders {side} vs {side_break}/{delta}/{finish}.
    "BOT3_BREAKOUT_REGISTER":    (LogLevel.INFO,    "decisions", "Bot3 BREAKOUT register : {sym} level={level} side_break={side_break} delta={delta} finish={finish}"),
    # GAP 5 : BAR OK heartbeat data path throttle 5min (tracking pipeline fraiche)
    "BOT3_BAR_OK":               (LogLevel.INFO,    "events",    "Bot3 BAR OK : {sym} bar_ts={bar_ts} age_sec={age_sec}"),
    # GAP 6 : SWING_COLOR distribution tracking (NEUTRE inclus) pour calibration
    "BOT3_SWING_COLOR_TRACKING": (LogLevel.INFO,    "decisions", "Bot3 SWING_COLOR distrib : {sym} level={level} bucket={bucket} side={side}"),
    # Audit dashboard 17/05 (Jackson Q1+Q2) — surveillance staleness + corrupt state
    # P5 : staleness state.json (emit lazy depuis dashboard backend si age > seuil)
    "BOT3_DASHBOARD_STATE_STALE": (LogLevel.MAJEUR, "events", "Bot3 state.json STALE : age={age_sec}s threshold={threshold}s (pipeline lag ou paper_trader freeze)"),
    # B4 : JSON state corrompu (fail-loud anti silent empty fallback)
    "BOT3_STATE_CORRUPT":        (LogLevel.CRITIQUE,"errors",   "Bot3 state.json CORRUPT : {state_file} err={err_type} msg={err_msg} (dashboard fallback empty)"),

    # ============================================================
    # V6 brain Sim2 (05/05) — Bot V6 enrichi Databento V4
    # ============================================================
    # FIX 19/05 PM (audit Bot 2 V6 agent) : reclassif categorie events -> decisions
    # car critique edge V6 perdu silencieusement quand V4 fallback DMP.
    # Avant : noyé dans events INFO (9080 BRAIN_V6_ACTIVE par jour, signal manqué).
    # Apres : decisions/ avec niveaux explicites (MAJEUR pour fallback, CRITIQUE
    # pour stale > seuil critique). Permet audit J+1 via grep `decisions/*paper_v6*`.
    "BRAIN_V6_ACTIVE":           (LogLevel.INFO,    "decisions", "Bot V6 brain actif : {sym} regime_mode={regime_mode} favor={regime_favor} bias_v6_score={bias_v6_score} dir={bias_v6_dir}"),
    "V6_V4_BAR_STALE":           (LogLevel.CRITIQUE, "decisions", "V6 bar V4 STALE : {sym} age={age_sec}s > {threshold}s (pipeline V4 retard) -> fallback DMP - edge V6 votes 11-16/blocs 7-16 INDISPONIBLE"),
    "V6_V4_FALLBACK_DMP":        (LogLevel.MAJEUR,  "decisions", "V6 fallback DMP : {sym} V4 indisponible source={fallback_source} reason={reason} - regime degrade (V4 features manquantes)"),
    "V6_CHASE_SKIPPED":          (LogLevel.INFO,    "decisions", "V6 CHASE skipped (R8 raffinement) : {sym} {direction} reason={reason}"),
    "V6_VOLUME_Z_TOO_LOW":       (LogLevel.MAJEUR,  "decisions", "V6 reject : {sym} {direction} volume_z={volume_z} < {threshold} (faux-breakout pepite #2)"),

    # ============================================================
    # Chantier 3 Live Enricher (13/05/2026 nuit) — Phase 3a
    # ============================================================
    "ENRICHER_BOOT":               (LogLevel.INFO,    "events", "Live Enricher boot : {sym} warmup_from_v4={warmup} state_loaded={loaded}"),
    "ENRICHER_SNAPSHOT_OK":        (LogLevel.INFO,    "events", "Enricher state snapshot OK : {sym} bars={bars} trades={trades} engines={engines}"),
    "ENRICHER_SNAPSHOT_FAIL":      (LogLevel.CRITIQUE,"events", "Enricher state snapshot FAIL : {sym} err={err} (crash recovery compromise)"),
    "ENRICHER_STATE_LOAD_FAIL":    (LogLevel.MAJEUR,  "events", "Enricher state load FAIL : {sym} err={err} -> cold start"),
    "ENRICHER_STATE_SCHEMA_MISMATCH": (LogLevel.MAJEUR, "events", "Enricher state SCHEMA mismatch : {sym} loaded={loaded} expected={expected} -> cold start"),
    "ENRICHER_BAR_PROCESSED":      (LogLevel.INFO,    "events", "Enricher bar processed : {sym} ts={ts} engines_time_ms={dt}"),
    "ENRICHER_CYCLE_SLOW":         (LogLevel.ALERTE,  "events", "Enricher cycle SLOW : {sym} dt={dt}ms > {limit}ms (engines a optimiser)"),
    "ENRICHER_INPUTS_INCOMPLETE":  (LogLevel.ALERTE,  "events", "Enricher inputs incomplete : {sym} missing={missing} (stream alive={alive})"),
    "ENRICHER_WRITE_FAIL":         (LogLevel.MAJEUR,  "events", "Enricher write FAIL : {sym} path={path} err={err}"),
    "ENRICHER_ENGINE_FAIL":        (LogLevel.MAJEUR,  "events", "Enricher engine chain fail : {sym} engine={engine} failed_lot={failed_lot} err_type={err_type} err={err}"),
    "ENRICHER_PARTNER_STALE":      (LogLevel.ALERTE,  "events", "Enricher partner bar stale/future : {sym} partner={partner} reason={reason} delta_ns={delta_ns} (intermarket features=NaN)"),
    "GAME_CHANGERS_OPEN_TYPE_UNKNOWN": (LogLevel.MAJEUR, "events", "Game changers OPEN_TYPE=UNKNOWN : {sym} date_et={date_et} mins_et={mins_et} missing_inputs={missing_inputs} (warmup cold start OU bug pipeline upstream - frequence elevee = bug)"),

    # ============================================================
    # R2 Fix Pass 4 (15/05/2026) — seed warmup J-1 cold start
    # ============================================================
    "ENRICHER_WARMUP_OK":          (LogLevel.INFO,    "events", "Enricher warmup V4 OK : {sym} n_bars={n_bars} path={path}"),
    "ENRICHER_WARMUP_FAIL":        (LogLevel.MAJEUR,  "events", "Enricher warmup V4 FAIL : {sym} err={err} -> cold start vide (anti-pattern V1 silent log emitted)"),
    "ENRICHER_SEED_OPEN_CASH_FROM_V4": (LogLevel.INFO, "events", "Enricher seed OpenCashPrice1030 depuis V4 : {sym} date={date} open_cash={open_cash} price_1030={price_1030}"),
    "ENRICHER_SEED_IMPORT_FAIL":   (LogLevel.MAJEUR,  "events", "Enricher seed phase_b_helpers import FAIL : {sym} (warmup partiel, classify_open_type peut UNKNOWN J0)"),
    "ENRICHER_SEED_SESSIONS_FROM_V4": (LogLevel.INFO, "events", "Enricher seed SessionsSwingsSimple depuis V4 : {sym} sdt={sdt} n_values={n_values} keys={keys}"),
    "ENRICHER_WRITE_DEDUP_SKIP":   (LogLevel.ALERTE,  "events", "Enricher write SKIP doublon ts_event_ns : {sym} path={path} ts_ns={ts_ns} (race restart-service ou Databento re-emit)"),
    "ENRICHER_SEED_SWINGS_LAG_FROM_V4": (LogLevel.INFO, "events", "Enricher seed SessionsSwingsLag depuis V4 : {sym} n_bars={n_bars} n_pivots={n_pivots} (P1.2 fix init swing tracker cold start)"),
    "ENRICHER_SEED_SWINGS_LAG_FAIL": (LogLevel.ALERTE, "events", "Enricher seed SessionsSwingsLag FAIL : {sym} reason={reason} (P1.2 - dist_swing_* sera null pendant 10-21 min jusqu'a detection live)"),
    "ENRICHER_SEED_VP_FROM_V4": (LogLevel.INFO, "events", "Enricher seed VolumeProfile (prev_*/pdh/pdl) depuis V4 : {sym} n_values={n_values} keys={keys} (P2.1 fix prev_* null cold start)"),
    # ============================================================
    # Phase 3c-A (18/05/2026 03:00 Paris nuit) — 17 features manquantes
    # ============================================================
    "PHASE_3C_A_FAIL":             (LogLevel.MAJEUR,  "events", "Phase 3c-A enrichment crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_A_REGIME_FAIL":      (LogLevel.ALERTE,  "events", "Phase 3c-A regime compute crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_B_FAIL":             (LogLevel.MAJEUR,  "events", "Phase 3c-B wire streaming crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_B_EDGE_FAIL":        (LogLevel.ALERTE,  "events", "Phase 3c-B edge_zones_streaming crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_B_COLOR_FAIL":       (LogLevel.ALERTE,  "events", "Phase 3c-B color_streaming crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_C_FAIL":             (LogLevel.MAJEUR,  "events", "Phase 3c-C rolling streaming crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_C_ATR_Z_FAIL":       (LogLevel.ALERTE,  "events", "Phase 3c-C atr_regime_zscore_60d crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_C_NPOC_FAIL":        (LogLevel.ALERTE,  "events", "Phase 3c-C naked_poc tracker crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_C_ROLL_FAIL":        (LogLevel.ALERTE,  "events", "Phase 3c-C roll detection crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_C_FFD_FAIL":         (LogLevel.ALERTE,  "events", "Phase 3c-C cvd_5d_ffd crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_C_VA_FAIL":          (LogLevel.ALERTE,  "events", "Phase 3c-C cur_va_* read crash : sym={sym} exc_type={exc_type} msg={exc_msg}"),
    "PHASE_3C_C_ATR_STALE":        (LogLevel.MAJEUR,  "events", "Phase 3c-C atr feed STALE : sym={sym} n_bars_consec_none={n_bars} (anti-pattern 11 V1 - atr_regime_zscore_60d reste None silencieux)"),
    "PHASE_3C_C_CVD_STALE":        (LogLevel.MAJEUR,  "events", "Phase 3c-C cvd_day feed STALE : sym={sym} n_bars_consec_none={n_bars} (anti-pattern 11 V1 - cvd_5d_rolling_ffd reste None silencieux)"),
    "PHASE_3C_C_NPOC_SESS_SKIP":   (LogLevel.INFO,    "events", "Phase 3c-C naked_poc skip push history : sym={sym} old_sess={old_sess} new_sess={new_sess} reason={reason} (boot mi-session ou prev_vpoc None - feature reste None pendant 7j)"),
    "ENRICHER_SEED_VP_FAIL": (LogLevel.ALERTE, "events", "Enricher seed VolumeProfile FAIL : {sym} reason={reason} (P2.1 - prev_*/pdh/pdl restera null jusqu'a session change)"),
    "ENRICHER_DATA_QUALITY_FLAG_SET": (LogLevel.ALERTE, "decisions", "Enricher data_quality_flag SET : {sym} flag={flag} n_bars={n_bars} sid={sid} (bit0=warmup bit1=sentinel999 bit2=sd_collapse bit3=swing_reset bit4=session_corrupt bit5=open_approximate bit6=ib_missing - ETL/ML drop si bit relevant)"),
    "ENRICHER_SESSIONS_OPEN_APPROXIMATE": (LogLevel.ALERTE, "decisions", "Enricher session open APPROXIMATE : {sym} session={session} mins_et={mins_et} start_exact={start_exact} (live boot mid-session, parite batch cassee, V4 batch ne refletera pas cet open)"),
    "ENRICHER_SEED_IB_FROM_V4": (LogLevel.INFO, "events", "Enricher seed IB (ib_high/ib_low) depuis V4 : {sym} sdt={sdt} ib_high={ib_high} ib_low={ib_low} (BUG #2 fix - cold/HOT restart > 10:30 ET)"),
    "ENRICHER_SEED_IB_FAIL": (LogLevel.ALERTE, "events", "Enricher seed IB FAIL : {sym} reason={reason} (BUG #2 - ib_high/ib_low restera NaN si live down 09:30-10:30 ET aujourd'hui)"),

    # ════════════════════════════════════════════════════════════════════════
    # Bot 3 v2 Narrative Layer (Phase 1 TRACKING ONLY, 18/05/2026)
    # ════════════════════════════════════════════════════════════════════════
    # Cf DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md
    # Cf DOCS/specs/2026-05-18-bot3v2-phase1-nsm-spec.md
    # Cf DOCS/specs/2026-05-18-bot3v2-phase1-story-trackers-spec.md

    # NSM (NarrativeStateMachine) - 8 codes
    "BOT3_NSM_STATE_TRANSITION":  (LogLevel.MAJEUR,   "decisions", "NSM transition : {sym} {from_state} -> {to_state} bias={bias_dir} conf={confidence:.2f} bar={bar_ts}"),
    "BOT3_NSM_STATE_OBSERVE":     (LogLevel.INFO,     "decisions", "NSM observe : {sym} state={state} bar_idx={bar_idx} bars_in_state={bars_in_state}"),
    "BOT3_NSM_INVALIDATED":       (LogLevel.CRITIQUE, "events",    "NSM scenario invalidated : {sym} from={from_state} trigger={trigger} bar={bar_ts}"),
    "BOT3_NSM_FLICKER_GUARD":     (LogLevel.ALERTE,   "decisions", "NSM flicker guard : {sym} blocked transition n_transitions_today={n}"),
    "BOT3_NSM_PERSIST_OK":        (LogLevel.INFO,     "events",    "NSM persist OK : symbols={symbols} n_events_flushed={n_events}"),
    "BOT3_NSM_PERSIST_FAIL":      (LogLevel.MAJEUR,   "events",    "NSM persist FAIL : err={err}"),
    "BOT3_NSM_PERSIST_RECOVERED": (LogLevel.ALERTE,   "events",    "NSM recovered fresh state apres corruption pickle : {sym} reason={reason}"),
    "BOT3_NSM_SESSION_RESET":     (LogLevel.INFO,     "events",    "NSM session reset : {sym} new_sdt={new_sdt} n_transitions_yesterday={n}"),
    "BOT3_NSM_ATR_FALLBACK_DAILY": (LogLevel.MAJEUR,  "decisions", "NSM atr_intraday absent : {sym} fallback atr daily ({atr_daily:.2f}) - seuils T28/T29/T30/T31 INATTEIGNABLES sur 1-min. Fix : passer atr_14m ou atr_intraday dans bar dict (cf incident 2026-05-18 22:00)."),
    "BOT3_NSM_TRANSITION_EXCEPTION": (LogLevel.MAJEUR, "decisions", "NSM transition exception : {sym} err={err} msg={msg} consec={consec} (circuit breaker trip a 10)"),
    "BOT3_NSM_TRANSITION_OK":      (LogLevel.INFO,   "decisions", "NSM heartbeat : {sym} count_since_boot={count_since_boot} (V2 actif et OK)"),
    "BOT3_NSM_CIRCUIT_BREAKER_TRIPPED": (LogLevel.CRITIQUE, "events", "NSM circuit breaker TRIPPED : {sym} consec={consec} msg={msg}"),
    "BOT3_V2_FALLBACK_V1_NEUTRAL": (LogLevel.INFO,   "decisions", "V2 fallback V1 NEUTRAL : {sym} level={level} (NEUTRAL non gere par V2 narrative, V1 7 scenarios applique)"),
    "BOT3_V2_TRADE_CONSTRUCTION_FAILED": (LogLevel.MAJEUR, "decisions", "V2 trade construction failed : {sym} level={level} scenario={scenario} err={err}"),
    "BOT3_V2_SHADOW_SIGNAL":       (LogLevel.INFO,   "decisions", "V2 shadow signal (tracking_only) : {sym} level={level} scenario={scenario} side={side} conf={confidence} state={narrative_state} (V1 reste decideur)"),
    "BOT3_V2_ADVANCE_EXCEPTION":   (LogLevel.MAJEUR, "decisions", "V2 advance pending exception : {sym} err={err} msg={msg} (NSM breaker NON impacte, advance separe)"),

    # StoryTrackers - 3 codes
    "BOT3_STORY_BOS_DETECTED":       (LogLevel.MAJEUR, "events",    "Bot3 STORY BOS detected : {sym} dir={bos_dir} price={bos_price} bar_idx={bar_idx} prev_close={prev_close} swing_ref={swing_ref}"),
    "BOT3_STORY_TREND_CONFIRMED":    (LogLevel.MAJEUR, "decisions", "Bot3 STORY trend confirmed : {sym} dir={trend_dir} hh={hh} ll={ll} slope60={slope60:.4f} bar_idx={bar_idx}"),
    "BOT3_STORY_REVERSAL_CANDIDATE": (LogLevel.ALERTE, "events",    "Bot3 STORY reversal candidate : {sym} slope60_prev={slope60_prev:.4f} slope60={slope60:.4f} hh5={hh5} ll5={ll5}"),

    # PlotTwistDetectors Phase 2 - 4 codes
    "BOT3_PLOT_TWIST_STRUCTURE_BREAK": (LogLevel.MAJEUR, "events",    "Bot3 PLOT TWIST structure break : {sym} dir={direction} close={close} swing_ref={swing_ref} bar_ts={bar_ts}"),
    "BOT3_PLOT_TWIST_VOLUME_ANOMALY":  (LogLevel.MAJEUR, "events",    "Bot3 PLOT TWIST volume anomaly : {sym} vol_z={vol_z:.2f} bar_ts={bar_ts}"),
    "BOT3_PLOT_TWIST_DIVERGENCE":      (LogLevel.MAJEUR, "events",    "Bot3 PLOT TWIST price/CVD divergence : {sym} dir={direction} price_delta={price_delta} cvd_delta={cvd_delta} bar_ts={bar_ts}"),
    "BOT3_PLOT_TWIST_CAPITULATION":    (LogLevel.CRITIQUE,"events",   "Bot3 PLOT TWIST capitulation : {sym} dir={direction} n_climax_bars={n_climax} bar_ts={bar_ts}"),

    # ScenarioValidator Phase 2 - 2 codes
    "BOT3_SCENARIO_INVALIDATED":      (LogLevel.CRITIQUE,"events",   "Bot3 SCENARIO invalidated : {sym} state={state} reason={reason} bars_in_state={bars_in_state}"),
    "BOT3_SCENARIO_TIME_DECAY":       (LogLevel.ALERTE,  "events",   "Bot3 SCENARIO time decay : {sym} state={state} bars_in_state={bars_in_state} threshold={threshold}"),

    # DirectionResolver Phase 3 - 6 codes
    "BOT3_RESOLVER_DIRECTION_RESOLVED":     (LogLevel.MAJEUR,  "decisions", "Bot3 RESOLVER direction : {sym} side={side} conf={confidence:.2f} scenario={scenario_id} state={state}"),
    # FIX 19/05 PM (investigation V2 SHADOW ZERO) : diagnostic init state V2
    "BOT3_ENGINE_INIT_V2_STATE":            (LogLevel.MAJEUR,  "events", "Bot3Engine init V2 narrative : nsm_set={nsm_set} resolver_set={resolver_set} use_narrative={use_narrative} v2_available={v2_available} tracking_only={tracking_only}"),
    "BOT3_NSM_STATE_CHANGE":                (LogLevel.INFO,    "decisions", "NSM state change : {sym} {prev_state} -> {cur_state} (transition_count={count})"),
    "BOT3_RESOLVER_NO_TRADE":               (LogLevel.INFO,    "decisions", "Bot3 RESOLVER no_trade : {sym} reason={reason} state={state}"),
    "BOT3_RESOLVER_PENDING_ENTRY":          (LogLevel.INFO,    "decisions", "Bot3 RESOLVER pending entry : {sym} scenario={scenario_id} pattern={pattern} bars_to_wait={bars_to_wait}"),
    "BOT3_RESOLVER_CONFIRMATION_OK":        (LogLevel.MAJEUR,  "decisions", "Bot3 RESOLVER confirmation OK : {sym} scenario={scenario_id} side={side} bars_waited={bars_waited}"),
    "BOT3_RESOLVER_CONFIRMATION_INVALIDATED":(LogLevel.MAJEUR, "decisions", "Bot3 RESOLVER confirmation invalidated : {sym} scenario={scenario_id} reason={reason}"),
    "BOT3_RESOLVER_CONFIRMATION_TIMEOUT":   (LogLevel.INFO,    "decisions", "Bot3 RESOLVER confirmation timeout : {sym} scenario={scenario_id} max_bars={max_bars}"),

    # ShadowMode Phase 3 - 1 code
    "BOT3_SHADOW_DIVERGENCE":               (LogLevel.MAJEUR,  "decisions", "Bot3 SHADOW divergence v1 vs v2 : {sym} legacy={legacy_side} narrative={narrative_side} scenario={scenario_id}"),

    # ════════════════════════════════════════════════════════════════════════
    # BOT 4 MIA Trader (Sim4 paper deploy 27/05/2026)
    # Phase 7.1 SAFE COLLECT 1 micro -> 7.2 PAPER AGGRESSIVE 3 micros.
    # Architecture M1->M2->M4->M3->M5->M3.5 (cf MASTER_PLAN J10/J11).
    # 50 codes V2 (apres review : doublons telemetry M6 Pydantic supprimes).
    # ════════════════════════════════════════════════════════════════════════

    # Lifecycle Bot 4 (10 codes)
    "BOT4_BOOT_START":              (LogLevel.INFO,     "events", "Bot4 boot start : symbols={symbols} dry_run={dry_run} trade_account={trade_account}"),
    "BOT4_BOOT_READY":              (LogLevel.INFO,     "events", "Bot4 boot ready : dtc_state={dtc_state} reader_state={reader_state} risk_mode={risk_mode} phase={phase}"),
    "BOT4_BOOT_FAIL":               (LogLevel.CRITIQUE, "events", "Bot4 boot FAIL : reason={reason} dtc_connected={dtc_connected}"),
    "BOT4_BOOT_LOCK_RECOVERY":      (LogLevel.ALERTE,   "events", "Bot4 lock file stale parse + replace : path={lock_path} stale_pid={stale_pid}"),
    "BOT4_CONFIG_LOADED":           (LogLevel.INFO,     "events", "Bot4 config loaded : risk_mode={risk_mode} sizing={sizing_mode} tr40={tr40_enabled} mfe_tp={mfe_tp_enabled} dry_run={dry_run}"),
    "BOT4_LOCK_FAIL":               (LogLevel.CRITIQUE, "events", "Bot4 lock file present, double-instance bloquee : path={lock_path} content={content}"),
    "BOT4_SHUTDOWN":                (LogLevel.MAJEUR,   "events", "Bot4 shutdown : reason={reason} positions_open={positions_open}"),
    "BOT4_HEARTBEAT":               (LogLevel.INFO,     "events", "Bot4 heartbeat : uptime_min={uptime_min} bars_processed={bars_processed} trades_today={trades_today} positions={positions}"),
    "BOT4_LOOP_EXCEPTION":          (LogLevel.CRITIQUE, "events", "Bot4 loop exception : symbol={symbol} exc_type={exc_type} exc_msg={exc_msg}"),
    "BOT4_KILL_SWITCH_DETECTED":    (LogLevel.MAJEUR,   "events", "Bot4 kill switch detected STOP.flag : path={kill_switch_path}"),

    # Reader M1 (6 codes - degraded modes only, ReaderEvent Pydantic capture le reste)
    "BOT4_READER_NO_BAR":           (LogLevel.ALERTE,   "events", "Bot4 reader no bar : sym={sym} live_root={live_root} reason={reason}"),
    "BOT4_READER_MENTHORQ_STALE":   (LogLevel.ALERTE,   "events", "Bot4 reader MenthorQ stale : sym={sym} staleness_h={staleness_h} threshold_h=48"),
    "BOT4_READER_MENTHORQ_ABSENT":  (LogLevel.ALERTE,   "events", "Bot4 reader MenthorQ absent : sym={sym} root={menthorq_root}"),
    "BOT4_READER_MENTHORQ_SCHEMA_MISMATCH": (LogLevel.CRITIQUE, "events", "Bot4 reader MenthorQ schema mismatch reason={reason} : sym={sym} path={path} payload_top_keys={top_keys} symbol_present={sym_present} structured_present={structured_present} key_levels_extracted={kl_extracted}"),
    "BOT4_READER_TS_FALLBACK":      (LogLevel.ALERTE,   "events", "Bot4 reader ts_event_ns fallback walltime : sym={sym} ts_raw={ts_raw}"),
    "BOT4_READER_DEGRADED":         (LogLevel.ALERTE,   "events", "Bot4 reader data degraded : sym={sym} reasons={reasons} menthorq_fresh={menthorq_fresh}"),
    "BOT4_REGIME_INSUFFICIENT_FEATURES": (LogLevel.ALERTE, "events", "Bot4 L1 regime_v2 votes insuffisants : sym={sym} votes_total={votes_total} (threshold=4) -> regime conf peu fiable (typique hors-RTH features MP NaN)"),
    "BOT4_REGIME_V1_V2_DIVERGENT":      (LogLevel.MAJEUR, "decisions", "Bot4 regime divergence v1 vs v2 : sym={sym} v1_favor={v1_favor} v2_favor={v2_favor} v1_conf={v1_conf} v2_conf={v2_conf} v1_actionable={v1_actionable} v2_actionable={v2_actionable} (audit fix 04/06)"),
    "BOT4_BAR_DECISION":                (LogLevel.INFO, "decisions", "Bot4 bar decision : sym={sym} action={action} dir={direction} score={score_total} thr={threshold_used} conv={conviction} binding={binding_gate} fresh={freshness_label}"),

    # Risk M4 (3 codes - transitions only, RiskEvent Pydantic capture blocking_gate)
    "BOT4_RISK_TRADE_OPEN":         (LogLevel.INFO,     "risk", "Bot4 risk trade_open : sym={sym} side={side} signal_id={signal_id} entry={entry_price} sl={sl_price} tp={tp_price} sl_ticks={sl_ticks} qty={qty} positions_open_after={positions_open}"),
    "BOT4_RISK_TRADE_CLOSE":        (LogLevel.INFO,     "risk", "Bot4 risk trade_close : sym={sym} signal_id={signal_id} pnl_usd={pnl_usd} exit_reason={exit_reason} consec_sl={consec_sl}"),
    "BOT4_RISK_DAILY_RESET":        (LogLevel.INFO,     "risk", "Bot4 risk daily reset : sym={sym} new_session={new_session_date} pnl_prev={pnl_prev}"),

    # SLTP M3 (1 code - exception only, SLTPEvent Pydantic capture reject_reason)
    "BOT4_SLTP_ADAPTER_ERROR":      (LogLevel.CRITIQUE, "events", "Bot4 SLTP adapter ERROR : sym={sym} dir={direction} err={err}"),

    # Execution M5 (14 codes - IO transitions DTC)
    "BOT4_EXEC_BRACKET_SENT":       (LogLevel.INFO,     "execution", "Bot4 exec bracket sent : sym={sym} side={side} qty={qty} parent={parent_id} tp_cid={tp_cid} sl_cid={sl_cid} signal_ref={signal_ref_price}"),
    "BOT4_EXEC_BRACKET_FAIL":       (LogLevel.MAJEUR,   "execution", "Bot4 exec bracket FAIL : sym={sym} side={side} qty={qty} reject_reason={reject_reason}"),
    "BOT4_EXEC_FILL_PARENT":        (LogLevel.INFO,     "execution", "Bot4 exec FILL parent : sym={sym} cid={cid} fill_price={fill_price} signal_ref={signal_ref_price} slip_ticks={slip_ticks}"),
    "BOT4_EXEC_FILL_TP":            (LogLevel.INFO,     "execution", "Bot4 exec FILL TP : sym={sym} cid={cid} fill_price={fill_price} pnl_ticks={pnl_ticks}"),
    "BOT4_EXEC_FILL_SL":            (LogLevel.INFO,     "execution", "Bot4 exec FILL SL : sym={sym} cid={cid} fill_price={fill_price} pnl_ticks={pnl_ticks}"),
    "BOT4_EXEC_FILL_INVALID":       (LogLevel.CRITIQUE, "execution", "Bot4 exec FILL INVALID (ghost trade) : sym={sym} cid={cid} status={order_status} fill_price={fill_price} qty={filled_qty}"),
    "BOT4_FILL_UNKNOWN_CID":        (LogLevel.INFO,     "execution", "Bot4 fill CID inconnu (recovery post-restart, autre bot, ou re-livraison) : cid={cid} fill_price={fill_price} is_tp={is_tp} is_sl={is_sl}"),

    # State persistance open_positions (fix BUG#1 28/05 restart-safe)
    "BOT4_OPEN_POSITIONS_RELOADED": (LogLevel.MAJEUR,   "events", "Bot4 open_positions reloaded au boot : n_loaded={n_loaded} age_sec={age_sec}"),
    "BOT4_RELOAD_SKIP_STALE":       (LogLevel.ALERTE,   "events", "Bot4 open_positions reload skip (fichier > 24h) : age_sec={age_sec} path={path}"),
    "BOT4_RELOAD_ITEM_FAIL":        (LogLevel.ALERTE,   "events", "Bot4 open_positions reload item fail : sid={sid} err={err}"),
    "BOT4_RELOAD_FAIL":             (LogLevel.CRITIQUE, "events", "Bot4 open_positions reload FAIL : path={path} err={err}"),
    "BOT4_PERSIST_FAIL":            (LogLevel.ALERTE,   "events", "Bot4 open_positions persist FAIL : err={err} n_positions={n_positions}"),
    "BOT4_OPEN_POSITIONS_PERSISTED": (LogLevel.INFO,    "events", "Bot4 open_positions persisted : n_positions={n_positions} path={path}"),
    # Lock + preflight env vars (fix BUG#7 28/05 boot 58% echec)
    "BOT4_LOCK_ORPHAN_CLEANED":     (LogLevel.ALERTE,   "events", "Bot4 lock orphan auto-cleaned : pid={orphan_pid} dead, path={lock_path}"),
    "BOT4_BOOT_FAIL_PREFLIGHT_ENV": (LogLevel.CRITIQUE, "events", "Bot4 boot preflight env vars manquantes : missing={missing}"),
    "BOT4_BOOT_FAIL_PREFLIGHT_DATA_ROOT": (LogLevel.CRITIQUE, "events", "Bot4 boot preflight data_root absent : path={data_root}"),
    "BOT4_BOOT_FAIL_PREFLIGHT_LOG_DIR": (LogLevel.CRITIQUE, "events", "Bot4 boot preflight log_dir parent absent : parent={log_dir_parent}"),
    "BOT4_EXEC_REPRICE_DONE":       (LogLevel.MAJEUR,   "execution", "Bot4 exec REPRICE : sym={sym} parent={parent_id} slip={slip_ticks} signal_ref={signal_ref} fill={fill_price}"),
    "BOT4_EXEC_OCO_REGISTERED":     (LogLevel.INFO,     "execution", "Bot4 exec OCO registered : sym={sym} tp_cid={tp_cid} sl_cid={sl_cid}"),
    "BOT4_EXEC_CANCEL_SENT":        (LogLevel.INFO,     "execution", "Bot4 exec cancel sent : sym={sym} cid={cid} ta={trade_account}"),
    "BOT4_EXEC_CANCEL_FAIL":        (LogLevel.ALERTE,   "execution", "Bot4 exec cancel FAIL : sym={sym} cid={cid} reason={reason}"),
    "BOT4_EXEC_PRICE_UNAVAILABLE":  (LogLevel.ALERTE,   "execution", "Bot4 exec price unavailable : sym={sym} contract={contract} consec={consec_failures} exc={exc}"),
    "BOT4_EXEC_MARKET_DATA_DOWN":   (LogLevel.CRITIQUE, "events", "Bot4 exec market data DOWN : symbol={contract} consec={consec_failures} threshold={threshold} positions_unmonitored={positions_unmonitored}"),
    "BOT4_EXEC_DTC_DISCONNECT":     (LogLevel.MAJEUR,   "events", "Bot4 exec DTC disconnect : positions_open={positions_open} action=skip_until_reconnect"),
    "BOT4_EXEC_DTC_RECONNECT":      (LogLevel.MAJEUR,   "events", "Bot4 exec DTC reconnect : attempts={attempts} positions_open={positions_open}"),

    # Flatten anti-orphelin 9 etapes (10 codes)
    "BOT4_FLATTEN_START":           (LogLevel.INFO,     "execution", "Bot4 flatten start : sym={sym} dir={direction} signal_id={signal_id} qty={n_contracts} tp_cid={tp_cid} sl_cid={sl_cid}"),
    "BOT4_FLATTEN_STEP_OK":         (LogLevel.INFO,     "execution", "Bot4 flatten step OK : sym={sym} step={step_id} duration_ms={duration_ms}"),
    "BOT4_FLATTEN_STEP_FAIL_CLEANUP":(LogLevel.ALERTE,  "execution", "Bot4 flatten step FAIL cleanup tolerable : sym={sym} step={step_id} error={error}"),
    "BOT4_FLATTEN_STEP_FAIL_CRITICAL":(LogLevel.MAJEUR, "execution", "Bot4 flatten step FAIL CRITICAL : sym={sym} step={step_id} error={error}"),
    "BOT4_FLATTEN_MARKET_CLOSE_SENT":(LogLevel.MAJEUR,  "execution", "Bot4 flatten MARKET CLOSE sent : sym={sym} side={close_side} qty={close_qty} cid={close_cid}"),
    "BOT4_FLATTEN_VERIFY_CLEAN":    (LogLevel.INFO,     "execution", "Bot4 flatten verified clean : sym={sym} signal_id={signal_id}"),
    "BOT4_FLATTEN_ORPHAN_DETECTED": (LogLevel.CRITIQUE, "execution", "Bot4 flatten ORPHAN detected post-cleanup : sym={sym} signal_id={signal_id} qty_residual={qty_residual} working_orders={working_orders}"),
    "BOT4_FLATTEN_DTC_FREEZE":      (LogLevel.CRITIQUE, "execution", "Bot4 flatten DTC freeze get_position_qty : sym={sym} signal_id={signal_id} ta={trade_account}"),
    "BOT4_FLATTEN_COMPLETE":        (LogLevel.MAJEUR,   "execution", "Bot4 flatten complete : sym={sym} signal_id={signal_id} duration_total_ms={duration_total_ms} critical_failed={critical_failed} cleanup_failed={cleanup_failed}"),
    "BOT4_FLATTEN_INCOMPLETE":      (LogLevel.CRITIQUE, "execution", "Bot4 flatten INCOMPLETE : sym={sym} signal_id={signal_id} final_qty_broker={final_qty_broker} VERIFIER MANUELLEMENT BROKER"),

    # PositionMonitor M3.5 (7 codes)
    "BOT4_MONITOR_TR40_ARMED":      (LogLevel.INFO,     "execution", "Bot4 monitor TR40 armed : sym={sym} signal_id={signal_id} mfe={mfe} arming_thr={arming_thr} sl_init={sl_init}"),
    "BOT4_MONITOR_TR40_UPDATED":    (LogLevel.INFO,     "execution", "Bot4 monitor TR40 SL update : sym={sym} signal_id={signal_id} old_sl={old_sl} new_sl={new_sl} mfe={mfe} count={count}"),
    "BOT4_MONITOR_TR40_NOT_ALIGNED":(LogLevel.MAJEUR,   "execution", "Bot4 monitor TR40 tick misalign : sym={sym} signal_id={signal_id} sl_raw={sl_raw} sl_aligned={sl_aligned} delta_ticks={delta_ticks}"),
    "BOT4_MONITOR_TRAILING_TP_ARMED":(LogLevel.INFO,    "execution", "Bot4 monitor trailing TP armed : sym={sym} signal_id={signal_id} mfe={mfe} threshold={threshold}"),
    "BOT4_MONITOR_TRAILING_TP_TRIGGERED":(LogLevel.MAJEUR,"execution", "Bot4 monitor trailing TP TRIGGERED : sym={sym} signal_id={signal_id} mfe_peak={mfe} excursion={excursion} drawback={drawback} captured_pct={captured_pct}"),
    "BOT4_MONITOR_OCO_ORPHAN_DETECTED":(LogLevel.CRITIQUE,"execution", "Bot4 monitor OCO orphan detected : sym={sym} signal_id={signal_id} dir={direction} sequence_completed={completed} orphan_post={orphan_post} VERIFIER BROKER"),
    "BOT4_MONITOR_POSITION_EXPIRED":(LogLevel.ALERTE,   "execution", "Bot4 monitor position expired (no TP/SL within max_hold) : sym={sym} signal_id={signal_id} bars_held={bars_held}"),
}


def resolve(code: str):
    """Retourne (level, category, template) pour un code. KeyError si inconnu."""
    if code not in LOG_CODES:
        raise KeyError(f"Code de log inconnu : {code}. Ajouter a CORE/log_catalog.py")
    level, category, template = LOG_CODES[code]
    return level, category, template


def format_message(code: str, **ctx) -> str:
    """Formate le message fr a partir du code + contexte.

    Fix P0#1 code-reviewer 23/05 : catch ValueError + TypeError du format spec.
    Sans ce fix, template `{x:.5f}` avec ctx x=None crashait l'emission de log
    (templates BN_V4_GATE_TREND/VOLUME/TRADE_CLOSE concernes).
    Maintenant : fallback gracieux avec marqueur explicite [FMT_ERR].
    """
    _, _, template = resolve(code)
    try:
        return template.format(**ctx)
    except KeyError as e:
        return f"{template} [MISSING_CTX: {e}]"
    except (ValueError, TypeError) as e:
        # Format spec error (e.g. {x:.5f} avec x=None) -> fallback safe.
        # Re-essai en remplacant None par 'None' string (degraded).
        safe_ctx = {k: ("None" if v is None else v) for k, v in ctx.items()}
        try:
            return template.format(**safe_ctx) + f" [FMT_DEGRADED]"
        except Exception:
            return f"{template} [FMT_ERR: {e} ctx={list(ctx.keys())}]"


def get_action(level: LogLevel) -> dict:
    """Retourne les actions auto associees au niveau (discord, mention, etc.)."""
    return LEVEL_ACTIONS[level]


CATEGORIES = ("trading", "execution", "risk", "ml", "data", "errors", "events", "decisions")
