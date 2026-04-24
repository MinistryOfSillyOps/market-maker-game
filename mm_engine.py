#!/usr/bin/env python3
"""Market Maker Engine - Core algorithms for automated market making.

This module implements the core market making algorithms including:
- Dynamic bid/ask quoting
- Inventory-skewed pricing
- Volatility-aware spreads
- Risk mechanics (inventory limits, end-of-round penalties, capital constraints)
- Order lifecycle management
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order status enumeration."""
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    PARTIAL = "PARTIAL"


@dataclass
class MarketSnapshot:
    """Market data snapshot.
    
    Contains current market state including best bid/ask prices,
    last trade price, and timestamp.
    """
    best_bid_price: Optional[float] = None
    best_ask_price: Optional[float] = None
    last_trade_price: float = 100.0
    mid_price: float = 100.0
    timestamp: int = 0  # milliseconds


@dataclass
class Order:
    """Order representation.
    
    Tracks an individual order with its price, quantity, and status.
    """
    id: str
    side: OrderSide
    price: float
    qty: int
    timestamp: int
    status: OrderStatus = OrderStatus.OPEN


@dataclass
class Fill:
    """Fill/execution event.
    
    Represents a trade execution against one of our orders.
    """
    order_id: str
    side: OrderSide
    price: float
    qty: int
    timestamp: int


@dataclass
class MMState:
    """Market maker state.
    
    Tracks current cash, position, orders, and PnL.
    """
    cash: float
    position: int = 0  # signed inventory (+long / -short)
    avg_entry_price: float = 0.0
    open_orders: dict[str, Order] = field(default_factory=dict)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    equity: float = 0.0
    initial_equity: float = 0.0
    
    def __post_init__(self):
        """Initialize equity tracking."""
        if self.initial_equity == 0.0:
            self.initial_equity = self.cash


@dataclass
class MMParams:
    """Market maker parameters.
    
    Configuration for the market making strategy including spread,
    volatility, inventory, and risk controls.
    """
    # Basic quoting
    base_spread_ticks: int = 4
    tick_size: float = 0.01
    quote_size: int = 50
    
    # Volatility behavior
    vol_lookback_n: int = 50
    vol_multiplier: float = 10.0
    
    # Inventory control
    inv_skew_k: float = 0.002  # reservation price shift per unit inventory
    max_position: int = 600
    soft_position: int = 300
    
    # Quoting behavior
    refresh_ms: int = 250
    price_improve_ticks: int = 0  # optional: step inside NBBO
    
    # Risk controls
    max_order_age_ms: int = 1000
    stop_loss_equity: Optional[float] = None


class ReturnsBuffer:
    """Rolling buffer for price returns calculation.
    
    Maintains a fixed-size buffer of log returns for volatility estimation.
    """
    
    def __init__(self, max_size: int):
        """Initialize returns buffer.
        
        Args:
            max_size: Maximum number of returns to keep
        """
        self.max_size = max_size
        self.returns: deque[float] = deque(maxlen=max_size)
        self.last_mid: Optional[float] = None
    
    def push(self, return_value: float) -> None:
        """Add a return to the buffer.
        
        Args:
            return_value: Log return to add
        """
        self.returns.append(return_value)
    
    def size(self) -> int:
        """Get current buffer size."""
        return len(self.returns)
    
    def values(self) -> list[float]:
        """Get all returns as a list."""
        return list(self.returns)


def compute_mid(snapshot: MarketSnapshot) -> float:
    """Compute mid price from market snapshot.
    
    Args:
        snapshot: Market data snapshot
        
    Returns:
        Mid price computed as average of bid/ask, or last trade if missing
    """
    if snapshot.best_bid_price is not None and snapshot.best_ask_price is not None:
        return (snapshot.best_bid_price + snapshot.best_ask_price) / 2.0
    else:
        return snapshot.last_trade_price


def update_returns_buffer(mid: float, returns_buffer: ReturnsBuffer) -> None:
    """Update returns buffer with new mid price.
    
    Computes log return from previous mid price and adds to buffer.
    
    Args:
        mid: Current mid price
        returns_buffer: Returns buffer to update
    """
    prev_mid = returns_buffer.last_mid
    if prev_mid is not None and prev_mid > 0:
        r = math.log(mid / prev_mid)
        returns_buffer.push(r)
    returns_buffer.last_mid = mid


