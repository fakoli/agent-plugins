# Review prompts

Use these as questions, not mandatory boilerplate headings. Omit a section
when its omission is honest and useful. Do not invent answers to fill a template.

## Product and experience

What could the user do before? What changes now? Which actual route, command
or input/output demonstrates that difference? Who carries the new complexity?
Where does the user learn that a model or external provider was involved?
Can they decline, undo, disable or continue after failure? What is still only a
journey hypothesis rather than user research?

## Design and decisions

What are the system boundary and data flows? Which component owns state,
permission, execution and acceptance? What alternatives would have avoided this
dependency? Which tradeoff is implemented, and which rationale is reconstructed?
Use context/runtime diagrams and focused decision records rather than every
possible architecture view. Include an accessible text equivalent for diagrams.

## Evidence and review

What observation supports each claim? Was the test mocked, live synthetic,
production or merely planned? Does the input match the reported revision? What
failed before the final run? What remains blocked? What did independent review
actually establish? If no independent review happened, say so. Do not create
fictional organizational approval or claim that a checklist ran itself.

## Narrative handoff

Identify one grounded tension, a working flow, the evidence that changed the
understanding, a difficult tradeoff and a limitation. Keep first-person memories
for the author to supply. A title direction and scene outline are enough until
the user requests a draft. Future ideas need a benefit hypothesis, smallest
experiment and authority boundary, not just an impressive name.

## Method provenance

- Brag 0.2.2, inspection/planning prompts: specific angle, actual working flow,
  visual identity, concise narrative. Conceptually adapted; no bundled Brag code.
- [C4 diagrams](https://c4model.com/diagrams): choose useful architecture zoom levels.
- [arc42 overview](https://arc42.org/overview/): constraints, runtime, decisions and risks.
- [ADR guidance](https://adr.github.io/): one consequential choice and its tradeoffs.
- [NN/g journey mapping](https://www.nngroup.com/articles/journey-mapping-101/): actor, scenario, phases and opportunities.

These sources inform the review questions. They are not mandatory standards
or copied templates. User scope and the destination's rules take precedence.
