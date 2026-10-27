# Cash API contract preservation matrix

This matrix describes the current contract to preserve. No endpoint was
called by this artifact and no API implementation was changed.

## `/cash` portal API

| Method/path | Current contract | T5 treatment |
|---|---|---|
| `POST /api/cash/login` | Username/password input; authenticated user, CSRF value and secure session cookie output | Contract recorded; no real credentials used |
| `GET /api/cash/me` | Authenticated user and refreshed CSRF value | Contract recorded; synthetic session only in future test |
| `GET /api/cash/summary?q&method&from&to` | Server-owned Cash scope; instruction/posting counts, rows, source metadata and filters | Read-only parity target |
| `POST /api/cash/logout` | Deletes the current portal session | Not called; mutation excluded |
| `PATCH /api/cash/profile` | Updates portal profile fields after origin/CSRF/session checks | Not called; mutation excluded |
| `POST /api/cash/password` | Changes password after current-password and CSRF checks | Not called; mutation excluded |
| `GET /api/cash/users` | Admin-only user listing | Not called; mutation/admin surface excluded |
| `POST /api/cash/users` | Admin-only portal-user creation | Not called; mutation excluded |
| `PATCH /api/cash/users/:id` | Admin-only portal-user update | Not called; mutation excluded |
| `POST /api/cash/users/:id/password` | Admin-only password reset | Not called; mutation excluded |

## Legacy related contracts

- `GET /api/operations` remains the legacy Accounts/Employee statement,
  search, date-range, daily-summary and CSV/export contract.
- `POST /api/assistant` remains the existing Cash question/report consumer.
- These contracts must remain available until an approved replacement proves
  equivalent field names, filters, scope, source labels and `canWrite:false`
  behavior.

## Required parity fields

The read-only projection must preserve, where present:

- instruction/posting IDs and source/command references;
- source time, method, purpose and amount in integer minor units;
- Employee ID mobile separately from payout mobile;
- posting status and source traceability metadata;
- server-owned `wa-01` / `Cash Payment` scope;
- search, method, inclusive date-range filters and employee grouping;
- no claim that an instruction is an independently verified external receipt.

## Prohibited T5 behavior

The artifact must not invoke `INSERT`, `UPDATE`, `DELETE`, a migration runner,
the cursor-update query, a Cash posting function, a WhatsApp send tool or a
production authentication/password path.