def estimate_vol(returns_buffer: ReturnsBuffer) -> float:
    """Estimate volatility from returns buffer.
    
    Computes standard deviation of log returns.
    
    Args:
        returns_buffer: Buffer containing price returns
        
    Returns:
        Volatility estimate (standard deviation), or 0 if insufficient data
    """
    if returns_buffer.size() < 2:
        return 0.0
    
    values = returns_buffer.values()
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(variance)


def vol_to_ticks(vol: float, vol_multiplier: float = 1.0) -> int:
    """Convert volatility to tick adjustment.
    
    Args:
        vol: Volatility estimate
        vol_multiplier: Multiplier for volatility scaling
        
    Returns:
        Number of ticks to add to spread
    """
    # Scale volatility to ticks (simple linear mapping)
    # vol is typically a small number (e.g., 0.001-0.1)
    # scale up to meaningful tick counts
    return int(vol * 1000 * vol_multiplier)


def compute_dynamic_spread_ticks(params: MMParams, vol: float) -> int:
    """Compute dynamic spread based on volatility.
    
    Args:
        params: Market maker parameters
        vol: Current volatility estimate
        
    Returns:
        Spread in ticks (minimum 1)
    """
    extra = vol_to_ticks(vol, params.vol_multiplier)
    return max(1, params.base_spread_ticks + extra)


def compute_reservation_price(mid: float, position: int, params: MMParams) -> float:
    """Compute reservation price with inventory skew.
    
    Reservation price shifts opposite to inventory:
    - Long inventory -> lower reservation price -> more eager to sell
    - Short inventory -> higher reservation price -> more eager to buy
    
    Args:
        mid: Current mid price
        position: Current inventory position
        params: Market maker parameters
        
    Returns:
        Reservation price adjusted for inventory
    """
    return mid - (params.inv_skew_k * position)


def round_to_tick(price: float, tick_size: float) -> float:
    """Round price to nearest tick.
    
    Args:
        price: Raw price
        tick_size: Tick size for rounding
        
    Returns:
        Price rounded to nearest tick
    """
    # Use round() with proper decimal places to avoid floating point issues
    ticks = round(price / tick_size)
    result = ticks * tick_size
    # Round to avoid floating point precision issues
    decimals = len(str(tick_size).split('.')[-1]) if '.' in str(tick_size) else 0
    return round(result, decimals)


def build_quotes(
    snapshot: MarketSnapshot,
    state: MMState,
    params: MMParams,
    vol: float
) -> tuple[float, float]:
    """Build bid and ask quote prices.
    
    Computes quote prices based on:
    - Dynamic spread (base + volatility adjustment)
    - Reservation price (inventory skew)
    - Optional price improvement inside NBBO
    - Non-crossing constraint
    
    Args:
        snapshot: Current market snapshot
        state: Current MM state
        params: MM parameters
        vol: Current volatility estimate
        
    Returns:
        Tuple of (bid_price, ask_price)
    """
    mid = snapshot.mid_price
    
    # Compute dynamic spread
    spread_ticks = compute_dynamic_spread_ticks(params, vol)
    half_spread = (spread_ticks * params.tick_size) / 2.0
    
    # Compute reservation price with inventory skew
    r = compute_reservation_price(mid, state.position, params)
    
    # Baseline quotes around reservation price
    raw_bid = r - half_spread
    raw_ask = r + half_spread
    
    # Optional: price-improve inside NBBO
    if params.price_improve_ticks > 0:
        if snapshot.best_bid_price is not None:
            improved_bid = snapshot.best_bid_price + params.price_improve_ticks * params.tick_size
            raw_bid = min(raw_bid, improved_bid)
        if snapshot.best_ask_price is not None:
            improved_ask = snapshot.best_ask_price - params.price_improve_ticks * params.tick_size
            raw_ask = max(raw_ask, improved_ask)
    
    # Round to tick size
    bid = round_to_tick(raw_bid, params.tick_size)
    ask = round_to_tick(raw_ask, params.tick_size)
    
    # Prevent crossed quotes (ensure bid < ask by at least 1 tick)
    # Use a small epsilon for floating point comparison
    if bid >= ask - params.tick_size * 0.5:
        bid = round_to_tick(ask - params.tick_size, params.tick_size)
    
    return (bid, ask)


