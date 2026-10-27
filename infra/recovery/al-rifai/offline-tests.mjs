/**
 * Offline tests only. No database/client/command-execution dependency.
 * Optional stdin bundle allows existing container Node to load approved sources.
 */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {guardInput,assertIdentity,readPlan,decodeFrames,fingerprints,verifyCollected,verifyWithMock,assertSupplemental,TARGET,CLUSTER,ARCHIVE_SHA,CONTAINER,TABLES,CATALOG_KEYS,FINGERPRINTS,VerificationStop} from './verifier.mjs';
import {sha,readEvidenceSet,expectedSnapshots,assertExactSnapshots} from './evidence-readonly.mjs';
const bundled=process.argv.includes('--bundle');
const files=bundled?JSON.parse(readFileSync(0,'utf8')):null;
const text=name=>bundled?files[name]:readFileSync(new URL('./'+name,import.meta.url),'utf8');

// C2 uses synthetic rows only. Historical C1 golden evidence mode is retained,
// but C2 verification must use --synthetic and never read private evidence.
if(process.argv.includes('--synthetic')){
 const b=JSON.parse(text('baseline-attestation.json')),sql=text('read-plan.sql');
 const input={target:TARGET,cluster:CLUSTER,archiveSha:ARCHIVE_SHA};
 const cases=[];
 function test(name,fn){fn();cases.push(name)}
 function blocked(name,fn,code){test(name,()=>assert.throws(fn,e=>e.code===code))}
 test('pinned plan',()=>assert.equal(readPlan(input,b,sql).sqlSHA256,b.readPlanSHA256));
 for(const target of ['alrifai','other',undefined,'',TARGET+';DROP DATABASE alrifai'])
  test('synthetic target guard '+String(target),()=>assert.throws(()=>guardInput({...input,target},b),VerificationStop));
 blocked('cluster mismatch',()=>guardInput({...input,cluster:'wrong'},b),'EXPECTED_CLUSTER');
 blocked('archive mismatch',()=>guardInput({...input,archiveSha:'wrong'},b),'ARCHIVE_IDENTITY');
 blocked('missing baseline',()=>guardInput(input,null),'BASELINE');
 blocked('SQL tampering',()=>readPlan(input,b,sql+' '),'READ_PLAN_CHANGED');
 const expected=[{id:'synthetic',datasetId:'fixture',kind:'chunk',payload:'synthetic-only',contentHash:sha('synthetic-only')}];
 test('synthetic snapshot compare',()=>assertExactSnapshots(structuredClone(expected),expected));
 test('synthetic duplicate rejected',()=>assert.throws(()=>assertExactSnapshots([expected[0],expected[0]],expected)));
 test('synthetic payload rejected',()=>assert.throws(()=>assertExactSnapshots([{...expected[0],payload:'changed'}],expected)));
 const identity={database:TARGET,user:'vps_pg_admin',cluster:CLUSTER,readOnly:'on',version:'16.15'};
 const rows=Object.fromEntries(TABLES.map(t=>[t,[]]));
 const frames=[{label:'identity',rows:[identity]},...TABLES.map(t=>({label:'table:'+t,rows:[]})),...CATALOG_KEYS.map(k=>({label:'catalog:'+k,rows:[]})),{label:'supplemental',rows:[{}]}];
 test('synthetic transport decoder',()=>assert.deepEqual(decodeFrames(frames.map(JSON.stringify).join('\n')).rows,rows));
 let calls=0;
 await assert.rejects(()=>verifyWithMock({...input,target:'alrifai'},b,async()=>{calls++;},expected),e=>e.code==='PRODUCTION_TARGET');
 test('production excluded before mock transport',()=>assert.equal(calls,0));
 let collected=0,rolled=0,closed=0;
 await assert.rejects(()=>verifyWithMock(input,b,async()=>({beginReadOnly:async()=>{},identity:async()=>({...identity,database:'alrifai'}),collect:async()=>{collected++;},rollback:async()=>{rolled++;},close:async()=>{closed++;}}),expected),e=>e.code==='ACTUAL_DATABASE');
 test('wrong identity blocks collection and releases',()=>assert.deepEqual([collected,rolled,closed],[0,1,1]));
 test('synthetic rows cannot qualify golden baseline',()=>assert.throws(()=>verifyCollected(input,b,{identity,rows,catalog:Object.fromEntries(CATALOG_KEYS.map(k=>[k,[]])),supplemental:{}},expected),VerificationStop));
 test('original catalog fingerprint retained',()=>assert.equal(sha(JSON.stringify(JSON.parse(text('baseline-catalog.json')))),FINGERPRINTS.catalog));
 test('no mutation dependencies',()=>assert.ok(!/node:child_process|from ['"]pg['"]/.test(text('verifier.mjs')+text('evidence-readonly.mjs'))));
 test('C2 process boundary present and locked',()=>assert.ok(text('restore-supervisor.py').includes('raise SafetyStop("C2_LIVE_TRANSPORT_LOCKED")')&&text('restore-supervisor.py').includes('class LockedOSBackend')));

 // Load only the exported bridge function; omit its stdin executable wrapper.
 // This exercises actual bridge serialization with synthetic production frames.
 const bridgeSource=text('restore-supervisor.py').match(/NODE_BRIDGE = r"""([\s\S]*?)"""/)[1].split('\ntry {')[0];
 const {comparePacket}=await import('data:text/javascript;base64,'+Buffer.from(bridgeSource).toString('base64'));
 const supplemental={
  database:{owner:'alrifai_app',encoding:'UTF8',collate:'en_US.utf8',ctype:'en_US.utf8',provider:'c',acl:null},
  schema:{owner:'pg_database_owner',acl:'{pg_database_owner=UC/pg_database_owner,=U/pg_database_owner}'},
  function:{owner:'alrifai_app',securityDefiner:false,language:'plpgsql'},
  indexes:TABLES.map(t=>({name:t+'_pkey',valid:true,ready:true})),
  relations:TABLES.map(t=>({name:t,rls:false,forceRls:false,acl:null})),
  extensions:[{name:'plpgsql',version:'1.0'}],
  functions:[{name:'alrifai_reject_snapshot_change',arguments:'',returns:'trigger',owner:'alrifai_app',securityDefiner:false,language:'plpgsql'}],
  schemas:[{name:'public'}],relationKinds:TABLES.flatMap(t=>[{name:t,kind:'r'},{name:t+'_pkey',kind:'i'}]).sort((a,b)=>a.name<b.name?-1:1),
  roles:[{name:'alrifai_app',superuser:false,createDatabase:false,createRole:false,login:true,replication:false,bypassRls:false},{name:'vps_pg_admin',superuser:true,createDatabase:true,createRole:true,login:true,replication:true,bypassRls:true}]
 };
 const productionFrames=structuredClone(frames);productionFrames[0].rows[0].database='alrifai';productionFrames.at(-1).rows=[supplemental];
 const encoded=productionFrames.map(JSON.stringify).join('\n');
 test('C3 production bridge synthetic serialization',()=>assert.deepEqual(comparePacket({mode:'production',frames:encoded}).fingerprints,fingerprints(rows,Object.fromEntries(CATALOG_KEYS.map(k=>[k,[]])))));
 for(const [key,value] of [['database',TARGET],['user','wrong'],['cluster','wrong'],['readOnly','off']]){
  const changed=structuredClone(productionFrames);changed[0].rows[0][key]=value;
  test('C3 production bridge identity '+key,()=>assert.throws(()=>comparePacket({mode:'production',frames:changed.map(JSON.stringify).join('\n')})));
 }
 test('C3 target bridge rejects production before evidence',()=>assert.throws(()=>comparePacket({mode:'target',frames:encoded})));
 test('C3 bridge malformed frame',()=>assert.throws(()=>comparePacket({mode:'production',frames:'PRIVATE_SENTINEL'})));
 test('C3 bridge missing frame',()=>assert.throws(()=>comparePacket({mode:'production',frames:productionFrames.slice(1).map(JSON.stringify).join('\n')})));
 const timestampFrames=structuredClone(productionFrames);
 timestampFrames[1+TABLES.indexOf('alrifai_schema_migrations')].rows=[{id:'fixture',sha256:'fixture',applied_at:'2026-10-08T00:00:00+00:00'}];
 const timestampRows=structuredClone(rows);timestampRows.alrifai_schema_migrations=[{id:'fixture',sha256:'fixture',applied_at:new Date('2026-10-08T00:00:00Z')}];
 test('C3 bridge UTC serialization',()=>assert.deepEqual(comparePacket({mode:'production',frames:timestampFrames.map(JSON.stringify).join('\n')}).fingerprints,fingerprints(timestampRows,Object.fromEntries(CATALOG_KEYS.map(k=>[k,[]])))));
 timestampFrames[1+TABLES.indexOf('alrifai_schema_migrations')].rows[0].applied_at='INVALID';
 test('C3 bridge invalid date rejected',()=>assert.throws(()=>comparePacket({mode:'production',frames:timestampFrames.map(JSON.stringify).join('\n')})));

 // C4 preserves the actual Node bridge and adds a separately locked operation registry.
 const supervisor=text('restore-supervisor.py');
 test('C4 read-only gate unconditionally locked',()=>assert.match(supervisor,/def launch_readonly\(\):\n    raise SafetyStop\('C4_READONLY_INTEGRATION_NOT_AUTHORIZED'\)/));
 test('C4 distinct narrow transport',()=>assert.match(supervisor,/class ReadOnlyTransport:/));
 test('C4 immutable SQL contract',()=>assert.equal(sha(sql),'d3b4a25e19bff52afeb380312ee70097a398cd989bd44a982ceb15d0c6d0d749'));
 test('C4 comparator argv hash bound',()=>assert.ok(supervisor.includes('6f99665c43b029d99e87bc0f7d0dd7d84533b957fac458d93e42c9971f0ff478')));
 test('C4 malformed production serialization',()=>assert.throws(()=>comparePacket({mode:'production',frames:JSON.stringify({label:'identity',rows:'PRIVATE_SENTINEL'})})));
 const wrongVersion=structuredClone(productionFrames);wrongVersion[0].rows[0].version='16.14';
 test('C4 production server version guard',()=>assert.throws(()=>comparePacket({mode:'production',frames:wrongVersion.map(JSON.stringify).join('\n')})));
 test('C4 production supplemental missing',()=>assert.throws(()=>comparePacket({mode:'production',frames:productionFrames.slice(0,-1).map(JSON.stringify).join('\n')})));
 test('C4 unordered production frame',()=>assert.throws(()=>comparePacket({mode:'production',frames:productionFrames.slice().reverse().map(JSON.stringify).join('\n')})));
 console.log(JSON.stringify({status:'PASS',mode:'C4_SYNTHETIC_ONLY',tests:cases.length,cases,liveDatabaseConnections:0,realRestoreCommands:0,privateEvidenceRead:false}));
 process.exit(0);
}

const baseline=JSON.parse(text('baseline-attestation.json')),catalog=JSON.parse(text('baseline-catalog.json')),sql=text('read-plan.sql');
const upstreamHashes=bundled?files._upstreamSHA256:Object.fromEntries(Object.keys(baseline.upstreamSourceSHA256).map(path=>[path,sha(readFileSync(path))]));
assert.deepEqual(upstreamHashes,baseline.upstreamSourceSHA256);
const input={target:TARGET,cluster:CLUSTER,archiveSha:ARCHIVE_SHA};
const results=[];const pass=(name)=>results.push({test:name,result:'PASS'});
function rejects(name,action,code){assert.throws(action,e=>e instanceof VerificationStop&&e.code===code);pass(name)}
guardInput(input,baseline);
const plan=readPlan(input,baseline,sql);
assert.equal(plan.command[plan.command.indexOf('-d')+1],TARGET);
assert.equal(plan.command[plan.command.indexOf('-h')+1],'/var/run/postgresql');
assert.equal(plan.command[plan.command.indexOf('-U')+1],'vps_pg_admin');pass('explicit connection parameters');
rejects('production target',()=>guardInput({...input,target:'alrifai'},baseline),'PRODUCTION_TARGET');
for(const target of [undefined,''])rejects('missing/empty target',()=>guardInput({...input,target},baseline),'MISSING_TARGET');
for(const target of ['postgresql://host/alrifai','alrifai_restore_other',' alrifai_restore_20261008_053528'])rejects('URI/unknown/whitespace target',()=>guardInput({...input,target},baseline),'UNAPPROVED_TARGET');
rejects('wrong expected cluster',()=>guardInput({...input,cluster:'0'},baseline),'EXPECTED_CLUSTER');
rejects('wrong archive hash',()=>guardInput({...input,archiveSha:'0'},baseline),'ARCHIVE_IDENTITY');
rejects('missing baseline',()=>guardInput(input,null),'BASELINE');
rejects('altered baseline',()=>guardInput(input,{...baseline,fingerprints:{}}),'BASELINE');
rejects('read-plan tampering',()=>readPlan(input,baseline,sql+'SELECT 1;'),'READ_PLAN_CHANGED');
const identity={database:TARGET,user:'vps_pg_admin',cluster:CLUSTER,readOnly:'on',version:'16.15'};
for(const [key,value,code] of [['database','alrifai','ACTUAL_DATABASE'],['database','another_db','ACTUAL_DATABASE'],['cluster','0','ACTUAL_CLUSTER'],['user','other','ACTUAL_USER'],['readOnly','off','NOT_READ_ONLY'],['version','16.14','SERVER_VERSION']])rejects('connected identity '+key+':'+value,()=>assertIdentity({...identity,[key]:value}),code);
assert.ok(sql.indexOf('\\if :qualification_guard')<sql.indexOf('SELECT * FROM public.'));
assert.ok(sql.includes('REPEATABLE READ READ ONLY')&&!sql.includes('COMMIT'));
assert.ok(!/(?:^|;\s*)(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|COPY|CALL|DO)\b/im.test(sql));pass('fixed read-only plan, identity before data and rollback only');
assert.equal(sha(JSON.stringify(catalog)),FINGERPRINTS.catalog);pass('offline reconstructed catalog golden hash');
const root=baseline.evidence.directory;
const expected=expectedSnapshots(readEvidenceSet(root,baseline.evidence.files));
const rows=Object.fromEntries(TABLES.map(t=>[t,[]]));
rows.site_source_snapshots=expected.slice().sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0);
rows.alrifai_schema_migrations=baseline.migrations.map(r=>({...r,applied_at:new Date(r.applied_at)}));
assert.deepEqual(fingerprints(rows,catalog),FINGERPRINTS);pass('all three golden fingerprints reconstructed without database');
assertExactSnapshots(rows.site_source_snapshots,expected);pass('54 exact snapshots, proof checks and all six evidence hashes');
const supplemental={
 database:{owner:'alrifai_app',encoding:'UTF8',collate:'en_US.utf8',ctype:'en_US.utf8',provider:'c',acl:null},
 schema:{owner:'pg_database_owner',acl:'{pg_database_owner=UC/pg_database_owner,=U/pg_database_owner}'},
 function:{owner:'alrifai_app',securityDefiner:false,language:'plpgsql'},
 indexes:TABLES.map(t=>({name:t+'_pkey',valid:true,ready:true})),
 relations:TABLES.map(t=>({name:t,rls:false,forceRls:false,acl:null})),
 extensions:[{name:'plpgsql',version:'1.0'}],
 functions:[{name:'alrifai_reject_snapshot_change',arguments:'',returns:'trigger',owner:'alrifai_app',securityDefiner:false,language:'plpgsql'}],
 schemas:[{name:'public'}],
 relationKinds:TABLES.flatMap(t=>[{name:t,kind:'r'},{name:t+'_pkey',kind:'i'}]).sort((a,b)=>a.name<b.name?-1:1),
 roles:[{name:'alrifai_app',superuser:false,createDatabase:false,createRole:false,login:true,replication:false,bypassRls:false},{name:'vps_pg_admin',superuser:true,createDatabase:true,createRole:true,login:true,replication:true,bypassRls:true}]
};
const collected={identity,rows,catalog,supplemental};
assert.equal(verifyCollected(input,baseline,collected,expected).status,'PASS');pass('golden complete comparator');
const frames=[{label:'identity',rows:[identity]},...TABLES.map(t=>({label:'table:'+t,rows:rows[t]})),...CATALOG_KEYS.map(k=>({label:'catalog:'+k,rows:catalog[k]})),{label:'supplemental',rows:[supplemental]}];
const encoded=frames.map(f=>JSON.stringify(f)).join('\n');
const decoded=decodeFrames(encoded);
assert.equal(verifyCollected(input,baseline,decoded,expected).status,'PASS');pass('framed decoder reproduces PostgreSQL-driver UTC date serialization');
rejects('missing frame',()=>decodeFrames(encoded.split('\n').slice(1).join('\n')),'FRAME_COUNT');
rejects('raw malformed frame',()=>decodeFrames('PRIVATE_SENTINEL_NOT_FOR_OUTPUT'),'FRAME_FORMAT');
const reorder=frames.slice();[reorder[1],reorder[2]]=[reorder[2],reorder[1]];
rejects('reordered frames',()=>decodeFrames(reorder.map(f=>JSON.stringify(f)).join('\n')),'FRAME_ORDER');
const alteredCatalog=structuredClone(catalog);alteredCatalog.grants.push({grantee:'PUBLIC',table_name:'programs',privilege_type:'INSERT'});
rejects('unexpected ACL',()=>verifyCollected(input,baseline,{...collected,catalog:alteredCatalog},expected),'CATALOG_OR_ACL_MISMATCH');
const badTimestamp={...rows,alrifai_schema_migrations:rows.alrifai_schema_migrations.map(r=>({...r,applied_at:'2026-10-07 21:05:59.743+00'}))};
rejects('timestamp drift',()=>verifyCollected(input,baseline,{...collected,rows:badTimestamp},expected),'MIGRATIONS');
const badPayload={...rows,site_source_snapshots:rows.site_source_snapshots.map((r,i)=>i===0?{...r,payload:r.payload+' '}:r)};
rejects('payload mismatch',()=>verifyCollected(input,baseline,{...collected,rows:badPayload},expected),'PAYLOAD_HASH');
rejects('operational rows',()=>verifyCollected(input,baseline,{...collected,rows:{...rows,programs:[{id:'synthetic'}]}},expected),'OPERATIONAL_ROWS');
const extraTable={...rows,unexpected:[]};
rejects('extra table',()=>verifyCollected(input,baseline,{...collected,rows:extraTable},expected),'TABLE_SET');
for(const [key,bad,code] of [
 ['database',{...supplemental.database,owner:'other'},'DATABASE_PROPERTIES'],
 ['schema',{...supplemental.schema,owner:'other'},'SCHEMA_PROPERTIES'],
 ['function',{...supplemental.function,securityDefiner:true},'FUNCTION_PROPERTIES'],
 ['indexes',supplemental.indexes.map((r,i)=>i===0?{...r,valid:false}:r),'INDEX_PROPERTIES'],
 ['relations',supplemental.relations.map((r,i)=>i===0?{...r,rls:true}:r),'RELATION_PROPERTIES'],
 ['extensions',[],'EXTENSIONS'],
 ['functions',[],'FUNCTION_INVENTORY'],['schemas',[{name:'unexpected'}],'SCHEMA_INVENTORY'],
 ['relationKinds',[],'RELATION_KINDS'],['roles',[],'ROLE_PROPERTIES']
])rejects('supplemental '+key,()=>assertSupplemental({...supplemental,[key]:bad}),code);
let calls=0,reads=0,rollbacks=0,closed=0;
const mock=(options={})=>async()=>{
 calls++;if(options.connectionFailure)throw Error('PRIVATE_CONNECTION_SENTINEL');
 return {beginReadOnly:async()=>{},identity:async()=>options.identity||identity,
 collect:async()=>{reads++;if(options.permissionFailure)throw Error('PRIVATE_PERMISSION_SENTINEL');return collected},
 rollback:async()=>{rollbacks++},close:async()=>{closed++}};
};
await assert.rejects(()=>verifyWithMock({...input,target:'alrifai'},baseline,mock(),expected),e=>e.code==='PRODUCTION_TARGET');
assert.equal(calls,0);pass('production rejected before transport');
await assert.rejects(()=>verifyWithMock(input,baseline,mock({identity:{...identity,database:'alrifai'}}),expected),e=>e.code==='ACTUAL_DATABASE');
assert.equal(reads,0);pass('wrong connected target rejected before data');
for(const key of ['connectionFailure','permissionFailure']){
 await assert.rejects(()=>verifyWithMock(input,baseline,mock({[key]:true}),expected),e=>e.code==='CONNECTION_OR_PERMISSION_FAILURE');pass(key+' sanitized');
}
assert.equal((await verifyWithMock(input,baseline,mock(),expected)).status,'PASS');assert.equal(rollbacks,3);assert.equal(closed,3);pass('successful read transaction rolled back and closed');
const source=text('verifier.mjs')+text('evidence-readonly.mjs');
assert.ok(!source.includes("from '../db/")&&!source.includes("from '../../apps/")&&!source.includes("from 'pg'")&&!source.includes("node:child_process"));
assert.ok(text('restore-supervisor.py').includes('raise SafetyStop("C2_LIVE_TRANSPORT_LOCKED")')&&!text('restore-supervisor.py').includes('os.system'));pass('static no production pool and locked executable transport');
for(const stage of ['rollback','close']){
 const transport=async()=>({beginReadOnly:async()=>{},identity:async()=>identity,collect:async()=>collected,rollback:async()=>{if(stage==='rollback')throw Error('PRIVATE_RELEASE_SENTINEL')},close:async()=>{if(stage==='close')throw Error('PRIVATE_RELEASE_SENTINEL')}});
 await assert.rejects(()=>verifyWithMock(input,baseline,transport,expected),e=>e.code==='TRANSACTION_RELEASE_FAILURE');pass('release failure '+stage+' fails closed');
}
console.log(JSON.stringify({status:'PASS',mode:'OFFLINE_ONLY',tests:results.length,cases:results,liveDatabaseConnections:0,realRestoreCommands:0,privatePayloadsLogged:false,fingerprints:FINGERPRINTS}));
