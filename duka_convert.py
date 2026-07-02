"""duka_convert.py — convert a dukascopy-node CSV export into the backtest CSV format.

Lets the M15 harnesses run on free Dukascopy data when no MT5 terminal is
available (e.g. CI / cloud). Dukascopy bid CSVs have no spread column, so a
fixed spread (in points) is stamped on every bar — pick your broker's typical
XAUUSD spread (20-40 points at POINT=0.01 == $0.20-$0.40).

  npx dukascopy-node -i xauusd -from 2020-01-01 -to now -t m15 -f csv -dir data
  python duka_convert.py data/xauusd-m15-bid-*.csv xauusd_m15.csv 30

Output columns: time,open,high,low,close,spread (UTC, oldest first).
"""
import sys, csv
from datetime import datetime, timezone

src = sys.argv[1]
dst = sys.argv[2]
spread_pts = int(sys.argv[3]) if len(sys.argv) > 3 else 30

rows = []
with open(src, newline="") as f:
    for r in csv.DictReader(f):
        try:
            ts = int(r["timestamp"]) // 1000
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        except (KeyError, ValueError):
            continue
        if h < l or o <= 0:
            continue
        if o == h == l == c:          # flat filler bar (weekend/holiday) — no information
            continue
        rows.append((ts, o, h, l, c))
rows.sort(key=lambda x: x[0])

with open(dst, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["time", "open", "high", "low", "close", "spread"])
    for ts, o, h, l, c in rows:
        t = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        w.writerow([t, o, h, l, c, spread_pts])

print("WROTE %s  bars=%d  %s -> %s  spread=%dpt" %
      (dst, len(rows),
       datetime.fromtimestamp(rows[0][0], timezone.utc).date(),
       datetime.fromtimestamp(rows[-1][0], timezone.utc).date(), spread_pts))
