# AL-RIFA'I persistent recovery tooling — Stage C1 / C2 preparation
## Authorization and execution boundary
Only these eight files and their two parent directories were approved for creation.
C2 adds fixed-target orchestration with synthetic process/database transport.
The OS/database execution boundary remains unconditionally locked. No real
creation, restore, cancellation, termination or cleanup transport is available.
The Python supervisor defaults to plan-only and rejects every other mode, even if
an operator supplies a purported approval. New execution authorization alone does
not switch this implementation on: a separately reviewed adapter revision is required.
The Node verifier is passive. Its CLI prints plan metadata only. Exported comparison
functions accept in-memory frames; they do not open connections or spawn commands.

## Provenance
baseline-attestation.json and baseline-catalog.json are RECONSTRUCTED evidence.
They are not recovered original Stage B machine-readable artifacts.
The original preserved artifact is the current-baseline custom dump at the pinned
path/checksum. Stage B linked its baseline to exported snapshot 00000003-00001C1A-1.
That transaction ended; its snapshot token cannot be reused.
C0 reconstructed rows from checksum-verified private evidence and recorded migration
timestamps and read catalog metadata separately. C1 reconstructs the sanitized
catalog from unchanged SQL sources and recorded PostgreSQL definition rendering,
without a database connection. Its canonical SHA-256 matches the Stage B result.
No private snapshot payload is stored in this package.

## Reused logic
evidence-readonly.mjs adapts only evidence() and expectedSnapshots() from the pinned
scripts/database.mjs. Explicit evidence-directory/manifest inputs replace ambient
defaults. All six evidence files, including seed-source.ts, are byte/checksum checked.
assertExactSnapshots checks every field, extras and duplicates.
verifier.mjs retains verify-state.mjs table/hash order without importing either
application executable or production-hardcoded pool.

## Serialization contract
State: for each attested table in order, SELECT * ORDER BY id; append UTF8 table name
and JSON.stringify(rows) to the same SHA-256 stream with no extra delimiter.
Use physical column/property order. Ledger applied_at is a Date serialized to UTC
ISO format. Empty operational arrays are included.
Snapshots: SHA-256 of JSON.stringify(all ordered snapshot rows), preserving payload
strings exactly. Manifest contentHash holds a chunk count, not a payload digest.
Catalog: SHA-256 of JSON.stringify(catalog), with keys columns, constraints, indexes,
triggers, function, ownership, grants in that order. Each uses the exact read-plan
projection, field order and SQL ordering. Fixed public search_path and matching
libc en_US.utf8 collation preserve catalog rendering/order.
No database OID, name or observation time enters these content hashes.
No real owner/grant/payload differences are normalized away.
Framed psql output uses explicit labels and one JSON line per projection; embedded
JSON string newlines stay escaped. Only ledger timestamp transport decoding changes
representation to the original Node driver's Date behavior.

## Read-only plan and supplementary checks
read-plan.sql is never executed by this C1 package. Future collection requires explicit
fixed container/socket/port/user/target, -X, -w, ON_ERROR_STOP and startup read-only mode.
The same transaction checks actual target/user/cluster/version/read-only state before
table reads. The plan ends with rollback. Its SHA-256 is pinned in verifier and attestation.
Supplementary checks cover database owner/locale/ACL, public schema owner/ACL, protection
function owner/security/language, valid/ready indexes, relation ACL/RLS and extensions.
A live verifier must also qualify app-target/session boundaries and production unchanged
state through separately reviewed read-only supervision. No live adapter exists here.

## Offline testing
Node built-in modules and Python standard library only; no dependency installation.
With a host Node runtime:
    node offline-tests.mjs
    python3 -B restore-supervisor.py --self-test
    python3 -B restore-supervisor.py
Node tests read private evidence to reconstruct a golden baseline entirely offline.
They do not connect to PostgreSQL. If host Node is unavailable, use the existing app
container's Node runtime with a no-file stdin bundle:
1. Read the eight source files on the host.
2. Encode evidence-readonly.mjs as a JavaScript data URL.
3. Replace only verifier's relative evidence import with that URL and encode verifier.
4. Replace offline-tests' two relative imports with those URLs.
5. Supply the original eight file texts as JSON on stdin and run Node --input-type=module
   -e <bundled-test-source> -- --bundle via docker exec -i al-rifai-app-1.
No mount/config/image/service change is required. Do not print the private evidence.
Run Python checks with -B; syntax validation uses ast.parse/compile in memory, never
py_compile or imports that generate __pycache__.

