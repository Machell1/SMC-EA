"""Resolve Deriv symbol names + available H1 history for EURUSD and the NAS100 index."""
import MetaTrader5 as mt5
from datetime import datetime, timezone

if not mt5.initialize(path=r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe"):
    if not mt5.initialize():
        raise SystemExit("mt5 init failed: %s" % str(mt5.last_error()))

cands = ["EURUSD", "NAS100", "US100", "USTEC", "USTECH", "USTEC100", "USNAS100",
         "NAS100.cash", "US Tech 100", "USTECHM", "NDX100", "NASUSD"]
print("=== candidate exact-name hits ===")
for nm in cands:
    info = mt5.symbol_info(nm)
    if info is not None:
        print("  HIT %-14s digits=%d point=%s" % (nm, info.digits, info.point))

print("=== fuzzy scan (name contains NAS / US100 / TEC / NDX) ===")
allsy = mt5.symbols_get()
for s in allsy:
    u = s.name.upper()
    if ("NAS" in u) or ("US100" in u) or ("USTEC" in u) or ("NDX" in u) or ("TECH" in u):
        print("  %-16s digits=%d point=%s desc=%s" % (s.name, s.digits, s.point, s.description[:40]))

def depth(sym):
    if mt5.symbol_info(sym) is None:
        return
    mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 200000)
    if r is None or len(r) == 0:
        print("  %-12s NO H1 DATA (%s)" % (sym, str(mt5.last_error()))); return
    t0 = datetime.fromtimestamp(int(r[0]["time"]), timezone.utc)
    t1 = datetime.fromtimestamp(int(r[-1]["time"]), timezone.utc)
    print("  %-12s H1 bars=%d  %s -> %s" % (sym, len(r), t0.date(), t1.date()))

print("=== H1 history depth ===")
depth("EURUSD")
for nm in cands:
    if mt5.symbol_info(nm) is not None and nm != "EURUSD":
        depth(nm)
