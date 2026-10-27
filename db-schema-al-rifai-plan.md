# Al-Rifa'i schema and Fazle Core gap plan

10 October 2026, Asia/Dhaka. Proposed future design only. No migrations, imports, source-code changes or deployment. [VPS_MAP](docs/VPS_MAP.md) remains deployed authority.

## Verified local foundation and existing candidate

Read apps/al-rifai/db/schema.ts, README.md, docs/EMPLOYEE_PROGRAM_SCHEMA_PROPOSAL.md and docs/OWNER_BUSINESS_POLICY.md. There are eight application table definitions plus the migration ledger. Live catalog was **not** queried this session; map counts are documented state, not a new database audit.

| Existing table | Purpose | Current column heads |
| --- | --- | --- |
| programs | Existing flat program anchor | id, details, motherVessel, lighterVessel, masterMobile, destination, escortName, escortMobile, startDate, endDate, shift, status, source, notes, duplicateOf, createdAt, revision |
| reviews | Pairwise duplicate decisions | id, aId, bId, decision, note, createdAt |
| datasets | Import markers | id, importedAt |
| site_source_snapshots | Immutable historical evidence | id, datasetId, kind, payload, contentHash |
| site_cash_archive | Historical cash, not a new live ledger | id, date, source, employeePhone, name, method, amountCents, details |
| site_operation_notes | Operational note structure | id, status, note, actor, updatedAt |
| site_payment_drafts | Proposed payment data | id, details, actor, createdAt |
| site_settlement_drafts | Proposed settlement data | id, details, actor, createdAt |
| Existing migration ledger | Applied migration/checksum authority | Preserve current runner-defined columns; inspect before any migration |

Reuse the existing eleven-table employee/program candidate rather than creating another employee/assignment system:

| Candidate table | Purpose | Possible/current candidate heads |
| --- | --- | --- |
| ep_source_occurrences | Exact source assertions | id, source_file, file_sha256, document_pointer, decoded_pointer, payload_sha256, source_record_id, raw_record, mapping_version |
| ep_review_decisions | Evidence-bound decisions | id, occurrence_id, role, event_key, decision, approver, approved_at, evidence_reference, assertion, supersedes |
| ep_employees | Employee mobile identity | id (immutable technical TEXT key), employee_id (normalized mobile TEXT UNIQUE), authoritative_code NULL, decision_id, approval |
| ep_employee_history | Original names/aliases/contact/employment | id, employee_id FK to ep_employees.employee_id, kind, value, comparison_value, valid_from NULL, valid_to NULL, verification, decision_id |
| ep_vessels | Verified vessel identity | id, authority_reference, decision_id, approval |
| ep_vessel_aliases | Preserved vessel names | id, vessel_id, label, comparison_value, valid_from NULL, valid_to NULL, decision_id |
| ep_programs | Typed extension of programs | program_id FK, authority_reference, start_date NULL, end_date NULL, shift NULL, lifecycle, decision_id |
| ep_program_vessels | Mother/lighter relationships | id, program_id, mother_id, lighter_id, decision_id |
| ep_assignment_events | Append assignment/replacement/lifecycle assertions | id, relationship_id, program_id, lighter_id, employee_id, kind, valid_from, valid_to NULL, previous_id NULL, decision_id |
| ep_import_batches | Atomic approved import checkpoints | id, manifest_sha256, manifest, schema_sha256, mapping_version, owner_approval_reference, accepted_count, committed_at |
| ep_source_bindings | Typed source-to-entity provenance | id, occurrence_id, role, event_key, decision_id, batch_id, target_sha256, employee_id NULL, employee_history_id NULL, vessel_id NULL, program_id NULL, relationship_id NULL, assignment_id NULL |

This table is a planning summary, not replacement DDL. Exact fields/constraints come from the reconciled candidate SQL and current policy, not superseded paragraphs in its historical audit. Existing candidate qualification documents must be checked for the latest status before execution.

Owner policy takes precedence over Fazle Core defaults: normalized employee mobile is operational employee_id; same mobile retains name aliases, same name/different mobile stays separate absent approved linkage. Only established employee-ledger/escort-mobile source roles may populate it. Sender/master/client/payout phone and arbitrary JID/LID are not employee evidence. No duplicate escort_mobile column. Employment and applicants remain distinct from identity matching.

## Fazle Core reference and portability limits

