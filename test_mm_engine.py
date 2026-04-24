#!/usr/bin/env python3
"""Unit tests for the market maker engine."""

import unittest
from mm_engine import (
    MarketSnapshot,
    Order,
    Fill,
    MMState,
    MMParams,
    OrderSide,
    OrderStatus,
    ReturnsBuffer,
    compute_mid,
    update_returns_buffer,
    estimate_vol,
    compute_dynamic_spread_ticks,
    compute_reservation_price,
    round_to_tick,
    build_quotes,
    effective_quote_sizes,
    update_unrealized_pnl,
    ExchangeSim,
    MarketMakerEngine,
)


class TestMarketDataHandling(unittest.TestCase):
    """Test market data handling functionality."""
    
    def test_compute_mid_with_bid_ask(self):
        """Test mid price computation with bid and ask."""
        snapshot = MarketSnapshot(
            best_bid_price=99.5,
            best_ask_price=100.5,
            last_trade_price=100.0
        )
        mid = compute_mid(snapshot)
        self.assertEqual(mid, 100.0)
    
    def test_compute_mid_fallback_to_last_trade(self):
        """Test mid price falls back to last trade when bid/ask missing."""
        snapshot = MarketSnapshot(
            best_bid_price=None,
            best_ask_price=None,
            last_trade_price=100.0
        )
        mid = compute_mid(snapshot)
        self.assertEqual(mid, 100.0)
    
    def test_compute_mid_partial_missing(self):
        """Test mid price with only one side missing."""
        snapshot = MarketSnapshot(
            best_bid_price=99.5,
            best_ask_price=None,
            last_trade_price=100.0
        )
        mid = compute_mid(snapshot)
        self.assertEqual(mid, 100.0)  # Falls back to last trade
    
    def test_returns_buffer_update(self):
        """Test returns buffer updates correctly."""
        buffer = ReturnsBuffer(max_size=50)
        
        # First update - no return computed
        update_returns_buffer(100.0, buffer)
        self.assertEqual(buffer.size(), 0)
        
        # Second update - computes return
        update_returns_buffer(101.0, buffer)
        self.assertEqual(buffer.size(), 1)
        
        # Returns should be log returns
        returns = buffer.values()
        self.assertAlmostEqual(returns[0], 0.00995, places=4)
    
    def test_estimate_vol_insufficient_data(self):
        """Test volatility estimation with insufficient data."""
        buffer = ReturnsBuffer(max_size=50)
        vol = estimate_vol(buffer)
        self.assertEqual(vol, 0.0)
        
        buffer.push(0.01)
        vol = estimate_vol(buffer)
        self.assertEqual(vol, 0.0)  # Need at least 2 data points
    
    def test_estimate_vol_with_data(self):
        """Test volatility estimation with sufficient data."""
        buffer = ReturnsBuffer(max_size=50)
        
        # Add some returns
        returns = [0.01, -0.005, 0.015, -0.01, 0.005]
        for r in returns:
            buffer.push(r)
        
        vol = estimate_vol(buffer)
        self.assertGreater(vol, 0.0)
        self.assertLess(vol, 0.1)  # Reasonable volatility


