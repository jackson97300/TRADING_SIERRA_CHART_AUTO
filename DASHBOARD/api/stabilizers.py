"""Stabilisateurs de signaux et cache pour le dashboard MIA V2.

Contient :
- _cached_call + _cache : cache TTL + mtime pour les appels couteux
- _enrich_regime_with_mtf : enrichissement regime par le MTF
- _stabilize_favor / _stabilize_qui : anti flip-flop sur les signaux
- _log_session_snapshot : ecriture JSONL 1 ligne/minute pour revue post-session

IMPORTANT : ces etats globaux (_cache, _prev_state, _favor_state, _qui_state)
necessitent uvicorn --workers 1. En multi-worker, externaliser dans Redis/SQLite.
"""
import json
import os
import time
from datetime import datetime, timezone

from DASHBOARD.api.data_reader import _calc_confidence, dist_to_price, get_field

# Logger V2 (R5 code-reviewer BUG #1 08/06) — emit BIAS_NEUTRAL_ZONE_FALLBACK
# si MTF boost ne suffit pas a basculer bias amont (audit J+7 impact fix).
# Fail-safe : si import echoue, fallback no-op.
# FIX 08/09 (audit) : le module n'a pas de emit() module-level — l'ancien
# import rendait chaque _v2log.emit() AttributeError avalee : ZERO emission
# en 3 mois. Un Logger via get_logger(), comme partout ailleurs.
try:
    from CORE.logging_v2 import get_logger as _get_logger
    _v2log = _get_logger("dashboard_stabilizers", process="dashboard")
except Exception:
    _v2log = None


# ═══════════════════════════════════════════════════════════════
# Cache TTL + mtime
# ═══════════════════════════════════════════════════════════════

_cache: dict = {}  # {key: {"data": ..., "mtime": float, "ts": float}}
CACHE_TTL = {"mtf": 10, "patterns": 60, "patterns_intraday": 15, "cta": 300}


def _cached_call(key, func, *args, ttl=10, file_path=None):
    """Cache avec TTL + verification mtime du fichier source."""
    now = time.time()
    entry = _cache.get(key)

    current_mtime = 0
    if file_path:
        try:
            current_mtime = os.path.getmtime(file_path)
        except OSError:
            pass

    if entry:
        age = now - entry["ts"]
        if age < ttl and (not file_path or entry["mtime"] == current_mtime):
            return entry["data"]

    result = func(*args)
    _cache[key] = {"data": result, "mtime": current_mtime, "ts": now}
    return result


# ═══════════════════════════════════════════════════════════════
# MTF Enrichment — ajuste confiance/favor du regime avec le MTF
# ═══════════════════════════════════════════════════════════════


