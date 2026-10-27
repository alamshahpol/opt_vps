-- PREPARED MIGRATION CANDIDATE — NOT APPLIED TO PRODUCTION.
--
-- Purpose: append-only Cash submission review decisions. Submission is not
-- approval; approval is not financial posting. Nothing here writes
-- cash_postings, cash_movements or any ledger fact.
--
-- Review required before application:
--   * Owner authorization for the exact schema/grants;
--   * isolated migration rehearsal against a restored clone;
--   * confirmation that `cash_instructions` remains append-only and that no
--     UPDATE/DELETE grant is introduced anywhere.

BEGIN;

CREATE TABLE public.cash_instruction_reviews (
  id text PRIMARY KEY CHECK (id ~ '^[a-f0-9]{64}$'),
  scope_account text NOT NULL CHECK (scope_account IN ('wa-01','wa-02')),
  instruction_id text NOT NULL REFERENCES public.cash_instructions(id),
  decision text NOT NULL CHECK (decision IN ('APPROVED','REJECTED','CORRECTION_REQUESTED')),
  actor_user_ref text NOT NULL REFERENCES public.cash_portal_users(id),
  actor_role text NOT NULL CHECK (actor_role IN ('ADMIN','USER')),
  note text NOT NULL DEFAULT '' CHECK (length(note) <= 1000),
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[a-f0-9]{64}$'),
  decided_at timestamptz NOT NULL DEFAULT now(),
  -- A submission and its reviewer must be different people.
  CONSTRAINT reviewer_not_submitter CHECK (actor_user_ref <> submitted_by_user_ref),
  submitted_by_user_ref text NOT NULL REFERENCES public.cash_portal_users(id)
);

-- Fundamental integrity: no mutation of a recorded decision, ever.
CREATE TRIGGER cash_instruction_reviews_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.cash_instruction_reviews
  FOR EACH STATEMENT EXECUTE FUNCTION public.alrifai_foundation_append_only();

REVOKE ALL ON public.cash_instruction_reviews FROM PUBLIC;
GRANT SELECT, INSERT ON public.cash_instruction_reviews TO ir_review_runtime;

-- Read-time projection. The newest decision per instruction; absent rows mean
-- PENDING_REVIEW. Approval here never implies a ledger posting.
CREATE VIEW public.cash_instruction_review_state AS
SELECT i.id AS instruction_id,
       i.scope_account,
       i.state AS instruction_state,
       r.decision,
       r.actor_user_ref AS decided_by,
       r.decided_at,
       CASE
         WHEN r.decision IS NULL THEN 'PENDING_REVIEW'
         WHEN r.decision = 'APPROVED' THEN 'ACTIVE_REVIEWED'
         WHEN r.decision = 'REJECTED' THEN 'REJECTED'
         ELSE 'CORRECTION_REQUESTED'
       END AS review_state
FROM public.cash_instructions i
LEFT JOIN LATERAL (
  SELECT decision, actor_user_ref, decided_at
  FROM public.cash_instruction_reviews r
  WHERE r.instruction_id = i.id AND r.scope_account = i.scope_account
  ORDER BY r.decided_at DESC, r.id DESC
  LIMIT 1
) r ON true;

REVOKE ALL ON public.cash_instruction_review_state FROM PUBLIC;
GRANT SELECT ON public.cash_instruction_review_state TO ir_review_runtime;

COMMIT;
