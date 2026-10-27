# WhatsApp MCP installation and three-number pairing plan

Prepared 10 October 2026, Asia/Dhaka. **Planning only: no clone, dependency installation, pairing, send, migration or restart has been performed.**

## Authority and source review

Follow [VPS_MAP.md](docs/VPS_MAP.md). Keep the owner's selected repository: `git@github.com:arshiyaazim/whatsapp-mcp.git`. The connected GitHub account successfully returned its README, go.mod, pyproject.toml, auth.go and the opening/schema portion of main.go. This resolves the earlier public-fetch failure; no repository substitution is recommended.

Sources: [WhatsApp README](https://github.com/arshiyaazim/whatsapp-mcp/blob/main/README.md), [Go dependencies](https://github.com/arshiyaazim/whatsapp-mcp/blob/main/whatsapp-bridge/go.mod), [Python dependencies](https://github.com/arshiyaazim/whatsapp-mcp/blob/main/whatsapp-mcp-server/pyproject.toml), [authentication](https://github.com/arshiyaazim/whatsapp-mcp/blob/main/whatsapp-bridge/auth.go).

README blob SHA observed: `b0109d022961d9232c0ee2eb16cdfb173cca6611`. This is a **file blob SHA, not a deployable commit**. Local Al-Rifa'i README records an earlier inspected commit `895404542017f34a900f9f572a5497c275a96440`; recheck the repository HEAD and select an exact commit at implementation time.

Conflict: apps/al-rifai/README.md proposes application-owned integration/session paths. This new shared-service plan follows VPS_MAP instead: code under services/whatsapp, state under /var/lib/vps/whatsapp. Do not create both deployments. Do not update the deployed map until installation actually changes deployed ownership/state.

## Verified requirements and behavior

- Go module requires Go 1.26.0; SQLite uses mattn/go-sqlite3 and requires CGO and a C build toolchain.
- Python requires >=3.11; prepare dependencies with uv and the repository lockfile. Exact toolchain/image versions and digests must be recorded after a successful build.
- FFmpeg is optional for audio conversion/media previews. Transcription additionally needs an explicitly configured provider or whisper.cpp/model; exclude it from the initial installation.
- Go creates `store/whatsapp.db`, `store/messages.db` and media relative to its working directory. Python database variables do **not** relocate Go storage.
- REST uses a bearer token and exact loopback Host checks. File tokens are owner-only; upstream first-start output may print sensitive setup material.
- MCP defaults to stdio; HTTP/SSE exists but has no built-in authentication. Use stdio initially.
- Incoming calls are recorded; outgoing calls are not reliably observable. Historical sync is incomplete in some circumstances. Do not promise complete archives.
- Sending tools exist; the selected fork must not be assumed to enforce DJNgoma's preview/confirmation behavior. Application authorization must be enforced separately.

## Proposed paths and isolation

| Item | Path or name |
| --- | --- |
| One source checkout | /opt/vps/services/whatsapp/source |
| Build/Compose/operator wrappers | /opt/vps/services/whatsapp/ |
| Account configuration | /etc/vps/services/whatsapp/wa-01.env, wa-02.env, wa-03.env |
| State | /var/lib/vps/whatsapp/wa-01/store, wa-02/store, wa-03/store |
| Approved upload staging | /var/lib/vps/whatsapp/wa-01/outbox, wa-02/outbox, wa-03/outbox |
| Backup staging | /var/backups/vps/whatsapp |
| Compose project | vps-whatsapp |
| Bridge services | whatsapp-wa-01, whatsapp-wa-02, whatsapp-wa-03 |
| MCP registrations | whatsapp-wa-01, whatsapp-wa-02, whatsapp-wa-03 |

Build one pinned image and reuse it for three separate processes. Each container has a separate approved nonroot UID, token and account-only mounts. Workdir `/runtime`; mount that account's store at `/runtime/store` and outbox at `/runtime/outbox`. Select unused UIDs after inspecting the host; do not reuse app UID 10001 automatically. Root-owned configuration 0600, directories 0700, umask 077 and only deliberate service-specific access. No sessions, QR values, numbers, passwords or media in source/plans.

## Ordered implementation procedure

1. Re-read map and local handoff, check source destination is absent or inspect its existing checkout, existing containers/networks, disk/RAM, tooling and UID availability. Do not overwrite an existing directory.
2. Verify existing SSH access without modifying protected /root/.ssh. Use strict host-key verification; do not disable it. If GitHub is not already trusted, verify its published host fingerprint before arranging trust. A connector's access does not prove host SSH-key access.
3. Future clone command, after the destination check:

   ```bash
   git clone git@github.com:arshiyaazim/whatsapp-mcp.git /opt/vps/services/whatsapp/source
   git -C /opt/vps/services/whatsapp/source rev-parse HEAD
   ```

   Record HEAD, review the diff from any previous audited commit, pin the deployment to that exact commit. Check repository AGENTS instructions before edits. No recurring automatic git pull.
4. Use a multi-stage Linux image: Go 1.26+ builder with compiler/CGO, Python >=3.11 and a pinned uv version. Run `go mod download`, `go mod verify`, bridge tests and `go build`; prepare Python with `uv sync --locked` and the supported dev extra in the test stage. Run pytest and Ruff checks. Copy the compiled bridge and prepared Python environment into the runtime image. Do not replace host Python or install global pip packages. Verify build toolchain, package availability and Linux SQLite compatibility rather than guessing success.
5. Prepare inactive Compose with three bridge services, no `ports`, no Docker socket, read-only rootfs where compatible, tmpfs for temporary files, account-only writable state, capability drops and bounded logs. Provisional per-instance budget: 1 CPU, 512 MiB, 128 PIDs; measure history/MCP/media bursts before adopting final limits. No daemon restart or resource changes to existing services.
6. Prefer initial bridge/MCP co-location: Go listens on its existing container loopback port 8080; launch the account's Python stdio process through an operator wrapper using `docker compose exec -T` into that same container. This preserves loopback Host validation and requires no bridge bind patch or host-published port. Keep code/interpreter paths absolute; the operator's Docker privilege must not be given to the app or an AI runner.
7. Create restricted runtime/configuration locations at implementation time. Set per-account `WHATSAPP_DEVICE_NAME`, `WHATSAPP_BRIDGE_PORT=8080`, `WHATSAPP_DB_PATH=/runtime/store/messages.db`, `WHATSMEOW_DB_PATH=/runtime/store/whatsapp.db`, `WHATSAPP_API_URL=http://127.0.0.1:8080/api`, `WHATSAPP_MEDIA_ROOTS=/runtime/outbox`, `WHATSAPP_MCP_TRANSPORT=stdio`, `WEBHOOK_ENABLED=false`, `WHATSAPP_AUTO_DOWNLOAD_MEDIA=false`. Generate separate tokens privately or securely capture upstream file-token setup; never paste their output into chat. MCP Python must inherit the corresponding configuration, not another account's environment.
8. Pair wa-01 interactively with its phone; verify then enable unattended restart. Repeat wa-02 and wa-03 sequentially. Register MCP processes separately. Read-only-first access requires a tested tool restriction/wrapper if upstream has no read-only switch; merely asking an agent not to send is not an access boundary.
9. Update VPS_MAP only after recording actual image/commit, ownership, mounts, network and recovery procedure. Leave Al-Rifa'i feeds disabled until their separate integration is ready.

## Pairing checklist for each account

Confirm the intended phone is active and the operator has it. Start only that bridge, show its latest terminal QR in the secure operator terminal, open WhatsApp > Linked Devices > Link a Device and scan. Verify the authenticated native account identity matches the intended number in a private check; verify the recognizable linked-device label. Record only the nonsecret account alias and verification result in documentation. Restart the same service and verify it reconnects without a new QR. Then read a small chat sample. Pairing is not permission to send messages.

The selected fork's verified flow is QR pairing; no phone-code pairing is promised. Optional full-history pairing must be chosen **before first pairing**, and verified against current CLI documentation. Do not delete/re-pair an existing store to obtain history automatically. Never run two bridges against one store or copy a session between numbers.

## Later application access

Only when Al-Rifa'i requires REST/webhooks, attach authorized consumers to vps-backend. Review a narrow bind-address and exact service-host allowlist adaptation or a private authenticated gateway; retain bearer auth/Host checks, never publish a host port. Network membership alone is not authentication. Webhook receiver derives account from trusted configuration and validates the matching X-Bridge-Token; upstream's header is a shared secret, not a cryptographic body signature. Pairing phase needs no app/PostgreSQL connection.

## Acceptance, backup and rollback

Verify all three identities, no cross-account reads, missing/wrong-token rejection, inappropriate Host rejection, confinement of media paths, reconnect after restart/recreation, bounded logs and no host-published bridge/MCP ports. Run synthetic webhook/reconciliation tests before live app ingestion. A permitted test send requires an explicit account/recipient/content and must not be included in read-only validation.

Stop the chosen bridge and all its MCP writers for a coordinated backup of the full store including hidden/journal files, configuration and required media; alternatively qualify a consistent online SQLite backup method for every DB plus media/session coordination. Never blindly copy running SQLite files. Encrypt backups and copy off-host; select retention/media budgets before cleanup. Test restore in an isolated nonconnecting environment; do not run cloned linked sessions concurrently. Roll back image/configuration while preserving state; an upstream schema upgrade may require restoring the matching pre-upgrade store, not just an older binary. PostgreSQL backup ownership stays with vps-infra.

See [WhatsApp schema](db-schema-whatsapp-plan.md), [Al-Rifa'i schema](db-schema-al-rifai-plan.md), [AI schema](db-schema-deepseek-herness-plan.md) and [integration guide](integration-use-plan.md).

## Gate C verified qualification — 10 October 2026

GATE: C
STATUS: Offline qualification complete; pilot PARTIALLY QUALIFIED pending deployment and live acceptance.
WHAT WAS VERIFIED: Pinned multi-stage Docker build; go mod download/verify, go vet, go test ./..., Go build; uv sync --locked with dev extra; Ruff lint/format; 171 Python tests; 42 network-disabled runtime acceptance checks. Real FFmpeg conversion, actual MCP SDK stdio relay, full 20-tool registration (17 original plus call retrieval/typing/history), read-only denial, cross-account credentials, policy revocation, shutdown cleanup and independent service launcher passed.
SOURCE COMMIT: 895404542017f34a900f9f572a5497c275a96440 (main, origin git@github.com:arshiyaazim/whatsapp-mcp.git). Local reviewed patches remain uncommitted; baseline alone does not describe the image.
FILES CREATED/MODIFIED: Source security/runtime/permission helpers, broker and supervisor, tests, pinned Dockerfile and entrypoint, client relay; inactive services/whatsapp/compose.yaml; qualification evidence; existing WhatsApp/schema/integration plans and repository README. Full inventory and hashes below.
SERVICES STARTED/CHANGED: Disposable isolated qualification containers only, removed afterward. No deployed WhatsApp service, AL-RIFA’I or vps-infra changes.
SQLITE STATE: Only disposable tmpfs fixtures; messages.db has chats/messages/calls; whatsapp.db has 17 dependency-owned tables. No real sessions, messages or runtime stores created. Offline initialization executes schema migration helpers only against disposable databases. Complete actual schema is recorded, not inferred from README.
POSTGRESQL CHANGES: NONE. No access, DDL, roles, migrations or ingestion.
SECURITY TEST RESULTS: 42 PASS; absent/wrong/master/cross-account consumer tokens rejected, Host checks enforced, forbidden direct MCP calls denied, media symlink escape denied in unit tests, private DB modes and exclusive store lock verified, REST loopback-only, no public MCP, no QR/token log leakage in tested paths. Broker temporary-credential shutdown race found and fixed, then re-tested.
RISKS: Live pairing, reconnect, synchronization load, message delivery, media retrieval from WhatsApp, transcription accuracy and real call rejection are NOT TESTED. Sampled offline peak ~218 MiB and 24 PIDs; 512 MiB / 1 CPU / 128 PIDs is provisional. Whisper/local recognition model is not included or qualified. Legacy standalone source compatibility remains, while the secured image requires policy; unauthorized direct process launch is outside the consumer boundary. Full off-host paired-session restore is NOT TESTED.
ROLLBACK PLAN: Gate C has no production activation. Retain pinned baseline and patch inventory; remove only explicitly identified qualification artifacts if later authorized. Never delete sessions. Deployment rollback must preserve stores and use matching pre-upgrade consistent backup if a schema downgrade is necessary.
NEXT ACTION: Gate D isolated wa-01 creation and unpaired startup only.
OWNER APPROVAL REQUIRED: Gate D. Gate E pairing remains separately gated.

Image reference: `sha256:e1e4376c08cc37d1c31691f56d284099ee165f48cb12bc39751d245dafdf933f` (local immutable image/index ID). Image config digest: `sha256:a525064a09a1a2ccf35c02fb5bc8144369180f4a81b0fa796216fac27b122f72`. No registry publication claimed. Toolchains: Go 1.26.9, CGO/GCC build environment; Python 3.12.15; uv 0.10.0; FFmpeg 5.1.9. Base manifests pinned in Dockerfile; Debian package snapshot pinned. Repository lockfiles unchanged.

[Build evidence](services/whatsapp/qualification/final-build.log), [runtime results](services/whatsapp/qualification/offline-results.json), [schema](services/whatsapp/qualification/sqlite-schema.json), [source hashes](services/whatsapp/qualification/source-sha256.json), [working tree](services/whatsapp/qualification/working-tree-status.txt), [inactive Compose](services/whatsapp/compose.yaml).

### Feature classification and limits

| Feature | Classification | Evidence / remaining qualification |
|---|---|---|
| Contacts and identity resolution; chat/context/message retrieval | EXISTING AND VERIFIED | Unit tests and actual stdio fixture reads; unverified LIDs not treated as phone numbers; ambiguous native IDs require chat context |
| Text sending, quoted replies, reactions, read receipts | EXISTING AND VERIFIED | Existing implementation and mocked tests retained; live effects NOT TESTED and not authorized |
| Image/document/video sending | EXISTING AND VERIFIED | Existing helpers and permission/media path tests; live effects NOT TESTED |
| Voice sending | EXISTING AND VERIFIED | Real FFmpeg conversion and mocked REST path; live delivery NOT TESTED |
| Media retrieval and preview | EXISTING AND VERIFIED | Existing helpers/tests and containment qualification; live retrieval NOT TESTED |
| Audio transcription | EXISTING BUT NOT YET TESTED | Tool retained; provider paths tested with mocks; real engine/model accuracy NOT TESTED |
| Incoming call detection/history | EXISTING AND VERIFIED | Source event persistence, SQLite catalog and actual MCP fixture read; live incoming call NOT TESTED |
| Webhook integration and history synchronization | EXISTING AND VERIFIED | Source and mocked tests; administrator disabled in pilot; live integration NOT TESTED |
| SQLite persistence and full MCP registration | EXISTING AND VERIFIED | Actual catalogs, private files, 20 tools, consistent stopped disposable restore |
| REST typing and bounded reply orchestration | EXISTING AND VERIFIED | Endpoint retained; pure callback tests verify approval/order/delay/final cleanup; live presence NOT TESTED |
| Consumer capabilities / independent stdio launcher | EXISTING AND VERIFIED | MCP invocation plus REST enforcement, revocation and real client lifecycle |
| Active call rejection endpoint / calls.respond | REQUIRES IMPLEMENTATION | Actual pinned dependency implements RejectCall; bridge does not expose it; not inferred from received CallReject events |
| Durable automatic customized call replies / policy administration | REQUIRES IMPLEMENTATION | Offline eligibility/dedup/cooldown helpers tested; no worker or durable control tables activated |

### Exact Gate D runtime proposal

Use project `vps-whatsapp`, service `whatsapp-wa-01`, the immutable image above and `service --wait-unpaired`. Allocate verified-free UID/GID 10002 only after rechecking. Create private account-specific store/outbox/control directories under `/var/lib/vps/whatsapp/wa-01` and private policy under `/etc/vps/services/whatsapp`. No phone/account public identifiers. Initially issue only scoped read grants. No send authorization is implied. Private Unix-socket relay supplies stdio without client Docker privileges; assign a narrow socket-access group and traversal permissions without exposing store/outbox or globally changing permissions. Broker socket is group-accessible; credentials remain mandatory. Default 0700 account parents must be reconciled with the approved client traversal policy at deployment.

Read-only rootfs, dropped capabilities, no Docker socket, no published ports, loopback REST, independent dedicated network, bounded logs and provisional resource limits. No app/PostgreSQL dependency. No webhook or automatic download activation. Runtime and secrets paths are deliberately absent until Gate D. Gate E must select history requirements and private QR socket before first pairing.

### Backup and recovery procedure

Stop the account service and verify both bridge and broker/MCP writers exited. Back up the entire account store including whatsapp.db, messages.db, all WAL/journals, session files, required media, private configuration and permission policy. Record image/configuration/source manifest with the backup. Encrypt with an owner-controlled key and transfer off-host to access-controlled storage; establish retention and key recovery before relying on it. Restart only the original session through its approved gate. Restore into isolated offline state with no external network; verify SQLite integrity, schemas and file ownership. Never start a cloned linked session concurrently. Gate C verified only a stopped synthetic-schema restore, not a paired-session, encrypted/off-host or disaster recovery test. Existing PostgreSQL backup authority stays unchanged.

## Gate D deployed-state evidence — 10 October 2026

GATE: D
STATUS: COMPLETE — wa-01 running unpaired; pilot PARTIALLY QUALIFIED pending Gate E/F.
WHAT WAS VERIFIED: 26 runtime checks passed, including pinned image, private account mounts/files, scoped REST auth and Host restriction, empty transport and unpaired device state, loopback-only bridge listener, authenticated MCP initialization/read-only tool listing/direct write denial, no tested QR/token log leakage and unchanged healthy protected services.
SOURCE COMMIT: 895404542017f34a900f9f572a5497c275a96440 plus Gate C qualified local patches; no source/build changes in Gate D.
FILES CREATED/MODIFIED: Created private wa-01 state/configuration and scoped reader credential, nonlogin UID/GID 10002; activated existing Compose definition; added qualification/gate-d-verify.py and gate-d-results.json; updated this existing plan and docs/VPS_MAP.md with verified facts. No application/infra files modified.
SERVICES STARTED/CHANGED: Only vps-whatsapp / whatsapp-wa-01, dedicated network vps-whatsapp_whatsapp-private; restart count zero. AL-RIFA’I and PostgreSQL container IDs/start timestamps unchanged, healthy.
SQLITE STATE: Canonical wa-01 private native stores created; zero paired devices and zero chats/messages/calls. No customer data or fabricated native records inserted. Schema initialization belongs to native bridge/dependency only.
POSTGRESQL CHANGES: NONE.
SECURITY TEST RESULTS: 26 PASS, [evidence](services/whatsapp/qualification/gate-d-results.json). MCP owner reader exposes 12 authorized tools; no write grant. Socket and scoped credential access currently restricted to root operator; future consumer onboarding requires only deliberate credential/socket access, never Docker privileges. Docker embedded DNS uses its normal private 127.0.0.11 listener in addition to bridge 127.0.0.1:8080; no public listener.
RISKS: Gate E pairing, real account identity, persistent paired reconnect, real read-only sample, synchronization load and paired-session/off-host restore are NOT TESTED. No MCP consumer application registration was assumed. Restart policy remains no pending paired acceptance. No wa-02/wa-03 created.
ROLLBACK PLAN: Stop only whatsapp-wa-01; preserve account store, config and credentials. Do not delete sessions or Docker volumes, perform global cleanup or downgrade native schemas without a matching backup.
NEXT ACTION: Gate E privately identify account/phone availability and select history synchronization requirements, then approved private QR pairing and read-only validation. No outbound sending, webhook or PostgreSQL ingestion authorization implied.
OWNER APPROVAL REQUIRED: Gate E pairing. Stopped here before pairing.

Owner-operated stdio command (no credential values in arguments):

```sh
python3 /opt/vps/services/whatsapp/source/mcp-client.py --socket /var/lib/vps/whatsapp/wa-01/control/mcp.sock --token-file /etc/vps/services/whatsapp/wa-01-reader.token
```

Run through a compatible stdio MCP client; this is not a public endpoint. Current ancestors and credential are root-restricted, so unprivileged application access is intentionally not provisioned. Media download permission may write native media files but grants no WhatsApp send/receipt action.

## Gate E2 live acceptance — 10 October 2026

GATE: E2
STATUS: PASS — wa-01 read-only pilot QUALIFIED for tested scope; recovery/load limitations remain.
Pairing: PASS; owner used private SSH terminals and confirmed scan/authentication. Agent did not initiate QR generation.
Correct account identity: PASS — owner explicitly confirmed intended account privately. No phone/JID recorded in report.
Linked-device label: PASS — owner confirmed VPS wa-01.
Normal History Sync: default full-history flag false/omitted; no backfill requested. Phone determines coverage; transport projection can omit unsupported/contentless records. No complete archive claim.
Chats/messages stored: 723 chats / 14,271 messages at acceptance snapshot. Earliest stored timestamp 2025-01-11 06:03:41 UTC; latest 2026-10-10 09:53:09 UTC. These are message timestamps, not ingestion timestamps; counts are not final.
Session persistence: PASS — one persisted device before/after transition; both SQLite integrity checks passed.
Reconnect without QR: PASS — temporary pairing process stopped gracefully; verified released lock and preserved store before normal service startup; original Compose container then authenticated and connected without QR.
Read-only MCP retrieval: PASS — authenticated MCP protocol initialization, contacts, two chats and two messages; private results excluded from evidence.
Unauthorized sending blocked: PASS — write tools hidden; direct send RPC denied; REST send/reaction/receipt/typing/history requests denied before execution. No actual outgoing WhatsApp message sent by acceptance actions.
Network isolation: PASS — dedicated account network, loopback REST and no published REST/MCP ports; no vps-backend connection.
AL-RIFA’I/PostgreSQL unchanged: PASS — original container IDs/start timestamps unchanged; both healthy. No PostgreSQL access/writes or application ingestion.
Exact runtime: vps-whatsapp-whatsapp-wa-01-1 running, same immutable Gate C image, service --wait-unpaired, restart count zero. Temporary pairing container no longer running. Only normal bridge owns store lock.
Modified configuration: NONE. Existing permissions, read grants, disabled webhooks/automatic downloads/content logging, image and Compose command retained. Session/history changed naturally through approved owner pairing and native sync. Only existing map/plan documentation and nonsecret qualification evidence updated.
Errors/risks: no ERROR lines in normal-runtime logs. Two MCP warning lines came from deliberate unauthorized send-tool calls (the SDK reports unlisted tool metadata); invocation was denied. No QR/scoped/master token observed in inspected normal-runtime logs. Sustained history/media load, complete historical coverage and encrypted off-host paired-session restore remain NOT TESTED. Restart policy remains no; an operator must start the account after host/container failure. Normal transport acknowledgments are distinct from user read receipts; no read-receipt permission was enabled.
Ready for continued operation: YES, within existing read-only scope. No wa-02/wa-03, automation, transcription grant, outbound grant, webhook or AL-RIFA’I integration enabled. No next-gate work performed.
Evidence: [Gate E2 results](services/whatsapp/qualification/gate-e2-results.json); verification script in the same qualification directory contains no customer records or credentials.

## Gate E3 session protection and stability — 10 October 2026

GATE: E3
STATUS: PARTIAL — available read-only checks complete; backup and disaster recovery BLOCKED.
Session backup: BLOCKED; owner confirmed no existing encryption key and instructed no unencrypted backup, new key, container stop/restart or configuration change. Canonical backup directory inspected empty; no backup created. Native store inventory: paired SQLite plus private bridge token and exclusive lock, approximately 14 MiB at preflight; no WAL/journals or downloaded media found then. Future consistent backup must include complete store, any later media/WAL/journals, required account configuration and scoped credentials, using stopped writers or an explicitly qualified consistency method. Never blindly copy active databases.
Encryption verification: BLOCKED. Encryption utilities alone are not an established recoverable key policy. No private key/passphrase generated, exposed or invented; no decryption/inventory verification claimed.
Off-host backup: PENDING. Disaster recovery: BLOCKED; no safe restore or off-host transfer was performed.
Restart policy: no -> no. Proposed unless-stopped only after verified encrypted backup, competing-process check and separate owner approval. Compose/image/network/mounts/permissions unchanged.
Controlled restart: NOT RUN. E3 reconnect without QR: NOT TESTED; E2 verified reconnect previously. Existing container start time remained 2026-10-10T09:52:22.930150826Z and restart count zero throughout E3.
SQLite integrity: PASS. Exclusive store lock: PASS. Correct persisted account identity unchanged: PASS (comparison only, no identity recorded).
Read-only MCP initialization/contact/chat/limited message retrieval: PASS. Unauthorized sending blocked: PASS; direct forbidden MCP calls and protected REST writes denied before execution. No actual message sending or artificial WhatsApp traffic. Webhooks, automatic media download, read receipts, reactions, typing and automatic replies were not enabled.
Network isolation: PASS; existing private network and container-loopback REST only, no published REST/MCP port.
Stability observation: 601.7 seconds, 21 healthy authenticated connection samples, zero failed samples/disconnects/restarts, zero ERROR/WARN/reconnect-failure lines during observation, no QR/token leakage found. Peak sampled memory approximately 79.2 MiB; peak sampled PIDs 11. Sampling is not a continuous peak guarantee or proof of long-term reliability. This observation is of the unchanged runtime, not a post-restart run.
AL-RIFA’I/PostgreSQL unchanged: PASS; original container IDs/start times retained and healthy; no DB/app changes. Pairing container absent.
Files modified: existing docs/VPS_MAP.md and whatsapp-mcp-plan.md only, plus nonsecret E3 evidence and one-shot verification/health scripts under services/whatsapp/qualification. No source/image rebuild, Compose/credential/session/configuration modification or new monitoring service.
Remaining risks: no verified encrypted/off-host session recovery; restart policy no requires manual startup after an outage; sustained history/media load and post-restart E3 stability remain unqualified. Stop here for separately approved encryption and recovery setup.

[Summary](services/whatsapp/qualification/gate-e3-results.json), [observation](services/whatsapp/qualification/gate-e3-observation.json), [final acceptance](services/whatsapp/qualification/gate-e3-final-checks.json), [operator health](services/whatsapp/qualification/gate-e3-health.json).

One-shot read-only operator check (requires root/operator access; never grant Docker privileges to an AI client):

```sh
python3 /opt/vps/services/whatsapp/qualification/wa-01-health.py
```

It reports running state, authenticated connection, restart count/policy, configured resource limits and sampled usage, exposure and recent errors/reconnect failures without printing tokens, identifiers or message contents. No alerts or periodic service is installed. A nonzero exit indicates a failed check; investigate privately and preserve the session rather than re-pairing.
