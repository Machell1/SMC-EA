"""Head-to-head on XAUUSD H1, LONG-only, uptrend regime (price > SMA200):
three ENTRY triggers x two EXIT frameworks, each vs a regime-matched RANDOM control.

  entries : SMC (FVG, and OB+FVG+BOS union)  |  trend-pullback (dip to SMA20 + resume)  |  random
  exits   : fixed (1.5*ATR SL, 2:1 TP, 24-bar)  |  BE@+1R then trail 3*ATR (gold-desk §2)
  control : random entries in the SAME uptrend, through the SAME exit, matched count.

Whatever BEATS random-in-trend is a real ENTRY edge; whatever TIES random is just the trend (beta).
Textbook params only. No lookahead (signal at close i, enter open i+1, stop checked before trail update).
Usage: python head_to_head.py <csv> <point> <slip> <split_year> <n_trials>"""
import sys, math
import numpy as np
sys.path.insert(0, r"C:\Users\Sanique Richards\Documents\Homework Heroes\Pokemon\smc-gold")
import smc_backtest as sb

csv_path = sys.argv[1]
sb.POINT = float(sys.argv[2]); sb.SLIP = float(sys.argv[3])
split_year = int(sys.argv[4]) if len(sys.argv) > 4 else 2023
N_TRIALS = int(sys.argv[5]) if len(sys.argv) > 5 else 64

d = sb.load(csv_path)
o, h, l, c, sp = d['o'], d['h'], d['l'], d['c'], d['sp']
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

s200 = sma(c, 200); s20 = sma(c, 20)

def up(i):
    return (not math.isnan(s200[i])) and c[i] > s200[i]

def simulate_trail(sig, d, a, sl_atr=1.5, trail_atr=3.0, max_hold=48):
    out = []; last_exit = -1
    for i in sig:
        e = i + 1
        if e >= n or math.isnan(a[i]) or e <= last_exit:
            continue
        cost = sp[e] * sb.POINT / 2.0 + sb.SLIP
        entry = o[e] + cost
        risk = sl_atr * a[i]
        if risk <= 0:
            continue
        stop = entry - risk; be = False; hw = entry; exit_px = None; last_j = e
        j = e
        while j < min(e + max_hold, n):
            if l[j] <= stop:                       # stop in force coming into bar j (no lookahead)
                exit_px = stop; break
            if h[j] > hw: hw = h[j]
            if not be and h[j] >= entry + risk:
                stop = max(stop, entry); be = True
            if be:
                stop = max(stop, hw - trail_atr * a[i])
            last_j = j; j += 1
        if exit_px is None:
            exit_px = c[last_j]
        exit_px -= cost
        out.append((exit_px - entry) / risk)
        last_exit = j
    return out

def pullback(d, a):
    sig = []
    for i in range(200, n - 1):
        if math.isnan(s200[i]) or math.isnan(s20[i]):
            continue
        if c[i] > s200[i] and l[i] <= s20[i] and c[i] > s20[i] and c[i] > o[i]:
            sig.append(i)
    return sig

# entries (filtered to uptrend)
fvg = [i for i in sb.det_fvg(d, a) if up(i)]
smc_any = sorted(set(i for i in (sb.det_ob(d, a) + sb.det_fvg(d, a) + sb.det_bos(d, a, sh, sl)) if up(i)))
pbk = pullback(d, a)
ENTRIES = [("SMC-FVG", fvg), ("SMC-any", smc_any), ("trend-pullback", pbk)]
EXITS = [("fixed 2:1", lambda s: sb.simulate(s, d, a)), ("BE+trail", lambda s: simulate_trail(s, d, a))]

def yr(i): return int(d['t'][i][:4])
split = next(i for i in range(n) if yr(i) >= split_year)
rng = np.random.default_rng(sb.RNG_SEED)

def rand_ctrl(count, exit_fn):
    valid = [i for i in range(200, n - 2) if not math.isnan(a[i]) and up(i)]
    if not valid:
        return []
    picks = sorted(int(x) for x in rng.choice(valid, size=min(count, len(valid)), replace=False))
    return exit_fn(picks)

print("XAUUSD %s -> %s  %d bars  split@%s  (LONG, uptrend price>SMA200)  N_TRIALS=%d"
      % (d['t'][0][:10], d['t'][-1][:10], n, d['t'][split][:10], N_TRIALS))
print("buy&hold: full %+.1f%%  train %+.1f%%  test %+.1f%%" % (sb.buyhold(d, 0, n), sb.buyhold(d, 0, split), sb.buyhold(d, split, n)))
for ename, esig in ENTRIES:
    for xname, xfn in EXITS:
        print("\n=== ENTRY %-14s  EXIT %-9s ===" % (ename, xname))
        for fold, (lo, hi) in [("TRAIN", (0, split)), ("TEST", (split, n))]:
            s = [i for i in esig if lo <= i < hi]
            rs = xfn(s)
            if not rs:
                print("  %-5s no trades" % fold); continue
            exp = sum(rs) / len(rs); wr = 100 * sum(1 for r in rs if r > 0) / len(rs)
            srp = sb.sharpe(rs); ds = sb.dsr(srp, N_TRIALS, len(rs))
            ctrl = rand_ctrl(len(rs), xfn)
            cexp = (sum(ctrl) / len(ctrl)) if ctrl else 0.0
            print("  %-5s n=%4d win%%=%4.1f expR=%+.3f totR=%+6.1f DSR=%.2f | rand=%+.3f edge=%+.3f"
                  % (fold, len(rs), wr, exp, sum(rs), ds, cexp, exp - cexp))
print("\nReal entry edge = beats random-in-trend (edge>0) in BOTH folds, DSR>=0.95. Tie with random = just the trend.")