class TestQuoteGeneration(unittest.TestCase):
    """Test quote generation functionality."""
    
    def test_dynamic_spread_base(self):
        """Test dynamic spread with no volatility."""
        params = MMParams(base_spread_ticks=4)
        spread = compute_dynamic_spread_ticks(params, 0.0)
        self.assertEqual(spread, 4)
    
    def test_dynamic_spread_with_volatility(self):
        """Test dynamic spread widens with volatility."""
        params = MMParams(base_spread_ticks=4, vol_multiplier=10.0)
        spread_low = compute_dynamic_spread_ticks(params, 0.001)
        spread_high = compute_dynamic_spread_ticks(params, 0.01)
        self.assertGreater(spread_high, spread_low)
    
    def test_dynamic_spread_minimum(self):
        """Test dynamic spread never goes below 1."""
        params = MMParams(base_spread_ticks=0, vol_multiplier=0.0)
        spread = compute_dynamic_spread_ticks(params, 0.0)
        self.assertEqual(spread, 1)
    
    def test_reservation_price_long_inventory(self):
        """Test reservation price shifts down with long inventory."""
        params = MMParams(inv_skew_k=0.002)
        mid = 100.0
        
        # Long position (positive inventory)
        res_price = compute_reservation_price(mid, 100, params)
        self.assertLess(res_price, mid)
        self.assertEqual(res_price, 99.8)  # 100 - (0.002 * 100)
    
    def test_reservation_price_short_inventory(self):
        """Test reservation price shifts up with short inventory."""
        params = MMParams(inv_skew_k=0.002)
        mid = 100.0
        
        # Short position (negative inventory)
        res_price = compute_reservation_price(mid, -100, params)
        self.assertGreater(res_price, mid)
        self.assertEqual(res_price, 100.2)  # 100 - (0.002 * -100)
    
    def test_reservation_price_flat(self):
        """Test reservation price equals mid when flat."""
        params = MMParams(inv_skew_k=0.002)
        mid = 100.0
        
        res_price = compute_reservation_price(mid, 0, params)
        self.assertEqual(res_price, mid)
    
    def test_round_to_tick(self):
        """Test price rounding to tick size."""
        self.assertEqual(round_to_tick(100.234, 0.01), 100.23)
        self.assertEqual(round_to_tick(100.236, 0.01), 100.24)
        self.assertEqual(round_to_tick(100.5, 0.25), 100.5)
        self.assertEqual(round_to_tick(100.6, 0.25), 100.5)
        self.assertEqual(round_to_tick(100.7, 0.25), 100.75)
    
    def test_build_quotes_non_crossing(self):
        """Test quotes are never crossed."""
        snapshot = MarketSnapshot(
            best_bid_price=100.0,
            best_ask_price=100.1,
            mid_price=100.05
        )
        state = MMState(cash=10000.0, position=0)
        params = MMParams(base_spread_ticks=1, tick_size=0.01)
        
        bid, ask = build_quotes(snapshot, state, params, 0.0)
        self.assertLess(bid, ask)
        # Allow for floating point tolerance (99% of tick size)
        FLOAT_TOLERANCE = 0.99
        self.assertGreaterEqual(ask - bid, params.tick_size * FLOAT_TOLERANCE)
    
    def test_build_quotes_inventory_skew(self):
        """Test quotes adjust for inventory."""
        snapshot = MarketSnapshot(mid_price=100.0)
        params = MMParams(
            base_spread_ticks=4,
            tick_size=0.01,
            inv_skew_k=0.01
        )
        
        # Flat position
        state_flat = MMState(cash=10000.0, position=0)
        bid_flat, ask_flat = build_quotes(snapshot, state_flat, params, 0.0)
        
        # Long position - quotes should shift down
        state_long = MMState(cash=10000.0, position=100)
        bid_long, ask_long = build_quotes(snapshot, state_long, params, 0.0)
        self.assertLess(bid_long, bid_flat)
        self.assertLess(ask_long, ask_flat)
        
        # Short position - quotes should shift up
        state_short = MMState(cash=10000.0, position=-100)
        bid_short, ask_short = build_quotes(snapshot, state_short, params, 0.0)
        self.assertGreater(bid_short, bid_flat)
        self.assertGreater(ask_short, ask_flat)