## Supervisor and failure control
proposed_plan() returns prospective argv arrays only; it executes nothing.
offline_simulate() is a pure mock lifecycle. It cannot authorize or perform real work.
Future preflight must independently recheck archive checksum, cluster/container/image,
versions, target absence, application target, permissions, health, maintenance,
approved window/capacity limits and fresh production fingerprints.
Future restore: one session, full archive, single transaction, exit on error; no clean,
create, filtering, trigger disabling, parallel jobs or ACL suppression.
Archive statements reset statement_timeout/lock_timeout: PGOPTIONS timeouts are not
a reliable restore bound. Independent monitoring is required.
Resource limits have no approved defaults. Owner must approve free-space/memory,
elapsed-duration and monitoring interval limits; health degradation stops work.
match_restore_session() is a pure predicate: exact cluster, target, unique application
name, session user, local client, captured PID/backend_start and start window.
It returns DESIGN_ONLY_NO_SIGNAL. Zero/multiple/changed matches prohibit signaling.
Future cancellation and any termination fallback need separate explicit authorization
and server-side cessation confirmation. No retry or fallback to production.
Restore failure leaves the created database; single-transaction changes normally roll
back. Connection loss around commit is uncertain until read-only inspection.
No automatic cleanup, cutover, restart, role setup or off-host transfer.

## Roles and system recovery limits
Existing vps_pg_admin is write-capable/superuser. Reviewed fixed read-only SQL narrows
this execution; it does not permanently restrict that role. A restricted role adds
privilege-level protection but requires separate creation/grant approval and explicit
ACL-overlay accounting. This implementation creates no role and assumes no overlay.
A database qualification is not host/disk/cluster recovery. Roles/globals, private
evidence/documents, secrets, source/images/config, mounts and off-host recovery remain
separate requirements. Financial corrections are not ordinary database rollback.

## Next approval gates
1. Review these exact file hashes, offline results, reconstruction provenance and limits.
2. Authorize a separately reviewed live-adapter revision/read-only integration scope.
3. Authorize Stage C explicitly: exact archive/checksum/target, commands, attended window,
   resource limits, monitoring/cancellation scope and protected diagnostic artifacts.
4. Stop at results review; retain qualification target/evidence.
5. Cleanup requires separate exact-object approval.
Stage C restore execution remains NOT AUTHORIZED; checkpoint remains NOT QUALIFIED.

### Reproducible container-based offline runner
Run this from the VPS host; it creates no files and sends only tooling text on stdin.
Private evidence is read inside the existing read-only evidence mount, not copied.
```sh
python3 -B - <<'PY'
from pathlib import Path
import base64, hashlib, json, subprocess
root = Path('/opt/vps/infra/recovery/al-rifai')
names = ['verifier.mjs','read-plan.sql','evidence-readonly.mjs',
         'baseline-attestation.json','baseline-catalog.json','offline-tests.mjs',
         'restore-supervisor.py','README.md']
bundle = {name: (root / name).read_text() for name in names}
baseline = json.loads(bundle['baseline-attestation.json'])
bundle['_upstreamSHA256'] = {
    path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for path in baseline['upstreamSourceSHA256']
}
if bundle['_upstreamSHA256'] != baseline['upstreamSourceSHA256']:
    raise SystemExit('STOP: upstream source mismatch')
def url(text):
    return 'data:text/javascript;base64,' + base64.b64encode(text.encode()).decode()
evidence = url(bundle['evidence-readonly.mjs'])
verifier = url(bundle['verifier.mjs'].replace(
    "'./evidence-readonly.mjs'", json.dumps(evidence)))
tests = bundle['offline-tests.mjs'].replace(
    "'./evidence-readonly.mjs'", json.dumps(evidence)).replace(
    "'./verifier.mjs'", json.dumps(verifier))
result = subprocess.run(
    ['docker','exec','-i','al-rifai-app-1','node','--input-type=module',
     '-e',tests,'--','--bundle'],
    input=json.dumps(bundle), capture_output=True, text=True, timeout=45)
if result.returncode:
    raise SystemExit('OFFLINE TEST FAILURE: private diagnostics suppressed')
print(result.stdout.strip())
PY
```
The runner launches an offline Node process only. PostgreSQL is never invoked.

Supplementary inventory also rejects extra public functions, user schemas,
unexpected relation kinds and altered application/admin role attributes.

## Preserved Stage C1 checkpoint (before C2 edits)

- `README.md`: `f13c3b171e2d8f0a580f87cd496f9ad24c7f26a7e68f90199e5dd5ba30d47f9c`
- `baseline-attestation.json`: `436d0029fc078042f9ac88e4802483e654445cae4f60022766a047cc7ed99b05`
- `baseline-catalog.json`: `b5e3d64c2124b0c2b3fdac772f0a129165c10ecb72cd4d938620f954c4dd2394`
- `evidence-readonly.mjs`: `10737d01e38c194e5770b5419323f26795f8bf55ede4d15de8d0fe25d31c34be`
- `offline-tests.mjs`: `e89ec4e6be24cc8572fd016197304920f90035ead669aa24b3456ffdfeb281eb`
- `read-plan.sql`: `d3b4a25e19bff52afeb380312ee70097a398cd989bd44a982ceb15d0c6d0d749`
- `restore-supervisor.py`: `1ed1adb58be4e7acd146e93b6f1776e710f392c225ca03687e85daa2e711a8af`
- `verifier.mjs`: `84c005c753a0cd0cf749fdabe9110dd519a0b010e21e35ba1076592306247a79`


