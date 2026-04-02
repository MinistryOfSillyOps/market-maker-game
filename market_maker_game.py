#!/usr/bin/env python3
"""Terminal stock market maker game.

Goal: maximize profit while ending with zero position (flat book).
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass


@dataclass
class GameConfig:
    starting_price: float = 100.0
    starting_cash: float = 10_000.0
    rounds: int = 20
    max_order_size: int = 25
    fee_per_share: float = 0.04
    spread: float = 0.10
    liquidation_penalty_per_share: float = 0.50


@dataclass
class GameState:
    round_number: int
    price: float
    cash: float
    position: int
    last_move: float = 0.0

    def mark_to_market_equity(self) -> float:
        return self.cash + self.position * self.price

    def unrealized_pnl(self, initial_cash: float) -> float:
        return self.mark_to_market_equity() - initial_cash


def format_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def next_price(current: float, momentum: float) -> tuple[float, float]:
    """Generate the next price with noise and slight momentum persistence."""
    shock = random.gauss(0.0, 1.4)
    drift = random.gauss(0.05, 0.08)
    step = (0.75 * momentum) + drift + shock
    new_price = max(1.0, current + step)
    return new_price, step


def print_status(state: GameState, cfg: GameConfig, initial_cash: float) -> None:
    bid = max(0.01, state.price - (cfg.spread / 2.0))
    ask = state.price + (cfg.spread / 2.0)
    equity = state.mark_to_market_equity()
    pnl = equity - initial_cash

    print("\n" + "=" * 72)
    print(f"Round {state.round_number}/{cfg.rounds}")
    print(
        f"Mid: {state.price:,.2f} | Bid: {bid:,.2f} | Ask: {ask:,.2f} "
        f"| Last move: {state.last_move:+.2f}"
    )
    print(
        f"Cash: {format_money(state.cash)} | Position: {state.position:+d} shares "
        f"| Equity: {format_money(equity)} | PnL: {format_money(pnl)}"
    )
    print("Actions: b <qty>=buy | s <qty>=sell/short | h=hold | ?=help | q=quit")


def apply_trade(state: GameState, side: str, qty: int, cfg: GameConfig) -> None:
    bid = max(0.01, state.price - (cfg.spread / 2.0))
    ask = state.price + (cfg.spread / 2.0)
    fee = qty * cfg.fee_per_share

    if side == "b":
        trade_value = ask * qty
        state.cash -= trade_value + fee
        state.position += qty
        print(
            f"Bought {qty} @ {ask:,.2f} | Fees {format_money(fee)} | "
            f"Cash change {format_money(-(trade_value + fee))}"
        )
    elif side == "s":
        trade_value = bid * qty
        state.cash += trade_value - fee
        state.position -= qty
        print(
            f"Sold {qty} @ {bid:,.2f} | Fees {format_money(fee)} | "
            f"Cash change {format_money(trade_value - fee)}"
        )


def parse_action(raw: str, cfg: GameConfig) -> tuple[str, int]:
    text = raw.strip().lower()
    if not text:
        return "", 0

    if text in {"h", "hold"}:
        return "h", 0
    if text in {"?", "help"}:
        return "?", 0
    if text in {"q", "quit", "exit"}:
        return "q", 0

    parts = text.split()
    if len(parts) != 2 or parts[0] not in {"b", "s", "buy", "sell"}:
        raise ValueError("Use 'b <qty>', 's <qty>', 'h', '?', or 'q'.")

    side = "b" if parts[0].startswith("b") else "s"
    try:
        qty = int(parts[1])
    except ValueError as exc:
        raise ValueError("Quantity must be an integer.") from exc

    if qty <= 0:
        raise ValueError("Quantity must be positive.")
    if qty > cfg.max_order_size:
        raise ValueError(f"Max order size is {cfg.max_order_size}.")

    return side, qty


def print_help(cfg: GameConfig) -> None:
    print("\nHow to play:")
    print("- Buy adds to your long position.")
    print("- Sell reduces your long or increases your short position.")
    print("- You can be long (positive shares), short (negative), or flat (0).")
    print("- Each trade pays fees and crosses a spread.")
    print(f"- Max order size per trade: {cfg.max_order_size} shares.")
    print("- Goal: highest PnL while ending FLAT (position = 0).")


def force_liquidate(state: GameState, cfg: GameConfig) -> float:
    if state.position == 0:
        return 0.0

    qty = abs(state.position)
    side = "sell" if state.position > 0 else "buy"
    bid = max(0.01, state.price - (cfg.spread / 2.0))
    ask = state.price + (cfg.spread / 2.0)
    fee = qty * cfg.fee_per_share
    penalty = qty * cfg.liquidation_penalty_per_share

    if state.position > 0:
        proceeds = qty * bid
        state.cash += proceeds - fee - penalty
    else:
        cost = qty * ask
        state.cash -= cost + fee + penalty

    print("\nEnd-of-game liquidation required (book not flat).")
    print(
        f"Forced {side} {qty} shares | Fees {format_money(fee)} "
        f"| Penalty {format_money(penalty)}"
    )
    state.position = 0
    return penalty


def run_game(cfg: GameConfig) -> None:
    state = GameState(
        round_number=1,
        price=cfg.starting_price,
        cash=cfg.starting_cash,
        position=0,
    )
    initial_cash = cfg.starting_cash

    print("Stock Market Maker: Flat Book Challenge")
    print("Enter '?' for instructions.")

    while state.round_number <= cfg.rounds:
        print_status(state, cfg, initial_cash)

        while True:
            raw = input("Action > ")
            try:
                action, qty = parse_action(raw, cfg)
            except ValueError as exc:
                print(f"Invalid input: {exc}")
                continue

            if action == "?":
                print_help(cfg)
                continue

            if action == "q":
                print("You ended the game early.")
                state.round_number = cfg.rounds + 1
                break

            if action in {"b", "s"}:
                apply_trade(state, action, qty, cfg)
            break

        if state.round_number > cfg.rounds:
            break

        state.price, state.last_move = next_price(state.price, state.last_move)
        state.round_number += 1

    penalty = force_liquidate(state, cfg)
    final_equity = state.mark_to_market_equity()
    final_pnl = final_equity - initial_cash

    print("\n" + "=" * 72)
    print("FINAL RESULTS")
    print(f"Final cash: {format_money(state.cash)}")
    print(f"Final position: {state.position:+d} shares (must be 0)")
    print(f"Liquidation penalty paid: {format_money(penalty)}")
    print(f"Final equity: {format_money(final_equity)}")
    print(f"Final PnL: {format_money(final_pnl)}")

    if penalty > 0:
        print("Result: You made/lose money, but missed the flat-book objective.")
    else:
        print("Result: You finished flat. Objective condition satisfied.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Play a stock market making game with long and short trading."
    )
    parser.add_argument("--rounds", type=int, default=20, help="Number of rounds.")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for repeatable markets.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    rounds = max(1, int(args.rounds))
    cfg = GameConfig(rounds=rounds)
    run_game(cfg)


if __name__ == "__main__":
    main()