class TestInventoryManagement(unittest.TestCase):
    """Test inventory and size management."""
    
    def test_effective_sizes_flat(self):
        """Test effective sizes with flat position."""
        state = MMState(cash=10000.0, position=0)
        params = MMParams(quote_size=50, soft_position=300, max_position=600)
        
        buy_qty, sell_qty = effective_quote_sizes(state, params)
        self.assertEqual(buy_qty, 50)
        self.assertEqual(sell_qty, 50)
    
    def test_effective_sizes_soft_limit_long(self):
        """Test effective sizes reduce buys when approaching long limit."""
        params = MMParams(quote_size=50, soft_position=300, max_position=600)
        
        # At soft position - start reducing buys
        state = MMState(cash=10000.0, position=300)
        buy_qty, sell_qty = effective_quote_sizes(state, params)
        self.assertEqual(buy_qty, 50)  # At soft limit, still full size
        self.assertEqual(sell_qty, 50)
        
        # Halfway to max
        state = MMState(cash=10000.0, position=450)
        buy_qty, sell_qty = effective_quote_sizes(state, params)
        self.assertLess(buy_qty, 50)
        self.assertGreater(buy_qty, 0)
        self.assertEqual(sell_qty, 50)
    
    def test_effective_sizes_hard_limit_long(self):
        """Test buy size is 0 at hard long limit."""
        state = MMState(cash=10000.0, position=600)
        params = MMParams(quote_size=50, soft_position=300, max_position=600)
        
        buy_qty, sell_qty = effective_quote_sizes(state, params)
        self.assertEqual(buy_qty, 0)
        self.assertEqual(sell_qty, 50)
    
    def test_effective_sizes_hard_limit_short(self):
        """Test sell size is 0 at hard short limit."""
        state = MMState(cash=10000.0, position=-600)
        params = MMParams(quote_size=50, soft_position=300, max_position=600)
        
        buy_qty, sell_qty = effective_quote_sizes(state, params)
        self.assertEqual(buy_qty, 50)
        self.assertEqual(sell_qty, 0)
    
    def test_effective_sizes_never_negative(self):
        """Test effective sizes are never negative."""
        state = MMState(cash=10000.0, position=1000)  # Beyond max
        params = MMParams(quote_size=50, soft_position=300, max_position=600)
        
        buy_qty, sell_qty = effective_quote_sizes(state, params)
        self.assertGreaterEqual(buy_qty, 0)
        self.assertGreaterEqual(sell_qty, 0)


class TestOrderLifecycle(unittest.TestCase):
    """Test order lifecycle management."""
    
    def test_stale_order_cancellation(self):
        """Test stale orders are cancelled."""
        params = MMParams(max_order_age_ms=1000)
        exchange = ExchangeSim()
        engine = MarketMakerEngine(params, exchange)
        
        # Add an order to state
        order = Order(
            id="ORD1",
            side=OrderSide.BUY,
            price=100.0,
            qty=50,
            timestamp=0,
            status=OrderStatus.OPEN
        )
        engine.state.open_orders["ORD1"] = order
        
        # Cancel stale orders after max age
        engine.cancel_stale_orders(1001)
        
        # Order should be removed
        self.assertNotIn("ORD1", engine.state.open_orders)
    
    def test_fresh_order_not_cancelled(self):
        """Test fresh orders are not cancelled."""
        params = MMParams(max_order_age_ms=1000)
        exchange = ExchangeSim()
        engine = MarketMakerEngine(params, exchange)
        
        # Add a fresh order
        order = Order(
            id="ORD1",
            side=OrderSide.BUY,
            price=100.0,
            qty=50,
            timestamp=500,
            status=OrderStatus.OPEN
        )
        engine.state.open_orders["ORD1"] = order
        
        # Try to cancel stale orders
        engine.cancel_stale_orders(1000)
        
        # Order should still be there
        self.assertIn("ORD1", engine.state.open_orders)
    
    def test_refresh_interval(self):
        """Test quote refresh respects interval."""
        params = MMParams(refresh_ms=250)
        exchange = ExchangeSim()
        engine = MarketMakerEngine(params, exchange)
        
        # Should refresh initially (last_refresh_time is 0)
        self.assertTrue(engine.should_refresh_quotes(0))
        
        # Mark as refreshed at timestamp 100
        engine.last_refresh_time = 100
        
        # Should not refresh before interval
        self.assertFalse(engine.should_refresh_quotes(200))
        
        # Should refresh after interval
        self.assertTrue(engine.should_refresh_quotes(350))