## Stage C2 architecture and verification
Only restore-supervisor.py, offline-tests.mjs and README.md were revised.
The original five other files, provenance and three fingerprints are unchanged.
FixedTargetAdapter reuses proposed_plan(), validate_mock_preflight() and
match_restore_session(). It validates exact argv arrays and a fresh fixed process
environment (PATH, LANG, LC_ALL, TZ), with no inherited PG*, Docker or loader values.
The future container-side environment must separately be validated; Docker exec
inherits container configuration, so host environment sanitation alone is insufficient.
All transport in this revision is MockTransport: command calls record labels and
consume synthetic outcomes. No OS process or database is invoked by the adapter.
launch_live() unconditionally raises C2_LIVE_TRANSPORT_LOCKED. No CLI, environment,
approval record or LIVE_EXECUTION_ENABLED flag can enable it. A source revision and
separate live execution approval are needed. This is not authentication of owner
approval: mock records test scope validation only.

Preflight validates fixed identities, missing/changed archive observations, target
absence/session exclusion, versions, application target, health, capacity, window,
configuration and production fingerprints. Archive observations are mock collector
facts, not proof that an archive was read. Monitoring validates finite numerical
limits/samples, monotonic elapsed time and sampling gaps, CPU, memory, disk, WAL,
locks and health. No limits have operational defaults or owner approval.
Mock restoration is one attempt, with no retry, fallback or cleanup. Failure retains
the target; creation errors may leave a target, and restore/connection exceptions
leave commit outcome unknown. Raw stdout/stderr and arbitrary exception messages
are discarded. Cessation is never claimed from a process failure.
Cancellation requests independently require cancel/terminate scope and exact cluster,
target, application, user, local client, unique PID/backend-start and start window.
Requests return mock actions only. No automatic cancellation or termination occurs.

Run C2 tests without private evidence or database access:
    python3 -B restore-supervisor.py --self-test
    node offline-tests.mjs --synthetic
The Python report retains the 40 synthetic C1 supervisor cases and adds C2 cases.
The Node synthetic branch uses the existing comparator/decoder with fabricated rows;
it does not replay the historical private-evidence golden baseline. The original
50 C1 golden test results remain the preserved checkpoint. If Node is unavailable
on the host, the documented stdin bundle may be run in the existing Node container,
adding --synthetic after --bundle. This runs a test process only, no database client.
No test fixture files or __pycache__ should be created.

## Historical C2 live transport gaps (superseded by C3 components below)
There is no executable OS transport, live observation collector, concurrent monitor,
archive descriptor binding, Node comparator bridge or live signal/cessation adapter.
C2 samples model monitoring during restore; the mock command returns immediately.
A real monitor must run concurrently, use a monotonic clock, enforce stale-sample
limits and recheck identity atomically with signaling to avoid PID-reuse races.
Before launch, open the exact archive without following symlinks, hash/stat the same
file descriptor and stream that descriptor to restore; independently verify the
archive content/TOC and container-side environment, local authentication and versions.
Future owner authorization must bind the reviewed revision, exact archive/target,
actions, start/end window, all numerical limits, diagnostic destination/permissions
and cancellation policy. Mock boolean window/permission facts are not real checks.
Production reads need a separate reviewed fixed read-only plan: read-plan.sql excludes
production. Reuse verifier.mjs for target frames; do not duplicate its hashing or
change the reconstructed baseline to pass a mismatch. Frame collection and a Node
bridge can be added within an approved supervisor revision; if any immutable file
needs changes, request exact additional scope before editing.

## Proposed eventual qualification procedure (not executable or authorized here)
1. Review exact adapter/SQL hashes and authorize live transport completion separately.
2. Review offline transport, concurrency and signal-race tests; approve read-only
   integration separately. Retain plan-only default and an independent execution gate.
3. Approve exact Stage C target/archive/container/image/cluster identities, commands,
   attended start/end window, responsible operator and positive resource thresholds.
4. Approve production pre/post read-only queries, target/session observations,
   permissions, archive validation and protected diagnostic location/retention.
5. Freshly collect health, version, configuration/start-time, target absence and
   production fingerprints. Stop on drift, insufficient resources or maintenance.
6. Start independent monitoring before creation; create only the pinned qualification
   database, then stream the full pinned archive in one restore session with existing
   --single-transaction/--exit-on-error/--role/--no-owner arguments. No clean/create,
   filtering, parallel jobs, ACL suppression or trigger disabling.
7. On pressure/failure, follow the separately approved exact-session cancel policy.
   Termination fallback needs explicit approval; confirm server-side cessation.
   Never retry or infer rollback after connection loss near commit.
8. Collect guarded read-only target frames; use the unchanged Node comparator and
   supplementary checks. Recheck production fingerprints, health/config/start times
   and absence of application sessions to the target. No cutover or restart.
