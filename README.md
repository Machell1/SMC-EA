# SMC EA — Smart-Money Command Center for MetaTrader 5

An on-chart **Smart Money Concepts command center** for Deriv MT5, driven by a Python
desk engine. The EA/indicator (`mql5/SMC_CommandCenter.mq5`) renders a live dashboard
panel plus the full SMC map — order blocks, fair value gaps, liquidity pools (EQH/EQL),
BOS/CHoCH markers, dealing-range channel and equilibrium, trend-regime line, and marked
candidate trades (entry / SL / TP with risk & reward zones).

**It is draw-only by design.** The indicator never places orders. The desk computes,
draws, and alerts; the operator decides.

## Architecture

```
Python desk engine (smc_map.py, every 5 min via Task Scheduler)
   |  computes SMC structure from live candles (MetaTrader5 python API)
   v
cmd_SMC_<SYMBOL>.txt   -->  atomic write, MT5 Common\Files sandbox
   |  polled every 2 s
   v
SMC_CommandCenter (indicator on the chart)  -- draws panel + zones
   |
ack_SMC_<SYMBOL>.txt   -->  render confirmation back to the desk
```

- One indicator instance per chart; each reads only its own `cmd_SMC_<symbol>.txt`.
- Semicolon line protocol, ANSI/ASCII, atomic temp+rename writes (no partial reads).
- `trend_engine.py` overlays a separately-validated trend-following state
  (long-only above SMA200 with a chandelier trail).

## Files

| File | Role |
|---|---|
| `mql5/SMC_CommandCenter.mq5` | the chart EA/indicator (dashboard + all drawing) |
| `smc_map.py` | desk engine: SMC detection + command-file writer (incl. the gold M15 killzone ruleset) |
| `trend_engine.py` | validated trend-harness state (long>SMA200, Donchian entry, ATR trail) |
| `smc_m15_backtest.py` | faithful M15 backtest of the exact pipeline (no lookahead, real costs, random-entry control) |
| `fetch_history.py` | pull deep candle history to CSV (any timeframe) |
| `duka_convert.py` | convert free Dukascopy M15 exports to the backtest CSV format (validation without MT5) |
| `validate_symbol.py`, `validate_filtered.py`, `head_to_head.py` | SMC validation harnesses (OOS folds, regime-matched random controls, DSR) |
| `trend_harness.py`, `trend_val.py` | trend-strategy validation |
| `scan_universe.py` | scan every broker symbol for strong trend candidates |
| `watchdog.bat`, `btc_refresh.py`, `cocoa_refresh.py` | 5-minute refresh runners (Windows Task Scheduler) |

## Install

1. Compile `mql5/SMC_CommandCenter.mq5` (MetaEditor) and attach it to a chart.
2. `pip install MetaTrader5`, then run the engine once:
   `python smc_map.py --live --auto-seq --symbol XAUUSD --htf H4 --ltf M15 --out-dir "<Terminal>\Common\Files"`
3. Schedule that command every 5 minutes (Task Scheduler) to keep the chart live.

## Honest validation status (read before trading anything)

This project is validation-first. Everything below was measured on real broker data
with out-of-sample folds, real spread+slippage, and **regime-matched random-entry
controls** (an entry only counts as an edge if it beats a coin flip taking the same
regime and exit).

- **H1 SMC entries: NO edge.** All four concepts (OB, FVG, BOS, sweep) failed on
  8.5y XAUUSD and 10.5y EURUSD — negative or no better than random out-of-sample.
- **Trend filters don't rescue them**: raw results improve but the same filter applied
  to the random control improves it just as much (beta, not alpha).
- **The one validated system is dumb trend-following** (long > SMA200, Donchian-20
  entry, BE+3xATR chandelier trail) on **gold H1**: 9/9 positive years, DSR 1.00 both
  folds, roughly double buy-and-hold at a third of the drawdown. It is regime beta,
  gold-specific (fails on EURUSD; NAS100 data-insufficient).
- **M15 work in progress**: the doctrine pipeline generates ~4 trades/year (signal
  starvation). An M15-native restructure (H4 bias + M15 CHoCH + M15 zone entry) trades
  ~200/year and **beats its random control in both folds on XAUUSD and BTCUSD**
  (+0.15 to +0.25R/trade over random) — the first SMC configuration to do so — but raw
  train-fold expectancy is ~breakeven. Filter variants currently under test
  (sweep-first on gold; session-window and trail-exit on BTC show both-folds-positive
  raw results, pending a deflated-Sharpe gate at the honest cross-variant trial count).