def effective_quote_sizes(state: MMState, params: MMParams) -> tuple[int, int]:
    """Compute effective quote sizes based on position limits.
    
    Reduces quote size on the risk-increasing side when approaching position limits.
    
    Args:
        state: Current MM state
        params: MM parameters
        
    Returns:
        Tuple of (buy_qty, sell_qty)
    """
    buy_size = params.quote_size
    sell_size = params.quote_size
    
    # Long position: reduce buys, keep sells
    if state.position >= params.soft_position:
        if params.max_position > params.soft_position:
            ratio = (state.position - params.soft_position) / (params.max_position - params.soft_position)
            buy_size = max(0, int(params.quote_size * (1 - ratio)))
        else:
            buy_size = 0
        sell_size = params.quote_size
    
    # Short position: reduce sells, keep buys
    if state.position <= -params.soft_position:
        if params.max_position > params.soft_position:
            ratio = (abs(state.position) - params.soft_position) / (params.max_position - params.soft_position)
            sell_size = max(0, int(params.quote_size * (1 - ratio)))
        else:
            sell_size = 0
        buy_size = params.quote_size
    
    # Hard limits
    if state.position >= params.max_position:
        buy_size = 0
    if state.position <= -params.max_position:
        sell_size = 0
    
    return (buy_size, sell_size)


def update_unrealized_pnl(state: MMState, mark_price: float) -> None:
    """Update unrealized PnL based on mark price.
    
    Args:
        state: MM state to update
        mark_price: Current mark/mid price
    """
    if state.position != 0 and state.avg_entry_price != 0:
        state.unrealized_pnl = state.position * (mark_price - state.avg_entry_price)
    else:
        state.unrealized_pnl = 0.0
    
    state.equity = state.cash + state.position * mark_price


def update_avg_entry_price(state: MMState) -> None:
    """Update average entry price after fills.
    
    Uses simple average cost method.
    
    Args:
        state: MM state to update
    """
    # This is called after fills update cash and position
    # For simplicity, we track cash-invested / position
    # In reality, this would use FIFO lots or weighted average
    if state.position == 0:
        state.avg_entry_price = 0.0
    # Note: avg_entry_price is updated in on_fill based on the fill itself


class ExchangeSim:
    """Exchange simulator interface.
    
    Provides interface for sending orders and receiving market events.
    """
    
    def __init__(self):
        """Initialize exchange simulator."""
        self.next_order_id = 1
    
    def send_limit_order(self, side: OrderSide, price: float, qty: int, timestamp: int) -> str:
        """Send a limit order to the exchange.
        
        Args:
            side: Order side (BUY or SELL)
            price: Limit price
            qty: Order quantity
            timestamp: Order timestamp
            
        Returns:
            Order ID
        """
        order_id = f"ORD{self.next_order_id}"
        self.next_order_id += 1
        return order_id
    
    def send_cancel(self, order_id: str) -> None:
        """Cancel an order.
        
        Args:
            order_id: ID of order to cancel
        """
        pass
    
    def cancel_all_orders(self) -> None:
        """Cancel all open orders."""
        pass