9. Retain target and protected evidence and stop for owner review. Cleanup and any
   transfer, role/grant changes, deployment or cutover require separate approval.

Owner approvals still needed: live transport source changes, any additional files,
read-only integration/production SQL, and actual Stage C execution. Execution approval
must specify minimum free bytes, minimum available memory, maximum duration, polling
interval, maximum CPU percent/WAL bytes/lock seconds, cancellation/termination scope,
attended window and diagnostic access/retention. Disk/WAL measurement definitions
and health criteria must be agreed before real monitoring can enforce these limits.
STAGE_C_RESTORE_EXECUTION = NOT_AUTHORIZED
RECOVERY_CHECKPOINT_STATUS = NOT_QUALIFIED

## C2 offline verification results

- Retained C1 supervisor: 40/40 PASS.
- C2 adapter synthetic cases: 73/73 PASS.
- C2 Node synthetic verifier cases: 20/20 PASS.
- Python syntax, default plan-only and six forbidden CLI modes: PASS.
- Zero database connections, real restore commands or cancellation/termination signals.
- No private evidence read by C2 tests; no additional fixture files created.
- Historical C1 50-case golden evidence verification was preserved, not rerun.

## Preserved C2 checkpoint before C3 implementation

| `README.md` | `d8a4a3e67231926a5836f39cb29ceb650a7e183afe7eebbc93979fe5790aa2e5` |
| `baseline-attestation.json` | `436d0029fc078042f9ac88e4802483e654445cae4f60022766a047cc7ed99b05` |
| `baseline-catalog.json` | `b5e3d64c2124b0c2b3fdac772f0a129165c10ecb72cd4d938620f954c4dd2394` |
| `evidence-readonly.mjs` | `10737d01e38c194e5770b5419323f26795f8bf55ede4d15de8d0fe25d31c34be` |
| `offline-tests.mjs` | `b2691518a2b06a3bbd2c533dc34b00c2d94e8982bae14ccdf1cdfabc517ddd9c` |
| `read-plan.sql` | `d3b4a25e19bff52afeb380312ee70097a398cd989bd44a982ceb15d0c6d0d749` |
| `restore-supervisor.py` | `631a6176e558087d919d660890bbb409fc2643c2353aa5d968554437ce9a998b` |
| `verifier.mjs` | `84c005c753a0cd0cf749fdabe9110dd519a0b010e21e35ba1076592306247a79` |


## Stage C3 dormant implementation
C3 modifies only restore-supervisor.py, offline-tests.mjs and this README. The five
immutable files are pinned and checked before SQL projection reuse and comparison.
The verified C2 checkpoint above is preserved as the before-edit inventory.
No new files, directories, roles, services or dependencies were created.

BoundedTransport provides fixed-argv, shell-free OS transport with nonblocking stdin,
stdout and stderr, bounded output, monotonic timeouts, broken-pipe handling and
monitor watchdog checks. The OS backend calls launch_live() unconditionally before
Popen. No entrypoint calls run_components(). Archive, observation, signal and evidence
OS backends also call that lock first. Tests inject memory-only backends; never Docker,
PostgreSQL, application services or runtime evidence files. Arbitrary argv, JSON
approval records and environment variables cannot unlock any concrete OS boundary.

The existing FixedTargetAdapter now also has run_components(): preflight -> production
observation -> monitoring -> one creation/restore -> unchanged target comparator ->
production comparison -> configuration/start-time checks -> retained summary. Its
real dependencies are all locked. The mock-only C2 lifecycle remains for regression
coverage. No retry, fallback, automatic signals, cleanup or restart is performed.
On failure, retain the target, never claim cessation, and report unknown commit when
the restore process did not conclusively complete. Client-pipe closure is not server
cessation. Diagnostic failure also prevents successful qualification.

PreflightCollector uses fixed read-only PostgreSQL identity/target/session queries
and an injected host/application collector. The dormant host collector inspects exact
containers, health/config/start times, source/config hashes, versions, disk/memory
and aggregate host CPU. Maintenance clearance and reference hashes must come from
an independently approved attended procedure. Mock window/config booleans are not
owner authentication. Docker inspection data and configuration bytes remain private
in memory and never enter the diagnostic writer. Host env is fixed; container commands
use env -i with fixed paths and explicit PGOPTIONS for read-only/UTC/timeouts.

ArchiveDescriptor opens the pinned archive using no-follow directory/file descriptors,
checks protected ownership/mode, hashes and rewinds that descriptor, then rechecks
metadata while streaming and checks a second stream hash at completion. Parent path
components must be root-owned and not group/world writable. Path replacement cannot
redirect the descriptor. In-place mutation cannot be absolutely prevented by a read
file descriptor: protected input during the run is required; detected drift stops
qualification, potentially after restore has received bytes. Archive header/hash checks
are not a full semantic TOC qualification; read-only integration must confirm the pinned
custom archive metadata with the installed pg_restore client.