def _enrich_regime_with_mtf(regime: dict, mtf: dict):
    """Modifie le regime in-place en integrant le MTF.

    FIX BUG #1 (08/06/2026) — Suppression override brutal favor + bias.
    Avant : MTF 4/4 forcait `favor=LONG` et `bias=BULLISH` meme si `bias_score`
    amont etait fortement BEARISH (-0.40). Le regime_engine etait bypass total.
    Apres : MTF contribue UNIQUEMENT via le boost de score. Le label bias est
    recalcule via le seuil score +-0.25, et le favor reste celui calcule par
    l'amont (regime_engine.compute_regime ou build_regime_context).
    Cf DOCS/BOT_CHANGELOG.md 08/06 + memory feedback_mtf_no_override.md
    """
    if not regime or not mtf:
        return

    bulls = mtf.get("bulls", 0)
    bears = mtf.get("bears", 0)
    confluence = mtf.get("confluence", 0)
    verdict = mtf.get("verdict", "")

    old_score = regime.get("bias_score", 0)
    old_favor = regime.get("favor", "NEUTRE")

    # Boost confiance par le MTF (graduation 2-3-4 timeframes alignees)
    mtf_boost = 0.0
    if bulls == 4 or bears == 4:
        mtf_boost = 0.25
    elif bulls == 3 or bears == 3:
        mtf_boost = 0.15
    elif bulls >= 2 or bears >= 2:
        mtf_boost = 0.10

    # Direction du boost (vers BULL ou BEAR)
    mtf_direction = 0
    if bulls >= 3:
        mtf_direction = 1
    elif bears >= 3:
        mtf_direction = -1

    new_score = old_score + mtf_direction * mtf_boost

    # FIX #1 : favor reste celui de l'amont. MTF n'override plus.
    # Si l'amont a calcule favor=NEUTRE/SHORT, MTF bull 4/4 ne force PAS LONG.
    # Le boost de score sera reflete dans le bias label si franchit seuil 0.25.
    new_favor = old_favor

    # FIX #1 : bias recalcule UNIQUEMENT via new_score (seuils +-0.25).
    # Plus de short-circuit "bulls==4 → BULLISH" qui ignorait old_score.
    old_bias = regime.get("bias", "NEUTRAL")
    if new_score > 0.25:
        new_bias = "BULLISH"
        new_bias_label = "HAUSSIER"
    elif new_score < -0.25:
        new_bias = "BEARISH"
        new_bias_label = "BAISSIER"
    else:
        new_bias = old_bias
        new_bias_label = regime.get("bias_label", "NEUTRE")
        # R5 audit J+7 : emit log quand fallback preserve bias amont non-NEUTRAL
        # (cas typique fix BUG #1 : MTF 4/4 contre bias -0.40 → score -0.15 zone
        # neutre → preserve BEARISH amont au lieu de forcer BULLISH comme avant).
        if old_bias != "NEUTRAL" and mtf_direction != 0 and _v2log:
            try:
                _v2log.emit(
                    "BIAS_NEUTRAL_ZONE_FALLBACK",
                    sym=regime.get("sym", "?"),
                    old_bias=old_bias,
                    old_score=round(old_score, 3),
                    new_score=round(new_score, 3),
                    mtf_bulls=bulls,
                    mtf_bears=bears,
                )
            except Exception:
                pass  # fail-safe : logging ne doit jamais bloquer le pipeline

    # Ajouter le facteur MTF dans bias_factors
    factors = regime.get("bias_factors", [])
    if mtf_direction != 0:
        icon = "bull" if mtf_direction > 0 else "bear"
        factors.append({
            "icon": icon,
            "text": f"MTF {verdict} (boost +{mtf_boost:.0%})",
        })

    # Recalculer confiance APRES ajout du facteur MTF
    new_confidence = _calc_confidence(new_score, factors)

    # Mettre a jour
    regime["bias"] = new_bias
    regime["bias_label"] = new_bias_label
    regime["bias_score"] = round(new_score, 3)
    regime["bias_confidence"] = round(new_confidence, 2)
    regime["bias_factors"] = factors
    regime["favor"] = new_favor
    regime["mtf_verdict"] = verdict
    regime["mtf_bulls"] = bulls
    regime["mtf_bears"] = bears


# ═══════════════════════════════════════════════════════════════
# Level Break Detector — detecte quand le prix casse un niveau cle
# ═══════════════════════════════════════════════════════════════

_prev_state: dict = {}
_break_cooldown: dict = {}  # {symbol_level: poll_count}
BREAK_COOLDOWN_POLLS = 12  # ~60s de cooldown (12 polls x 5s)
BREAK_MIN_DIST = 8  # distance min en ticks pour valider une cassure


