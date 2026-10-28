# Release candidate record — 2026-10-28 (prepared, NOT deployed, NOT enabled)

Unified Super Admin authentication on the Owner's existing Cash Portal credential.
This document records the final verification and release preparation. **Nothing in
this document has been applied to production.**

| Item | Value |
|---|---|
| Source commit the image was built from | `47f7e11` ("docs: unified Super Admin authentication report, cutover and rollback plan") |
| Branch / remote state at build | `main`, fast-forward push `433b1ed..47f7e11` to `git@github.com:arshiyaazim/opt_vps.git` |
| Candidate image | `local/al-rifai:20261028-unified-auth` |
| Image digest (manifest list == image ID) | `sha256:52105520fa0e288a05955bdac9ea7c12daed09f5304d3a3ab6472fc5b8139a97` |
| Platform manifest | `sha256:1b76b666a8abd1487134633168de7aee5c5bf215f91a143e633b6092101b341c` |
| Image config | `sha256:855ad77135c0ce9b985a183b35e4af554a6dff52967e891be398d4629f1b6195` |
| Image build time / size | 2026-10-28T06:27:09+01:00 / 412,133,912 bytes |
| Pre-change backup | `/var/lib/vps/al-rifai/backups/pre-unified-auth-20261028.dump` |
| Backup SHA-256 | `b1f8c8fa9f5061f896ba7e00ed2245cb60e269a93b85be73e7b7f185bc309792` |
| Backup size / shape | 61 MB, `pg_dump -Fc`, 61 table-data sections, restore rehearsed |
| Production image (preserved, unchanged) | `sha256:5f3e2aad0916f66f99c7af13339929ba8e0e041ef904de957c5d2f64244f3b06` |
| Production migration ledger | 30 rows applied, newest `0030_epoch_scoped_register_and_program_writes.sql`; `0033` **not** applied |

## 1. Owner identity verification (read-only, via the Cash application role)

Performed with the authorized Cash connection (`ir_review_runtime`, session forced
`default_transaction_read_only=on`), metadata only. No plaintext credential, hash
value, session token or secret file content was retrieved or printed.

| Check | Result |
|---|---|
| Cash account count | `1` |
| Account id | `81a73b320d9d56c175b48552a648b7405659dc814921bf12be38927f07b72c79` |
| Username / role | `Admin` / `ADMIN` |
| Active / must-change-password | `true` / `false` |
| Password hash scheme / length | `pbkdf2-sha256`, 600,000 iterations, 118 chars |
| Password-hash fingerprint (`md5(password_hash)`) | `e4d99a36533187eecd5f9d4f515f7ca3` — **identical to the recorded baseline** |
| `password_changed_at` | `2026-10-17T00:20:56.635Z` (unchanged) |
| Row version | `2` (unchanged) |
| Newest activity | `2026-10-28T03:33:56.610Z` — account in live use |
| Duplicate usernames (case-insensitive) | none |
| Accounts by role | `ADMIN=1` only |
| `ALRIFAI_CASH_SUPER_ADMIN_IDS` | exactly one id, equal to the account id above |
| Sessions | 24 total, 3 unexpired, all belonging to that single account |

Conflicting Super Admin identities: **none** — one account, one configured id, one
ADMIN role, no duplicate username.

Post-verification re-check (after every rehearsal below) returned the same id,
fingerprint, version and session count, confirming no account or password was
modified at any point.

Known pre-migration limitation: `ir_review_runtime` holds `INSERT` only on
`cash_portal_audit`, so audit history is not readable until `0033` grants `SELECT`
(see §3).

## 2. Authentication verification

### 2.1 Automated suites (isolated Node 22.23.3 container, no production runtime)

| Check | Result |
|---|---|
| Full suite (`tests/*.mjs`, 157 tests) | **156 pass, 0 fail, 1 pre-existing skip** |
| `tests/workflows.mjs` | pass |
| `tests/source-register.mjs` | pass |
| `tests/phase1-unit.mjs` | pass |
| `tsc --noEmit` | pass (exit 0) |
| ESLint over `app lib release tests scripts proxy.ts db components` | 0 errors, 0 warnings |
| `next build --webpack` | pass; `/login`, `/admin`, `/api/auth/[...path]` present |
| Image build (`pnpm typecheck && pnpm lint && pnpm build` inside Dockerfile) | pass |

