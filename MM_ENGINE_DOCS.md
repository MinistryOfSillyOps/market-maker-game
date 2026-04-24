# Market Maker Engine Documentation

## Overview

The Market Maker Engine (`mm_engine.py`) implements sophisticated algorithms for automated market making in trading games. The engine manages:

- **Dynamic bid/ask quoting** with volatility-aware spreads
- **Inventory-skewed pricing** to manage position risk
- **Risk controls** including position limits and stop losses
- **Order lifecycle management** with cancel/replace logic
- **Fill handling** with PnL tracking

## Architecture

### Core Data Structures

#### `MarketSnapshot`
Represents current market state:
- `best_bid_price`, `best_ask_price`: Current NBBO (National Best Bid/Offer)
- `last_trade_price`: Most recent trade
- `mid_price`: Computed mid price
- `timestamp`: Market data timestamp in milliseconds

#### `MMState`
Tracks the market maker's current state:
- `cash`: Available cash
- `position`: Signed inventory (positive = long, negative = short)
- `avg_entry_price`: Average entry price for unrealized PnL calculation
- `open_orders`: Dictionary of active orders
- `realized_pnl`, `unrealized_pnl`: Profit and loss tracking
- `equity`: Total value (cash + position * mark)

#### `MMParams`
Configuration parameters for the strategy:

**Basic Quoting:**
- `base_spread_ticks` (default: 4): Base spread in ticks
- `tick_size` (default: 0.01): Minimum price increment
- `quote_size` (default: 50): Default order size

**Volatility Behavior:**
- `vol_lookback_n` (default: 50): Number of returns for volatility calculation
- `vol_multiplier` (default: 10.0): Volatility scaling factor

**Inventory Control:**
- `inv_skew_k` (default: 0.002): Reservation price shift per unit inventory
- `max_position` (default: 600): Hard inventory limit
- `soft_position` (default: 300): Soft limit where size reduction begins

**Quoting Behavior:**
- `refresh_ms` (default: 250): Quote refresh interval in milliseconds
- `price_improve_ticks` (default: 0): Optional improvement inside NBBO

**Risk Controls:**
- `max_order_age_ms` (default: 1000): Maximum order age before cancellation
- `stop_loss_equity` (optional): Stop loss equity threshold

## Key Algorithms

### Mid Price Calculation

The mid price is computed as:
1. Average of best bid and ask if both are available
2. Otherwise, fall back to last trade price

```python
mid = (best_bid + best_ask) / 2  # if both exist
mid = last_trade_price           # otherwise
```

### Volatility Estimation

Volatility is estimated using rolling log returns:
1. Maintain a buffer of the last N log returns
2. Compute standard deviation of returns
3. Return 0 if insufficient data (< 2 points)

```python
log_return = ln(current_mid / previous_mid)
volatility = stddev(returns_buffer)
```

### Dynamic Spread

The spread widens during volatile periods:
```python
spread_ticks = max(1, base_spread_ticks + vol_extra_ticks)
```

Where `vol_extra_ticks` scales with volatility and `vol_multiplier`.

### Reservation Price & Inventory Skew

The reservation price adjusts based on inventory to encourage mean reversion:

```python
reservation_price = mid - (inv_skew_k * position)
```

- **Long inventory (position > 0)**: Reservation price shifts DOWN → quotes shift down → more eager to sell
- **Short inventory (position < 0)**: Reservation price shifts UP → quotes shift up → more eager to buy
- **Flat (position = 0)**: Reservation price equals mid

### Quote Generation

Quotes are built around the reservation price:

```python
half_spread = (spread_ticks * tick_size) / 2
raw_bid = reservation_price - half_spread
raw_ask = reservation_price + half_spread

# Round to tick size
bid = round_to_tick(raw_bid, tick_size)
ask = round_to_tick(raw_ask, tick_size)

# Ensure non-crossing (bid < ask by at least 1 tick)
if bid >= ask:
    bid = ask - tick_size
```

### Position Limits & Size Reduction

Quote sizes are reduced when approaching position limits:

**Long position approaching `max_position`:**
- Buy size reduces linearly from `soft_position` to `max_position`
- At `max_position`, buy size = 0
- Sell size remains full

**Short position approaching `-max_position`:**
- Sell size reduces linearly
- At `-max_position`, sell size = 0
- Buy size remains full

### Order Lifecycle

The engine uses a **cancel/replace** strategy:
1. On each refresh interval, cancel all existing orders
2. Compute new quote prices and sizes
3. Place new orders

Orders are also cancelled if:
- Age exceeds `max_order_age_ms`
- Stop loss is triggered
- Position limits are hit

