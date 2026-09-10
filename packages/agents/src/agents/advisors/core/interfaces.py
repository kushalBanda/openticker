from typing import Protocol


class Advisor[StatsT, ProposalT](Protocol):
    """One Advisor per strategy: proposes tunable params once per
    reformation cycle, in place of fixed rule-based constants. See
    `docs/adr/0001-pairs-trading-advisor-shape.md` and `CONTEXT.md`'s
    `Advisor`/`Proposal` entries for the design rationale.
    """

    async def propose(self, candidates: list[StatsT], prior: ProposalT) -> ProposalT: ...
