-- Isolated rehearsal for db/migration-candidates/0032_vessel_program_commands.sql
-- Run only against a throwaway PostgreSQL clone. Never against production.
\set ON_ERROR_STOP on

-- Seed a VERIFIED person actor (identity registry shape).
INSERT INTO identity_review_candidate.records(collection,id,payload)
VALUES ('registry','person-1','{"kind":"person","status":"VERIFIED"}'::jsonb);

-- 1. Add program through the command layer.
SELECT public.alrifai_vessel_program_add(
  'program-1','MV. Alpha Unity','MV. Light One','01829984145','O/A To Local','Md. Osman','01754334400','2026-10-03','D','person-1','initial') AS add_result;

-- 2. Edit, release, assign, replace and void all bump revision by one.
SELECT public.alrifai_vessel_program_update('program-1','{"destination":"Chattogram"}'::jsonb,'person-1','destination fix') AS edit_result;
SELECT public.alrifai_vessel_program_release('program-1','2026-10-06','N','O/A To Local','person-1','{"source":"test"}'::jsonb) AS release_result;
SELECT public.alrifai_vessel_program_assign('program-1','01754334400','2026-10-03','D','person-1',false,'initial assignment') AS assign_result;
SELECT public.alrifai_vessel_program_assign('program-1','01754334401','2026-10-04','N','person-1',true,'replacement') AS replace_result;
SELECT public.alrifai_vessel_program_void('program-1','person-1','duplicate order confirmed') AS void_result;

-- 3. Ledger integrity: 6 events, revision 5, program still present, status Voided.
DO $$
DECLARE events integer; revision_value integer; status_value text; assignments integer;
BEGIN
 SELECT jsonb_array_length(details::jsonb->'programCommand'->'events'), revision, status
   INTO events, revision_value, status_value FROM public.programs WHERE id='program-1';
 IF events <> 6 THEN RAISE EXCEPTION 'expected 6 ledger events, got %', events; END IF;
 IF revision_value <> 5 THEN RAISE EXCEPTION 'expected revision 5, got %', revision_value; END IF;
 IF status_value <> 'Voided' THEN RAISE EXCEPTION 'expected Voided, got %', status_value; END IF;
 SELECT count(*) INTO assignments FROM public.program_assignments WHERE program_id='program-1';
 IF assignments <> 2 THEN RAISE EXCEPTION 'expected 2 assignment revisions, got %', assignments; END IF;
END $$;

-- 4. No destructive delete path exists; DELETE is not granted to the runtime role.
SET ROLE ir_review_runtime;
DO $$
BEGIN
 BEGIN
  UPDATE public.programs SET "motherVessel"='direct write' WHERE id='program-1';
  RAISE EXCEPTION 'broad UPDATE unexpectedly allowed';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;
DO $$
BEGIN
 BEGIN
  DELETE FROM public.programs WHERE id='program-1';
  RAISE EXCEPTION 'DELETE unexpectedly allowed';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;
RESET ROLE;

-- 5. Actor verification fails closed for unverified actors.
DO $$
BEGIN
 BEGIN
  PERFORM public.alrifai_vessel_program_void('program-1','person-unknown','should fail');
  RAISE EXCEPTION 'unverified actor was accepted';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM NOT LIKE '%VERIFIED_ACTOR_REQUIRED%' THEN RAISE; END IF;
 END;
END $$;

-- 6. Cash is untouched by every vessel command.
DO $$
DECLARE instructions integer; postings integer;
BEGIN
 SELECT count(*) INTO instructions FROM public.cash_instructions;
 SELECT count(*) INTO postings FROM public.cash_postings;
 IF instructions <> 0 OR postings <> 0 THEN RAISE EXCEPTION 'vessel commands touched cash'; END IF;
END $$;

SELECT 'VESSEL_COMMANDS_REHEARSAL_OK' AS result;
