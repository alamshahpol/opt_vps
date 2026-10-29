import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';
import {ZodError} from 'zod';
import {createCandidateApi} from '../candidates/identity-review/api.ts';
import {hash} from '../candidates/identity-review/contracts.ts';
import {reconciliationDecision} from '../candidates/identity-review/reconciliation.ts';
import {manualRequest} from '../candidates/identity-review/reconciliation-imports.ts';
import {emptyState} from '../candidates/identity-review/repository.ts';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = readFileSync(new URL('../lib/cash-source.ts', import.meta.url), 'utf8');

function cashModule(summary) {
  const code = ts.transpileModule(source, {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  }).outputText;
  const stubs = {
    '@/lib/evidence': {lazyEvidence: () => ({cash: [], excel: []})},
    '@/db/raw': {database: () => ({})},
    '@/lib/accounts-snapshot': {accountsImportSummary: summary, accountsCash: async () => []},
    '@/lib/cash-data': {cashNotice: 'fixture'},
    '@/lib/live-cash-read': {
      liveCashRows: async () => [{id: 'synthetic'}],
      liveCashCoverage: async () => ({last_date: null, messages: 2}),
    },
  };
  const fixtureModule = {exports: {}};
  new Function('require', 'module', 'exports', code)(name => {
    assert.ok(Object.hasOwn(stubs, name), `Unexpected dependency: ${name}`);
    return stubs[name];
  }, fixtureModule, fixtureModule.exports);
  return fixtureModule.exports;
}

test('Cash module import does not enumerate private evidence during a build', async () => {
  const missing = new Proxy({}, {ownKeys() { throw new Error('EVIDENCE_UNAVAILABLE'); }});
  const cash = cashModule(missing);
  await assert.rejects(cash.loadCashSnapshot(), /EVIDENCE_UNAVAILABLE/);
});

test('Cash requests preserve the verified summary and fail closed without it', async () => {
  const cash = cashModule({updatedAt: 'fixture-date', sourceMessages: 8, marker: 'fixture'});
  const snapshot = await cash.loadCashSnapshot();
  assert.equal(snapshot.importSummary.updatedAt, 'fixture-date');
  assert.equal(snapshot.importSummary.sourceMessages, 2);
  assert.equal(snapshot.importSummary.accountsQualifiedRows, 1);
  assert.equal(snapshot.importSummary.marker, 'fixture');
});

test('Zod record validation accepts valid review fields and rejects invalid values', async () => {
  let calls = 0;
  const api = createCandidateApi({actOnReview: async (_credentials, _id, input) => {
    calls++;
    return {fields: input.fields};
  }}, {origin: 'https://fixture.invalid'});
  const post = fields => api(new Request(`https://fixture.invalid/candidate-api/reviews/${'a'.repeat(64)}/actions`, {
    method: 'POST',
    headers: {origin: 'https://fixture.invalid', 'content-type': 'application/json'},
    body: JSON.stringify({expectedVersion: 1, expectedEpoch: 1, operationId: 'fixture', action: 'CORRECT_FIELDS', reason: 'fixture', fields}),
  }), '127.0.0.1');
  const valid = await post({name: 'fixture', amount: 123, optional: null});
  assert.equal(valid.status, 200);
  assert.deepEqual((await valid.json()).fields, {name: 'fixture', amount: 123, optional: null});
  const invalid = await post({name: ['not a string']});
  assert.equal(invalid.status, 400);
  assert.equal((await invalid.json()).error, 'INVALID_CONTRACT_INPUT');
  assert.equal(calls, 1, 'invalid fields must not reach the service');
});

test('Zod reconciliation records validate against an in-memory owner and SQL stub', async () => {
  const now = Date.parse('2026-01-01T00:00:00Z');
  const token = 'a'.repeat(64), csrf = 'b'.repeat(64);
  const state = emptyState();
  state.registry.owner = {id: 'owner', kind: 'person', status: 'VERIFIED', data: {}};
  state.registry.role = {id: 'role', kind: 'relationship', status: 'VERIFIED', data: {personId: 'owner', kind: 'SUPER_ADMIN'}};
  state.staff.staff = {id: 'staff', username: 'fixture', personId: 'owner', active: true, version: 1};
  state.sessions[hash(token)] = {id: hash(token), accountId: 'staff', accountVersion: 1, personId: 'owner',
    csrfHash: hash(csrf), createdAt: now, lastSeen: now, expiresAt: now + 60_000};
  const credentials = {token, csrf};
  const statements = [];
  const client = {query: async sql => {statements.push(sql); return {rows: []};}};
  const operationId = '123e4567-e89b-12d3-a456-426614174000';
  const input = {domain: 'ESCORT', fields: {name: 'fixture', count: 2, active: true, optional: null},
    reason: 'offline fixture', operationId};
  const valid = await manualRequest(state, credentials, input, now, client);
  assert.equal(valid.status, 'PENDING');
  assert.equal(valid.canonicalWrites, 0);
  assert.equal(statements.length, 4, 'all queries use a synthetic SQL stub');
  statements.length = 0;
  await assert.rejects(manualRequest(state, credentials, {...input, fields: {invalid: ['array']}}, now, client), ZodError);
  assert.equal(statements.length, 0, 'invalid manual fields must not reach SQL');

  const decision = {id: 'c'.repeat(64), operationId, expectedRevision: 1, action: 'REJECT',
    reason: 'offline fixture', fields: {value: 'fixture', metadata: {synthetic: true}}};
  await assert.rejects(reconciliationDecision(state, credentials, decision, now, client), /NOT_FOUND/);
  assert.equal(statements.length, 2, 'valid fields passed parsing and reached only the SQL stub');
  statements.length = 0;
  await assert.rejects(reconciliationDecision(state, credentials, {...decision, fields: ['invalid']}, now, client), ZodError);
  assert.equal(statements.length, 0, 'invalid decision fields must not reach SQL');
});

test('installation checks are non-mutating and distinguish missing prerequisites', () => {
  const directory = mkdtempSync(join(tmpdir(), 'alrifai-install-check-'));
  try {
    const missing = join(directory, 'does-not-exist');
    const env = {
      PATH: process.env.PATH || '/usr/bin:/bin',
      ALRIFAI_EVIDENCE_DIR: missing,
      ALRIFAI_VALIDATION_PASSWORD_FILE: missing,
      PGPASSWORD_FILE: missing,
    };
    const check = args => spawnSync(process.execPath, ['scripts/install-check.mjs', ...args], {cwd: root, env, encoding: 'utf8'});
    const optional = check([]);
    assert.equal(optional.status, 0, optional.stderr);
    assert.match(optional.stdout, /Private evidence files readable: 0\/5/);
    assert.match(optional.stdout, /database\/schema, TLS, permissions and WhatsApp are NOT verified/);
    assert.doesNotMatch(optional.stdout, new RegExp(directory));
    assert.equal(check(['--strict']).status, 1);
    assert.equal(check(['--unknown']).status, 2);
    const evidence = spawnSync(process.execPath, ['--experimental-strip-types', 'tests/source-register.mjs'], {
      cwd: root, env: {PATH: env.PATH}, encoding: 'utf8',
    });
    assert.equal(evidence.status, 2);
    assert.match(evidence.stderr, /isolated, authorized evidence copy/);
  } finally {
    rmSync(directory, {recursive: true, force: true});
  }
});
