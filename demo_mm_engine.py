#!/usr/bin/env python3
"""Demo script showing the market maker engine in action.

This script simulates a simple market and demonstrates the engine's behavior.
"""

import random
from mm_engine import (
    MMParams,
    MarketMakerEngine,
    ExchangeSim,
    MarketSnapshot,
    Fill,
    OrderSide,
)


class SimpleMarketSim:
    """Simple market simulator for demonstration."""
    
    def __init__(self, initial_price: float = 100.0, volatility: float = 0.5):
        """Initialize market simulator.
        
        Args:
            initial_price: Starting price
            volatility: Price volatility
        """
        self.price = initial_price
        self.volatility = volatility
        self.timestamp = 0
        self.tick_size = 0.01
    
    def generate_snapshot(self) -> MarketSnapshot:
        """Generate next market snapshot with random walk.
        
        Returns:
            MarketSnapshot with simulated prices
        """
        # Random walk with drift
        change = random.gauss(0.0, self.volatility)
        self.price = max(1.0, self.price + change)
        
        # Generate bid/ask spread
        spread = 0.10
        bid = self.price - spread / 2
        ask = self.price + spread / 2
        
        snapshot = MarketSnapshot(
            best_bid_price=bid,
            best_ask_price=ask,
            last_trade_price=self.price,
            timestamp=self.timestamp
        )
        
        self.timestamp += 100  # 100ms per tick
        return snapshot
    
    def simulate_fills(self, engine: MarketMakerEngine, snapshot: MarketSnapshot) -> list[Fill]:
        """Simulate possible fills against engine's orders.
        
        Args:
            engine: Market maker engine
            snapshot: Current market snapshot
            
        Returns:
            List of fills that occurred
        """
        fills = []
        
        # Simple fill logic: random chance of fills for orders near market
        for order_id, order in list(engine.state.open_orders.items()):
            fill_probability = 0.0
            
            if order.side == OrderSide.BUY:
                # Buy order fills if price comes down to our bid
                if snapshot.best_ask_price is not None:
                    if order.price >= snapshot.best_ask_price * 0.998:
                        fill_probability = 0.3
            else:  # SELL
                # Sell order fills if price comes up to our ask
                if snapshot.best_bid_price is not None:
                    if order.price <= snapshot.best_bid_price * 1.002:
                        fill_probability = 0.3
            
            if random.random() < fill_probability:
                # Partial or full fill
                fill_qty = random.randint(1, order.qty)
                fill = Fill(
                    order_id=order_id,
                    side=order.side,
                    price=order.price,
                    qty=fill_qty,
                    timestamp=snapshot.timestamp
                )
                fills.append(fill)
        
        return fills


def run_demo(rounds: int = 100, verbose: bool = True):
    """Run market making demo.
    
    Args:
        rounds: Number of simulation rounds
        verbose: Print detailed output
    """
    # Configure market maker
    params = MMParams(
        base_spread_ticks=4,
        tick_size=0.01,
        quote_size=50,
        vol_lookback_n=50,
        vol_multiplier=10.0,
        inv_skew_k=0.002,
        soft_position=300,
        max_position=600,
        refresh_ms=250,
        max_order_age_ms=1000,
    )
    
    # Create engine
    exchange = ExchangeSim()
    initial_cash = 10000.0
    engine = MarketMakerEngine(params, exchange, initial_cash=initial_cash)
    
    # Create market simulator
    market = SimpleMarketSim(initial_price=100.0, volatility=0.5)
    
    if verbose:
        print("=" * 80)
        print("Market Maker Engine Demo")
        print("=" * 80)
        print(f"Initial cash: ${initial_cash:,.2f}")
        print(f"Starting price: ${market.price:.2f}")
        print(f"Parameters:")
        print(f"  Base spread: {params.base_spread_ticks} ticks")
        print(f"  Quote size: {params.quote_size} shares")
        print(f"  Max position: ±{params.max_position} shares")
        print(f"  Inventory skew: {params.inv_skew_k}")
        print("=" * 80)
        print()
    
    # Simulation loop
    for round_num in range(1, rounds + 1):
        # Generate market snapshot
        snapshot = market.generate_snapshot()
        
        # Engine processes market tick
        engine.on_market_tick(snapshot)
        
        # Simulate fills
        fills = market.simulate_fills(engine, snapshot)
        for fill in fills:
            engine.on_fill(fill, snapshot)
        
        # Print status periodically
        if verbose and (round_num % 10 == 0 or round_num == 1):
            print(f"\nRound {round_num}/{rounds}")
            print(f"  Price: ${snapshot.mid_price:.2f} | Vol: {engine.vol:.4f}")
            print(f"  Position: {engine.state.position:+d} shares")
            print(f"  Cash: ${engine.state.cash:,.2f}")
            print(f"  Equity: ${engine.state.equity:,.2f}")
            print(f"  Unrealized PnL: ${engine.state.unrealized_pnl:+,.2f}")
            print(f"  Open orders: {len(engine.state.open_orders)}")
            
            if len(engine.state.open_orders) > 0:
                buy_orders = [o for o in engine.state.open_orders.values() if o.side == OrderSide.BUY]
                sell_orders = [o for o in engine.state.open_orders.values() if o.side == OrderSide.SELL]
                if buy_orders:
                    bo = buy_orders[0]
                    print(f"    Buy: {bo.qty} @ ${bo.price:.2f}")
                if sell_orders:
                    so = sell_orders[0]
                    print(f"    Sell: {so.qty} @ ${so.price:.2f}")
    
    # Final summary
    final_pnl = engine.state.equity - initial_cash
    
    if verbose:
        print("\n" + "=" * 80)
        print("FINAL RESULTS")
        print("=" * 80)
        print(f"Final price: ${snapshot.mid_price:.2f}")
        print(f"Final position: {engine.state.position:+d} shares")
        print(f"Final cash: ${engine.state.cash:,.2f}")
        print(f"Final equity: ${engine.state.equity:,.2f}")
        print(f"Total PnL: ${final_pnl:+,.2f} ({final_pnl/initial_cash*100:+.2f}%)")
        print("=" * 80)
    
    return {
        'final_pnl': final_pnl,
        'final_position': engine.state.position,
        'final_equity': engine.state.equity,
        'rounds': rounds
    }


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Demo of market maker engine"
    )
    parser.add_argument(
        '--rounds',
        type=int,
        default=100,
        help="Number of simulation rounds (default: 100)"
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=None,
        help="Random seed for reproducibility"
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help="Suppress verbose output"
    )
    
    args = parser.parse_args()
    
    if args.seed is not None:
        random.seed(args.seed)
    
    results = run_demo(rounds=args.rounds, verbose=not args.quiet)
    
    if args.quiet:
        print(f"PnL: ${results['final_pnl']:+,.2f}")


if __name__ == "__main__":
    main()
