"""smc_m15_backtest.py — faithful M15 backtest of the SMC COMMAND CENTER pipeline.

DETECTOR IDENTITY: imports detect_setup / structure_bias / swings / atr from smc_map —
the SAME code the live command center runs. Never re-implements a detector.

Pipeline per closed M15 bar i (NO LOOKAHEAD anywhere):
  1. H4 context = aggregation of COMPLETED 4-hour buckets of M15 bars <= i
     (the bucket containing bar i is in progress -> excluded).
  2. bias = structure_bias(H4 swings);  state,sig = detect_setup(H4, M15window, close[i], bias)
  3. state == LTF_CONFIRMED and flat -> place a pending LIMIT at sig.entry with sig.sl/sig.tp.
     Pending expires after PEND_BARS if unfilled. One ticket at a time (doctrine).
  4. Fill: limit touched intrabar. Exit: SL/TP intrabar with SL PRIORITY on ambiguous bars;
     MAX_HOLD bars then exit at close. Costs: per-bar spread/2 + SLIP charged on entry AND exit.

Outputs per fold (train/test): n, win%, expR, totR, sharpe, maxDD(R), plus a regime-matched
RANDOM control (same direction mix, median stop distance & RR, same exit machinery, same costs).
Usage: python smc_m15_backtest.py <m15.csv> <point> <slip> <split_year> [label]
"""
import sys, csv, math, random
sys.path.insert(0, r"C:\Users\Sanique Richards\Documents\Homework Heroes\Pokemon\smc-command-desk")
import smc_map as sm

CSV_PATH  = sys.argv[1]
POINT     = float(sys.argv[2])
SLIP      = float(sys.argv[3])
SPLIT_Y   = int(sys.argv[4]) if len(sys.argv) > 4 else 2025
LABEL     = sys.argv[5] if len(sys.argv) > 5 else CSV_PATH
MODE      = sys.argv[6] if len(sys.argv) > 6 else "doctrine"   # doctrine | scalp | gold
FILTERS   = set((sys.argv[7] if len(sys.argv) > 7 else "").split(",")) - {""}
# scalp-mode filters: sess (London+NY 07-21 UTC), disp (displacement break bar),
#                     sweep (liquidity sweep within 20 bars first), trail (BE@1R + 2xATR trail)
# gold-mode  filters: trail (BE@1R + 2xATR trail), nobias (drop the H4-bias alignment gate),
#                     ce/mkt (entry style; default = zone edge), rr20/cap2/nocap (RR gates),
#                     buf25 (wider stop), nopd (drop premium/discount),
#                     tuethu (Tue-Thu only, silver-bullet advice)

H4_BARS   = 160     # H4 context window given to detect_setup (matches live --htf-count)
M15_BARS  = 224     # M15 window (matches live --ltf-count; >2 days for prior-day levels)
PEND_BARS = 16      # pending limit validity: 16 x M15 = 4h
if MODE == "gold":
    PEND_BARS = 8   # killzone retrace entries must fill inside the window (2h)
MAX_HOLD  = 96      # 24h max hold
WARMUP    = H4_BARS * 16 + 32
RNG_SEED  = 12345

# ---------- load ----------
t=[];o=[];h=[];l=[];c=[];sp=[]
with open(CSV_PATH, newline="") as f:
    for r in csv.DictReader(f):
        t.append(r["time"]); o.append(float(r["open"])); h.append(float(r["high"]))
        l.append(float(r["low"])); c.append(float(r["close"])); sp.append(float(r.get("spread",0) or 0))
n=len(c)
if n < WARMUP + 500:
    raise SystemExit("insufficient M15 bars: %d" % n)

