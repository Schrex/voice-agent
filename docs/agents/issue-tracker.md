# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use `gh api` (GitHub's REST API) for all operations.

Why REST only: claude.ai/code cloud sessions block GitHub's GraphQL API, and the high-level `gh issue` / `gh pr` commands are built on GraphQL, so they fail there with `HTTP 403: GitHub GraphQL is not available`. `gh api repos/...` calls work everywhere: in cloud sessions the session proxy supplies GitHub auth (no `GH_TOKEN` needed); on a laptop, after `gh auth login`. Agents may also use the GitHub tools built into the session instead of `gh`.

`R=repos/Schrex/voice-agent` below. Multi-line bodies: write to a file and pass `-F body=@file.md`.

## Conventions

- **Create an issue**: `gh api -X POST $R/issues -f title="..." -F body=@body.md -f 'labels[]=needs-triage'`.
- **Read an issue**: `gh api $R/issues/<n> --jq '{number, title, body, state, labels: [.labels[].name], assignees: [.assignees[].login]}'`; comments: `gh api $R/issues/<n>/comments --jq '.[].body'`.
- **List issues**: `gh api --paginate "$R/issues?state=open&labels=<label>&per_page=100" --jq '.[] | select(.pull_request | not) | {number, title, labels: [.labels[].name]}'`. The issues endpoint also returns PRs; the `select` drops them.
- **Make an issue a sub-issue of a parent**: `gh api -X POST $R/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>` (database id, as in **Blocking** below). Without sub-issues, put `Part of #<parent>` at the top of the child body.
- **Comment on an issue**: `gh api -X POST $R/issues/<n>/comments -f body="..."`
- **Apply / remove labels**: `gh api -X POST $R/issues/<n>/labels -f 'labels[]=<label>'` / `gh api -X DELETE $R/issues/<n>/labels/<label>`
- **Close**: comment as above, then `gh api -X PATCH $R/issues/<n> -f state=closed -f state_reason=completed` (or `not_planned`).

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues:

- **Read a PR**: `gh api $R/pulls/<n>`, comments via `gh api $R/issues/<n>/comments`, diff via `gh api $R/pulls/<n> -H 'Accept: application/vnd.github.diff'`.
- **List external PRs for triage**: `gh api --paginate "$R/pulls?state=open" --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`.
- **Comment / label / close**: the issue calls above work on PR numbers too; close with `gh api -X PATCH $R/pulls/<n> -f state=closed`.
- **Open a draft PR**: `gh api -X POST $R/pulls -f title="..." -f head=<branch> -f base=main -F draft=true -F body=@body.md`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: `gh api $R/issues/42` answers for both, and a `pull_request` key in the result means it is a PR.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. Create as above with `-f 'labels[]=wayfinder:map'`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (see **Make an issue a sub-issue of a parent**). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api -X POST $R/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api $R/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate); list them with `gh api $R/issues/<n>/dependencies/blocked_by --jq '.[].number'`. Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: open `ready-for-agent` issues with no open blocker and no assignee, lowest number first:
  `gh api --paginate "$R/issues?labels=ready-for-agent&state=open&per_page=100" --jq '.[] | select(.pull_request | not) | select((.issue_dependencies_summary.blocked_by // 0) == 0 and (.assignees | length) == 0) | "#\(.number) \(.title)"'`
- **Claim**: `gh api -X POST $R/issues/<n>/assignees -f 'assignees[]=<github-login>'`, the session's first write. REST has no `@me`; get the login with `gh api user --jq .login`.
- **Resolve**: comment with the answer, close (both above), then append a context pointer (gist + link) to the map's Decisions-so-far.
