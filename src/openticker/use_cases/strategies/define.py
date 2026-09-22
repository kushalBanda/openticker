"""Create, change, read, delete and preview strategy definitions (ADR 20 in
docs/adr). Nothing here places an order or starts a run."""

import re
from dataclasses import dataclass
from datetime import date, datetime

from openticker.core.options.chain import expires_at
from openticker.core.options.underlyings import options_of
from openticker.core.strategies.legs import LegResolutionError, resolve_expiry, resolve_leg
from openticker.core.strategies.models import (
    InvalidStrategyError,
    LegSpec,
    OptionsStrategySpec,
    leg_id,
)
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Instrument, InstrumentType, Side
from openticker.storage.sqlite import strategies_repo
from openticker.storage.sqlite.instruments_repo import (
    future_contracts,
    option_contracts,
    option_expiries,
)
from openticker.storage.sqlite.strategies_repo import StoredStrategy
from openticker.use_cases.resolve_instrument import resolve_instrument

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,59}")


class UnknownStrategyError(LookupError):
    pass


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


def create_strategy(name: str, spec: OptionsStrategySpec, now: datetime) -> StoredStrategy:
    _check(name, spec)
    return strategies_repo.insert_strategy(name, spec, now)


def update_strategy(
    strategy_id: str, name: str, spec: OptionsStrategySpec, now: datetime
) -> StoredStrategy:
    """Replaces the whole definition."""
    _check(name, spec)
    stored = strategies_repo.update_strategy(strategy_id, name, spec, now)
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
    if not strategies_repo.delete_strategy(strategy_id, now):
        raise _unknown(strategy_id)


def preview_strategy(strategy_id: str, broker: BrokerPort, now: datetime) -> StrategyPreview:
    """The contracts each leg would trade if the strategy started now, at the
    underlying's current price. Places nothing."""
    stored = get_strategy(strategy_id)
    spec = stored.spec
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
    return StrategyPreview(stored, underlying, price, legs, _net_premium(legs))


def _check(name: str, spec: OptionsStrategySpec) -> None:
    if not _NAME.fullmatch(name):
        raise InvalidStrategyError(
            f"strategy name {name!r} must be 1-60 letters, digits, spaces, '.', '-' or '_', "
            "starting with a letter or digit"
        )
    options_of(resolve_instrument(spec.underlying, spec.exchange.value))


def _net_premium(legs: tuple[PreviewLeg, ...]) -> float | None:
    total = 0.0
    for leg in legs:
        if leg.last_price is None:
            return None
        sign = 1 if leg.spec.side is Side.SELL else -1
        total += sign * leg.last_price * leg.quantity
    return round(total, 2)


def _unknown(strategy_id: str) -> UnknownStrategyError:
    return UnknownStrategyError(
        f"no strategy with id {strategy_id!r}; list_strategies shows the ones that exist"
    )
