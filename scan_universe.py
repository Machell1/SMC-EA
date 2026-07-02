"""Scan EVERY tradeable symbol through the ONLY validated methodology (trend-following:
long a confirmed uptrend with momentum). Ranks the cleanest current LONG candidates.
Honest: trend-following is BETA, validated only on gold; on other symbols it's an
unvalidated momentum read. Output is candidates, not endorsed edges."""
import math, sys, json
import MetaTrader5 as mt5
from datetime import datetime, timezone

if not mt5.initialize(path=r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe"):
    if not mt5.initialize():
        raise SystemExit("mt5 init failed: %s" % str(mt5.last_error()))

def sma(x, p):
    out = [float('nan')] * len(x); s = 0.0
    for i in range(len(x)):
        s += x[i]
        if i >= p: s -= x[i - p]
        if i >= p - 1: out[i] = s / p
    return out

def atr(h, l, c, n=14):
    tr = [h[0] - l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    a = [float('nan')] * len(c)
    if len(c) >= n:
        a[n - 1] = sum(tr[:n]) / n
        for i in range(n, len(c)):
            a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a

def adx(h, l, c, p=14):
    n = len(c)
    tr = [0.0] * n; pdm = [0.0] * n; mdm = [0.0] * n
    for i in range(1, n):
        up = h[i] - h[i - 1]; dn = l[i - 1] - l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    pdi = [float('nan')] * n; mdi = [float('nan')] * n; dx = [float('nan')] * n; adxv = [float('nan')] * n
    if n <= 2 * p + 1: return adxv, pdi, mdi
    trs = sum(tr[1:p + 1]); ps = sum(pdm[1:p + 1]); ms = sum(mdm[1:p + 1])
    for i in range(p + 1, n):
        trs += tr[i] - trs / p; ps += pdm[i] - ps / p; ms += mdm[i] - ms / p
        if trs > 0:
            pdi[i] = 100 * ps / trs; mdi[i] = 100 * ms / trs
            den = pdi[i] + mdi[i]
            dx[i] = 100 * abs(pdi[i] - mdi[i]) / den if den > 0 else 0.0
    first = 2 * p + 1
    seed = sum(v for v in dx[p + 1:first] if not math.isnan(v)) / p
    adxv[first - 1] = seed
    for i in range(first, n):
        if not math.isnan(dx[i]):
            adxv[i] = (adxv[i - 1] * (p - 1) + dx[i]) / p
    return adxv, pdi, mdi

def is_synth(name, desc):
    u = (name + " " + desc).upper()
    return any(k in u for k in ("VOLATILITY", "BOOM", "CRASH", "JUMP", "STEP", "RANGE BREAK", "DRIFT", "SYNTHETIC", "VOL ", "DEX ", "MULTI STEP"))

rows = []
for s in mt5.symbols_get():
    name = s.name
    if not mt5.symbol_select(name, True):
        continue
    r = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H1, 0, 260)
    if r is None or len(r) < 220:
        continue
    h = [float(x['high']) for x in r]; l = [float(x['low']) for x in r]; c = [float(x['close']) for x in r]
    a = atr(h, l, c); s200 = sma(c, 200); s20 = sma(c, 20)
    adxv, pdi, mdi = adx(h, l, c)
    i = len(c) - 2
    if math.isnan(s200[i]) or math.isnan(adxv[i]) or math.isnan(a[i]) or a[i] <= 0:
        continue
    px = c[i]
    up = px > s200[i]; rising = s200[i] > s200[i - 20]
    av = adxv[i]; diup = pdi[i] > mdi[i]
    don_hi = max(c[i - 19:i + 1])
    breakout = px >= don_hi and px > s20[i]
    pct = (px - s200[i]) / s200[i] * 100.0
    if up and rising and av > 20 and diup:
        regime = "UP"
    elif (not up) and (s200[i] < s200[i - 20]) and av > 20 and (not diup):
        regime = "DOWN"
    else:
        regime = "RANGE"
    fresh_long = up and rising and av > 20 and diup and breakout
    score = pct + av * 0.1 + (8 if fresh_long else 0) + (3 if (up and breakout) else 0)
    rows.append(dict(name=name, synth=is_synth(name, s.description), regime=regime, score=score, up=up, adx=av,
                     diup=diup, pct=pct, fresh=fresh_long, breakout=breakout, px=px,
                     entry=px, stop=px - 1.5 * a[i], atr=a[i], digits=s.digits,
                     vmin=s.volume_min, tv=s.trade_tick_value, ts=(s.trade_tick_size or s.point)))

ai = mt5.account_info(); eq = ai.equity if ai else 0.0
print("scanned %d symbols  | equity $%.2f  | %s UTC" % (len(rows), eq, datetime.now(timezone.utc).strftime("%H:%M")))

def riskline(rw):
    sl_dist = rw['entry'] - rw['stop']
    rl = (sl_dist / rw['ts']) * rw['tv'] if rw['ts'] > 0 and rw['tv'] > 0 else 0
    rmin = rl * rw['vmin']
    pctrisk = (rmin / eq * 100) if eq > 0 else 0
    return rmin, pctrisk

def show(rw):
    rm, pr = riskline(rw)
    d = rw['digits']
    f = "%." + str(d) + "f"
    tag = "SYNTH" if rw['synth'] else "real "
    print("  %-16s %s regime=%-5s adx=%4.1f  %+6.2f%% vs SMA200  px=%s  | entry %s stop %s  minlot %.2f risk $%.2f (%.1f%%)"
          % (rw['name'], tag, rw['regime'], rw['adx'], rw['pct'], f % rw['px'], f % rw['entry'], f % rw['stop'], rw['vmin'], rm, pr))

fresh = sorted([r for r in rows if r['fresh']], key=lambda x: -x['score'])
ups = sorted([r for r in rows if r['regime'] == "UP"], key=lambda x: -x['score'])

print("\n=== FRESH LONG BREAKOUTS (uptrend + ADX>20 + new 20-bar high = trend harness would ENTER now) ===")
if fresh:
    for rw in fresh[:12]:
        show(rw)
else:
    print("  none right now (no symbol is breaking out to a new high inside a confirmed uptrend)")

print("\n=== STRONGEST CONFIRMED UPTRENDS (no fresh breakout yet — buy a pullback that resumes) ===")
for rw in ups[:12]:
    show(rw)

print("\n=== regime tally ===")
tal = {}
for r in rows:
    tal[r['regime']] = tal.get(r['regime'], 0) + 1
print(" ", tal)

# machine-readable output for the opportunity-scanner alert task
if "--json" in sys.argv:
    jp = sys.argv[sys.argv.index("--json") + 1]
    out = []
    for r in sorted([x for x in rows if x['regime'] == "UP"], key=lambda x: -x['score']):
        rm, pr = riskline(r)
        out.append({"name": r['name'], "synth": r['synth'], "adx": round(r['adx'], 1),
                    "pct": round(r['pct'], 1), "fresh": r['fresh'],
                    "entry": round(r['entry'], r['digits']), "stop": round(r['stop'], r['digits']),
                    "minlot": r['vmin'], "risk_usd": round(rm, 2), "risk_pct": round(pr, 1)})
    with open(jp, "w") as f:
        json.dump({"ts": int(datetime.now(timezone.utc).timestamp()), "equity": eq, "candidates": out}, f)
    print("WROTE json %s (%d UP candidates)" % (jp, len(out)))
