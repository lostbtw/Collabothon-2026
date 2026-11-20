# Instructions for every Claude Code session in this repo

Six people build **Ordo** (an "Autonomous CFO" for small companies) at Collabothon 2026. Each person has one role and one Claude Code session. Feature freeze **Saturday 22:00**; coding ends **Sunday 22 Nov 2026, 10:00**.

Ordo connects to where a small company's money data lives (mailbox, bank accounts, invoicing tool, exchange rates), reads and reconciles it into one owner-approved ledger, forecasts cash day by day, and when a gap is coming explains why and prepares the fix (up to a credit line), which runs only after the owner approves, and only in simulation. A second agent, FX Shield, protects the foreign-currency deals where exchange-rate risk really matters.

Read first: your role's **spec issue** (open it in the browser or read it through the API), `GLOSSARY.md`, `contracts/README.md`.

## 1. Which role am I?

Read `.role` in the repo root (one digit, 1–6, not committed). If it does not exist, ask the human which role they have and create it: `echo 3 > .role`.

| Role | Name | Spec | Folders you own (only you edit these) |
|---|---|---|---|
| 1 | Platform, model, document reading | #1 | `deploy/`, `notebooks/`, `backend/pipeline/extract/` |
| 2 | Connectors and sync | #2 | `backend/connectors/`, `backend/queue/`, `backend/executor/`, `sim/bank/`, `sim/releaser/` |
| 3 | Matching and document test set | #3 | `backend/pipeline/` (except `extract/`), `sim/documents/` |
| 4 | Finance engine, FX Shield, scenario | #4 | `backend/finance/`, `sim/scenario/` |
| 5 | API, agents, approvals (integration captain) | #5 | `backend/api/`, `backend/agents/`, `backend/db/`, the backend package skeleton and CI |
| 6 | Frontend and UX | #6 | `frontend/` |

Shared, change only by the contract rule (section 4): `contracts/`. Never edit another role's folders.

## 2. The work loop

Tickets are GitHub issues: sub-issues of your spec, labelled `role:<N>`. Everything about issues and pull requests is done **in the browser** (no `gh` CLI needed): `https://github.com/lostbtw/Collabothon-2026/issues`. Filter by label `role:<N>`; a ticket is startable when it has no open "blocked by" and no assignee.

At the start of the session and after finishing every ticket: `git switch main && git pull --rebase`. The human tells you which ticket to work on (its number or its `R<role>·<id>` title). Read it and its parent spec; the human can paste the text, or you can read a public issue with `curl -s https://api.github.com/repos/lostbtw/Collabothon-2026/issues/<n>`. Requests from other roles carry the label `needs-triage`.

Take musts before shoulds. For each ticket:

1. The human claims it in the browser (Assignees: assign yourself).
2. **Never commit to `main` directly.** One branch per ticket, cut from fresh `main`: `git switch main && git pull --rebase && git switch -c r<role>/<n>-<short-slug>` (for example `r2/13-bank-sim`). Work in your folders only, commit small with `#<n>` in the message, push the branch often (`git push -u origin <branch>`).
3. Done = acceptance criteria met, tests pass, and it works against the **real** thing it depends on. Then the human opens a pull request into `main` (GitHub shows a link after `git push`), title `R<role>·<id> <title>`, body `Closes #<n>. <what was verified>`. Before merging: `git fetch && git rebase origin/main`, tests green. Merge it yourselves (squash) once it is green; use another role's review only for changes under `contracts/`. Merging closes the ticket through `Closes #<n>`.

`main` must always run. After a merge, delete the branch and start the next ticket from fresh `main`. A ticket that is blocked by another ticket's code branches from `main` once that code is merged; if it must start earlier, branch from the other branch and say so in the PR.

**Integrates with** (in the ticket body) means the dependency is not finished but a stand-in exists: build against the stand-in, open the PR as a **draft** with "works on the stand-in" in the body, and take the next ticket. When the real dependency lands, swap it in first, mark the PR ready, then merge.

Need something from another role (a field, an endpoint, a fix)? Leave their code alone: comment on their ticket, or open a new issue with labels `role:<their N>` and `needs-triage`.

