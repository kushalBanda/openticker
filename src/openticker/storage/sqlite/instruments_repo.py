"""get_instrument, search_instruments, upsert_instruments, option_expiries,
option_contracts — the broker-agnostic instrument master.

Upsert, not replace: rows for contracts that have since expired stay in the
table until something prunes them (nothing does yet).
"""

import re
from dataclasses import asdict
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from openticker.ports.models import Exchange, Instrument, InstrumentType
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import InstrumentRow

_KEY_COLUMNS = ("exchange", "symbol")


def upsert_instruments(rows: list[Instrument]) -> int:
    """Insert new rows, overwrite existing ones by (exchange, symbol). Returns count written."""
    if not rows:
        return 0
    statement = insert(InstrumentRow)
    statement = statement.on_conflict_do_update(
        index_elements=list(_KEY_COLUMNS),
        set_={
            column.name: statement.excluded[column.name]
            for column in InstrumentRow.__table__.columns
            if column.name not in _KEY_COLUMNS
        },
    )
    with Session(get_engine()) as session:
        session.execute(statement, [asdict(row) for row in rows])
        session.commit()
    return len(rows)


def get_instrument(symbol: str, exchange: str) -> Instrument | None:
    with Session(get_engine()) as session:
        row = session.scalar(
            select(InstrumentRow).where(
                InstrumentRow.exchange == exchange, InstrumentRow.symbol == symbol
            )
        )
    return _to_instrument(row) if row is not None else None


def search_instruments(
    query: str,
    exchange: str | None,
    instrument_type: str | None,
    live_on: date | None,
    limit: int,
) -> list[Instrument]:
    """Symbols containing `query` (case-insensitive): exact match first, then
    prefix matches, then the rest, shortest symbol first. `live_on` drops
    contracts that expired before that date."""
    pattern = query.upper()
    upper_symbol = func.upper(InstrumentRow.symbol)
    statement = select(InstrumentRow).where(upper_symbol.contains(pattern, autoescape=True))
    if exchange is not None:
        statement = statement.where(InstrumentRow.exchange == exchange)
    if instrument_type is not None:
        statement = statement.where(InstrumentRow.instrument_type == instrument_type)
    if live_on is not None:
        statement = statement.where(
            or_(InstrumentRow.expiry.is_(None), InstrumentRow.expiry >= live_on)
        )
    statement = statement.order_by(
        upper_symbol != pattern,
        ~upper_symbol.startswith(pattern),
        func.length(InstrumentRow.symbol),
        InstrumentRow.symbol,
        InstrumentRow.exchange,
    ).limit(limit)
    with Session(get_engine()) as session:
        rows = session.scalars(statement).all()
    return [_to_instrument(row) for row in rows]


def option_expiries(name: str, exchange: str, live_on: date) -> list[date]:
    """Expiries, earliest first, of options whose symbols start with the
    underlying `name` (ADR 4 in docs/adr), from `live_on` onwards."""
    return sorted({row.expiry for row in _options(name, exchange, live_on) if row.expiry})


def option_contracts(name: str, exchange: str, expiry: date) -> list[Instrument]:
    """Every call and put on `name` expiring on `expiry`, by strike."""
    rows = [row for row in _options(name, exchange, expiry) if row.expiry == expiry]
    return [
        _to_instrument(row) for row in sorted(rows, key=lambda row: (row.strike or 0.0, row.symbol))
    ]


def _options(name: str, exchange: str, live_on: date) -> list[InstrumentRow]:
    """Option rows for exactly `name`. The LIKE prefix also matches longer
    names (NIFTY matches NIFTYNXT50...), so symbols are checked against the
    full `<name><DDMMMYY><strike><CE|PE>` shape."""
    shape = re.compile(rf"{re.escape(name)}\d{{2}}[A-Z]{{3}}\d{{2}}[\d.]+(CE|PE)")
    statement = select(InstrumentRow).where(
        InstrumentRow.exchange == exchange,
        InstrumentRow.instrument_type.in_([InstrumentType.CE.value, InstrumentType.PE.value]),
        InstrumentRow.symbol.startswith(name, autoescape=True),
        InstrumentRow.expiry >= live_on,
    )
    with Session(get_engine()) as session:
        rows = session.scalars(statement).all()
    return [row for row in rows if shape.fullmatch(row.symbol)]


def _to_instrument(row: InstrumentRow) -> Instrument:
    return Instrument(
        symbol=row.symbol,
        broker_symbol=row.broker_symbol,
        exchange=Exchange(row.exchange),
        broker_exchange=row.broker_exchange,
        token=row.token,
        expiry=row.expiry,
        strike=row.strike,
        lot_size=row.lot_size,
        instrument_type=InstrumentType(row.instrument_type),
        tick_size=row.tick_size,
    )
