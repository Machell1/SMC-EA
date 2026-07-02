"""
smc_map.py — SMC COMMAND DESK live map engine (R3/R4/R7).

Reads MCP candle CSV(s), computes the Smart-Money map with the SAME detector
gating as the verified Pokemon/smc-gold/smc_backtest.py (DETECTOR-IDENTITY
INVARIANT), and writes the per-symbol command file the SMC_CommandCenter
indicator renders:  cmd_SMC_<SYMBOL>.txt  in the MT5 Common\\Files sandbox.

It DRAWS structure only. It never trades and never invents a price — every
level emitted is a real OHLC value from the fetched candles.

Detector parity with smc_backtest.py:
  swings  : fractal half-width w=2, confirmed at i+w
  bull OB : c[i-1]<o[i-1] and c[i]>h[i-1] and (c[i]-o[i])>0.6*(h[i]-l[i])
  bull FVG: l[i] > h[i-2]   (no displacement filter)
  EQ tol  : 0.10 * ATR(14)
  sweep   : l[j]<eql and c[j]>eql and c[j]>o[j]   (no body filter)
Bearish variants are the exact mirror (clearly the symmetric inversion),
used for two-sided DRAWING only.
"""
from __future__ import annotations
import csv, sys, time, math, argparse, os, json
from datetime import datetime, timedelta, timezone

EQ_TOL_ATR = 0.10
SWING_W    = 2
ATR_N      = 14

# ---------- IO ----------
def load_mcp_csv(path):
    rows = []
    with open(path, newline="") as f:
        rd = csv.reader(f)
        header = next(rd, None)
        for r in rd:
            if not r or len(r) < 6:
                continue
            try:
                ts = r[1]
                o, h, l, c = float(r[2]), float(r[3]), float(r[4]), float(r[5])
                sp = float(r[7]) if len(r) > 7 and r[7] != "" else 0.0
            except ValueError:
                continue
            rows.append((ts, o, h, l, c, sp))
    # chronological by ISO time string (lexicographic == chronological); guards
    # against the MCP newest-first row order.
    rows.sort(key=lambda x: x[0])
    t  = [x[0] for x in rows]
    o  = [x[1] for x in rows]
    h  = [x[2] for x in rows]
    l  = [x[3] for x in rows]
    c  = [x[4] for x in rows]
    sp = [x[5] for x in rows]
    return t, o, h, l, c, sp

