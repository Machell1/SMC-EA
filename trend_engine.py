"""TREND HARNESS — live state engine (validated 'dumb beta' on gold).
Long-only: regime = close>SMA200(H1); entry = new Donchian-20 high in uptrend & >SMA20;
exit = BE@+1R then 3xATR chandelier trail, OR regime flip close<SMA200.

It REPLAYS the deterministic backtest over freshly-fetched H1 history each run, so the
CURRENT state (FLAT / LONG + entry + trailing stop) is always consistent with the backtest
with NO persisted-state drift. It writes trend_signal_<SYM>.json and prints a status line.
It is READ-ONLY: it never places orders. The operator / their EA executes if they choose.
Usage: python trend_engine.py <SYMBOL> <out_dir> [point] [slip] [bars]"""
import sys, math, json, os
import MetaTrader5 as mt5
from datetime import datetime, timezone
sys.path.insert(0, r"C:\Users\Sanique Richards\Documents\Homework Heroes\Pokemon\smc-gold")
import smc_backtest as sb

SYM = sys.argv[1]
OUT = sys.argv[2]
POINT = float(sys.argv[3]) if len(sys.argv) > 3 else 0.01
SLIP = float(sys.argv[4]) if len(sys.argv) > 4 else 0.05
BARS = int(sys.argv[5]) if len(sys.argv) > 5 else 2200
VALNOTE = sys.argv[6] if len(sys.argv) > 6 else "PASS-gold (9/9 yrs, DSR1.00, both folds; BETA, gold-specific)"
SL_ATR, TRAIL_ATR, DON = 1.5, 3.0, 20

if not mt5.initialize(path=r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe"):
    if not mt5.initialize():
        raise SystemExit("mt5 init failed: %s" % str(mt5.last_error()))
mt5.symbol_select(SYM, True)
rates = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 0, BARS)
if rates is None or len(rates) < 250:
    raise SystemExit("insufficient H1 for %s" % SYM)

t = [datetime.fromtimestamp(int(r["time"]), timezone.utc) for r in rates]
o = [float(r["open"]) for r in rates]; h = [float(r["high"]) for r in rates]
l = [float(r["low"]) for r in rates]; c = [float(r["close"]) for r in rates]
sp = [float(r["spread"]) for r in rates]
d = dict(t=[x.strftime("%Y-%m-%d %H:%M:%S") for x in t], o=o, h=h, l=l, c=c, sp=sp)
n = len(c)
a = sb.atr(h, l, c)

def sma(x, p):
    out = [float('nan')] * len(x); s = 0.0
    for i in range(len(x)):
        s += x[i]
        if i >= p: s -= x[i - p]
        if i >= p - 1: out[i] = s / p
    return out

s200, s20 = sma(c, 200), sma(c, 20)
last = n - 2  # last fully CLOSED H1 bar (n-1 is the forming bar)

# replay the deterministic position sim up to `last`
pos = None
for i in range(200, last + 1):
    if math.isnan(a[i]) or math.isnan(s200[i]) or math.isnan(s20[i]):
        continue
    if pos is None:
        if c[i] > s200[i] and c[i] > s20[i] and c[i] >= max(c[i - DON + 1:i + 1]):
            e = i + 1
            if e > last:
                break
            cost = sp[e] * POINT / 2.0 + SLIP
            entry = o[e] + cost
            risk = SL_ATR * a[i]
            if risk <= 0:
                continue
            pos = {"e": e, "entry": entry, "risk": risk, "stop": entry - risk, "hw": entry, "sig": i}
    else:
        p = pos
        if l[i] <= p["stop"]:
            pos = None; continue
        if c[i] < s200[i]:
            pos = None; continue
        p["hw"] = max(p["hw"], h[i])
        if h[i] >= p["entry"] + p["risk"]:
            p["stop"] = max(p["stop"], p["entry"])
        p["stop"] = max(p["stop"], p["hw"] - TRAIL_ATR * a[p["sig"]])

