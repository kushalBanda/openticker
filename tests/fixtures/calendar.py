from openticker.core.calendar.models import MarketCalendar

# 2026 with no holidays: weekdays trade regular hours.
NO_HOLIDAYS = MarketCalendar(years=frozenset({2026}), holidays=(), special_sessions=())
