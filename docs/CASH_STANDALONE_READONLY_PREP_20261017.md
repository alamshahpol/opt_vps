# AL-RIFA'I Cash Standalone Read-only Artifact

Status: preparation manifest only. This file is documentation; it is not an
executable artifact and does not authorize implementation, deployment or
financial processing.

Date: 2026-10-17 (Asia/Dhaka)

## Boundary and invariants

- Existing `/cash`, `/api/cash`, shared PostgreSQL database, `wa-01`
  Bridge-1, authentication and canonical posting function remain authoritative.
- The first artifact is read-only. It must not post payment, advance a cursor,
  run migrations, send WhatsApp messages, alter runtime flags or write to
  production.
- No secret, password, mounted auth file, bridge store, raw WhatsApp message,
  production record or credential is copied into the artifact or repository.
- No second database, bridge, ledger, posting function or business authority
  is introduced.

## Exact source boundary to inventory

The following are the first-pass source groups. They are protected paths and
are not edited by this preparation step:

- UI/API: `apps/al-rifai/app/cash/`,
  `apps/al-rifai/app/api/cash/[...path]/route.ts`,
  `apps/al-rifai/app/api/operations/route.ts`,
  `apps/al-rifai/app/api/assistant/route.ts`,
  `apps/al-rifai/app/accounts-panel.tsx`.
- Cash/shared libraries: `apps/al-rifai/lib/cash-data.ts`,
  `cash-scope.ts`, `cash-portal.ts`, `cash-source.ts`,
  `live-cash-read.ts`, `operations.ts`, `accounts-snapshot.ts`,
  `evidence.ts`, `evidence-types.ts`, `db/raw.ts`, `db/postgres.mjs`.
- Existing live/manual adapters and their existing dependencies:
  `apps/al-rifai/candidates/identity-review/live-cash.ts`,
  `cash-commands.ts`, `auth.ts`, `contracts.ts`, `repository.ts`,
  `stored-history-mcp.ts`, `host.ts`, `deployment-profile.ts`,
  `lib/history-extraction.mjs` and `lib/history-policy.mjs`.
- Schema contracts to reference, not to run or copy into production:
  `apps/al-rifai/db/migrations/0011_stored_history_foundation.sql`,
  `0012_business_workflows.sql`, `0015_live_owner_accountant_cash.sql`,
  `0016_cash_payment_account_name.sql`, `0017_cash_portal_auth.sql` and
  `0019_cash_lid_employee_master.sql`.
- Build/test contract: `apps/al-rifai/package.json`,
  `pnpm-lock.yaml`, `tsconfig.json`, `next.config.ts`, `Dockerfile`,
  `release/` and `compose.yaml`. These require Owner approval before any
  edit or copy into an implementation repository.

## Read-only artifact task list

| ID | Task | Expected evidence | Status |
|---|---|---|---|
| T0 | Confirm freeze, path guard and approval boundary | no protected edit; approval checklist | Prepared only |
| T1 | Build source/import manifest from the boundary above | paths, imports and contract owners; no secrets | Prepared only |
| T2 | Define read-only adapter interface | SQL read scope, API response types, source scope | Prepared only |
| T3 | Define API parity matrix | login/session/CSRF, summary/filter/export and error contracts | Prepared only |
| T4 | Define disposable test harness | synthetic fixtures, isolated PostgreSQL and no bridge writes | Prepared only |
| T5 | Assemble standalone read-only package | separate non-production artifact, zero writer/cursor/migration calls | Blocked on Owner exception |
| T6 | Execute parity/regression tests | captured command, exit code and evidence; PASS only after execution | Not run |
| T7 | Review and approve any writer-capable transition | exact paths, deployment/restart and financial boundary | Not authorized |

## Required API contract checks

The extracted read-only artifact must preserve the current contracts for:

- `POST /api/cash/login`: credentials in, session user/CSRF and secure cookie
  out; no credential values in fixtures or logs.
