// Historical backfill for the seven Owner-approved WA-01 conversations.
//
// Stage first, reconcile, then publish canonical records. Cash publication uses
// the same code path as live capture (lib/cash-publish.ts), so a message can
// never produce two financial instructions. Vessel rows are only queued for the
// existing review processor: nothing is approved, released or posted here.
//
// Run: node --experimental-strip-types scripts/backfill-approved.mjs <batch-id>

import {createHash} from 'node:crypto';
import {createPool} from '../db/postgres.mjs';
import {loadConversationScope} from '../lib/conversation-scope.ts';
import {parseLivePaymentBlocks} from '../candidates/identity-review/live-cash.ts';
import {publishCashBlock,CASH_EPOCH_CURRENT} from '../lib/cash-publish.ts';
import {isCashScopeOwner,CASH_SCOPE_NAME} from '../lib/cash-scope.ts';

const batchId = process.argv[2] ?? 'backfill-20261026';
const hex = (value) => createHash('sha256').update(value).digest('hex');
const sha = (value) => hex(JSON.stringify(value, Object.keys(value).sort()));

// The bridge-resolved JID is authoritative when present. The original LID/PN is
// always retained in raw_content, so nothing is lost by preferring the resolved
// form here.
const senderJidOf = (row) => {
  const raw = row.raw_content ?? {};
  const resolved = typeof raw.resolvedSenderJid === 'string' ? raw.resolvedSenderJid : null;
  if (resolved && resolved.includes('@')) return resolved;
  if (!row.sender_bare) return null;
  const bridge = typeof raw.bridgeSender === 'string' ? raw.bridgeSender : '';
  if (bridge.includes('@')) return bridge;
  // A 13-digit 8801… value is a subscriber number; a longer numeric identifier is
  // a LID and must never be rewritten into a phone number.
  return row.sender_bare.length <= 13 ? `${row.sender_bare}@s.whatsapp.net` : `${row.sender_bare}@lid`;
};

const loader = createPool({readOnly: false});
const publisher = createPool({readOnly: false, user: 'ir_review_runtime'});

const tally = {
  scanned: 0, inserted: 0, cashEligible: 0, cashPublished: 0,
  cashDuplicate: 0, vesselQueued: 0, archiveQueued: 0, unmatched: 0, reviewQueued: 0,
};