def _niveaux_cles(bar: dict) -> dict:
    """LA carte des niveaux — une seule liste, partagee par le detecteur de
    cassures et la porte de lieu (jamais deux listes qui divergent)."""
    levels = {}
    _add = lambda name, val: levels.update({name: val}) if val else None
    _add("VWAP_D", dist_to_price(bar, "dist_vwap_d"))
    _add("VWAP_W", dist_to_price(bar, "dist_vwap_w"))
    _add("VWAP_M", dist_to_price(bar, "dist_vwap_m"))
    _add("VPOC", dist_to_price(bar, "dist_cur_vpoc"))
    _add("VAH", dist_to_price(bar, "dist_cur_vah"))
    _add("VAL", dist_to_price(bar, "dist_cur_val"))
    _add("PREV_VPOC", dist_to_price(bar, "dist_prev_vpoc"))
    _add("SWING_H", dist_to_price(bar, "dist_swing_high"))
    _add("SWING_L", dist_to_price(bar, "dist_swing_low"))
    _add("IB_H", dist_to_price(bar, "dist_ib_high"))
    _add("IB_L", dist_to_price(bar, "dist_ib_low"))
    _add("OVN_H", dist_to_price(bar, "dist_ovn_high"))
    _add("OVN_L", dist_to_price(bar, "dist_ovn_low"))
    _add("CALL_WALL", dist_to_price(bar, "dist_mq_call"))
    _add("PUT_WALL", dist_to_price(bar, "dist_mq_put"))
    _add("HVL", dist_to_price(bar, "dist_mq_hvl"))
    _add("SD1U", dist_to_price(bar, "dist_vwap_d_sd1u"))
    _add("SD1D", dist_to_price(bar, "dist_vwap_d_sd1d"))
    _add("SD2U", dist_to_price(bar, "dist_vwap_d_sd2u"))
    _add("SD2D", dist_to_price(bar, "dist_vwap_d_sd2d"))
    return levels


# PORTE DE LIEU (Jackson 08/09) : « les entrees se font aux zones, pas au
# milieu ». Seuils = le P10 de V3 : 0,10 x atr_barre MEDIAN par instrument
# (mesures 06-07/09 : ES 15,11 pts -> 6 t ; NQ 101,14 pts -> 40 t) — jamais
# recopie d'un instrument a l'autre (regle calibration 04/09). Fallback 8 t.
SEUIL_ZONE_TICKS = {"ES": 6, "NQ": 40}


def zone_info(bar: dict) -> dict:
    """Le niveau le plus proche du prix + le verdict `en_zone`.

    Audit du 08/09 : « Breakdown SWING_H » conseille a 17 pts SOUS la zone,
    dans un aimant a 10 pts — R:R 0,23 contre 1,7 a la zone. Le detecteur
    de cassures exige d'etre >= 8 t AU-DELA du niveau (anti-bruit) : par
    construction, un signal d'evenement n'est JAMAIS a la zone. Cette porte
    le dit — build_conseil_global passe ATTENDRE hors zone, le favor force
    porte le motif."""
    price = get_field(bar, "price", 0.0) if bar else 0.0
    if not price:
        return {"en_zone": False, "niveau": None, "prix": None,
                "dist_ticks": None, "seuil_ticks": None}
    levels = _niveaux_cles(bar)
    if not levels:
        return {"en_zone": False, "niveau": None, "prix": None,
                "dist_ticks": None, "seuil_ticks": None}
    nom, lvl = min(levels.items(), key=lambda kv: abs(price - kv[1]))
    from DASHBOARD.api.readers import TICK_SIZE   # jamais un 0.25 en dur (S1)
    dist_t = round(abs(price - lvl) / TICK_SIZE)
    seuil = SEUIL_ZONE_TICKS.get(str(bar.get("sym", "")).upper(), 8)
    return {"en_zone": dist_t <= seuil, "niveau": nom, "prix": lvl,
            "dist_ticks": dist_t, "seuil_ticks": seuil}