### Fill Handling

When a fill occurs:
1. Update order status (FILLED or PARTIAL)
2. Update cash: `cash -= qty * price` for buys, `cash += qty * price` for sells
3. Update position: `position += qty` for buys, `position -= qty` for sells
4. Recompute average entry price
5. Update unrealized PnL based on current mark

### Risk Controls

**Stop Loss:**
If equity falls below `stop_loss_equity`:
1. Cancel all open orders
2. Set `stopped = True`
3. Stop placing new orders

**Position Limits:**
Hard limits prevent placing orders that would increase exposure beyond `max_position`:
- At `+max_position`: no new buy orders
- At `-max_position`: no new sell orders

## PnL Calculation

**Unrealized PnL:**
```python
unrealized_pnl = position * (mark_price - avg_entry_price)
```

**Realized PnL (approximation):**
```python
realized_pnl = cash + position * mark_price - initial_equity
```

**Equity:**
```python
equity = cash + position * mark_price
```

## Usage Example

```python
from mm_engine import MMParams, MarketMakerEngine, ExchangeSim, MarketSnapshot

# Configure parameters
params = MMParams(
    base_spread_ticks=4,
    tick_size=0.01,
    quote_size=50,
    vol_multiplier=10.0,
    inv_skew_k=0.002,
    max_position=600,
    soft_position=300,
    refresh_ms=250
)

# Create exchange simulator and engine
exchange = ExchangeSim()
engine = MarketMakerEngine(params, exchange, initial_cash=10000.0)

# Process market tick
snapshot = MarketSnapshot(
    best_bid_price=99.95,
    best_ask_price=100.05,
    last_trade_price=100.0,
    timestamp=0
)
engine.on_market_tick(snapshot)

# Handle fills
fill = Fill(
    order_id="ORD1",
    side=OrderSide.BUY,
    price=99.96,
    qty=25,
    timestamp=50
)
engine.on_fill(fill, snapshot)
```

## Tuning Guide

### Making the Strategy More Conservative
- **Increase** `base_spread_ticks` - wider quotes, less adverse selection
- **Increase** `vol_multiplier` - pull back more in volatile markets
- **Decrease** `max_position` / `soft_position` - tighter risk limits
- **Increase** `inv_skew_k` - more aggressive inventory flattening

### Making the Strategy More Aggressive
- **Decrease** `base_spread_ticks` - tighter quotes, more fills
- **Decrease** `vol_multiplier` - stay in market during volatility
- **Increase** `max_position` - allow larger positions
- **Enable** `price_improve_ticks` - compete inside NBBO
- **Decrease** `refresh_ms` - update quotes more frequently

### Typical Parameter Ranges

| Parameter | Conservative | Moderate | Aggressive |
|-----------|-------------|----------|------------|
| `base_spread_ticks` | 8-10 | 4-6 | 1-3 |
| `vol_multiplier` | 15-20 | 8-12 | 3-7 |
| `max_position` | 300-400 | 500-700 | 800-1000 |
| `inv_skew_k` | 0.005-0.01 | 0.002-0.004 | 0.0005-0.001 |
| `refresh_ms` | 500-1000 | 200-400 | 50-150 |

## Testing

The engine includes comprehensive unit tests covering:
- Market data handling (mid price fallback, volatility estimation)
- Quote generation (non-crossing, inventory skew)
- Position limits and size management
- Order lifecycle and stale order cancellation
- Fill handling and PnL updates
- Risk controls and stop loss
- Determinism

Run tests with:
```bash
python3 -m unittest test_mm_engine -v
```

## Simplifications vs Real Markets

1. **Average cost basis**: Real systems use FIFO lots or cost basis tracking
2. **No market impact**: Assumes fills don't move the market
3. **Simplified volatility**: Uses simple standard deviation, not EWMA or GARCH
4. **No fee modeling**: Doesn't distinguish maker/taker fees
5. **Synchronous fills**: Real markets have asynchronous fill notifications
6. **No partial fills on single order**: Each fill is treated atomically
7. **No order rejection handling**: Assumes orders are always accepted

## Determinism

Given identical inputs (market snapshots, fills, initial state), the engine produces identical outputs. This is crucial for:
- Backtesting reproducibility
- Game replay functionality
- Debugging and analysis

## Performance Considerations

- Quote refresh is O(1) - constant time operation
- Fill handling is O(1) - direct dictionary lookup
- Volatility calculation is O(N) where N = `vol_lookback_n`
- Stale order cancellation is O(M) where M = number of open orders

For typical parameters (N=50, M≤5), the engine can process thousands of ticks per second.
