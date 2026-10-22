# poteto-mode structure investigation

- [x] Route through the **how** skill. For motivation questions, also route through the **why** skill.
  - skip: why, user requests current structure, not historical motivation.
- [x] Throughput checkpoint stays one line: `throughput checkpoint: n/a, read-only investigation`.
- [x] Produce the `how`-shaped output (Overview / Key Concepts / How It Works / Where Things Live / Gotchas), or a recommendation with a tradeoffs table if the request is a decision between alternatives.
- [x] Apply the **unslop** skill to the reply.

throughput checkpoint: n/a, read-only investigation

## Swarm

- [x] Frame
  - Goal: explain actual current structure with file references and distinguish implemented functionality from design-only improvements.
  - Shape: partition into UI/API and workflow/storage/model source slices. No product writes, database access, server runs, installs or git mutations.
- [x] Fan out
- [x] Aggregate
  - Both source explorers returned PASS for assigned inspection coverage, not runtime correctness. No dropouts. Their findings agree that prompt policy exceeds executable quality checks and source/vision work remains design-only.
- [x] Report
  - Consolidated explanation prepared with file-role map, collection/search flow, storage ownership, and limitations. Boundary Discipline separates input/schema checks from semantic truth. Minimize Reader Load organizes the explanation around the two user workflows.

## How

- [x] Assess complexity
  - Cross-file architecture. Two explorers and one synthesis agent, read-only.
- [x] Explore (complex only)
- [x] Synthesize (complex only)
- [x] Present
