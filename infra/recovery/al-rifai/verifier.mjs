/**
 * Passive, explicit-target verifier. Never opens connections or spawns commands.
 * Hash/serialization algorithm adapted from scripts/verify-state.mjs.
 */
import {readFileSync} from 'node:fs';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {sha,assertExactSnapshots} from './evidence-readonly.mjs';
import {createHash} from 'node:crypto';
export const TARGET='alrifai_restore_20261008_053528';
export const CLUSTER='7694012476208082978';
export const ARCHIVE_SHA='5f12fdeff34aac57e733af012e52daebb97f44fa7d56d962166fa4c85debcded';
export const CONTAINER='63b70ddf47f20b7836f860d7819acc273a3e66b2bd96febbde0cbf1339ac6bd6';
export const TABLES=['programs','reviews','datasets','site_cash_archive','site_operation_notes','site_payment_drafts','site_settlement_drafts','site_source_snapshots','alrifai_schema_migrations'];
export const CATALOG_KEYS=['columns','constraints','indexes','triggers','function','ownership','grants'];
export const FINGERPRINTS={state:'96f4fe553fdd54d5e10869696dd9e5ded3e9da434c4fe4cc37496599be0464ba',snapshots:'3590e6eba9081e3f0bc79c90b35375a636b76b16fe3a4043adad4edf93bb0757',catalog:'146c5dbf5f3a2f88ade4dbf893eeba189035b03b99b5cb798ae8531060f5a174'};
export const READ_PLAN_SHA='d3b4a25e19bff52afeb380312ee70097a398cd989bd44a982ceb15d0c6d0d749';
export class VerificationStop extends Error{constructor(code){super(code);this.code=code}}
const stop=code=>{throw new VerificationStop(code)};
export function guardInput(input,baseline){
 if(!input||typeof input.target!=='string'||input.target.length===0)stop('MISSING_TARGET');
 if(input.target==='alrifai')stop('PRODUCTION_TARGET');
 if(input.target!==TARGET||!/^[a-z][a-z0-9_]*$/.test(input.target))stop('UNAPPROVED_TARGET');
 if(input.cluster!==CLUSTER)stop('EXPECTED_CLUSTER');
 if(input.archiveSha!==ARCHIVE_SHA)stop('ARCHIVE_IDENTITY');
 if(!baseline||baseline.provenance?.classification!=='RECONSTRUCTED_NOT_ORIGINAL_STAGE_B'||Object.keys(FINGERPRINTS).some(k=>baseline.fingerprints?.[k]!==FINGERPRINTS[k]))stop('BASELINE');
 if(baseline.target!==TARGET||baseline.cluster!==CLUSTER||baseline.archive?.sha256!==ARCHIVE_SHA||baseline.readPlanSHA256!==READ_PLAN_SHA)stop('BASELINE_IDENTITY');
}
export function assertIdentity(id){
 if(!id||id.database!==TARGET||id.database==='alrifai')stop('ACTUAL_DATABASE');
 if(id.cluster!==CLUSTER)stop('ACTUAL_CLUSTER');
 if(id.user!=='vps_pg_admin')stop('ACTUAL_USER');
 if(id.readOnly!=='on')stop('NOT_READ_ONLY');
 if(id.version!=='16.15')stop('SERVER_VERSION');
}
export function readPlan(input,baseline,sql){
 guardInput(input,baseline);
 if(sha(sql)!==READ_PLAN_SHA)stop('READ_PLAN_CHANGED');
 return {command:['docker','exec','-i','-e','PGOPTIONS=-c default_transaction_read_only=on',CONTAINER,'psql','-X','-qAt','-w','-h','/var/run/postgresql','-p','5432','-U','vps_pg_admin','-d',TARGET,'-v','ON_ERROR_STOP=1'],sqlSHA256:READ_PLAN_SHA};
}
export function decodeFrames(text){
 const labels=['identity',...TABLES.map(t=>'table:'+t),...CATALOG_KEYS.map(k=>'catalog:'+k),'supplemental'];
 let frames;try{frames=text.trimEnd().split('\n').map(x=>JSON.parse(x))}catch{stop('FRAME_FORMAT')}
 if(frames.length!==labels.length)stop('FRAME_COUNT');
 const rows={},catalog={};let identity,supplemental;
 for(let n=0;n<labels.length;n++){
  const f=frames[n];if(f.label!==labels[n]||!Array.isArray(f.rows))stop('FRAME_ORDER');
  if(f.label==='identity'){if(f.rows.length!==1)stop('IDENTITY_COUNT');identity=f.rows[0];assertIdentity(identity)}
  else if(f.label==='supplemental'){if(f.rows.length!==1)stop('SUPPLEMENTAL_COUNT');supplemental=f.rows[0]}
  else if(f.label.startsWith('table:'))rows[f.label.slice(6)]=f.rows;
  else catalog[f.label.slice(8)]=f.rows;
 }
 for(const row of rows.alrifai_schema_migrations){
  if(typeof row.applied_at!=='string'||!/^\d{4}-\d{2}-\d{2}T.*(?:Z|\+00:00)$/.test(row.applied_at))stop('TIMESTAMP_FORMAT');
  const value=new Date(row.applied_at);if(!Number.isFinite(value.valueOf()))stop('TIMESTAMP_FORMAT');row.applied_at=value;
 }
 return {identity,rows,catalog,supplemental};
}
export function fingerprints(rows,catalog){
 const hash=createHash('sha256');
 for(const table of TABLES){if(!Array.isArray(rows[table]))stop('TABLE_SET');hash.update(table).update(JSON.stringify(rows[table]));}
 return {state:hash.digest('hex'),snapshots:sha(JSON.stringify(rows.site_source_snapshots)),catalog:sha(JSON.stringify(catalog))};
}
export function assertSupplemental(s){
 if(!s||s.database?.owner!=='alrifai_app'||s.database.encoding!=='UTF8'||s.database.collate!=='en_US.utf8'||s.database.ctype!=='en_US.utf8'||s.database.provider!=='c'||s.database.acl!==null)stop('DATABASE_PROPERTIES');
 if(s.schema?.owner!=='pg_database_owner'||s.schema.acl!=='{pg_database_owner=UC/pg_database_owner,=U/pg_database_owner}')stop('SCHEMA_PROPERTIES');
 if(s.function?.owner!=='alrifai_app'||s.function.securityDefiner!==false||s.function.language!=='plpgsql')stop('FUNCTION_PROPERTIES');
 if(!Array.isArray(s.indexes)||s.indexes.length!==9||s.indexes.some(x=>x.valid!==true||x.ready!==true)||s.indexes.map(x=>x.name).sort().join('|')!==TABLES.map(t=>t+'_pkey').sort().join('|'))stop('INDEX_PROPERTIES');
 if(!Array.isArray(s.relations)||s.relations.length!==9||s.relations.some(x=>x.rls!==false||x.forceRls!==false||x.acl!==null)||s.relations.map(x=>x.name).sort().join('|')!==[...TABLES].sort().join('|'))stop('RELATION_PROPERTIES');
 if(JSON.stringify(s.extensions)!==JSON.stringify([{name:'plpgsql',version:'1.0'}]))stop('EXTENSIONS');
 if(JSON.stringify(s.functions)!==JSON.stringify([{name:'alrifai_reject_snapshot_change',arguments:'',returns:'trigger',owner:'alrifai_app',securityDefiner:false,language:'plpgsql'}]))stop('FUNCTION_INVENTORY');
 if(JSON.stringify(s.schemas)!==JSON.stringify([{name:'public'}]))stop('SCHEMA_INVENTORY');
 const kinds=TABLES.flatMap(t=>[{name:t,kind:'r'},{name:t+'_pkey',kind:'i'}]).sort((a,b)=>a.name<b.name?-1:1);
 if(JSON.stringify(s.relationKinds)!==JSON.stringify(kinds))stop('RELATION_KINDS');
 const roles=[{name:'alrifai_app',superuser:false,createDatabase:false,createRole:false,login:true,replication:false,bypassRls:false},{name:'vps_pg_admin',superuser:true,createDatabase:true,createRole:true,login:true,replication:true,bypassRls:true}];
 if(JSON.stringify(s.roles)!==JSON.stringify(roles))stop('ROLE_PROPERTIES');
}
export function verifyCollected(input,baseline,collected,expected){
 guardInput(input,baseline);assertIdentity(collected.identity);
 const {rows,catalog,supplemental}=collected;
 if(Object.keys(rows).sort().join('|')!==[...TABLES].sort().join('|'))stop('TABLE_SET');
 if(Object.keys(catalog).join('|')!==CATALOG_KEYS.join('|'))stop('CATALOG_ORDER');
 if(TABLES.slice(0,7).some(t=>rows[t].length!==0))stop('OPERATIONAL_ROWS');
 if(rows.alrifai_schema_migrations.length!==6||rows.alrifai_schema_migrations.some((r,i)=>r.id!==baseline.migrations[i]?.id||r.sha256!==baseline.migrations[i]?.sha256||r.applied_at?.toISOString?.()!==baseline.migrations[i]?.applied_at))stop('MIGRATIONS');
 if(rows.site_source_snapshots.length!==54||rows.site_source_snapshots.filter(r=>r.kind==='manifest').length!==2)stop('SNAPSHOT_COUNTS');
 for(const r of rows.site_source_snapshots)if(r.kind!=='manifest'&&sha(r.payload)!==r.contentHash)stop('PAYLOAD_HASH');
 try{assertExactSnapshots(rows.site_source_snapshots,expected)}catch{stop('SNAPSHOT_CONTENT')}
 assertSupplemental(supplemental);
 const result=fingerprints(rows,catalog);
 for(const k of Object.keys(FINGERPRINTS))if(result[k]!==FINGERPRINTS[k])stop(k==='catalog'?'CATALOG_OR_ACL_MISMATCH':'SERIALIZATION_MISMATCH');
 return {status:'PASS',readOnly:true,counts:Object.fromEntries(TABLES.map(t=>[t,rows[t].length])),fingerprints:result};
}
export async function verifyWithMock(input,baseline,transport,expected){
 guardInput(input,baseline);let connection,begun=false;
 try{
  connection=await transport();await connection.beginReadOnly();begun=true;
  assertIdentity(await connection.identity());
  return verifyCollected(input,baseline,await connection.collect(),expected);
 }catch(e){if(e instanceof VerificationStop)throw e;stop('CONNECTION_OR_PERMISSION_FAILURE')}
 finally{
  if(connection){
   let releaseFailed=false;
   if(begun)try{await connection.rollback()}catch{releaseFailed=true}
   try{await connection.close()}catch{releaseFailed=true}
   if(releaseFailed)stop('TRANSACTION_RELEASE_FAILURE');
  }
 }
}
function main(){
 // No live connection mode. Default prints plan metadata only.
 const args=process.argv.slice(2);
 if(args.length!==0&&args[0]!=='--plan')stop('LIVE_EXECUTION_DISABLED');
 const baseline=JSON.parse(readFileSync(new URL('./baseline-attestation.json',import.meta.url),'utf8'));
 const sql=readFileSync(new URL('./read-plan.sql',import.meta.url),'utf8');
 const input={target:TARGET,cluster:CLUSTER,archiveSha:ARCHIVE_SHA};
 console.log(JSON.stringify({mode:'PLAN_ONLY',liveExecutionEnabled:false,...readPlan(input,baseline,sql)}));
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){try{main()}catch(e){console.error(JSON.stringify({status:'BLOCKED',code:e instanceof VerificationStop?e.code:'INPUT_UNAVAILABLE'}));process.exitCode=1}}
