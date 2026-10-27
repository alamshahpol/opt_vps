# T5 read-only test plan

Status: plan and static readiness only. No test in this file is labeled PASS
unless it is executed and its exit code/evidence is captured.

## Safe checks prepared

1. Confirm the staging directory contains only the four documentation files
   listed in `README.md`.
2. Scan the staging files for secret-like values, raw phone/message content,
   mounted credential paths and production evidence paths.
3. Compare the source/import manifest with the current Cash files using
   read-only `rg`/path checks.
4. Confirm no executable entry point, migration command, database client,
   Bridge-1 socket path or posting-function call exists in the artifact.
5. Check local availability of the existing Node/pnpm test toolchain without
   installing anything.

## Planned disposable tests

Only after a separately approved disposable setup exists:

- Run the existing focused safety suite:
  `node --experimental-strip-types tests/cash-intake-safety.mjs`.
- Run the selected existing workflow/replay/database/UI suites without real
  credentials or Bridge-1 access.
- Use synthetic PostgreSQL rows and synthetic source IDs only.
- Use a metadata-only synthetic reader, never the real Bridge-1 store/socket.
- Assert zero INSERT/UPDATE/DELETE, zero cursor movement, zero posting-function
  calls, zero migration calls and zero outbound-message calls.
- Compare the read-only API response fields for authentication, scope,
  filters, search, date range, employee statements, summaries, source links
  and export.
- Test wrong sender/recipient/group/route, Employee ID/payout separation and
  duplicate/conflict identities using synthetic inputs.
- Test desktop/mobile rendering only against synthetic data.

## Current execution result

- Dependency installation: NOT RUN.
- Node/pnpm availability: checked separately; no installation attempted.
- Existing test execution: NOT RUN.
- Browser execution: NOT RUN.
- Disposable PostgreSQL qualification: NOT RUN.
- Production/runtime/database/Bridge-1 checks: NOT RUN.

No PASS claim is made for any unexecuted check.