class TestFillHandling(unittest.TestCase):
    """Test fill handling and state updates."""
    
    def test_fill_buy_updates_position(self):
        """Test buy fill increases position and decreases cash."""
        params = MMParams()
        exchange = ExchangeSim()
        engine = MarketMakerEngine(params, exchange, initial_cash=10000.0)
        
        # Add order to state
        order = Order(
            id="ORD1",
            side=OrderSide.BUY,
            price=100.0,
            qty=50,
            timestamp=0
        )
        engine.state.open_orders["ORD1"] = order
        
        # Create fill
        fill = Fill(
            order_id="ORD1",
            side=OrderSide.BUY,
            price=100.0,
            qty=50,
            timestamp=100
        )
        
        snapshot = MarketSnapshot(mid_price=100.0)
        engine.on_fill(fill, snapshot)
        
        # Position should increase
        self.assertEqual(engine.state.position, 50)
        
        # Cash should decrease
        self.assertEqual(engine.state.cash, 5000.0)  # 10000 - (50 * 100)
        
        # Order should be filled and removed
        self.assertNotIn("ORD1", engine.state.open_orders)
    
    def test_fill_sell_updates_position(self):
        """Test sell fill decreases position and increases cash."""
        params = MMParams()
        exchange = ExchangeSim()
        engine = MarketMakerEngine(params, exchange, initial_cash=10000.0)
        
        # Set initial position
        engine.state.position = 100
        
        # Add order to state
        order = Order(
            id="ORD1",
            side=OrderSide.SELL,
            price=100.0,
            qty=50,
            timestamp=0
        )
        engine.state.open_orders["ORD1"] = order
        
        # Create fill
        fill = Fill(
            order_id="ORD1",
            side=OrderSide.SELL,
            price=100.0,
            qty=50,
            timestamp=100
        )
        
        snapshot = MarketSnapshot(mid_price=100.0)
        engine.on_fill(fill, snapshot)
        
        # Position should decrease
        self.assertEqual(engine.state.position, 50)
        
        # Cash should increase
        self.assertEqual(engine.state.cash, 15000.0)  # 10000 + (50 * 100)
    
    def test_partial_fill(self):
        """Test partial fill updates order correctly."""
        params = MMParams()
        exchange = ExchangeSim()
        engine = MarketMakerEngine(params, exchange, initial_cash=10000.0)
        
        # Add order to state
        order = Order(
            id="ORD1",
            side=OrderSide.BUY,
            price=100.0,
            qty=100,
            timestamp=0
        )
        engine.state.open_orders["ORD1"] = order
        
        # Create partial fill
        fill = Fill(
            order_id="ORD1",
            side=OrderSide.BUY,
            price=100.0,
            qty=30,
            timestamp=100
        )
        
        snapshot = MarketSnapshot(mid_price=100.0)
        engine.on_fill(fill, snapshot)
        
        # Order should still exist with reduced quantity
        self.assertIn("ORD1", engine.state.open_orders)
        self.assertEqual(engine.state.open_orders["ORD1"].qty, 70)
        self.assertEqual(engine.state.open_orders["ORD1"].status, OrderStatus.PARTIAL)
        
        # Position and cash should update
        self.assertEqual(engine.state.position, 30)
        self.assertEqual(engine.state.cash, 7000.0)
    
    def test_unrealized_pnl_calculation(self):
        """Test unrealized PnL is calculated correctly."""
        state = MMState(cash=10000.0, position=100, avg_entry_price=100.0)
        
        # Mark price increases
        update_unrealized_pnl(state, 105.0)
        self.assertEqual(state.unrealized_pnl, 500.0)  # 100 * (105 - 100)
        
        # Equity includes unrealized gains
        self.assertEqual(state.equity, 20500.0)  # 10000 + 100 * 105
        
        # Mark price decreases
        update_unrealized_pnl(state, 95.0)
        self.assertEqual(state.unrealized_pnl, -500.0)  # 100 * (95 - 100)
        self.assertEqual(state.equity, 19500.0)  # 10000 + 100 * 95