Running out of time? Propose a cut from section 5 to the human. A must-have is never dropped silently: close it with label `wontfix` and a comment naming what replaces it.

A contract change (section 4) is its own small PR under `contracts/`, merged before the code that depends on it.

## 3. Product rules every role builds to

**Control model.** Every agent output carries both labels (schema fields `control_level`, `execution_mode`):

| Control level | Meaning | Badge |
|---|---|---|
| `analysed_autonomously` | Agent did it alone; read-only, no effect outside the app, listed in "What I did on my own", undoable | grey |
| `recommendation` | Advice; nothing to execute | blue |
| `approval_required` | Action prepared; runs only after the owner approves, possibly edited | amber |

Execution mode: `none`, `simulated` (every action in this build, against the Sandbox Bank, the word SIMULATED on the button and in the result), `permitted` (refused by the server in this build).

**Hard rules** (do not break, whatever the task):

1. The app and the model run on the team's OpenShift AI cluster. The app's LLM is an open-weights model served there. Never add a call to a hosted LLM API in app code.
2. Synthetic data only. Invented companies, people and tax ids, marked SAMPLE. No real names, no real documents, no real bank data, no real e-mail addresses in the repo or on the cluster.
3. No secrets in Git. Use OpenShift Secrets; commit only `deploy/secrets.example.yaml` with names.
4. The LLM never produces a number that reaches the user directly. Numbers come from the finance engine or from extraction with a confidence value.
5. Every Recommendation carries `control_level`, `execution_mode`, `explanation` and at least one `evidence` link. All execution is `simulated`.
6. Money is a decimal string plus currency, never a float. Negative means money out.
7. Before reopening a design decision, read `DECISIONS.md`.
8. Commits and pull requests carry the human author only. No AI attribution of any kind: no `Co-Authored-By` trailer for an assistant, no "Generated with" line, no assistant or tool name in commit messages, branch names or PR text. `.claude/settings.json` switches the automatic attribution off; do not add it by hand either.

## 4. Contracts

`contracts/` is the agreement between roles; `contracts/fixtures/` are the stand-ins everyone builds against. A contract change is one commit that changes the schema **and** its fixture, with `python3 contracts/validate_fixtures.py` printing `0 invalid`. Announce it with a comment on the consuming role's spec issue. After the feature freeze: only new optional fields. Role 5 arbitrates conflicts.

## 5. Milestones and cut order

| When | Milestone |
|---|---|
| Fri 21:00 | Skeleton API serves every contract path from fixtures |
| Fri 22:00 | **M1**: hello-model page served from the cluster (hard criteria met) |
| Fri 24:00 | **M2**: walking skeleton on the cluster |
| Sat 13:00 | **M3**: hero flow works once on the cluster; screen video recorded |
| Sat 20:00 | **M4**: liquidity flow complete on real data, pizzeria included |
| Sat 22:00 | **Feature freeze**: only bug, data and copy fixes after this |
| Sun 09:00 | Code freeze, tag `demo` |

Cut from the top, decided at Sat 18:00 and 22:00: KSeF API connector → OGX → FX Shield extras (netting, option, graphic) → free SQL chat tool → Commerzbank sandbox → NeMo Guardrails → inFakt → tax-reserve card → free-text chat (keep the suggested-question buttons) → Borsuk Labs backfill history. **Never cut:** the served model on the cluster, the hero receipt flow, forecast + credit card + approval + simulated execution, the control-level badges, the pizzeria company.

Emergency demo if the messy pipeline is not stable by Sat 22:00: pizzeria-only liquidity flow (needs roles 1, 2 bank only, 4, 5, 6).

## 6. Keep the human informed

After each ticket, say in two lines: what is done, what you start next, and whether anything is blocked.

## Agent skills

### Issue tracker

Specs and tickets are GitHub issues in `lostbtw/Collabothon-2026` (specs #1–#6, tickets are their sub-issues).

### Triage labels

Labels: `spec`, `role:<N>`, `priority:<must|should>`, `needs-triage` (a request waiting for the owning role).

### Domain docs

Single-context: `GLOSSARY.md` and `DECISIONS.md` (used instead of `docs/adr/`) at the root. See `docs/agents/domain.md`.
