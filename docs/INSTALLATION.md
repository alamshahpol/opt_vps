# Installation and validation from a clean checkout

This guide is for **source validation and a public-only local preview**, not a
production deployment. The production Compose files are descriptions of an
existing VPS, with pinned images, host-specific mounts, credentials, networks,
and live workers. They are **not** a generic installer. Do not run `docker
compose up`, import evidence, apply migrations, restart services, pair WhatsApp,
or perform financial or messaging actions without separate Owner approval.
Read [AGENTS.md](../AGENTS.md) first.

A clean checkout can build without private evidence, but a working operational
system additionally needs a separately provisioned PostgreSQL database and
roles/schema, approved evidence, authentication, TLS, integration credentials,
networking, and any expressly approved WhatsApp services. Some screens and
candidate migrations are still approval-gated. The source checks below do not
establish production readiness or authority to use live data.

## 1. Prerequisites

- A non-production Linux/macOS environment and a clean clone without production
  `.env` files, private mounts, sessions or databases. Do not run the preview on
  the production VPS: some Cash components have fixed `/etc/vps` paths.
- Node.js **22.13 or newer** (Node 22 LTS recommended; validated with 22.22.3).
  The project pins pnpm **11.25.0** via Corepack; install Corepack separately if
  your Node distribution does not include it. `corepack pnpm --version` should
  print the pinned version.
- Python **3.11+** for the additional offline tests. Git and network access to
  the package registry are needed for the first dependency installation.

```bash
git clone https://github.com/alamshahpol/opt_vps.git
cd opt_vps/apps/al-rifai
corepack pnpm install --frozen-lockfile
corepack pnpm check:install
```

The checker reports missing runtime files without reading their contents. In a
clean checkout, missing private evidence, validation/database passwords and the
fixed Cash review password are **expected**; the command still succeeds when
Node and dependencies are available. `corepack pnpm check:install --strict`
returns nonzero if those checked files are missing. Strict mode checks only a
subset of file readability: it does **not** validate contents/checksums, database
connection/schema, TLS, OS permissions, integrations or production readiness.

## 2. Offline checks and production build

From `apps/al-rifai`:

```bash
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm test             # offline Node suite; same as test:unit
corepack pnpm test:python      # offline Python suite, including mock harness tests
corepack pnpm build
corepack pnpm test:smoke       # requires the completed build
corepack pnpm audit            # registry access required
```

The default Node and Python runners use a minimal environment: they do not
inherit evidence paths, database URLs or production flags. The Node suite skips
the optional uploaded WhatsApp export parser fixture and its disposable-DB test;
the Python suite reports explicit skips for private evidence and a reviewed
artifact absent from the source checkout. The smoke test stages the Dockerfile's
standalone runtime files in a temporary directory, starts a server on loopback,
checks public pages/assets and fail-closed protected routes, and checks disabled
workers using only a synthetic temporary password. It also checks the local
standalone start command. It does **not** run Docker, verify the database, or
test the enabled workers.

On 29 October 2026, the full JavaScript `pnpm audit` reported zero known
advisories. The WhatsApp Python lock was checked separately against PyPI's
version advisory metadata (all locked platforms) and `pip-audit` (Linux/Python
3.11): both reported zero known advisories. Advisories change over time. These
checks do not audit Go, operating-system packages, container images, application
logic, or deployed dependencies. Some upstream development packages remain
deprecated.

### Separate evidence and qualification tests

Do not point tests at production. If specifically authorized, prepare a private,
isolated copy and explicitly provide its location:

```bash
ALRIFAI_EVIDENCE_DIR=/path/to/isolated/authorized-copy corepack pnpm test:evidence
```

The Python evidence tests can be selected separately with that same environment
variable and `python3 -m unittest discover -s tests -p 'test_*.py'`. Their
optional byte-identical reimport checks also need isolated copies of the
original exports/proof files; review their `AL_RIFAI_*` paths before running.
Comparing the omitted, reviewed SQL artifact requires a separately authorized
isolated copy at its expected `data/` path and explicit
`ALRIFAI_REVIEWED_ARTIFACT_CHECK=1` when invoking Python directly. Never copy
private evidence or credentials into Git or a container build context.

