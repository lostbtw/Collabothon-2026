# Instructions for every Claude Code session in this repo

Six people build **Ordo** (an "Autonomous CFO" for small companies) at Collabothon 2026. Each person has one role and one Claude Code session. Coding ends **Sunday 22 Nov 2026, 10:00**. Feature freeze **Saturday 22:00**.

Read first, in this order: `docs/04_DEV_PLAN.md` (your role's section), `docs/01_SOLUTION.md`, `contracts/README.md`.

## 1. Which role am I?

Read the file `.role` in the repo root (one digit, 1–6, not committed). If it does not exist, ask the human which role they have and create it: `echo 3 > .role`.

| Role | Name | Folders you own (only you edit these) |
|---|---|---|
| 1 | Platform, model, document reading | `deploy/`, `notebooks/`, `backend/pipeline/extract/` |
| 2 | Connectors and sync | `backend/connectors/`, `backend/queue/`, `backend/executor/`, `sim/bank/`, `sim/releaser/` |
| 3 | Matching and document test set | `backend/pipeline/` (except `extract/`), `sim/documents/` |
| 4 | Finance engine, rules, scenario | `backend/finance/`, `sim/scenario/` |
| 5 | API, agents, approvals (integration captain) | `backend/api/`, `backend/agents/`, `backend/db/` |
| 6 | Frontend and UX | `frontend/` |

Shared, change only by the contract rule (section 4): `contracts/`.
Never edit: another role's folders, another role's `status/role-N.json`.

## 2. The work loop

Progress lives in `status/role-N.json` (one file per role) and is read and written with `tools/status.py`. Other roles' progress is always read from `origin/main`, so it is as fresh as their last push.

At the start of the session and after finishing every task:

```bash
git pull --rebase --autostash
python3 tools/status.py board        # what everyone is doing
python3 tools/status.py requests     # has anyone asked me for something?
python3 tools/status.py next         # what I can start now
```

For each task:

1. `python3 tools/status.py set <ID> in_progress --push`
2. Do the work, in your folders only. Commit small. `git pull --rebase --autostash && git push` often. `main` must always run.
3. When it works and its tests pass: `python3 tools/status.py set <ID> done --evidence "<commit hash or URL>" --push`

A task is `done` only when it works against the **real** thing it depends on.

## 3. When something I need is not finished yet

`next` shows three kinds of startable task:

| Label | Meaning | What to do |
|---|---|---|
| `READY` | Everything it needs is done | Start it |
| `START ON MOCK` | A dependency from another role is not done, but a stand-in exists (the line "meanwhile: …") | Build it against the stand-in. When it works on the stand-in: `set <ID> mock_done --push`. Then start a background wait (below) and move to your next task |
| `INTEGRATE NOW` | You finished on a stand-in and the real dependency has now landed | Do this first: swap the stand-in for the real thing, test, then `set <ID> done` |

Do not sit idle and do not poll by hand. Start a background wait and keep working; you will be notified when it exits:

```bash
python3 tools/status.py wait 1.4 --timeout 7200     # run in the background
```

Exit code 0 = the task is done on `origin/main`: pull, then integrate. Exit code 2 = timeout: run `board`, tell the human, and consider `ask`.

If a task shows `WAITING` (no stand-in exists) and you have nothing else startable: tell the human, and leave a request for the owning role.

Need something from another role (a field, an endpoint, a fix)? Do not edit their code:

```bash
python3 tools/status.py ask 5 "raw_item needs a forwarded_by field in metadata" --push
```

They see it in `requests` and on the `board`, and close it with `resolve <file> --push`.

## 4. Contracts

`contracts/` is the agreement between roles. Fixtures in `contracts/fixtures/` are the stand-ins everyone builds against.
A contract change is one commit that changes the schema **and** its fixture, with `python3 contracts/validate_fixtures.py` printing `0 invalid`. Announce it with `ask <consumer role> "..."`. After the feature freeze: only new optional fields.

## 5. Is it still possible?

```bash
python3 tools/status.py forecast
```

It compares each role's remaining must-have hours with the working hours left before the freeze. If your role shows `OVER`, tell the human immediately and propose a cut from `docs/04_DEV_PLAN.md` section 5 (the cut order). Never silently drop a must-have: mark it `cut` with a `--note` saying what replaces it.

## 6. Hard rules (do not break, whatever the task)

1. The app and the model run on the team's OpenShift AI cluster. The app's LLM is an open-weights model served there. Never add a call to a hosted LLM API in app code.
2. Synthetic data only. Invented companies, people and tax ids, marked SAMPLE. No real names, no real documents, no real bank data in the repo or on the cluster.
3. No secrets in Git. Use OpenShift Secrets; commit only `deploy/secrets.example.yaml` with names.
4. The LLM never produces a number that reaches the user directly. Numbers come from the finance engine or from extraction with a confidence value.
5. Every Recommendation carries `control_level`, `execution_mode`, `explanation` and at least one `evidence` link. All execution is `simulated`.
6. Money is a decimal string plus currency, never a float. Negative means money out.
7. Before reopening a design decision, read `DECISIONS.md`.
8. Commits and pull requests carry the human author only. No AI attribution of any kind: no `Co-Authored-By` trailer for an assistant, no "Generated with" line, no assistant or tool name in commit messages, branch names or PR text. `.claude/settings.json` switches the automatic attribution off; do not add it by hand either.

## 7. Keep the human informed

After each task, say in two lines: what is done, what you start next, and whether anything is blocked. Update the one-line status others see:

```bash
python3 tools/status.py now "mailbox connector: attachments parsed, cursor next" --push
```
