# Product

## Platform
web

## Purpose
CQA evaluates customer-service chats and call transcripts against a versioned Freedom Broker checklist. The hackathon prioritizes reasoned, reproducible analysis of unseen conversations, alongside usability and process completeness. Official Ground Truth is not available locally.

## Workflow
Import a dialogue dataset or audio; inspect the conversation; automatically identify client/operator roles for newly transcribed audio; evaluate by checklist; inspect criterion explanations and linked original messages; independently recheck ambiguous results; export results.

## Confirmed constraints
React/TypeScript/Vite frontend, FastAPI/Python/SQLite backend. Russian interface; RU/KZ/EN conversations. STT is mandatory. User selected DeepSeek V4.1 Flash 1017 as the main evaluator. Stored prior evaluations remain immutable.

## Brand and language
User requested Freedom Broker branding and removal of technical interface noise: model names, tokens, cost, provider labels. Branding references the current official fbroker.kz website, not an unverified third-party brandbook. Never invent completion states, assessment statistics, confidence, or scores.

## Evaluation guidance
Organizer clarification supplied by user on 2026-11-07: prioritize sensible explanations, closeness to expert judgment, reproducibility, and complete workflows; exact point-by-point matching is not the sole objective. Handle missing data without inventing facts. Account for spoken language and imperfect STT. Unknown rubric-specific questions remain unresolved.

## Live demonstration requirements

Further organizer guidance supplied by the user on 2026-11-07: selection combines
expert agreement, internal repository checks, functionality, usability, and diversity
of local/cloud architectures. No public formula or factor weights are available.
Do not optimize for an invented selection formula or claim benchmark accuracy without labels.

The primary presentation must demonstrate a working product on new conversations.
The reviewers may operate the interface themselves. Required demonstration scenarios:

- Find conversations with critical errors and open the supporting explanations.
- Let an operator submit an evaluation appeal and inspect its processing status.
- Add or edit a checklist criterion and change its weight through the interface.
- Open a particular conversation's criterion scores, explanations, and evidence.

Implemented: evidence-linked evaluations, immutable checklist versions, a checklist
editor with criterion/weight/scale/N/A controls, and a dedicated filter for critical
flags in the latest AI evaluations. Criterion appeals support submission, review,
acceptance/rejection, server-persisted history, and separate cumulative QA result
snapshots. Original AI evaluations are preserved. Draft guards protect navigation;
appeal/QA drafts survive switching result tabs. Distinct authenticated user roles
are still not implemented: names are self-reported in the shared workspace.

## Corporate audience

Design for QA specialists, operators, team leads, and directors. Maintain the
restrained Freedom visual style, legible tables, clear actions, and accessible
statuses. Prioritize evidence, audit history, and complete workflows over decorative
dashboards, game elements, mascots, or unverified confidence percentages.

## Accuracy improvement priorities

Establish a manually reviewed RU/KZ/EN calibration set separated by scenario family
from a held-out set. Measure decisions per criterion, N/A errors, critical-error
precision/recall, score error, and repeat-run stability. Include incomplete calls,
bot-to-operator handoffs, code-switching, and STT corruption. Synthetic cases are
regression tests, not the organizers' Ground Truth.

The offline `cqa.benchmark` CLI now exports blank annotation templates and compares
reviewed labels with saved AI results, including criterion confusion, N/A and
critical-flag precision/recall, and total-score MAE. It rejects cross-split scenario
families and duplicate cases. Manual labels and measured accuracy remain pending.

Experiment with criterion-specific evidence extraction and explicit applicability
decisions before scoring. Preserve the configured N/A rules; uncertain evidence is
a review status, not automatically N/A or a violation. Retain the full conversation
when checking missing actions and critical errors. Compare every candidate prompt
or architecture to the existing DeepSeek baseline before promotion. Independent
verification already exists; model agreement alone is not proof of correctness.

## Submission and omnichannel clarification (2026-11-07)

The organizer results appendix defines JSON 1.0, with DEV containing 60 chats and 5 calls,
PROD containing 10 control chats, original conversation IDs, all eight official criteria,
one-based evidence indices across every original role, and explicit error records.
The Submission screen exports saved AI evaluations for an immutable imported dataset
manifest and selected compatible checklist. Missing results are disclosed; export performs
no inference or Git publishing. The team name is Bibigon; it is the default on the Submission screen.

Organizer clarification supplied by the user: consider an omnichannel system. Do not infer
completed identity verification from app login, chat presence, or a phone call. Explicit
conversation/system evidence remains valid; general inquiries may be N/A under the rubric.
This clarification is included in prompt cqa-judge-v3-omnichannel for subsequent evaluations;
historical evaluations are not rewritten.

## Automatic audio participants (2026-11-07)

User requested removal of manual speaker-role selection for audio. Upload now chains STT
with semantic client/operator assignment by complete STT speaker identity. No manual
language or speaker-role fields in audio import/review; uncertain classification preserves
the transcript and allows retry without repeating STT. Existing saved derivations are reused.
The complete DEV dataset has now been reevaluated with DeepSeek and prompt v3 omnichannel:
65 successful original conversations, 0 processing errors in the refreshed submission JSON.

## One-step pasted-text evaluation (2026-11-07)

User explicitly rejected the intermediate participant/turn editor. Pasted text now has
one Evaluate action: background role/language inference, source-preserving import, and
checklist evaluation followed by the standard dialogue/detail screen. Name is optional.
No role dropdowns, timestamps, merge/delete controls or confirmation step in this flow.
Failed scoring keeps the saved conversation and retries scoring without repeating parsing;
completed scoring is retained if refreshing/opening the result fails. Ambiguous unparseable
source produces a plain error instead of fabricated participant assignments.
