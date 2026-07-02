"""§6 validation WITH a regime filter (block ranging markets), tested honestly:
the SAME trend filter is applied to the SMC entries AND the random-entry control,
so 'edge vs random' answers the real question -- does the SMC ENTRY beat a random
entry taken in the SAME trending regime? Textbook params only (SMA200, ADX>20).
Usage: python validate_filtered.py <csv> <point> <slip> <split_year> <n_trials>"""
import sys, math
import numpy as np
sys.path.insert(0, r"C:\Users\Sanique Richards\Documents\Homework Heroes\Pokemon\smc-gold")
import smc_backtest as sb

csv_path = sys.argv[1]
sb.POINT = float(sys.argv[2])
sb.SLIP = float(sys.argv[3])
split_year = int(sys.argv[4]) if len(sys.argv) > 4 else 2023
N_TRIALS = int(sys.argv[5]) if len(sys.argv) > 5 else 64   # big: penalize the filter search

d = sb.load(csv_path)
h, l, c = d['h'], d['l'], d['c']
n = len(c)
a = sb.atr(h, l, c)
sh, sl = sb.swings(h, l)
nan = float('nan')

def sma(x, p):
    out = [nan] * len(x); s = 0.0
    for i in range(len(x)):
        s += x[i]
        if i >= p: s -= x[i - p]
        if i >= p - 1: out[i] = s / p
    return out

def adx(h, l, c, p=14):
    tr = [0.0] * n; pdm = [0.0] * n; mdm = [0.0] * n
    for i in range(1, n):
        up = h[i] - h[i - 1]; dn = l[i - 1] - l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    pdi = [nan] * n; mdi = [nan] * n; dx = [nan] * n; adxv = [nan] * n
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

s200 = sma(c, 200)
s50 = sma(c, 50)
adxv, pdi, mdi = adx(h, l, c)

def f_none(i): return True
def f_sma(i):  return (not math.isnan(s200[i])) and c[i] > s200[i]          # uptrend (longs)
def f_gx(i):   return (not math.isnan(s200[i])) and (not math.isnan(s50[i])) and s50[i] > s200[i]
def f_adx(i):  return (not math.isnan(adxv[i])) and adxv[i] > 20 and (not math.isnan(pdi[i])) and pdi[i] > mdi[i]
def f_trend(i):return f_sma(i) and (not math.isnan(adxv[i])) and adxv[i] > 20  # SMA200 up + real trend

FILTERS = [("no-filter", f_none), ("SMA200-up", f_sma), ("50>200", f_gx), ("ADX>20+DI", f_adx), ("trend(SMA+ADX)", f_trend)]
dets = {"OB": sb.det_ob(d, a), "FVG": sb.det_fvg(d, a), "BOS": sb.det_bos(d, a, sh, sl), "SWEEP": sb.det_sweep(d, a, sl)}

def yr(i): return int(d['t'][i][:4])
try:
    split = next(i for i in range(n) if yr(i) >= split_year)
except StopIteration:
    split = n // 2

print("data %s -> %s  (%d bars)  split @%s  POINT=%s SLIP=%s N_TRIALS=%d"
      % (d['t'][0][:10], d['t'][-1][:10], n, d['t'][split][:10], sb.POINT, sb.SLIP, N_TRIALS))
print("buy&hold: full %+.1f%%  train %+.1f%%  test %+.1f%%" % (sb.buyhold(d, 0, n), sb.buyhold(d, 0, split), sb.buyhold(d, split, n)))
rng = np.random.default_rng(sb.RNG_SEED)
for fname, filt in FILTERS:
    print("\n================= FILTER: %s =================" % fname)
    for fold, (lo, hi) in [("TRAIN", (0, split)), ("TEST", (split, n))]:
        line = "  %-5s " % fold
        for nm, sig in dets.items():
            s = [i for i in sig if lo <= i < hi]
            rs = sb.simulate(s, d, a, htrend=filt)
            if not rs:
                line += " %s:n0" % nm; continue
            exp = sum(rs) / len(rs); srp = sb.sharpe(rs); ds = sb.dsr(srp, N_TRIALS, len(rs))
            ctrl = sb.random_control(len(rs), d, a, rng, htrend=filt)
            cexp = (sum(ctrl) / len(ctrl)) if ctrl else 0.0
            line += "  %s:n%d exp%+.3f DSR%.2f edge%+.3f" % (nm, len(rs), exp, ds, exp - cexp)
        print(line)
print("\nPASS needs: BOTH folds positive AND edge-vs-random>0 AND DSR>=0.95 (same filter on the control).")
