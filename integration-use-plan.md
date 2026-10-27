# How to use the installation and schema plans together

10 October 2026, Asia/Dhaka. Planning deliverables only. All four requested repository READMEs were fetched through the connected GitHub account; no repository was cloned/executed. Existing map/application schema and employee/program policy were read locally.

## Read order

1. [VPS_MAP.md](docs/VPS_MAP.md): deployed paths, privacy, persistence and single PostgreSQL owner.
2. [whatsapp-mcp-plan.md](whatsapp-mcp-plan.md): exact selected fork, dependencies, isolated runtime and three-number pairing.
3. [db-schema-whatsapp-plan.md](db-schema-whatsapp-plan.md): transport SQLite vs proposed application PostgreSQL projection.
4. [db-schema-al-rifai-plan.md](db-schema-al-rifai-plan.md): preserve existing schema/candidate and select business features from Fazle Core.
5. [db-schema-deepseek-herness-plan.md](db-schema-deepseek-herness-plan.md): optional AI drafts and shared action controls.

These root-level Markdown deliverables were explicitly requested. Future deployed operational records belong under docs; runtime state/secrets never belong in these files. VPS_MAP is unchanged because deployed state is unchanged.

## Source evidence register

| Repository/read | Observed file blob SHA | Source |
| --- | --- | --- |
| WhatsApp README | b0109d022961d9232c0ee2eb16cdfb173cca6611 | [README](https://github.com/arshiyaazim/whatsapp-mcp/blob/main/README.md) |
| Fazle Core README | f832a35704c7dc2abf45bbea3c668bae69898592 | [README](https://github.com/arshiyaazim/fazle-core/blob/main/README.md) |
| Playwright MCP README | 7cecc4144025919587399336dff41b0d3ba366ad | [README](https://github.com/microsoft/playwright-mcp/blob/main/README.md) |
| GitHub MCP README | 6413b58760bb04f841c63062712f75f0dae6c4d6 | [README](https://github.com/github/github-mcp-server/blob/main/README.md) |
| Fazle migration inventory | 21731d29d877269700b55993b571ec703d2b6b57 | [Inventory](https://github.com/arshiyaazim/fazle-core/blob/main/db/MIGRATION_INVENTORY.md) |

Blob hashes identify fetched files, not repository commits. Reads used the default branch and are not an atomic pinned checkout. At implementation resolve exact commits and re-read relevant source from those commits. README state claims are documentation, not independent live-server verification. Table proposals are not claims that those tables already exist.

## Responsibilities and useful workflows

| Component | Responsibility | Useful application |
| --- | --- | --- |
| Selected WhatsApp fork | One linked device per isolated process, SQLite transport history and MCP | Private searches, account-specific transport, evidence acquisition |
| Al-Rifa'i | Business records, login/RBAC, employee/vessel/program views and approvals | Operator workspace showing source-linked drafts and confirmed facts |
| Fazle Core | Reference patterns/code to audit and port selectively | Recruitment, payroll, reconciliation, scoped identity and draft workflows |
| DeepSeek/Hermes adapter (optional) | Scoped generation/retrieval | Summarize authorized chats, explain discrepancies, prepare replies |
| Playwright MCP | Developer browser inspection/debugging | Inspect Al-Rifa'i UI/accessibility; investigate failing workflows |
| GitHub MCP | Developer repository/issue/PR/CI tools | Read selected repositories, review code/diffs, inspect build failures |

Example: a WhatsApp vessel order becomes an account-scoped native message projection, then a source occurrence and review candidate. A verified client order can support Draft; separate complete admin evidence supports confirmation. Employee matching follows the existing mobile policy. UI displays evidence/aliases and asks the authorized operator to decide. Later AI can summarize/extract a proposal, but cannot invent dates, approve itself, send a reply or post a payment.

## Playwright MCP usage plan

Its README requires Node.js 18+ and documents `@playwright/mcp`, headless/isolated sessions and a Docker image (headless Chromium). Pin package version/image digest rather than copying @latest or --pull=always into production. Run on demand over stdio with a dedicated test browser and synthetic data. Profiles/screenshots/traces belong in restricted /var/lib/vps developer-test state; secrets outside source. Use a private test login, not a production admin session or WhatsApp Web login.

Use it to inspect screens, accessibility and reproduce UI issues. Maintain deterministic Playwright tests separately for repeatable regression checks; an exploratory MCP session is not a test suite. The README also discusses Playwright CLI as a lighter coding-agent option; choose the tool that matches the development client rather than installing both automatically.

A host-run browser can reach the app's existing 127.0.0.1:3000 URL. A Docker browser cannot use its own loopback to reach the host app; use the authorized vps-backend service address/test deployment and the intended private test authentication. Do not publish 8931 just because the README example does. Host/origin filters and MCP itself are not a security boundary; restrict browser network/filesystem at runtime.

## GitHub MCP usage plan

The README supports hosted remote MCP and local Docker/binary operation, configurable toolsets and read-only mode. Existing connected GitHub access already served this research, so a second server is optional. If needed use remote OAuth in a supported development client, or a pinned local stdio image with read-only mode and a repository-scoped credential. Keep credentials under /etc/vps and out of configuration checked into source. Do not grant the app Docker privilege to launch it.

Limit tools to repository reads initially. Later developer tasks can use narrowly authorized branch/PR/CI capabilities. Lockdown mode is a best-effort content filter, not credential authorization. GitHub MCP does not install Go/Python dependencies or establish VPS SSH clone access. Never feed payroll/customer/session data into GitHub issues or PRs.

## Delivery phases and acceptance

| Phase | Result | Required evidence |
| --- | --- | --- |
| 1 | Reviewed pinned WhatsApp checkout/build, inactive deployment | Dependency locks, successful tests, exact mount/network config |
| 2 | Three independently paired private bridges/MCP registrations | Private identity checks, persistence/restart and account isolation |
| 3 | Durable/reconciled message projection + private operator UI | Replay/crash tests, least privilege, auth and source evidence |
| 4 | Employee/program/release/attendance draft workflows | Existing policy/candidate qualification and reader acceptance |
| 5 | Reviewed finance/payroll/billing | One ledger/approval authority and transactional/reversal tests |
| 6 | Optional AI drafts + development MCP tools | Scoped synthetic tests, actual provider provenance, no bypass writes |

Implementation decisions still needed: account purposes/aliases and authorized operators; MCP client location/transport; media/history budgets and retention; off-host encrypted backup destination; final runtime UIDs; app login/roles; whether AI runs locally or through an approved remote provider. No plaintext real numbers/keys are needed in chat. These decisions do not block completing the planning files.

This session creates only these five documents. Installation, paired-phone actions, database migrations, app write enablement and deployment remain future work. Approval should concern the concrete reviewed change being executed; existing authorization must not be re-requested unnecessarily.

## Gate C independent service boundary

Current owner instructions supersede any earlier requirement that WhatsApp depend on AL-RIFA’I or Hermes. WhatsApp owns its sessions, native SQLite, media and authenticated MCP boundary. Applications are replaceable consumers. No Hermes/DeepSeek Harness installation, PostgreSQL ingestion or business automation is part of this pilot. Feature implementation is retained; grants independently govern execution. A scoped consumer authenticates through a private Unix socket and stdio relay without Docker access. The full bridge bearer token is not supplied to consumers. Write grants require explicit operator authorization; pairing is not such authorization.