def detect_level_breaks(symbol: str, bar: dict) -> list[dict]:
    """Detecte les cassures de niveaux avec cooldown anti-bruit."""
    global _prev_state, _break_cooldown
    if not bar:
        return []

    price = get_field(bar, "price", 0.0)
    if not price:
        return []

    levels = _niveaux_cles(bar)

    prev = _prev_state.get(symbol, {})
    breaks = []

    # Decrementer les cooldowns
    for key in list(_break_cooldown.keys()):
        if key.startswith(symbol + "_"):
            _break_cooldown[key] -= 1
            if _break_cooldown[key] <= 0:
                del _break_cooldown[key]

    for name, lvl_price in levels.items():
        if not lvl_price:
            continue
        current_side = "above" if price > lvl_price else "below"
        prev_side = prev.get(name)
        cooldown_key = f"{symbol}_{name}"

        if prev_side and prev_side != current_side:
            dist_ticks = round((price - lvl_price) / 0.25)

            if abs(dist_ticks) < BREAK_MIN_DIST:
                continue

            if cooldown_key in _break_cooldown:
                continue

            _break_cooldown[cooldown_key] = BREAK_COOLDOWN_POLLS

            if current_side == "above":
                breaks.append({
                    "level": name, "price": lvl_price, "direction": "BREAKOUT",
                    "signal": "BUY", "dist": dist_ticks,
                    "text": f"{name} {lvl_price:.2f} CASSE par le HAUT (+{dist_ticks}t)",
                })
            else:
                breaks.append({
                    "level": name, "price": lvl_price, "direction": "BREAKDOWN",
                    "signal": "SELL", "dist": dist_ticks,
                    "text": f"{name} {lvl_price:.2f} CASSE par le BAS ({dist_ticks}t)",
                })

    new_state = {name: ("above" if price > lvl else "below") for name, lvl in levels.items() if lvl}
    _prev_state[symbol] = new_state

    return breaks


# ═══════════════════════════════════════════════════════════════
# Favor Stabilizer — empeche les flip-flops
# ═══════════════════════════════════════════════════════════════

_favor_state: dict = {}
# {symbol: {"current": "LONG/SHORT/NEUTRE", "reason": str, "votes": [],
#           "trigger_price": float, "trigger_time": str}}

FAVOR_MIN_VOTES = 3


