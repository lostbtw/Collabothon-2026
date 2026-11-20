# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root: the project's vocabulary.
- **`DECISIONS.md`** at the repo root: this repo's decision log, used instead of `docs/adr/`. `R-xx` entries are recommendations on the team's fixed decisions, `D-xx` entries are decisions on how to build; newest at the bottom. Read the entries that touch the area you're about to work in.
- **The spec issue of the role you work for** (#1–#6, see `docs/agents/issue-tracker.md`): the domain rules, numbers and decision tables for that area.

If `GLOSSARY.md` or `DECISIONS.md` is missing, **proceed silently**. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) maintains them.

## File structure

Single-context repo:

```
/
├── GLOSSARY.md
├── DECISIONS.md      ← decision log (instead of docs/adr/)
├── contracts/        ← schemas, API, events, fixtures shared by all roles
└── backend/, frontend/, sim/, deploy/
```

## Recording a new decision

Append it to `DECISIONS.md` as the next `D-xx`, in the existing style: a heading with the decision in one line, then context, decision, the rejected alternative, and why. Only for decisions that are hard to reverse, surprising without context, and the result of a real trade-off.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag decision conflicts

If your output contradicts an entry in `DECISIONS.md`, surface it explicitly rather than silently overriding:

> _Contradicts D-20 (one ledger writer), but worth reopening because…_
