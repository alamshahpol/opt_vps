# Source and import manifest

This is a read-only source inventory. It records paths and relationships; it
does not copy source, credentials, database records or WhatsApp content.

## Entry surfaces

| Surface | Existing path | Role in the read-only artifact |
|---|---|---|
| Cash page | `apps/al-rifai/app/cash/page.tsx` | UI contract reference; not copied or executed |
| Cash API | `apps/al-rifai/app/api/cash/[...path]/route.ts` | Authenticated endpoint contract reference |
| Legacy Accounts API | `apps/al-rifai/app/api/operations/route.ts` | Existing historical/search/report contract |
| Assistant API | `apps/al-rifai/app/api/assistant/route.ts` | Existing Cash question/report consumer |
| Legacy Accounts UI | `apps/al-rifai/app/accounts-panel.tsx` | Existing employee statement/filter/export contract |

## Verified import edges

- `app/cash/page.tsx` uses React state/effects, Lucide UI components and the
  `/api/cash/` endpoint family.
- `app/api/cash/[...path]/route.ts` imports `next/server`,
  `lib/cash-portal.ts` and `lib/cash-scope.ts`.
- `lib/cash-portal.ts` uses `pg`, Node crypto/util/fs and the existing
  PostgreSQL host/password-file contract. It contains portal session/profile/
  audit writes; the read-only artifact does not call those mutations.
- `lib/live-cash-read.ts` uses `pg`, Node fs, `lib/operations.ts` and
  `lib/cash-scope.ts`; its pool is configured read-only and is the only live
  projection dependency considered here.
- `lib/cash-source.ts` uses evidence loaders, `db/raw.ts`,
  `accounts-snapshot.ts`, `cash-data.ts` and `live-cash-read.ts`.
- `lib/cash-data.ts` uses `zod`, `vessel-data.ts` and Cash row types from
  `operations.ts` for filtering, grouping, totals and date validation.
- `app/api/operations/route.ts` uses `cash-source.ts` and `cash-data.ts` for
  the legacy Accounts search, employee statements, daily summary and export.
- `app/api/assistant/route.ts` uses `cash-source.ts`, `cash-data.ts` and
  `operations-assistant.ts` for Cash-related answers.

## Reference-only writer/consumer paths

These paths were inspected for boundary completeness but are excluded from
the contract-only artifact because they can advance cursors or write business
records:

- `apps/al-rifai/candidates/identity-review/live-cash.ts`
- `apps/al-rifai/candidates/identity-review/cash-commands.ts`
- `apps/al-rifai/candidates/identity-review/host.ts`
- `apps/al-rifai/candidates/identity-review/stored-history-mcp.ts`
- `apps/al-rifai/lib/cash-portal.ts` mutation handlers
- `apps/al-rifai/db/migrations/`
- `apps/al-rifai/scripts/database.mjs`

## Environment key names

Only names were recorded; no values were read or copied:

- `PGHOST` and the existing PostgreSQL password-file mechanism.
- `ALRIFAI_CASH_ORIGIN`.
- `ALRIFAI_LIVE_CASH_SYNC`.
- `ALRIFAI_LIVE_CASH_INTENT_CAPTURE`.
- Existing owner-reference and manual-posting gate names used by the current
  code.

The artifact does not load `.env.example`, mounted auth files, Bridge-1
tokens, database passwords, owner references or runtime environment files.

## Authoritative contracts retained

- Existing shared PostgreSQL `alrifai` database.
- Existing Cash tables and immutable/source-link constraints.
- Existing `wa-01` Bridge-1 reader/session contract.
- Existing `cashScopeWhere` account/chat scope.
- Existing source-message/block and operation identity rules.
- Existing canonical posting function, referenced but never called here.