def _stabilize_favor(symbol: str, regime: dict, advisory: dict | None, level_breaks: list):
    """Stabilise le favor + enregistre le prix de declenchement pour la fraicheur."""
    global _favor_state
    if not regime:
        return

    raw_favor = regime.get("favor", "NEUTRE")
    state = _favor_state.get(symbol, {
        "current": "NEUTRE", "reason": "init", "votes": [],
        "trigger_price": 0.0, "trigger_time": "",
    })

    # Detecter les evenements forts qui forcent un changement immediat
    forced = False
    force_reason = ""

    # 1. Cassure de niveau cle
    if level_breaks:
        for lb in level_breaks:
            if lb.get("level") in ("VWAP_D", "VPOC", "VAH", "VAL", "SWING_H", "SWING_L", "IB_H", "IB_L"):
                if lb["signal"] == "BUY" and raw_favor == "LONG":
                    forced = True
                    force_reason = f"Breakout {lb['level']} {lb['price']:.2f}"
                elif lb["signal"] == "SELL" and raw_favor == "SHORT":
                    forced = True
                    force_reason = f"Breakdown {lb['level']} {lb['price']:.2f}"

    # FIX BUG #1 R1 (08/06/2026) — Suppression force MTF 4/4 dans _stabilize_favor.
    # AVANT : MTF 4/4 forcait raw_favor = LONG/SHORT meme si bias_score amont contradit.
    # CASCADE : meme bug qu'au-dessus dans _enrich_regime_with_mtf — Bot 1 prenait
    # des LONG NQ en dead cat bounce via cette couche meme apres fix #1.
    # APRES : MTF est deja represente via le boost de score (+0.25 max) qui se
    # propage en `bias` -> `favor` par le pipeline amont. Pas besoin de re-forcer ici.
    # Cf reviewer code-reviewer a7a1a8b98472f08f1 R1 + memory feedback_mtf_no_override.md.
    mtf_bulls = regime.get("mtf_bulls", 0)
    mtf_bears = regime.get("mtf_bears", 0)

    # 3. Divergence EXTREME — SAUF en mode TREND (pas de fade de breakout)
    div_grade = regime.get("div_grade", "NONE")
    reg_mode = regime.get("mode", "NORMAL")
    if div_grade == "EXTREME" and reg_mode != "TREND":
        range_pos = regime.get("range_pos", 50)
        if range_pos >= 80 and raw_favor == "SHORT" and state["current"] != "SHORT":
            forced = True
            force_reason = "DIV EXTREME au top"
        elif range_pos <= 20 and raw_favor == "LONG" and state["current"] != "LONG":
            forced = True
            force_reason = "DIV EXTREME au bottom"

    # PORTE DE LIEU (Jackson 08/09) : un favor FORCE par une cassure alors
    # que le prix est loin de toute zone doit LE DIRE — l'evenement presse,
    # la zone attend. La demote en ATTENDRE vit dans build_conseil_global ;
    # ici on rend le motif honnete sur la carte FAVORISER.
    zone = regime.get("zone") or {}
    if forced and zone and not zone.get("en_zone", True):
        force_reason += " — HORS ZONE (plus proche %s a %st, seuil %st)" % (
            zone.get("niveau"), zone.get("dist_ticks"), zone.get("seuil_ticks"))

    # Prix actuel pour le tracking
    current_price = regime.get("_price", 0.0)
    now_str = datetime.now(timezone.utc).strftime("%H:%M")

    old_favor = state["current"]

    if forced:
        state["current"] = raw_favor
        state["reason"] = force_reason
        state["votes"] = []
        state["trigger_price"] = current_price
        state["trigger_time"] = now_str
    else:
        if raw_favor != state["current"] and raw_favor != "NEUTRE":
            state["votes"].append(raw_favor)
            state["votes"] = state["votes"][-5:]
            consecutive = 0
            for v in reversed(state["votes"]):
                if v == raw_favor:
                    consecutive += 1
                else:
                    break
            if consecutive >= FAVOR_MIN_VOTES:
                # FIX BUG #1 R2 (08/06/2026) — Suppression veto MTF 4/4 sur flip consensus.
                # AVANT : si mtf_bears >= 4 bloquait un flip vers LONG (et inverse), meme
                # avec consensus 3 votes. Resultat : state["current"] reste sur ancien favor
                # pendant que le marche bascule. Double source de verite vs regime_engine.
                # APRES : consensus 3 votes consecutifs = flip libre. MTF est deja represente
                # dans raw_favor via pipeline amont (bias_score boost +0.25). Pas de double-check.
                state["current"] = raw_favor
                state["reason"] = f"Consensus {consecutive} votes"
                state["votes"] = []
                state["trigger_price"] = current_price
                state["trigger_time"] = now_str
        elif raw_favor == state["current"]:
            state["votes"] = []

    _favor_state[symbol] = state

    # Calculer la fraicheur du signal
    trigger_price = state.get("trigger_price", 0)
    trigger_time = state.get("trigger_time", "")
    moved_ticks = 0
    freshness = "FRAIS"

    if trigger_price and current_price and state["current"] != "NEUTRE":
        if state["current"] == "SHORT":
            moved_ticks = round((trigger_price - current_price) / 0.25)
        else:  # LONG
            moved_ticks = round((current_price - trigger_price) / 0.25)

        if moved_ticks > 200:
            freshness = "EPUISE"
        elif moved_ticks > 80:
            freshness = "AVANCE"
        elif moved_ticks > 20:
            freshness = "EN COURS"
        elif moved_ticks < -20:
            freshness = "CONTRE"
        else:
            freshness = "FRAIS"

    # Ecrire dans le regime et l'advisory
    regime["favor"] = state["current"]
    regime["favor_reason"] = state["reason"]
    regime["favor_raw"] = raw_favor
    regime["favor_trigger_price"] = trigger_price
    regime["favor_trigger_time"] = trigger_time
    regime["favor_moved_ticks"] = moved_ticks
    regime["favor_freshness"] = freshness

    if advisory:
        advisory["favor"] = state["current"]
        advisory["favor_reason"] = state["reason"]
        advisory["favor_freshness"] = freshness
        advisory["favor_moved_ticks"] = moved_ticks


# ═══════════════════════════════════════════════════════════════
# Qui Stabilizer — empeche les flip-flops
# ═══════════════════════════════════════════════════════════════

_qui_state = {"current": "PERSONNE", "votes": []}
QUI_MIN_VOTES = 3


