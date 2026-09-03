from datetime import UTC, datetime

import pytest
from ingest.core.models import Bar
from strategy.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_SIDE_SELL,
    ORDER_TYPE_MARKET,
)
from strategy.core.models import Fill, Order
from strategy.core.portfolio import Portfolio


def _fill(side: str, quantity: int, fill_price: float, commission: float = 0.0) -> Fill:
    order = Order(
        symbol="NSE-RELIANCE",
        side=side,
        quantity=quantity,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return Fill(
        order=order,
        fill_price=fill_price,
        fill_ts=datetime(2026, 1, 2, tzinfo=UTC),
        commission=commission,
    )


def test_apply_fills_updates_cash_and_positions() -> None:
    portfolio = Portfolio(starting_cash=1000.0)

    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0, commission=2.0)])

    assert portfolio.cash == 1000.0 - (5 * 10.0) - 2.0
    assert portfolio.positions["NSE-RELIANCE"] == 5


def test_apply_fills_sell_reduces_position_increases_cash() -> None:
    portfolio = Portfolio(starting_cash=1000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0)])

    portfolio.apply_fills([_fill(ORDER_SIDE_SELL, quantity=3, fill_price=12.0, commission=1.0)])

    assert portfolio.positions["NSE-RELIANCE"] == 2
    assert portfolio.cash == 1000.0 - 50.0 + 36.0 - 1.0


def test_mark_to_market_appends_equity_curve_point() -> None:
    portfolio = Portfolio(starting_cash=1000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0)])
    bar = Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, 3, tzinfo=UTC),
        open=11.0,
        high=11.0,
        low=11.0,
        close=11.0,
        volume=1000,
        provider="test",
    )

    portfolio.mark_to_market({"NSE-RELIANCE": bar})

    assert len(portfolio.equity_curve) == 1
    ts, value = portfolio.equity_curve[0]
    assert ts == bar.ts
    assert value == (1000.0 - 50.0) + (5 * 11.0)


def test_mark_to_market_carries_last_known_close_when_symbol_absent() -> None:
    portfolio = Portfolio(starting_cash=1000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0)])
    reliance_bar = Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, 3, tzinfo=UTC),
        open=11.0,
        high=11.0,
        low=11.0,
        close=11.0,
        volume=1000,
        provider="test",
    )
    portfolio.mark_to_market({"NSE-RELIANCE": reliance_bar})

    tcs_bar = Bar(
        symbol="NSE-TCS",
        interval="1d",
        ts=datetime(2026, 1, 4, tzinfo=UTC),
        open=200.0,
        high=200.0,
        low=200.0,
        close=200.0,
        volume=1000,
        provider="test",
    )
    portfolio.mark_to_market({"NSE-TCS": tcs_bar})

    ts, value = portfolio.equity_curve[-1]
    assert ts == tcs_bar.ts
    # NSE-RELIANCE absent this step: valued at its last known close (11.0), not dropped.
    assert value == (1000.0 - 50.0) + (5 * 11.0)


# --- TradeLedger tests (docs/superpowers/specs/2026-09-03-trade-ledger-design.md) ---


def test_ledger_records_realized_pnl_zero_on_opening_long() -> None:
    portfolio = Portfolio(starting_cash=1000.0)

    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0, commission=1.0)])

    entry = portfolio.ledger.entries[0]
    assert entry.realized_pnl == 0.0
    assert entry.cost_basis_before == 0.0
    assert entry.cash_after == portfolio.cash
    assert entry.position_after == 5


def test_ledger_weighted_average_cost_basis_on_adding_to_long() -> None:
    portfolio = Portfolio(starting_cash=10_000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0)])

    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=20.0)])

    entry = portfolio.ledger.entries[1]
    assert entry.cost_basis_before == 10.0
    assert entry.realized_pnl == 0.0
    # weighted average: (10*5 + 20*5) / 10 = 15.0
    assert portfolio._cost_basis["NSE-RELIANCE"] == pytest.approx(15.0)


def test_ledger_realized_pnl_on_partial_close_long() -> None:
    portfolio = Portfolio(starting_cash=10_000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=10, fill_price=10.0)])

    portfolio.apply_fills([_fill(ORDER_SIDE_SELL, quantity=4, fill_price=15.0)])

    entry = portfolio.ledger.entries[1]
    assert entry.cost_basis_before == 10.0
    assert entry.realized_pnl == pytest.approx((15.0 - 10.0) * 4)
    assert entry.position_after == 6
    assert portfolio._cost_basis["NSE-RELIANCE"] == 10.0  # unchanged, same lot