class MarketMakerEngine:
    """Market maker engine.
    
    Main engine implementing the market making algorithm including:
    - Market data handling
    - Quote generation
    - Order management
    - Risk controls
    - Fill handling
    """
    
    def __init__(
        self,
        params: MMParams,
        exchange: ExchangeSim,
        initial_cash: float = 10000.0
    ):
        """Initialize market maker engine.
        
        Args:
            params: Market maker parameters
            exchange: Exchange simulator interface
            initial_cash: Starting cash
        """
        self.params = params
        self.exchange = exchange
        self.state = MMState(cash=initial_cash, initial_equity=initial_cash)
        self.returns_buffer = ReturnsBuffer(params.vol_lookback_n)
        self.last_refresh_time = 0
        self.vol = 0.0
        self.stopped = False  # Set to true when stop loss triggered
    
    def cancel_stale_orders(self, now: int) -> None:
        """Cancel orders that have exceeded max age.
        
        Args:
            now: Current timestamp in milliseconds
        """
        stale_orders = []
        for order_id, order in self.state.open_orders.items():
            age = now - order.timestamp
            if age > self.params.max_order_age_ms:
                stale_orders.append(order_id)
        
        for order_id in stale_orders:
            self.exchange.send_cancel(order_id)
            order = self.state.open_orders[order_id]
            order.status = OrderStatus.CANCELLED
            del self.state.open_orders[order_id]
    
    def should_refresh_quotes(self, timestamp: int) -> bool:
        """Check if quotes should be refreshed.
        
        Args:
            timestamp: Current timestamp in milliseconds
            
        Returns:
            True if refresh interval has elapsed
        """
        # First refresh should always happen
        if self.last_refresh_time == 0:
            return True
        elapsed = timestamp - self.last_refresh_time
        return elapsed >= self.params.refresh_ms
    
    def cancel_all_orders(self) -> None:
        """Cancel all open orders."""
        self.exchange.cancel_all_orders()
        for order in self.state.open_orders.values():
            order.status = OrderStatus.CANCELLED
        self.state.open_orders.clear()
    
    def on_market_tick(self, snapshot: MarketSnapshot) -> None:
        """Handle market tick event.
        
        Main event loop that:
        1. Updates mid price and volatility
        2. Performs risk checks
        3. Cancels stale orders
        4. Re-quotes on refresh interval
        
        Args:
            snapshot: Current market snapshot
        """
        # 1) Update mid + vol
        snapshot.mid_price = compute_mid(snapshot)
        update_returns_buffer(snapshot.mid_price, self.returns_buffer)
        self.vol = estimate_vol(self.returns_buffer)
        
        # 2) Risk checks
        mark = snapshot.mid_price
        update_unrealized_pnl(self.state, mark)
        
        # Stop loss check
        if self.params.stop_loss_equity is not None:
            if self.state.equity < self.params.stop_loss_equity:
                if not self.stopped:
                    self.cancel_all_orders()
                    self.stopped = True
                return
        
        # 3) Cancel stale quotes
        self.cancel_stale_orders(snapshot.timestamp)
        
        # 4) Re-quote on refresh interval
        if self.should_refresh_quotes(snapshot.timestamp):
            self.last_refresh_time = snapshot.timestamp
            
            # Build new quotes
            bid_px, ask_px = build_quotes(snapshot, self.state, self.params, self.vol)
            buy_qty, sell_qty = effective_quote_sizes(self.state, self.params)
            
            # Cancel/Replace: always cancel existing and re-post
            self.cancel_all_orders()
            
            # Place new orders
            if buy_qty > 0:
                order_id = self.exchange.send_limit_order(
                    OrderSide.BUY, bid_px, buy_qty, snapshot.timestamp
                )
                order = Order(
                    id=order_id,
                    side=OrderSide.BUY,
                    price=bid_px,
                    qty=buy_qty,
                    timestamp=snapshot.timestamp,
                    status=OrderStatus.OPEN
                )
                self.state.open_orders[order_id] = order
            
            if sell_qty > 0:
                order_id = self.exchange.send_limit_order(
                    OrderSide.SELL, ask_px, sell_qty, snapshot.timestamp
                )
                order = Order(
                    id=order_id,
                    side=OrderSide.SELL,
                    price=ask_px,
                    qty=sell_qty,
                    timestamp=snapshot.timestamp,
                    status=OrderStatus.OPEN
                )
                self.state.open_orders[order_id] = order
    
    def on_fill(self, fill: Fill, snapshot: MarketSnapshot) -> None:
        """Handle fill event.
        
        Updates order state, cash, position, and PnL.
        
        Args:
            fill: Fill event
            snapshot: Current market snapshot
        """
        # Get the order
        if fill.order_id not in self.state.open_orders:
            # Order already removed or doesn't exist
            return
        
        order = self.state.open_orders[fill.order_id]
        
        # Update order quantity
        order.qty -= fill.qty
        if order.qty <= 0:
            order.status = OrderStatus.FILLED
            del self.state.open_orders[fill.order_id]
        else:
            order.status = OrderStatus.PARTIAL
        
        # Update position and cash
        old_position = self.state.position
        old_cost_basis = self.state.avg_entry_price * abs(old_position) if old_position != 0 else 0.0
        
        if fill.side == OrderSide.BUY:
            self.state.position += fill.qty
            self.state.cash -= fill.qty * fill.price
            
            # Update average entry price for longs
            if self.state.position > 0:
                total_cost = old_cost_basis + (fill.qty * fill.price)
                self.state.avg_entry_price = total_cost / self.state.position
            elif self.state.position == 0:
                self.state.avg_entry_price = 0.0
            else:
                # Covering shorts - realized PnL
                self.state.avg_entry_price = 0.0  # Simplified
        
        elif fill.side == OrderSide.SELL:
            self.state.position -= fill.qty
            self.state.cash += fill.qty * fill.price
            
            # Update average entry price for shorts
            if self.state.position < 0:
                total_proceeds = old_cost_basis + (fill.qty * fill.price)
                self.state.avg_entry_price = total_proceeds / abs(self.state.position)
            elif self.state.position == 0:
                self.state.avg_entry_price = 0.0
            else:
                # Closing longs - realized PnL
                self.state.avg_entry_price = 0.0  # Simplified
        
        # Update PnL
        update_unrealized_pnl(self.state, snapshot.mid_price)
        self.state.realized_pnl = (
            self.state.cash + self.state.position * snapshot.mid_price - self.state.initial_equity
        )
