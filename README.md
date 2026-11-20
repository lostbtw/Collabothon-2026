# Ordo — Autonomous CFO (Collabothon 2026, Commerzbank x Red Hat)

Planning package produced on Friday 20 Nov 2026. Coding ends **Sunday 10:00**.

| Read this | If you are |
|---|---|
| [docs/04_DEV_PLAN.md](docs/04_DEV_PLAN.md) | Everyone — roles, tasks, hour-by-hour timeline, cut order, Git rules |
| [docs/01_SOLUTION.md](docs/01_SOLUTION.md) | Everyone — product, control model, architecture, model choice, bonus items |
| [docs/02_DATA_AND_SYNC.md](docs/02_DATA_AND_SYNC.md) | Roles 2, 3, 4 — dataset, connectors, matching engine, domain rules |
| [contracts/](contracts/README.md) | Everyone who writes code — schemas, API, events, fixtures (the mocks) |
| [docs/05_DEMO_AND_PITCH.md](docs/05_DEMO_AND_PITCH.md) | Roles 4, 5, 6 — 1-minute and 3-minute scripts, fallbacks, critic pass |
| [docs/06_RISKS_AND_QUESTIONS.md](docs/06_RISKS_AND_QUESTIONS.md) | Stand-ups; questions for the organisers |
| [docs/00_ANALYSIS.md](docs/00_ANALYSIS.md) | Anyone who wants the reasons — challenge, data profile, idea verdicts, feasibility, research |
| [DECISIONS.md](DECISIONS.md) | Before reopening a decision |
| [spikes/](spikes/README.md) | Proofs you can run in seconds |
| [CLAUDE.md](CLAUDE.md) | Every Claude Code session reads this: role folders, work loop, waiting on dependencies, hard rules |
| `python3 tools/status.py board` | Live team progress; `next`, `wait`, `forecast` — see `CLAUDE.md` |

Set-up per person: clone, `echo <your role number 1-6> > .role`, start Claude Code in the folder, say "start my role".

Checks: `python3 contracts/validate_fixtures.py` (expects `0 invalid`).

Everything in this repository is synthetic. Company, people, vendors and tax ids are invented and marked SAMPLE.
