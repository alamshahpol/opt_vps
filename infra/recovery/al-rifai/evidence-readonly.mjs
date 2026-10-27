/**
 * Read-only adaptation of scripts/database.mjs evidence()/expectedSnapshots().
 * No imports of application pools, migration code, or executable CLI modules.
 */
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
export const sha=value=>createHash('sha256').update(value).digest('hex');
const NAMES=['accounts-snapshot.json','chat-archive.json','conversation-snapshot.json','operations.json','seed-source.ts','recovered-programs.json'];
export function readEvidenceSet(directory,manifest){
 if(typeof directory!=='string'||!directory.startsWith('/'))throw Error('EVIDENCE_DIRECTORY');
 if(!manifest||Object.keys(manifest).sort().join('|')!==[...NAMES].sort().join('|'))throw Error('EVIDENCE_MANIFEST');
 const bytes=new Map();
 for(const name of NAMES){
  const b=readFileSync(join(directory,name)),m=manifest[name];
  if(b.length!==m.bytes||sha(b)!==m.sha256)throw Error('EVIDENCE_CHECKSUM');
  bytes.set(name,b);
 }
 return name=>{
  if(!bytes.has(name)||name==='seed-source.ts')throw Error('EVIDENCE_NAME');
  try{return JSON.parse(bytes.get(name).toString('utf8'))}catch{throw Error('EVIDENCE_FORMAT')}
 };
}
export function expectedSnapshots(evidence){
 return ['conversation-snapshot.json','accounts-snapshot.json'].flatMap(name=>{
  const snapshot=evidence(name);
  if(name==='accounts-snapshot.json'){
   const proof=snapshot.summary.identityProof;
   if(proof.confirmed!==true||proof.accountantContactConfirmed!==true||proof.conversationType!=='direct'||proof.sourceSha256!==snapshot.summary.sourceSha256)throw Error('ACCOUNTS_IDENTITY');
   const original=evidence('conversation-snapshot.json');
   if(original.summary.files.find(f=>f.key==='mamun')?.sha256!==snapshot.summary.sourceSha256)throw Error('ACCOUNTS_SOURCE');
  }
  return [...snapshot.chunks.map(c=>({id:c.id,datasetId:snapshot.datasetId,kind:c.kind,payload:c.payload,contentHash:c.contentHash})),{id:snapshot.datasetId+':complete',datasetId:snapshot.datasetId,kind:'manifest',payload:JSON.stringify(snapshot.summary),contentHash:String(snapshot.chunks.length)}];
 });
}
export function assertExactSnapshots(actual,expected){
 if(!Array.isArray(actual)||actual.length!==expected.length)throw Error('SNAPSHOT_COUNT');
 const byId=new Map(actual.map(r=>[r.id,r]));
 if(byId.size!==actual.length)throw Error('SNAPSHOT_DUPLICATE');
 for(const row of expected){
  const a=byId.get(row.id);
  if(!a||Object.keys(a).length!==Object.keys(row).length||Object.keys(row).some(k=>a[k]!==row[k]))throw Error('SNAPSHOT_CONTENT');
 }
}
