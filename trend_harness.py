"""Validate the 'dumb beta' trend harness, long-only:
  REGIME : long-eligible only when close > SMA200 (confirmed uptrend)
  ENTRY  : flat + uptrend + close is a new <DON>-bar high + close > SMA20  (momentum, avoids churn)
  EXIT   : initial stop entry-1.5*ATR; BE@+1R; chandelier trail highHigh-3*ATR; OR regime flip close<SMA200
  long only, one position, real costs (spread+slip), no lookahead.

Reports per-fold: trades, win%, expectancy R, total R, Sharpe, DSR, maxDD(R), time-in-market,
and the DEFENSIVE test: system return & maxDD (1% risk/trade) vs BUY&HOLD return & maxDD.
Usage: python trend_harness.py <csv> <point> <slip> <split_year> <n_trials>"""
import sys, math
import numpy as np
sys.path.insert(0, r"C:\Users\Sanique Richards\Documents\Homework Heroes\Pokemon\smc-gold")
import smc_backtest as sb

csv_path = sys.argv[1]
POINT = float(sys.argv[2]); SLIP = float(sys.argv[3])
split_year = int(sys.argv[4]) if len(sys.argv) > 4 else 2023
N_TRIALS = int(sys.argv[5]) if len(sys.argv) > 5 else 64
SL_ATR, TRAIL_ATR, DON = 1.5, 3.0, 20

d = sb.load(csv_path)
o, h, l, c, sp = d['o'], d['h'], d['l'], d['c'], d['sp']
n = len(c)
a = sb.atr(h, l, c)
nan = float('nan')

def sma(x, p):
    out = [nan] * len(x); s = 0.0
    for i in range(len(x)):
        s += x[i]
        if i >= p: s -= x[i - p]
        if i >= p - 1: out[i] = s / p
    return out

s200, s20 = sma(c, 200), sma(c, 20)

trades = []          # (entry_bar, exit_bar, R, entry_year)
pos = None
for i in range(200, n - 1):
    if math.isnan(a[i]) or math.isnan(s200[i]) or math.isnan(s20[i]):
        continue
    if pos is None:
        if c[i] > s200[i] and c[i] > s20[i] and c[i] >= max(c[i - DON + 1:i + 1]):
            e = i + 1
            cost = sp[e] * POINT / 2.0 + SLIP
            entry = o[e] + cost
            risk = SL_ATR * a[i]
            if risk <= 0:
                continue
            pos = {"e": e, "entry": entry, "risk": risk, "stop": entry - risk, "hw": entry, "sig": i, "cost": cost}
    else:
        p = pos
        if l[i] <= p["stop"]:                              # stop set last bar (no lookahead)
            r = (p["stop"] - p["cost"] - p["entry"]) / p["risk"]
            trades.append((p["e"], i, r, int(d['t'][p["e"]][:4]))); pos = None; continue
        if c[i] < s200[i]:                                 # regime flip -> exit at close
            r = (c[i] - p["cost"] - p["entry"]) / p["risk"]
            trades.append((p["e"], i, r, int(d['t'][p["e"]][:4]))); pos = None; continue
        p["hw"] = max(p["hw"], h[i])
        if h[i] >= p["entry"] + p["risk"]:
            p["stop"] = max(p["stop"], p["entry"])
        p["stop"] = max(p["stop"], p["hw"] - TRAIL_ATR * a[p["sig"]])

def yr(i): return int(d['t'][i][:4])
split = next(i for i in range(n) if yr(i) >= split_year)

def maxdd(curve):
    peak = curve[0] if curve else 0; mdd = 0
    for v in curve:
        peak = max(peak, v); mdd = min(mdd, v - peak)
    return mdd

def bh_maxdd_pct(lo, hi):
    peak = c[lo]; mdd = 0
    for i in range(lo, hi):
        peak = max(peak, c[i]); mdd = min(mdd, (c[i] - peak) / peak * 100)
    return mdd

def report(rs_trades, lo, hi, label):
    sub = [t for t in rs_trades if lo <= t[0] < hi]
    rs = [t[2] for t in sub]
    if not rs:
        print("  %-6s no trades" % label); return
    exp = sum(rs) / len(rs); wr = 100 * sum(1 for r in rs if r > 0) / len(rs)
    srp = sb.sharpe(rs); ds = sb.dsr(srp, N_TRIALS, len(rs))
    cum = []; s = 0
    for r in rs:
        s += r; cum.append(s)
    ddR = maxdd(cum)
    bars_in = sum(t[1] - t[0] for t in sub); tim = 100 * bars_in / (hi - lo)
    # 1% risk/trade compounding equity
    eq = 1.0; ec = [1.0]
    for r in rs:
        eq *= (1 + 0.01 * r); ec.append(eq)
    sys_ret = (eq - 1) * 100
    sys_dd = maxdd(ec) / (max(ec) if ec else 1) * 100
    bh = sb.buyhold(d, lo, hi); bh_dd = bh_maxdd_pct(lo, hi)
    print("  %-6s n=%3d win%%=%4.1f expR=%+.3f totR=%+6.1f Sharpe=%+.2f DSR=%.2f maxDD=%.1fR TiM=%4.1f%%"
          % (label, len(rs), wr, exp, sum(rs), srp, ds, ddR, tim))
    print("         DEFENSIVE: system %+.1f%% (maxDD %.1f%%, 1%%/trade)  vs  buy&hold %+.1f%% (maxDD %.1f%%)"
          % (sys_ret, sys_dd, bh, bh_dd))

print("=== %s ===  %s -> %s  %d bars  split@%s  N_TRIALS=%d  [long>SMA200, Don%d entry, BE+%gxATR trail]"
      % (csv_path.split('\\')[-1], d['t'][0][:10], d['t'][-1][:10], n, d['t'][split][:10], N_TRIALS, DON, TRAIL_ATR))
report(trades, 0, n, "FULL")
report(trades, 0, split, "TRAIN")
report(trades, split, n, "TEST")
by = {}
for t in trades:
    by.setdefault(t[3], []).append(t[2])
print("  per-year totR:", {y: round(sum(v), 1) for y, v in sorted(by.items())})
pos_y = sum(1 for y, v in by.items() if sum(v) > 0)
print("  positive years: %d/%d" % (pos_y, len(by)))