- **Gold M15 killzone ruleset (research round, Jul 2026)**: see the section below.
  It beats its random control in both folds (+0.34R / +0.43R per trade over random)
  but the raw train fold is still negative and the variant count means it does NOT
  clear a deflated-Sharpe gate. Observe-only.
- Until a ruleset passes that gate, **the EA stays signal-only.** Any future
  auto-trading build ships with LIVE mode OFF by default, hard server-side stops,
  per-trade and daily risk caps, and a consecutive-loss circuit breaker.

## Gold M15 killzone ruleset (research round, Jul 2026)

`smc_map.detect_gold_m15` is a mechanical encoding of the community-consensus SMC
playbook for XAUUSD M15, distilled from strategy guides and trader-forum discussion
(TradingNX top-down guide, A.K Pro Traders SMC workflow, Liquidity Hunters killzone
playbooks, Complete Traders Edge ICT gold setups, ICT Silver Bullet material, plus
the r/Forex-style skeptic threads that stress mechanical definitions and honest
controls). The desk auto-activates it for `XAU*` symbols on M15 (`--ruleset auto`).

The sequence (every leg is a real OHLC level; no invented prices):

1. **Killzone time gate** — London 07:00–10:00 UTC or New York 12:30–16:00 UTC.
   Asian-session and off-hours signals are refused outright.
2. **Sweep-first** — a recent (≤8 bars) raid of a *named* liquidity pool: Asian-range
   high/low, prior-day high/low, or an EQH/EQL cluster; wick through, body closes back.
   No sweep = no entry (the single loudest piece of community advice).
3. **Displacement MSS** — a CHoCH/BOS in the trade direction *after* the sweep whose
   break bar is a quantified displacement candle (body ≥ 50% of range, range ≥ 1.2×ATR14).
   "It looked displaced" is not testable; this is.
4. **Zone entry** — the M15 FVG (preferred) or OB left by the displacement leg
   (zones older than the sweep are refused). Entry at the zone edge; the popular
   50%-of-FVG "consequent encroachment" entry is available (`ce`) but measured worse.
5. **Stop beyond the sweep wick** + 0.10×ATR buffer — gold overshoots levels; stops at
   the zone border get harvested.
6. **Target = opposing liquidity pool**, capped at 3R (scale-out proxy), minimum 1.5R.
7. **Premium/discount** — longs only below the dealing-range equilibrium, shorts only
   above (skippable via `nopd`, measured worse without it).
8. **H4 bias alignment** — longs only in H4 bullish structure, shorts only in bearish.

The chart shows the full story: Asian-range box, PDH/PDL liquidity rays, a magenta
SWEEP marker on the raid wick, killzone status on the panel, and entry/SL/TP when the
whole sequence confirms (`KZ_CONFIRMED`).

**Honest validation** (6.5y Dukascopy XAUUSD M15 2020-2026, 30pt spread + $0.07 slip,
train/test split at 2024, regime-matched random-entry controls, BE@1R + 2×ATR trail):

```
python duka_convert.py xauusd-m15-bid-*.csv xauusd_m15.csv 30
python smc_m15_backtest.py xauusd_m15.csv 0.01 0.07 2024 XAUUSD gold trail

TRAIN n=18  win%=16.7  expR=-0.214  | random=-0.557  EDGE=+0.343
TEST  n= 9  win%=33.3  expR=+0.071  | random=-0.359  EDGE=+0.430
```

- It beats its random control in **both** folds — consistent with the M15 restructure
  finding that sweep-gated M15 entries carry real information.
- But raw train-fold expectancy is negative, the trade count is tiny (~7 signals/yr —
  the strict sweep→MSS→fresh-zone chain rarely lines up), and ~15 rule variants were
  measured to land here, so this does **not** clear a deflated-Sharpe gate. It ships
  as an observe-only overlay, same as everything else.
- Findings that contradict the chat-room lore, measured on the same harness: the
  CE (50% FVG) entry filled less and earned less than the zone edge; RR≥2.0 minimum
  filtered out the trades that paid; the "trade only Tue–Thu" advice made both folds
  worse; dropping premium/discount or H4-bias alignment degraded the edge.

**This is not financial advice. Most tested SMC entries had no edge. Trade at your own risk.**
