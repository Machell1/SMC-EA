"""BTCUSD 5-min refresh: trend engine THEN SMC map (dashboard overlays the trend state).
Windowless. Run by the SMC_CommandCenter_Watchdog_BTCUSD task."""
import subprocess

PY = r"C:\Python313\python.exe"
BASE = r"C:\Users\Sanique Richards\Documents\Homework Heroes\Pokemon\smc-command-desk"
CF = r"C:\Users\Sanique Richards\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
NOWIN = 0x08000000  # CREATE_NO_WINDOW

VAL = "NOT yet validated - trend overlay observe-only (BTC has data; run trend_val.py to test it)"

subprocess.run([PY, BASE + r"\trend_engine.py", "BTCUSD", CF, "0.01", "5.0", "2200", VAL],
               creationflags=NOWIN)
subprocess.run([PY, BASE + r"\smc_map.py", "--live", "--auto-seq", "--symbol", "BTCUSD",
                "--htf", "H4", "--ltf", "M15", "--ttl", "1200", "--validation", "FAIL", "--state", "OBSERVE",
                "--desk-mode", "VALIDATE - observe-only",
                "--news-file", CF + r"\smc_news_BTCUSD.txt", "--ticket-file", CF + r"\smc_ticket_BTCUSD.txt",
                "--out-dir", CF],
               creationflags=NOWIN)