The historical `tests/employee-program-qualification.mjs` expects an older
`lib/vessel-source.ts` expression; `tests/identity-review-candidate.mjs` detects
a mismatch with the frozen `lib/escort-intake-candidate.mjs` evidence pin, and
its referenced WhatsApp qualification document is not included in this clone.
They are not part of the default offline suite. Do not rewrite the frozen pins
or claim historical qualification passed; the differences need separate Owner
review and the authorized original fixtures.

## 3. Public-only local preview

After the build, in the same isolated machine and clean checkout, start the
loopback-only server (Ctrl+C to stop):

```bash
scratch="$(mktemp -d)"
env -i HOME="$HOME" PATH="$PATH" NEXT_TELEMETRY_DISABLED=1 \
  ALRIFAI_EVIDENCE_DIR="$scratch/no-evidence" \
  ALRIFAI_VALIDATION_PASSWORD_FILE="$scratch/no-validation-password" \
  PGPASSWORD_FILE="$scratch/no-database-password" PGHOST=127.0.0.1 \
  ALRIFAI_UNIFIED_AUTH_MODE=off ALRIFAI_LIVE_CASH_SYNC=0 \
  ALRIFAI_VESSEL_PROCESSING_ENABLED=0 ALRIFAI_MESSAGE_MIRROR_ENABLED=0 \
  corepack pnpm start
```

Open <http://127.0.0.1:3000/> on that same machine. `/` and `/signup` are public;
`/signup` explains administrator provisioning and does not create an account.
Protected workspace routes return 401 without credentials, and `/api/health`
returns 503 without a configured database. The Cash login surface may be visible,
but operational Cash and Vessel data, login, integrations and workers are not
configured by this preview. Do not expose it publicly or supply production
secrets. Remove the empty scratch directory after stopping the server.

## 4. Containers and database rehearsals

The app Dockerfile now builds from source without an evidence build context;
private evidence remains a runtime-only input. On an isolated machine with
Docker, `docker build -t alrifai-source:local .` from `apps/al-rifai` builds a
candidate image without starting it. The image build was **not** verified in
the current environment because Docker was unavailable. A successful build is
not permission to deploy it or use the production Compose files.

The optional [0031/0032 schema rehearsal](../apps/al-rifai/docs/MIGRATION-READINESS-0031-0032.md#7-isolated-schema-rehearsal-not-a-production-restore)
creates its own throwaway networkless PostgreSQL container, accepts no existing
database target, and removes its temporary data. It requires Docker and a
pre-existing `postgres:16-alpine` image. Only mocked safety tests were run in
this environment; real PostgreSQL execution remains unverified. It is not a
backup-restore rehearsal and it does not authorize applying either migration.

## 5. WhatsApp source checks

The Python service dependencies and source tests can be set up separately without
starting a bridge or accessing an account. In a separate non-production workspace, install Python
3.11+, [uv](https://docs.astral.sh/uv/) and FFmpeg (the full Python test suite
needs the `ffmpeg` executable), then from the repository root:

```bash
cd services/whatsapp/source/whatsapp-mcp-server
uv sync --locked --extra dev
scratch="$(mktemp -d)"
env -i HOME="$HOME" PATH="$PATH" \
  WHATSAPP_DB_PATH="$scratch/no-messages.db" WHATSMEOW_DB_PATH="$scratch/no-whatsapp.db" \
  uv run --locked --extra dev pytest -q
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
```

`uv sync` installs the locked dependencies for running from source; this project
is not installed as a package by that command. A separately built Python wheel
includes all service modules, but it does not include or configure the Go bridge.
The patched `cryptography` release has no prebuilt Intel macOS wheel; installation
there may require Rust/OpenSSL build tools and was not verified here.
The bridge separately requires Go 1.26+ and its module
requirements. The Go bridge and live pairing were not tested in this environment.
The upstream README describes pairing and sending; those instructions are not
authorization to touch an existing account or run another writer.

## 6. Before any real deployment

A responsible operator must separately review the target host, image and Compose
configuration, DNS/TLS, database identity/roles and migration ledger, backup
and restore plan, evidence provenance/checksums, file ownership/permissions,
secret storage, authentication, network isolation, worker flags and WhatsApp
scope. Follow the existing component runbooks and obtain action-specific Owner
approval. Do not treat a green source build, file checker, local smoke test,
previous historical report, or this guide as permission to deploy or alter
production data.
