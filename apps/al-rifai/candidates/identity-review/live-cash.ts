import {employeeMobile,exactMinor} from '../../lib/history-extraction.mjs';
import {digest} from './contracts.ts';
import type {NativeLivePage,NativeLiveReader} from '../../lib/native-live-reader.ts';
import type pg from 'pg';
import {CASH_SCOPE_ACCOUNT as ACCOUNT,CASH_SCOPE_ACCOUNTANT,CASH_SCOPE_CHAT as CHAT,CASH_SCOPE_NAME as CASH_ACCOUNT,isCashScopeChat,isCashScopeOwner} from '../../lib/cash-scope.ts';
import {publishCashBlock,CASH_EPOCH_CURRENT} from '../../lib/cash-publish.ts';

const phonePattern=/(?:\+?880|00880|0)1[3-9][0-9]{8}(?![0-9])/g;
const digits=(s:string)=>s.normalize('NFC').replace(/[০-৯]/g,c=>String(c.charCodeAt(0)-0x09e6));
const phoneAtStart=(s:string,i:number)=>i===0||!/[0-9]/.test(s[i-1]);

type PaymentFields={employeeMobile:string;employeeName:string;payoutMobile:string;method:'cash'|'bkash'|'nagad'|'bank'|'rocket';amountMinor:string;purpose:string};
type PaymentBlock={blockKey:string;blockOrder:number;fields:PaymentFields};

