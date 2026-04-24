# Stock Market Maker Game

A terminal game where you trade one stock over multiple rounds.

You can:
- Buy shares (`long` exposure)
- Sell shares (`short` exposure)
- Hold and wait

Your objective is to maximize PnL **and** end with no position (`position = 0`).

## What's New: Market Maker Engine

This repository now includes a sophisticated **automated market making engine** (`mm_engine.py`) with:

- **Dynamic bid/ask quoting** with volatility-aware spreads
- **Inventory-skewed pricing** to manage position risk  
- **Risk mechanics** including position limits and stop losses
- **Order lifecycle management** with cancel/replace logic
- **Fill handling** with PnL tracking

See [MM_ENGINE_DOCS.md](MM_ENGINE_DOCS.md) for detailed documentation.

### Try the Engine Demo

```bash
python3 demo_mm_engine.py --rounds 100 --seed 42
```

This runs a simulation showing the engine automatically making markets.

## Run the Original Game

```bash
python3 market_maker_game.py
```

Optional flags:

```bash
python3 market_maker_game.py --rounds 30 --seed 42
```

## Commands During Game

- `b <qty>`: buy shares
- `s <qty>`: sell shares (or short if you are not long enough)
- `h`: hold
- `?`: show help
- `q`: quit early

## Mechanics

- Prices move each round with random noise and light momentum.
- Trades cross a bid/ask spread.
- Fees are charged per share.
- If you end with a non-zero position, the game force-liquidates your book and applies a penalty.

That means final score rewards both profitable trading and risk discipline.

## Testing

Run the market maker engine tests:

```bash
python3 -m unittest test_mm_engine -v
```

All 31 tests should pass.
