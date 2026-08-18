---
name: rag-outline-to-novel
description: "RAG-guided novel writing, continuation, and rewriting: retrieve and reconcile novel-rag canon, history, outlines, character/world state, style audits, and feedback, then produce audited prose and write back confirmed changes. Use for writing from an outline, continuing from a story break, rewriting existing chapters or scenes, or any novel-rag retrieval and post-generation writeback task."
---

# RAG Outline to Novel

Use this skill when a request asks to write, continue, expand, or rewrite fiction that must remain consistent with a `novel-rag` library. Keep the prose as the user-facing output; keep retrieval, planning, and audits internal unless the user asks to see them.

## Core workflow

Follow this sequence for every generation task:

1. Identify the `story_id`, `timeline_id`, volume/chapter/scene position, output mode, and the requested operation (write, continue, or rewrite). Stop and ask only when an unknown would change the core outcome.
2. Retrieve the minimum necessary context in this order: registry, current outline, current character/world state, adjacent history, relevant canon, active rules, active style audits, then feedback and approved samples. Keep alternate stories and timelines isolated.
3. Resolve authority before writing. Apply the user's current explicit instruction first; then mandatory task/scene rules, world/story rules, active canon and history, current state, outline, and finally advisory style guidance. Treat future outline events as plans, not facts.
4. Produce an internal execution contract (what must happen, must be preserved, must not happen, forbidden reveals, continuity limits, allowed invention, and blocking unknowns). Do not expose or persist it as canon.
5. Run a pre-generation judgment: identify the chapter or scene core, order and weight nodes, emotional/information curve, transitions, and a length budget. Allocate detail by narrative importance instead of expanding every outline item equally.
6. Generate a structurally complete draft, then render the prose in the active voice. Preserve causality, character knowledge, injuries, locations, resources, relationships, and stated outcomes. Do not paste retrieved passages together or turn outline bullets into summary prose.
7. Audit before delivery. Check execution-contract compliance, outline events and order, canon and continuity, character behavior, information release, pacing, and style. Fix facts and structure before sentence polish; rerun judgment only if the core scene, node weights, outline structure, or ruling changed.
8. After the user confirms the final prose, write back only changes evidenced by that prose. Update history, character/world current state and change logs, and feedback as applicable. Promote a rule or style change only after explicit confirmation; never update current state from an outline, plan, draft, or agent inference.

## Retrieval and writeback guardrails

- Require both story and timeline identity on every retrieval and writeback.
- Prefer active/canon versions; exclude deprecated, archived, draft, runtime, and alternate material unless the task explicitly requests comparison.
- Keep `canon` for confirmed facts, `history` for what has happened, `outline` for future requirements, `character-state` and `world-state` for the current post-history state, and `feedback` for user corrections.
- Treat a character's dialogue, a rumor, a mistaken belief, and an image as perspective-bound evidence rather than automatic canon.
- If retrieval fails, retry with canonical names, aliases, story/timeline identifiers, chapter context, and recent appearances. Preserve the core direction; do not invent identity, victory, relationship, ability, or world-rule facts.
- Do not reveal internal workflow artifacts or claim that un-retrieved material exists.

## Canonical document templates

Use the shared templates as the only maintained document shapes. Read the file, fill its required metadata and type-specific values, then validate the resulting document with `novel_rag.documents.load_document` and `validate_document` before writing it. Never copy an older template from this skill or its references.

| Document | Canonical source |
| --- | --- |
| outline | `novel-rag/shared/templates/chapter-outline.yaml` |
| current character state | `novel-rag/shared/templates/character-current.yaml` |
| current world state | `novel-rag/shared/templates/world-current.yaml` |
| style audit | `novel-rag/shared/templates/style-audit.yaml` |
| feedback | `novel-rag/shared/templates/feedback.yaml` |

For character state, provide both `metadata.character_id` and `metadata.variant_id` in addition to the common required metadata. Keep the template's existing key names and types; do not add a parallel schema in prose or YAML.

## Reference navigation

- Read [workflow.md](references/workflow.md) for the detailed Ruler -> Judgment -> Generator -> Audit procedure, retrieval fallback, and continuity checks.
- Read [add_rag.md](references/add_rag.md) for library layout, module boundaries, indexing, and persistence rules.
- Read [update.md](references/update.md) for evidence-based character-state updates and post-chapter writeback.

The references preserve the project's detailed guidance. They are not sources for formal document templates; use the canonical files above whenever a document is created or updated.

## Completion checks

Before returning prose, confirm that the requested events and result are present, no forbidden reveal or unauthorized fact was introduced, every viewpoint character acts with current knowledge and capability, and the ending state can feed the next task. For writeback, validate each generated YAML document and require user confirmation for durable rule, canon, or style changes.