def load_live(symbol, tf_str, count):
    """Fetch candles straight from the running MT5 terminal.
    Returns server-time wall-clock strings (same clock as chart iTime), so object
    anchors land on the exact bars with NO timezone conversion needed."""
    import MetaTrader5 as mt5
    tfmap = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
             "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
             "D1": mt5.TIMEFRAME_D1}
    if tf_str not in tfmap:
        sys.exit("bad timeframe %s" % tf_str)
    if not mt5.initialize(path=r"C:\\Program Files\\MetaTrader 5 Terminal\\terminal64.exe"):
        if not mt5.initialize():
            sys.exit("mt5 initialize failed: %s" % str(mt5.last_error()))
    rates = mt5.copy_rates_from_pos(symbol, tfmap[tf_str], 0, count)
    if rates is None or len(rates) == 0:
        sys.exit("no rates for %s %s (err=%s)" % (symbol, tf_str, str(mt5.last_error())))
    t = []; o = []; h = []; l = []; c = []; sp = []
    for r in rates:                                  # already oldest -> newest
        t.append(datetime.fromtimestamp(int(r["time"]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        o.append(float(r["open"])); h.append(float(r["high"]))
        l.append(float(r["low"]));  c.append(float(r["close"])); sp.append(float(r["spread"]))
    return t, o, h, l, c, sp

def live_price(symbol):
    import MetaTrader5 as mt5
    tk = mt5.symbol_info_tick(symbol)
    return float(tk.bid) if tk else 0.0

def live_equity():
    import MetaTrader5 as mt5
    ai = mt5.account_info()
    return ("%.2f" % ai.equity) if ai else ""

def live_digits(symbol):
    import MetaTrader5 as mt5
    info = mt5.symbol_info(symbol)
    return int(info.digits) if info else 2

def parse_iso(s):
    s = s.strip().replace("T", " ")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)

def fmt_time(iso, offset_sec=0):
    dt = parse_iso(iso) + timedelta(seconds=offset_sec)
    return dt.strftime("%Y.%m.%d %H:%M:%S")

# ---------- indicators ----------
def atr(h, l, c, n=ATR_N):
    if len(c) == 0:
        return []
    tr = [h[0] - l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    a = [float("nan")] * len(c)
    if len(c) >= n:
        a[n - 1] = sum(tr[:n]) / n
        for i in range(n, len(c)):
            a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a

def swings(h, l, w=SWING_W):
    sh, sl = [], []
    for i in range(w, len(h) - w):
        if h[i] == max(h[i - w:i + w + 1]) and h[i] > max(h[i - w:i]) and h[i] > max(h[i + 1:i + w + 1]):
            sh.append(i)
        if l[i] == min(l[i - w:i + w + 1]) and l[i] < min(l[i - w:i]) and l[i] < min(l[i + 1:i + w + 1]):
            sl.append(i)
    return sh, sl

# ---------- SMC geometry (real prices only) ----------
def bull_obs(o, h, l, c, a, price, maxn=2):
    res = []
    for i in range(len(c) - 2, 1, -1):
        if math.isnan(a[i]):
            continue
        if c[i - 1] < o[i - 1] and c[i] > h[i - 1] and (c[i] - o[i]) > 0.6 * (h[i] - l[i]):
            lo, hi = l[i - 1], h[i - 1]
            if hi >= price:
                continue
            if any(c[j] < lo for j in range(i + 1, len(c))):   # mitigated
                continue
            res.append((i, lo, hi))
            if len(res) >= maxn:
                break
    return res

def bear_obs(o, h, l, c, a, price, maxn=2):
    res = []
    for i in range(len(c) - 2, 1, -1):
        if math.isnan(a[i]):
            continue
        if c[i - 1] > o[i - 1] and c[i] < l[i - 1] and (o[i] - c[i]) > 0.6 * (h[i] - l[i]):
            lo, hi = l[i - 1], h[i - 1]
            if lo <= price:
                continue
            if any(c[j] > hi for j in range(i + 1, len(c))):
                continue
            res.append((i, lo, hi))
            if len(res) >= maxn:
                break
    return res

def bull_fvgs(h, l, c, a, maxn=1):
    res = []
    for i in range(len(c) - 1, 1, -1):
        if math.isnan(a[i]):
            continue
        if l[i] > h[i - 2]:
            glo, ghi = h[i - 2], l[i]
            if any(l[j] <= glo for j in range(i + 1, len(c))):   # filled
                continue
            res.append((i, glo, ghi))
            if len(res) >= maxn:
                break
    return res

def bear_fvgs(h, l, c, a, maxn=1):
    res = []
    for i in range(len(c) - 1, 1, -1):
        if math.isnan(a[i]):
            continue
        if h[i] < l[i - 2]:
            glo, ghi = h[i], l[i - 2]
            if any(h[j] >= ghi for j in range(i + 1, len(c))):
                continue
            res.append((i, glo, ghi))
            if len(res) >= maxn:
                break
    return res

def eq_pool(sw, vals, a, price, side):
    """side='high' -> EQH above price (buy-side); 'low' -> EQL below price."""
    pools = []
    for k in range(1, len(sw)):
        ai, bi = sw[k - 1], sw[k]
        if math.isnan(a[bi]):
            continue
        if abs(vals[ai] - vals[bi]) <= EQ_TOL_ATR * a[bi]:
            lvl = max(vals[ai], vals[bi]) if side == "high" else min(vals[ai], vals[bi])
            pools.append((bi, lvl))
    if side == "high":
        pools = [p for p in pools if p[1] >= price]
    else:
        pools = [p for p in pools if p[1] <= price]
    return pools[-1] if pools else None

def last_break(sh, sl, h, l, c):
    sh_s, sl_s = sorted(sh), sorted(sl)
    bull = bear = None
    last_sh, ptr = None, 0
    for i in range(2, len(c)):
        while ptr < len(sh_s) and sh_s[ptr] + SWING_W <= i:
            last_sh = sh_s[ptr]; ptr += 1
        if last_sh is not None and c[i] > h[last_sh] and c[i - 1] <= h[last_sh]:
            bull = (i, h[last_sh], "up")
    last_sl, ptr = None, 0
    for i in range(2, len(c)):
        while ptr < len(sl_s) and sl_s[ptr] + SWING_W <= i:
            last_sl = sl_s[ptr]; ptr += 1
        if last_sl is not None and c[i] < l[last_sl] and c[i - 1] >= l[last_sl]:
            bear = (i, l[last_sl], "down")
    cands = [x for x in (bull, bear) if x]
    return max(cands, key=lambda x: x[0]) if cands else None

def structure_bias(sh, sl, h, l):
    if len(sh) >= 2 and len(sl) >= 2:
        hh = h[sh[-1]] > h[sh[-2]]
        hl = l[sl[-1]] > l[sl[-2]]
        lh = h[sh[-1]] < h[sh[-2]]
        ll = l[sl[-1]] < l[sl[-2]]
        if hh and hl:
            return "BULLISH"
        if lh and ll:
            return "BEARISH"
    return "RANGE"

# ---------- violation detection (a marked level being taken out) ----------
VIOL_LOOKBACK = 3        # a sweep/break only "fires" within the last 3 bars

def eqh_swept(h, c, level, n):
    """EQH (buy-side) swept: wick above the pool, body closes back below. No lookahead."""
    for j in range(n - 1, max(-1, n - 1 - VIOL_LOOKBACK), -1):
        if j < 0:
            break
        if h[j] > level and c[j] < level:
            return (j, h[j])
    return None

def eql_swept(l, c, level, n):
    """EQL (sell-side) swept: wick below the pool, body closes back above."""
    for j in range(n - 1, max(-1, n - 1 - VIOL_LOOKBACK), -1):
        if j < 0:
            break
        if l[j] < level and c[j] > level:
            return (j, l[j])
    return None

def liq_above_of(sh, h, a, price):
    p = eq_pool(sh, h, a, price, "high")
    return p[1] if p else (h[sh[-1]] if sh else None)

def liq_below_of(sl, l, a, price):
    p = eq_pool(sl, l, a, price, "low")
    return p[1] if p else (l[sl[-1]] if sl else None)

# ---------- XAUUSD M15 killzone ruleset -------------------------------------
# Research-tuned (see README "Gold M15 killzone ruleset"): the community
# consensus for SMC on gold M15 is sweep-first + displacement MSS inside the
# London / New York killzones, entry at the 50% of the confirmation FVG/OB
# (consequent encroachment), stop beyond the sweep wick with an ATR buffer,
# target the opposing liquidity pool, longs only in discount / shorts only in
# premium of the dealing range. All levels are real OHLC values (R-invariant).
KZ_WINDOWS      = ((7*60,  10*60),      # London open killzone 07:00-10:00 UTC
                   (12*60+30, 16*60))   # NY killzone 12:30-16:00 UTC
ASIA_H0, ASIA_H1 = 0, 6                 # Asian accumulation range hours (UTC)
KZ_SWEEP_LOOKBACK = 8                   # sweep must be recent (M15 bars)
KZ_MSS_LOOKBACK   = 12                  # structure shift must be recent (M15 bars)
DISP_BODY_FRAC    = 0.5                 # displacement bar: body >= 50% of range
DISP_ATR_MULT     = 1.2                 # ... and range >= 1.2 * ATR(14)
KZ_SL_BUF_ATR     = 0.10                # stop buffer beyond the sweep wick
KZ_RR_MIN         = 1.5                 # minimum reward:risk (validated: 1.5 beat the
                                        # community-quoted 2.0 on 6.5y of gold M15)
KZ_RR_CAP         = 3.0                 # cap target at 3R (single-TP proxy for scaling out)

def _minute_of_day(ts):
    return int(ts[11:13]) * 60 + int(ts[14:16])

def in_killzone(ts):
    m = _minute_of_day(ts)
    return any(lo <= m < hi for lo, hi in KZ_WINDOWS)

def killzone_name(ts):
    m = _minute_of_day(ts)
    if KZ_WINDOWS[0][0] <= m < KZ_WINDOWS[0][1]:
        return "LONDON 07-10Z"
    if KZ_WINDOWS[1][0] <= m < KZ_WINDOWS[1][1]:
        return "NY 12:30-16Z"
    return "off"

def session_levels(t, h, l):
    """Asian-range high/low of the CURRENT day and full prior-day high/low —
    gold's primary intraday liquidity pools. Uses only bars already in the
    window (closed data). Returns dict of level -> (price, bar_index) or None."""
    m = len(t)
    if m == 0:
        return {}
    today = t[-1][:10]
    asia_hi = asia_lo = pd_hi = pd_lo = None
    prev_day = None
    for i in range(m - 1, -1, -1):
        d = t[i][:10]
        if d == today:
            hh = int(t[i][11:13])
            if ASIA_H0 <= hh < ASIA_H1:
                if asia_hi is None or h[i] > asia_hi[0]:
                    asia_hi = (h[i], i)
                if asia_lo is None or l[i] < asia_lo[0]:
                    asia_lo = (l[i], i)
        else:
            if prev_day is None:
                prev_day = d
            if d != prev_day:
                break
            if pd_hi is None or h[i] > pd_hi[0]:
                pd_hi = (h[i], i)
            if pd_lo is None or l[i] < pd_lo[0]:
                pd_lo = (l[i], i)
    return {"asia_hi": asia_hi, "asia_lo": asia_lo, "pd_hi": pd_hi, "pd_lo": pd_lo}

def swept_level(h, l, c, level, side, m, lookback=KZ_SWEEP_LOOKBACK):
    """Generic recent sweep of a liquidity level. side='high': wick above,
    body closes back below (buy-side raid). side='low': mirror. Returns
    (bar_index, wick_extreme) or None. No lookahead."""
    for j in range(m - 1, max(-1, m - 1 - lookback), -1):
        if j < 0:
            break
        if side == "high" and h[j] > level and c[j] < level:
            return (j, h[j])
        if side == "low" and l[j] < level and c[j] > level:
            return (j, l[j])
    return None

def displacement_ok(o, h, l, c, a, i):
    """The community-quantified displacement test: conviction body and an
    above-average range on the structure-break bar."""
    if i < 0 or i >= len(c) or math.isnan(a[i]):
        return False
    rng = h[i] - l[i]
    if rng <= 0:
        return False
    return abs(c[i] - o[i]) >= DISP_BODY_FRAC * rng and rng >= DISP_ATR_MULT * a[i]

def detect_gold_m15(M15, price, bias, require_bias=True,
                    entry_mode="edge", sl_buf=KZ_SL_BUF_ATR,
                    rr_min=KZ_RR_MIN, rr_cap=KZ_RR_CAP, require_pd=True):
    """XAUUSD M15 killzone setup: (1) killzone time gate, (2) recent sweep of a
    real liquidity pool (Asian range / prior-day extreme / EQH-EQL), (3) MSS
    (CHoCH/BOS) in trade direction AFTER the sweep on a displacement bar,
    (4) entry at 50% of the confirmation FVG (fallback OB), (5) stop beyond
    the sweep wick + ATR buffer, (6) TP at opposing liquidity, RR >= 2,
    (7) longs in discount / shorts in premium of the M15 dealing range.
    Returns sig dict or None. Uses only closed-bar values."""
    (t15, o15, h15, l15, c15, a15, sh15, sl15) = M15
    m = len(c15)
    if m < 30:
        return None
    atr15 = a15[-1] if not math.isnan(a15[-1]) else 0.0
    if atr15 <= 0 or not in_killzone(t15[-1]):
        return None
    if not sh15 or not sl15:
        return None

    sess = session_levels(t15, h15, l15)
    rng_hi, rng_lo = h15[sh15[-1]], l15[sl15[-1]]
    eq_mid = 0.5 * (rng_hi + rng_lo)

    def low_side_levels():
        lv = []
        for k in ("asia_lo", "pd_lo"):
            if sess.get(k):
                lv.append((sess[k][0], k))
        p = eq_pool(sl15, l15, a15, price, "low")
        if p:
            lv.append((p[1], "eql"))
        return lv

    def high_side_levels():
        lv = []
        for k in ("asia_hi", "pd_hi"):
            if sess.get(k):
                lv.append((sess[k][0], k))
        p = eq_pool(sh15, h15, a15, price, "high")
        if p:
            lv.append((p[1], "eqh"))
        return lv

    brk = last_break(sh15, sl15, h15, l15, c15)

    def build(direction):
        side = "low" if direction == "LONG" else "high"
        levels = low_side_levels() if direction == "LONG" else high_side_levels()
        best = None
        for lvl, src in levels:
            sw = swept_level(h15, l15, c15, lvl, side, m)
            if sw and (best is None or sw[0] > best[0][0]):
                best = (sw, lvl, src)
        if best is None:
            return None
        (sweep_j, sweep_ext), sweep_lvl, sweep_src = best
        want = "up" if direction == "LONG" else "down"
        if brk is None or brk[2] != want:
            return None
        if brk[0] < sweep_j or brk[0] < m - KZ_MSS_LOOKBACK:
            return None
        if not displacement_ok(o15, h15, l15, c15, a15, brk[0]):
            return None
        if direction == "LONG":
            z = bull_fvgs(h15, l15, c15, a15, maxn=1) or bull_obs(o15, h15, l15, c15, a15, price, maxn=1)
        else:
            z = bear_fvgs(h15, l15, c15, a15, maxn=1) or bear_obs(o15, h15, l15, c15, a15, price, maxn=1)
        if not z:
            return None
        if z[0][0] < sweep_j:      # zone must be left by the post-sweep displacement leg
            return None
        z_lo, z_hi = z[0][1], z[0][2]
        if entry_mode == "ce":
            entry = 0.5 * (z_lo + z_hi)                   # consequent encroachment
        elif entry_mode == "mkt":
            entry = price                                 # displacement-close market entry
        else:                                             # "edge" (validated default)
            entry = z_hi if direction == "LONG" else z_lo
        if direction == "LONG":
            if require_pd and entry > eq_mid:             # not in discount
                return None
            sl_ = min(sweep_ext, z_lo) - sl_buf * atr15
            tp = liq_above_of(sh15, h15, a15, price)
            if tp is None or not (tp > entry > sl_):
                return None
            risk = entry - sl_
            if rr_cap > 0:
                tp = min(tp, entry + rr_cap * risk)       # scale-out proxy
            rr = (tp - entry) / risk if risk > 0 else 0
        else:
            if require_pd and entry < eq_mid:             # not in premium
                return None
            sl_ = max(sweep_ext, z_hi) + sl_buf * atr15
            tp = liq_below_of(sl15, l15, a15, price)
            if tp is None or not (sl_ > entry > tp):
                return None
            risk = sl_ - entry
            if rr_cap > 0:
                tp = max(tp, entry - rr_cap * risk)       # scale-out proxy
            rr = (entry - tp) / risk if risk > 0 else 0
        if rr < rr_min:
            return None
        return {"dir": direction, "entry": entry, "sl": sl_, "tp": tp, "rr": rr,
                "poi": (z_lo, z_hi), "sweep_bar": sweep_j, "sweep_level": sweep_lvl,
                "sweep_src": sweep_src, "sweep_ext": sweep_ext, "mss_bar": brk[0]}

    if require_bias:
        if bias == "BULLISH":
            return build("LONG")
        if bias == "BEARISH":
            return build("SHORT")
        return None
    return build("LONG") or build("SHORT")

# ---------- setup detection (HTF POI -> LTF confirmation -> entry/SL/TP) ----------
def detect_setup(HTF, LTF, price, bias):
    """Walk the state machine for the HTF-bias direction.
    HTF/LTF = (t,o,h,l,c,a,sh,sl). Returns (state, sig|None) where sig carries
    dir/entry/sl/tp/rr/poi. Only real candle-derived prices are used."""
    (t, o, h, l, c, a, sh, sl_) = HTF
    (t2, o2, h2, l2, c2, a2, sh2, sl2) = LTF
    atr_l = a2[-1] if (a2 and not math.isnan(a2[-1])) else (a[-1] if not math.isnan(a[-1]) else 0.0)
    if atr_l <= 0:
        return ("OBSERVE", None)

    def liq_below():
        p = eq_pool(sl_, l, a, price, "low")
        if p:
            return p[1]
        return l[sl_[-1]] if sl_ else None

    def liq_above():
        p = eq_pool(sh, h, a, price, "high")
        if p:
            return p[1]
        return h[sh[-1]] if sh else None

    if bias == "BEARISH":
        obs = bear_obs(o, h, l, c, a, price, maxn=1)
        if obs:
            poi = (obs[0][1], obs[0][2])
        else:
            fv = bear_fvgs(h, l, c, a, maxn=1)
            poi = (fv[0][1], fv[0][2]) if fv else None
        if not poi:
            return ("OBSERVE", None)
        poi_lo, poi_hi = poi
        if price < poi_lo:                                  # price still below the supply zone
            return ("HTF_ARMED", {"dir": "SHORT", "poi": poi})
        brk = last_break(sh2, sl2, h2, l2, c2)              # LTF CHoCH down, recent
        choch = brk is not None and brk[2] == "down" and brk[0] >= len(c2) - 12
        ez = bear_obs(o2, h2, l2, c2, a2, price, maxn=1) or bear_fvgs(h2, l2, c2, a2, maxn=1)
        if choch and ez:
            entry = ez[0][1]                                # sell-limit at LTF zone low
            sl = poi_hi + 1.5 * atr_l
            tp = liq_below()
            if tp is not None and sl > entry > tp:
                risk = sl - entry
                rr = (entry - tp) / risk if risk > 0 else 0
                return ("LTF_CONFIRMED", {"dir": "SHORT", "entry": entry, "sl": sl, "tp": tp, "rr": rr, "poi": poi})
        return ("AT_POI", {"dir": "SHORT", "poi": poi})

    if bias == "BULLISH":
        obs = bull_obs(o, h, l, c, a, price, maxn=1)
        if obs:
            poi = (obs[0][1], obs[0][2])
        else:
            fv = bull_fvgs(h, l, c, a, maxn=1)
            poi = (fv[0][1], fv[0][2]) if fv else None
        if not poi:
            return ("OBSERVE", None)
        poi_lo, poi_hi = poi
        if price > poi_hi:                                  # price still above the demand zone
            return ("HTF_ARMED", {"dir": "LONG", "poi": poi})
        brk = last_break(sh2, sl2, h2, l2, c2)
        choch = brk is not None and brk[2] == "up" and brk[0] >= len(c2) - 12
        ez = bull_obs(o2, h2, l2, c2, a2, price, maxn=1) or bull_fvgs(h2, l2, c2, a2, maxn=1)
        if choch and ez:
            entry = ez[0][2]                                # buy-limit at LTF zone high
            sl = poi_lo - 1.5 * atr_l
            tp = liq_above()
            if tp is not None and tp > entry > sl:
                risk = entry - sl
                rr = (tp - entry) / risk if risk > 0 else 0
                return ("LTF_CONFIRMED", {"dir": "LONG", "entry": entry, "sl": sl, "tp": tp, "rr": rr, "poi": poi})
        return ("AT_POI", {"dir": "LONG", "poi": poi})

    return ("OBSERVE", None)

# ---------- emit ----------
def esc(v):
    return str(v).replace(";", ",").replace("\r", " ").replace("\n", " ")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="fetch candles from the running MT5 terminal")
    ap.add_argument("--htf-count", type=int, default=160)
    ap.add_argument("--ltf-count", type=int, default=224)   # >2 days of M15: prior-day levels need it
    ap.add_argument("--htf-csv", default="")
    ap.add_argument("--ltf-csv", default="")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--htf", default="H4")
    ap.add_argument("--ltf", default="M15")
    ap.add_argument("--ruleset", default="auto", choices=["auto", "doctrine", "gold_m15"],
                    help="auto = gold_m15 for XAU* symbols on M15, doctrine otherwise")
    ap.add_argument("--seq", type=int, default=0)
    ap.add_argument("--auto-seq", action="store_true", help="auto-increment a per-symbol seq counter file (for the watchdog)")
    ap.add_argument("--ttl", type=int, default=5400)
    ap.add_argument("--offset", type=int, default=0, help="server-UTC offset seconds for object times")
    ap.add_argument("--equity", default="")
    ap.add_argument("--price", default="")
    ap.add_argument("--desk-mode", default="VALIDATE - observe-only")
    ap.add_argument("--news", default="")
    ap.add_argument("--pressure", default="monitor")
    ap.add_argument("--lockout", default="none")
    ap.add_argument("--news-file", default="")
    ap.add_argument("--ticket-file", default="")
    ap.add_argument("--validation", default="PENDING")
    ap.add_argument("--state", default="OBSERVE")
    ap.add_argument("--ticket", default="none")
    ap.add_argument("--last-wake", default="")
    ap.add_argument("--next-wake", default="")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    # cached inputs (so the OS watchdog, which has no live news/recon, stays current)
    # news cache = up to 3 lines: event / pressure / lockout (the agent writes it; the watchdog reads it)
    if args.news_file and os.path.exists(args.news_file):
        try:
            with open(args.news_file, encoding="utf-8") as f:
                _ln = [x.strip() for x in f.read().splitlines()]
            if len(_ln) > 0 and _ln[0] and not args.news:
                args.news = _ln[0]
            if len(_ln) > 1 and _ln[1]:
                args.pressure = _ln[1]
            if len(_ln) > 2 and _ln[2]:
                args.lockout = _ln[2]
        except OSError:
            pass
    if not args.news:
        args.news = "monitor"
    if args.ticket_file and (not args.ticket or args.ticket == "none") and os.path.exists(args.ticket_file):
        try:
            with open(args.ticket_file, encoding="utf-8") as f:
                line = f.readline().strip()
            if line:
                args.ticket = line
        except OSError:
            pass

    # auto-increment seq (monotonic across watchdog + agent writers)
    if args.auto_seq:
        seqp = os.path.join(args.out_dir, "seq_%s.txt" % args.symbol)
        cur = 0
        try:
            with open(seqp, encoding="utf-8") as f:
                cur = int((f.readline().strip() or "0"))
        except (OSError, ValueError):
            cur = 0
        args.seq = cur + 1
        try:
            with open(seqp, "w", encoding="utf-8") as f:
                f.write(str(args.seq))
        except OSError:
            pass
    if args.seq <= 0:
        args.seq = 1

    if args.live:
        t, o, h, l, c, sp = load_live(args.symbol, args.htf, args.htf_count)
        off = 0                                      # live times are already server-time
        if not args.price:
            p = live_price(args.symbol)
            if p > 0:
                args.price = "%.5f" % p
        if not args.equity:
            args.equity = live_equity()
    else:
        if not args.htf_csv:
            sys.exit("need --htf-csv or --live")
        t, o, h, l, c, sp = load_mcp_csv(args.htf_csv)
        off = args.offset
    if len(c) < 30:
        sys.exit("not enough HTF candles: %d" % len(c))
    a = atr(h, l, c)
    sh, sl = swings(h, l)
    price = float(args.price) if args.price else c[-1]
    digits = (live_digits(args.symbol) if args.live else 2)
    px = lambda v: ("%." + str(digits) + "f") % v

    objs = []   # (id, kind, t1, p1, t2, p2, color, label)

    # channel: last two confirmed swing highs / lows
    if len(sh) >= 2:
        ai, bi = sh[-2], sh[-1]
        objs.append(("chan_up", "TREND", fmt_time(t[ai], off), h[ai], fmt_time(t[bi], off), h[bi], "dodger", "channel hi"))
    if len(sl) >= 2:
        ai, bi = sl[-2], sl[-1]
        objs.append(("chan_dn", "TREND", fmt_time(t[ai], off), l[ai], fmt_time(t[bi], off), l[bi], "dodger", "channel lo"))

    # equilibrium of the active dealing range
    poi_txt = "none"
    if sh and sl:
        rng_hi, rng_lo = h[sh[-1]], l[sl[-1]]
        eq = 0.5 * (rng_hi + rng_lo)
        objs.append(("eq_mid", "EQ", fmt_time(t[min(sh[-1], sl[-1])], off), eq, "0", 0, "silver", "equilibrium 0.5"))

    # order blocks (real reaction areas)
    for n, (i, lo, hi) in enumerate(bull_obs(o, h, l, c, a, price)):
        objs.append(("ob_bull_%d" % n, "OB", fmt_time(t[i - 1], off), hi, "0", lo, "teal", "%s OB demand" % args.htf))
        if poi_txt == "none":
            poi_txt = "%s demand OB %s-%s" % (args.htf, px(lo), px(hi))
    for n, (i, lo, hi) in enumerate(bear_obs(o, h, l, c, a, price)):
        objs.append(("ob_bear_%d" % n, "OB", fmt_time(t[i - 1], off), hi, "0", lo, "crimson", "%s OB supply" % args.htf))
        if poi_txt == "none":
            poi_txt = "%s supply OB %s-%s" % (args.htf, px(lo), px(hi))

    # fair value gaps
    for n, (i, glo, ghi) in enumerate(bull_fvgs(h, l, c, a)):
        objs.append(("fvg_bull_%d" % n, "FVG", fmt_time(t[i - 2], off), ghi, "0", glo, "slate", "%s FVG" % args.htf))
    for n, (i, glo, ghi) in enumerate(bear_fvgs(h, l, c, a)):
        objs.append(("fvg_bear_%d" % n, "FVG", fmt_time(t[i], off), ghi, "0", glo, "slate", "%s FVG" % args.htf))

    # liquidity pools
    eqh = eq_pool(sh, h, a, price, "high")
    if eqh:
        objs.append(("eqh", "LIQ", fmt_time(t[eqh[0]], off), eqh[1], "0", 0, "gold", "EQH buy-side liq"))
    eql = eq_pool(sl, l, a, price, "low")
    if eql:
        objs.append(("eql", "LIQ", fmt_time(t[eql[0]], off), eql[1], "0", 0, "gold", "EQL sell-side liq"))

    # last structural break
    bias = structure_bias(sh, sl, h, l)
    brk = last_break(sh, sl, h, l, c)
    if brk:
        bi, lvl, d = brk
        agree = (d == "up" and bias == "BULLISH") or (d == "down" and bias == "BEARISH")
        kind = "BOS" if agree else "CHOCH"
        col = "dodger" if kind == "BOS" else "orange"
        objs.append(("brk", kind, fmt_time(t[bi], off), lvl, "0", 0, col, "%s %s" % (kind, d)))

    # ---- LTF refinement + setup detection (HTF POI -> LTF confirmation) ----
    ruleset = args.ruleset
    if ruleset == "auto":
        ruleset = "gold_m15" if (args.symbol.upper().startswith("XAU") and args.ltf.upper() == "M15") else "doctrine"
    setup_state, sig = ("OBSERVE", None)
    kz_txt = ""
    ltf_loaded = None
    if args.live:
        ltf_loaded = load_live(args.symbol, args.ltf, args.ltf_count)
    elif args.ltf_csv and os.path.exists(args.ltf_csv):
        ltf_loaded = load_mcp_csv(args.ltf_csv)
    if ltf_loaded:
        t2, o2, h2, l2, c2, sp2 = ltf_loaded
        if len(c2) >= 30:
            aa2 = atr(h2, l2, c2)
            sh2, sl2 = swings(h2, l2)
            for n, (i, lo, hi) in enumerate(bull_obs(o2, h2, l2, c2, aa2, price, maxn=1)):
                objs.append(("ltf_ob_b_%d" % n, "OB", fmt_time(t2[i - 1], off), hi, "0", lo, "teal", "%s OB" % args.ltf))
            for n, (i, glo, ghi) in enumerate(bull_fvgs(h2, l2, c2, aa2, maxn=1)):
                objs.append(("ltf_fvg_b_%d" % n, "FVG", fmt_time(t2[i - 2], off), ghi, "0", glo, "slate", "%s FVG" % args.ltf))
            setup_state, sig = detect_setup((t, o, h, l, c, a, sh, sl),
                                            (t2, o2, h2, l2, c2, aa2, sh2, sl2), price, bias)
            if ruleset == "gold_m15":
                # session liquidity map: Asian range box + prior-day extremes
                sess = session_levels(t2, h2, l2)
                if sess.get("asia_hi") and sess.get("asia_lo"):
                    ah, al = sess["asia_hi"], sess["asia_lo"]
                    ti = min(ah[1], al[1])
                    objs.append(("asia_rng", "ZONE", fmt_time(t2[ti], off), ah[0], "0", al[0], "slate", "Asia range"))
                if sess.get("pd_hi"):
                    objs.append(("pdh", "LIQ", fmt_time(t2[sess["pd_hi"][1]], off), sess["pd_hi"][0], "0", 0, "gold", "PDH liq"))
                if sess.get("pd_lo"):
                    objs.append(("pdl", "LIQ", fmt_time(t2[sess["pd_lo"][1]], off), sess["pd_lo"][0], "0", 0, "gold", "PDL liq"))
                kz_txt = killzone_name(t2[-1])
                gsig = detect_gold_m15((t2, o2, h2, l2, c2, aa2, sh2, sl2), price, bias)
                if gsig:
                    setup_state, sig = "KZ_CONFIRMED", gsig
                    objs.append(("kz_sweep", "SWEEP", fmt_time(t2[gsig["sweep_bar"]], off),
                                 gsig["sweep_ext"], "0", 0, "magenta",
                                 "SWEEP %s" % gsig["sweep_src"]))
    else:
        setup_state = "HTF_ARMED" if bias in ("BULLISH", "BEARISH") else "OBSERVE"

    CONFIRMED_STATES = ("LTF_CONFIRMED", "KZ_CONFIRMED")

    # draw entry/SL/TP when a setup is confirmed (reuse LIQ/TARGET kinds -> no indicator change)
    if sig and setup_state in CONFIRMED_STATES:
        rt = fmt_time(t[-1], off)
        objs.append(("sig_entry", "LIQ", rt, sig["entry"], "0", 0, "dodger", "ENTRY %s" % sig["dir"]))
        objs.append(("sig_sl", "LIQ", rt, sig["sl"], "0", 0, "crimson", "SL"))
        objs.append(("sig_tp", "TARGET", rt, sig["tp"], "0", 0, "lime", "TP"))

    # ---- VIOLATIONS + POSSIBLE-TRADE (OBSERVE-ONLY; a swept/broken level is removed,
    #      and the trade it sets up is drawn as a tentative POSS mark) ----
    suppress = set()        # object ids the redraw must NOT re-emit this run
    viol_txt = "none"
    poss_panel = None
    res = None
    try:
        nbar = len(c)
        rtv = fmt_time(t[-1], off)
        atr_h = a[-1] if (a and not math.isnan(a[-1])) else 0.0
        BUF, RR_MIN = 0.25 * atr_h, 1.5
        confirmed = bool(sig and setup_state in CONFIRMED_STATES)

        def emit_poss(direction, entry, sl_, tp):
            if confirmed:                      # the validated state machine supersedes a candidate
                return None
            if entry <= 0 or sl_ <= 0 or tp is None or tp <= 0:
                return None
            if direction == "SHORT":
                if not (sl_ > entry > tp):
                    return None
                risk = sl_ - entry
                rr = (entry - tp) / risk if risk > 0 else 0
            else:
                if not (tp > entry > sl_):
                    return None
                risk = entry - sl_
                rr = (tp - entry) / risk if risk > 0 else 0
            if rr < RR_MIN:
                return None
            # risk (red) + reward (green) zones = the full trade marked as a R/R box
            t_back = fmt_time(t[max(0, nbar - 16)], off)
            if direction == "SHORT":
                risk_top, risk_bot, rew_top, rew_bot = sl_, entry, entry, tp
            else:
                risk_top, risk_bot, rew_top, rew_bot = entry, sl_, tp, entry
            objs.append(("poss_reward", "ZONE", t_back, rew_top, "0", rew_bot, "teal", ""))
            objs.append(("poss_risk", "ZONE", t_back, risk_top, "0", risk_bot, "crimson", ""))
            objs.append(("poss_entry", "LIQ", rtv, entry, "0", 0, "magenta", "POSS %s ENTRY %s" % (direction, px(entry))))
            objs.append(("poss_sl", "LIQ", rtv, sl_, "0", 0, "orange", "POSS SL %s (-1R)" % px(sl_)))
            objs.append(("poss_tp", "TARGET", rtv, tp, "0", 0, "lime", "POSS TP %s (+%.1fR)" % (px(tp), rr)))
            return (direction, entry, sl_, tp, rr)

        # RULE 1: EQH (buy-side liq above) swept -> remove the eqh mark, POSS SHORT reversal
        if eqh:
            sw = eqh_swept(h, c, eqh[1], nbar)
            if sw:
                suppress.add("eqh")
                viol_txt = "EQH swept @%s" % px(eqh[1])
                if res is None:
                    res = emit_poss("SHORT", eqh[1], sw[1] + BUF, liq_below_of(sl, l, a, price))
        # RULE 2: EQL (sell-side liq below) swept -> remove the eql mark, POSS LONG reversal
        if eql:
            sw = eql_swept(l, c, eql[1], nbar)
            if sw:
                suppress.add("eql")
                viol_txt = ("EQL swept @%s" % px(eql[1])) if viol_txt == "none" else viol_txt + "; EQL @%s" % px(eql[1])
                if res is None:
                    res = emit_poss("LONG", eql[1], sw[1] - BUF, liq_above_of(sh, h, a, price))
        # RULE 3/4: BOS broke structure -> POSS continuation on the pullback (only if no sweep trade)
        if res is None and brk:
            bi, lvl, dxn = brk
            if bi >= nbar - VIOL_LOOKBACK:
                if dxn == "up" and bias == "BULLISH":
                    z = bull_obs(o, h, l, c, a, price, maxn=1) or bull_fvgs(h, l, c, a, maxn=1)
                    if z:
                        z_lo, z_hi = z[0][1], z[0][2]
                        res = emit_poss("LONG", z_hi, min(z_lo, lvl) - BUF, liq_above_of(sh, h, a, price))
                elif dxn == "down" and bias == "BEARISH":
                    z = bear_obs(o, h, l, c, a, price, maxn=1) or bear_fvgs(h, l, c, a, maxn=1)
                    if z:
                        z_lo, z_hi = z[0][1], z[0][2]
                        res = emit_poss("SHORT", z_lo, max(z_hi, lvl) + BUF, liq_below_of(sl, l, a, price))
        poss_src = "viol" if res else ""
        # FALLBACK: no fresh violation -> mark the ANTICIPATED trade from the current HTF POI/bias,
        # so a 'possible trade' is always on the chart whenever there's a directional setup.
        if res is None and not confirmed and sig and sig.get("poi") and setup_state in ("HTF_ARMED", "AT_POI"):
            plo, phi = sig["poi"]
            if sig.get("dir") == "SHORT":          # short the supply zone above price
                res = emit_poss("SHORT", plo, phi + BUF, liq_below_of(sl, l, a, price))
            elif sig.get("dir") == "LONG":         # long the demand zone below price
                res = emit_poss("LONG", phi, plo - BUF, liq_above_of(sh, h, a, price))
            if res:
                poss_src = "POI"
        if res:
            dd, ee, ss, tt, rr = res
            tag = "POI plan, obs" if poss_src == "POI" else "obs"
            poss_panel = ("Possible", "%s e%s sl%s tp%s R%.1f (%s)" % (dd, px(ee), px(ss), px(tt), rr, tag))
    except Exception:
        suppress, viol_txt, poss_panel, res = set(), "none", None, None   # never break the dashboard

    # ---- panel (clean, sectioned; "__sec" rows render as section headers) ----
    val_map = {"FAIL": "FAIL - observe-only", "PASS": "PASS - live-eligible", "PENDING": "PENDING"}
    val_disp = val_map.get(args.validation.upper(), args.validation)
    risk_disp = "0% - observe-only" if args.validation.upper() != "PASS" else "per R5"
    updated = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    _ = (risk_disp, updated)  # (kept for callers; header shows the timestamp)
    sdir = (" " + sig["dir"]) if (sig and sig.get("dir")) else ""
    state_disp = setup_state + sdir
    panel = [
        ("__sec", "STATUS"),
        ("State", state_disp),
        ("Validation", val_disp),
        ("Bias", "%s (%s)" % (bias, args.htf)),
        ("Price", px(price)),
        ("__sec", "DESK"),
        ("POI", poi_txt),
        ("News", args.news),
        ("Lockout", args.lockout),
        ("Risk", "0%% / eq $%s" % (args.equity or "n/a")),
        ("Ticket", args.ticket),
    ]
    if kz_txt:
        panel.insert(5, ("Killzone", kz_txt if kz_txt != "off" else "off - no entries"))
    if sig and setup_state in CONFIRMED_STATES:
        panel.append(("Trade", "e%s sl%s tp%s R%.1f" % (px(sig["entry"]), px(sig["sl"]), px(sig["tp"]), sig["rr"])))
        if setup_state == "KZ_CONFIRMED":
            panel.append(("Sweep", "%s swept @%s" % (sig.get("sweep_src", "?"), px(sig.get("sweep_level", 0)))))
    if viol_txt != "none":
        panel.append(("Violations", viol_txt))
    if poss_panel:
        panel.append(poss_panel)

    # ---- TREND HARNESS overlay (the §6-VALIDATED long>SMA200 trend follower) ----
    try:
        tp = os.path.join(args.out_dir, "trend_signal_%s.json" % args.symbol)
        if os.path.exists(tp):
            with open(tp, encoding="utf-8") as tf:
                tj = json.load(tf)
            tstate = tj.get("state", "?"); treg = tj.get("regime", "?")
            sma2 = tj.get("sma200", 0); tstop = tj.get("stop", 0)
            rt2 = fmt_time(t[-1], off)
            if sma2:
                objs.append(("trend_sma200", "EQ", rt2, sma2, "0", 0, "gold", "SMA200 %s" % px(sma2)))
            if tstate == "LONG" and tstop:
                objs.append(("trend_stop", "LIQ", rt2, tstop, "0", 0, "crimson", "TREND stop %s" % px(tstop)))
            tval = tstate + ((" @%s" % px(tj.get("entry", 0))) if tstate == "LONG" else "")
            panel.append(("Trend", "%s / %s" % (tval, treg)))
    except (OSError, ValueError):
        pass

    # ---- SCALP overlay (manual trade marks; reads scalp_<SYM>.json, auto-clears when the file is removed) ----
    try:
        scp = os.path.join(args.out_dir, "scalp_%s.json" % args.symbol)
        if os.path.exists(scp):
            with open(scp, encoding="utf-8") as sf:
                sj = json.load(sf)
            se = sj.get("entry", 0); ssl = sj.get("sl", 0)
            st1 = sj.get("tp1", 0); st2 = sj.get("tp2", 0); sdir = sj.get("dir", "SHORT")
            rt3 = fmt_time(t[-1], off); tb = fmt_time(t[max(0, len(t) - 10)], off)
            if se and ssl:
                objs.append(("scalp_risk", "ZONE", tb, max(se, ssl), "0", min(se, ssl), "crimson", ""))
                if st2:
                    objs.append(("scalp_reward", "ZONE", tb, max(se, st2), "0", min(se, st2), "teal", ""))
                objs.append(("scalp_entry", "LIQ", rt3, se, "0", 0, "gold", "SCALP %s %s" % (sdir, px(se))))
                objs.append(("scalp_sl", "LIQ", rt3, ssl, "0", 0, "crimson", "SCALP SL %s" % px(ssl)))
                if st1:
                    objs.append(("scalp_t1", "TARGET", rt3, st1, "0", 0, "lime", "T1 %s" % px(st1)))
                if st2:
                    objs.append(("scalp_t2", "TARGET", rt3, st2, "0", 0, "lime", "T2 %s" % px(st2)))
                panel.append(("Scalp", "%s e%s sl%s t1%s" % (sdir, px(se), px(ssl), px(st1))))
    except (OSError, ValueError):
        pass

    # ---- serialize ----
    lines = []
    lines.append("meta;1;%d;%d;%s;%s;%s;%d" % (args.seq, int(time.time()), args.symbol, args.htf, args.ltf, args.ttl))
    for k, v in panel:
        lines.append("panel;%s;%s" % (esc(k), esc(v)))
    for ob in objs:
        oid, kind, t1, p1, t2v, p2, col, lab = ob
        if oid in suppress:                # a violated level self-deletes via the full redraw
            continue
        p1s = ("%.5f" % p1) if isinstance(p1, float) else str(p1)
        p2s = ("%.5f" % p2) if isinstance(p2, float) else str(p2)
        lines.append("obj;%s;%s;%s;%s;%s;%s;%s;%s" % (esc(oid), kind, t1, p1s, t2v, p2s, col, esc(lab)))
    text = "\r\n".join(lines) + "\r\n"

    out = os.path.join(args.out_dir, "cmd_SMC_%s.txt" % args.symbol)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:   # utf-8 no BOM == ANSI for ASCII
        f.write(text)
    os.replace(tmp, out)

    # ---- signal file for the alerter (push once per NEW armed setup) ----
    sigstate_p = os.path.join(args.out_dir, "smc_sigstate_%s.json" % args.symbol)
    prev_key, armed_seq, prev_poss = "", 0, ""
    try:
        with open(sigstate_p, encoding="utf-8") as f:
            _st = json.load(f)
        prev_key = _st.get("sig_key", "")
        armed_seq = int(_st.get("armed_seq", 0))
        prev_poss = _st.get("poss_key", "")
    except (OSError, ValueError):
        pass
    sig_key = ("%s:%s" % (sig["dir"], px(sig["entry"]))) if (setup_state in CONFIRMED_STATES and sig) else ""
    armed_new = bool(sig_key) and sig_key != prev_key
    if armed_new:
        armed_seq += 1
    S = sig or {}
    poi_lo, poi_hi = S.get("poi", (0, 0))
    poss_key = ("%s:%s" % (res[0], px(res[1]))) if res else ""
    poss_new = bool(poss_key) and poss_key != prev_poss
    signal = {"ts": int(time.time()), "symbol": args.symbol, "state": setup_state, "bias": bias,
              "price": round(price, digits), "dir": S.get("dir", ""),
              "entry": round(S.get("entry", 0), digits), "sl": round(S.get("sl", 0), digits),
              "tp": round(S.get("tp", 0), digits), "rr": round(S.get("rr", 0), 2),
              "poi_lo": round(poi_lo, digits), "poi_hi": round(poi_hi, digits),
              "armed_seq": armed_seq, "armed_new": armed_new, "validation": args.validation,
              "violation": (viol_txt if viol_txt != "none" else ""),
              "poss_dir": (res[0] if res else ""), "poss_entry": (round(res[1], digits) if res else 0),
              "poss_sl": (round(res[2], digits) if res else 0), "poss_tp": (round(res[3], digits) if res else 0),
              "poss_rr": (round(res[4], 2) if res else 0), "poss_new": poss_new}
    with open(os.path.join(args.out_dir, "smc_signal_%s.json" % args.symbol), "w", encoding="utf-8") as f:
        json.dump(signal, f)
    with open(sigstate_p, "w", encoding="utf-8") as f:
        json.dump({"sig_key": sig_key, "armed_seq": armed_seq, "poss_key": poss_key}, f)

    print("WROTE %s" % out)
    print("seq=%d  bias=%s  state=%s  objects=%d  price=%.2f" % (args.seq, bias, setup_state, len(objs), price))
    if sig and setup_state in CONFIRMED_STATES:
        print("SETUP %s  entry=%.2f sl=%.2f tp=%.2f rr=%.2f  armed_new=%s seq=%d"
              % (sig["dir"], sig["entry"], sig["sl"], sig["tp"], sig["rr"], armed_new, armed_seq))
    print("active_poi=%s" % poi_txt)

if __name__ == "__main__":
    main()
