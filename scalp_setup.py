"""Find the best near-price SCALP SHORT setup on gold (M5 entry, M15 context).
Reuses the smc_map detectors (pure-python). Honest: no validated edge; scalp = discretionary."""
import sys
sys.path.insert(0, r"C:\Users\Sanique Richards\Documents\Homework Heroes\Pokemon\smc-command-desk")
import smc_map as sm

SYM = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
_p = sm.load_live(SYM, "M5", 5)        # initializes mt5 connection
price = sm.live_price(SYM)
if price <= 0:
    price = _p[4][-1]                  # fall back to last M5 close

def analyze(tf, n):
    t, o, h, l, c, sp = sm.load_live(SYM, tf, n)
    a = sm.atr(h, l, c)
    sh, sl = sm.swings(h, l)
    atr_tf = a[-1]
    spread = sp[-1]
    # resistance ABOVE price (where to short a rejection): supply OBs, bear FVGs, EQH
    res = []
    for (i, lo, hi) in sm.bear_obs(o, h, l, c, a, price, maxn=4):
        if lo > price:
            res.append((lo, hi, "supply OB"))
    for (i, glo, ghi) in sm.bear_fvgs(h, l, c, a, maxn=4):
        if glo > price:
            res.append((glo, ghi, "bear FVG"))
    eqh = sm.eq_pool(sh, h, a, price, "high")
    if eqh and eqh[1] > price:
        res.append((eqh[1], eqh[1], "EQH buy-side liq"))
    # nearest swing high above
    sh_above = sorted([h[i] for i in sh if h[i] > price])
    if sh_above:
        res.append((sh_above[0], sh_above[0], "swing high"))
    res = sorted(res, key=lambda x: x[0])
    # support BELOW price (target): demand OBs, bull FVGs, EQL, swing lows
    sup = []
    for (i, lo, hi) in sm.bull_obs(o, h, l, c, a, price, maxn=4):
        if hi < price:
            sup.append((hi, lo, "demand OB"))
    eql = sm.eq_pool(sl, l, a, price, "low")
    if eql and eql[1] < price:
        sup.append((eql[1], eql[1], "EQL sell-side liq"))
    sl_below = sorted([l[i] for i in sl if l[i] < price], reverse=True)
    for x in sl_below[:3]:
        sup.append((x, x, "swing low"))
    sup = sorted(sup, key=lambda x: -x[0])  # nearest below first
    return atr_tf, spread, res, sup

price5_atr, spread5, res5, sup5 = analyze("M5", 360)
price15_atr, spread15, res15, sup15 = analyze("M15", 300)

print("=== GOLD SCALP SHORT — live near price %.2f ===" % price)
print("M5 ATR=%.2f  M15 ATR=%.2f  spread=%.0f pts (~$%.2f round-trip)" % (price5_atr, price15_atr, spread5, spread5 * 0.01))
print("\nRESISTANCE above price (short a rejection here):")
for lo, hi, kind in res5[:4]:
    print("  M5  %-16s %.2f - %.2f  (%+.1f pts away)" % (kind, lo, hi, lo - price))
for lo, hi, kind in res15[:3]:
    print("  M15 %-16s %.2f - %.2f  (%+.1f pts away)" % (kind, lo, hi, lo - price))
print("\nSUPPORT below price (scalp target):")
for top, bot, kind in sup5[:4]:
    print("  M5  %-16s %.2f  (%+.1f pts away)" % (kind, top, top - price))

# build the best scalp short: short the NEAREST resistance, stop above it, target nearest support
if res5:
    r_lo, r_hi, r_kind = res5[0]
    entry = r_lo
    stop = r_hi + 0.4 * price5_atr
    tgt = sup5[0][0] if sup5 else (entry - 2 * (stop - entry))
    risk = stop - entry
    rr = (entry - tgt) / risk if risk > 0 else 0
    print("\n>>> BEST SCALP SHORT (M5):")
    print("    SELL-LIMIT %.2f  (%s, %+.1f pts above)" % (entry, r_kind, entry - price))
    print("    STOP       %.2f  (%.1f pts risk)" % (stop, risk))
    print("    TARGET     %.2f  (%.1f pts, %s)  RR %.1f" % (tgt, entry - tgt, sup5[0][2] if sup5 else "2R", rr))
    print("    spread eats ~%.0f pts of that -> net target ~%.1f pts" % (spread5, (entry - tgt) - spread5))
else:
    print("\n>>> No clean resistance above price on M5 — nothing to short into right now.")
