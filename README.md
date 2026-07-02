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
| `smc_map.py` | desk engine: SMC detection + command-file writer |
| `trend_engine.py` | validated trend-harness state (long>SMA200, Donchian entry, ATR trail) |
| `smc_m15_backtest.py` | faithful M15 backtest of the exact pipeline (no lookahead, real costs, random-entry control) |
| `fetch_history.py` | pull deep candle history to CSV (any timeframe) |
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
- Until a ruleset passes that gate, **the EA stays signal-only.** Any future
  auto-trading build ships with LIVE mode OFF by default, hard server-side stops,
  per-trade and daily risk caps, and a consecutive-loss circuit breaker.

**This is not financial advice. Most tested SMC entries had no edge. Trade at your own risk.**
