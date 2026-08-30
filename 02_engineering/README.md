# Phase 2 — Engineering rigor

Goal: build a real event-driven backtest engine skeleton in C++. This is the antidote to a "notebook toy" curriculum — build the pattern, don't just call a library.

## Study first

Read `../docs/resources/nautilus_trader/docs/concepts/architecture.md` — real production-trading architecture reference (Rust-native, but the design principles translate directly to C++):

- Quality attribute ordering: Reliability > Performance > Modularity > Testability > Maintainability > Deployability
- Fail-fast / crash-only design — bad data errors or panics immediately, never propagates silently
- Event-driven message-bus architecture — Data/Risk/Execution/Portfolio as separate components
- Ports and adapters — venue-specific code isolated behind adapters
- Single-threaded deterministic core — why backtest and live can share identical logic

See `../Learnings/02-engineering-architecture.md` for a status-tracked note on this.

## First hands-on project

Build a minimal C++ event-driven backtest skeleton:

- A typed message bus
- Three components: `DataEngine`, `RiskEngine` (stub), `ExecutionEngine` (stub)
- Process one equity's price series end to end through the bus

Small scope, real architecture. This skeleton is reused in Phase 3.

## Parallel track

Algorithms/data-structures sharpening — the coding-interview bar at these firms is separate from the brainteaser rounds and expects real competence, not scripting-level familiarity.
