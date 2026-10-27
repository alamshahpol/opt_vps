// Canonical Cash publication for the single verified Admin -> Accountant stream.
//
// One code path is used by live capture and by the historical backfill, so both
// produce identical source/operation/instruction identifiers for the same
// message. A message replayed through the Accountant's other addressing form
// (PN vs LID) therefore collapses onto one record instead of creating a second
// financial instruction.
//
// Financial safety: this module only writes REVIEW-state instructions. It never
// posts, confirms, approves or settles anything.

import type pg from 'pg';
import {digest} from '../candidates/identity-review/contracts.ts';
import {CASH_SCOPE_ACCOUNTANT} from './cash-scope.ts';

export const CASH_EPOCH_CURRENT = 'CANONICAL_BACKFILL_20261026';
export const CASH_EPOCH_ARCHIVE = 'LEGACY_PRE_TRANSITION_20261026';

export type CashBlockFields = {
  employeeMobile: string;
  employeeName: string;
  payoutMobile: string;
  method: 'cash' | 'bkash' | 'nagad' | 'bank' | 'rocket';
  amountMinor: string;
  purpose: string;
};

export type CashBlock = { blockKey: string; blockOrder: number; fields: CashBlockFields };

export type CashPublishInput = {
  account: string;
  chatJid: string;
  messageId: string;
  sender: string;
  sourceTime: string;
  sourceHash: string;
  cashAccount: string;
  epoch: string;
  block: CashBlock;
  /** Verified Admin/Accountant binding reference; omitted only for backfill. */
  command?: { action: string; actorRef: string; actorBindingRef: string; authEpoch: number };
};

export function cashSourceIds(messageId: string, blockKey: string, account: string) {
  const source = digest(['live-owner-accountant-source-v2', account, CASH_SCOPE_ACCOUNTANT, messageId, blockKey]);
  const operation = digest(['live-owner-accountant-operation-v2', account, CASH_SCOPE_ACCOUNTANT, messageId, blockKey]);
  return {
    source,
    operation,
    instruction: digest(['live-owner-accountant-instruction', operation]),
    command: digest(['live-owner-accountant-command', operation]),
  };
}

/**
 * Publishes one parsed payment block. Returns 'written', 'duplicate' (same epoch)
 * or throws on a source replay conflict. The caller owns no transaction.
 */