class TestRiskControls(unittest.TestCase):
    """Test risk control functionality."""
    
    def test_stop_loss_triggers(self):
        """Test stop loss cancels orders when equity drops."""
        params = MMParams(stop_loss_equity=9000.0)
        exchange = ExchangeSim()
        engine = MarketMakerEngine(params, exchange, initial_cash=10000.0)
        
        # Add an order
        order = Order(
            id="ORD1",
            side=OrderSide.BUY,
            price=100.0,
            qty=50,
            timestamp=0
        )
        engine.state.open_orders["ORD1"] = order
        
        # Set state to trigger stop loss
        engine.state.position = -100
        engine.state.cash = 5000.0
        
        # Market tick with high price (increases loss on short position)
        snapshot = MarketSnapshot(mid_price=150.0, timestamp=0)
        engine.on_market_tick(snapshot)
        
        # Orders should be cancelled and stopped flag set
        self.assertEqual(len(engine.state.open_orders), 0)
        self.assertTrue(engine.stopped)
    
    def test_no_new_orders_after_stop_loss(self):
        """Test no new orders are placed after stop loss."""
        params = MMParams(stop_loss_equity=9000.0, refresh_ms=100)
        exchange = ExchangeSim()
        engine = MarketMakerEngine(params, exchange, initial_cash=10000.0)
        
        # Trigger stop loss
        engine.state.position = -100
        engine.state.cash = 5000.0
        snapshot = MarketSnapshot(mid_price=150.0, timestamp=0)
        engine.on_market_tick(snapshot)
        
        self.assertTrue(engine.stopped)
        
        # Try to quote again
        snapshot = MarketSnapshot(mid_price=150.0, timestamp=200)
        engine.on_market_tick(snapshot)
        
        # No orders should be placed
        self.assertEqual(len(engine.state.open_orders), 0)


class TestDeterminism(unittest.TestCase):
    """Test deterministic behavior."""
    
    def test_identical_snapshots_produce_identical_quotes(self):
        """Test same inputs produce same outputs."""
        params = MMParams()
        
        # First run
        exchange1 = ExchangeSim()
        engine1 = MarketMakerEngine(params, exchange1, initial_cash=10000.0)
        
        snapshot1 = MarketSnapshot(mid_price=100.0, timestamp=0)
        engine1.on_market_tick(snapshot1)
        
        orders1 = list(engine1.state.open_orders.values())
        
        # Second run with identical inputs
        exchange2 = ExchangeSim()
        engine2 = MarketMakerEngine(params, exchange2, initial_cash=10000.0)
        
        snapshot2 = MarketSnapshot(mid_price=100.0, timestamp=0)
        engine2.on_market_tick(snapshot2)
        
        orders2 = list(engine2.state.open_orders.values())
        
        # Should produce identical quotes
        self.assertEqual(len(orders1), len(orders2))
        if len(orders1) > 0:
            for o1, o2 in zip(orders1, orders2):
                self.assertEqual(o1.side, o2.side)
                self.assertEqual(o1.price, o2.price)
                self.assertEqual(o1.qty, o2.qty)


class TestIntegration(unittest.TestCase):
    """Integration tests for the full engine."""
    
    def test_full_market_making_cycle(self):
        """Test complete market making cycle."""
        params = MMParams(
            base_spread_ticks=4,
            tick_size=0.01,
            quote_size=50,
            refresh_ms=100
        )
        exchange = ExchangeSim()
        engine = MarketMakerEngine(params, exchange, initial_cash=10000.0)
        
        # First market tick
        snapshot = MarketSnapshot(
            best_bid_price=99.95,
            best_ask_price=100.05,
            last_trade_price=100.0,
            timestamp=0
        )
        engine.on_market_tick(snapshot)
        
        # Should have placed orders
        self.assertGreater(len(engine.state.open_orders), 0)
        
        # Get the orders
        buy_orders = [o for o in engine.state.open_orders.values() if o.side == OrderSide.BUY]
        sell_orders = [o for o in engine.state.open_orders.values() if o.side == OrderSide.SELL]
        
        self.assertEqual(len(buy_orders), 1)
        self.assertEqual(len(sell_orders), 1)
        
        # Simulate a fill on buy side
        buy_order = buy_orders[0]
        fill = Fill(
            order_id=buy_order.id,
            side=OrderSide.BUY,
            price=buy_order.price,
            qty=25,
            timestamp=50
        )
        engine.on_fill(fill, snapshot)
        
        # Position should be updated
        self.assertEqual(engine.state.position, 25)
        
        # Next market tick should re-quote
        snapshot2 = MarketSnapshot(
            best_bid_price=100.05,
            best_ask_price=100.15,
            last_trade_price=100.1,
            timestamp=150
        )
        engine.on_market_tick(snapshot2)
        
        # Should have new orders with inventory skew
        new_orders = list(engine.state.open_orders.values())
        self.assertGreater(len(new_orders), 0)


if __name__ == "__main__":
    unittest.main()