price = c[-1]
regime = "UPTREND" if c[last] > s200[last] else ("DOWN/RANGE" if c[last] <= s200[last] else "?")
don_high = max(c[last - DON + 1:last + 1])
if pos is not None:
    state = "LONG"
    entry = round(pos["entry"], 2); stop = round(pos["stop"], 2)
    rmult = round((price - pos["entry"]) / pos["risk"], 2)
    note = "in long, trailing stop %.2f (open %+.2fR)" % (stop, rmult)
else:
    entry = stop = 0.0; rmult = 0.0
    if regime == "UPTREND":
        state = "ARMED"  # waiting for a new Donchian-20 high
        note = "uptrend; arms on H1 close > %.2f (Donchian-20 high)" % don_high
    else:
        state = "FLAT"
        note = "regime down/range (price %.2f < SMA200 %.2f); stand aside" % (price, s200[last])

# ---- position sizing for path-A manual/EA execution (1% risk, min-lot reality flagged) ----
equity = lot = risk_usd = risk_pct = sl_dist = plan_entry = plan_stop = 0.0
min_lot_floor = False
ai = mt5.account_info()
if ai:
    equity = float(ai.equity)
if state == "LONG":
    plan_entry, plan_stop = pos["entry"], pos["stop"]
elif state == "ARMED":
    plan_entry = don_high
    plan_stop = don_high - SL_ATR * a[last]
info = mt5.symbol_info(SYM)
if plan_entry > 0 and plan_stop > 0 and plan_entry > plan_stop and info and equity > 0:
    sl_dist = plan_entry - plan_stop
    ts = info.trade_tick_size or info.point
    tv = info.trade_tick_value
    if ts > 0 and tv > 0:
        risk_per_lot = (sl_dist / ts) * tv
        vmin = info.volume_min or 0.01
        vstep = info.volume_step or 0.01
        if risk_per_lot > 0:
            steps = math.floor((0.01 * equity) / risk_per_lot / vstep)
            lot = max(vmin, steps * vstep)
            risk_usd = risk_per_lot * lot
            risk_pct = risk_usd / equity * 100.0
            min_lot_floor = (lot <= vmin + 1e-9) and (risk_pct > 1.5)

# flip detection for the alerter
ss_p = os.path.join(OUT, "trend_sigstate_%s.json" % SYM)
prev_state, flip_seq = "", 0
try:
    with open(ss_p, encoding="utf-8") as f:
        _s = json.load(f); prev_state = _s.get("state", ""); flip_seq = int(_s.get("flip_seq", 0))
except (OSError, ValueError):
    pass
flipped = bool(prev_state) and prev_state != state and {prev_state, state} != {"FLAT", "ARMED"}
if flipped:
    flip_seq += 1

sig = {"ts": int(datetime.now(timezone.utc).timestamp()), "symbol": SYM, "strategy": "trend-harness",
       "validation": VALNOTE,
       "regime": regime, "state": state, "price": round(price, 2),
       "sma200": round(s200[last], 2), "don20_high": round(don_high, 2),
       "entry": entry, "stop": stop, "open_R": rmult,
       "plan_entry": round(plan_entry, 2), "plan_stop": round(plan_stop, 2), "sl_dist": round(sl_dist, 2),
       "equity": round(equity, 2), "lot": round(lot, 2), "risk_usd": round(risk_usd, 2),
       "risk_pct": round(risk_pct, 2), "min_lot_floor": min_lot_floor,
       "flip_seq": flip_seq, "flipped": flipped, "note": note}
with open(os.path.join(OUT, "trend_signal_%s.json" % SYM), "w", encoding="utf-8") as f:
    json.dump(sig, f)
with open(ss_p, "w", encoding="utf-8") as f:
    json.dump({"state": state, "flip_seq": flip_seq}, f)

print("TREND %s  regime=%s  state=%s  price=%.2f  SMA200=%.2f  don20=%.2f  flip_seq=%d"
      % (SYM, regime, state, price, s200[last], don_high, flip_seq))
print("  ", note)
if plan_entry > 0:
    print("  PLAN: entry %.2f  stop %.2f  (SL %.2f)  -> lot %.2f  risk $%.2f (%.1f%% of $%.2f)%s"
          % (plan_entry, plan_stop, sl_dist, lot, risk_usd, risk_pct, equity,
             "  [MIN-LOT FLOOR: risk>1%]" if min_lot_floor else ""))
