# Cash and Vessel Domain Delivery Plan — Corrected Review

**Status:** Source assessment, implementation record, and proposed release plan. Repository changes are not production authorization.  
**Scope assumption:** Cash/Vessel processing is Bridge1 / WA-01 only while WA-01 remains connected. WA-02 is paused for these domains during that period. Do not read, import, query, replay, alter, or delete WA-02 Cash/Vessel data. Loss of WA-01 connectivity does not authorize automatic WA-02 failover; that requires a separate Owner decision.  
**Business source:** New, authorized WhatsApp conversations only; do not import historical spreadsheets, archives, or external domain data as part of this plan.

## Superseding development status — 2026-10-25

The Owner's scoped Cash development-unfreeze authorization supersedes the
source-code freeze gates below for the approved WhatsApp/Mirror/Cash/Vessel
integration work. It does not authorize production migration, deployment,
restart, Live Sync activation, historical backfill, WA-02 permission expansion,
or financial writes. The WA-01-only processing boundary and existing financial
security, identity, review, and approval controls remain in force. The phase
plan below is historical/proposed evidence, not a current blocker to the
authorized source work or production approval.

## Decision

The supplied delivery plan is **not implementable as written for the requested workflow**. It is a useful safety/reliability outline, but it omits the required source allowlists and business-level duplicate rule, assumes groups can produce Vessel records when the current code rejects them, and describes replay safety that only covers the same source message. The shared live ingestion worker also polls both accounts, so the requested Bridge1-only boundary is not currently guaranteed by the worker.

The existing plan and relevant application/bridge source were inspected statically. No live database contents were queried, no Bridge2 data was accessed or imported, no WhatsApp action was taken, no app or bridge was restarted, and no protected code was changed. The source submodules already contain extensive uncommitted changes; treat those as pre-existing and preserve them.

## Owner clarifications incorporated

### A. WA-02 history and domain separation

- The reported 2,905 already-ingested WA-02 rows and any already Cash-processed results are part of the existing baseline. Leave them untouched: no cleanup, backfill, reprocessing, replay, or verification query is included here.
- While WA-01 is connected, WA-02 must remain inactive for Cash and Vessel/Escort processing. This is a proposed future operating rule, not authorization to change the live worker, cursors, or runtime configuration.
- Do not infer that WA-02 should automatically take over after a WA-01 disconnect. Fail closed and obtain an explicit Owner decision before any fallback or recovery action.
- Keep the Cash payment path distinct from Vessel/Escort request and duty/release workflows. Staff/client requests, ordinary conversation, and images are not payments merely because they mention money.
- Proposed Cash transaction-candidate gate: only an outbound message from the authorized Admin identity on WA-01, addressed to the authorized Accountant destination, and matching the agreed structured payment-message shape may be considered for transaction parsing. A message must carry the applicable payment details (such as amount, recipient identity/number when present, and intended cash use); ordinary sentences, unrelated messages, and images do not pass this gate. Passing the gate is not approval to post, settle, or otherwise perform a financial action.
- Proposed Escort workflow: authorized client requests are transformed into a structured draft using the existing app-defined template/fields; the authorized Admin/Pin role may complete the Escort identity and contact details, then return the prepared message to the originating client. Duty, release, and related payment conversations remain separate business events; conversations may be evidence for a later review, not authority to infer or execute a payment. Template fields and routing must be verified from source before any implementation.
- These business boundaries remain applicable. The 2026-10-25 Owner instruction authorizes the scoped source-code, test, and development-policy changes needed for integration; it does not authorize the production actions listed in the superseding status above.

### B. Verification without production-data access

- Do not query or reveal any existing production database records. Preserve existing records and use no production business data as test input.
- End-to-end validation, if separately authorized, must use an isolated non-production environment and only messages/data the Owner intentionally creates for that test. The test may exercise parsing, processing, templates, bots, ingestion, and persistence against an isolated test database; it must not connect to or write to the live database.
- Report only test outcomes and bounded synthetic-record counts/IDs as needed; do not expose unrelated database contents. No real WhatsApp send, production ingestion, or live-data inspection is authorized by this plan.

### C. Compatibility cursor errors

- Track the three WA-01 compatibility cursor errors as a separate, sequential workstream, not as permission to change Cash/Vessel behavior.
- Audit and remediate at most one cursor error at a time, after authorization for the exact affected paths. Once that item is complete, audit the next issue and provide its own scope, risk, and execution plan before starting it.
- Defer the other two until separately prioritized. Do not change cursors, replay messages, or perform any production recovery as part of this documentation update.

## Evidence and required corrections

