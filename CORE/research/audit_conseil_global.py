"""
Audit empirique - Conseil Global v1 (actuel) vs v2 (enrichi)
============================================================

Mission : mesurer efficacite du verdict ACHAT/VENTE du dashboard MIA
et comparer avec v2 enrichie (BN footprint + Dalton + Open Type).

Usage : python -X utf8 CORE/research/audit_conseil_global.py

Auteur : market-analyst (Claude) - 21/04/2026
"""

from __future__ import annotations
import json, math, sys
from collections import defaultdict, deque
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.research._simulator import simulate_exit_bar_aware

TICK_SIZE = 0.25
JOURS = ["20260417", "20260420", "20260421"]
SL_TICKS = 25
TP_TICKS = 50
HORIZON_BARS = 120
DEDUP_BARS = 30


def _finite(v, default=0.0):
    if v is None:
        return default
    try:
        f = float(v)
        if not math.isfinite(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _int_finite(v, default=0):
    try:
        return int(_finite(v, default))
    except (TypeError, ValueError):
        return default


def load_bars(path):
    bars = []
    if not path.exists():
        return bars
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                bars.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return bars



def compute_regime(bar):
    """Port fidele du bias + div_grade + range_pos."""
    vix = _finite(bar.get("vix_level"))
    atr_ratio = _finite(bar.get("sess_range_atr"))
    vwap_slope_10 = _finite(bar.get("vwap_slope_10"))
    vwap_d_side = _int_finite(bar.get("vwap_d_side"))
    vwap_w_side = _int_finite(bar.get("vwap_w_side"))
    vwap_m_side = _int_finite(bar.get("vwap_m_side"))
    dist_vwap = _finite(bar.get("dist_vwap_d"))
    delta_pct = _finite(bar.get("delta_pct"))
    delta_day_dir = _int_finite(bar.get("delta_day_dir"))
    delta_day = _finite(bar.get("delta_day"))
    pos = _finite(bar.get("range_pos"), 50.0)
    new_high = _int_finite(bar.get("new_swing_high"))
    new_low = _int_finite(bar.get("new_swing_low"))
    cvd_dir = _int_finite(bar.get("cvd_day_dir"))
    delta_div = _int_finite(bar.get("delta_divergence"))
    rvol = _finite(bar.get("rvol"), 1.0)

    score = 0.0
    if pos >= 80:
        if new_high and delta_day > 0:
            score += 0.10
        else:
            score -= 0.30
    elif pos <= 20:
        if new_low and delta_day < 0:
            score -= 0.10
        else:
            score += 0.30

    if delta_day_dir > 0 and delta_pct > 0.05:
        score += 0.25
    elif delta_day_dir < 0 and delta_pct < -0.05:
        score -= 0.25
    elif delta_day_dir > 0:
        score += 0.10
    elif delta_day_dir < 0:
        score -= 0.10

    if dist_vwap < -15:
        score += 0.20
    elif dist_vwap > 15:
        score -= 0.20

    if vwap_slope_10 > 2:
        score += 0.15
    elif vwap_slope_10 < -2:
        score -= 0.15

    if cvd_dir == 1:
        score += 0.10
    elif cvd_dir == -1:
        score -= 0.10

    div_quality = 0.0
    if delta_div:
        vw_str = abs(dist_vwap)
        if vw_str > 200: div_quality += 3.0
        elif vw_str > 80: div_quality += 2.0
        elif vw_str > 30: div_quality += 1.0
        if pos >= 90 or pos <= 10: div_quality += 2.0
        elif pos >= 80 or pos <= 20: div_quality += 1.0
        if atr_ratio > 1.3: div_quality += 1.5
        elif atr_ratio > 1.0: div_quality += 0.5
        if vix > 25: div_quality += 1.0
        elif vix > 20: div_quality += 0.5
        if dist_vwap < -100 and vwap_d_side == 1 and vwap_w_side == 1 and vwap_m_side == 1:
            div_quality += 1.5
        elif dist_vwap > 100 and vwap_d_side == -1 and vwap_w_side == -1 and vwap_m_side == -1:
            div_quality += 1.5
        if rvol < 0.7: div_quality += 1.0

    div_grade = "NONE"
    if div_quality >= 6: div_grade = "EXTREME"
    elif div_quality >= 4: div_grade = "FORTE"
    elif div_quality >= 3: div_grade = "MODEREE"
    elif delta_div: div_grade = "FAIBLE"

    trending_up = vwap_slope_10 > 5 and delta_day_dir > 0
    trending_dn = vwap_slope_10 < -5 and delta_day_dir < 0
    is_trending = trending_up or trending_dn

    if div_quality >= 5 and not is_trending:
        if pos >= 70 and dist_vwap < -50:
            score += -min(div_quality / 20.0, 0.35)
        elif pos <= 30 and dist_vwap > 50:
            score += min(div_quality / 20.0, 0.35)

    score = max(-1.0, min(1.0, score))
    if score > 0.25:
        bias = "BULLISH"
    elif score < -0.25:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {"bias": bias, "bias_score": score, "range_pos": pos,
            "div_grade": div_grade, "div_quality": div_quality,
            "delta_day_dir": delta_day_dir, "rvol": rvol}



def compute_mtf_at(bars, idx):
    """Port simplifie de read_mtf_bias sur 4 TF (1m/5m/15m/1h)."""
    all_bars = []
    for d in bars[:idx + 1]:
        price = _finite(d.get("price"))
        if price <= 0:
            continue
        ts_ms = d.get("ts")
        if not ts_ms:
            continue
        dist_vwap = _finite(d.get("dist_vwap_d"))
        vwap_price = price + dist_vwap * TICK_SIZE if dist_vwap != 0 else 0.0
        all_bars.append({
            "time": int(ts_ms) // 1000,
            "open": price,
            "high": _finite(d.get("bar_high"), price),
            "low": _finite(d.get("bar_low"), price),
            "close": price,
            "delta": _finite(d.get("delta_bar")),
            "vwap": vwap_price,
            "volume": _finite(d.get("total_vol")),
        })
    if len(all_bars) < 5:
        return {"bulls": 0, "bears": 0, "verdict": "N/A"}

    for i in range(1, len(all_bars)):
        all_bars[i]["open"] = all_bars[i - 1]["close"]

    def aggregate(src, tf_min):
        if tf_min <= 1:
            return src
        interval = tf_min * 60
        agg = []
        cur = None
        for b in src:
            bucket = (b["time"] // interval) * interval
            if cur is None or cur["time"] != bucket:
                if cur:
                    agg.append(cur)
                cur = dict(b)
                cur["time"] = bucket
            else:
                cur["high"] = max(cur["high"], b["high"])
                cur["low"] = min(cur["low"], b["low"])
                cur["close"] = b["close"]
                cur["delta"] = cur.get("delta", 0) + b.get("delta", 0)
                cur["volume"] = cur.get("volume", 0) + b.get("volume", 0)
                cur["vwap"] = b["vwap"]
        if cur:
            agg.append(cur)
        return agg

    def calc_bias(bars_sub, n_bars, tf_name):
        subset = bars_sub[-n_bars:] if len(bars_sub) >= n_bars else bars_sub
        if not subset:
            return 0.0
        last = subset[-1]
        vwap = last.get("vwap", 0)
        price = last["close"]
        vwap_score = 0.0
        if vwap > 0:
            dist_ticks = (price - vwap) / TICK_SIZE
            vwap_score = max(-1, min(1, dist_ticks / 60))
        total_delta = sum(b.get("delta", 0) for b in subset)
        total_vol = sum(b.get("volume", 1) for b in subset)
        delta_pct = total_delta / max(total_vol, 1)
        delta_score = max(-1, min(1, delta_pct * 5))
        mom_norm = {"1m": 0.1, "5m": 0.2, "15m": 0.3, "1h": 0.5}
        first_open = subset[0]["open"]
        last_close = subset[-1]["close"]
        if first_open > 0:
            change_pct = (last_close - first_open) / first_open * 100
            momentum_score = max(-1, min(1, change_pct / mom_norm.get(tf_name, 0.3)))
        else:
            momentum_score = 0.0
        return 0.4 * vwap_score + 0.3 * delta_score + 0.3 * momentum_score

    tfs = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
    n_per_tf = {"1m": 10, "5m": 6, "15m": 4, "1h": 4}
    scores = []
    for tf_name, tf_min in tfs.items():
        agg = aggregate(all_bars, tf_min)
        scores.append(calc_bias(agg, n_per_tf[tf_name], tf_name))

    bulls = sum(1 for s in scores if s > 0.25)
    bears = sum(1 for s in scores if s < -0.25)
    return {"bulls": bulls, "bears": bears, "verdict": f"{bulls}b/{bears}r"}


_GAMMA_THR_MIN = 10.0
_GAMMA_THR_MAX = 80.0
_GAMMA_THR_RATIO = 0.5
_GAMMA_DEFAULT_ATR = 30.0


def gamma_gate(bar):
    atr = _finite(bar.get("atr"), _GAMMA_DEFAULT_ATR) or _GAMMA_DEFAULT_ATR
    threshold = max(_GAMMA_THR_MIN, min(_GAMMA_THR_MAX, atr * _GAMMA_THR_RATIO))
    call_dist = abs(_finite(bar.get("dist_mq_call"), 0.0))
    put_dist = abs(_finite(bar.get("dist_mq_put"), 0.0))
    gex_flip = _int_finite(bar.get("bool_gex_flip_zone"))
    block_long = (0 < call_dist <= threshold)
    block_short = (0 < put_dist <= threshold)
    if gex_flip:
        block_long = True
        block_short = True
    return block_long, block_short



def conseil_global_v1(bar, regime, mtf):
    bull_pts = 0
    bear_pts = 0
    bias = regime.get("bias", "NEUTRAL")
    if bias == "BULLISH": bull_pts += 2
    elif bias == "BEARISH": bear_pts += 2
    dd = regime.get("delta_day_dir", 0)
    if dd > 0: bull_pts += 1
    elif dd < 0: bear_pts += 1
    pos = regime.get("range_pos", 50)
    if pos <= 20: bull_pts += 1
    elif pos >= 80: bear_pts += 1
    mb = mtf.get("bulls", 0)
    br = mtf.get("bears", 0)
    if mb >= 3:
        bull_pts += 2 if mb == 4 else 1
    if br >= 3:
        bear_pts += 2 if br == 4 else 1
    div_grade = regime.get("div_grade", "NONE")
    if div_grade in ("EXTREME", "FORTE"):
        if pos <= 20: bull_pts += 2
        elif pos >= 80: bear_pts += 2
    block_long, block_short = gamma_gate(bar)
    if block_long: bull_pts = min(bull_pts, 3)
    if block_short: bear_pts = min(bear_pts, 3)
    conflict = bull_pts >= 3 and bear_pts >= 3
    if conflict:
        action = "CONFLIT"
    elif bull_pts >= 5 and bear_pts <= 2:
        action = "ACHAT"
    elif bear_pts >= 5 and bull_pts <= 2:
        action = "VENTE"
    elif bull_pts >= 4 and bear_pts <= 2:
        action = "ACHAT_PRUDENT"
    elif bear_pts >= 4 and bull_pts <= 2:
        action = "VENTE_PRUDENTE"
    else:
        action = "ATTENDRE"
    return {"action": action, "bull": bull_pts, "bear": bear_pts}


class _RespInitState:
    def __init__(self, window=20):
        self.window = window
        self.out_below_pval_bar = -9999
        self.out_above_pvah_bar = -9999
        self.current_bar = 0
        self.vol_buf = deque(maxlen=20)

    def step(self, bar):
        self.current_bar += 1
        dpvah = bar.get("dist_prev_vah")
        dpval = bar.get("dist_prev_val")
        if dpvah is None or dpval is None:
            return {"ctx_responsive_buy": 0, "ctx_responsive_sell": 0,
                    "ctx_initiating_buy": 0, "ctx_initiating_sell": 0}
        try:
            dpvah = float(dpvah)
            dpval = float(dpval)
            if not (math.isfinite(dpvah) and math.isfinite(dpval)):
                return {"ctx_responsive_buy": 0, "ctx_responsive_sell": 0,
                        "ctx_initiating_buy": 0, "ctx_initiating_sell": 0}
        except (TypeError, ValueError):
            return {"ctx_responsive_buy": 0, "ctx_responsive_sell": 0,
                    "ctx_initiating_buy": 0, "ctx_initiating_sell": 0}
        vol = _finite(bar.get("total_vol"))
        self.vol_buf.append(vol)
        below_pval = dpval > 0
        above_pvah = dpvah < 0
        inside_va = (dpval < 0) and (dpvah > 0)
        if below_pval:
            self.out_below_pval_bar = self.current_bar
        if above_pvah:
            self.out_above_pvah_bar = self.current_bar
        vol_spike = False
        if len(self.vol_buf) >= 10:
            avg = sum(list(self.vol_buf)[-11:-1]) / 10
            if avg > 0 and vol / avg >= 1.5:
                vol_spike = True
        bars_since_out_pval = self.current_bar - self.out_below_pval_bar
        resp_buy = 1 if (inside_va and 0 < bars_since_out_pval <= self.window) else 0
        bars_since_out_pvah = self.current_bar - self.out_above_pvah_bar
        resp_sell = 1 if (inside_va and 0 < bars_since_out_pvah <= self.window) else 0
        init_buy = 1 if (above_pvah and vol_spike) else 0
        init_sell = 1 if (below_pval and vol_spike) else 0
        return {"ctx_responsive_buy": resp_buy, "ctx_responsive_sell": resp_sell,
                "ctx_initiating_buy": init_buy, "ctx_initiating_sell": init_sell}


OPEN_TYPE_SIZE_MULT = {
    0: 0.5, 1: 1.2, 2: 1.2, 3: 1.1, 4: 1.1, 5: 1.0, 6: 1.0,
    7: 0.7, 8: 0.9, 9: 0.9, 10: 0.5, 11: 0.5,
}



def conseil_global_v2(bar, regime, mtf, dalton_feat, variant="NORMAL"):
    """v2 enrichi. variant NORMAL (6/5) ou STRICT (7/6)."""
    bull_pts = 0.0
    bear_pts = 0.0
    bias = regime.get("bias", "NEUTRAL")
    if bias == "BULLISH": bull_pts += 2
    elif bias == "BEARISH": bear_pts += 2
    dd = regime.get("delta_day_dir", 0)
    if dd > 0: bull_pts += 1
    elif dd < 0: bear_pts += 1
    pos = regime.get("range_pos", 50)
    if pos <= 20: bull_pts += 1
    elif pos >= 80: bear_pts += 1
    mb = mtf.get("bulls", 0)
    br = mtf.get("bears", 0)
    if mb >= 3:
        bull_pts += 2 if mb == 4 else 1
    if br >= 3:
        bear_pts += 2 if br == 4 else 1
    div_grade = regime.get("div_grade", "NONE")
    if div_grade in ("EXTREME", "FORTE"):
        if pos <= 20: bull_pts += 2
        elif pos >= 80: bear_pts += 2
    block_long, block_short = gamma_gate(bar)
    if block_long: bull_pts = min(bull_pts, 3)
    if block_short: bear_pts = min(bear_pts, 3)
    bn_up = _int_finite(bar.get("bn_color_up"))
    bn_dn = _int_finite(bar.get("bn_color_dn"))
    bn_long_up = _int_finite(bar.get("bn_long_up"))
    bn_long_dn = _int_finite(bar.get("bn_long_dn"))
    bn_absorb_bid = _int_finite(bar.get("bn_absorb_bid"))
    bn_absorb_ask = _int_finite(bar.get("bn_absorb_ask"))
    if bn_up == 1 and bn_long_up == 1: bull_pts += 1.0
    if bn_dn == 1 and bn_long_dn == 1: bear_pts += 1.0
    if bn_absorb_bid == 1: bull_pts += 0.5
    if bn_absorb_ask == 1: bear_pts += 0.5
    atr = _finite(bar.get("atr"), 1.0)
    thr = max(5.0, 0.3 * atr)
    dee = abs(_finite(bar.get("dist_ext_edge_buy")))
    dlu = abs(_finite(bar.get("dist_ext_long_up")))
    des = abs(_finite(bar.get("dist_ext_edge_sell")))
    dld = abs(_finite(bar.get("dist_ext_long_dn")))
    if 0 < dee < thr and dee < 1000: bull_pts += 0.5
    if 0 < dlu < thr and dlu < 1000: bull_pts += 0.5
    if 0 < des < thr and des < 1000: bear_pts += 0.5
    if 0 < dld < thr and dld < 1000: bear_pts += 0.5
    if dalton_feat.get("ctx_initiating_buy"): bull_pts += 1.0
    if dalton_feat.get("ctx_initiating_sell"): bear_pts += 1.0
    if dalton_feat.get("ctx_responsive_buy"): bull_pts += 0.5
    if dalton_feat.get("ctx_responsive_sell"): bear_pts += 0.5
    ot = _int_finite(bar.get("open_type"))
    size_mult = OPEN_TYPE_SIZE_MULT.get(ot, 0.5)
    if bull_pts > bear_pts:
        bull_pts *= size_mult
    elif bear_pts > bull_pts:
        bear_pts *= size_mult
    if block_long: bull_pts = min(bull_pts, 3)
    if block_short: bear_pts = min(bear_pts, 3)
    if variant == "STRICT":
        thr_buy, thr_buy_p, thr_sell, thr_sell_p = 7.0, 6.0, 7.0, 6.0
    else:
        thr_buy, thr_buy_p, thr_sell, thr_sell_p = 6.0, 5.0, 6.0, 5.0
    conflict = bull_pts >= 3 and bear_pts >= 3
    if conflict:
        action = "CONFLIT"
    elif bull_pts >= thr_buy and bear_pts <= 2:
        action = "ACHAT"
    elif bear_pts >= thr_sell and bull_pts <= 2:
        action = "VENTE"
    elif bull_pts >= thr_buy_p and bear_pts <= 2:
        action = "ACHAT_PRUDENT"
    elif bear_pts >= thr_sell_p and bull_pts <= 2:
        action = "VENTE_PRUDENTE"
    else:
        action = "ATTENDRE"
    return {"action": action, "bull": bull_pts, "bear": bear_pts}


BUY_ACTIONS = {"ACHAT", "ACHAT_PRUDENT"}
SELL_ACTIONS = {"VENTE", "VENTE_PRUDENTE"}



def compute_metrics(trades, by_action, variant_name, symbol):
    n = len(trades)
    if n == 0:
        return {"variant": variant_name, "symbol": symbol, "n": 0,
                "pf": 0, "wr": 0, "ev": 0, "by_action": {},
                "total_pnl": 0, "feature_contrib": {}}
    wins = [t for t in trades if t["pnl_ticks"] > 0]
    losses = [t for t in trades if t["pnl_ticks"] < 0]
    win_sum = sum(t["pnl_ticks"] for t in wins)
    loss_sum = -sum(t["pnl_ticks"] for t in losses)
    pf = win_sum / loss_sum if loss_sum > 0 else float("inf") if win_sum > 0 else 0.0
    wr = len(wins) / n * 100
    ev = sum(t["pnl_ticks"] for t in trades) / n
    by_act = {}
    for action, ts in by_action.items():
        n2 = len(ts)
        if n2 == 0: continue
        w2 = [t for t in ts if t["pnl_ticks"] > 0]
        l2 = [t for t in ts if t["pnl_ticks"] < 0]
        wsum = sum(t["pnl_ticks"] for t in w2)
        lsum = -sum(t["pnl_ticks"] for t in l2)
        pf2 = wsum / lsum if lsum > 0 else float("inf") if wsum > 0 else 0.0
        by_act[action] = {"n": n2, "wr": len(w2) / n2 * 100, "pf": pf2,
                          "ev": sum(t["pnl_ticks"] for t in ts) / n2}
    feat_contrib = {}
    feat_keys = ["bn_color_up_long_up", "bn_color_dn_long_dn",
                 "bn_absorb_bid", "bn_absorb_ask",
                 "ctx_initiating_buy", "ctx_initiating_sell",
                 "ctx_responsive_buy", "ctx_responsive_sell",
                 "ext_edge_buy_active", "ext_long_up_active",
                 "open_type_boost", "open_type_penalty"]
    for k in feat_keys:
        actives = [t for t in trades if t.get("v2_feat", {}).get(k)]
        if actives:
            wins_a = [t for t in actives if t["pnl_ticks"] > 0]
            feat_contrib[k] = {"n": len(actives), "wr": len(wins_a) / len(actives) * 100,
                               "ev": sum(t["pnl_ticks"] for t in actives) / len(actives)}
    return {"variant": variant_name, "symbol": symbol, "n": n, "pf": pf, "wr": wr,
            "ev": ev, "total_pnl": sum(t["pnl_ticks"] for t in trades),
            "by_action": by_act, "feature_contrib": feat_contrib}


def extract_v2_features(bar, dalton_feat):
    ot = _int_finite(bar.get("open_type"))
    return {
        "bn_color_up_long_up": (_int_finite(bar.get("bn_color_up")) == 1
                                  and _int_finite(bar.get("bn_long_up")) == 1),
        "bn_color_dn_long_dn": (_int_finite(bar.get("bn_color_dn")) == 1
                                  and _int_finite(bar.get("bn_long_dn")) == 1),
        "bn_absorb_bid": _int_finite(bar.get("bn_absorb_bid")) == 1,
        "bn_absorb_ask": _int_finite(bar.get("bn_absorb_ask")) == 1,
        "ctx_initiating_buy": bool(dalton_feat.get("ctx_initiating_buy")),
        "ctx_initiating_sell": bool(dalton_feat.get("ctx_initiating_sell")),
        "ctx_responsive_buy": bool(dalton_feat.get("ctx_responsive_buy")),
        "ctx_responsive_sell": bool(dalton_feat.get("ctx_responsive_sell")),
        "ext_edge_buy_active": (abs(_finite(bar.get("dist_ext_edge_buy"))) > 0
                                   and abs(_finite(bar.get("dist_ext_edge_buy"))) < 1000),
        "ext_long_up_active": (abs(_finite(bar.get("dist_ext_long_up"))) > 0
                                  and abs(_finite(bar.get("dist_ext_long_up"))) < 1000),
        "open_type_boost": ot in (1, 2),
        "open_type_penalty": ot in (10, 11, 7),
    }



def backtest_all_days(symbol, variant_fn, name):
    all_trades = []
    by_action = defaultdict(list)
    for jour in JOURS:
        path = _ROOT / "DATA" / symbol / f"{jour}_{symbol}.jsonl"
        bars = load_bars(path)
        if not bars:
            continue
        dalton = _RespInitState(window=20)
        last_trade_idx = -DEDUP_BARS - 1
        for i, bar in enumerate(bars):
            if bar.get("session_id") != "US":
                dalton.step(bar)
                continue
            dalton_feat = dalton.step(bar)
            regime = compute_regime(bar)
            mtf = compute_mtf_at(bars, i)
            decision = variant_fn(bar, regime, mtf, dalton_feat, i)
            action = decision.get("action", "ATTENDRE")
            if action not in (BUY_ACTIONS | SELL_ACTIONS):
                continue
            if i - last_trade_idx < DEDUP_BARS:
                continue
            entry_price = _finite(bar.get("price"))
            if entry_price <= 0:
                continue
            direction = "BUY" if action in BUY_ACTIONS else "SELL"
            exit_info = simulate_exit_bar_aware(
                bars, i, direction, entry_price, SL_TICKS, TP_TICKS,
                HORIZON_BARS, TICK_SIZE)
            if not exit_info:
                continue
            t = {"jour": jour, "idx": i, "action": action, "direction": direction,
                 "bull": decision["bull"], "bear": decision["bear"],
                 "entry_price": entry_price, "exit_reason": exit_info["exit_reason"],
                 "pnl_ticks": exit_info["pnl_ticks"],
                 "v2_feat": extract_v2_features(bar, dalton_feat)}
            all_trades.append(t)
            by_action[action].append(t)
            last_trade_idx = i
    return compute_metrics(all_trades, by_action, name, symbol)


def fmt_pf(pf):
    if pf == float("inf"):
        return "inf"
    return f"{pf:.2f}"



def main():
    print("=" * 80)
    print("AUDIT CONSEIL GLOBAL v1 vs v2")
    print("=" * 80)
    print("Jours :", JOURS, "(19/04 = weekend, ignore)")
    print("Config: SL=" + str(SL_TICKS) + "t TP=" + str(TP_TICKS) + "t RR=2.0 horizon=" + str(HORIZON_BARS) + " dedup=" + str(DEDUP_BARS))
    print("Session : US uniquement")
    print("")
    summary = []
    for symbol in ["ES", "NQ"]:
        print("")
        print("-" * 60)
        print("SYMBOL " + symbol)
        print("-" * 60)
        variants = [
            ("v1", lambda b, r, m, d, i: conseil_global_v1(b, r, m)),
            ("v2_NORMAL", lambda b, r, m, d, i: conseil_global_v2(b, r, m, d, "NORMAL")),
            ("v2_STRICT", lambda b, r, m, d, i: conseil_global_v2(b, r, m, d, "STRICT")),
        ]
        for name, fn in variants:
            res = backtest_all_days(symbol, fn, name)
            summary.append(res)
            print("")
            print(name + ":")
            print("  N trades : " + str(res["n"]))
            print("  WR       : " + ("%.1f%%" % res["wr"]))
            print("  PF       : " + fmt_pf(res["pf"]))
            print("  EV/trade : " + ("%+.1f ticks" % res["ev"]))
            print("  Total PnL: " + ("%+.0f ticks" % res.get("total_pnl", 0)))
            if res.get("by_action"):
                print("  Par action :")
                for act, mx in sorted(res["by_action"].items()):
                    line = "    %-15s N=%3d  WR=%4.1f%%  PF=%5s  EV=%+.1ft" % (act, mx["n"], mx["wr"], fmt_pf(mx["pf"]), mx["ev"])
                    print(line)
    print("")
    print("=" * 80)
    print("TABLEAU COMPARATIF")
    print("=" * 80)
    print("%-8s %-12s %5s %7s %7s %7s %8s" % ("Symbol", "Variant", "N", "WR%", "PF", "EV", "Total"))
    print("-" * 60)
    for r in summary:
        pf_s = fmt_pf(r["pf"])
        line = "%-8s %-12s %5d %6.1f%% %7s %+6.1f %+7.0f" % (r["symbol"], r["variant"], r["n"], r["wr"], pf_s, r["ev"], r.get("total_pnl", 0))
        print(line)
    print("")
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    for symbol in ["ES", "NQ"]:
        v1 = next((r for r in summary if r["symbol"] == symbol and r["variant"] == "v1"), None)
        v2n = next((r for r in summary if r["symbol"] == symbol and r["variant"] == "v2_NORMAL"), None)
        v2s = next((r for r in summary if r["symbol"] == symbol and r["variant"] == "v2_STRICT"), None)
        if not v1 or not v2n:
            continue
        pf_v1 = v1["pf"] if v1["pf"] != float("inf") else 99.0
        pf_v2n = v2n["pf"] if v2n["pf"] != float("inf") else 99.0
        pf_v2s = v2s["pf"] if v2s and v2s["pf"] != float("inf") else 99.0
        diff_n = pf_v2n - pf_v1
        diff_s = pf_v2s - pf_v1
        print("")
        print(symbol + ":")
        print("  v1        PF=" + fmt_pf(v1["pf"]) + " WR=%.1f%% N=%d" % (v1["wr"], v1["n"]))
        print("  v2 NORMAL PF=" + fmt_pf(v2n["pf"]) + " WR=%.1f%% N=%d  (diff PF %+.2f)" % (v2n["wr"], v2n["n"], diff_n))
        if v2s:
            print("  v2 STRICT PF=" + fmt_pf(v2s["pf"]) + " WR=%.1f%% N=%d  (diff PF %+.2f)" % (v2s["wr"], v2s["n"], diff_s))
        best_diff = max(diff_n, diff_s)
        if best_diff >= 0.3:
            print("  -> GO patch dashboard (v2 >= v1 + 0.3 PF)")
        elif abs(best_diff) < 0.3:
            print("  -> NOISE : garder v1 (|diff| < 0.3 PF)")
        else:
            print("  -> v2 degrade : garder v1")
    print("")
    print("=" * 80)
    print("FEATURE CONTRIBUTION (v2_NORMAL)")
    print("=" * 80)
    for r in summary:
        if r["variant"] != "v2_NORMAL":
            continue
        fc = r.get("feature_contrib", {})
        if not fc:
            continue
        print("")
        print(r["symbol"] + " - features actives dans trades v2 :")
        sorted_fc = sorted(fc.items(), key=lambda x: -x[1]["ev"])
        for k, v in sorted_fc:
            line = "  %-30s N=%3d  WR=%4.1f%%  EV=%+.1ft" % (k, v["n"], v["wr"], v["ev"])
            print(line)
    print("")
    print("=" * 80)
    print("HONESTY DISCLOSURE")
    print("=" * 80)
    n_jours = len(JOURS)
    total_trades = sum(r["n"] for r in summary)
    print("Jours utiles     : " + str(n_jours) + " (17, 20, 21 avril - 19/04 weekend)")
    print("Total trades     : " + str(total_trades) + " (3 variantes x 2 symboles)")
    print("Variantes testees: 3 (v1 + v2 NORMAL + v2 STRICT). PAS de grid search.")
    print("Sample           : FAIBLE. Re-valider sur >=20 jours v4 mi-mai 2026.")
    print("Ponderations v2  : fixees a priori (theorie). PAS d optimization.")


if __name__ == "__main__":
    main()
