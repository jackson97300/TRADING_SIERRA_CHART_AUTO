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
    "CIRCUIT_BREAKER_TRIP":    (LogLevel.MAJEUR,   "risk", "Circuit breaker {sym} : {consec_losses} pertes consecutives, pause {pause_min} min"),
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
    "BOT_KILL_SWITCH_ACTIVATED": (LogLevel.MAJEUR, "events", "STOP.flag detecte : flatten + pause (positions closed: {n_closed})"),
    "BOT_KILL_SWITCH_RELEASED": (LogLevel.INFO,    "events", "STOP.flag supprime : reprise trading"),
    "GATE_MTF_BULL_DESERT":     (LogLevel.INFO,    "decisions", "SHORT reject : mtf_bulls<=1 ({mtf_bulls}/4) edge negatif prouve"),
    # --- Paper trader gates funnel (enrichissement log V2 - 25/04) ---
    "GATE_CONSEIL_ATTENDRE":    (LogLevel.INFO,    "decisions", "Conseil ATTENDRE : {sym} bull={bull_pts} bear={bear_pts} bias={bias} mtf={mtf_bulls}/{mtf_bears} rangepos={range_pos}%"),
    "GATE_CONSEIL_CONFLIT":     (LogLevel.INFO,    "decisions", "Conseil CONFLIT : {sym} bull={bull_pts} bear={bear_pts}"),
    "GATE_SELL_AUTO_DISABLED":  (LogLevel.ALERTE,  "decisions", "SELL auto-disabled : {sym} reason={reason}"),
    "GATE_FRESHNESS_EXPIRED":   (LogLevel.INFO,    "decisions", "Freshness expire : {sym} state={freshness}"),
    "GATE_SIGNAL_DEDUPED":      (LogLevel.INFO,    "decisions", "Signal dedup : {sym} signal_id={signal_id}"),
    "GATE_CONF_TOO_LOW":        (LogLevel.INFO,    "decisions", "Confidence too low : {sym} conf={confidence} < {min_conf_required}"),
    "GATE_MTF_INSUFFICIENT":    (LogLevel.INFO,    "decisions", "MTF insuffisant : {sym} dir={direction} bulls={mtf_bulls}/{mtf_bears} need>={min_required}"),
    "GATE_BAR_DMP_MISSING":     (LogLevel.ALERTE,  "decisions", "Bar DMP absente : {sym} dir={direction}"),
    "GATE_SLTP_REJECT":         (LogLevel.INFO,    "decisions", "SLTP reject : {sym} dir={direction} raison={reason_fine}"),
    "GATE_PAYOFF_TOO_LOW":      (LogLevel.INFO,    "decisions", "Payoff insuffisant : {sym} expected=${expected_payoff_usd} < min=${min_required}"),
    "DLL_RELOAD":              (LogLevel.ALERTE,   "events", "DLL Sierra Chart reloadee"),
    "CONFIG_RELOAD":           (LogLevel.INFO,     "events", "Config reloadee depuis disque"),

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
    # 01/05 Jackson "TRACK TOUT" : tracage exhaustif des rejets silencieux
    "BAR_LOAD_NONE":             (LogLevel.ALERTE,   "decisions", "Bar load None : {sym} {reason}"),
    "GATE_RTH_BLOCK":            (LogLevel.INFO,     "decisions", "Gate RTH BLOCK : {sym} hors RTH (heure UTC={hour_utc:.2f}h) — {reason}"),
    "GATE_DTC_UNAVAILABLE":      (LogLevel.ALERTE,   "decisions", "Gate DTC UNAVAILABLE : {sym} dtc_ok={dtc_ok} in_instruments={in_instruments} — {reason}"),
    # 01/05 Jackson "PAS DE VETO, JUSTE LOGGER" : veto_delta_div_buy_for_short retire
    # de quality_gate_v3 (jamais valide empiriquement). Observe-only pour audit WR.
    "VETO_DELTA_DIV_OBSERVED":   (LogLevel.INFO,     "decisions", "Veto observed : {sym} dir={direction} delta_div_buy={delta_div_buy} — {note}"),

    # Anomalies generiques python (paper_trader)
    # Permet de tracker exceptions Python uncaught dans hot paths
    "PY_EXCEPTION_HOT_PATH":     (LogLevel.CRITIQUE, "events", "Exception Python hot path : {sym} fn={fn_name} type={exc_type} msg={exc_msg}"),
    "FUNNEL_REJECT_CONTRACT_BUG":(LogLevel.MAJEUR,   "events", "Funnel reject API misuse : {sym} step={step} kwargs_overlap={overlap_keys}"),

    # Mismatch state.json vs broker (position fantome)
    "STATE_VS_BROKER_MISMATCH":  (LogLevel.CRITIQUE, "execution", "State vs broker mismatch : {sym} state={state_pos} broker={broker_pos} → cleanup attendu"),
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
