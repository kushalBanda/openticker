"""Create, change, read, delete and preview strategy definitions (ADR 20 and
ADR 24 in docs/adr). Nothing here places an order or starts a run. A strategy
is edited or deleted only while it isn't running (ADR 21 in docs/adr)."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial

from sqlalchemy.orm import Session

from openticker.core.options.chain import expires_at
from openticker.core.options.underlyings import options_of
from openticker.core.strategies.legs import LegResolutionError, resolve_expiry, resolve_leg
from openticker.core.strategies.models import (
    InvalidStrategyError,
    LegSpec,
    OptionsStrategySpec,
    SignalStrategySpec,
    StrategySpec,
    leg_id,
)
from openticker.core.strategies.runs import CommandKind
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Instrument, InstrumentType, Side
from openticker.storage.sqlite import runs_repo, strategies_repo
from openticker.storage.sqlite.instruments_repo import (
    future_contracts,
    get_instrument,
    option_contracts,
    option_expiries,
)
from openticker.storage.sqlite.strategies_repo import StoredStrategy
from openticker.use_cases.resolve_instrument import resolve_instrument

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,59}")


class UnknownStrategyError(LookupError):
    pass


class StrategyRunningError(Exception):
    """The strategy has a run open, or one about to start."""


class StrategyKindError(Exception):
    """The request is for the other kind of strategy: options or signal."""


@dataclass(frozen=True)
class PreviewLeg:
    leg_id: str
    spec: LegSpec
    instrument: Instrument
    label: str  # ATM, ITM2, OTM1, FUT
    quantity: int  # units: lots times the contract's lot size
    last_price: float | None


@dataclass(frozen=True)
class StrategyPreview:
    strategy: StoredStrategy
    underlying: Instrument
    underlying_price: float
    legs: tuple[PreviewLeg, ...]
    net_premium: float | None  # received minus paid at last prices; None if a price is missing


def create_strategy(name: str, spec: StrategySpec, now: datetime) -> StoredStrategy:
    _check(name, spec, now)
    return strategies_repo.insert_strategy(name, spec, now)


def update_strategy(
    strategy_id: str, name: str, spec: StrategySpec, now: datetime
) -> StoredStrategy:
    """Replaces the whole definition. A strategy keeps its kind."""
    if isinstance(get_strategy(strategy_id).spec, SignalStrategySpec) != isinstance(
        spec, SignalStrategySpec
    ):
        raise StrategyKindError(
            "a strategy keeps its kind: update an options strategy with update_strategy and a "
            "signal strategy with update_signal_strategy, or create a new one"
        )
    _check(name, spec, now)
    stored = strategies_repo.update_strategy(
        strategy_id, name, spec, now, partial(_refuse_while_running, strategy_id, "editing")
    )
    if stored is None:
        raise _unknown(strategy_id)
    return stored


def get_strategy(strategy_id: str) -> StoredStrategy:
    stored = strategies_repo.find_strategy(strategy_id)
    if stored is None:
        raise _unknown(strategy_id)
    return stored


def list_strategies() -> list[StoredStrategy]:
    return strategies_repo.list_strategies()


def delete_strategy(strategy_id: str, now: datetime) -> None:
    if not strategies_repo.delete_strategy(
        strategy_id, now, partial(_refuse_while_running, strategy_id, "deleting")
    ):
        raise _unknown(strategy_id)


def preview_strategy(strategy_id: str, broker: BrokerPort, now: datetime) -> StrategyPreview:
    """The contracts each leg would trade if the strategy started now, at the
    underlying's current price. Places nothing."""
    stored = get_strategy(strategy_id)
    if not isinstance(stored.spec, OptionsStrategySpec):
        raise StrategyKindError(
            f"{stored.name!r} is a signal strategy: its legs name their contracts, so there is "
            "nothing to resolve; get_strategy shows them"
        )
    underlying, price, legs = resolve_legs(stored.spec, broker, now)
    return StrategyPreview(stored, underlying, price, legs, _net_premium(legs))