| Finding | Evidence in current source | Consequence for requested workflow |
|---|---|---|
| The ingestion worker processes a shared chat list for both accounts. | [message-ingestion-worker.ts](apps/al-rifai/scripts/message-ingestion-worker.ts#L19) defines the chat list; the worker iterates it for both accounts and calls WA-02 at [line 381](apps/al-rifai/scripts/message-ingestion-worker.ts#L381). | A plan that merely says “in-scope chats” does not enforce “Bridge1 only.” Do not run/replay this worker as part of this task. A future authorized change must demonstrate account and per-domain source isolation before deployment. |
| Cash is already constrained to one approved counterparty/chat, with two address representations for that same contact. | [cash-scope.ts](apps/al-rifai/lib/cash-scope.ts#L1) and [process-cash.ts](apps/al-rifai/scripts/process-cash.ts#L27). The Cash processor keeps candidates in `REVIEW` with `financialAction: "NONE"`. | Preserve that scope and behavior exactly. Do not treat the two address forms as two people or widen Cash to Vessel group chats. |
| Three Vessel contacts are seeded, but group messages are not accepted as contact-authorized input. | [0018_escort_order_register.sql](apps/al-rifai/db/migrations/0018_escort_order_register.sql#L68) seeds the contacts. [escort-register.mjs](apps/al-rifai/lib/escort-register.mjs#L32) rejects group chats in `contactFor`; the corresponding test explicitly expects no group operations at [escort-register.mjs test](apps/al-rifai/tests/escort-register.mjs#L47). | The requirement for three Vessel group chats is not met. Adding groups safely requires explicit group allowlisting and participant-to-contact authorization, not merely ingesting group history. |
| Current replay dedupe is source-message/block idempotency only. | The Vessel code computes a source hash at [escort-register.mjs](apps/al-rifai/lib/escort-register.mjs#L37), tracks it at [line 83](apps/al-rifai/lib/escort-register.mjs#L83), and the database uniqueness is `(account_id, source_hash, block_key)` at [0018_escort_order_register.sql](apps/al-rifai/db/migrations/0018_escort_order_register.sql#L46). | A distinct message from another contact/group has a different source identity and can create a second row for the same business order. The requested cross-message duplicate rule is absent. |
| Existing assignment matching is narrower than the requested duplicate relationship. | [escort-register.mjs](apps/al-rifai/lib/escort-register.mjs#L99) requires the same contact and chat and does not define a cross-contact business key. | Cross-contact duplicates will not be identified consistently. Keep source-message replay idempotency, but add a separate business-order identity and source-link model under explicit authorization. |
| The current Vessel shape separates a draft from an assignment review. | `validDraftFields` requires no escort/date; assignment candidates become `REVIEW`, not a confirmed order, in [escort-register.mjs](apps/al-rifai/lib/escort-register.mjs#L21) and [process-vessel.ts](apps/al-rifai/scripts/process-vessel.ts#L180). | A complete duplicate tuple cannot be assumed to exist on every first message. Define when the tuple is complete and keep incomplete/conflicting records in review. |
| The existing plan includes account-wide production metrics and Bridge2 status in its “verified starting point.” | [CASH-VESSEL-DOMAIN-DELIVERY-PLAN.md](apps/al-rifai/docs/CASH-VESSEL-DOMAIN-DELIVERY-PLAN.md#L29). | Those details are outside this requested review boundary and were not revalidated. Remove Bridge2-derived evidence from the execution plan and do not use aggregate counts as proof of the requested contact/group coverage. |

## Corrected execution plan

### Historical Phase 0 — Freeze and scope gate

1. Treat this review as source-only. Do not query live business data, open message bodies, inspect credentials, access Bridge2, replay history, change cursors, or contact WhatsApp.
2. This historical freeze gate was superseded by the Owner's 2026-10-25 scoped source-development authorization. That authorization covers the approved integration source and isolated tests only; it does not authorize production migration, deployment, restart, Live Sync, historical replay, WA-02 permission expansion, or financial writes.
3. Confirm the final source allowlist without reading production message content:
   - Cash payment candidates: authorized Admin sender to authorized Accountant destination, on WA-01, with the agreed structured payment-message shape. Ordinary text/conversation and images are not payment candidates.
   - Vessel/Escort requests: exactly the approved direct-contact conversations and explicitly authorized groups/participants, on WA-01 only. Follow the app's source template and identity rules; do not treat requests or duty/release discussions as payment instructions.
4. Record the sender identity policy for each Vessel group: group JID plus stable participant identity mapped to one of the three authorized contacts. Display names and unverified phone guesses are not authority.
5. Leave the reported 2,905 WA-02 rows and any WA-02 Cash-processed data untouched. Do not inspect them. Treat WA-02 as paused for Cash/Vessel while WA-01 is connected; any failover after loss of WA-01 requires a separate explicit Owner decision.
6. Stop if the shared worker cannot enforce WA-01-only/domain-specific ingestion for this task without touching a protected path. Do not disable or alter the running baseline as a workaround.

**Exit:** exact source scope and permissions are approved; there is no Bridge2 data access and no production database query; any protected edits have a qualifying Owner exception; no production read/replay/write is proposed.

### Phase 1 — Define the Vessel business identity

Keep two identities distinct:

1. **Source identity:** account, chat, message ID/revision, and parsed block. This continues to make retries of the same message idempotent.
2. **Business duplicate identity:** normalized mother vessel + normalized lighter vessel + verified escort identity + start/duty date, scoped to the same approved business domain/account.

Rules:

- Normalize for comparison, but retain the original text and source provenance. Use verified escort mobile/identity where available; do not merge on a display name alone.
- Interpret “same start date” as the date field the Owner designates as the program start/duty date, in the agreed business timezone. Do not infer a date from unrelated message timestamps.
- If any tuple element is missing, conflicting, or not reliably identified, do not auto-merge; place it in review.
- Treat a matching tuple from different authorized contacts or groups as the same business duplicate candidate. Keep every original source message and link it to the canonical order/duplicate decision; never delete or overwrite source evidence.
- Do not use fuzzy vessel-name matching as an automatic duplicate key. Fuzzy/alias matches may suggest a review candidate only.
- Preserve the user's date-only duplicate rule. Because different shifts on one date could otherwise collide, present such a match for review unless the Owner explicitly confirms it should be merged.

**Exit:** written examples and synthetic fixtures establish exact-match, missing-field, conflicting-field, same-date/different-shift, alias, and near-match outcomes before schema or behavior changes.

### Phase 2 — Design authorized group intake and duplicate persistence

1. Define an explicit Vessel source policy separate from Cash. Only the approved three direct chats and three group chats can produce Vessel review records.
2. In groups, require both an allowlisted group and an authorized sender participant. Unknown, hidden, or unresolved participant identity stays out of the Vessel business register and is surfaced as an actionable review/exclusion outcome.
3. Preserve the existing source-message idempotency key. Add a distinct business key only for a complete, verified tuple.
4. Persist source-to-business-order links and duplicate decisions transactionally. A unique business key may prevent a second canonical order, but must not silently discard the later source message or its evidence.
5. Keep ambiguous assignment/order matches in `REVIEW`. No automatic confirmation, operational assignment, or financial action is permitted.
6. Review required schema, source-consumer, app/API, tests, and release paths before editing. These may be Cash-protected or shared paths; if so, stop until the exact Owner exception is approved.

**Exit:** design demonstrates that two different authorized contacts/groups with the same complete tuple yield one canonical business order and retain both source links, while distinct tuples remain distinct.

### Phase 3 — Isolated synthetic end-to-end verification

Do not execute tests against production or use production messages. Use an authorized, isolated Node.js 22 environment, test-only WhatsApp endpoints/devices if needed, and Owner-created synthetic messages only. The persistence target must be an isolated test database, never the live database. If that environment is unavailable, record tests as not run; do not fall back to the production app container.

Required tests:

- An authorized Admin outbound to the Accountant on WA-01 is considered a Cash transaction candidate only when its structure satisfies the approved template; ordinary conversation and images are not parsed or posted as payments.
- Escort request messages follow the app-defined template and route to a draft for the authorized Admin/Pin workflow; unrelated senders, unapproved chats, and unresolved identities are excluded or held for review.
- Synthetic test runs may verify the end-to-end pipeline through isolated persistence without exposing or querying existing production data.
- Same source message replay creates no duplicate source/domain operation.
- Same complete business tuple from two different authorized contacts creates one canonical order and two provenance links.
- Same tuple from a permitted group is accepted only when the participant identity is authorized.
- An unapproved group, unknown participant, other account, or WA-02 source creates no in-scope Vessel order.
- A changed mother vessel, lighter vessel, escort identity, or start date does not silently merge.
- Missing or conflicting tuple fields produce review, not an inferred duplicate or canonical order.
- Same date but different shift is held for review under the date-only rule.
- Concurrent duplicate processing, transaction failure, and retry preserve one canonical order and all source evidence.
- Cash scope remains the single approved contact; Cash output remains review-only and `financialAction: "NONE"`.
- Review APIs expose source provenance while business writes remain disabled.

**Exit:** focused tests pass; typecheck/lint pass for authorized changed files; test logs contain no real message bodies or secrets.

### Phase 4 — Cursor compatibility workstream (sequential; separate authorization)

1. Select only the first of the three WA-01 compatibility cursor errors for investigation; do not alter or advance production cursors during diagnosis.
2. Audit the error and its exact code/configuration/test scope, then obtain Owner authorization for the affected protected paths before any fix.
3. Validate that single fix in an isolated environment. After completion, audit the next cursor issue and present a separate plan; defer the remaining two until their turn.
4. Do not combine cursor remediation with Cash/Vessel rollout, replay, or deployment. Each production action requires its own explicit authorization.

**Exit:** one authorized cursor issue is fixed and validated in isolation; the next issue has a separately reviewed plan; the two deferred issues remain untouched.

### Phase 5 — Controlled release gate

1. Review the exact diff and verify it touches only Owner-authorized paths.
2. Prove WA-01-only/domain-specific routing from code and isolated tests before deployment. Do not access Bridge2 or query the live database to prove this.
3. Obtain separate deployment approval identifying the app service, restart scope, observation window, and rollback procedure. Do not restart either WhatsApp bridge for an app change.
4. Any production observation must be separately authorized, read-only, bounded, and limited to WA-01; no history replay, production database query, or business-data write.

**Exit:** explicit source/domain isolation is verified, Vessel duplicates are represented once with all source links, Cash remains unchanged unless a separate exact-path Owner exception is approved, and release approval is separately recorded.

## Assessment limits

- This assessment inspected application, schema/migration, bridge source contracts, scripts, and tests. It did not inspect live database contents or Bridge2 data, and it did not import any Cash/Vessel information. The reported WA-02 row count and processed records remain unverified here and untouched.
- Tests were inspected but not run: the host lacks the project Node.js runtime, and the production app container is not an authorized test environment here.
- Repository and service submodules were already dirty, including uncommitted app, migration, test, and bridge files. Findings describe the present working-tree source, not a verified deployed build.
- The existing plan's reported runtime counts/cursor state and the actual behavior of the deployed image remain unverified by this review.

## Implementation status — 2026-10-21

The following repository changes were made after the source-only assessment;
they are not deployed and migration
`apps/al-rifai/db/migrations/0023_vessel_business_duplicate_identity.sql`
has not been applied:

- Cash and Vessel processors now select only WA-01 rows. The worker's
  historical backfill creates new Cash/Vessel queue entries only for WA-01;
  the generic archive-page writer may still leave WA-02 processing markers,
  which these processors do not select. The shared worker skips the WA-02
  versions of the configured Cash/Escort direct-chat JIDs and the candidate
  Escort/Release group JIDs, while leaving the unrelated
  Office group available for general ingestion. Existing WA-02 queue rows are
  left untouched and are not selected by these processors.
- Vessel register derivation rejects WA-02 input. A group message is eligible
  only when an active authorization exactly maps its WA-01 group JID and
  incoming participant JID to an active existing contact. No group authorization
  was seeded: the repository's group candidates remain unverified.
- Complete Vessel business tuples use a deterministic, account-scoped identity.
  Same-tuple, same-shift source messages converge on one review row and retain
  per-source provenance/events. Missing identity fields do not receive a
  business key; same-date, different-shift matches remain separate review rows.
- The read-only Escort API remains unchanged in its write boundary; the UI now
  displays each available source event for a canonical row.

Cash parsing, identity rules, review-only output, and financial write behavior
were not changed. No live records were read or written, no WhatsApp message was
sent, and no migration, deployment, or restart was performed. Focused tests
were not run because an authorized isolated Node.js 22 test environment was
unavailable; production was not used as a test environment.

## Implementation checkpoint and next-session handoff — 2026-10-21

This checkpoint supersedes the preceding implementation-status statements
where they conflict with the later test report. It records that report; the
checks below were not rerun while saving this documentation update.

### Current stage

Implementation and verification; not ready for production release.

### Completed and verified

The preceding implementation report recorded these successful results:

- 29 focused tests passed.
- Workflow and Phase 1 unit tests passed.
- TypeScript typecheck passed.
- Focused ESLint passed.
- Next.js build passed.
- Go formatting, `go vet`, and Go tests passed.
- `git diff --check` passed.

These are reported passes, not commands rerun for this checkpoint. The
migration-chain check described below did **not** pass and must not be
represented as validated by an adjusted test.

### Critical unresolved defects

**A. WA-02 ingestion isolation**

A synthetic test found that `ingestCompatibilityPage` creates pending Cash
and Vessel processing markers for a WA-02 message. Downstream processor
filters are insufficient: they prevent selection but do not prevent marker
creation. Trace the complete ingestion path and put the minimum correct
source/account guard at the boundary that creates domain markers. Do not
clean up, inspect, replay, or reprocess existing WA-02 data.

Relevant implementation and regression-test paths:
`apps/al-rifai/lib/whatsapp-archive.ts`,
`apps/al-rifai/scripts/message-ingestion-worker.ts`, and
`apps/al-rifai/tests/whatsapp-archive-ingestion.mjs`.

**B. Vessel duplicate inconsistency**

`apps/al-rifai/scripts/process-vessel.ts` and
`apps/al-rifai/scripts/reconcile-ingest.mjs` do not consistently handle
same-date, different-shift records. Review the shared helper,
batch behavior, canonical ID/business-key assignment, and provenance links.
Both paths must produce consistent outcomes; uncertain or incomplete records
must remain reviewable rather than being silently merged or discarded.

Relevant paths include `apps/al-rifai/lib/escort-register.mjs` and
`apps/al-rifai/tests/escort-register.mjs`. Confirm any additional affected
regression-test or schema paths from the preserved diff before editing.

**C. Migration-chain failure**

The fresh migration sequence fails at
`apps/al-rifai/db/migrations/0016_cash_payment_account_name.sql` when it
attempts to add `cash_instructions_cash_account_check` to
`public.cash_instructions`; the reported PostgreSQL failure is that this
constraint already exists, having been created earlier in the chain. A
test-only workaround was previously attempted, but its exact harness command
or alteration was not captured in the available report or repository
documentation. Treat that workaround as test-only and non-evidence: do not
report the adjusted test as a successful validation of the unmodified chain.
Recover the exact workaround from the original test/run record if available,
then validate the complete, unmodified migration sequence in an isolated
environment. Resolve the collision without weakening Cash business rules.

The exact earlier migration that creates the conflicting constraint remains
to be identified during the ordered follow-up; do not guess or alter it now.

### Other outstanding verification

- Full-project lint runner did not complete because of `ENOBUFS`; focused lint
  passed.
- The `source-register.mjs` test was not run because it depends on production
  evidence rather than an isolated fixture.
- WhatsApp MCP Python tests remain unverified.
- Runtime and production behavior remain unverified.
- No production migration or deployment was performed.

### Group authorization

No verified group/participant authorization mapping was found. Keep group
intake pending for those sources. Do not invent JIDs or identities. This
authorization gap does not block independent implementation work.

### Cash boundary and required authorization

This handoff is not an Owner exception. Do not edit Cash-protected code,
tests, migrations, dependencies, configuration, or release paths without a
new, explicit, path-specific Owner exception. The known Cash-sensitive paths
for this checkpoint include:

- `apps/al-rifai/lib/whatsapp-archive.ts` and
  `apps/al-rifai/scripts/message-ingestion-worker.ts` (shared ingestion that
  creates Cash markers);
- `apps/al-rifai/tests/whatsapp-archive-ingestion.mjs` and
  `apps/al-rifai/tests/cash-intake-safety.mjs` (Cash-related test coverage);
- `apps/al-rifai/db/migrations/0016_cash_payment_account_name.sql`, and any
  exact earlier migration path shown to create the conflicting constraint.

The migration directory is protected as a whole. Before any protected edit,
the Owner exception must specify exact paths, intended behavior, validation
plan, deployment/restart scope, and financial write boundary. No such
authorization is granted here. Vessel-only implementation may proceed
independently where it does not modify Cash-protected behavior or paths.

Do not deploy, restart production, apply production migrations, replay live
history, send WhatsApp messages, or perform live financial postings.

### Ordered next steps

1. Inspect the current diff and preserve all pre-existing changes.
2. Fix WA-02 marker creation at the correct ingestion boundary, subject to
   the required path-specific Owner exception for protected paths.
3. Make duplicate handling consistent across both Vessel processing paths.
4. Resolve the migration-chain constraint collision without weakening Cash
   business rules, after obtaining the required exact-path Owner exception.
5. Add regression tests for all three defects, subject to the same Cash
   authorization boundary.
6. Re-run relevant tests, typecheck, lint, build, and migration validation in
   isolated environments.
7. Update this handoff with actual results and any remaining evidence gaps.

## Continuation update — 2026-10-21, 23:30 CEST

### Current stage

Implementation and verification; not ready for production release. The
independent Vessel batch-consistency fix is implemented but its tests could
not be executed in the available environment. WA-02 ingestion and migration
repairs remain blocked on the Cash Freeze authorization gate.

### Changes made in this continuation

- `apps/al-rifai/scripts/process-vessel.ts`: keep the WA-01 register match
  state for the whole processing batch and add every persisted DRAFT or REVIEW
  operation to it. Previously the state was recreated for every message and
  only DRAFTs were retained, so same-batch assignment reviews could not
  participate in matching.
- `apps/al-rifai/lib/escort-register.mjs`: deduplicate same-business-tuple
  candidates by canonical order ID before comparing shifts. Multiple source
  events for one canonical order therefore do not produce repeated
  `differentShiftOrderIds`.
- `apps/al-rifai/tests/escort-register.mjs`: add regression coverage for an
  exact source duplicate and replay, same-date/same-shift canonical reuse,
  same-date/different-shift review, repeated reconciliation, preserving an
  existing canonical ID while ignoring an unrelated account record, and
  keeping review operations in process-batch match state. These tests are
  added but not executed.

`reconcile-ingest.mjs` already passes the complete WA-01 message batch to the
shared derivation helper; its existing working-tree diff was inspected and
preserved, not changed by this continuation.

### WA-02 isolation — still blocked

No WA-02 source or test code was changed. The exact marker-creation boundary
is `apps/al-rifai/lib/whatsapp-archive.ts`, in
`ingestCompatibilityPage`: after resolving the original message ID, its
processing-row insert unconditionally adds `cash` and `vessel` pending rows
(current source around line 473), including for `input.accountId === 'wa-02'`.
This is why processor-side filters do not prevent marker creation. The
minimum correction is to keep the immutable archive processing row while
creating Cash/Vessel rows only for the authorized WA-01 account. The related
regression test belongs in
`apps/al-rifai/tests/whatsapp-archive-ingestion.mjs`. Both are Cash-protected
paths; obtain an explicit Owner exception for those exact paths before
editing. The shared consumer path
`apps/al-rifai/scripts/message-ingestion-worker.ts` is also protected and
must remain unchanged unless tracing proves it needs a separately authorized
edit. Do not inspect or alter existing WA-02 records. Unknown groups remain
pending review; no identities or group mappings are inferred.

### Migration chain — still blocked

Static inspection identifies the collision: migration
`apps/al-rifai/db/migrations/0012_business_workflows.sql` declares a
column-level `CHECK` on `cash_account`, which PostgreSQL names
`cash_instructions_cash_account_check`. Migration
`apps/al-rifai/db/migrations/0016_cash_payment_account_name.sql` tries to add
another constraint with that name. Migration 0015 drops the separate
table-level `cash_instructions_check`, not the column-level account check.
This is the reason the fresh sequence collides; no migration was edited.

The earlier test-only workaround could not be recovered from repository
history or available run records. Its adjustment is not evidence that the
unmodified chain passes. No fresh migration sequence was run because an
isolated database with verified absence of production credentials, routes,
and shared volumes could not be established (the container configuration
tool was unavailable). The exact paths needing a Cash Owner exception before
any migration correction are
`apps/al-rifai/db/migrations/0012_business_workflows.sql`,
`apps/al-rifai/db/migrations/0015_live_owner_accountant_cash.sql`, and
`apps/al-rifai/db/migrations/0016_cash_payment_account_name.sql`, plus any
exact migration-test path established for validation. Preserve all Cash
constraints and rules.

### Verification in this continuation

| Check | Result | Notes |
|---|---|---|
| Vessel regression tests (`tests/escort-register.mjs`) | NOT RUN | No host Node.js or pnpm; no configured isolated Node container was available. |
| WA-02 ingestion regression tests | NOT RUN | Protected test/source paths require Owner authorization; no code was changed there. |
| TypeScript typecheck, focused lint, and Next.js build | NOT RUN | Required project runtime/tooling is unavailable; prior checkpoint passes remain historical, not rerun results. |
| Fresh unmodified migration-chain validation | NOT RUN | Safe database isolation could not be proven; no migration was executed. |
| `git diff --check` | PASS | Tracked AL-RIFA’I working diff. An explicit whitespace scan also passed for edited source/test files and this checkpoint section. |
| Full-project lint runner | NOT RUN | The earlier reported `ENOBUFS` was not rerun. `scripts/lint.mjs` uses `spawnSync` with ESLint JSON output and a 4 MiB `maxBuffer`; this is a plausible output-buffer pressure point, not a reproduced root cause. No system limits or broad cleanup were changed. |
| `source-register.mjs` | NOT RUN | Its input depends on production evidence and no safe isolated fixture/input was confirmed. |
| WhatsApp MCP Python tests | NOT RUN | `uv` and `pytest` are unavailable in this environment. Go tests were not rerun because no WhatsApp service files changed. |
| Runtime or production behavior | NOT RUN | No unit result is treated as runtime/production verification. |

The earlier checkpoint's 29 focused tests, workflow and Phase 1 unit tests,
typecheck, focused ESLint, Next.js build, Go formatting/vet/tests, and
`git diff --check` results remain recorded as prior reported passes only;
they were not repeated in this continuation.

### Authorization, changed paths, and preserved state

The Cash-protected paths requiring an explicit, exact-path Owner exception
for the blocked work are:

- `apps/al-rifai/lib/whatsapp-archive.ts`
- `apps/al-rifai/tests/whatsapp-archive-ingestion.mjs`
- `apps/al-rifai/scripts/message-ingestion-worker.ts` only if an edit there is
  demonstrated necessary
- `apps/al-rifai/db/migrations/0012_business_workflows.sql`
- `apps/al-rifai/db/migrations/0015_live_owner_accountant_cash.sql`
- `apps/al-rifai/db/migrations/0016_cash_payment_account_name.sql`
- Any exact migration regression-test/runner paths required by an approved
  implementation

The exception must state exact paths, intended behavior, validation plan,
deployment/restart scope, and financial write boundary. No exception is
granted by this continuation.

Files changed by this continuation:

- `apps/al-rifai/scripts/process-vessel.ts`
- `apps/al-rifai/lib/escort-register.mjs`
- `apps/al-rifai/tests/escort-register.mjs`
- `CASH-VESSEL-DOMAIN-DELIVERY-PLAN-CORRECTED.md`

All previously dirty and untracked app/service work was preserved; no broad
staging, reset, cleanup, production restart/deploy/migration, live replay,
WhatsApp send, credential change, or financial posting occurred.

## Latest continuation update — 2026-10-21

### Current

- Vessel review is static only. No Vessel source or test file was changed in
  this continuation.
- The three Vessel files named above are untracked in the nested
  `apps/al-rifai` repository. Consequently, `git diff` against its committed
  HEAD is empty for them; the current code was inspected directly and compared
  with the preceding checkpoint's description, not with a recoverable patch.
- Cash Freeze remains in effect. No protected code, tests, migration, runtime
  configuration, or deployment file was changed.

### Done in this continuation

- Inspected the current Vessel processor, matching helper, and focused tests;
  traced their batch, replay, review, and canonical-ID behavior.
- Confirmed the project-pinned Node/pnpm toolchain and checked the available
  host and bounded local-runtime locations.
- Rechecked the 0012/0015/0016 constraint collision and searched repository
  history, reflogs, and available local session records for the earlier
  workaround.
- Preserved the dirty root and app worktrees; updated this checkpoint only.

### Unverified / blocked

- Vessel regression tests and typecheck/lint/build: **NOT RUN** because Node is
  unavailable and no safe non-production container test environment could be
  established.
- The exact before/after source patch and Vessel runtime behavior: unverified;
  the three current Vessel files are untracked relative to the app HEAD.
- WA-02 marker correction and migration-chain repair: blocked pending the
  exact-path Owner authorization below. No live or disposable migration run
  occurred.

### Vessel matching review

The observed batch change is narrowly scoped: `process-vessel.ts` creates one
WA-01 `accountRows` collection for the fetched batch and adds each persisted
DRAFT or REVIEW operation to it. `deriveEscortRegisterOps` can therefore see
earlier rows from that batch as it handles later messages.

- The draft candidate predicate remains limited to DRAFT rows and retains its
  account, contact, chat, master, vessel, destination, booking-date, and
  source-time checks.
- Source replay protection remains keyed by account, source hash, and block
  key. The WA-02 rejection and the WA-01-only query/account-row filter remain
  in place.
- Business duplicate matching still requires the account-scoped business key;
  same-shift duplicates reuse the existing canonical order ID, while a
  different shift remains a separate REVIEW with
  `SAME_DATE_DIFFERENT_SHIFT_REQUIRES_REVIEW`. Candidate canonical order IDs
  are deduplicated before shift comparison.
- Persistence still inserts source links/events with conflict protection; the
  batch update does not turn a REVIEW into a confirmation or change the
  existing DRAFT matching predicate.

These are source-level observations, not executed regression results. Because
the files are untracked and no earlier patch was recovered, a complete
before/after diff and runtime behavior are **unverified**.

### Toolchain and tests in this continuation

The app manifest requires Node.js `>=22.13.0` and pins `pnpm@11.25.0`; its
lockfile is v9. The Dockerfile installs Node 22 and pnpm in the build stage,
but its production runtime stage contains Node only. On this host, `node`,
`pnpm`, Corepack, npm, and npx are not on PATH; bounded checks found no
alternate Node binary or pnpm executable. Existing app `node_modules` and a
pnpm store are present, but they cannot run without Node. No Bun, Deno, or
other compatible runtime was found. The container-tool configuration
integration returned “no implementation registered”; no container CLI was
used, and the production app container was not used as a test environment.

| Check actually attempted in this continuation | Result |
|---|---|
| Inspect tracked Vessel diff | No tracked diff; the three source/test files are untracked. |
| Vessel regression tests | **NOT RUN** — no Node runtime; production runtime is not an authorized test environment. |
| Typecheck, focused lint, build | **NOT RUN** — required Node runtime is unavailable. |
| Migration chain execution | **NOT RUN** — no disposable database isolation was established. |
| Production/runtime behavior | **NOT RUN**. |

No application test, typecheck, lint, build, or migration was executed in this
continuation. Any test/build results recorded in earlier sections remain
historical and were not repeated.

### Migration investigation and worktree preservation

Read-only inspection reconfirmed that migration 0012 defines the
`cash_account` column CHECK (PostgreSQL's generated name is
`cash_instructions_cash_account_check`), migration 0015 drops the separate
table-level `cash_instructions_check`, and migration 0016 adds the already
generated column-constraint name. This is the duplicate-constraint collision.
The repository commit/reflog search and available local session records did
not recover the earlier test-only workaround or its command. No migration was
run.

The outer `/opt/vps` worktree and nested `/opt/vps/apps/al-rifai` worktree
remain dirty as they were; no staging, reset, cleanup, or broad rewrite was
performed. The nested repository lists
`/tmp/alrifai-stabilization-20261016/source` as prunable, and that path is
absent; it was not recreated or altered.

### Exact files changed in this continuation

- `CASH-VESSEL-DOMAIN-DELIVERY-PLAN-CORRECTED.md` — this verification record
  only.

No application source, test, migration, configuration, or deployment file was
changed in this continuation.

### Owner authorization request prepared — no authorization granted

Please authorize only the following exact paths and changes:

1. `apps/al-rifai/lib/whatsapp-archive.ts` and
   `apps/al-rifai/tests/whatsapp-archive-ingestion.mjs` — fix the identified
   WA-02 marker-creation defect so WA-02 archive ingestion does not create
   Cash/Vessel pending work; regression coverage will assert that WA-02
   receives no domain markers while authorized WA-01 behavior remains intact.
2. `apps/al-rifai/db/migrations/0012_business_workflows.sql`,
   `apps/al-rifai/db/migrations/0015_live_owner_accountant_cash.sql`,
   `apps/al-rifai/db/migrations/0016_cash_payment_account_name.sql`, and the
   proposed new `apps/al-rifai/tests/cash-migration-chain.mjs` — resolve and
   test the duplicate account CHECK across the fresh migration sequence. The
   test will apply the sequence only to an empty, disposable PostgreSQL
   instance and assert successful application plus preservation of the
   intended account constraint.

For both items, validation will use synthetic fixtures only. Any database
test must verify isolation before execution: fresh test-only credentials,
no production credentials, no production network route or shared volume, and
an empty disposable database. It will perform no live-data reads, payment
posting, Cash-table business-data writes, WhatsApp replay, or message send.
Requested deployment/restart scope is **none**; no production deployment,
restart, or migration is requested. Any need to modify
`apps/al-rifai/scripts/message-ingestion-worker.ts` must be demonstrated and
submitted as a separate exact-path authorization request.

### Owner-authorized execution and verification — 2026-10-22

The Owner subsequently explicitly authorized the listed WA-02 isolation and
Cash migration repair paths. This execution record supersedes the preceding
"no authorization granted" request status. The existing dirty worktrees and
all unrelated work were preserved; nothing was staged.

#### Current

The authorized ingestion guard and migration repair are implemented and
verified in isolated tests. No deployment, restart, production migration,
production database query, payment action, or live WhatsApp action was
performed. Production behavior remains unverified.

#### Root causes and fixes

- **WA-02 ingestion:** The shared marker helper previously created pending
  Cash and Vessel processing rows for records from either WhatsApp account.
  Both compatibility and archive ingestion now always preserve the archive
  marker, but create Cash/Vessel markers only for the exact authorized
  `wa-01` account. Existing rows are not deleted or updated, and duplicate
  handling remains idempotent. No group JIDs, sender identities, or
  authorization mappings were invented.
- **Unknown group input:** The regression case for an unknown WA-01 group
  continues to leave Cash/Vessel work pending review and does not write group
  authorization or identity-review authority records.
- **Cash migration collision:** Migration 0012 creates the
  `cash_instructions_cash_account_check` check. Migration 0015 drops a
  different table-level check and does not remove this account check.
  Migration 0016 attempted to add another constraint with the already-used
  name. Migration 0016 now explicitly drops the existing account check and
  recreates it, allowing the approved `Cash Payment` label while retaining
  the prior safe-label regular expression. The constraint was not weakened
  or skipped.

#### Isolation evidence

- The migration chain ran in disposable container
  `alrifai-migration-chain-test-final-20261022-1235`, with
  `network=none`, read-only root filesystem, database data on container-local
  tmpfs, no published ports, and no production/shared data volumes.
- The only bind mount was the test-only password file, mounted read-only.
  The Node runner shared the isolated container's network namespace, used a
  read-only source mount, and received no production environment or
  credential mounts. The password file was temporary and its contents were
  never printed or recorded.
- Before applying migrations, the disposable database had zero public
  tables. Only synthetic fixtures were used in the focused ingestion and
  Vessel tests.

#### Tests and results

| Check | Result | Notes |
|---|---|---|
| WA-02, archive, and Vessel focused regressions | **PASS** | 29 tests across `tests/whatsapp-archive-ingestion.mjs`, `tests/whatsapp-archive.mjs`, and `tests/escort-register.mjs`; includes WA-02 archive-only markers, WA-01 permitted markers, unknown group pending review, duplicate/replay behavior, and unrelated-record preservation. |
| Workflow and Phase 1 unit tests | **PASS** | Executed in the isolated Node 22.23.3 environment. |
| Full migration chain | **PASS** | 24 migrations applied to the fresh disposable database. |
| Migration-ledger second run | **PASS** | Re-running the established runner applied no migrations; no separate idempotency behavior was added to SQL migrations. |
| Final Cash constraint inspection | **PASS** | Exactly one `cash_instructions_cash_account_check` exists with the approved label and original safe-label regex. |
| Typecheck | **PASS** | Ran in the isolated Node environment. |
| Focused ESLint | **PASS** | Ran against the relevant application source and tests. |
| Full lint | **FAIL** | `scripts/lint.mjs` terminated with `ENOBUFS` at its 4 MiB `spawnSync` output buffer; this is not reported as a lint pass. |
| Build | **PASS, with caveat** | Built in an isolated Node 22.23.3 container. Existing installed Next.js was 16.3.4 while the lockfile specifies 16.3.8; therefore this was not a lockfile-matched build. |
| Production behavior | **NOT RUN** | Production migrations, data, service behavior, deployment, and live WhatsApp behavior were not exercised. |

The host had no Node or pnpm. The cached Node 22.23.3 container was used;
pnpm 11.25.0 and a lockfile-based dependency install were not available or
performed. Thus the build result has the dependency-version caveat above.
Migration 0011 has an explicit transaction boundary inside the existing
migration runner; the failed pre-fix disposable run showed that a later
migration failure can leave earlier ledger work committed. Migration 0011
was not changed because it is outside the authorized file scope.

#### Vessel verification

The focused Vessel regression suite passed. It covers exact duplicates,
same-date/same-shift canonical matching, different-shift review behavior,
idempotency, canonical-ID preservation, and unrelated-record preservation.
No production Vessel behavior was exercised.

#### Files changed in this authorized execution

- `apps/al-rifai/lib/whatsapp-archive.ts`
- `apps/al-rifai/tests/whatsapp-archive-ingestion.mjs`
- `apps/al-rifai/db/migrations/0016_cash_payment_account_name.sql`
- `CASH-VESSEL-DOMAIN-DELIVERY-PLAN-CORRECTED.md` (this record)

Migrations 0012 and 0015 were inspected but not changed; no new
`cash-migration-chain.mjs` test file was needed. Other pre-existing dirty
files and the separate WhatsApp source worktree were left untouched.

#### Remaining blockers and production status

- Obtain an isolated environment with the pinned pnpm version and exact
  lockfile dependencies for a reproducible typecheck/lint/build run; resolve
  or separately diagnose the full-lint `ENOBUFS` failure.
- Production migration application, production data, and live behavior are
  unverified and remain outside this authorization.
- No production service operation or production database/data operation was
  performed. Final read-only container status showed the app and PostgreSQL
  healthy and both WhatsApp bridges up. This execution did not change or
  restart them.

## Owner follow-up — 2026-10-22

### Current

- **Cash date:** The display is backed by `cash_instructions.source_time`.
  `liveCashRows()` selects that field and formats it in `Asia/Dhaka`;
  the Cash transaction table also formats each row's `source_time` in that
  timezone. The coverage notice uses `max(source_time)`, not an ingestion or
  update timestamp. Therefore a displayed date of 2026-10-18 is a stored
  source/business timestamp rendered for Dhaka, not evidence by itself of an
  18 October database update. The specific production timestamp and its
  originating source message were not queried, so whether that particular
  date is expected remains **unverified**. No financial data was read or
  changed for this investigation.
- **Canonical Vessel URL:** The Cash page's Vessel register anchor already
  targets `/vessel`. The Vessel page route exists at `/vessel`. However,
  `app/vessel-dashboard.tsx` initializes `source`, `page`, and `sort` to
  `historical`, `1`, and `newest`, then serializes those defaults with
  `history.replaceState` after loading. This explains the observed query
  string on ordinary entry. The minimal fix is to keep request parameters
  separate from URL serialization and omit untouched defaults from the
  browser URL, while retaining explicitly selected filters. No change was
  made because `app/vessel-dashboard.tsx` is outside the exact approved code
  paths; Owner approval is required before editing it.
- **Read-only live checks:** The app container reported `Up 22 hours
  (healthy)` and PostgreSQL `Up 3 days (healthy)`; both WhatsApp bridge
  containers reported `Up 30 hours`. The local database-backed
  `http://127.0.0.1:3000/api/health` returned HTTP 200. External GET checks
  returned HTTP 200 for `/cash` and HTTP 401 for `/vessel`. The unauthenticated
  `/vessel` response does not verify authenticated page rendering or route
  health. No authenticated browser check was performed.

### Done

- Re-inspected the authorized WA-02 guard: immutable archive markers are
  retained for both accounts, while pending Cash/Vessel markers are created
  only for `wa-01`. The WA-02 archive-only and replay assertions, plus WA-01
  marker behavior, are present in
  `apps/al-rifai/tests/whatsapp-archive-ingestion.mjs`.
- Re-inspected migration 0016: it drops and recreates the existing account
  check with the exact `Cash Payment` exception and original safe-label
  regular expression. Migration 0012's account check and migration 0015's
  separate table-check removal remain intact. The existing handoff records
  the isolated 24-migration run, second-run ledger check, and final constraint
  inspection as PASS; those are prior execution results, not rerun here.
- Re-inspected the existing Vessel shift/deduplication changes. The prior
  isolated run recorded 29 focused archive, ingestion, and Vessel tests as
  PASS; that result is historical evidence and was not rerun in this session.
- Updated this handoff with the date, canonical URL, live-route, test, and
  remaining-authorization findings.

### Unverified

- The production row/source behind the reported 2026-10-18 date was not
  inspected. A bounded read-only production financial-data query would be
  needed to classify that individual timestamp conclusively; it was not
  performed under the existing no-live-record-query boundary.
- The regression suites could not be rerun: the host has no Node.js or pnpm,
  and the container-tools configuration integration is unavailable. The
  production app container was not used for testing. No migration test was
  rerun; the only recorded migration result remains the prior isolated run.
- The current external `/vessel` result is unauthenticated HTTP 401, so
  authenticated route rendering remains unverified. `/cash` returned HTTP
  200, but no authenticated Cash data was inspected.
- No application source, test, or migration path was changed in this
  follow-up. The only path changed in this follow-up is
  `CASH-VESSEL-DOMAIN-DELIVERY-PLAN-CORRECTED.md`. Earlier authorized
  implementation paths and results are recorded above.
- Next safe action: obtain explicit approval for the minimal
  `apps/al-rifai/app/vessel-dashboard.tsx` URL-serialization change; separately
  authorize any production record inspection if the Owner needs the exact
  source row for the reported date. Do not deploy or modify financial data.

No production deployment, restart, migration, or live financial-data
modification was performed.

## Goal-driven continuation — 2026-10-22, 13:52 CEST

### Current

- The source-level Vessel URL fix is in the worktree, not production. Ordinary
  entry now keeps `/vessel` free of untouched `source=historical`, `page=1`,
  and `sort=newest`; the API request still includes the same default
  parameters, so the loaded dataset and ordering are unchanged. Explicitly
  supplied initial values and user-selected source, page, sort, and non-empty
  filters remain represented in the browser URL. Browser updates continue to
  use `replaceState`, not navigation entries.
- The Cash page link remains `/vessel`; `/vessel` is the actual app route.
- **Cash date classification:** The Cash transaction table takes its
  displayed date from the row's `source_time`, formatted in `Asia/Dhaka`.
  The API's optional date-range predicates also compare `source_time` in
  `Asia/Dhaka`; the initial Cash UI date-range state is empty. This identifies
  the displayed field as the transaction/source timestamp, not an ingestion
  or update time, and shows no default date-range filter in the UI code.
  However, the exact production timestamp behind 2026-10-18 could not be
  read: the minimum timestamp-only query was denied on `cash_instructions`
  for role `alrifai_app`. No additional permissions were requested. Whether
  this particular source timestamp is correct or a source-data issue is
  therefore **still unverified**.
- **Read-only live checks this continuation:** local `/api/health` returned
  HTTP 200; local and public `/cash` returned HTTP 200; local and public
  `/vessel` returned HTTP 401; local and public `/api/cash/me` returned HTTP
  401 without credentials. The two 401 statuses are consistent with an
  unauthenticated request and do not establish authenticated rendering.
  Container status showed `al-rifai-app-1` healthy, PostgreSQL healthy, and
  both WhatsApp bridges running. No authenticated access was attempted.

### Done

- Updated `apps/al-rifai/app/vessel-dashboard.tsx` to build browser URL
  parameters separately from API request parameters, omit untouched
  defaults, preserve explicitly selected base state, and avoid a redundant
  `replaceState` when the URL is unchanged. Record open/close now uses the
  browser-state parameters while API fetches retain all internal defaults.
- Added `apps/al-rifai/lib/vessel-url-state.ts`, a pure typed serializer, and
  `apps/al-rifai/tests/vessel-url-state.mjs` with focused default, explicit
  default, filter, source, page, and sort cases.
- Re-inspected WA-02 ingestion and tests. The common marker helper retains
  archive markers but gates pending Cash/Vessel markers on exact account
  `wa-01`. Tests specify WA-02 compatibility/archive-only behavior and
  idempotency, along with WA-01 marker creation. The WA-02 worker may archive
  messages, but the marker boundary prevents that ingestion from creating
  Cash/Vessel work.
- Re-inspected processing separation: Cash consumes only pending `cash`
  markers for `wa-01` and classifies review candidates with
  `financialAction: "NONE"`; Vessel consumes only pending `vessel` markers
  for `wa-01` and persists to escort-order/source/event tables. The archive
  processor operates only on `archive` markers. No Cash/Vessel cross-domain
  trigger or shared financial writer was found in the inspected paths.
- Re-inspected posting isolation: Cash postings are written through the
  guarded database functions, with operation replay checks and append-only
  business-fact protections; the app role's migration grants are SELECT on
  posting tables and EXECUTE on the guarded function. Cash processor status
  updates target WhatsApp processing markers, not canonical Cash postings.
  The Vessel register API is read-only and rejects POST, PUT, PATCH, and
  DELETE. This is source-level evidence, not a production authorization or
  grant inspection.
- Re-inspected the migration 0016 account-check replacement. The prior
  handoff's isolated migration-chain pass remains historical evidence; no
  migration was executed during this continuation.

### Tests and checks in this continuation

| Check | Result | Scope |
|---|---|---|
| `tests/vessel-url-state.mjs` | **PASS** — 3 tests | Ran with Node 22.23.3 in a disposable `--network none`, `--read-only` container with the source mounted read-only. |
| `git diff --check` | **PASS** | App worktree; no whitespace errors. |
| WA-02 ingestion / archive / Vessel existing suites | **NOT RUN** | No host Node/pnpm or app `node_modules`; the read-only Node container has no project dependencies. Existing prior PASS is historical, not rerun. |
| Typecheck, ESLint, Next build | **NOT RUN** | Dependencies and pinned pnpm install are unavailable; no install was attempted. |
| Migration-chain execution | **NOT RUN** | No migration was run. The recorded isolated 24-migration PASS and second-run check are from the earlier authorized execution. |
| Cash timestamp-only diagnostic | **BLOCKED** | Read-only query returned `permission denied for table cash_instructions` for `alrifai_app`. No production records or sensitive fields were returned. |
| Route/auth and container checks | **OBSERVED** | HTTP statuses and container health above; not an authenticated application check. |

### Exact paths changed in this continuation

- `apps/al-rifai/app/vessel-dashboard.tsx`
- `apps/al-rifai/lib/vessel-url-state.ts`
- `apps/al-rifai/tests/vessel-url-state.mjs`
- `CASH-VESSEL-DOMAIN-DELIVERY-PLAN-CORRECTED.md`

All pre-existing dirty tracked and untracked work in `/opt/vps`,
`apps/al-rifai`, and `services/whatsapp/source` was preserved. No staging,
reset, cleanup, dependency install, configuration change, or unrelated
rewrite was performed.

### Unverified and next authorized steps

- To classify the exact 2026-10-18 date, the least-privilege next step is for
  the Owner or a separately authorized read-only database operator to run a
  timestamp-only query for the latest `wa-01` / `Cash Payment` instruction,
  returning only its `source_time` and `created_at` in `Asia/Dhaka`. Do not
  widen `alrifai_app` privileges for this purpose without separate Owner
  approval. Do not retrieve row IDs, amounts, employee/contact fields, or
  message content.
- Authenticated Vessel/Cash page rendering and the deployed browser URL
  remain unverified. Do not deploy merely to validate the source change.
- The focused URL helper test passed, but application typecheck, lint, build,
  and the existing Cash/WA-02/Vessel suites have not been rerun against the
  current complete worktree.
- Production readiness is **not established**. The next smallest safe step
  is the Owner-provided aggregate timestamp evidence; thereafter, run the
  project checks in an already-authorized isolated environment before
  considering a separately authorized release.

No production deployment, restart, migration, or live financial-data change
occurred.

## Goal-driven continuation — 2026-10-22, 14:49 CEST

### Current verified state

- The authorized Vessel URL behavior is in the worktree only. The Cash-page
  link remains `/vessel`, the route exists, and the API request construction
  retains its existing defaults. The browser URL omits untouched default
  `source=historical`, `page=1`, and `sort=newest`, while explicit base state
  and non-empty filters remain shareable. Redundant `replaceState` calls are
  skipped. A React lint finding was fixed by initializing the URL-state ref
  once through `useRef`'s initializer.
- Authenticated browser rendering and the deployed browser URL remain
  unverified; no deployment was performed.
- Cash UI source confirms that the displayed date uses `source_time` formatted
  in `Asia/Dhaka`. The existing relevant-record scope is `wa-01` and
  `Cash Payment`, ordered by `source_time DESC, id DESC`; `cash_instructions`
  has both `source_time` and `created_at`. This identifies the displayed
  field, but not the actual production values behind 2026-10-18.
- The timestamp-only production read remains **BLOCKED** by the previously
  observed `permission denied for table cash_instructions` for `alrifai_app`.
  No alternate privileged credential, broader grant, authenticated API
  probe, or sensitive-field query was used.
- Production was not deployed, restarted, migrated, or written. A read-only
  health check returned `{"status":"ok"}`; app/PostgreSQL were healthy and
  both WhatsApp bridge containers were running at observation time.
- The starting worktree had substantial pre-existing dirty changes in the
  app and WhatsApp-source repositories, including Cash-protected files.
  Those were preserved without staging, reset, or cleanup. This continuation
  changed only `apps/al-rifai/app/vessel-dashboard.tsx` for the ref lint fix
  and this plan plus `NEXT-SESSION-HANDOFF.md`.

### Validation record for this continuation

Checks ran in disposable Node 22.23.3 containers with `--network none` and
read-only source mounts; the build used a temporary copy, and no production
database, credentials, WhatsApp sockets, or volumes were available.

| Check | Result | Evidence / limitation |
|---|---|---|
| URL-state + Cash safety + Vessel health isolation + WA-02 archive tests | **PASS** — 19 tests | Includes defaults/shareability, no-posting safety, and WA-02 archive-only assertions. |
| Package-defined escort and archive tests | **PASS** — 23 tests | Re-run after the ref correction. |
| Workflow tests | **PASS** | Isolated run completed. |
| Phase-1 unit checks | **PASS** | Isolated run completed. |
| Typecheck | **PASS** | `tsc --noEmit` succeeded with temporary compiler state. |
| Targeted ESLint | **PASS** | Dashboard, serializer, and URL-state test. |
| Full ESLint | **FAIL** | Existing wrapper exited on `ENOBUFS`; direct full-tree lint reported 8,291 errors and 92,728 warnings, including archived qualification copies. No unrelated baseline cleanup was attempted. |
| Next build | **PASS, qualified** | `/vessel` and other routes built in isolation. Installed Next.js was 16.3.4; committed manifest/lockfile specify 16.3.8, so exact lockfile-version build is still unverified. |
| Authenticated browser rendering | **NOT RUN** | No authenticated production or test-account session was used. |
| `tests/source-register.mjs` | **BLOCKED** | The evidence file `/var/lib/vps/al-rifai/evidence/chat-archive.json` was not present in the isolated environment; no production evidence mount was added. |
| `git diff --check` | **PASS** | Root, app, and WhatsApp-source worktrees. |
| Migration chain / production integration | **NOT RUN** | No database, import, or production integration was executed. |

### Isolation and Cash/Vessel boundary

- WA-02 archive ingestion tests pass with archive-only markers and
  idempotency; no pending Cash or Vessel markers are created for WA-02.
  Tests preserve WA-01 marker eligibility. Current Cash and Vessel processor
  queries also constrain pending work to `wa-01`. This is source/test
  verification, not a live ingestion run.
- No Cash source behavior, tests, migrations, dependencies, deployment
  configuration, payment data, or employee data were changed. Cash Freeze
  remains active. No message was sent.
- The exact 2026-10-18 source timestamp remains unverified. Next authorized
  action: the Owner or an already-authorized read-only database operator
  returns only `source_time` and `created_at` in `Asia/Dhaka` for the latest
  row in the existing `wa-01` / `Cash Payment` scope, selected using
  `source_time DESC, id DESC`. Do not widen `alrifai_app` grants or return
  identifiers, amounts, identities, or message content.
- Before considering a release, run the full safe validation against exact
  lockfile dependencies in an authorized isolated environment. No release,
  deploy, or restart is authorized here.

## Goal-driven continuation — 2026-10-22, 15:48 CEST

### Current

- The required latest Cash `source_time` and `created_at` values remain
  **BLOCKED**. The prior timestamp-only query was denied for `alrifai_app`;
  this continuation did not retry it or seek alternate access.
- `package.json` and `pnpm-lock.yaml` specify Next.js `16.3.8`; the package
  manager is pinned to `pnpm@11.25.0`. No verified isolated dependency tree
  for those exact locked versions was established, so no build or test was
  run and no package download/install was attempted.
- `tests/source-register.mjs` was not run because it requires
  `chat-archive.json`; no safe fixture was confirmed, and no production
  evidence or personal data was copied or mounted.
- `git diff --check` passed for tracked root, app, and WhatsApp-source diffs.
  This does not cover untracked files.
- The root, app, and WhatsApp-source worktrees were already dirty. The app
  worktree still contains changed Cash-protected UI/API, library,
  migration, test, package/configuration, and release paths. This inspection
  did not establish the provenance or exact-path Owner authorization for
  those changes. They remain untouched.
- Production health/status was not rechecked. Prior live observations are
  historical, not a current health assertion.

### Isolation and readiness

- No Cash/Vessel behavior, production data, configuration, database,
  container, bridge, or WhatsApp state was changed by this continuation.
  No message was sent. Cash Freeze remains in force.
- Cash/Vessel isolation for the current dirty worktree is **UNVERIFIED** due
  to the outstanding protected-path changes and missing authorization
  evidence. Previous source/test results remain historical and were not
  rerun.
- **Deployment readiness: BLOCKED.** The timestamp evidence, exact
  lockfile-version build, `source-register` test, and authorization status of
  the protected worktree changes remain unresolved.
- Next action: have the Owner or an already-authorized read-only database
  operator provide only the latest in-scope `source_time` and `created_at`
  in `Asia/Dhaka`; do not widen grants or return other fields. Keep all
  protected dirty changes untouched pending exact-path Owner review.
- No production deployment, restart, migration, or write was performed.

## Read-only Cash/Bridge audit — 2026-10-22, 16:41 CEST

### 1. Bridge/source timestamp evidence

- Bridge1 source schema defines message identity as `(id, chat_jid)` and
  stores sender, timestamp, and direction. WA-01/WA-02 containers were
  running, but the approved health probes returned no payload (exit code 6).
  No alternate API, socket, credential, or store access was attempted.
- Existing bounded MCP history-list tools include message body text; the
  proof tool needs known message IDs and returns state/hash rather than
  timestamp/sender. No metadata-only native read was available in this
  session; actual Bridge1 SQLite rows are **UNVERIFIED**.
- A read-only aggregate against the AL-RIFA'I projection, filtered to WA-01
  Cash payment candidates, found 1,707 processed candidate rows. All had a
  message ID, timestamp, sender reference, and chat reference. No message
  IDs, contacts, body, amounts, or employee data were returned. This verifies
  populated fields in the projection only, not complete bridge-to-app sync or
  Cash-row mapping.
- The live projection schema exposes native message ID, chat, sender,
  timestamp, direction, and ingestion time. It is not evidence that every
  Bridge1 message was copied losslessly.

### 2. Cash-record mapping

- **BLOCKED:** `alrifai_app` has no SELECT privilege on `cash_instructions` or
  `source_refs`. No Cash row or exact latest `source_time`/`created_at` pair
  was read; no alternate role or grant was used.
- `source_time` is the source event timestamp; `created_at` is when the Cash
  instruction was created in the application database. They are different
  timestamps and the requested latest pair remains unverified.

### 3. Duplicate protection

- Live database index metadata confirms unique source-message identity
  `(wa_account, chat_jid, message_id)` and unique processing identity
  `(original_id, domain)`.
- Cash postings have unique `(scope_account, operation_id)`. Cash
  instructions have primary-key uniqueness, but the operation index is
  non-unique. The source-reference unique index includes
  `(scope_account, channel, external_ref, block_key, payload_hash)` and does
  not alone enforce uniqueness by source message/block independent of hash.
- The dirty source snapshot uses deterministic account/chat/message/block
  IDs and an operation advisory lock; production use of that code is
  unverified. Timestamp equality alone is not a safe duplicate rule because
  separate messages can share timestamp resolution, while one message may
  contain multiple legitimate blocks.

### 4. Employee identity and ledger

- Live aggregate metadata shows 173 WA-01 `employee_master` rows; all are
  in `REVIEW` state and all have aliases. No phone, name, alias, or transaction
  data was returned. The table key is `(scope_account, employee_mobile)`;
  correctness of any individual cash-to-employee mapping remains
  **UNVERIFIED**.

### 5. Cash access control

- Static review of the dirty, uncommitted app worktree finds only `ADMIN` and
  `USER` Cash portal roles, not a distinct `SUPER_ADMIN` role. The `summary`
  and `messages` GET handlers authenticate but do not call `requireAdmin`;
  user-management handlers do. The messages handler selects message text and
  sender metadata. If deployed, this worktree API appears to allow a regular
  authenticated `USER` to read sensitive Cash data, contrary to the stated
  Super Admin-only rule.
- This is not a verified live authorization result. GET authentication also
  updates session/user activity timestamps, so the endpoints were not called
  under a “read-only DB” requirement. No accounts or credentials were used,
  and deployment of the dirty worktree is unverified.

### Safety and readiness

- Inspection was limited to schema/index metadata, scoped aggregate counts,
  static code, and container status/health. No message body, Cash row, phone,
  employee identity, amount, secret, or credential was read or returned. No
  production data or behavior was changed; no message was sent.
- The bridge health probes returned no response; container status alone does
  not prove the native reader or bridge API is available.
- **Deployment readiness: BLOCKED.** The direct native metadata read, Cash
  record mapping/timestamps, employee mapping correctness, live access-control
  behavior, and authorization of the protected dirty worktree remain
  unresolved. Next action: request an exact-scope metadata-only result from
  the Owner or an already-authorized read-only operator; do not widen grants,
  expose financial/message details, or modify Cash behavior.

## Ready-made tool discovery and capability closure — 2026-10-22

This continuation reuses the retained architecture and audit evidence above.
It is not a new live audit: no production query, endpoint probe, test, package
installation, deployment, restart, migration, or business write was performed.
Only this plan and `NEXT-SESSION-HANDOFF.md` were updated. Root, app, and
WhatsApp-source worktrees were already dirty; no existing changes were staged,
replaced, or cleaned. Cash Freeze remains in force.

### A–G. Candidate assessment and selection

| Need | Candidate / evidence | Compatibility, operating cost and risk | Decision |
|---|---|---|---|
| A. PostgreSQL read-only MCP and schema/query inspection | [CrystalDBA Postgres MCP](https://github.com/crystaldba/postgres-mcp), MIT; upstream README documents restricted/read-only mode. Current metadata reports package `0.3.0`, Python `>=3.12`, and `mcp[cli] <2.0`; its current branch commit observed here is 2026-08-16. | Additional Python/container plus a DB credential and network path. Restricted mode is not a replacement for database ACLs; an MCP client could still retrieve any rows the role can SELECT. The host Python is 3.10 and production app image has no Python. GitHub's advisory page could not be retrieved in this review, so advisory status is unknown, not “none.” | **Do not deploy or connect to production now.** If a future isolated POC is approved, pin image/version, use a dedicated DB principal restricted to diagnostic views, set bounded query timeouts, test read-only behavior and inspect the exact tool surface. Do not use `alrifai_app` or `ir_review_runtime`. |
| B. WhatsApp source inspection and metadata-only reads | Reuse the existing [WhatsApp MCP/bridge source](https://github.com/verygoodplugins/whatsapp-mcp) (MIT) and its account-bound native/store adapters; no second bridge or message pipeline. [Native Message Intake Inventory](apps/al-rifai/docs/NATIVE_MESSAGE_INTAKE_INVENTORY.md) records older source-store schema and coverage limits. | Static source inspection finds `list_archive_messages` returns message text and is gated by both `native.events.read` and `native.content.read`. The candidate `list_native_events` reader can return held records without content, but `native.events.read` is not in the current capability map, so the diagnostic tool is not available through the current map. The source tree has uncommitted changes; this is not proof of deployed behavior. | **Reuse existing bridge; close the metadata-only tool gap before use.** A narrowly scoped tool must require `native.events.read` only, expose bounded identity/time/direction/status metadata, and never expose body/media/quote or send/write operations. This bridge-source change is protected and needs an exact-path Owner exception. |
| C. Reconciliation, lineage, duplicate tests and data quality | Existing AL-RIFA’I `source_refs`, `domain_events`, reconciliation tables, append-only message evidence and PostgreSQL unique constraints; existing `node:test` suite. Compare [dbt Core](https://github.com/dbt-labs/dbt-core) (Apache-2.0; [official docs](https://docs.getdbt.com/docs/introduction)) and [pgTAP](https://github.com/theory/pgtap) (PostgreSQL license; currently documented at 1.3.5). | dbt is for SQL transformation/model graphs and adds a Python/toolchain workflow not needed for this application. pgTAP is a PostgreSQL extension; installing it into the production server would require server/database changes. The existing runtime and fixtures already use Node's test runner and disposable PostgreSQL qualification. | **No new data platform.** Build fixed, read-only reconciliation queries/views and business invariants into the existing isolated test workflow after authorization. Consider pgTAP only inside a disposable DB if SQL assertions cannot be covered with the existing harness; never install it in production for this task. |
| D. Health, logs, errors and alerts | [Gatus](https://github.com/TwiN/gatus), Apache-2.0; the repository is actively changing (latest commit observed 2026-10-22) and its current `go.mod` targets Go 1.26.3. [Uptime Kuma](https://github.com/louislam/uptime-kuma), MIT; latest commit observed 2026-10-20. | App and container already have `/api/health` / Docker healthchecks, bounded JSON logs, and approved one-shot checks, but retained evidence describes no independent alerting. Gatus is configuration-driven and can be one small separate monitor, but still adds a container, network reachability and an alert destination. Uptime Kuma offers a UI and many notification integrations but persists local SQLite state and its current package declares Node `>=26.2` (its README's older Node requirement differs); its admin UI and state add more operations. Neither candidate's GitHub advisory page was retrievable here. | **Reuse current healthchecks first.** If independent alerts are required, prefer a pinned Gatus image and a minimal allow-listed endpoint config, only after Owner approves service/network/alert destination. Do not deploy Uptime Kuma in parallel. No public status page or sensitive endpoint/data exposure. |
| E. Integration tests and isolated database fixtures | Existing Node built-in test runner and recorded disposable Node/PostgreSQL workflow; [Testcontainers for Node.js](https://github.com/testcontainers/testcontainers-node), MIT, active (latest commit observed 2026-10-14). | Testcontainers provides throwaway Docker-backed dependencies and fits Node 22, but adds a package, Docker daemon access and another dependency to the app test tree. `package.json` is Cash-protected; this task did not alter it. Existing tests already use the built-in runner and the retained qualification pattern. | **Reuse the current isolated harness.** Consider Testcontainers only if it materially simplifies repeatable disposable-Postgres tests; add it only in an authorized change and never point it at production. No dependency was installed. |
| F. App authentication, roles and audit | Existing Next.js server-side session, app route guards and candidate `cash_portal_audit`; compare [Auth.js](https://authjs.dev/) (ISC). | Auth.js is a general authentication library, not the missing Owner/Super Admin business-authority mapping; replacing the existing session model would be a broad, risky migration. Static review of the dirty app candidate found `ADMIN`/`USER` roles and a possible Cash GET guard gap; live deployment and authorization remain unverified. | **Do not replace authentication.** Close the exact app authorization gap in the existing server-side path, with an explicit Super Admin grant and tests. Do not treat a UI-only restriction or MCP token as end-user authorization. The Cash code/test change is protected and needs explicit Owner authorization. |
| G. Workflow/orchestration | Airflow/Prefect-style pipeline alternatives were considered against the current Next.js + PostgreSQL + account-scoped MCP architecture. | The existing bounded reader/consumer and DB cursor/processing state already describe the intended workflow. An orchestrator would add another service, credentials, retries and a competing operational control plane without closing a demonstrated gap. | **Reject for now.** Keep one existing source reader, one canonical database and domain-specific processors. |

The assessment is based on official repositories/docs and repository files
available on 2026-10-22. It is not a code audit of each third-party project.
Repository activity/release metadata is not a security certification. Since
public GitHub advisory pages could not be fetched for Postgres MCP, Gatus or
Uptime Kuma, their advisory status remains **UNVERIFIED** and must be checked
again at version-pinning time.

### B. Reuse, source-to-Cash evidence and limitations

| Stage / measure | Evidence retained | Status |
|---|---|---|
| Bridge source schema | `messages.db` stores composite `(id, chat_jid)`, sender, timestamp and direction (`is_from_me`); the old inventory recorded 14,541 WA-01 and 12,604 WA-02 rows on 2026-10-12. The current bridge projection is not an immutable/lossless event archive. | **HISTORICAL ONLY.** No current source rows or same-scope count was read. |
| Bridge to app projection | A bounded WA-01 Cash-candidate aggregate in the 2026-10-22 audit found 1,707 rows, each with message ID, timestamp, sender reference and chat reference. | **PARTIAL.** This is not a comparable total of all Bridge1 rows, nor proof of complete ingestion. |
| Ingestion / processing outcomes | App migration/source defines original-message uniqueness `(wa_account, chat_jid, message_id)` and one processing row per `(original_id, domain)`, with `pending`, `processed`, and `error` states. | **STATIC CANDIDATE ONLY.** No current live status totals, failure/rejection breakdown or missing-source list are available. |
| Cash instruction/posting link | The retained live index audit found unique `cash_postings(scope_account, operation_id)`. Cash instruction/source-reference row access as `alrifai_app` was denied. The `source_refs` unique key includes `payload_hash`, so it does not alone enforce per-message/block uniqueness independent of payload. | **BLOCKED.** No Cash rows, source timestamps, creation timestamps, posting totals or unmatched identities were read. |
| Employee link | The prior scoped aggregate found 173 WA-01 `employee_master` rows, all `REVIEW`; no names, numbers or transaction rows were returned. | **UNVERIFIED.** No correct normalized-mobile-to-ledger mapping is proven. |
| Failures / duplicates / unmatched | The schema has error/status fields and keys that can support reconciliation; exact counts require same-window, same-scope source and app reads. | **UNVERIFIED, not zero.** Do not infer no failures, duplicates or unmatched records from missing permission. |

The 14,541 historical all-WA-01 source messages and 1,707 scoped candidate
projection rows have different scope and observation dates; they must not be
subtracted or represented as an ingestion loss count. The approved bridge
health probes in the retained audit returned no payload (exit code 6). No
alternate socket, credential or SQLite-store access was attempted.

Current dirty source code statically calls the archive reader, which returns
message content, and a Cash processor that classifies candidates as
`financialAction: NONE`; these facts do not establish production use or a
posting guarantee. The dirty Vessel processor also writes only DRAFT/REVIEW
operations in its candidate path and is scoped to WA-01. No such code was
executed or changed here. The live state and deployment of the worktree remain
unverified.

### C. Capability, permission and dependency package

These are proposed, **not granted**, production dependencies:

| Item / target | Minimum required scope | Why and guardrails | Validation / rollback |
|---|---|---|---|
| Bridge metadata reader / WA-01 native store | One new read-only MCP capability (`native.events.read`) on a server-side allow-list of exact account/chat/cursor scopes. Output source message ID or stable opaque key, source timestamp, direction, pseudonymous sender/chat reference, event state and cursor only. No body, media, quote, content hash, contact lookup, send, read-receipt, or store mutation. | Needed to reconcile exact source identity and source time without exposing content. Client arguments cannot widen account/chat scope; bounded pages/timeouts; fail closed on missing source metadata. | Use synthetic isolated store rows, test authorized/denied scope and content omission, and compare counts against source fixtures. Revoke that consumer capability/config to roll back. Any source/profile/host policy edit requires the exact-path exception described below. |
| PostgreSQL diagnostic access | New `NOLOGIN` view-owner plus separate `LOGIN` diagnostic role only if the existing authorized API/MCP cannot return the required metadata. `CONNECT` to `alrifai`; `SELECT` on explicitly named security-barrier diagnostic views only; no base-table, sequence, schema-create, temp, function-execute, or DML privilege. Do not widen `alrifai_app` or reuse `ir_review_runtime`. | Required to compare source, ingestion/processing, Cash-posting and Vessel counts without granting broad table access. Views should expose only fixed-scope status, timestamps and opaque source linkage; omit bodies, amounts, employee names/mobile/JIDs, passwords and arbitrary SQL. Validate owner rights, `search_path`, column ACLs and whether the view is fixed-scope; privilege boundaries are separate from app authorization. | Test effective privileges and zero write access in disposable PostgreSQL; test only aggregate fixtures. Revoke role/view grants and remove the isolated secret reference for rollback. A production role/secret/grant or migration requires Owner approval. |
| Cash application Super Admin authorization | Existing app session only; an explicit server-side `SUPER_ADMIN` authority and mandatory guard on every Cash data-read route and nested data accessor. No extra database read capability for ordinary users. | Business rule is Super Admin-only. The static candidate roles are only `ADMIN`/`USER`; do not silently promote a user or infer authority from chat membership. Keep bridge diagnostic tokens separate from app sessions. | Test anonymous, USER, ADMIN and explicit SUPER_ADMIN outcomes in an isolated fixture, including non-GET denial and indirect routes. Roll back the app image only if no irreversible data/schema change was made; revoke the role grant if authority was provisioned. Owner must identify the authorized principal(s). |
| Reconciliation/test tooling | Existing Node `node:test`, existing locked toolchain, disposable PostgreSQL/SQLite fixtures only. Optional Testcontainers dependency only after approval. | Covers count reconciliation, idempotency, authorization and domain separation without importing production data. Never run app package scripts against live env or production DB. | Exact lockfile install/build/test in an isolated Node 22 environment with network/data isolation and synthetic fixtures; destroy only the named disposable environment. No production DB or bridge mount. |
| Monitoring | Existing `/api/health`/Docker healthchecks first. Optional pinned Gatus container on an allow-listed internal network, read-only HTTP checks, no database credentials; alert receiver to be specified by Owner. | Needed for independent alerting, not business data access. Avoid monitor admin UI on a public interface and avoid exposing diagnostic query data. | Verify healthy/unhealthy synthetic endpoints and alert delivery in isolated staging; remove the monitor service/config to roll back. New service/network/notification credentials need Owner approval. |

Do not return message IDs or chat/sender identities in general diagnostics by
default. Use stable opaque linkage inside a server-side, exact-scope query and
show only counts/statuses unless record-level reconciliation is separately
authorized. Any discrepancy must be reviewable without turning an ambiguous
match into an automatic posting.

### D. Security, idempotency and domain-isolation proof gates

No new test was run in this continuation. The following are mandatory **NOT
RUN / BLOCKED** gates before any production readiness claim:

1. **Source-to-Cash:** reconcile a bounded fixed WA-01/Owner–Accountant source
   interval to ingested, processed, rejected/error, eligible, unmatched,
   instruction, and `cash_postings` counts; include stable source linkage and
   source/ingestion/processing/Cash creation timestamps. Return only required
   metadata and aggregate totals.
2. **Replay/concurrency:** re-ingest the same account/chat/message/block and
   process it sequentially and concurrently; prove one source row, one
   processing outcome and at most one posting by stable `operation_id`.
   Distinct message IDs with the same timestamp/body remain distinct; separate
   valid blocks in one message remain separate.
3. **Employee/posting:** only a verified normalized employee mobile may link
   to the intended ledger identity. Unknown, conflicting or `REVIEW` mapping
   stays unposted. `cash_postings` is canonical. Late delivery/status/replay
   cannot mutate or repost a Posted transaction.
4. **Authorization:** no unauthenticated, USER or ordinary ADMIN principal can
   read Cash amounts, messages, postings or employee data; only explicitly
   authorized SUPER_ADMIN succeeds. No test may use production credentials.
5. **Vessel isolation:** permitted Escort Client/chat source creates only
   Escort DRAFT/REVIEW records; Cash/Accountant chat and disallowed accounts
   create none. Cash/Vessel identities, scopes, permissions and writers stay
   separate. Re-run existing WA-02 and source-scope regressions.
6. **Database and health:** diagnostic role cannot SELECT underlying tables
   or execute writes; fixed views return no message content. App and bridge
   health/alert failures are visible with redacted errors and recover after
   the isolated dependency is restored.

Historical test passes in earlier handoffs are not current passes. Exact
lockfile-version build/test, browser authorization, production permission
behavior, migration state and all gates above remain **NOT RUN / UNVERIFIED**.
Do not use production data or attempt protected tests until exact-path Owner
authorization and a genuinely isolated test environment are established.

### E. Readiness, deployment order and rollback

**Production readiness: BLOCKED.** Current completion is limited to existing
architecture reuse, static candidate evaluation and documentation. The
requirements for comparable source-to-Cash counts, correct employee mapping,
live Super Admin enforcement, end-to-end duplicate posting prevention,
production deployment provenance and verified alerting are not proven.

After the required authorization, use this order:

1. Preserve and identify all existing dirty changes and their provenance;
   obtain explicit Owner disposition for protected paths before incorporating
   or deploying them.
2. Build a source/DB metadata-only POC against synthetic, isolated bridge and
   PostgreSQL fixtures. Add no dependency if built-in Node tests suffice.
3. Implement/test the native metadata-only reader and diagnostic view/role
   only under their exact-path/database exception; test ACLs and no-content
   output before any data connection.
4. Fix and test Super Admin Cash reads and the source/employee/posting
   invariants in isolation. No financial writer behavior is changed by this
   plan; any posting behavior change needs a separate financial exception.
5. Run exact-lockfile typecheck, focused tests, full tests and build in the
   authorized isolated Node 22 environment. Record PASS/FAIL/BLOCKED for each.
6. Approve a separate deployment window and explicit scope. Deploy only the
   approved app/bridge image and additive, backward-compatible read-only
   diagnostic grant/view, then verify health, permissions and redacted error
   visibility. Do not restart/deploy any service under this documentation
   update.

Rollback: remove monitor configuration/service if adopted; revoke only the
diagnostic role's view grants and secret reference; disable the new
metadata-reader capability; restore the prior pinned app/bridge image only
under an approved deployment action. Prefer additive database changes; do not
drop or rewrite business rows as rollback. Preserve evidence, stop on
unexpected financial or domain effects, and escalate rather than auto-revert.

### F. Owner decisions and exact protected exception request

Recommended defaults: (1) no production access until an exact-scope
metadata-only channel and least-privilege role are ready; (2) no posting or
employee mapping changes under Cash Freeze; (3) no new orchestrator; (4)
Gatus only if an alert destination and new service are explicitly approved;
(5) do not grant any existing portal account Super Admin by inference.

Before implementation of the identified security/capability work, the Owner
must provide one consolidated exception that states the exact paths, intended
behavior, validation plan, deployment/restart scope and financial write
boundary. The candidate protected paths for review are:

- Bridge metadata-only capability: `services/whatsapp/source/whatsapp-mcp-server/main.py`,
  `services/whatsapp/source/whatsapp-mcp-server/capabilities.py`,
  `services/whatsapp/source/whatsapp-mcp-server/native_reader.py`, and a
  focused capability test under
  `services/whatsapp/source/whatsapp-mcp-server/tests/`.
- Cash API authorization: `apps/al-rifai/app/api/cash/[...path]/route.ts`,
  `apps/al-rifai/lib/cash-portal.ts`, and a focused authorization test under
  `apps/al-rifai/tests/`.
- Diagnostic DB boundary only if the MCP/API cannot meet the need: one new
  additive migration under `apps/al-rifai/db/migrations/` plus an isolated
  privilege/contract test under `apps/al-rifai/tests/`.
- Monitoring: a new Gatus service/config in the existing infrastructure
  configuration, only if the Owner approves a new service, internal
  reachability and a specific alert destination.

The recommended financial write boundary for these tasks is **no production
business-data writes, no Cash posting/approval changes and no WhatsApp sends**.
The authorization change is intended to restrict access, not create or alter
financial records. Database role/view creation and deployment/restart remain
separate production approvals. The Owner must explicitly identify which
existing person, if any, is authorized as Super Admin; no account is promoted
by default.

## Bounded offline implementation — 2026-10-22

The Owner approved offline code/test work only for the listed bridge metadata
capability and Cash API authorization paths. This does not authorize production
database changes, runtime configuration, migration, restart, deployment,
financial writes, Cash posting/approval changes, or WhatsApp sends.

### Implemented in the approved paths

- Registered `list_native_events` under the dedicated `native.events.read`
  capability. `native.identity.read`, `messages.read`, or a send capability
  alone does not expose it.
- Made the native events page explicitly metadata-only. Even when a consumer
  also has content capability, this tool returns a held metadata record with
  no body/envelope/quote and omits paired JID/LID values from the response.
  Existing account, chat, participant and privacy-barrier checks remain in
  place.
- Added a synthetic disposable-SQLite test that exercises the tool with a
  content-capable principal, checks the metadata output for absence of a
  synthetic body and paired identities, and rejects an out-of-scope chat.
- Added a fail-closed Cash read guard for `summary` and `messages`. The
  existing `ADMIN` role is insufficient by itself: an account must also have
  an explicit ID in `ALRIFAI_CASH_SUPER_ADMIN_IDS`. The default (unset or
  empty) denies access; no user, role, or ID was promoted or selected.
- Added focused tests for default denial, explicit allowlisting, rejection of
  `USER`/malformed identities, and guard placement before Cash read queries.
  Cash writes, parsing, posting, ingestion, migrations and domain processing
  were not changed.

### Validation and remaining gates

| Check | Status | Evidence / limit |
|---|---|---|
| Cash authorization test | **NOT RUN** | VS Code test discovery reported no registered controllers; host Node/pnpm are unavailable and no approved isolated Node runner was available. |
| WhatsApp metadata capability test | **NOT RUN** | VS Code test discovery reported no registered controllers; Python environment configuration and container-tool helpers were unavailable. |
| Typecheck, lint, full tests, build | **NOT RUN** | No authorized isolated Node 22 build/test environment was available. |
| Source-to-ingestion-to-Cash reconciliation | **BLOCKED** | Historical counts remain incomparable; no authorized current source/Cash metadata mapping or exact failure/unmatched counts. |
| Super Admin identity/configuration | **BLOCKED** | Owner has not named an existing portal `ADMIN` identity. The new allowlist is not configured in production. |
| Live bridge capability and app authorization | **UNVERIFIED** | These are working-tree changes only; no production service was restarted or deployed. |
| Cash/Vessel isolation in live operation | **UNVERIFIED** | No cross-domain test was run and no live processing was exercised. |

**Current status: DEPLOYMENT BLOCKED.** Before a separate release decision,
set the runtime `ALRIFAI_CASH_SUPER_ADMIN_IDS` only to Owner-designated
existing `ADMIN` IDs; include the required runtime documentation/configuration
change in that release scope. Then run the focused tests and exact-lockfile
typecheck/lint/full tests/build in isolated Node 22 and Python environments.
Production DB grants/views, migration, service restart/deployment, source
reconciliation reads, and any financial operation require their own explicit
authorization. No existing dirty work was reset, staged, or discarded.

## Batch 0.2 — Vessel duplicate qualification update

This section records a later offline qualification; it does not authorize a
production migration or release and does not alter the Cash Freeze.

- `apps/al-rifai/lib/escort-register.mjs` now links a unique, exact
  normalized Mother/Lighter pair match within one day to the existing
  canonical order ID, but marks the new source as a potential duplicate in
  `REVIEW`. It does not confirm, update, or overwrite the canonical row.
  Distinct source messages retain source links, events, and provenance.
- Multiple canonical matches remain ambiguous review with no business key.
  Dates more than one day apart and differing vessel pairs remain distinct.
  WA-01 scope, exact draft matching, group authorization, identity/access
  policy, and Cash behavior are unchanged.
- `apps/al-rifai/tests/escort-register.mjs` adds synthetic coverage for the
  one-day rule, two-day separation, differing lighter, ambiguous candidates,
  retained canonical IDs, source evidence, and replay idempotency.
- Validation: 29 focused synthetic tests passed; targeted ESLint and
  TypeScript checks passed in isolated Node 22.23.3 environments. Full
  frozen-lockfile build/tests and disposable migration-chain validation were
  not run. The `pnpm exec` attempt failed before executing checks because it
  tried writing temporary install state to the read-only source mount; no
  install or source mutation resulted.
- No migration, database, production data, account, role, session,
  authorization/permission, bridge, or deployment was changed. Migrations
  0018 and 0020–0023 remain unapproved for production; 0018 includes contact
  seed/upsert and grants, 0021/0022 include grants/triggers, and 0023 adds
  identity/group-authorizations and alters the event constraint.

**Current decision remains NO-GO for release/deployment.** Exact-lockfile
build/full-suite results, disposable migration verification, authenticated
browser acceptance, and release-path authorization/isolation remain gates.
