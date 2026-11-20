# Issue tracker: GitHub

Specs and tickets live as GitHub issues in `lostbtw/Collabothon-2026`. Use the `gh` CLI for all operations; it infers the repo from `git remote -v`.

## How this repo uses issues

- **Specs** are issues #1–#6, one per role, labelled `spec` and `role:<N>`. Each role's **tickets** are sub-issues of its spec, labelled `role:<N>`, `priority:must` or `priority:should`, and `ready-for-agent`.
- **Blocked by** (native issue dependency) = a hard dependency: the ticket cannot start until the blocker is closed.
- **Integrates with** (section in the ticket body) = a soft dependency: start now on the stand-in named under "Stand-in until blockers land"; close the ticket only after it works against the real thing.
- Ticket titles start with `R<role>·<id>` (for example `R3·3.4`); people refer to tickets by that id or by `#number`.

## Conventions

- **What can I start**: `gh issue list --label role:<N> --state open --search "-is:blocked -label:spec no:assignee" --json number,title --jq '.[] | "\(.number) \(.title)"'`. Musts before shoulds.
- **Claim**: `gh issue edit <n> --add-assignee @me`, before any work.
- **Read an issue**: `gh issue view <n> --comments`. Always read the parent spec too.
- **Create an issue**: `gh issue create --title "..." --body-file <file> --label "role:<N>,needs-triage"`. For a request to another role, label it with their role.
- **Make an issue a sub-issue**: `gh issue create --parent <spec> ...` or `gh issue edit <spec> --add-sub-issue <child>`.
- **Blocking**: `gh issue create --blocked-by <n>,<n> ...` or `gh issue edit <child> --add-blocked-by <blocker>`. Open blockers: `gh api repos/lostbtw/Collabothon-2026/issues/<n> --jq .issue_dependencies_summary.blocked_by` (0 = startable).
- **Wait for another ticket** without polling by hand, in the background: `until [ "$(gh issue view <n> --json state --jq .state)" = CLOSED ]; do sleep 120; done`.
- **Comment**: `gh issue comment <n> --body "..."`.
- **Labels**: `gh issue edit <n> --add-label "..."` / `--remove-label "..."`.
- **Close**: comment first with the evidence (`gh issue comment <n> --body "Done in <commit sha>: <what was verified>"`), then `gh issue close <n>`. On an already-closed issue, `gh issue close --comment` drops the comment and still exits 0.

File issues only into `lostbtw/Collabothon-2026`.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

## When a skill says "publish to the issue tracker"

Create a GitHub issue. A new spec gets labels `spec,role:<N>`; a new ticket gets `--parent <its role's spec>`, its role and priority labels, and native `--blocked-by` edges for hard dependencies.

## When a skill says "fetch the relevant ticket"

`gh issue view <n> --comments`, plus its parent spec.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: a sub-issue of the map. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: see **Blocking** under Conventions.
- **Frontier query**: the map's open sub-issues with no open blocker and no assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
