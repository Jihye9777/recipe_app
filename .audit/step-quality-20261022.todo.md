# Step evidence feature

- [x] First commit existing changes.
  - Baseline 2e6e4c7. Python 38 tests, JS syntax and both DOM suites passed.
- [x] `how` over the affected subsystem.
  - Grounding: current README ingestion/search flow and source-backed structure investigation in this conversation. Existing steps are strings, quality checks ingredient evidence only, review uses durable interrupts, SQLite stores recipe JSON.
- [x] `architect` for parallel design exploration.
  - A chosen by root and independent cross-judge; B's single pure quality owner grafted. Contract docs/superpowers/plans/2026-10-22-step-evidence-contract.md.
- [x] Write the throughput checkpoint as four todo items.
  - Blocking first steps. Baseline commit and schema/evidence contract before code.
  - Independent workstreams. Two isolated design outputs; coupled product implementation has one owner.
  - Shared mutable state. Product writer gets an exclusive git worktree; root does not write or run suites there while owned. User data stays outside that worktree.
  - Smallest safe decomposition. One implementation owner for domain/schema/workflow/prompt/UI so source facts and step contracts cannot drift across concurrent writers. Independent verifier follows.
- [x] Delegate code-writing to a subagent using your configured feature model.
  - skip: session capacity rejected new agents. Root implemented in an exclusive worktree; finished non-author reviewers reused through native follow-up with current briefs and exact revisions.
- [x] Verify on the matching surface.
  - 61 Python/API tests, JS syntax and both DOM suites passed. Local Gemma synthetic example completed before final review fixes. Stored transcript evaluation returned review without changing source. No browser is connected, so visual/mobile testing is not verified.
- [x] Rebase into small, ordered commits. Stack follow-ups.
  - Use additive commits; no rebase needed unless topology requires it. Preserve existing user history.
- [x] If the design is contested, `interrogate` before shipping.
  - skip: independent design cross-judge agreed on the chosen contract. Correctness review found three implementation gaps; all reproduced with failing regressions and fixed in 4e595a3.
- [x] Run **Opening a PR**.
  - skip: user authorized local commits and local main merge, not remote push or PR creation.
- [x] Independent verification of exact head before local main merge.
  - Non-author reviewer returned PASS + NOTES on 4e595a3. All 61 Python/API tests, JS syntax and both DOM suites passed; three correctness findings resolved. Browser/mobile appearance remains untested.
- [x] Fast-forward local main and confirm ancestry, status, and tests.
  - main fast-forwarded from 848613e to verified code 4e595a3. Backup ref backup/main-before-step-quality-20261022 preserves the prior main. Main Python tests passed; no remote push or PR.

## Design arena

- [x] Frame
  - Outputs: two independently reasoned designs in .runtime/step-quality-design-a.md and .runtime/step-quality-design-b.md.
  - Rubric: faithful fact/step preservation, deterministic review routing and honest limits, backwards compatibility and no user DB writes, small public API, regression-testability.
  - Two seats fit the current task; model-diverse design comparison.
- [x] Fan out
  - Agent capacity allowed one design explorer; second spawn rejected. No further new spawns. Candidate B is a labelled sequential root pass. Required independent review will reuse a finished non-author reviewer through followup_task with the complete brief and exact head.
- [x] Cross-judge
- [x] Pick
- [x] Graft
- [x] Verify
  - Source-grounded design comparison completed. Runtime proof remains an implementation gate.

## Scope

- Approved spec: docs/superpowers/specs/2026-10-22-step-evidence-quality-design.md.
- Preserve string steps and add typed step_details. Local-only source facts and grounded omission/conflict checks. No description/vision collection in this change.
- No .env or credentials reads. No package install, user DB mutation, deletion, force push, PR or remote push. Test-owned isolated scratch only.
- Local main merge includes existing feature-branch history because main is an ancestor. Preserve a named pre-merge branch for recovery.
