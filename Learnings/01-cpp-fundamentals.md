Status: not-read

# C++ fundamentals for trading systems

Why this matters: 4 of 5 target firms run C++ for execution. This is not "learn C++ syntax" — it's the mechanics that matter in a low-latency, correctness-critical system.

## Core topics

- Memory model: stack vs heap, ownership
- RAII (Resource Acquisition Is Initialization) — why C++ trading code leans on this instead of manual cleanup
- Move semantics and rvalue references — avoiding unnecessary copies in hot paths
- References vs pointers, when to use which
- `const` correctness

## Why this connects to Phase 2

The event-driven backtest engine you build in `02_engineering` needs real ownership discipline — a message bus passing typed events between components is exactly where sloppy memory handling causes bugs. Read this before starting that build.

## Questions to bring back

- Any specific area (move semantics, RAII) that needs a worked example against the Phase 2 engine code once it exists?
