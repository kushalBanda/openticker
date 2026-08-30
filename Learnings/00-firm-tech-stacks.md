Status: not-read

# Elite quant firm tech stacks

Verified 2026-08-30 against current job postings, engineering blogs, and talks.

- **Jane Street** — OCaml, firm-wide, deliberate outlier (type safety/correctness over raw speed). Interviews are language-agnostic; OCaml taught on the job.
  - [Making OCaml Safe for Performance Engineering](https://www.janestreet.com/tech-talks/making-ocaml-safe-for-performance-engineering/)
  - [Jane Street: Full Story](https://youngandcalculated.substack.com/p/jane-street-the-full-story-of-wall)
- **Optiver** — C++, latency-first. New-grad SWE interviews require C++/C/Java/C#.
  - [Most Valuable Skills in Quant Finance](https://youngandcalculated.substack.com/p/the-most-valuable-skills-in-quant)
- **Jump Trading** — C++, low-latency hard requirement for trading-adjacent roles.
  - [Coding OA Patterns: Citadel, HRT, Jane Street](https://www.techinterview.org/post/3233474726/coding-oa-patterns-citadel-hrt-jane-street/)
- **Hudson River Trading (HRT)** — split by team: Trading Tech ~70% C++/30% Python, Research ~70% Python/30% C++. Rust adopted for some new perf-critical components. Infra: Python + some Go. Hardware/FPGA: Verilog.
  - [HRT job posting](https://www.hudsonrivertrading.com/hrt-job/software-engineer-c-or-python-2027-grads/)
  - [Python or C++? HRT explains](https://www.efinancialcareers.com/news/python-or-c-hudson-river-trading-explains-which-languages-are-needed-for-each-job)
- **Citadel Securities** — C++ central, multi-round systems-level coding interviews.
  - [Coding OA Patterns](https://www.techinterview.org/post/3233474726/coding-oa-patterns-citadel-hrt-jane-street/)

## Takeaway

4 of 5 firms run C++ (execution) + Python (research). Jane Street is the sole OCaml outlier. This is why the curriculum's core stack is C++ + Python, with OCaml/Rust as optional bonus, not prerequisite.

## Questions to bring back

- Does the OCaml gap matter if Jane Street specifically is the top target?
- Worth a small OCaml bonus module later, or skip entirely?
