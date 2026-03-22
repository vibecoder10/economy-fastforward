# Betting Brain Program

## Mission

Your mission: **Turn $100 into $150+ on Kalshi prediction markets.**

Every bet is an experiment. Every outcome is data. Compound what works. Discard what doesn't.

---

## State

brain: ON
mode: paper
starting_bankroll_cents: 10000

---

## Scoring Weights

weights:
  price_edge: 0.30
  volume_signal: 0.20
  time_to_close: 0.20
  category_fit: 0.15
  price_momentum: 0.15

---

## Thresholds

thresholds:
  min_confidence: 60
  min_edge_cents: 5
  max_positions: 5
  take_profit_pct: 0.30
  max_bet_pct: 0.15
  min_bet_cents: 100
  cooldown_hours: 4

---

## Categories

Ranked by expected edge (update as we learn):

categories:
  Geopolitics: 50
  Economy: 50
  US Politics: 50
  World Politics: 50