ConcurrentMonitor runs independently with monotonic time, initial readiness, threshold,
sampling-gap/stale checks and worker failure detection. The main process pump checks
its watchdog while operations run. A stuck collector makes liveness checks fail; no
worker retry or signal follows automatically. Metrics are aggregate host CPU (0-100),
MemAvailable bytes, available bytes on the PostgreSQL filesystem, total files in pg_wal
(not just restore-generated WAL), and active lock-waiting query age (a conservative
proxy for wait duration). Owner approval must accept these measurement definitions
and positive limits. A dead/stalled monitor causes STOP, not a claim of backend rollback.

The NodeComparator bridges bounded private SQL frames to unchanged verifier exports.
Target mode uses decodeFrames/verifyCollected and checksum-verified evidence; production
mode uses a separately guarded production-only plan and fingerprints(), preserving UTC
Date serialization, property order and payload bytes. Production fingerprints are
compared to the pinned baseline before restore and to that fresh observation afterward.
Only counts/hashes/status are allowed out of the bridge; raw frames are never diagnostics.
production_sql() reuses immutable projection text, not its qualification guard. The
original read-plan.sql remains byte-identical and production-excluding.

capture_restore_session(), cancellation_request(), signal_sql() and CancellationObserver
require exact cluster/database/application/user/local-client/PID/backend-start/window,
unique matching sessions, separately scoped cancel/terminate approval, server-side
predicate revalidation and bounded absence observations. PID reuse or a replacement
restore backend prohibits claiming cessation. READ ONLY does not prohibit PostgreSQL
signal functions; their concrete backend has a separate unconditional lock. This code
reduces check/signal races but does not claim atomic PID-plus-start signaling. A live
signal policy must explicitly resolve/accept that residual risk. Cessation observation
alone does not prove commit or rollback. No live cancellation test was performed.

DiagnosticEvidence allowlists bounded metadata, suppresses arbitrary errors/fields and
uses an injected filesystem during testing. The dormant writer requires an existing
root:root 0700 /var/lib/vps/al-rifai/recovery-evidence directory and exclusive 0600 files
qualification-summary.json / qualification-failure.json. No mkdir, overwrite, deletion
or cleanup is implemented. Partial evidence on I/O failure is retained. This path and
its exact artifacts need separate owner approval before use; none exist from C3 work.

### Next read-only integration scope (separate approval, not executed)
Authorize a reviewed integration entrypoint revision while keeping launch_live and all
mutation/signal boundaries locked. Inspect only pinned PostgreSQL/app container identities,
versions, health/config/start times; read the protected archive to validate descriptor,
checksum and pg_restore metadata; run exact production/admin read-only guarded queries
with rollback; sample host/cluster resources; exercise production Node serialization
and bounded private evidence verification. Do not create an absent qualification target.
Target-frame collection is conditional on its already-existing exact identity and
separate explicit approval. No cancellation/termination, restore, roles, service changes
or cleanup. Separately approve diagnostic paths/artifacts or keep integration diagnostics
in memory. Return exact proposed SQL/argv hashes, limits and results before further gates.

The global lock currently also rejects read-only OS transport. Read-only integration
therefore needs a separately reviewed entrypoint/backend gate permitting only the fixed
read-only command registry; implementation approval alone does not grant that permission.
Live restore later requires its own reviewed activation revision, exact archive/target,
attended owner launch, resources, signals/cessation policy and retention approval. No
CLI/env/JSON payload provides independent owner authorization. Root can modify root-owned
code; this is an operational approval boundary, not privilege-level isolation against root.
Reconstructed baseline provenance remains unchanged. Database qualification does not
establish host/disk/globals/secrets/off-host recovery.

### C3 offline verification results

- C1 supervisor regressions: 40 PASS.
- C2 supervisor regressions: 73 PASS.
- C3 Python component/lifecycle cases: 125 PASS.
- Node synthetic verifier/actual bridge cases: 30 PASS.
- Default plan-only and six forbidden CLI modes: PASS.
- Dynamic concrete-backend lock checks and AST entrypoint/shell checks: PASS.
- No Docker/PostgreSQL/application contact, private evidence reads, runtime evidence files or live signals.
- Historical C1 golden private-evidence tests were preserved, not rerun.

## C3 checkpoint before C4 edits

- `README.md`: `f6402f0b0f3bfb5763738b38b972e00d971aee07ab75034922e28bddf268a033`
- `baseline-attestation.json`: `436d0029fc078042f9ac88e4802483e654445cae4f60022766a047cc7ed99b05`
- `baseline-catalog.json`: `b5e3d64c2124b0c2b3fdac772f0a129165c10ecb72cd4d938620f954c4dd2394`
- `evidence-readonly.mjs`: `10737d01e38c194e5770b5419323f26795f8bf55ede4d15de8d0fe25d31c34be`
- `offline-tests.mjs`: `18ceef9ce3d0adfc342bfb267d411bf48512d30d016f8b29edc14b089e54e19b`
- `read-plan.sql`: `d3b4a25e19bff52afeb380312ee70097a398cd989bd44a982ceb15d0c6d0d749`
- `restore-supervisor.py`: `8ff3776be189dd9e48360b0d823b7f19edddfcc2aa769952ad2af872909f5a7f`
- `verifier.mjs`: `84c005c753a0cd0cf749fdabe9110dd519a0b010e21e35ba1076592306247a79`

