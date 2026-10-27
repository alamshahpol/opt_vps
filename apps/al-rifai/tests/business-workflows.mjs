import test from 'node:test';
import assert from 'node:assert/strict';
import {extractStoredMessage,exactMinor} from '../lib/history-extraction.mjs';
import {historyAdmission,extractionScopes} from '../lib/history-policy.mjs';
import {compatibleDraft} from '../candidates/identity-review/history-business.ts';
import {visibleHistorySources} from '../candidates/identity-review/source-visibility.ts';
import {hash} from '../candidates/identity-review/contracts.ts';
import {emptyState} from '../candidates/identity-review/repository.ts';
import {cashAccess} from '../candidates/identity-review/cash-commands.ts';
import {previewCanonicalProgramCommand} from '../lib/program-command-boundary.ts';
const payment='ID: 01712345678 Karim 01812345678 (B) 1,250.50/-';
const message={accountId:'wa-01',chatJid:'8801844836824@s.whatsapp.net',id:'synthetic-message-a',sender:'8801880446111',text:payment+'\nID: invalid sibling\n'+payment,sourceTime:'2026-10-15T02:00:00.000Z',direction:'OUTGOING',deletedAt:null};
const admission={role:'ADMIN',actorRef:'owner',bindingRefs:['owner-binding'],historical:true};
const context={allowed:true,subjectRole:'ACCOUNTANT',subjectRef:'accountant',senderLabel:'Fixture Accountant',admission};
const record=(kind,id,data)=>({kind,id,status:'VERIFIED',version:1,data});
function state(){
 const s=emptyState();s.registry.owner=record('person','owner',{id:'owner',displayName:'Fixture owner'});s.registry.rel=record('relationship','rel',{personId:'owner',kind:'SUPER_ADMIN'});
 s.registry.accountant=record('person','accountant',{id:'accountant',displayName:'Fixture Accountant'});s.registry.ar=record('relationship','ar',{personId:'accountant',kind:'ACCOUNTANT'});
 s.registry.ab=record('binding','ab',{personId:'accountant',accountId:'wa-01',chatJid:message.chatJid,senderJid:'8801844836824',direction:'INCOMING',purpose:'SENDER',validFrom:'2026-01-01T00:00:00Z',validTo:null,evidenceRefs:['fixture']});
 s.registry.ob=record('binding','ob',{personId:'owner',accountId:'wa-01',chatJid:'8801880446111@s.whatsapp.net',senderJid:message.sender,direction:'OUTGOING',purpose:'ACCOUNT_OWNER',validFrom:'2026-01-01T00:00:00Z',validTo:null,evidenceRefs:['fixture']});
 for(const [n,cap,domain] of [[1,'intake.read','IDENTITY'],[2,'review.read','ACCOUNTS'],[3,'evidence.read','ACCOUNTS']])s.registry['g'+n]=record('grant','g'+n,{personId:'owner',channel:'STAFF',capability:cap,scope:{accountId:'wa-01',domain,chatJid:null,resourceId:null}});
 const now=Date.parse(message.sourceTime),token='a'.repeat(64);s.staff.staff={id:'staff',username:'fixture',personId:'owner',passwordHash:'fixture',active:true,version:1,approvalRef:'fixture'};
 s.sessions[hash(token)]={id:hash(token),accountId:'staff',accountVersion:1,personId:'owner',csrfHash:hash('b'.repeat(64)),createdAt:now,lastSeen:now,expiresAt:now+100000};
 return {s,credentials:{token,csrf:'b'.repeat(64)},now};
}
test('multiple payment blocks retain source order, exact BDT and malformed sibling',()=>{
 const rows=extractStoredMessage(message,context);assert.equal(rows.length,3);assert.deepEqual(rows.map(r=>r.assertion.blockOrder),[0,1,2]);assert.equal(rows[0].assertion.fields.amountMinor,'125050');assert.equal(rows[2].assertion.fields.amountMinor,'125050');assert.ok(rows[1].assertion.reasons.includes('EMPLOYEE_ID_UNRESOLVED'));assert.equal(exactMinor('1,000.09'),'100009');assert.equal(exactMinor('1,00'),null);
});
test('incoming Accountant summary and unbound outgoing account do not create payment intents',()=>{
 assert.deepEqual(extractStoredMessage({...message,direction:'INCOMING'},context),[]);assert.deepEqual(extractStoredMessage(message,{...context,admission:{...admission,role:'UNRESOLVED'}}),[]);
});
test('exact replay, distinct equal instructions, parser revision and source edits retain operation identity',()=>{
 const a=extractStoredMessage(message,context),replay=extractStoredMessage(message,context),b=extractStoredMessage({...message,id:'synthetic-message-b'},context),edit=extractStoredMessage({...message,text:message.text.replace('1,250.50','1,300.00')},context);
 assert.deepEqual(a,replay);assert.notEqual(a[0].assertion.operationId,b[0].assertion.operationId);assert.equal(a[0].assertion.operationId,edit[0].assertion.operationId);assert.notEqual(a[0].id,edit[0].id);assert.equal(a[0].assertion.posted,false);
});
test('Admin authority comes from current registry and exact paired owner, never display name',()=>{
 const {s}=state(),scope=extractionScopes(s.registry,'owner','wa-01')[0],native={accountId:'wa-01',pairedJid:'8801880446111@s.whatsapp.net',pairedLid:''};
 assert.equal(historyAdmission(s.registry,message,scope,native).role,'ADMIN');assert.equal(historyAdmission(s.registry,{...message,sender:'123456789012345',chatJid:'120363408741101070@g.us'},scope,{...native,pairedLid:'123456789012345@lid'}).role,'ADMIN');assert.equal(historyAdmission(s.registry,message,scope,{...native,pairedJid:'8801958122300@s.whatsapp.net'}).role,'UNRESOLVED');s.registry.ob.status='REVOKED';assert.equal(historyAdmission(s.registry,message,scope,native).role,'UNRESOLVED');
});
test('group chatter has no lifecycle effect; explicit release preserves exact labelled identity/date',()=>{
 const scope={...context,subjectRole:'APPROVED_GROUP'};assert.deepEqual(extractStoredMessage({...message,text:'Two escorts sick today, arrange staff'},scope),[]);
 const [release]=extractStoredMessage({...message,text:'Employee ID: 01712345678\nRelease Date: 2026-10-15\nEnd Shift: N\nRelease Point: Port\nConveyance: 200.50'},scope);assert.equal(release.assertion.kind,'RELEASE');assert.equal(release.assertion.fields.conveyanceMinor,'20050');
});
test('draft compatibility allows incomplete siblings but does not merge different lighters',()=>{
 assert.equal(compatibleDraft({motherVessel:'MV Test',lighterVessel:'One'},{motherVessel:'Test',lighterVessel:'One'}),true);assert.equal(compatibleDraft({motherVessel:'Test',lighterVessel:'Two'},{motherVessel:'Test',lighterVessel:'One'}),false);
});
test('unknown, revoked, changed and cross-account sources are withheld; current grants rechecked',async()=>{
 const {s,credentials,now}=state(),ref={sourceRef:'a',accountId:'wa-01',chatJid:message.chatJid,messageId:message.id,payloadHash:'a'.repeat(64)};
 for(const proof of [{visibility:'UNKNOWN',payloadHash:ref.payloadHash},{visibility:'REVOKED',payloadHash:ref.payloadHash},{visibility:'VISIBLE',payloadHash:'b'.repeat(64)}])assert.equal((await visibleHistorySources(s,credentials,'wa-01',[ref],()=>now,async()=>({a:proof}))).size,0);
 assert.equal((await visibleHistorySources(s,credentials,'wa-01',[ref],()=>now,async()=>({a:{visibility:'VISIBLE',payloadHash:ref.payloadHash}}))).size,1);
 assert.equal((await visibleHistorySources(s,credentials,'wa-02',[{...ref,accountId:'wa-02'}],()=>now,async()=>({a:{visibility:'VISIBLE',payloadHash:ref.payloadHash}}))).size,0);
 await assert.rejects(visibleHistorySources(s,credentials,'wa-01',[ref],()=>now,async()=>{s.registry.g2.status='REVOKED';return {a:{visibility:'VISIBLE',payloadHash:ref.payloadHash}};}),/HISTORY_SCOPE_DENIED/);
});
test('manual financial posting is default-off and needs a current exact account/domain grant',()=>{
 const {s,credentials,now}=state();delete process.env.ALRIFAI_CASH_POSTING_ENABLED;assert.equal(cashAccess(s,credentials,now).post,false);process.env.ALRIFAI_CASH_POSTING_ENABLED='APPROVED_MANUAL_V1';assert.equal(cashAccess(s,credentials,now).post,false);delete process.env.ALRIFAI_CASH_POSTING_ENABLED;
});
test('canonical confirmation updates the draft and does not assert actual duty',async()=>{
 const before={id:'hist_fixture',motherVessel:'Test',lighterVessel:'One',masterMobile:'',destination:'',escortName:'',escortMobile:'',startDate:'',endDate:'',shift:'',source:'fixture',notes:'',duplicateOf:null,createdAt:message.sourceTime,revision:1,status:'Draft',details:{programCommand:{schemaVersion:'alrifai-program-command-v1',authority:'ALRIFAI_OPERATIONAL_QUALIFICATION_ONLY',scope:{accountId:'wa-01',chatJid:message.chatJid},state:'Draft',primaryReviewId:'primary',employeeId:null,events:[]}}};
 const client={query:async(sql)=>({rows:sql.startsWith('SELECT current_database')?[{database:'alrifai_identity_qualification_existing'}]:sql.includes('FOR UPDATE')?[{record:before,oversized:false}]:[]}),release(){}};
 const context={reviewId:'primary',reviewVersion:1,sourceOccurrenceId:'source',sourceRevision:1,sourceHash:'a'.repeat(64),sourceReferences:['source'],accountId:'wa-01',chatJid:message.chatJid,actorId:'owner',epoch:1,fields:{motherVessel:'Test',lighterVessel:'One',escortName:'Karim',employeeMobile:'+8801712345678',assignmentDate:'2026-10-15',shift:'D'},employee:null,expectedProgramVersion:1,historySource:{sourceRef:'source',operationId:'operation',actorRef:'owner',role:'ADMIN',historical:true,bindingRefs:['binding']},command:{action:'CONFIRM',programId:'hist_fixture',reason:'fixture'}};
 const preview=await previewCanonicalProgramCommand(client,context);assert.equal(preview.after.id,before.id);assert.equal(preview.nextState,'Confirmed');assert.equal(preview.after.revision,2);assert.equal(preview.ledger.dutyStartedOn,undefined);
 await assert.rejects(previewCanonicalProgramCommand(client,{...context,historySource:{...context.historySource,historical:false}}),/HISTORICAL_ADMIN_AUTHORITY_REQUIRED/);
});