Read [Fazle Core README](https://github.com/arshiyaazim/fazle-core/blob/main/README.md) and [migration inventory](https://github.com/arshiyaazim/fazle-core/blob/main/db/MIGRATION_INVENTORY.md) through the connected account. README file blob `f832a35704c7dc2abf45bbea3c668bae69898592`; inventory blob `21731d29d877269700b55993b571ec703d2b6b57`. README's embedded branch/commit describes another working-tree deployment; do not assume those flags, credentials or live rows exist on this VPS.

| Useful reference | Al-Rifa'i adaptation |
| --- | --- |
| fpe_employees + legacy wbom_employees | Keep one ep_employees authority; map legacy IDs as external references after audited import, never duplicate authorities |
| fpe_employee_payout_destinations | Separate payment destination from employee identity |
| fpe_cash_transactions, fpe_income_transactions | Design one reviewed canonical financial posting service; do not revive deprecated wbom_cash_transactions |
| wbom_escort_programs, escort_roster_entries | Reuse programs + ep_programs/vessels/assignment events |
| fazle_roles/admins | Build app-specific authenticated users/roles/sessions; do not copy API keys into browser localStorage |
| wbom_whatsapp_messages + wbom_group_identities | Use account-scoped wa projection/provenance, preserving distinct group-name observations |
| Draft approval + outbound authorization | Bind approvals to immutable content/account/recipient; revalidate at execution |
| Recruitment, attendance, payroll, billing | Add domains incrementally with reviewed evidence and typed relations |

Inventory reports stale migration tracking, multiple schema sources/startup DDL and some tables with only guessed test-fixture definitions. It also contains conflicting historical applied-status notes. Therefore do not run Fazle Core's migration runner against alrifai or copy its startup behavior. Review actual migration/code definitions per adopted feature; no claim of a complete Fazle schema audit is made here.

## Optional later operational tables

Only add these when the relevant feature is scheduled; they are not all prerequisites for WhatsApp. Prefer app public-schema names with a consistent prefix. Types: UUID IDs unless existing TEXT/FK compatibility dictates otherwise, date for business days, timestamptz for instants, bigint minor units + currency for money, numeric for rates/quantities, bounded jsonb for evidence details.

| Proposed table | Purpose | Possible column heads |
| --- | --- | --- |
| app_users | Authenticated operators | id, login_identifier, password_hash_or_identity_ref, status, created_at |
| app_roles / app_user_roles | Explicit permission hierarchy | role_id, name, permission_set; user_id, role_id, granted_by, granted_at, revoked_at |
| app_sessions | Revocable login sessions | id, user_id, token_hash, issued_at, expires_at, revoked_at |
| employee_payout_destinations | Independently reviewed payment destinations | id, employee_id mobile FK, method, destination_ref, verification_status, verified_by, valid_from, valid_to |
| recruitment_candidates | Applicant pipeline | id, contact_ref, name_assertion, stage, post_intake_status, linked_employee_id NULL, created_at |
| recruitment_events | Preserved intake/joining events | id, candidate_id, event_type, occurred_at, evidence_ref, actor_id, details |
| attendance_entries | Verified duty attendance | id, employee_id mobile FK, program_id NULL, duty_date, shift, attendance_status, evidence_ref, review_id |
| release_slips | Reviewed release evidence | id, program_id, employee_id, media_asset_id, ocr_status, extracted_fields, verified_release_date NULL, reviewed_by NULL |
| settlement_items | Reviewed settlement calculations | id, settlement_draft_id FK, program_id, employee_id, duty_days, rate_minor, currency, food_minor, advance_minor, net_minor, calculation_version |
| cash_transactions | Proposed canonical cash postings | id, transaction_kind, employee_id NULL, amount_minor, currency, occurred_at, method, source_ref, approval_id, idempotency_key UNIQUE, reversal_of NULL, created_by |
| income_transactions | Canonical incoming receipts | id, client_id, amount_minor, currency, received_at, method, invoice_id NULL, source_ref, idempotency_key UNIQUE |
| payroll_batches | Period calculation/review | id, period_start, period_end, status, calculation_version, approved_by NULL, approved_at NULL |
| payroll_items | Employee amounts in a batch | id, batch_id, employee_id, earned_minor, advance_minor, deduction_minor, net_minor, currency, evidence_refs |
| clients / client_billing_profiles | Client and effective billing terms | id, display_name, contact_ref; id, client_id, service_type, rate_minor, currency, valid_from, valid_to |
| invoices / invoice_items | Reviewed service billing | id, client_id, invoice_number, issue_date, due_date, status; id, invoice_id, program_id, quantity, rate_minor, amount_minor, currency |
| business_approvals | Shared exact-action approval | id, action_type, payload_hash, requested_by, approved_by NULL, status, expires_at, executed_at NULL, result_ref NULL |
| audit_events | Append actor/action/evidence history | id, actor_id, action_type, entity_type, entity_id, before_hash NULL, after_hash NULL, evidence_refs, occurred_at, trace_id |

Use existing payment/settlement draft tables via additive typed extensions or reviewed child tables; do not introduce competing draft authorities. business_approvals is the shared approval anchor for sends, AI proposals and financial operations. Establish its ownership once before dependent migrations.

A settlement approval is not payment completion; a PAID message is not a verified transfer; a release slip is not automatic program completion. Confirmed -> Assigned/Active -> Released -> Completed requires separate evidence. Ghat-duty patterns propose review, never silently post wages. Financial rows are append/reversal based, not destructive edits. Currency precision and company accounting policy must be settled before posting; this is not a double-entry general ledger design.

## Implementation sequence and constraints

1. Preserve snapshots and read-only app behavior. Qualify existing employee/program candidate and reader compatibility without assuming approval for production import.
2. Add private account-scoped message projection, authentication/RBAC and human review UI.
3. Integrate vessel/employee identity and evidence-linked program views; historical snapshots remain separate from live observations.
4. Add release/attendance/settlement drafts, then reviewed financial/payroll/billing features. Deploy writes through distinct least-privilege service roles; app's read-only default stays meaningful.
5. Add AI drafts after the business facts, source scopes and exact approval path work.

Use FKs compatible with existing TEXT IDs, unique payroll batch/employee keys, money nonnegative checks with explicit direction/reversal semantics, date-order checks, indexes for mobile/date/program lookups and transaction locks for competing approval/posting actions. Existing immutable ep facts remain append-only; newer domain workflows use reviewed events/projections rather than mutating frozen evidence. Use one migration ledger and a disposable test database on existing PostgreSQL, followed by logical backup, reader acceptance and controlled deployment. Never import all Fazle Core schema or enable auto-send as a shortcut.
