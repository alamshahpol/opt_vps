import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {validDate,normalizeEmployeeMobile} from '../lib/employee-program-validation.mjs';
const readerPath=new URL('../lib/vessel-source.ts',import.meta.url),original=readFileSync(readerPath,'utf8');
const old="(row.escortName&&normalize(row.escortName)===normalize(r.escortName))";
const replacement="(!phone(row.escortMobile)&&!phone(r.escortMobile)&&row.escortName&&normalize(row.escortName)===normalize(r.escortName))";
assert.equal(original.split(old).length,2);
function reader(stored,imported,seed=[],patched=false){
 const source=patched?original.replace(old,replacement):original;
 const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const stubs={'@/lib/integrations':{integrationConfig:{}},'../db/raw':{database:()=>({all:async sql=>{assert.equal(sql,'SELECT * FROM programs ORDER BY "startDate" DESC, id');return {results:stored};}})},'./seed':{seed},'./conversation-snapshot':{importedPrograms:async()=>imported,importSummary:{updatedAt:'SYNTHETIC'}},'./vessel-data':{validDate,missingFields:()=>[]}};
 const qualificationModule={exports:{}};new Function('require','module','exports',code)(name=>{assert.ok(stubs[name],'Unexpected reader dependency: '+name);return stubs[name];},qualificationModule,qualificationModule.exports);
 return qualificationModule.exports.historicalSnapshot();
}
const row=(id,extra={})=>({id,motherVessel:'Synthetic Mother',lighterVessel:'Synthetic Lighter',escortName:'Synthetic Name',escortMobile:'01700000001',masterMobile:'',startDate:'2026-01-01',shift:'D',status:'Recorded',details:{},aliases:[id],evidence:[],conflicts:[],...extra});
test('existing alias overlay suppresses already-listed stable ID',async()=>{const r=await reader([row('legacy')],[row('source',{aliases:['source','legacy']})]);assert.equal(r.rows.length,1);});
test('existing empty programs fallback includes seed without writes',async()=>{const r=await reader([],[],[row('seed')]);assert.equal(r.rows.length,1);assert.equal(r.rows[0].id,'seed');});
test('existing nonempty programs stops seed fallback',async()=>{const r=await reader([row('accepted')],[],[row('seed')]);assert.equal(r.rows.length,1);assert.equal(r.rows[0].id,'accepted');});
test('original-reader defect reproduced: same name/different valid mobiles collapses records',async()=>{const r=await reader([row('accepted',{escortMobile:'01800000001'})],[row('source')]);assert.equal(r.rows.length,1);assert.ok(r.rows[0].aliases.includes('accepted'));assert.notEqual(normalizeEmployeeMobile(r.rows[0].escortMobile),normalizeEmployeeMobile('01800000001'));});
test('proposed phone guard preserves distinct mobile identities without editing existing reader',async()=>{const r=await reader([row('accepted',{escortMobile:'01800000001'})],[row('source')],[],true);assert.equal(r.rows.length,2);assert.equal(new Set(r.rows.map(r=>normalizeEmployeeMobile(r.escortMobile))).size,2);});
test('proposed phone guard retains equal-mobile evidence overlay',async()=>{const r=await reader([row('accepted',{escortMobile:'+8801700000001'})],[row('source')],[],true);assert.equal(r.rows.length,1);assert.ok(r.rows[0].aliases.includes('accepted'));});
test('original-reader duplicate exposure: ambiguous source overlays append accepted row as another display record',async()=>{const r=await reader([row('accepted')],[row('source-a'),row('source-b')]);assert.equal(r.rows.length,3);assert.deepEqual(new Set(r.rows.map(r=>r.id)),new Set(['accepted','source-a','source-b']));});
test('original-reader authority issue: unique heuristic overlay retains source ID/status rather than accepted anchor',async()=>{const r=await reader([row('accepted',{status:'Active'})],[row('source')]);assert.equal(r.rows.length,1);assert.equal(r.rows[0].id,'source');assert.equal(r.rows[0].status,'Recorded');});
test('evidence qualification is passive and keeps role scopes separate',()=>{const code=readFileSync(new URL('../scripts/employee-program-evidence-qualification.mjs',import.meta.url),'utf8');assert.doesNotMatch(code,/createPool|importEvidence|fetch\(/);assert.match(code,/OWNER_ATTESTED_ADMIN_ACCOUNTANT_PAYMENT_INSTRUCTIONS_ONLY/);assert.match(code,/programConfirmationAuthorityVerified:false/);});
