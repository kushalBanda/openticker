from datetime import UTC, datetime, timedelta

from agents.advisors.pairs_trading.schema import (
    CandidateStats,
    PairsTradingProposal,
    SelectedPairWeight,
)
from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.strategies.pairs_trading.strategy import PairsTradingStrategy


def _bar(symbol: str, day: int, close: float) -> Bar:
    ts = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Bar(
        symbol=symbol, interval="1d", ts=ts, open=close, high=close, low=close,
        close=close, volume=1000, provider="test",
    )


class _FakeAdvisor:
    """Records every call's candidates, returns a scripted proposal per call
    (or the last one repeated if the script runs out).
    """

    def __init__(self, proposals: list[PairsTradingProposal]) -> None:
        self._proposals = proposals
        self.calls: list[list[CandidateStats]] = []

    async def propose(
        self, candidates: list[CandidateStats], prior: PairsTradingProposal
    ) -> PairsTradingProposal:
        self.calls.append(candidates)
        index = min(len(self.calls) - 1, len(self._proposals) - 1)
        return self._proposals[index]


async def test_advisor_selection_applies_tuned_params_and_capital_weight() -> None:
    def a_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 101.0

    def b_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 100.9

    formation_days = range(32)
    bars_a = [_bar("A", d, a_close(d)) for d in formation_days]
    bars_b = [_bar("B", d, b_close(d)) for d in formation_days]
    bars_a += [_bar("A", 32, 100.0), _bar("A", 33, 100.0)]
    bars_b += [_bar("B", 32, 1.0), _bar("B", 33, 1.0)]

    proposal = PairsTradingProposal(
        entry_z=2.5,
        formation_months=4,
        trading_months=2,
        buffer=0.2,
        selected=(SelectedPairWeight("A", "B", 0.8),),
    )
    advisor = _FakeAdvisor([proposal])

    strategy = PairsTradingStrategy(
        formation_months=1, trading_months=1, top_n_pairs=1, entry_z=2.0, advisor=advisor,
    )
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run({"A": bars_a, "B": bars_b}, strategy)

    assert len(advisor.calls) == 1
    assert strategy._entry_z == 2.5
    assert strategy._formation_months == 4
    assert strategy._trading_months == 2

    capital = 0.8 * 100_000.0
    assert result.positions.get("A", 0) < 0
    assert result.positions.get("B", 0) > 0
    assert abs(abs(result.positions["A"]) * 100.0 - capital) <= 100.0
    assert abs(abs(result.positions["B"]) * 1.0 - capital) <= 1.0


async def test_advisor_sees_no_pnl_history_on_first_call_then_populated_after_round_trip() -> None:
    def a_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 101.0

    def b_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 100.9

    formation_days = range(32)
    bars_a = [_bar("A", d, a_close(d)) for d in formation_days]
    bars_b = [_bar("B", d, b_close(d)) for d in formation_days]
    # Shock entry, then reversal far enough to flip the z-score sign and
    # trigger an exit, then flat through the next reformation boundary.
    bars_a += [_bar("A", d, 100.0) for d in range(32, 63)]
    bars_b += [_bar("B", 32, 1.0), _bar("B", 33, 1.0), *[_bar("B", d, 500.0) for d in range(34, 63)]]

    first_cycle_proposal = PairsTradingProposal(
        entry_z=2.0, formation_months=1, trading_months=1, buffer=0.1,
        selected=(SelectedPairWeight("A", "B", 0.9),),
    )
    advisor = _FakeAdvisor([first_cycle_proposal])

    strategy = PairsTradingStrategy(
        formation_months=1, trading_months=1, top_n_pairs=1, entry_z=2.0, advisor=advisor,
    )
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    await engine.run({"A": bars_a, "B": bars_b}, strategy)

    assert len(advisor.calls) == 2
    first_call_stats = advisor.calls[0][0]
    assert first_call_stats.win_rate is None
    assert first_call_stats.realized_pnl is None
    assert first_call_stats.trade_count is None

    second_call_stats = advisor.calls[1][0]
    assert second_call_stats.trade_count is not None
    assert second_call_stats.trade_count >= 1
    assert second_call_stats.win_rate is not None
    assert second_call_stats.realized_pnl is not None
