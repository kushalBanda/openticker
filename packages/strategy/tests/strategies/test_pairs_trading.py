from datetime import UTC, datetime, timedelta

import pytest
from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.strategies.pairs_trading.strategy import PairsTradingStrategy


def _bar(symbol: str, day: int, close: float) -> Bar:
    ts = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Bar(
        symbol=symbol,
        interval="1d",
        ts=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="test",
    )


async def test_no_entry_before_formation_window_is_complete() -> None:
    # Only 10 days of history — formation_months=1 needs ~31 days before its
    # first reformation, so no pair is ever selected, no matter how sharply
    # the price diverges.
    a_closes = [100.0] * 5 + [200.0] * 5
    b_closes = [100.0] * 10
    bars = {
        "A": [_bar("A", d, c) for d, c in enumerate(a_closes)],
        "B": [_bar("B", d, c) for d, c in enumerate(b_closes)],
    }

    strategy = PairsTradingStrategy(formation_months=1, trading_months=1, top_n_pairs=1, entry_z=2.0)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("A", 0) == 0
    assert result.positions.get("B", 0) == 0
    assert result.ledger.entries == []


async def test_enters_position_when_spread_diverges_past_entry_z() -> None:
    def a_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 101.0

    def b_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 100.9

    formation_days = range(32)  # 2026-01-01 .. 2026-02-01, reaches reformation
    bars_a = [_bar("A", d, a_close(d)) for d in formation_days]
    bars_b = [_bar("B", d, b_close(d)) for d in formation_days]

    # Trading-period shock: B crashes, A stays at its formation baseline.
    # Two identical bars so the order placed on the shock bar fills.
    bars_a += [_bar("A", 32, 100.0), _bar("A", 33, 100.0)]
    bars_b += [_bar("B", 32, 1.0), _bar("B", 33, 1.0)]

    strategy = PairsTradingStrategy(formation_months=1, trading_months=1, top_n_pairs=1, entry_z=2.0)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run({"A": bars_a, "B": bars_b}, strategy)

    assert result.positions.get("A", 0) < 0
    assert result.positions.get("B", 0) > 0


async def test_exits_position_when_spread_reverts_through_mean() -> None:
    def a_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 101.0

    def b_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 100.9

    formation_days = range(32)
    bars_a = [_bar("A", d, a_close(d)) for d in formation_days]
    bars_b = [_bar("B", d, b_close(d)) for d in formation_days]

    # Shock entry (B crashes, matches the entry test above), then a reversal
    # far enough past the frozen mean the other way to flip the z-score's
    # sign, which is what should trigger the exit.
    bars_a += [
        _bar("A", 32, 100.0),
        _bar("A", 33, 100.0),
        _bar("A", 34, 100.0),
        _bar("A", 35, 100.0),
    ]
    bars_b += [
        _bar("B", 32, 1.0),
        _bar("B", 33, 1.0),
        _bar("B", 34, 500.0),
        _bar("B", 35, 500.0),
    ]

    strategy = PairsTradingStrategy(formation_months=1, trading_months=1, top_n_pairs=1, entry_z=2.0)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run({"A": bars_a, "B": bars_b}, strategy)

    assert result.positions.get("A", 0) == 0
    assert result.positions.get("B", 0) == 0


async def test_dollar_neutral_sizing_splits_capital_equally_across_top_n_pairs() -> None:
    def a_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 101.0

    def b_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 100.9

    def c_close(day: int) -> float:
        return 203.0 if day % 2 == 0 else 200.0

    def d_close(day: int) -> float:
        return 201.8 if day % 2 == 0 else 200.0

    formation_days = range(32)
    bars = {
        "A": [_bar("A", d, a_close(d)) for d in formation_days],
        "B": [_bar("B", d, b_close(d)) for d in formation_days],
        "C": [_bar("C", d, c_close(d)) for d in formation_days],
        "D": [_bar("D", d, d_close(d)) for d in formation_days],
    }
    # Trading-period shock on day 32: crash B and D so both pairs (A,B) and
    # (C,D) — the two tightest by sum-of-squared-deviation over the
    # formation window above — blow past entry_z at the same time.
    bars["A"] += [_bar("A", 32, 100.0), _bar("A", 33, 100.0)]
    bars["B"] += [_bar("B", 32, 1.0), _bar("B", 33, 1.0)]
    bars["C"] += [_bar("C", 32, 203.0), _bar("C", 33, 203.0)]
    bars["D"] += [_bar("D", 32, 1.0), _bar("D", 33, 1.0)]

    strategy = PairsTradingStrategy(formation_months=1, trading_months=1, top_n_pairs=2, entry_z=2.0)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    capital_per_pair = 100_000.0 / 2  # two selected pairs, equal-weight split
    assert result.positions.get("A", 0) == -500  # short: floor(50_000 / 100.0)
    assert result.positions.get("B", 0) == 50_000  # long: floor(50_000 / 1.0)
    assert result.positions.get("C", 0) == -246  # short: floor(50_000 / 203.0)
    assert result.positions.get("D", 0) == 50_000  # long: floor(50_000 / 1.0)

    # Every leg's notional lands within one share of its equal-weight slice.
    assert abs(abs(result.positions["A"]) * 100.0 - capital_per_pair) <= 100.0
    assert abs(abs(result.positions["C"]) * 203.0 - capital_per_pair) <= 203.0


