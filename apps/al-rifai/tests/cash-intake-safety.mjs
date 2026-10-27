import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseLivePaymentBlocks,liveSourceIdentity,isLiveCashOwnerOutgoing} from '../candidates/identity-review/live-cash.ts';
import {cashScopeWhere,CASH_SCOPE_ACCOUNT,CASH_SCOPE_CHAT,CASH_SCOPE_CHAT_LID,CASH_SCOPE_NAME,isCashScopeChat,isCashScopeOwner} from '../lib/cash-scope.ts';

test('cash parser requires two mobile numbers, name, method and amount',()=>{
 const rows=parseLivePaymentBlocks('ID: 01312345678 Rahim Uddin 01712345678 (B) 1,250/- food');
 assert.equal(rows.length,1);
 assert.equal(rows[0].fields.employeeMobile,'+8801312345678');
 assert.equal(rows[0].fields.payoutMobile,'+8801712345678');
 assert.equal(rows[0].fields.amountMinor,'125000');
});

test('name-only and incomplete payment text never creates a cash block',()=>{
 assert.deepEqual(parseLivePaymentBlocks('Rahim Uddin (B) 1,250/- food'),[]);
 assert.deepEqual(parseLivePaymentBlocks('ID: 01312345678 Rahim Uddin (B) 1,250/- food'),[]);
});

test('same source message and block have stable idempotency identity',()=>{
 assert.equal(liveSourceIdentity('message-1','payment-block-0'),liveSourceIdentity('message-1','payment-block-0'));
 assert.notEqual(liveSourceIdentity('message-1','payment-block-0'),liveSourceIdentity('message-1','payment-block-1'));
 assert.notEqual(liveSourceIdentity('message-1','payment-block-0'),liveSourceIdentity('message-2','payment-block-0'));
 // PN and LID are one logical Accountant conversation: the source identity must
 // collapse to a single record so a replayed message cannot post twice.
 assert.equal(liveSourceIdentity('message-1','payment-block-0',CASH_SCOPE_CHAT),liveSourceIdentity('message-1','payment-block-0',CASH_SCOPE_CHAT_LID));
});

test('Accountant PN and native LID remain one explicitly scoped Cash chat',()=>{
 assert.equal(isCashScopeChat(CASH_SCOPE_CHAT),true);
 assert.equal(isCashScopeChat(CASH_SCOPE_CHAT_LID),true);
 assert.equal(isCashScopeOwner('8801880446111@s.whatsapp.net'),true);
 assert.equal(isCashScopeOwner('93282931581172:27@lid'),true);
 assert.equal(isCashScopeChat('120363428977781821@g.us'),false);
});

test('owner direction and recipient scope reject wrong transport identities',()=>{
 // The live reader now yields native records: eligibility is decided on the
 // bridge envelope, never on a caller-supplied message object.
 const envelope={version:'native-message-envelope-v1',provider:'WHATSAPP',accountId:'wa-01',nativeMessageId:'m',chatJid:CASH_SCOPE_CHAT_LID,chatType:'direct',senderJid:'93282931581172:27@lid',senderPhone:null,senderLid:null,direction:'OUTGOING',sourceTimestamp:'2026-10-17T06:57:48.000Z',observedAt:'2026-10-17T06:57:49.000Z',eventType:'TEXT',payload:{text:'',sha256:'a'.repeat(64)},quotedMessageId:null,forwarded:null,media:[],groupDisplayName:null,membershipEvidence:null};
 assert.equal(isLiveCashOwnerOutgoing({status:'CONTENT',envelope}),true);
 assert.equal(isLiveCashOwnerOutgoing({status:'CONTENT',envelope:{...envelope,direction:'INCOMING'}}),false);
 assert.equal(isLiveCashOwnerOutgoing({status:'CONTENT',envelope:{...envelope,senderJid:'8801844836824@s.whatsapp.net'}}),false);
 assert.equal(isLiveCashOwnerOutgoing({status:'CONTENT',envelope:{...envelope,chatJid:'120363428977781821@g.us'}}),false);
 assert.equal(isLiveCashOwnerOutgoing({status:'NON_CONTENT',envelope:null}),false);
});

test('cash API scope is server-owned and traceable',()=>{
 const clauses=cashScopeWhere('i').join(' AND ');
 assert.match(clauses,/i\.scope_account = 'wa-01'/);
 assert.match(clauses,/i\.cash_account = 'Cash Payment'/);
 assert.equal(CASH_SCOPE_ACCOUNT,'wa-01');
 assert.match(CASH_SCOPE_CHAT,/@s\.whatsapp\.net$/);
 assert.equal(CASH_SCOPE_NAME,'Cash Payment');
 const route=readFileSync(new URL('../app/api/cash/[...path]/route.ts',import.meta.url),'utf8');
 for(const field of ['i.source_ref','i.command_id','i.state','i.reasons','s.chat_jid','s.message_id','s.original_sender_ref','AS review','AS posted_minor'])assert.match(route,new RegExp(field.replaceAll('.','\\.')));
});

test('live intake remains review-only and has no financial posting path',()=>{
 const source=readFileSync(new URL('../candidates/identity-review/live-cash.ts',import.meta.url),'utf8');
 const publisher=readFileSync(new URL('../lib/cash-publish.ts',import.meta.url),'utf8');
 assert.match(source,/mode!=='APPROVED_REVIEW_ONLY'/);
 assert.match(publisher,/FINANCIAL_POSTING_REQUIRES_SEPARATE_APPROVAL/);
 assert.match(publisher,/,\s*'REVIEW'/);
 assert.doesNotMatch(source,/APPROVED_AUTO_POST|alrifai_post_owner_accountant_cash/);
 assert.doesNotMatch(publisher,/APPROVED_AUTO_POST|alrifai_post_owner_accountant_cash/);
 assert.match(source,/LIVE_CASH_ACCOUNTANT_BINDING_REQUIRED/);
 assert.match(publisher,/message_id=\$2/);
});
