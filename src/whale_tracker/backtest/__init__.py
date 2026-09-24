"""Historical backtest: replays REAL past market data through the same
pipeline simulate.py drives (simulate.run_cycle, unchanged) instead of
synthetic random walks.

Why it exists: calibrate.py's own finding (see paper_trading.py's
docstring) is that a no-drift GBM price path has no exploitable
structure by construction, so no simulation can say whether this
strategy has a real edge. Real paper trading can, but Kademe 3's
"strong" gate is rare enough that waiting for enough closed positions
takes weeks. Replaying the last N days of real price, funding,
Fear&Greed and exchange-wallet stablecoin flow answers the same
question now, with known limitations (see run.py's LIMITATIONS)."""