def test_ledger_realized_pnl_on_full_close_long() -> None:
    portfolio = Portfolio(starting_cash=10_000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=10, fill_price=10.0)])

    portfolio.apply_fills([_fill(ORDER_SIDE_SELL, quantity=10, fill_price=15.0)])

    entry = portfolio.ledger.entries[1]
    assert entry.realized_pnl == pytest.approx((15.0 - 10.0) * 10)
    assert entry.position_after == 0
    assert portfolio._cost_basis["NSE-RELIANCE"] == 0.0  # reset, nothing open


def test_ledger_flip_long_to_short_splits_realized_pnl_correctly() -> None:
    portfolio = Portfolio(starting_cash=10_000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=10, fill_price=10.0)])

    # Sell 15: closes the 10-share long (realized on 10 only), opens a 5-share short.
    portfolio.apply_fills([_fill(ORDER_SIDE_SELL, quantity=15, fill_price=15.0)])

    entry = portfolio.ledger.entries[1]
    assert entry.realized_pnl == pytest.approx((15.0 - 10.0) * 10)
    assert entry.position_after == -5
    assert portfolio._cost_basis["NSE-RELIANCE"] == 15.0  # new short lot opened at fill price


def test_ledger_short_side_mirrors_long_side() -> None:
    portfolio = Portfolio(starting_cash=10_000.0)

    # Open short from flat.
    portfolio.apply_fills([_fill(ORDER_SIDE_SELL, quantity=10, fill_price=20.0)])
    entry = portfolio.ledger.entries[0]
    assert entry.realized_pnl == 0.0
    assert portfolio._cost_basis["NSE-RELIANCE"] == 20.0

    # Add to short at a different price -> weighted average.
    portfolio.apply_fills([_fill(ORDER_SIDE_SELL, quantity=10, fill_price=10.0)])
    assert portfolio._cost_basis["NSE-RELIANCE"] == pytest.approx(15.0)

    # Partial cover: profit = (cost_basis - fill_price) * quantity for a short.
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=8, fill_price=12.0)])
    entry = portfolio.ledger.entries[2]
    assert entry.realized_pnl == pytest.approx((15.0 - 12.0) * 8)
    assert entry.position_after == -12
    assert portfolio._cost_basis["NSE-RELIANCE"] == 15.0  # unchanged

    # Full cover + flip to long.
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=20, fill_price=14.0)])
    entry = portfolio.ledger.entries[3]
    assert entry.realized_pnl == pytest.approx((15.0 - 14.0) * 12)
    assert entry.position_after == 8
    assert portfolio._cost_basis["NSE-RELIANCE"] == 14.0  # new long lot at fill price


def test_ledger_entries_accumulate_in_fill_order() -> None:
    portfolio = Portfolio(starting_cash=10_000.0)

    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0)])
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=3, fill_price=11.0)])
    portfolio.apply_fills([_fill(ORDER_SIDE_SELL, quantity=2, fill_price=12.0)])

    entries = portfolio.ledger.entries
    assert len(entries) == 3
    assert [e.quantity for e in entries] == [5, 3, 2]
    assert [e.side for e in entries] == [ORDER_SIDE_BUY, ORDER_SIDE_BUY, ORDER_SIDE_SELL]


def test_portfolio_ledger_property_is_read_only() -> None:
    portfolio = Portfolio(starting_cash=10_000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0)])

    entries = portfolio.ledger.entries
    entries.append(entries[0])  # mutate the returned copy

    assert len(portfolio.ledger.entries) == 1  # internal state unaffected


def test_ledger_entry_cash_and_position_after_match_portfolio_state() -> None:
    portfolio = Portfolio(starting_cash=10_000.0)

    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0, commission=2.0)])
    portfolio.apply_fills([_fill(ORDER_SIDE_SELL, quantity=2, fill_price=12.0, commission=1.0)])

    entries = portfolio.ledger.entries
    assert entries[0].cash_after == 10_000.0 - 50.0 - 2.0
    assert entries[0].position_after == 5
    assert entries[1].cash_after == portfolio.cash
    assert entries[1].position_after == portfolio.positions["NSE-RELIANCE"]


def test_apply_fills_raises_on_unknown_order_side() -> None:
    portfolio = Portfolio(starting_cash=1000.0)
    bad_order = Order(
        symbol="NSE-RELIANCE",
        side="short",  # not a recognized side
        quantity=5,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    bad_fill = Fill(
        order=bad_order, fill_price=10.0, fill_ts=datetime(2026, 1, 2, tzinfo=UTC), commission=0.0
    )

    with pytest.raises(ValueError, match="unknown order side"):
        portfolio.apply_fills([bad_fill])

    assert portfolio.cash == 1000.0
    assert portfolio.positions == {}
    assert portfolio.ledger.entries == []