## C4 read-only gate implementation (offline only)

This section supersedes earlier live integration proposals. Only the supervisor,
synthetic tests and this README were modified. Five immutable files retain their
C3 hashes above. Baseline provenance remains RECONSTRUCTED.

`--mode plan` remains the default. `--mode readonly` calls `launch_readonly()`,
which unconditionally raises C4_READONLY_INTEGRATION_NOT_AUTHORIZED before wiring.
`launch_live()` remains a single unconditional C2_LIVE_TRANSPORT_LOCKED raise.
Flags, environment, JSON approval and synthetic fixtures never unlock either gate.
Concrete OS, archive and observation adapters independently enforce the read-only
lock. Tests inject memory-only adapters. No runtime evidence files are created.

The distinct ReadOnlyTransport reuses only the bounded process pump, not the generic
restore command registry. Its allowlist excludes target SQL, creation, restore,
signals, generic commands, cleanup and restart. Exact argv lists and sanitized
process environments must match, as must pinned SQL bytes. Comparator packets may
request only production mode. Production observation is limited to two attempts;
any failure stops the single integration attempt. There is no automatic retry.

### Fixed command and SQL manifests

Argv SHA-256 hashes use UTF-8 JSON arrays with compact comma/colon separators and
ensure_ascii=False; SQL hashes cover exact UTF-8 bytes, including whitespace.
The Node -e source is NODE_BRIDGE, reused unchanged from C3.

- `identity` argv SHA-256: `2c3f0d0b13d7c0f2ef0056f575e5a1591ce9a2ca4b3302f94e8f516be4689856`
  Exact argv: `["/usr/bin/docker","exec","-i","63b70ddf47f20b7836f860d7819acc273a3e66b2bd96febbde0cbf1339ac6bd6","/usr/bin/env","-i","PATH=/usr/local/bin:/usr/bin:/bin","LANG=C","TZ=UTC","PGOPTIONS=-c default_transaction_read_only=on -c timezone=UTC -c statement_timeout=15000 -c lock_timeout=5000","/usr/local/bin/psql","-X","-qAt","-w","-h","/var/run/postgresql","-p","5432","-U","vps_pg_admin","-d","postgres","-v","ON_ERROR_STOP=1"]`
- `resources` argv SHA-256: `2c3f0d0b13d7c0f2ef0056f575e5a1591ce9a2ca4b3302f94e8f516be4689856`
  Exact argv: `["/usr/bin/docker","exec","-i","63b70ddf47f20b7836f860d7819acc273a3e66b2bd96febbde0cbf1339ac6bd6","/usr/bin/env","-i","PATH=/usr/local/bin:/usr/bin:/bin","LANG=C","TZ=UTC","PGOPTIONS=-c default_transaction_read_only=on -c timezone=UTC -c statement_timeout=15000 -c lock_timeout=5000","/usr/local/bin/psql","-X","-qAt","-w","-h","/var/run/postgresql","-p","5432","-U","vps_pg_admin","-d","postgres","-v","ON_ERROR_STOP=1"]`
- `production` argv SHA-256: `d46e5b6cf8167b3294a40752388c048a13a860b75dd422c1c4f2866068808fd7`
  Exact argv: `["/usr/bin/docker","exec","-i","63b70ddf47f20b7836f860d7819acc273a3e66b2bd96febbde0cbf1339ac6bd6","/usr/bin/env","-i","PATH=/usr/local/bin:/usr/bin:/bin","LANG=C","TZ=UTC","PGOPTIONS=-c default_transaction_read_only=on -c timezone=UTC -c statement_timeout=15000 -c lock_timeout=5000","/usr/local/bin/psql","-X","-qAt","-w","-h","/var/run/postgresql","-p","5432","-U","vps_pg_admin","-d","alrifai","-v","ON_ERROR_STOP=1"]`