// Live parser is deliberately narrower than the general review parser: it
// requires employee mobile + name + separate payout mobile + method + amount.
// A missing employee mobile (name-only) is ignored, never treated as a person.
export function parseLivePaymentBlocks(input:string):PaymentBlock[]{
 const text=digits(input),lines=text.split(/\r?\n/),out:PaymentBlock[]=[];
 for(const line of lines){
  const source=line.trim();
  if(!/^\s*(?:ID|Employee\s*ID|আইডি)\s*[:=-]/iu.test(source))continue;
  const phones=[...source.matchAll(phonePattern)].filter(m=>phoneAtStart(source,m.index??0));
  if(phones.length!==2)continue;
  const first=phones[0],second=phones[1];
  const employee=employeeMobile(first[0]),payout=employeeMobile(second[0]);
  if(!employee||!payout)continue;
  const name=source.slice((first.index??0)+first[0].length,second.index??0).trim().replace(/^[\s,:;*-]+|[\s,:;*-]+$/g,'');
  if(!/^[\p{L}\p{M} .'-]{2,100}$/u.test(name))continue;
  const tail=source.slice((second.index??0)+second[0].length);
  const method=/^\s*\(\s*(B|N|C|R|BKASH|NAGAD|CASH|ROCKET|BANK)\s*\)\s*[-:=]?\s*([0-9,]+(?:\.[0-9]{1,2})?)\s*\/-?(?:\s+(.*?))?\s*$/i.exec(tail);
  if(!method)continue;
  const amountMinor=exactMinor(method[2]);
  if(!amountMinor)continue;
  const code=method[1].toUpperCase();
  const methodName=({B:'bkash',BKASH:'bkash',N:'nagad',NAGAD:'nagad',C:'cash',CASH:'cash',R:'rocket',ROCKET:'rocket',BANK:'bank'} as const)[code];
  if(!methodName)continue;
  out.push({blockKey:`payment-block-${out.length}`,blockOrder:out.length,fields:{employeeMobile:employee,employeeName:name,payoutMobile:payout,method:methodName,amountMinor,purpose:(method[3]?.trim()||'Owner direct payment instruction').slice(0,500)}});
 }
 return out;
}

// A record is eligible only when the bridge marked it CONTENT, it carries an
// envelope, the conversation is the approved Accountant chat and the sender is
// the verified Owner/Admin. Group and system rows can never qualify.
export function ownerOutgoing(record:{status:string;envelope:NativeLivePage['records'][number]['envelope']}):LiveMessage|null{
 const e=record.envelope;
 if(record.status!=='CONTENT'||!e)return null;
 if(e.accountId!==ACCOUNT||!isCashScopeChat(e.chatJid)||e.direction!=='OUTGOING'||!isCashScopeOwner(e.senderJid))return null;
 return {id:e.nativeMessageId,chatJid:e.chatJid,sender:e.senderJid,sourceTime:e.sourceTimestamp,text:e.payload?.text??'',direction:e.direction};
}

export const isLiveCashOwnerOutgoing=(record:{status:string;envelope:NativeLivePage['records'][number]['envelope']})=>ownerOutgoing(record)!==null;

export function liveSourceIdentity(messageId:string,blockKey:string,chatJid:string=CHAT){
 void chatJid;
 // Canonical: the Accountant's PN and LID chats are ONE logical conversation, so
 // the source identity deliberately excludes chatJid. A message replayed through
 // the other addressing form collapses onto the same record instead of creating a
 // second financial instruction. Historical rows keep their original identifiers.
 return digest(['live-owner-accountant-source-v2',ACCOUNT,CASH_SCOPE_ACCOUNTANT,messageId,blockKey]);
}


type LiveMessage={id:string;chatJid:string;sender:string;sourceTime:string;text:string;direction:'INCOMING'|'OUTGOING'};

async function writeBlock(pool:pg.Pool,message:LiveMessage,sourceHash:string,block:PaymentBlock){
 // Eligibility is unchanged: only a verified Owner/Admin outgoing message in the
 // approved Accountant direct chat can become a Cash instruction candidate, and
 // only while the verified ACCOUNTANT binding exists for that exact chat.
 const epoch=(await pool.query("SELECT (payload->>'epoch')::bigint AS epoch FROM identity_review_candidate.records WHERE collection='meta' AND id='epoch' FOR SHARE")).rows[0]?.epoch;
 if(epoch===undefined||epoch===null)throw new Error('LIVE_CASH_AUTH_EPOCH_UNAVAILABLE');
 const accountantBinding=(await pool.query(`SELECT EXISTS(
  SELECT 1 FROM identity_review_candidate.records b
  JOIN identity_review_candidate.records r
    ON r.collection='registry' AND r.payload->>'kind'='relationship' AND r.payload->>'status'='VERIFIED'
   AND r.payload->'data'->>'kind'='ACCOUNTANT'
   AND r.payload->'data'->>'personId'=b.payload->'data'->>'personId'
  WHERE b.collection='registry' AND b.payload->>'kind'='binding' AND b.payload->>'status'='VERIFIED'
    AND b.payload->'data'->>'accountId'=$1
    AND b.payload->'data'->>'chatJid'=$2
    AND b.payload->'data'->>'direction'='INCOMING'
    AND b.payload->'data'->>'purpose'='SENDER') AS allowed`,[ACCOUNT,message.chatJid])).rows[0]?.allowed;
 if(accountantBinding!==true)throw new Error('LIVE_CASH_ACCOUNTANT_BINDING_REQUIRED');
 return publishCashBlock(pool,{
  account:ACCOUNT,
  chatJid:message.chatJid,
  messageId:message.id,
  sender:message.sender,
  sourceTime:message.sourceTime,
  sourceHash,
  cashAccount:CASH_ACCOUNT,
  epoch:CASH_EPOCH_CURRENT,
  block,
  command:{
   action:'CASH_OWNER_ACCOUNTANT_INTENT_CAPTURE',
   actorRef:process.env.ALRIFAI_CASH_OWNER_PERSON_REF||'unbound-owner',
   actorBindingRef:process.env.ALRIFAI_CASH_OWNER_BINDING_REF||'unbound-owner-binding',
   authEpoch:Number(epoch),
  },
 });
}

export function startLiveOwnerAccountantCashSync(pool:pg.Pool,reader:NativeLiveReader){
 const mode=process.env.ALRIFAI_LIVE_CASH_INTENT_CAPTURE;
 if(mode!=='APPROVED_REVIEW_ONLY')throw new Error('LIVE_CASH_REVIEW_ONLY_MODE_REQUIRED');
 let running=false;
 const run=async()=>{
  if(running)return;running=true;
  try{
   const channels=(await pool.query('SELECT chat_jid,after_rowid,native_cursor,enabled FROM public.cash_live_sync_channels WHERE scope_account=$1 ORDER BY chat_jid',[ACCOUNT])).rows as {chat_jid:string;after_rowid:string;native_cursor:string|null;enabled:boolean}[];
   for(const channel of channels){
    if(!channel.enabled||!isCashScopeChat(channel.chat_jid))continue;
    try{
     // Activation deliberately returns only a boundary cursor: history comes from
     // the approved backfill, and live continuation starts from the boundary.
     let cursor=channel.native_cursor&&/^n1:[0-9a-f-]{36}:[0-9a-f]{24}:[0-9]+:[0-9]+$/.test(channel.native_cursor)
      ?channel.native_cursor
      :(await reader.activate(ACCOUNT,channel.chat_jid)).nextCursor;
     for(let pageNumber=0;pageNumber<250;pageNumber++){
      const page=await reader.page(ACCOUNT,channel.chat_jid,cursor);
      for(const record of page.records){
       const message=ownerOutgoing(record);
       if(!message)continue;
       const blocks=parseLivePaymentBlocks(message.text);
       const sourceHash=record.envelope?.payload?.sha256??record.semanticHash;
       if(!sourceHash)throw new Error('LIVE_CASH_SOURCE_HASH_UNAVAILABLE');
       for(const block of blocks){
        try{await writeBlock(pool,message,sourceHash,block);}
        catch(error){if(error instanceof Error&&error.message==='LIVE_CASH_ACCOUNTANT_BINDING_REQUIRED')continue;throw error;}
       }
      }
      cursor=page.nextCursor;
      await pool.query('UPDATE public.cash_live_sync_channels SET native_cursor=$3,last_error=NULL,last_processed_at=now(),updated_at=now() WHERE scope_account=$1 AND chat_jid=$2',[ACCOUNT,channel.chat_jid,cursor]);
      if(page.complete)break;
     }
    }catch(error){
     const message=error instanceof Error?error.message:'LIVE_CASH_SYNC_FAILED';
     await pool.query('UPDATE public.cash_live_sync_channels SET last_error=$3,updated_at=now() WHERE scope_account=$1 AND chat_jid=$2',[ACCOUNT,channel.chat_jid,message.slice(0,1000)]).catch(()=>undefined);
    }
   }
  }catch(error){
   const message=error instanceof Error?error.message:'LIVE_CASH_SYNC_FAILED';
   await pool.query('UPDATE public.cash_live_sync_channels SET last_error=$2,updated_at=now() WHERE scope_account=$1',[ACCOUNT,message.slice(0,1000)]).catch(()=>undefined);
  }finally{running=false;}
 };
 void run();
 const timer=setInterval(()=>void run(),5000);timer.unref();
 return {stop:()=>clearInterval(timer)};
}
