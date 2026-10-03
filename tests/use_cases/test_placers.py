from openticker.storage.sqlite import scripts_repo
from openticker.storage.sqlite.strategies_repo import insert_strategy, write_transaction
from openticker.use_cases.placers import placer_names
from tests.fixtures.strategies import NOW, STRADDLE


def test_strategies_and_scripts_by_name() -> None:
    straddle = insert_strategy("NIFTY short straddle", STRADDLE, NOW)
    with write_transaction() as session:
        script = scripts_repo.insert_script(session, "rel_trail.py", "0" * 64, 10, NOW)

    names = placer_names(
        [f"strategy:{straddle.id}", f"script:{script.id}", "strategy:gone", "ui", "mcp:codex"]
    )

    assert names == {
        f"strategy:{straddle.id}": "NIFTY short straddle",
        f"script:{script.id}": "rel_trail.py",
    }


def test_nothing_to_look_up() -> None:
    assert placer_names(["ui", "mcp:claude-code"]) == {}