- `compare` argv SHA-256: `6f99665c43b029d99e87bc0f7d0dd7d84533b957fac458d93e42c9971f0ff478`
  Exact argv: `["/root/.vscode-server/cli/servers/Stable-07f806f999227108933c2e30515b26eecc1fda74/server/node","--input-type=module","-e","\nimport {readFileSync} from 'node:fs';\nimport {decodeFrames,verifyCollected,fingerprints,TABLES,CATALOG_KEYS,assertSupplemental,TARGET,CLUSTER,ARCHIVE_SHA} from 'file:///opt/vps/infra/recovery/al-rifai/verifier.mjs';\nimport {readEvidenceSet,expectedSnapshots,assertExactSnapshots} from 'file:///opt/vps/infra/recovery/al-rifai/evidence-readonly.mjs';\nexport function comparePacket(p){\n const baseline=JSON.parse(readFileSync('/opt/vps/infra/recovery/al-rifai/baseline-attestation.json','utf8'));\n if(p.mode==='target'){\n  const collected=decodeFrames(p.frames);\n  const expected=expectedSnapshots(readEvidenceSet(baseline.evidence.directory,baseline.evidence.files));\n  return verifyCollected({target:TARGET,cluster:CLUSTER,archiveSha:ARCHIVE_SHA},baseline,collected,expected);\n }\n if(p.mode!=='production')throw Error('MODE');\n const labels=['identity',...TABLES.map(t=>'table:'+t),...CATALOG_KEYS.map(k=>'catalog:'+k),'supplemental'];\n const fs=p.frames.trimEnd().split('\\n').map(line=>JSON.parse(line));\n if(fs.length!==labels.length||fs.some((f,i)=>f.label!==labels[i]||!Array.isArray(f.rows)))throw Error('FRAMES');\n if(fs[0].rows.length!==1)throw Error('IDENTITY');\n const id=fs[0].rows[0];\n if(id.database!=='alrifai'||id.cluster!==CLUSTER||id.user!=='vps_pg_admin'||id.version!=='16.15'||id.readOnly!=='on')throw Error('IDENTITY');\n const rows=Object.fromEntries(TABLES.map((t,i)=>[t,fs[1+i].rows]));\n const catalog=Object.fromEntries(CATALOG_KEYS.map((k,i)=>[k,fs[1+TABLES.length+i].rows]));\n for(const r of rows.alrifai_schema_migrations){\n  if(typeof r.applied_at!=='string'||!/^\\d{4}-\\d{2}-\\d{2}T.*(?:Z|\\+00:00)$/.test(r.applied_at))throw Error('TIMESTAMP');\n  r.applied_at=new Date(r.applied_at);if(!Number.isFinite(r.applied_at.valueOf()))throw Error('TIMESTAMP');\n }\n const last=fs.at(-1);if(last.rows.length!==1)throw Error('SUPPLEMENTAL');assertSupplemental(last.rows[0]);\n return {status:'OBSERVED',readOnly:true,fingerprints:fingerprints(rows,catalog)};\n}\ntry {\n const bytes=readFileSync(0);if(bytes.length>64*1024*1024)throw Error('SIZE');\n const result=comparePacket(JSON.parse(bytes.toString('utf8')));\n console.log(JSON.stringify(result));\n} catch {console.log(JSON.stringify({status:'BLOCKED',code:'COMPARATOR_FAILURE'}));process.exitCode=1;}\n"]`
- `inspect-pg` argv SHA-256: `d93abd43e1d7dea1df0d402aa1762107fb97448643294ed702f614702106e327`
  Exact argv: `["/usr/bin/docker","inspect","--format","{{json .}}","63b70ddf47f20b7836f860d7819acc273a3e66b2bd96febbde0cbf1339ac6bd6"]`
- `inspect-app` argv SHA-256: `22dd19193a79de5b1970cea5600e19ed2cf824c4ddcb9cb5436cd357da4adf66`
  Exact argv: `["/usr/bin/docker","inspect","--format","{{json .}}","al-rifai-app-1"]`
- `version` argv SHA-256: `43c66ce38edbb36555d7a2dabe87c4cb53e100b00a24fbbeb820877c118f0876`
  Exact argv: `["/usr/bin/docker","exec","63b70ddf47f20b7836f860d7819acc273a3e66b2bd96febbde0cbf1339ac6bd6","/usr/local/bin/psql","--version"]`
- `archive-version` argv SHA-256: `200ef421f9d34c9e42f2c7354c7ad4f5ce8715e105bf37691e80b3726a7d94b5`
  Exact argv: `["/usr/bin/docker","exec","63b70ddf47f20b7836f860d7819acc273a3e66b2bd96febbde0cbf1339ac6bd6","/usr/local/bin/pg_restore","--version"]`
- `archive-list` argv SHA-256: `5a514020b03ac16a6dff1e3836eb79463d0099e2312189a7acea3ef280b8288b`
  Exact argv: `["/usr/bin/docker","exec","-i","63b70ddf47f20b7836f860d7819acc273a3e66b2bd96febbde0cbf1339ac6bd6","/usr/bin/env","-i","PATH=/usr/local/bin:/usr/bin:/bin","LANG=C","TZ=UTC","/usr/local/bin/pg_restore","--list"]`
- `node-version` argv SHA-256: `27f7e03bbe9532c30d6c4ae7de55d79e5ef5740dbfa0a32b65b51b85ee8f488a`
  Exact argv: `["/root/.vscode-server/cli/servers/Stable-07f806f999227108933c2e30515b26eecc1fda74/server/node","--version"]`
