# WhatsApp database schema plan

10 October 2026, Asia/Dhaka. Design proposal only; no DDL executed. [Deployment plan](whatsapp-mcp-plan.md) governs account isolation. [VPS_MAP](docs/VPS_MAP.md) governs persistence and PostgreSQL ownership.

## Existing upstream SQLite authority

Source: [README](https://github.com/arshiyaazim/whatsapp-mcp/blob/main/README.md) and inspected [main.go](https://github.com/arshiyaazim/whatsapp-mcp/blob/main/whatsapp-bridge/main.go), opening 330 lines. This is not an exhaustive latest schema audit; inspect remaining migration/helpers at the pinned commit before implementation.

Each number has a separate messages.db and whatsapp.db. whatsmeow owns session/contact/LID/key tables inside whatsapp.db: preserve them opaquely, do not recreate them or export encryption/auth material into PostgreSQL.

| Verified table | Purpose | Observed columns |
| --- | --- | --- |
| chats | Bridge chat cache | jid (PK), name, last_message_time, ephemeral_expiration, ephemeral_setting_timestamp, last_read_time |
| messages | Transport message history | id, chat_jid (composite PK), sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length, deleted_at, quoted_message_id |
| calls | Observed incoming call lifecycle | call_id, chat_jid (composite PK), from_jid, timestamp, is_from_me, call_type, is_group, result, duration_sec, ended_at, reason |

Do not expose media_key, encrypted-media URL credentials or session tables to app/LLM consumers. Calls missed during downtime cannot be recovered by inventing records. A successful send acknowledgement is not proof of recipient delivery, reading or local persistence.

## Proposed PostgreSQL projection

Initial deployment needs **no PostgreSQL schema**. Later use the existing alrifai database on existing vps-infra PostgreSQL, with a proposed `wa` schema and narrowly scoped ingestion/read roles. No extra PostgreSQL container. If multiple apps later need messaging, decide dedicated database ownership on the same instance before implementation; do not create two canonical projections.

All names below are proposed. IDs use UUID unless a native text key is indicated; times use timestamptz; phones/JIDs remain text; bounded structured metadata uses jsonb. Operational records are not copies of session keys.

| Table | Purpose | Possible column heads |
| --- | --- | --- |
| wa.accounts | Nonsecret account registry | id, alias UNIQUE, channel, device_jid, verified_phone_e164, display_name, enabled, pairing_verified_at, created_at |
| wa.account_health | Latest observed connectivity | account_id PK/FK, observed_at, connected, authenticated, last_message_at, last_reconciled_at, safe_error_code |
| wa.chats | Rebuildable chat projection | account_id, chat_jid (PK), kind, display_name, name_source, name_observed_at, last_message_at, last_read_at, ephemeral_seconds |
| wa.contact_observations | Account-specific identity evidence | id, account_id, contact_jid, phone_e164 NULL, lid_jid NULL, display_name, name_source, observed_at, confidence, source_ref |
| wa.messages | Rebuildable native message projection | account_id, chat_jid, message_id (PK), sender_jid, resolved_phone_e164 NULL, content, message_at, ingested_at, is_from_me, media_type, quoted_message_id NULL, deleted_at NULL, source_revision_hash |
| wa.message_events | Append lifecycle observations | id, account_id, chat_jid, message_id, event_key UNIQUE, event_type, event_at NULL, observed_at, target_message_id NULL, sender_jid, payload_safe, source_ref |
| wa.media_assets | Restricted media index | id, account_id, chat_jid, message_id, kind, mime_type, original_filename, storage_relative_path NULL, size_bytes, sha256, acquisition_status, acquired_at, retention_until NULL |
| wa.calls | Rebuildable incoming call observations | account_id, chat_jid, call_id (PK), from_jid, started_at, ended_at NULL, call_type, is_group, observed_result, duration_sec NULL, reason, ingested_at |
| wa.ingest_events | Durable receiver inbox | id, account_id, event_key UNIQUE, event_type, native_message_id NULL, chat_jid NULL, occurred_at NULL, received_at, payload_safe, payload_hash, status, attempt_count, next_attempt_at, safe_error_code |
| wa.sync_cursors | Reconciliation checkpoints | account_id, stream (PK), cursor_version, cursor_value, overlap_start_at, committed_at, last_error_code |
| wa.outbound_intents | Single app-owned send queue | id, account_id, chat_jid, idempotency_key UNIQUE, content_or_media_ref, content_hash, actor_type, actor_id, ai_run_id NULL, approval_id NULL, status, created_at, expires_at NULL, next_attempt_at NULL |
| wa.send_attempts | Submission and uncertain-outcome history | id, intent_id FK, attempt_no, started_at, finished_at NULL, outcome, native_message_id NULL, safe_error_code, retry_permitted |
| wa.message_attributions | Link native sends to known producers | account_id, chat_jid, message_id (PK), intent_id FK NULL, actor_type, actor_id NULL, ai_run_id NULL, correlated_at, correlation_method |

## Keys, privacy and behavior

- Never deduplicate by message_id alone. Use account + chat + native message ID, retaining distinct observations across accounts. Messages/chats have composite FKs; reactions/replies can reference targets not yet synced, so allow deferred resolution without dropping source events.
- Index messages by (account_id, chat_jid, message_at, message_id), contact observations by (account_id, contact_jid), and due queue/inbox work with partial indexes on eligible statuses. Event uniqueness includes account scope in the event-key construction.
- Store native message time separately from receipt/reconciliation time. Preserve unknowns as NULL. Do not infer phone digits from LIDs, overwrite display-name provenance or identify an employee from sender/group name alone.
- Use transactionally committed projection writes and cursor advances. Timestamp-only cursors lose tied/late/history records: use versioned native keys plus bounded overlap and idempotent upserts, separate history reconciliation and call streams. Webhooks alone are insufficient; upstream export/reconciliation support must be audited/added.
- Receiver durably commits an inbox event before acknowledging. Payload/event bounds, replay deduplication and account-specific authentication are required. Sanitize raw data to exclude auth/media encryption secrets. Retention is explicit and does not silently discard business evidence.
- App projections may reflect edit/delete observations; immutable business evidence retains original hashes and review lineage subject to an agreed privacy retention policy. Do not confuse projection mutability with immutable evidence.
- Outbound state: draft -> approved -> queued -> submitting -> sent; rejected/expired/cancelled/failed/unknown are separate. Approval binds exact account, destination, content hash, actor and expiry. Revalidate permission before submission. A timeout after submission becomes unknown; never blindly retry it. Local idempotency cannot guarantee exactly-once delivery on WhatsApp.
- Never infer human/AI attribution from is_from_me. Uncorrelated self messages remain unattributed. Do not post money when a message merely says PAID or when a send succeeds.
- Use one outbound intent queue: reuse it for AI and manual sends instead of adding competing social/AI retry queues. An audited service enforces write permission; direct unrestricted MCP sends bypass this workflow and must not be granted to production agents.

## Migration qualification

Use Al-Rifa'i's existing checksum-tracked migration framework, with a narrowly scoped `wa` writer and read-only UI views; do not grant the bridge PostgreSQL access. Qualify fresh migrations, FK/account separation, tied timestamps, duplicate callbacks, crash-before/after-commit, lost webhooks, failed local send persistence and unknown outcomes in a disposable database **on the existing PostgreSQL instance**. Test backup/restore and reader compatibility before explicitly applying production changes. Current app role/default read-only sessions must not be globally weakened to make ingestion work.

## Gate C owner correction — independent service control proposal (not executed)

The WhatsApp service remains independent of AL-RIFA’I or an AI harness. Earlier application coupling is superseded by the current owner instruction. Native transport/session tables remain dependency-owned. No PostgreSQL changes are authorized or performed. A future optional **separate service-owned SQLite `control.db`** may contain the following; none is created by this qualification:

| Proposed table | Column heads and primary key | Foreign keys / indexes |
|---|---|---|
| service_accounts | account_id PK, alias UNIQUE, enabled, created_at | alias unique |
| service_consumers | consumer_id PK, account_id, name, enabled, expires_at, credential_hash | account_id -> service_accounts; unique account/name |
| capability_grants | consumer_id, capability, granted_by, granted_at, expires_at; PK(consumer_id,capability) | consumer_id -> service_consumers; expiry index |
| call_policies | policy_id PK, account_id, caller_category, enabled, template_hash, cooldown_seconds, approval_required | account FK; unique account/category |
| call_automation_events | event_id PK, account_id, chat_jid, native_call_id, event_type, observed_at, policy_id, status | account/policy FKs; unique(account_id,chat_jid,native_call_id,event_type); status/time index |
| caller_cooldowns | account_id, caller_jid, next_eligible_at, lease_until; PK(account_id,caller_jid) | account FK; next_eligible_at index |
| outbound_actions | action_id PK, account_id, consumer_id, source_event_id, destination_jid, content_hash, status, created_at, expires_at, idempotency_key | account/consumer/event FKs; unique(account_id,idempotency_key); status/time index |
| exact_approvals | approval_id PK, action_id, approver_id, approved_content_hash, approved_destination, expires_at, approved_at | action FK; action/expiry index |
| outbound_attempts | attempt_id PK, action_id, started_at, ended_at, native_message_id, result, sanitized_error | action FK; action/time index |

Native chat/call/message references are logical cross-database references, not pretend SQLite foreign keys. Credentials and session encryption keys never enter PostgreSQL. Transactions must reserve deduplication/cooldown leases before dispatch. An uncertain send result becomes `unknown`; no automatic retry. Approval binds exact account, destination, content and expiry. This is a communication control store, not a business ledger.

The pinned whatsmeow dependency implements `Client.RejectCall`; the bridge does not expose it. Incoming call storage is existing functionality, while active rejection and a durable automated response worker require implementation and live qualification. Observing a reject event does not prove active rejection. Unknown callers default to denied; known, personal and group policies remain separately configurable. Offline helpers test approval -> composing -> bounded delay -> approval recheck -> send -> paused cleanup -> result recording. They are not an enabled automation worker.

## Actual Gate C disposable native SQLite catalog

Complete DDL, column types, primary keys, foreign keys and indexes: [verified catalog](services/whatsapp/qualification/sqlite-schema.json). This catalog contains no messages or session values.

| Database / table | Actual column heads |
|---|---|
| messages.db / calls | call_id, chat_jid, from_jid, timestamp, is_from_me, call_type, is_group, result, duration_sec, ended_at, reason |
| messages.db / chats | jid, name, last_message_time, ephemeral_expiration, ephemeral_setting_timestamp, last_read_time |
| messages.db / messages | id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length, deleted_at, quoted_message_id |
| whatsapp.db / whatsmeow_app_state_mutation_macs | jid, name, version, index_mac, value_mac |
| whatsapp.db / whatsmeow_app_state_sync_keys | jid, key_id, key_data, timestamp, fingerprint |
| whatsapp.db / whatsmeow_app_state_version | jid, name, version, hash |
| whatsapp.db / whatsmeow_chat_settings | our_jid, chat_jid, muted_until, pinned, archived |
| whatsapp.db / whatsmeow_contacts | our_jid, their_jid, first_name, full_name, push_name, business_name, redacted_phone |
| whatsapp.db / whatsmeow_device | jid, lid, facebook_uuid, registration_id, noise_key, identity_key, signed_pre_key, signed_pre_key_id, signed_pre_key_sig, adv_key, adv_details, adv_account_sig, adv_account_sig_key, adv_device_sig, platform, business_name, push_name, lid_migration_ts, companion_meta_nonce |
| whatsapp.db / whatsmeow_event_buffer | our_jid, ciphertext_hash, plaintext, server_timestamp, insert_timestamp |
| whatsapp.db / whatsmeow_identity_keys | our_jid, their_id, identity |
| whatsapp.db / whatsmeow_lid_map | lid, pn |
| whatsapp.db / whatsmeow_message_secrets | our_jid, chat_jid, sender_jid, message_id, key |
| whatsapp.db / whatsmeow_nct_salt | our_jid, salt |
| whatsapp.db / whatsmeow_pre_keys | jid, key_id, key, uploaded |
| whatsapp.db / whatsmeow_privacy_tokens | our_jid, their_jid, token, timestamp, sender_timestamp |
| whatsapp.db / whatsmeow_retry_buffer | our_jid, chat_jid, message_id, format, plaintext, timestamp |
| whatsapp.db / whatsmeow_sender_keys | our_jid, chat_id, sender_id, sender_key |
| whatsapp.db / whatsmeow_sessions | our_jid, their_id, session |
| whatsapp.db / whatsmeow_version | version, compat |
