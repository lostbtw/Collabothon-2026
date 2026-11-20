# Ordo — Autonomous CFO (Collabothon 2026, Commerzbank x Red Hat)

Ordo turns a small company's scattered money data into one owner-approved ledger, forecasts cash day by day, and prepares the fix when a gap is coming. The owner approves; every action runs in simulation. Coding ends **Sunday 22 Nov 2026, 10:00**.

| Where | What |
|---|---|
| [Issues #1–#6](https://github.com/lostbtw/Collabothon-2026/issues?q=label%3Aspec) | One spec per role; each role's tickets are its sub-issues |
| [CLAUDE.md](CLAUDE.md) | Roles, folders, the work loop, hard rules, milestones, cut order |
| [GLOSSARY.md](GLOSSARY.md) | The project's vocabulary |
| [contracts/](contracts/README.md) | Schemas, API, events and fixtures every role builds against |
| [DECISIONS.md](DECISIONS.md) | Why things are the way they are |

Set-up per person: clone, `echo <your role number 1-6> > .role`, install the GitHub CLI and run `gh auth login`, start Claude Code in the folder, pick a ticket (see `CLAUDE.md` section 2) and run `/implement #<number>`.

Backend: one Python 3.12 package in `backend/`, managed with [uv](https://docs.astral.sh/uv/). `uv sync` installs it; each process starts as `uv run python -m backend <api|connectors|pipeline|agents>`. Your process goes in `backend/<your folder>/main.py` as `run(argv)`; until then the entrypoint is a placeholder. Tests live next to the code they test (`backend/<folder>/tests/`).

Database: Postgres, schema in `backend/db/migrations/`; `uv run python -m backend.db setup` migrates and seeds the database at `ORDO_DATABASE_URL`. Entities are read and written through `backend.db.store.Store`; pydantic models of every contract entity are in `backend.db.contracts.MODELS`. Tests that need a database use the `db` fixture: CI provides Postgres, and locally `uv sync --group localdb` installs a private Postgres (pgserver) so no Docker is needed; without either, those tests are skipped.

Checks (the same ones CI runs on every pull request): `python3 contracts/validate_fixtures.py` (expects `0 invalid`), `uv run python -m pytest` (all backend tests), and `npx tsc --noEmit` in `frontend/`.

Everything in this repository is synthetic. Company, people, vendors and tax ids are invented and marked SAMPLE.
