"""Numpy-free trend-harness validation (avoids the OpenBLAS memory issue).
Same logic as trend_harness.py: long>SMA200, Donchian-20 breakout entry, BE+3xATR trail.
Usage: python trend_val.py <csv> <point> <slip> <split_year>"""
import sys, csv, math

csv_path = sys.argv[1]
POINT = float(sys.argv[2]); SLIP = float(sys.argv[3])
split_year = int(sys.argv[4]) if len(sys.argv) > 4 else 2025
SL_ATR, TRAIL_ATR, DON = 1.5, 3.0, 20
nan = float('nan')

t = []; o = []; h = []; l = []; c = []; sp = []
with open(csv_path, newline="") as f:
    for r in csv.DictReader(f):
        t.append(r["time"]); o.append(float(r["open"])); h.append(float(r["high"]))
        l.append(float(r["low"])); c.append(float(r["close"])); sp.append(float(r.get("spread", 0) or 0))
n = len(c)

def atr(n_=14):
    tr = [h[0] - l[0]]
    for i in range(1, n):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    a = [nan] * n
    if n >= n_:
        a[n_ - 1] = sum(tr[:n_]) / n_
        for i in range(n_, n):
            a[i] = (a[i - 1] * (n_ - 1) + tr[i]) / n_
    return a

def sma(p):
    out = [nan] * n; s = 0.0
    for i in range(n):
        s += c[i]
        if i >= p: s -= c[i - p]
        if i >= p - 1: out[i] = s / p
    return out

a = atr(); s200 = sma(200); s20 = sma(20)
trades = []; pos = None
for i in range(200, n - 1):
    if math.isnan(a[i]) or math.isnan(s200[i]) or math.isnan(s20[i]):
        continue
    if pos is None:
        if c[i] > s200[i] and c[i] > s20[i] and c[i] >= max(c[i - DON + 1:i + 1]):
            e = i + 1; cost = sp[e] * POINT / 2.0 + SLIP
            entry = o[e] + cost; risk = SL_ATR * a[i]
            if risk <= 0: continue
            pos = {"e": e, "entry": entry, "risk": risk, "stop": entry - risk, "hw": entry, "sig": i}
    else:
        p = pos
        if l[i] <= p["stop"]:
            trades.append((p["e"], i, (p["stop"] - cost - p["entry"]) / p["risk"], int(t[p["e"]][:4]))); pos = None; continue
        if c[i] < s200[i]:
            trades.append((p["e"], i, (c[i] - cost - p["entry"]) / p["risk"], int(t[p["e"]][:4]))); pos = None; continue
        p["hw"] = max(p["hw"], h[i])
        if h[i] >= p["entry"] + p["risk"]: p["stop"] = max(p["stop"], p["entry"])
        p["stop"] = max(p["stop"], p["hw"] - TRAIL_ATR * a[p["sig"]])

def sharpe(rs):
    if len(rs) < 2: return 0.0
    m = sum(rs) / len(rs); var = sum((x - m) ** 2 for x in rs) / len(rs)
    sd = math.sqrt(var)
    return (m / sd * math.sqrt(len(rs))) if sd > 0 else 0.0

def maxdd(curve):
    peak = curve[0] if curve else 0; mdd = 0
    for v in curve:
        peak = max(peak, v); mdd = min(mdd, v - peak)
    return mdd

def bh(lo, hi): return 100 * (c[hi - 1] - c[lo]) / c[lo]
def bh_dd(lo, hi):
    peak = c[lo]; mdd = 0
    for i in range(lo, hi):
        peak = max(peak, c[i]); mdd = min(mdd, (c[i] - peak) / peak * 100)
    return mdd

split = next((i for i in range(n) if int(t[i][:4]) >= split_year), n // 2)
print("Cocoa %s -> %s  %d H1 bars  split@%s  [long>SMA200 + Don%d, BE+%gxATR trail]"
      % (t[0][:10], t[-1][:10], n, t[split][:10], DON, TRAIL_ATR))

def fold(name, lo, hi):
    sub = [x for x in trades if lo <= x[0] < hi]; rs = [x[2] for x in sub]
    if not rs:
        print("  %-6s no trades" % name); return
    exp = sum(rs) / len(rs); wr = 100 * sum(1 for r in rs if r > 0) / len(rs)
    cum = []; s = 0
    for r in rs: s += r; cum.append(s)
    eq = 1.0; ec = [1.0]
    for r in rs: eq *= (1 + 0.01 * r); ec.append(eq)
    print("  %-6s n=%3d win%%=%4.1f expR=%+.3f totR=%+6.1f Sharpe=%+.2f maxDD=%.1fR | sys %+.1f%% (DD %.1f%%) vs B&H %+.1f%% (DD %.1f%%)"
          % (name, len(rs), wr, exp, sum(rs), sharpe(rs), maxdd(cum), (eq - 1) * 100,
             maxdd(ec) / (max(ec) if ec else 1) * 100, bh(lo, hi), bh_dd(lo, hi)))

fold("FULL", 0, n); fold("TRAIN", 0, split); fold("TEST", split, n)
by = {}
for x in trades: by.setdefault(x[3], []).append(x[2])
print("  per-year totR:", {y: round(sum(v), 1) for y, v in sorted(by.items())},
      " positive:", sum(1 for v in by.values() if sum(v) > 0), "/", len(by))
