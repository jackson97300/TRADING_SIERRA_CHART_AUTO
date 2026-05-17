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

    # ============================================================
    # V6 brain Sim2 (05/05) — Bot V6 enrichi Databento V4
    # ============================================================
    "BRAIN_V6_ACTIVE":           (LogLevel.INFO,    "events",    "Bot V6 brain actif : {sym} regime_mode={regime_mode} favor={regime_favor} bias_v6_score={bias_v6_score} dir={bias_v6_dir}"),
    "V6_V4_BAR_STALE":           (LogLevel.MAJEUR,  "events",    "V6 bar V4 STALE : {sym} age={age_sec}s > {threshold}s (pipeline V4 retard) -> fallback DMP"),
    "V6_V4_FALLBACK_DMP":        (LogLevel.ALERTE,  "events",    "V6 fallback DMP : {sym} V4 indisponible source={fallback_source} reason={reason}"),
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
    "ENRICHER_SEED_VP_FAIL": (LogLevel.ALERTE, "events", "Enricher seed VolumeProfile FAIL : {sym} reason={reason} (P2.1 - prev_*/pdh/pdl restera null jusqu'a session change)"),
    "ENRICHER_DATA_QUALITY_FLAG_SET": (LogLevel.ALERTE, "decisions", "Enricher data_quality_flag SET : {sym} flag={flag} n_bars={n_bars} sid={sid} (bit0=warmup bit1=sentinel999 bit2=sd_collapse bit3=swing_reset bit4=session_corrupt bit5=open_approximate bit6=ib_missing - ETL/ML drop si bit relevant)"),
    "ENRICHER_SESSIONS_OPEN_APPROXIMATE": (LogLevel.ALERTE, "decisions", "Enricher session open APPROXIMATE : {sym} session={session} mins_et={mins_et} start_exact={start_exact} (live boot mid-session, parite batch cassee, V4 batch ne refletera pas cet open)"),
    "ENRICHER_SEED_IB_FROM_V4": (LogLevel.INFO, "events", "Enricher seed IB (ib_high/ib_low) depuis V4 : {sym} sdt={sdt} ib_high={ib_high} ib_low={ib_low} (BUG #2 fix - cold/HOT restart > 10:30 ET)"),
    "ENRICHER_SEED_IB_FAIL": (LogLevel.ALERTE, "events", "Enricher seed IB FAIL : {sym} reason={reason} (BUG #2 - ib_high/ib_low restera NaN si live down 09:30-10:30 ET aujourd'hui)"),
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