async function main() {
  const scope = await loadConversationScope({
    query: (sql, values) => loader.query(sql, values),
  });
  console.log(`approved conversations: ${scope.conversations.length}`);

  const runId = hex(`backfill|${batchId}`).slice(0, 40);
  await loader.query(
    `INSERT INTO public.wa01_backfill_runs (id,batch_id,scope,status,notes)
     VALUES ($1,$2,$3::jsonb,'STAGED','{}'::jsonb)
     ON CONFLICT (id) DO UPDATE SET status='STAGED'`,
    [runId, batchId, JSON.stringify(scope.conversations.map((c) => ({
      chatJid: c.canonicalChatJid, domain: c.domain, type: c.conversationType,
    })))],
  );

  const rows = (await loader.query(
    `SELECT * FROM public.wa01_backfill_staging WHERE batch_id=$1 ORDER BY chat_jid,source_time`,
    [batchId],
  )).rows;
  console.log(`staged messages: ${rows.length}`);

  for (const row of rows) {
    tally.scanned += 1;
    const conversation = scope.byChat(row.chat_jid);
    if (!conversation) { tally.unmatched += 1; continue; }

    const incomingSenderJid = senderJidOf(row);
    const inserted = (await loader.query(
      `INSERT INTO public.whatsapp_messages_original
       (wa_account,chat_jid,chat_type,message_id,direction,sender_jid,sender_phone,
        sender_push_name,receiver_jid,group_name,timestamp,message_type,raw_content,
        text_content,media_ref,ingested_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14,$15,now())
       ON CONFLICT (wa_account,chat_jid,message_id) DO NOTHING
       RETURNING id`,
      [row.account_id, row.chat_jid, row.chat_type, row.message_id, row.direction,
        incomingSenderJid, row.sender_phone,
        row.sender_push_name, row.receiver_jid, row.group_name, row.source_time,
        row.message_type, JSON.stringify(row.raw_content), row.text_content, row.media_ref],
    )).rows[0];
    // A message already present keeps its original row: the backfill never rewrites
    // stored evidence. It is still routed through processing so that no approved
    // message escapes Cash/Vessel extraction merely because it arrived earlier.
    const originalId = inserted?.id ?? (await loader.query(
      `SELECT id FROM public.whatsapp_messages_original
        WHERE wa_account=$1 AND chat_jid=$2 AND message_id=$3`,
      [row.account_id, row.chat_jid, row.message_id],
    )).rows[0]?.id;
    if (!originalId) { tally.unmatched += 1; continue; }
    if (inserted) tally.inserted += 1;

    await loader.query(
      `INSERT INTO public.whatsapp_messages_processing (original_id,domain,status,processed_content,processed_at)
       VALUES ($1,'archive','processed',$2::jsonb,now())
       ON CONFLICT (original_id,domain) DO NOTHING`,
      [originalId, JSON.stringify({version: 'immutable-original-archive-v1', sourceMode: 'wa01-store-backfill'})],
    );
    await loader.query(
      `INSERT INTO public.whatsapp_messages_processing (original_id,domain,status)
       VALUES ($1,'cash','pending') ON CONFLICT (original_id,domain) DO NOTHING`,
      [originalId],
    );
    if (conversation.domain === 'VESSEL') {
      const queued = await loader.query(
        `INSERT INTO public.whatsapp_messages_processing (original_id,domain,status)
         VALUES ($1,'vessel','pending') ON CONFLICT (original_id,domain) DO NOTHING RETURNING id`,
        [originalId],
      );
      if (queued.rowCount) tally.vesselQueued += 1;
    }

    if (conversation.domain !== 'CASH') continue;
    // Cash eligibility is unchanged and strict: a verified Owner/Admin outgoing
    // message in the designated Accountant direct chat only.
    if (row.direction !== 'outgoing' || !row.sender_bare || !isCashScopeOwner(row.sender_bare)) continue;
    const blocks = parseLivePaymentBlocks(row.text_content ?? '');
    if (!blocks.length) continue;
    tally.cashEligible += 1;

    const sourceHash = sha({
      accountId: row.account_id, chatJid: row.chat_jid, id: row.message_id,
      sender: senderJidOf(row), text: row.text_content ?? '',
      sourceTime: new Date(row.source_time).toISOString(), direction: 'OUTGOING', deletedAt: null,
    });
    for (const block of blocks) {
      try {
        const outcome = await publishCashBlock(publisher, {
          account: row.account_id,
          chatJid: row.chat_jid,
          messageId: row.message_id,
          sender: senderJidOf(row) ?? `${row.sender_bare}@s.whatsapp.net`,
          sourceTime: new Date(row.source_time).toISOString(),
          sourceHash,
          cashAccount: CASH_SCOPE_NAME,
          epoch: CASH_EPOCH_CURRENT,
          block,
        });
        if (outcome === 'written') tally.cashPublished += 1; else tally.cashDuplicate += 1;
      } catch (error) {
        if (error instanceof Error && /LIVE_SOURCE_REPLAY_CONFLICT/.test(error.message)) {
          tally.reviewQueued += 1; continue;
        }
        throw error;
      }
    }
  }

  await loader.query(
    `UPDATE public.wa01_backfill_runs SET status='PUBLISHED',finished_at=now(),
       scanned=$2,inserted=$3,cash_eligible=$4,cash_published=$5,cash_duplicate=$6,
       vessel_queued=$7,unmatched=$8,review_queued=$9
     WHERE id=$1`,
    [runId, tally.scanned, tally.inserted, tally.cashEligible, tally.cashPublished,
      tally.cashDuplicate, tally.vesselQueued, tally.unmatched, tally.reviewQueued],
  );
  console.log(JSON.stringify({batchId, ...tally}, null, 2));
}

main()
  .then(async () => { await loader.end(); await publisher.end(); })
  .catch(async (error) => {
    console.error('backfill failed:', error instanceof Error ? error.message : error);
    await loader.end().catch(() => undefined);
    await publisher.end().catch(() => undefined);
    process.exitCode = 1;
  });
