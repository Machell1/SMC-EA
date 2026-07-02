"""Cocoa 5-min refresh: runs the trend engine THEN the SMC map (so the dashboard
overlays the live trend state). Windowless. Run by the SMC_CommandCenter_Watchdog_Cocoa task."""
import subprocess

PY = r"C:\Python313\python.exe"
BASE = r"C:\Users\Sanique Richards\Documents\Homework Heroes\Pokemon\smc-command-desk"
CF = r"C:\Users\Sanique Richards\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
NOWIN = 0x08000000  # CREATE_NO_WINDOW

VAL = "INDICATIVE +EV ~2y data-limited (both folds +, 3/3yr, avoided -79pct B&H crash); momentum/beta, NOT fully validated"

subprocess.run([PY, BASE + r"\trend_engine.py", "Cocoa", CF, "0.01", "1.0", "2200", VAL],
               creationflags=NOWIN)
subprocess.run([PY, BASE + r"\smc_map.py", "--live", "--auto-seq", "--symbol", "Cocoa",
                "--htf", "H4", "--ltf", "M15", "--ttl", "1200", "--validation", "FAIL", "--state", "OBSERVE",
                "--desk-mode", "VALIDATE - observe-only",
                "--news-file", CF + r"\smc_news_Cocoa.txt", "--ticket-file", CF + r"\smc_ticket_Cocoa.txt",
                "--out-dir", CF],
               creationflags=NOWIN)