export async function publishCashBlock(
  pool: pg.Pool,
  input: CashPublishInput,
): Promise<'written' | 'duplicate'> {
  const ids = cashSourceIds(input.messageId, input.block.blockKey, input.account);
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [ids.operation]);

    // Idempotency is per provenance epoch: an archived pre-transition record must
    // never suppress the canonical record for the same source message, and a
    // replayed canonical message must never create a second instruction.
    const duplicate = (await client.query(
      `SELECT 1
         FROM public.source_refs s
         JOIN public.cash_instructions ci
           ON ci.scope_account=s.scope_account AND ci.source_ref=s.id
        WHERE s.scope_account=$1 AND s.source_kind='LIVE_OWNER_ACCOUNTANT_PAYMENT'
          AND s.message_id=$2 AND s.block_key=$3 AND ci.dataset_epoch=$4
        LIMIT 1`,
      [input.account, input.messageId, input.block.blockKey, input.epoch],
    )).rows[0];
    if (duplicate) {
      await client.query('ROLLBACK');
      return 'duplicate';
    }

    const payload = {
      accountId: input.account,
      chatJid: input.chatJid,
      messageId: input.messageId,
      sender: input.sender,
      direction: 'OUTGOING' as const,
      recipientChatJid: CASH_SCOPE_ACCOUNTANT,
      sourceHash: input.sourceHash,
      blockKey: input.block.blockKey,
      ...input.block.fields,
      cashAccount: input.cashAccount,
    };
    const payloadHash = digest(payload);

    const command = input.command ?? {
      action: 'CASH_OWNER_ACCOUNTANT_INTENT_CAPTURE',
      actorRef: process.env.ALRIFAI_CASH_OWNER_PERSON_REF || 'unbound-owner',
      actorBindingRef: process.env.ALRIFAI_CASH_OWNER_BINDING_REF || 'unbound-owner-binding',
      authEpoch: 1,
    };
    await client.query(
      `INSERT INTO public.business_commands
       (id,scope_account,source_ref,operation_key,payload_hash,action,actor_ref,actor_binding_ref,auth_epoch,expected_resource_version,confirmation_basis,result_ref,result_hash,committed_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,1,'ADMIN_DIRECT',$10,$5,$11)
       ON CONFLICT (scope_account,operation_key) DO NOTHING`,
      [ids.command, input.account, ids.source, `cash-owner-accountant:${ids.operation}`, payloadHash,
        command.action, command.actorRef, command.actorBindingRef, command.authEpoch, ids.instruction, input.sourceTime],
    );
    // A changed body for an already-recorded source must conflict, never silently
    // revise financial evidence.
    const prior=(await client.query('SELECT payload_hash FROM public.source_refs WHERE scope_account=$1 AND id=$2',[input.account,ids.source])).rows[0] as {payload_hash:string}|undefined;
    if(prior&&prior.payload_hash!==payloadHash)throw new Error('LIVE_SOURCE_REPLAY_CONFLICT');
    await client.query(
      `INSERT INTO public.source_refs
       (id,scope_account,created_command_id,channel,provider,chat_jid,message_id,source_kind,external_ref,block_key,payload_hash,source_time,observed_at,original_sender_ref,submitted_by_ref,origin_state,visibility_state)
       VALUES ($1,$2,$3,'WHATSAPP','WHATSAPP_NATIVE_BRIDGE',$4,$5,'LIVE_OWNER_ACCOUNTANT_PAYMENT',$6,$7,$8,$9,now(),$10,$10,'PROVEN','VISIBLE')
       ON CONFLICT (scope_account,id) DO NOTHING`,
      [ids.source, input.account, ids.command, input.chatJid, input.messageId,
        `${input.account}|${CASH_SCOPE_ACCOUNTANT}|${input.messageId}`, input.block.blockKey, payloadHash,
        input.sourceTime, input.sender],
    );
    await client.query(
      `INSERT INTO public.cash_instructions
       (id,operation_id,scope_account,source_ref,command_id,source_time,block_order,employee_mobile,employee_name,payout_mobile,purpose,method,amount_minor,state,reasons,payload_hash,cash_account,dataset_epoch)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'REVIEW',$14::jsonb,$15,$16,$17)
       ON CONFLICT (id) DO NOTHING`,
      [ids.instruction, ids.operation, input.account, ids.source, ids.command, input.sourceTime,
        input.block.blockOrder, input.block.fields.employeeMobile, input.block.fields.employeeName,
        input.block.fields.payoutMobile, input.block.fields.purpose, input.block.fields.method,
        input.block.fields.amountMinor, '["FINANCIAL_POSTING_REQUIRES_SEPARATE_APPROVAL"]',
        payloadHash, input.cashAccount, input.epoch],
    );
    await client.query(
      `INSERT INTO public.employee_master
       (scope_account,employee_mobile,preferred_name,name_aliases,state,first_seen_at,last_seen_at,updated_at)
       VALUES ($1,$2,$3,ARRAY[$3]::text[],'REVIEW',$4,$4,now())
       ON CONFLICT (scope_account,employee_mobile) DO UPDATE SET
        preferred_name=CASE WHEN EXCLUDED.last_seen_at>=employee_master.last_seen_at THEN EXCLUDED.preferred_name ELSE employee_master.preferred_name END,
        name_aliases=(SELECT array_agg(DISTINCT n ORDER BY n) FROM unnest(employee_master.name_aliases||EXCLUDED.name_aliases) AS n),
        first_seen_at=LEAST(employee_master.first_seen_at,EXCLUDED.first_seen_at),
        last_seen_at=GREATEST(employee_master.last_seen_at,EXCLUDED.last_seen_at),
        updated_at=now()`,
      [input.account, input.block.fields.employeeMobile, input.block.fields.employeeName, input.sourceTime],
    );
    await client.query('COMMIT');
    return 'written';
  } catch (error) {
    await client.query('ROLLBACK').catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}
