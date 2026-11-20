# Ordo — Autonomous CFO (Collabothon 2026, Commerzbank x Red Hat)

Ordo turns a small company's scattered money data into one owner-approved ledger, forecasts cash day by day, and prepares the fix when a gap is coming. The owner approves; every action runs in simulation. Coding ends **Sunday 22 Nov 2026, 10:00**.

| Where | What |
|---|---|
| [Issues #1–#6](https://github.com/lostbtw/Collabothon-2026/issues?q=label%3Aspec) | One spec per role; each role's tickets are its sub-issues |
| [CLAUDE.md](CLAUDE.md) | Roles, folders, the work loop, hard rules, milestones, cut order |
| [GLOSSARY.md](GLOSSARY.md) | The project's vocabulary |
| [contracts/](contracts/README.md) | Schemas, API, events and fixtures every role builds against |
| [DECISIONS.md](DECISIONS.md) | Why things are the way they are |

Set-up per person: clone, `echo <your role number 1-6> > .role`, start Claude Code in the folder, pick a ticket in the browser (see `CLAUDE.md` section 2) and tell Claude its number. One branch and one pull request per ticket; nobody commits to `main` directly.

Checks: `python3 contracts/validate_fixtures.py` (expects `0 invalid`).

Everything in this repository is synthetic. Company, people, vendors and tax ids are invented and marked SAMPLE.
