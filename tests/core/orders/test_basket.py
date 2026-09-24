from openticker.core.orders.basket import basket_sequence
from openticker.ports.models import Side


def test_buys_go_first_keeping_caller_order_within_side() -> None:
    sides = [Side.SELL, Side.BUY, Side.SELL, Side.BUY]

    assert basket_sequence(sides) == [1, 3, 0, 2]


def test_all_one_side_keeps_caller_order() -> None:
    assert basket_sequence([Side.SELL, Side.SELL]) == [0, 1]
    assert basket_sequence([]) == []