test('future approved Escort client is admitted by role and binding, unrelated sender is review',()=>{
 const {s}=state();s.registry.future=record('person','future',{displayName:'Fixture future client'});s.registry.fr=record('relationship','fr',{personId:'future',kind:'CLIENT',clientId:'future-client',serviceKind:'ESCORT'});
 s.registry.fb=record('binding','fb',{...s.registry.ab.data,personId:'future',chatJid:'8801711111111@s.whatsapp.net',senderJid:'8801711111111'});
 for(const [n,cap,domain] of [[4,'review.read','ESCORT'],[5,'evidence.read','ESCORT']])s.registry['g'+n]=record('grant','g'+n,{personId:'owner',channel:'STAFF',capability:cap,scope:{accountId:'wa-01',domain,chatJid:null,resourceId:null}});
 const scope=extractionScopes(s.registry,'owner','wa-01').find(v=>v.subjectRef==='future');assert.ok(scope);
 const m={...message,chatJid:scope.chatJid,sender:'8801711111111',direction:'INCOMING'};
 assert.equal(historyAdmission(s.registry,m,scope,{}).role,'CLIENT');assert.equal(historyAdmission(s.registry,{...m,sender:'8801799999999'},scope,{}).role,'UNRESOLVED');
});
test('explicit actual start/replacement reuse lifecycle parser while dates remain source facts',()=>{
 const [row]=extractStoredMessage({...message,text:'Event: Actual Duty Start\nProgram ID: hist_fixture\nEmployee ID: 01712345678\nActual Start Date: 2026-10-15'},{...context,subjectRole:'CLIENT'});
 assert.equal(row.assertion.fields.lifecycleAction,'DUTY_START');assert.equal(row.assertion.fields.actualStartDate,'2026-10-15');assert.equal(row.assertion.fields.employeeMobile,'+8801712345678');
});
import {calculateSourceDuty} from '../lib/duty-calculation.mjs';
test('duty uses explicit attendance, dated rate and policy version; missing evidence never defaults',()=>{
 const assignment={employeeMobile:'+8801712345678',actualStart:'2026-10-15',releaseDate:'2026-10-15'};
 const inputs={assignment,attendance:[{employeeMobile:assignment.employeeMobile,date:'2026-10-15',shift:'D',verified:true,sourceRef:'attendance-a'}],rates:[{employeeMobile:assignment.employeeMobile,validFrom:'2026-10-01',validTo:null,halfDayMinor:'125050',verified:true,sourceRef:'rate-a',version:'rate-v1'}],policy:{verified:true,version:'fixture-policy-v1',unit:'HALF_DAY',rounding:'EXACT_MINOR'},conveyanceMinor:'20050'};
 assert.equal(calculateSourceDuty(inputs).payableMinor,'145100');assert.equal(calculateSourceDuty({...inputs,rates:[]}).state,'UNRESOLVED');assert.equal(calculateSourceDuty({...inputs,attendance:[]}).payableMinor,null);
});
