# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A self-study curriculum repo, not a software product (yet). It targets hiring at elite quant/HFT firms (Jane Street, Optiver, Jump Trading, Hudson River Trading, Citadel Securities tier). There is no build/lint/test tooling at the repo root today — code will appear inside the phase folders as the curriculum progresses, starting with a C++ backtest engine in `02_engineering/`. When code is added to a phase folder, its own build/test commands belong in that folder's README, not here, unless a repo-wide toolchain is introduced.

Design spec (read this for full rationale): `docs/superpowers/specs/2026-08-30-elite-quant-curriculum-design.md`

## Core stack decision

**C++ + Python.** Chosen because 4 of 5 target firms (Optiver, Jump, HRT, Citadel Securities) run C++ for execution and Python for research. Jane Street's OCaml and any Rust usage are bonus/optional, not prerequisites — do not default to Rust or OCaml for exercises unless the user asks.

## Repo structure and how it fits together

The phases are ordered by dependency and build on each other — later phases assume earlier ones are done:

- `01_foundations/` — probability/stats, linear algebra, mental math, C++ fundamentals. Prerequisite for everything else.
- `02_engineering/` — builds a minimal event-driven C++ backtest engine (message bus + `DataEngine`/`RiskEngine`/`ExecutionEngine` components), modeled on the architecture principles documented in `docs/resources/nautilus_trader/docs/concepts/architecture.md` (quality-attribute ordering, fail-fast design, ports-and-adapters, single-threaded deterministic core). This engine is the vehicle for Phase 3 — it is not a throwaway exercise.
- `03_strategies/` — equities strategies (momentum, mean-reversion) run through the Phase 2 engine, deliberately compared against a naive pandas backtest to make the architectural difference concrete.
- `04_derivatives/` — options/derivatives bridge (Black-Scholes, Greeks, stochastic calculus), sequenced after equities work is solid.
- `05_interview_prep/` — brainteaser/probability/market-making prep. Mental math and probability drills are meant to run in parallel from Phase 1 onward, not deferred to this phase.
- `Learnings/` — topic notes for the user to read outside chat, each with a `Status: not-read` / `in-progress` / `understood` line at the top of the file and an index table in `Learnings/README.md`. When the user says they've read or updated the status of a note, check that file's `Status:` line and its "Questions to bring back" section before discussing the topic.
- `docs/resources/` — cloned reference repos (e.g. `nautilus_trader`) kept as read-only architecture study material. Gitignored (`docs/resources/*/`) — never treat these as vendored dependencies of this repo, and never edit files inside them.

## Explicit constraints (deliberate, do not "fix")

- No week/time estimates anywhere in phase docs or specs — sequencing is by dependency, not by timeline. This was an explicit user requirement.
- The Phase 2 engine is meant to be hand-built, not swapped for an off-the-shelf backtesting library — the point is production-grade engineering practice, not the fastest path to a working backtest.