async def test_force_unwinds_open_positions_at_trading_period_end() -> None:
    def a_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 101.0

    def b_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 100.9

    formation_days = range(32)  # 2026-01-01 .. 2026-02-01, first reformation
    bars_a = [_bar("A", d, a_close(d)) for d in formation_days]
    bars_b = [_bar("B", d, b_close(d)) for d in formation_days]

    # B crashes on day 32 and never recovers, all the way past the second
    # reformation date (2026-03-01, day 59) — the position must be forced
    # flat there even though the spread never converged on its own. entry_z
    # is set high enough that the still-diverged spread, re-scored against
    # the freshly re-formed baseline, does not immediately re-enter.
    bars_a += [_bar("A", d, 100.0) for d in range(32, 61)]
    bars_b += [_bar("B", d, 1.0) for d in range(32, 61)]

    strategy = PairsTradingStrategy(formation_months=1, trading_months=1, top_n_pairs=1, entry_z=3.0)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run({"A": bars_a, "B": bars_b}, strategy)

    assert result.positions.get("A", 0) == 0
    assert result.positions.get("B", 0) == 0


async def test_reselects_pairs_at_each_reformation_boundary() -> None:
    # X and Y move in tight lockstep through the first formation window
    # (days 0-31); Y and Z move in tight lockstep through the second
    # (days 31-59, X now frozen and left out). top_n_pairs=1 forces an
    # unambiguous choice each cycle.
    def x_close(day: int) -> float:
        if day <= 31:
            return 100.0 if day % 2 == 0 else 101.0
        return 100.0

    def y_close(day: int) -> float:
        if day <= 31:
            return 100.0 if day % 2 == 0 else 100.9
        return 100.9 if day % 2 == 0 else 101.8

    def z_close(day: int) -> float:
        if day <= 31:
            return 500.0
        if day <= 59:
            return 500.0 if day % 2 == 0 else 504.5
        return 1.0  # cycle-2 shock: crashes only after the second reformation

    days = range(62)
    bars = {
        "X": [_bar("X", d, x_close(d)) for d in days],
        "Y": [_bar("Y", d, y_close(d)) for d in days],
        "Z": [_bar("Z", d, z_close(d)) for d in days],
    }

    strategy = PairsTradingStrategy(formation_months=1, trading_months=1, top_n_pairs=1, entry_z=3.0)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    # X was only ever half of the first cycle's pair; once the second
    # reformation drops it, nothing in this run should still be trading it.
    assert result.positions.get("X", 0) == 0
    # The second cycle's pair (Y, Z) is the one that actually reacts to the
    # post-reformation shock.
    assert result.positions.get("Y", 0) < 0
    assert result.positions.get("Z", 0) > 0


def test_rejects_invalid_params() -> None:
    with pytest.raises(ValueError, match="formation_months"):
        PairsTradingStrategy(formation_months=0, trading_months=1, top_n_pairs=1, entry_z=2.0)
    with pytest.raises(ValueError, match="trading_months"):
        PairsTradingStrategy(formation_months=1, trading_months=0, top_n_pairs=1, entry_z=2.0)
    with pytest.raises(ValueError, match="top_n_pairs"):
        PairsTradingStrategy(formation_months=1, trading_months=1, top_n_pairs=0, entry_z=2.0)
    with pytest.raises(ValueError, match="entry_z"):
        PairsTradingStrategy(formation_months=1, trading_months=1, top_n_pairs=1, entry_z=0.0)