- `GET /api/cash/me`: authenticated user and refreshed CSRF.
- `GET /api/cash/summary?q&method&from&to`: scoped counts, rows, posting
  linkage, source metadata and filters.
- `POST /api/cash/logout`, `PATCH /api/cash/profile`,
  `POST /api/cash/password` and admin `/api/cash/users` behavior, including
  origin, CSRF, role and forced-password rules.
- Existing `/api/operations` and `/api/assistant` consumers used by the
  legacy Accounts/assistant surfaces.

## Dependency and environment contract

The artifact may reference existing contracts but must not copy their values:

- PostgreSQL: existing `alrifai` database, current role/read permissions,
  `PGHOST` and existing password-file mechanism.
- Cash origin and mode keys: `ALRIFAI_CASH_ORIGIN`,
  `ALRIFAI_LIVE_CASH_SYNC`, `ALRIFAI_LIVE_CASH_INTENT_CAPTURE`, existing
  owner reference keys and the existing manual-posting gate.
- Bridge: existing `wa-01` reader/session and mounted control-socket contract;
  no token, SQLite store or raw message export.
- Runtime: Node `>=22.13.0`, pnpm `11.25.0`, existing lockfile and current
  package dependency graph. Dependency installation/build changes require
  separate approval.

## Disposable/non-production setup

- Use only an isolated disposable PostgreSQL/schema already approved for
  qualification, populated with synthetic records and synthetic source IDs.
- The artifact itself must not run `db:migrate`, `db:import` or any migration
  runner. If a disposable schema must be prepared, that is a separate,
  explicitly approved test setup action outside production.
- Replace Bridge-1 with a synthetic reader fixture or recorded metadata-only
  test double. Do not mount the real Bridge-1 socket/store or read raw messages.
- Use synthetic accounts/session fixtures. Do not use production credentials,
  owner references, password hashes or employee/payment records.
- Capture only exit codes, contract results, hashes of synthetic fixtures and
  zero-write assertions.

## Planned tests (not executed in this step)

- `node --experimental-strip-types tests/cash-intake-safety.mjs`.
- Existing workflow/replay/database/UI suites selected by the manifest:
  `tests/workflows.mjs`, `tests/business-workflows.mjs`,
  `tests/replay-metrics.mjs`, `tests/identity-review-postgres.mjs`,
  `tests/ui-lifecycle-entry.tsx` and `tests/ui-lifecycle-browser.py`.
- Static checks that the artifact has no imports of production auth files,
  bridge stores, raw evidence or migration execution paths.
- API parity for login/session/CSRF/origin, filters, search, date range,
  employee statements, source traceability, export and error responses.
- Read-only assertions: no `INSERT`, `UPDATE`, `DELETE`, posting-function
  call, cursor update, migration call or WhatsApp send.
- Synthetic duplicate/conflict checks for source message + block identity,
  operation identity, manual versus WhatsApp provenance, Employee ID versus
  payout mobile, wrong sender/recipient/group/route and concurrent readers.
- Desktop/mobile UI checks using synthetic data only. No live acceptance claim
  is made until the test actually runs.

## Approval gates and rollback

- Before T5: Owner exception for the exact implementation paths, intended
  behavior, validation, deployment/restart scope and financial write boundary.
- Before package/dependency/config changes: separate protected-path approval.
- Before GitHub repository creation or push: explicit repository/access
  approval.
- Before any live flag, cursor, permission, deployment, restart, migration,
  payment write, posting, movement or WhatsApp action: separate action-specific
  approval.
- If non-production preparation fails, discard only the un-deployed artifact
  and preserve the existing application/database. Do not auto-revert an
  approved change and do not touch the production baseline.

## Current preparation result

- This manifest is the only artifact created by this step.
- No executable standalone package, dependency change, test fixture, database,
  runtime, bridge, deployment, GitHub repository or credential was created or
  changed.
- Runtime/database freshness is unverified in this session; no test result is
  labeled PASS without execution evidence.