def resolve_legs(
    spec: OptionsStrategySpec, broker: BrokerPort, now: datetime
) -> tuple[Instrument, float, tuple[PreviewLeg, ...]]:
    """The underlying, its price, and the contract each leg resolves to now."""
    underlying = resolve_instrument(spec.underlying, spec.exchange.value)
    name, derivatives_exchange = options_of(underlying)
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    price = broker.get_quote(underlying).last_price
    if price <= 0:
        raise BrokerError(f"no usable price for {spec.underlying} yet; try again once it trades")

    expiries = [
        listed
        for listed in option_expiries(name, derivatives_exchange, today)
        if expires_at(listed) > now
    ]
    futures = [
        future
        for future in future_contracts(name, derivatives_exchange, today)
        if future.expiry is not None and expires_at(future.expiry) > now
    ]
    chains: dict[date, list[Instrument]] = {}
    resolved = []
    for index, leg in enumerate(spec.legs):
        try:
            if leg.option_type is InstrumentType.FUT:
                expiry = resolve_expiry(
                    leg.expiry, [future.expiry for future in futures if future.expiry], today
                )
                contracts = [future for future in futures if future.expiry == expiry]
            else:
                expiry = resolve_expiry(leg.expiry, expiries, today)
                if expiry not in chains:
                    chains[expiry] = option_contracts(name, derivatives_exchange, expiry)
                contracts = chains[expiry]
            resolved.append((index, leg, resolve_leg(leg, price, contracts)))
        except LegResolutionError as exc:
            raise LegResolutionError(f"{leg_id(index)} ({name} {leg.option_type}): {exc}") from exc

    quotes = {
        quote.instrument.symbol: quote.last_price
        for quote in broker.get_quotes([result.instrument for _, _, result in resolved])
    }
    legs = tuple(
        PreviewLeg(
            leg_id=leg_id(index),
            spec=leg,
            instrument=result.instrument,
            label=result.label,
            quantity=leg.lots * result.instrument.lot_size,
            last_price=quotes.get(result.instrument.symbol),
        )
        for index, leg, result in resolved
    )
    return underlying, price, legs


def _check(name: str, spec: StrategySpec, now: datetime) -> None:
    if not _NAME.fullmatch(name):
        raise InvalidStrategyError(
            f"strategy name {name!r} must be 1-60 letters, digits, spaces, '.', '-' or '_', "
            "starting with a letter or digit"
        )
    if isinstance(spec, OptionsStrategySpec):
        options_of(resolve_instrument(spec.underlying, spec.exchange.value))
        return
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    for index, leg in enumerate(spec.legs):
        name = f"{leg_id(index)} ({leg.symbol} {leg.exchange})"
        instrument = get_instrument(leg.symbol, leg.exchange.value)
        if instrument is None:
            raise InvalidStrategyError(
                f"{name} is not in the instrument master; search_instruments finds the exact "
                "symbol, and sync_instruments refreshes the master"
            )
        if instrument.expiry is not None and instrument.expiry < today:
            raise InvalidStrategyError(f"{name} expired on {instrument.expiry}")
        lot = max(instrument.lot_size, 1)
        if leg.quantity % lot:
            raise InvalidStrategyError(
                f"{name}: quantity {leg.quantity} is not a whole number of lots of {lot}"
            )


def _net_premium(legs: tuple[PreviewLeg, ...]) -> float | None:
    total = 0.0
    for leg in legs:
        if leg.last_price is None:
            return None
        sign = 1 if leg.spec.side is Side.SELL else -1
        total += sign * leg.last_price * leg.quantity
    return round(total, 2)


def _refuse_while_running(strategy_id: str, doing: str, session: Session) -> None:
    if runs_repo.active_run_of(session, strategy_id) is not None or any(
        command.kind is CommandKind.START
        for command in runs_repo.pending_commands_of(session, strategy_id)
    ):
        raise StrategyRunningError(
            f"stop the strategy before {doing} it: it is running (stop_strategy, then "
            "try again once get_strategy_runs shows the run ended)"
        )


def _unknown(strategy_id: str) -> UnknownStrategyError:
    return UnknownStrategyError(
        f"no strategy with id {strategy_id!r}; list_strategies shows the ones that exist"
    )
