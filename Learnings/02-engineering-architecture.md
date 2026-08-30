Status: not-read

# NautilusTrader architecture — production trading-system design

Source: `docs/resources/nautilus_trader/docs/concepts/architecture.md` (cloned repo, read-only reference).

Why this matters: this is what an actual production-grade trading engine's design looks like — not a toy backtester. The principles translate to C++ even though NautilusTrader itself is Rust-core.

## Key principles to internalize

- **Quality attribute ordering**: Reliability > Performance > Modularity > Testability > Maintainability > Deployability. Correctness beats speed, always, when they trade off.
- **Fail-fast / crash-only design**: invalid data (NaN price, negative timestamp, overflow) errors or panics immediately at the boundary, rather than silently propagating into a wrong trade.
- **Event-driven message-bus architecture**: Data/Risk/Execution/Portfolio engines are separate components communicating via typed pub/sub, not direct function calls.
- **Ports and adapters (hexagonal architecture)**: venue-specific integration code is isolated behind adapters; the core stays venue-agnostic.
- **Single-threaded deterministic core**: the trading logic runs on one thread for deterministic event ordering; async I/O happens on separate threads/tasks at the edges. This determinism is *why* backtest and live can share identical strategy code (research-to-live parity).

## Direct link to the Phase 2 project

Your minimal C++ backtest skeleton (message bus + DataEngine/RiskEngine/ExecutionEngine) is a small-scale copy of this pattern. Read this file before writing that code.

## Questions to bring back

- Does fail-fast vs graceful-degradation make sense as a design choice, or want to walk through the trade-off with an example?
- Want to see the actual architecture.md diagrams (mermaid) rendered before starting the build?