- `identity` SQL SHA-256: `d6258868ed0eb899e205fcb5c001de2251b3b8058a695720798e93ab4d848164`; source: observation_sql()
- `resources` SQL SHA-256: `e4d1a5f192b46975203f80affe6527087a80d20d7281153684dc14fc01348eaf`; source: resource_sql()
- `production` SQL SHA-256: `282196103d2d9117e36bfa2221855f2597f7fda87659ffc9f54ecd1ee30e04bb`; source: production_sql()

### Bounds and resource readiness

At most two database processes run simultaneously (nonblocking bounded semaphore).
SQL statement timeout is 15 seconds; lock timeout is 5 seconds; each process is
capped at 20 seconds and the owner-selected observation window at 120 seconds.
Versions have 1 KiB stdout bounds; production frames 32 MiB; other stdout and
all stderr 64 KiB. Comparator input is limited to 64 MiB. Raw inspect output,
configuration bytes, production frames and private observations stay in memory;
results contain only fixed status codes, fingerprints and TOC digest.

No resource default authorizes integration. Supply all seven limits explicitly:
minimumFreeBytes, minimumAvailableMemoryBytes, maximumCpuPercent, maximumWalBytes,
maximumLockSeconds, monitorIntervalSeconds and maximumRestoreSeconds. Also supply
startupSeconds, acquisitionSeconds, freshnessSeconds, processSeconds and
durationSeconds. maximumRestoreSeconds must equal durationSeconds; acquisition
must not exceed freshness, which must not exceed monitorIntervalSeconds.

Monitoring starts independently and waits for its first valid acquired sample.
Age is measured from acquisition start, never receipt; slow acquisition, stale
samples, dead workers, malformed session observations and breached limits stop
execution. Sampling uses half the configured monitor interval. Disk availability
and MemAvailable use bytes; CPU uses host percentage between samples; WAL uses
bytes of LSN advance; lockSeconds is the existing query-age proxy, not exact lock
wait duration. CPU acquisition is serialized across monitor and preflight calls.

### Archive and failure semantics

Secure open traverses directories without following symlinks. The pinned
root-owned 0600 regular descriptor, size, PGDMP magic and full initial checksum
are validated before listing; device/inode/size/timestamps/ownership/mode are
checked during reads and after listing. The dedicated `pg_restore --list` command
has no database argument and reads the same descriptor. Early stdin closure is
allowed only for this listing operation: exit zero, bounded output and metadata
integrity remain mandatory. No full second stream hash is claimed after early
closure. TOC must identify CUSTOM, dump version 1.15-0 and 34 entries.

Every identity, authentication, checksum, metadata, SQL/argv pin, monitor,
comparator, timeout or output failure stops without retry, fallback, signals or
cleanup. Process pipes are detached; server/remote process cessation is not
asserted. Administrative READ ONLY is transaction policy, not privilege-level
isolation of the superuser vps_pg_admin. Local trust authentication and loaded HBA,
real timing, Docker exec cessation, Node version stability and filesystem I/O
latency remain live-integration risks. Metadata checks cannot establish an atomic
snapshot against a malicious concurrent privileged writer. No restore
qualification, globals recovery, disk recovery or production cutover is claimed.

### Proposed separately approved read-only procedure

1. Owner reviews this exact checkpoint, manifests, fixed container/image/cluster,
   postgres and alrifai observations, vps_pg_admin role, socket /var/run/postgresql
   port 5432, archive identity and the private observation scope.
2. Owner explicitly approves all resource/timing limits, UTC start/end window,
   reviewed application source/config/mount hashes and maintenance clearance.
   These configuration values are consistency checks, not independent authorization.
3. A separate implementation approval is required for a bounded operational
   authorization mechanism replacing only the read-only unconditional lock. No
   executable live procedure is enabled by this checkpoint; --mode readonly stops.
   Restore launch_live must remain unchanged and independently locked.
4. After that reviewed change and its offline verification, obtain separate live
   read-only execution approval. Reverify eight hashes immediately before entry.
5. Execute one readonly_entrypoint with the exact reviewed config/reference/window:
   immutable pins; admin/host preflight; executable versions; descriptor checksum
   and bounded TOC listing; production fingerprint before; independent resource
   monitor; production fingerprint after; admin/host identity recheck; monitor close.
   No qualification-target connection, create, restore or signal operation occurs.
6. On any failed check, stop and report generic failure/cessation unknown. Do not
   cancel, terminate, retry, clean up or restart. Owner separately decides observation
   or intervention. Successful read-only comparison remains NOT_QUALIFIED.

Evidence is in-memory only at this stage. Owner must separately approve any future
persisted evidence directory, root:root 0700 directory/0600 files, sanitized schema,
retention period, access and deletion. No location or retention is activated here.

### C4 offline verification

Supervisor regressions: C1 40, C2 73, C3 125, C4 96 PASS.
Node synthetic verifier/actual bridge: 38 PASS. Dynamic CLI gate and AST checks
confirm plan-only defaults, unconditional restore/read-only locks and no shell
execution. Historical private-evidence golden tests were preserved, not rerun.
No Docker, PostgreSQL, application service, archive listing or live signal executed.
