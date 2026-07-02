"""Fetch deep history for a Deriv symbol and save it in the smc_backtest CSV format
(time,open,high,low,close,spread).
Usage: python fetch_history.py "<symbol>" <out.csv> [timeframe=H1]"""
import sys, csv
import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta

sym = sys.argv[1]
out = sys.argv[2]
tf_str = (sys.argv[3] if len(sys.argv) > 3 else "H1").upper()

if not mt5.initialize(path=r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe"):
    if not mt5.initialize():
        raise SystemExit("mt5 init failed: %s" % str(mt5.last_error()))
mt5.symbol_select(sym, True)

TFMAP = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
         "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
         "D1": mt5.TIMEFRAME_D1}
if tf_str not in TFMAP:
    raise SystemExit("bad timeframe %s" % tf_str)
TF = TFMAP[tf_str]

start = datetime(2016, 1, 1, tzinfo=timezone.utc)
end = datetime.now(timezone.utc) + timedelta(days=1)

rates = mt5.copy_rates_range(sym, TF, start, end)
if rates is None or len(rates) == 0:
    # fall back to from_pos with decreasing counts
    for n in (400000, 250000, 120000, 90000, 60000, 40000, 20000, 10000):
        rates = mt5.copy_rates_from_pos(sym, TF, 0, n)
        if rates is not None and len(rates) > 0:
            break
if rates is None or len(rates) == 0:
    raise SystemExit("no %s data for %s (%s)" % (tf_str, sym, str(mt5.last_error())))

with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["time", "open", "high", "low", "close", "spread"])
    for r in rates:
        t = datetime.fromtimestamp(int(r["time"]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        w.writerow([t, r["open"], r["high"], r["low"], r["close"], int(r["spread"])])

t0 = datetime.fromtimestamp(int(rates[0]["time"]), timezone.utc)
t1 = datetime.fromtimestamp(int(rates[-1]["time"]), timezone.utc)
info = mt5.symbol_info(sym)
print("WROTE %s  bars=%d  %s -> %s  point=%s digits=%d"
      % (out, len(rates), t0.date(), t1.date(), info.point, info.digits))
# year coverage
yrs = {}
for r in rates:
    y = datetime.fromtimestamp(int(r["time"]), timezone.utc).year
    yrs[y] = yrs.get(y, 0) + 1
print("by year:", dict(sorted(yrs.items())))
