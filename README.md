# Stock Market Maker Game

A terminal game where you trade one stock over multiple rounds.

You can:
- Buy shares (`long` exposure)
- Sell shares (`short` exposure)
- Hold and wait

Your objective is to maximize PnL **and** end with no position (`position = 0`).

## Run

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