### 2.2 Runtime rehearsal — candidate image, throwaway clone: 36/36 checks pass

Disposable Postgres 16 restored from the backup above, `0033` applied, throwaway
credentials only, candidate image started on its own network from the same commit.
The Owner's production credential was never used: the clone's row was re-hashed with
a rehearsal-only password under the identical id/username/role.

| Check | Result |
|---|---|
| Health endpoint | 200 |
| Unauthenticated navigation → `302 /login?next=%2Fdashboard` | pass |
| Unauthenticated API → `401` (fail closed) | pass |
| Wrong password → `401 INVALID_CREDENTIALS`, no cookie minted | pass |
| Existing Cash credential accepted on `/login` | 200 |
| Same `__Host-alrifai_cash` cookie name, existing session table | pass |
| Owner resolves as configured Super Admin | `superAdmin: true` |
| `/admin` renders for the Super Admin | 200 |
| Standard user Cash login | 200 |
| Standard user is not Super Admin | `superAdmin: false` |
| Standard user `/admin` → redirect | 307 |
| Standard user cannot list accounts / create an ADMIN / self-escalate | 403 / 403 / 403 |
| `workspace.admin` grant refused | `CAPABILITY_NOT_GRANTABLE` |
| Final active Super Admin cannot be deactivated | `LAST_ADMIN_PROTECTED` |
| Valid capability grant persists | 200 |
| Audit history readable after `0033` | 200 |
| Legacy `validator` Basic accepted in `on` mode | 200 |
| No Basic, no session → denied | 401 |
| Cash portal's own `/api/cash/login` unchanged | 200 |
| Logout revokes the session | 200, then 401 |
| `shadow`: `/login` verifies credential, session does **not** authorise the workspace | 200 / 302 |
| `shadow`: legacy Basic still accepted | 200 |
| `off`: unified endpoints not exposed, legacy guard only, Cash login unchanged | 401 / 401 / 200 |

Conclusion: the existing credential is reused as-is, no new password is required,
no password hash is changed, Cash login still works, and the Admin Panel is enforced
server-side (role + configured id + capability allowlist, never a client claim).

## 3. Migration 0033 readiness

Additive only: adds `capabilities jsonb` and `username_changed_at`, grants
`SELECT` on `cash_portal_audit` to `ir_review_runtime`, and installs a
final-active-admin guard trigger. No user row, hash, session, role or audit row is
modified; no `DELETE` or `UPDATE` grant is added anywhere.

| Rehearsal | Result |
|---|---|
| Restore of `pre-unified-auth-20261028.dump` into throwaway Postgres 16 | exit 0 |
| Restored clone fidelity | 1 user, 24 sessions, 33 audit rows, fingerprint `e4d99a36…` (identical) |
| Apply pass 1 | exit 0 |
| Apply pass 2 (idempotency) | exit 0, only `NOTICE … already exists` |
| Users / sessions / audit row counts after apply | unchanged |
| Password fingerprint after apply | `e4d99a36533187eecd5f9d4f515f7ca3` (unchanged) |
| `capabilities` default `'[]'::jsonb`, `jsonb_typeof = array` | pass |
| `cash_portal_users_capabilities_array` CHECK rejects non-array | pass |
| Guard: demote / deactivate / delete final active ADMIN | blocked with `LAST_ADMIN_PROTECTED` (23514) |
| Guard: harmless update (`display_name`) | allowed |
| Guard: second active ADMIN allows demoting the first | allowed |
| Guard: demoting or deleting the then-final ADMIN | blocked |
| `ir_review_runtime` audit grants before / after | `INSERT` → `INSERT,SELECT` |
| `ir_review_runtime` users grants before / after | `INSERT,SELECT,UPDATE` (unchanged, no DELETE) |
| Documented rollback ladder (drop trigger, drop function, revoke SELECT, drop 2 columns) | exit 0 |
| State after rollback | columns/trigger/function gone, audit grants back to `INSERT`, owner row and 24 sessions intact |

**Not applied to production.** Applying it remains an Owner decision.

## 4. GitHub synchronization

