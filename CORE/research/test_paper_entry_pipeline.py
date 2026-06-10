"""Test empirique pipeline check_entry — step-by-step debug."""
import sys, json, os, time
from datetime import datetime, timezone

sys.path.insert(0, ".")

import CORE.mia_paper_trader as mpt
mpt.DATA_DIR = "/tmp/paper_test"
mpt.STATE_FILE = "/tmp/paper_test/state.json"
os.makedirs(mpt.DATA_DIR, exist_ok=True)

# On charge une VRAIE barre du JSONL live pour avoir toutes les features
def load_real_bar(symbol):
    """Load derniere barre du JSONL."""
    p = f"DATA/{symbol}/20260422_{symbol}.jsonl"
    with open(p, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in reversed(lines):
        s = line.strip()
        if s:
            b = json.loads(s)
            if b.get("price"):
                return b
    return None

real_bar_es = load_real_bar("ES")
real_bar_nq = load_real_bar("NQ")
print(f"Real bar ES loaded: price={real_bar_es.get('price')} atr={real_bar_es.get('atr')}")
print(f"Real bar NQ loaded: price={real_bar_nq.get('price')} atr={real_bar_nq.get('atr')}")
print(f"  NQ dist_gex_nearest_up: {real_bar_nq.get('dist_gex_nearest_up')}")
print(f"  NQ dist_cur_vah: {real_bar_nq.get('dist_cur_vah')}")
print(f"  NQ dist_session_hvn_above: {real_bar_nq.get('dist_session_hvn_above')}")

mpt.PaperTrader._read_last_jsonl_bar = lambda self, symbol: real_bar_es if symbol == "ES" else real_bar_nq

# Patch check_entry pour tracer step-by-step
orig_check_entry = mpt.PaperTrader.check_entry

def check_entry_traced(self, data, symbol):
    """Copie de check_entry avec prints a chaque step."""
    print(f"\n  >> check_entry({symbol})")
    sym = symbol.lower()
    instr = data.get(sym)
    if not instr:
        print(f"  [STEP 0] REJECT : instr absent")
        return None
    reg = instr.get("regime", {})
    banner = data.get("banner", {})
    price = banner.get(sym, {}).get("price", 0)
    if not price:
        print(f"  [STEP 0] REJECT : price manquant")
        return None
    print(f"  [STEP 0] OK : price={price}")

    if symbol in self.positions:
        print(f"  [STEP 1] REJECT : deja en position")
        return None
    if self.trade_count >= mpt.ENTRY_RULES["max_trades_per_day"]:
        print(f"  [STEP 1] REJECT : trade_count max")
        return None
    print(f"  [STEP 1] OK : position+count")

    now_ts = time.time()
    last_close = self._last_close_ts.get(symbol)
    if last_close and (now_ts - last_close) < mpt.ENTRY_RULES["cooldown_post_close_sec"]:
        print(f"  [STEP 2] REJECT : cooldown")
        return None
    pause_until = self._circuit_pause_until.get(symbol)
    if pause_until and now_ts < pause_until:
        print(f"  [STEP 2] REJECT : circuit breaker")
        return None
    print(f"  [STEP 2] OK : cooldown+breaker")

    conseil = data.get("conseil_global", {}).get(sym, {})
    action = conseil.get("action", "ATTENDRE")
    print(f"  [STEP 3] action={action}")
    if action in ("ATTENDRE", "CONFLIT"):
        print(f"  [STEP 3] REJECT : action")
        return None
    direction_int = 1 if "ACHAT" in action else -1
    direction = "LONG" if direction_int == 1 else "SHORT"
    prudent = "PRUDENT" in action
    print(f"  [STEP 3] OK : direction={direction}")

    freshness_v15 = conseil.get("freshness", "IDLE")
    if freshness_v15 != mpt.ENTRY_RULES["freshness_required"]:
        print(f"  [STEP 4] REJECT : freshness={freshness_v15}")
        return None
    print(f"  [STEP 4] OK : freshness=NEW")

    signal_id = conseil.get("signal_id")
    if signal_id and signal_id in self._traded_signal_ids:
        print(f"  [STEP 5] REJECT : signal_id deja consomme")
        return None
    print(f"  [STEP 5] OK : signal_id={signal_id}")

    confidence = reg.get("bias_confidence", 0)
    min_conf = 0.40 if prudent else mpt.ENTRY_RULES["min_confidence"]
    if confidence < min_conf:
        print(f"  [STEP 6] REJECT : confidence {confidence} < {min_conf}")
        return None
    mtf_bulls = reg.get("mtf_bulls", 0)
    mtf_bears = reg.get("mtf_bears", 0)
    if direction == "LONG" and mtf_bulls < mpt.ENTRY_RULES["min_mtf_bulls"]:
        print(f"  [STEP 6] REJECT : mtf_bulls {mtf_bulls} < {mpt.ENTRY_RULES['min_mtf_bulls']}")
        return None
    print(f"  [STEP 6] OK : conf={confidence} mtf_bulls={mtf_bulls}")

    bot_data = data.get("bot", {})
    bar_row_dict = bot_data.get("last_bars", {}).get(sym, {})
    if not bar_row_dict:
        bar_row_dict = self._read_last_jsonl_bar(symbol)
    if not bar_row_dict:
        print(f"  [STEP 7] REJECT : bar DMP absente")
        return None
    print(f"  [STEP 7a] Bar loaded, keys count={len(bar_row_dict)}")

    engine = self.sltp_engines[symbol]
    sltp_result = engine.evaluate_single(bar_row_dict, direction_int)
    print(f"  [STEP 7b] SLTPEngine result: valid={sltp_result.valid} sl_ticks={sltp_result.sl_ticks} tp1_ticks={sltp_result.tp1_ticks} reject_reason={getattr(sltp_result, 'reject_reason', 'N/A')}")
    if not sltp_result.valid:
        print(f"  [STEP 7b] REJECT : SLTPEngine invalid")
        return None
    print(f"  [STEP 7b] OK : SL={sltp_result.sl_wall} TP={sltp_result.tp1_wall}")

    sl_ticks = sltp_result.sl_ticks
    tp_ticks = sltp_result.tp1_ticks
    tv = mpt.TICK_VALUE[symbol]
    wr = self._get_dynamic_wr()
    expected_payoff_usd = (wr * tp_ticks - (1 - wr) * sl_ticks) * tv * mpt.ENTRY_RULES["n_micros"]
    print(f"  [STEP 8] wr={wr} tp_t={tp_ticks} sl_t={sl_ticks} exp=${expected_payoff_usd:.2f} (min ${mpt.ENTRY_RULES['min_expected_payoff_usd']})")
    if expected_payoff_usd < mpt.ENTRY_RULES["min_expected_payoff_usd"]:
        print(f"  [STEP 8] REJECT : exp_payoff insuffisant")
        return None
    print(f"  [STEP 8] OK : trade accepte")
    return {"direction": direction, "signal_id": signal_id, "sl_ticks": sl_ticks, "tp_ticks": tp_ticks,
            "entry_price": price, "expected_payoff_usd": expected_payoff_usd}


mpt.PaperTrader.check_entry = check_entry_traced

def make_payload(sym="ES", action="ACHAT", freshness="NEW", conf=0.70, mtf_bulls=3):
    sym_lc = sym.lower()
    price = real_bar_es.get("price") if sym == "ES" else real_bar_nq.get("price")
    other = "nq" if sym_lc == "es" else "es"
    p = {
        "banner": {
            "es": {"price": real_bar_es.get("price"), "ts": int(time.time() * 1000)},
            "nq": {"price": real_bar_nq.get("price"), "ts": int(time.time() * 1000)},
        },
        "conseil_global": {
            sym_lc: {"action": action, "freshness": freshness, "signal_id": f"test_{sym}_{int(time.time())}"},
            other: {"action": "ATTENDRE", "freshness": "IDLE"},
        },
        sym_lc: {"regime": {"bias_confidence": conf, "mtf_bulls": mtf_bulls, "mtf_bears": 0}},
        other: {"regime": {}},
    }
    return p

for sym in ("ES", "NQ"):
    print("\n" + "=" * 70)
    print(f"TEST — pipeline check_entry {sym} avec vraie barre JSONL")
    print("=" * 70)
    trader = mpt.PaperTrader()
    payload = make_payload(sym)
    signal = trader.check_entry(payload, sym)
    print(f"\n>> RESULT {sym}: {'SIGNAL' if signal else 'REJET'}")
    if signal:
        print(f"  direction={signal['direction']} SL={signal['sl_ticks']}t TP={signal['tp_ticks']}t Exp=${signal['expected_payoff_usd']:.2f}")
