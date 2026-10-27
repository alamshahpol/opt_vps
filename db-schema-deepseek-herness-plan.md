# DeepSeek, Hermes and AI orchestration schema plan

10 October 2026, Asia/Dhaka. Filename preserves the requested `herness` spelling; this document interprets it as **Hermes**. DeepSeek is a proposed provider/model option, not an installed service or a verified enabled Fazle Core provider. No model/API integration or AI database has been installed.

## Verified reference and important distinctions

[Fazle Core README](https://github.com/arshiyaazim/fazle-core/blob/main/README.md) describes OmniRoute -> Ollama/Hermes -> safe fallback, with Groq/Kimi disabled in its documented deployment. Hermes-family local models and a separate Hermes runner are different components. Customer dispatch passes prefetched scoped context and has no MCP tools in its described first phase. [Migration inventory](https://github.com/arshiyaazim/fazle-core/blob/main/db/MIGRATION_INVENTORY.md) documents hermes_tasks, hermes_task_events, hermes_action_approvals and decision-audit concepts; deployment/applied claims there are not this VPS's state.

VPS_MAP makes Hermes/Router conditional. Start with a small draft-generation adapter in Al-Rifa'i; add a shared runner/router only when multiple consumers or persistent task execution justify it. No Redis, Qdrant, Ollama, weights or GPU assumptions. DeepSeek provider endpoint, model identifier, pricing, data policy and compatibility must be verified from its official documentation at implementation time; no API URL/model is hardcoded here.

## Proposed ownership and tables

Use optional `ai` schema inside existing alrifai database on existing vps-infra PostgreSQL. Separate read-scoped retrieval from execution privileges. All tables below are proposals, not upstream schemas. UUID keys, timestamptz instants, jsonb bounded structured metadata, text provider/model IDs and numeric measured costs. Store credential references only; keys remain under /etc/vps.

| Table | Purpose | Possible column heads |
| --- | --- | --- |
| ai.providers | Approved provider configuration | id, name, provider_kind, base_url, credential_ref, enabled, data_residency_note, config_version |
| ai.models | Physical models/capabilities | id, provider_id, model_identifier, capabilities, context_limit NULL, enabled, observed_at |
| ai.routes | Versioned task/provider selection | id, route_name, task_type, model_id, fallback_route_id NULL, timeout_seconds, privacy_scope, policy_version, enabled |
| ai.runs | Generation execution record | id, route_id, requesting_actor_id, account_id NULL, chat_jid NULL, purpose, status, started_at, finished_at NULL, prompt_template_version, input_hash, output_ref NULL, trace_id |
| ai.run_attempts | Each physical provider attempt | id, run_id, attempt_no, provider_id, actual_model_id, started_at, finished_at, outcome, input_tokens NULL, output_tokens NULL, latency_ms, measured_cost NULL, currency NULL, safe_error_code |
| ai.context_sources | Exact authorized evidence supplied | id, run_id, source_kind, source_ref, source_hash, account_id NULL, scope_policy_version, retrieved_at |
| ai.reply_drafts | Reviewable generated reply | id, run_id, account_id, chat_jid, reply_to_message_id NULL, content, content_hash, status, reviewed_by NULL, reviewed_at NULL, outbound_intent_id NULL |
| ai.knowledge_documents | Reviewed factual authority | id, domain, title, content_ref, content_hash, authority_status, approved_by NULL, effective_from NULL, effective_to NULL, audience_scope |
| ai.knowledge_chunks | Rebuildable retrieval index | id, document_id, ordinal, text_or_ref, content_hash, index_version, embedding_model_id NULL |
| ai.feedback | Structured operator corrections | id, run_id, draft_id NULL, reviewer_id, verdict, correction_ref NULL, reason, created_at |
| ai.policy_decisions | Trace policy evaluations | id, run_id NULL, action_type, scope_hash, policy_version, outcome, reason_codes, evaluated_at |
| ai.tasks (later only) | Persistent task/dependency state | id, parent_task_id NULL, goal, status, requesting_actor_id, scope, trace_id, created_at, expires_at NULL |
| ai.task_dependencies (later only) | Enforced task dependencies | task_id, depends_on_task_id (PK/FKs), dependency_kind |
| ai.task_events (later only) | Append transitions/evidence | id, task_id, event_type, previous_status, next_status, actor_id, evidence_refs, occurred_at |

Reuse proposed public.business_approvals for exact actions; do not create a second ai/hermes approval engine. Reuse wa.outbound_intents and wa.send_attempts for every generated send; AI drafts are content candidates, not another queue. Execution privilege is held by the reviewed action worker, not the language model or provider.

## Data flow and controls

Inbound wa message -> authenticated operator/business scope -> authorized facts/retrieval -> ai.run -> physical provider attempts -> reply draft -> exact human approval -> existing outbound intent -> verified transport outcome. Business mutations use the same explicit approval/transaction service, never SQL authored/executed directly by the model.

Record actual model and attempt after fallback, never label all results DeepSeek/Hermes. Privacy-sensitive context must not fall back to a remote provider outside the approved scope. Unknown token/cost values remain NULL; estimate fields, if later added, are separately named. Use bounded timeouts/circuit breaks and retry only safe generation failures; provider generation retry is independent of WhatsApp send retry.

Context is account/chat/role scoped. WhatsApp text, repository issues and web pages are untrusted content, not executable instructions. Keep browser/GitHub tools in a developer identity separate from customer-facing AI. No secrets, arbitrary filesystem or global cross-account search to customer dispatch. Evidence links/hashes must remain available to the reviewer; exclude raw secrets and unnecessary personal content from audit/metrics.

## Indexes, retention and validation

Unique model(provider_id, model_identifier), route version identity, attempt(run_id, attempt_no), chunk(document_id, ordinal, index_version); indexes on runs(trace_id, started_at), drafts(status, created_at) and knowledge(domain, authority_status). Tasks enforce valid transitions and acyclic dependencies in transactional validation. Shared approval binds action payload hash, requester, reviewer, expiry and scope; changing a draft invalidates approval. Avoid redundant build authorization unless a real persistent runner needs it.

Use PostgreSQL text search first; embeddings/vector extensions require demonstrated need and compatibility review. Approved/current facts are separate from archived/conflicting facts; uncertain salary/payroll rules fail to human review. Select retention for prompts, outputs, feedback and personal evidence before production; model-provider data processing needs owner selection.

First acceptance tests use synthetic conversations: cross-account scope denial, ambiguous identity, conflicting KB facts, provider outage, disallowed remote fallback, expired approval, edited draft, prompt-injected message and no automatic financial/outbound action. No real sends or production ledger writes are needed. These are later implementation tests, not tests executed in this planning session.
