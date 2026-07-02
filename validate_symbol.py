"""Run the §6 SMC validation on any symbol's H1 CSV, reusing the VERIFIED
smc_backtest detectors (detector-identity invariant) with per-instrument cost
and an honest cross-symbol DSR trial count.
Usage: python validate_symbol.py <csv> <point> <slip> <n_trials> <split_year>"""
import sys
import numpy as np
sys.path.insert(0, r"C:\Users\Sanique Richards\Documents\Homework Heroes\Pokemon\smc-gold")
import smc_backtest as sb

csv_path = sys.argv[1]
sb.POINT = float(sys.argv[2])
sb.SLIP = float(sys.argv[3])
n_trials = int(sys.argv[4]) if len(sys.argv) > 4 else 8
split_year = int(sys.argv[5]) if len(sys.argv) > 5 else 2023

d = sb.load(csv_path)
a = sb.atr(d['h'], d['l'], d['c'])
sh, sl = sb.swings(d['h'], d['l'])
n = len(d['c'])

def yr(i):
    return int(d['t'][i][:4])

try:
    split = next(i for i in range(n) if yr(i) >= split_year)
except StopIteration:
    split = n // 2

dets = {"OB": sb.det_ob(d, a), "FVG": sb.det_fvg(d, a),
        "BOS": sb.det_bos(d, a, sh, sl), "SWEEP": sb.det_sweep(d, a, sl)}
rng = np.random.default_rng(sb.RNG_SEED)
print("data: %s -> %s  (%d H1 bars)  OOS split @ %s  POINT=%s SLIP=%s N_TRIALS=%d"
      % (d['t'][0], d['t'][-1], n, d['t'][split], sb.POINT, sb.SLIP, n_trials))
print("buy&hold: full %+.1f%%  train %+.1f%%  test %+.1f%%\n"
      % (sb.buyhold(d, 0, n), sb.buyhold(d, 0, split), sb.buyhold(d, split, n)))
for fold, (lo, hi) in [("TRAIN(<%d)" % split_year, (0, split)), ("TEST(>=%d)" % split_year, (split, n))]:
    print("--- %s ---" % fold)
    for nm, sig in dets.items():
        s = [i for i in sig if lo <= i < hi]
        rs = sb.simulate(s, d, a)
        r = sb.report(nm, rs, n_trials)
        if r:
            ctrl = sb.random_control(r['n'], d, a, rng)
            cexp = sum(ctrl) / len(ctrl) if ctrl else 0
            print("%14s |   random expR=%+.3f   edge vs random=%+.3f R" % ("", cexp, r['exp'] - cexp))
    print()