def _stabilize_qui(advisory: dict):
    """Stabilise qui_a_la_main — ne flippe pas a chaque barre."""
    global _qui_state
    if not advisory:
        return

    raw = advisory.get("qui_a_la_main", "PERSONNE")

    if raw != _qui_state["current"]:
        _qui_state["votes"].append(raw)
        _qui_state["votes"] = _qui_state["votes"][-5:]
        consecutive = 0
        for v in reversed(_qui_state["votes"]):
            if v == raw:
                consecutive += 1
            else:
                break
        if consecutive >= QUI_MIN_VOTES:
            _qui_state["current"] = raw
            _qui_state["votes"] = []
    else:
        _qui_state["votes"] = []

    advisory["qui_a_la_main"] = _qui_state["current"]


# ═══════════════════════════════════════════════════════════════
# Session Logger — ecrit 1 ligne JSONL par minute
# ═══════════════════════════════════════════════════════════════

_last_log_minute = 0


def _log_session_snapshot(bar_es, bar_nq, regime_es, regime_nq, advisory, intermarket):
    """Ecrit un snapshot par minute dans DATA/SESSION_LOGS/YYYYMMDD.jsonl."""
    global _last_log_minute
    now = datetime.now(timezone.utc)
    minute_key = now.hour * 60 + now.minute
    if minute_key == _last_log_minute:
        return
    _last_log_minute = minute_key

    base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "DATA", "SESSION_LOGS")
    os.makedirs(base_dir, exist_ok=True)
    filepath = os.path.join(base_dir, f"{now.strftime('%Y%m%d')}.jsonl")

    def _safe(bar, field, default=0):
        if not bar:
            return default
        v = bar.get(field, default)
        return v if v is not None else default

    snapshot = {
        "ts": now.isoformat(),
        "minute": now.strftime("%H:%M"),
        "es_price": _safe(bar_es, "price"),
        "nq_price": _safe(bar_nq, "price"),
        "es_bias": regime_es.get("bias", "?") if regime_es else "?",
        "es_bias_score": regime_es.get("bias_score", 0) if regime_es else 0,
        "es_confidence": regime_es.get("bias_confidence", 0) if regime_es else 0,
        "es_mode": regime_es.get("mode", "?") if regime_es else "?",
        "es_favor": regime_es.get("favor", "?") if regime_es else "?",
        "es_range_pos": regime_es.get("range_pos", 50) if regime_es else 50,
        "es_div_active": regime_es.get("div_active", False) if regime_es else False,
        "es_div_quality": regime_es.get("div_quality", 0) if regime_es else 0,
        "es_div_grade": regime_es.get("div_grade", "NONE") if regime_es else "NONE",
        "nq_bias": regime_nq.get("bias", "?") if regime_nq else "?",
        "nq_bias_score": regime_nq.get("bias_score", 0) if regime_nq else 0,
        "nq_confidence": regime_nq.get("bias_confidence", 0) if regime_nq else 0,
        "nq_mode": regime_nq.get("mode", "?") if regime_nq else "?",
        "nq_favor": regime_nq.get("favor", "?") if regime_nq else "?",
        "nq_range_pos": regime_nq.get("range_pos", 50) if regime_nq else 50,
        "nq_div_active": regime_nq.get("div_active", False) if regime_nq else False,
        "nq_div_quality": regime_nq.get("div_quality", 0) if regime_nq else 0,
        "nq_div_grade": regime_nq.get("div_grade", "NONE") if regime_nq else "NONE",
        "adv_favor": advisory.get("favor", "?") if advisory else "?",
        "adv_qui": advisory.get("qui_a_la_main", "?") if advisory else "?",
        "adv_force": advisory.get("force", "?") if advisory else "?",
        "smt_div": (intermarket or {}).get("smt_divergence", 0),
        "smt_dir": (intermarket or {}).get("smt_direction", "NONE"),
        "es_delta_day": _safe(bar_es, "delta_day"),
        "nq_delta_day": _safe(bar_nq, "delta_day"),
        "es_rvol": _safe(bar_es, "rvol", 1.0),
        "nq_rvol": _safe(bar_nq, "rvol", 1.0),
        "es_vwap_d": _safe(bar_es, "dist_vwap_d"),
        "nq_vwap_d": _safe(bar_nq, "dist_vwap_d"),
        "vix": _safe(bar_es, "vix_level"),
    }

    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except OSError:
        pass