# ---------- pre-aggregate H4 buckets (timestamp-floored, completed-only logic at use time) ----------
def bucket_key(ts):          # "YYYY-MM-DD HH:MM:SS" -> 4h bucket id
    d, tm = ts.split(" ")
    return d + " %02d" % ((int(tm[:2]) // 4) * 4)

bk=[bucket_key(x) for x in t]
# bucket index per bar + bucket arrays (built once, then referenced by completed-count)
b_t=[];b_o=[];b_h=[];b_l=[];b_c=[]; bar_bucket=[0]*n
cur=None
for i in range(n):
    if bk[i]!=cur:
        cur=bk[i]; b_t.append(t[i]); b_o.append(o[i]); b_h.append(h[i]); b_l.append(l[i]); b_c.append(c[i])
    else:
        b_h[-1]=max(b_h[-1],h[i]); b_l[-1]=min(b_l[-1],l[i]); b_c[-1]=c[i]
    bar_bucket[i]=len(b_t)-1

def cost_at(j):
    return sp[j]*POINT/2.0 + SLIP

RR_MIN = 1.5

def detect_scalp(M15, price, bias):
    """M15-NATIVE candidate ruleset (P3 restructure) = the desk's 'POSS continuation' trade:
    H4 gives ONLY the bias; the trade lives on M15. M15 CHoCH/BOS in bias direction within
    the last 12 bars + fresh M15 OB/FVG zone; entry at the zone edge, SL beyond the M15 zone
    +0.25*ATR15, TP at M15 opposing liquidity. If validated, this gets folded into smc_map."""
    (t15, o15, h15, l15, c15, a15, sh15, sl15) = M15
    m = len(c15)
    atr15 = a15[-1] if not math.isnan(a15[-1]) else 0.0
    if atr15 <= 0 or bias not in ("BULLISH", "BEARISH"):
        return None
    brk = sm.last_break(sh15, sl15, h15, l15, c15)
    if brk is None or brk[0] < m - 12:
        return None
    if "disp" in FILTERS:                                # break bar must be a displacement bar
        bi = brk[0]
        body = abs(c15[bi] - o15[bi]); rng = h15[bi] - l15[bi]
        if rng <= 0 or body < 0.5 * rng or rng < 0.8 * atr15:
            return None
    if bias == "BULLISH":
        if brk[2] != "up":
            return None
        if "sweep" in FILTERS:
            p = sm.eq_pool(sl15, l15, a15, price, "low")
            lvl = p[1] if p else (l15[sl15[-1]] if sl15 else None)
            if lvl is None or sm.eql_swept(l15, c15, lvl, m) is None:
                return None
        z = sm.bull_obs(o15, h15, l15, c15, a15, price, maxn=1) or sm.bull_fvgs(h15, l15, c15, a15, maxn=1)
        if not z:
            return None
        z_lo, z_hi = z[0][1], z[0][2]
        entry = z_hi
        sl_ = z_lo - 0.25 * atr15
        p = sm.eq_pool(sh15, h15, a15, price, "high")
        tp = p[1] if p else (h15[sh15[-1]] if sh15 and h15[sh15[-1]] > entry else None)
        if tp is None or not (tp > entry > sl_):
            return None
        risk = entry - sl_
        rr = (tp - entry) / risk if risk > 0 else 0
        if rr < RR_MIN:
            return None
        return {"dir": "LONG", "entry": entry, "sl": sl_, "tp": tp, "rr": rr}
    else:
        if brk[2] != "down":
            return None
        if "sweep" in FILTERS:
            p = sm.eq_pool(sh15, h15, a15, price, "high")
            lvl = p[1] if p else (h15[sh15[-1]] if sh15 else None)
            if lvl is None or sm.eqh_swept(h15, c15, lvl, m) is None:
                return None
        z = sm.bear_obs(o15, h15, l15, c15, a15, price, maxn=1) or sm.bear_fvgs(h15, l15, c15, a15, maxn=1)
        if not z:
            return None
        z_lo, z_hi = z[0][1], z[0][2]
        entry = z_lo
        sl_ = z_hi + 0.25 * atr15
        p = sm.eq_pool(sl15, l15, a15, price, "low")
        tp = p[1] if p else (l15[sl15[-1]] if sl15 and l15[sl15[-1]] < entry else None)
        if tp is None or not (sl_ > entry > tp):
            return None
        risk = sl_ - entry
        rr = (entry - tp) / risk if risk > 0 else 0
        if rr < RR_MIN:
            return None
        return {"dir": "SHORT", "entry": entry, "sl": sl_, "tp": tp, "rr": rr}

import datetime as _dt
def in_session(ts):
    if "tuethu" in FILTERS:                               # silver-bullet advice: skip Mon/Fri
        wd = _dt.date(int(ts[:4]), int(ts[5:7]), int(ts[8:10])).weekday()
        if wd in (0, 4):
            return False
    if "sess" not in FILTERS:
        return True
    hh = int(ts[11:13])
    return 7 <= hh < 21                                   # London open .. NY close (UTC)

# ---------- simulate ----------
trades=[]                     # (entry_bar, dir, entry, sl, tp, exit_bar, R, year, sl_atr_mult, rr)
pending=None; pos=None
last_state="OBSERVE"
random.seed(RNG_SEED)
sig_bars=[]                   # bars where a confirmed signal was emitted (for control matching)

for i in range(WARMUP, n-1):
    # --- manage open position ---
    if pos is not None:
        p=pos
        trail = "trail" in FILTERS
        hit_sl = (l[i]<=p["sl"]) if p["dir"]=="LONG" else (h[i]>=p["sl"])   # stop set at PRIOR bar
        hit_tp = (not trail) and ((h[i]>=p["tp"]) if p["dir"]=="LONG" else (l[i]<=p["tp"]))
        exit_px=None
        if hit_sl: exit_px=p["sl"]                      # SL priority on ambiguous bars
        elif hit_tp: exit_px=p["tp"]
        elif i-p["e"]>=MAX_HOLD: exit_px=c[i]
        if exit_px is not None:
            cst=cost_at(i)
            px = exit_px-cst if p["dir"]=="LONG" else exit_px+cst
            R = (px-p["entry"])/p["risk"] if p["dir"]=="LONG" else (p["entry"]-px)/p["risk"]
            trades.append((p["e"],p["dir"],p["entry"],p["sl"],p["tp"],i,R,int(t[p["e"]][:4]),p["slm"],p["rr"]))
            pos=None
        else:
            if trail:                                    # update AFTER the exit check (no lookahead)
                if p["dir"]=="LONG":
                    p["hw"]=max(p.get("hw",p["entry"]),h[i])
                    if h[i]>=p["entry"]+p["risk"]: p["sl"]=max(p["sl"],p["entry"])
                    p["sl"]=max(p["sl"],p["hw"]-2.0*p["atr"])
                else:
                    p["hw"]=min(p.get("hw",p["entry"]),l[i])
                    if l[i]<=p["entry"]-p["risk"]: p["sl"]=min(p["sl"],p["entry"])
                    p["sl"]=min(p["sl"],p["hw"]+2.0*p["atr"])
            continue                                     # in a trade: no new signals
    # --- pending fill / expiry ---
    if pending is not None:
        q=pending
        touched = (l[i]<=q["entry"]) if q["dir"]=="LONG" else (h[i]>=q["entry"])
        if touched:
            cst=cost_at(i)
            e_px = q["entry"]+cst if q["dir"]=="LONG" else q["entry"]-cst
            risk = (e_px-q["sl"]) if q["dir"]=="LONG" else (q["sl"]-e_px)
            if risk>0:
                pos={"e":i,"dir":q["dir"],"entry":e_px,"sl":q["sl"],"tp":q["tp"],"risk":risk,
                     "slm":q["slm"],"rr":q["rr"],"atr":q["atr"]}
            pending=None
            continue
        if i-q["b"]>=PEND_BARS:
            pending=None
    if pos is not None or pending is not None:
        continue
    # --- signal at this bar close (windowed, closed-data-only) ---
    nb=bar_bucket[i]                                     # bucket of bar i is INCOMPLETE
    if nb < H4_BARS+2: continue
    lo4=nb-H4_BARS
    H4=(b_t[lo4:nb], b_o[lo4:nb], b_h[lo4:nb], b_l[lo4:nb], b_c[lo4:nb])
    lo15=i+1-M15_BARS
    M15=(t[lo15:i+1], o[lo15:i+1], h[lo15:i+1], l[lo15:i+1], c[lo15:i+1])
    sh4,sl4 = sm.swings(H4[2],H4[3])
    a15= sm.atr(M15[2],M15[3],M15[4]); sh15,sl15 = sm.swings(M15[2],M15[3])
    bias = sm.structure_bias(sh4,sl4,H4[2],H4[3])
    if MODE=="gold":
        sig = sm.detect_gold_m15((M15[0],M15[1],M15[2],M15[3],M15[4],a15,sh15,sl15),
                                 c[i], bias, require_bias=("nobias" not in FILTERS),
                                 entry_mode=("ce" if "ce" in FILTERS else
                                             ("mkt" if "mkt" in FILTERS else "edge")),
                                 sl_buf=(0.25 if "buf25" in FILTERS else sm.KZ_SL_BUF_ATR),
                                 rr_min=(2.0 if "rr20" in FILTERS else sm.KZ_RR_MIN),
                                 rr_cap=(2.0 if "cap2" in FILTERS else
                                         (0.0 if "nocap" in FILTERS else sm.KZ_RR_CAP)),
                                 require_pd=("nopd" not in FILTERS))
        state = "LTF_CONFIRMED" if sig else "OBSERVE"
    elif MODE=="scalp":
        sig = detect_scalp((M15[0],M15[1],M15[2],M15[3],M15[4],a15,sh15,sl15), c[i], bias)
        state = "LTF_CONFIRMED" if sig else "OBSERVE"
    else:
        a4 = sm.atr(H4[2],H4[3],H4[4])
        state,sig = sm.detect_setup((H4[0],H4[1],H4[2],H4[3],H4[4],a4,sh4,sl4),
                                    (M15[0],M15[1],M15[2],M15[3],M15[4],a15,sh15,sl15),
                                    c[i], bias)
    if state=="LTF_CONFIRMED" and sig and last_state!="LTF_CONFIRMED" and in_session(t[i]):
        atr15 = a15[-1] if not math.isnan(a15[-1]) else 0
        if atr15>0 and sig["rr"]>0:
            slm = abs(sig["sl"]-sig["entry"])/atr15
            pending={"b":i,"dir":sig["dir"],"entry":sig["entry"],"sl":sig["sl"],"tp":sig["tp"],
                     "slm":slm,"rr":sig["rr"],"atr":atr15}
            sig_bars.append((i,sig["dir"]))
    last_state=state

# ---------- random control (same exit machinery, median geometry, matched count) ----------
def run_control(count, dirs, med_slm, med_rr):
    random.seed(RNG_SEED)
    valid=[i for i in range(WARMUP,n-MAX_HOLD-2)]
    out=[]
    tries=0
    while len(out)<count and tries<count*50:
        tries+=1
        i=random.choice(valid); d=random.choice(dirs)
        # need M15 ATR at i
        lo15=i+1-M15_BARS
        a15=sm.atr(h[lo15:i+1],l[lo15:i+1],c[lo15:i+1])
        atr15=a15[-1]
        if math.isnan(atr15) or atr15<=0: continue
        cst=cost_at(i+1)
        e_px = o[i+1]+cst if d=="LONG" else o[i+1]-cst
        risk = med_slm*atr15
        sl_ = e_px-risk if d=="LONG" else e_px+risk
        tp_ = e_px+med_rr*risk if d=="LONG" else e_px-med_rr*risk
        exit_px=None; last_j=i+1
        for j in range(i+1, min(i+1+MAX_HOLD, n)):
            hit_sl=(l[j]<=sl_) if d=="LONG" else (h[j]>=sl_)
            hit_tp=(h[j]>=tp_) if d=="LONG" else (l[j]<=tp_)
            if hit_sl: exit_px=sl_; break
            if hit_tp: exit_px=tp_; break
            last_j=j
        if exit_px is None: exit_px=c[last_j]
        cst2=cost_at(last_j)
        px = exit_px-cst2 if d=="LONG" else exit_px+cst2
        out.append(((px-e_px)/risk) if d=="LONG" else ((e_px-px)/risk))
    return out

# ---------- report ----------
def sharpe(rs):
    if len(rs)<2: return 0.0
    m=sum(rs)/len(rs); sd=math.sqrt(sum((x-m)**2 for x in rs)/len(rs))
    return (m/sd*math.sqrt(len(rs))) if sd>0 else 0.0

def maxdd(rs):
    s=0;pk=0;dd=0
    for r in rs:
        s+=r; pk=max(pk,s); dd=min(dd,s-pk)
    return dd

split=next((i for i in range(n) if int(t[i][:4])>=SPLIT_Y), n//2)
med = lambda xs: sorted(xs)[len(xs)//2] if xs else 0
all_slm=[x[8] for x in trades]; all_rr=[x[9] for x in trades]
print("=== %s ===  mode=%s filters=%s  %s -> %s  (%d bars)  split@%s  POINT=%s SLIP=%s" %
      (LABEL, MODE, (",".join(sorted(FILTERS)) or "none"), t[0][:10], t[-1][:10], n, t[split][:10], POINT, SLIP))
print("signals emitted=%d  trades filled=%d  (fill rate %.0f%%)  med SLxATR=%.2f  med RR=%.2f" %
      (len(sig_bars), len(trades), 100*len(trades)/max(1,len(sig_bars)), med(all_slm), med(all_rr)))
for fold,(lo,hi) in [("TRAIN",(0,split)),("TEST",(split,n))]:
    sub=[x for x in trades if lo<=x[0]<hi]; rs=[x[6] for x in sub]
    if not rs:
        print("  %-5s no trades" % fold); continue
    dirs=[x[1] for x in sub]
    ctrl=run_control(len(rs), dirs, med([x[8] for x in sub]), med([x[9] for x in sub]))
    cexp=(sum(ctrl)/len(ctrl)) if ctrl else 0.0
    exp=sum(rs)/len(rs); wr=100*sum(1 for r in rs if r>0)/len(rs)
    nl=sum(1 for d in dirs if d=="LONG")
    print("  %-5s n=%4d (L%d/S%d) win%%=%4.1f expR=%+.3f totR=%+7.1f shp=%+.2f maxDD=%.1fR | rand=%+.3f EDGE=%+.3f"
          % (fold,len(rs),nl,len(rs)-nl,wr,exp,sum(rs),sharpe(rs),maxdd(rs),cexp,exp-cexp))
by={}
for x in trades: by.setdefault(x[7],[]).append(x[6])
print("  per-year totR:", {y: round(sum(v),1) for y,v in sorted(by.items())})