| Item | Result |
|---|---|
| Working tree before push | clean |
| Secret scan over `433b1ed..HEAD` | no credential/token/private-key patterns; only `.env.example` changed, comment-only |
| Push | `git push origin main` → **`433b1ed..47f7e11`** (fast-forward, no force) |
| Local vs remote after push | `0` ahead / `0` behind |

## 5. New candidate image

`local/al-rifai:20261028-unified-auth`
digest `sha256:52105520fa0e288a05955bdac9ea7c12daed09f5304d3a3ab6472fc5b8139a97`,
built from `47f7e11` with BuildKit and the read-only `evidence` build context.
Content spot-check inside the image: `server.js`, `start-private-app.mjs`,
`entry-rules.mjs` with `/admin` and `/api/auth/login` allowed and an unrelated path
denied; `.next/server/app/{login,admin}` present.

The running production image
`sha256:5f3e2aad…` is untouched: `compose.yaml` still pins it, no container was
recreated, and `al-rifai-app-1` remains `Up (healthy)`.

## 6. Exact safe deployment sequence (not started)

Each step is separately approvable and individually reversible. Stop and report on
any deviation.

1. **Re-verify the credential baseline** — rerun the read-only identity check and
   confirm id `81a73b32…c79` and fingerprint `e4d99a36533187eecd5f9d4f515f7ca3`.
2. **Take a fresh backup** — `pg_dump -Fc` from `vps-infra-postgres-1`, record the
   SHA-256, and confirm `pg_restore -l` lists the expected objects.
3. **Apply migration 0033** — promote
   `db/migration-candidates/0033_unified_auth_sessions.sql` into `db/migrations/`
   (source commit), then apply it in production once, using the same mechanism as
   `alrifai_schema_migrations` (`node /app/scripts/database.mjs migrate` inside the
   app container, or an equivalent single transaction plus ledger row whose
   `sha256` equals the file). Verify: column defaults, CHECK constraint, trigger
   presence, `ir_review_runtime` audit grants `INSERT,SELECT`, and unchanged user /
   session / fingerprint values. Rollback ladder is in §3.
4. **Deploy the candidate image in `off` mode** — pin
   `sha256:52105520…` in `compose.yaml`, recreate only the app service, and record
   the deployed digest and commit `47f7e11`. In `off` mode behaviour is identical to
   today: legacy Basic only. Verify `/api/health`, Cash portal login, and that
   `POST /api/auth/login` is not exposed.
5. **Enable `shadow`** — set `ALRIFAI_UNIFIED_AUTH_MODE=shadow` (and
   `ALRIFAI_UNIFIED_ORIGINS` if hosts other than the two defaults are wanted) in
   `/etc/vps/apps/al-rifai/app.env`, restart the app service, then sign in once at
   `/login` with the existing Cash credential. Expected: sign-in succeeds, protected
   pages still demand the legacy credential.
6. **Enable `on`** — set `ALRIFAI_UNIFIED_AUTH_MODE=on`, restart, and use
   `/login` → `/dashboard`. The legacy Basic credential remains valid throughout.
7. **Retire the legacy guard only if, and when, the Owner separately decides to.**

Rollback at any step: set `ALRIFAI_UNIFIED_AUTH_MODE=off` and restart (previous
behaviour exactly, Cash sessions stay valid); re-pin the previous image digest
`sha256:5f3e2aad…` and recreate the app service; migration 0033 is reversible with
the ladder in §3. The `validator` Basic credential is the fallback that keeps the
Owner reachable even if the database is unavailable.

## 7. Remaining Owner approvals

1. Apply migration `0033` in production.
2. Deploy the candidate image `sha256:52105520…` (records digest + commit `47f7e11`).
3. Enable `ALRIFAI_UNIFIED_AUTH_MODE=shadow`, then `on` (each requires an app restart).
4. Approve `ALRIFAI_UNIFIED_ORIGINS` if any host beyond
   `https://alrifai.iamazim.com` and `https://app.al-rifai.iamazim.com` is required.
5. Decide, separately, whether the `validator` Basic guard is ever retired.

Not done and not authorised by this record: production migration, deployment,
restart, mode change, credential change, Cash posting or WhatsApp change.
