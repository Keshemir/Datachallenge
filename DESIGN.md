# Interface design

## Direction
Operate mode: a quiet Freedom-branded quality-review workspace. The central object is a conversation and its criterion-level evidence. List/detail architecture, not a promotional landing page or infrastructure dashboard.

## Sources
- Official reference: https://fbroker.kz/ (inspected 2026-11-07).
- Local logo: frontend/public/brand/freedom.svg from https://fbroker.kz/images/Logo.svg.
- Local font: frontend/public/brand/cofo-sans.woff2 from the official site's CoFo Sans webfont asset.
- A separate public broker brandbook was not verified. Do not claim formal brandbook compliance.

## Tokens
- Brand green: #00b323, taken from the official site's CSS.
- Accessible primary action: #008529; hover #006e22.
- Ink #252b29; muted #69736f; canvas #f6f7f8; borders #e7ebe8; selected surface #eaf7ed.
- Font: CoFo Sans, 100–900 variable; Segoe UI/sans-serif fallback.
- Heading 32px desktop / 28px mobile; section 18px; body 14px; metadata 12px.
- Main spacing: 8 / 12 / 16 / 24 / 36px. Buttons 8px radius; panels 12px; dialog 16px.

## Composition
Desktop: 228px fixed white sidebar, 76px header, neutral canvas, a single conversation table. Search and language/channel filters are above the list. In a dialogue, original messages and assessment sit side by side. Scores, answers, and flags are distinct. Explanations expand in place; evidence buttons scroll to and highlight the source message.
Mobile: sidebar becomes compact top navigation. Filters stack; secondary table columns condense into per-row status. Conversation and evaluation stack. No document-level horizontal overflow; keyboard focus remains visible. Native dialog provides protected focus for file upload; native audio controls preserve familiar playback.

## Interaction principles
No model names, usage counts, prices, technical hashes, or raw API links in normal screens. Keep original record IDs for navigation. Show real data only. Preserve old assessments in history. Use separate error/empty/loading states. Disable mutations while running; never re-run inference merely to view a result. Respect reduced motion.

## Verification
1440px and 390px screenshots stored in ignored tmp/design/. Search, filters, pagination, import validation, dialog dismissal, criterion evidence navigation, review tab, audio roles, export, and checklist are tested against the local app. Browser tests do not issue additional paid inference.

## Final review

Independent UX review: ship; skip navigation, full-conversation search, identified contrast pairs, and readable recording names verified after corrections. Final checks: 71 backend tests, TypeScript/Vite build, and live browser flows at 1440px and 390px. No paid inference in browser checks.
