# Elite Quant Curriculum — Design Spec

Date: 2026-08-30

## Goal

Build a self-study repo that prepares the user for hiring at elite quant/HFT firms
(Jane Street, Optiver, Jump Trading, HRT, Citadel Securities tier). User has decent
math/CS/finance background but is new to quant specifically. Time budget: part-time,
5-10 hrs/week (curriculum content is phase-ordered, not time-boxed — no week estimates
in any phase doc). Equities first, options/derivatives later.

## Research findings behind the design

- 4 of 5 target firms (Optiver, Jump, HRT, Citadel Securities) run **C++ for execution
  + Python for research**. Jane Street is the sole outlier, using OCaml firm-wide.
  Rust is emerging (HRT, some newer shops) but not replacing C++ anywhere yet.
  Decision: **C++ + Python is the core stack.** OCaml and Rust are optional/bonus,
  not prerequisites.
- Interviews at these firms test, in rough order of gate strength: mental math
  (hard gate — Jane Street rejects well-credentialed candidates on this alone),
  probability under time pressure, market intuition/game theory, and separately,
  solid coding/algorithms competence (not scripting-level).
- `nautilus_trader` (github.com/nautechsystems/nautilus_trader) — Rust-core,
  production-grade, event-driven, multi-asset/multi-venue trading engine — is a
  strong architecture reference even though the user's build language is C++, not
  Rust. Its `docs/concepts/architecture.md` documents real production-trading design
  principles: quality-attribute ordering (Reliability > Performance > Modularity >
  Testability > Maintainability > Deployability), fail-fast/crash-only design,
  event-driven message-bus architecture, ports-and-adapters isolation of venue code,
  and backtest/live code parity via a single-threaded deterministic core. These
  principles inform Phase 2 below, translated to C++.

## Repo structure

```
01_foundations/       — probability/stats, linear algebra, mental math, C++ fundamentals
02_engineering/        — event-driven backtest engine build (C++), architecture study
03_strategies/         — equities strategies run through own engine
04_derivatives/        — options/derivatives bridge
05_interview_prep/     — puzzle books, mock interviews, market-making games
Learnings/             — topic notes with read-status tracking (see below)
docs/resources/        — cloned reference repos (e.g. nautilus_trader), read-only study material
docs/superpowers/specs/ — design specs (this file and future ones)
```

No timeline files anywhere — phase docs are ordered by dependency, not by week.

## Phase content (no time estimates)

1. **Foundations** — probability/stats rigor (not descriptive-stats-only), linear
   algebra, daily mental math drilling (Zetamac), C++ fundamentals (memory model,
   RAII, move semantics — real language mechanics, not just syntax).
2. **Engineering rigor** — study `nautilus_trader`'s architecture doc as a model,
   then build a minimal event-driven backtest engine in C++: typed message bus,
   fail-fast data validation, separate Data/Risk/Execution components. Parallel:
   algorithms/data-structures sharpening for the coding interview bar.
3. **Quant strategy + backtesting** — equities strategies (momentum, mean-reversion)
   run through the Phase 2 engine, not a toy pandas script. Compare against a naive
   backtest to feel the architectural difference.
4. **Options/derivatives bridge** — Black-Scholes, Greeks, stochastic calculus basics.
5. **Interview-specific prep** — Green Book (Zhou, *A Practical Guide to Quantitative
   Finance Interviews*) → *Heard on the Street* (Crack) → *Fifty Challenging Problems
   in Probability* (Mosteller). Mock interviews, market-making games.

**Parallel track from day one:** daily mental math + probability drills run alongside
every phase, not deferred to the end.

## First hands-on project

In `02_engineering/`: a minimal C++ event-driven backtest skeleton — a message bus
plus three components (DataEngine, RiskEngine stub, ExecutionEngine stub) processing
one equity's price series end to end. Small, but real architecture, not a toy script.

## Learnings folder — read-status tracking system

Purpose: user reads topic notes (links + short write-ups) at their own pace outside
chat, then comes back to discuss/ask questions. Needs a simple status marker so we
both know what's been read.

- `Learnings/README.md` — index table: topic, phase it belongs to, status, link to
  the note file.
- One file per topic under `Learnings/<phase-prefix>-<topic-slug>.md`, each with a
  frontmatter-style status line at the top:
  `Status: not-read` / `Status: in-progress` / `Status: understood`
  followed by links and a short explanation of the topic.
- User edits the `Status:` line manually when they've read something; that's the
  only interaction contract — no automation, no tooling needed.

## Out of scope for this spec

- Rust or OCaml as primary build languages (kept as bonus/optional notes only).
- Any concrete week/time estimates.
- Live trading / real capital deployment — this repo is a learning system, not a
  production trading system.
