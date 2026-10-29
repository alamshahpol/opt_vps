import test from 'node:test';
import assert from 'node:assert/strict';
import {copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const script = join(root, 'tests/sql/rehearsal_bootstrap.sh');
const id = 'a'.repeat(64);

// A fake Docker executable records arguments and consumes no data. No real
// container, network, database, image or Docker daemon is used by these tests.
function runFake(args = [], extra = {}, fixture = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'alrifai-rehearsal-test-'));
  const log = join(directory, 'docker.log');
  const sqlLog = join(directory, 'synthetic-sql.log');
  const fake = join(directory, 'docker');
  let target = script;
  if (fixture.isolatedFiles) {
    const tree = join(directory, 'checkout');
    for (const path of ['tests/sql', 'db/migrations', 'db/migration-candidates']) {
      mkdirSync(join(tree, path), {recursive: true});
    }
    target = join(tree, 'tests/sql/rehearsal_bootstrap.sh');
    copyFileSync(script, target);
    for (let number = 0; number <= 30; number++) {
      const prefix = String(number).padStart(4, '0');
      if (prefix !== fixture.omit) writeFileSync(join(tree, `db/migrations/${prefix}_fixture.sql`), `-- baseline-${prefix}\n`);
    }
    if (fixture.duplicate) writeFileSync(join(tree, `db/migrations/${fixture.duplicate}_duplicate.sql`), '-- duplicate\n');
    writeFileSync(join(tree, 'db/migrations/0033_unapproved_future.sql'), '-- unapproved-future-migration\n');
    for (const name of ['0031_cash_submissions_and_reviews.sql', '0032_vessel_program_commands.sql']) {
      writeFileSync(join(tree, 'db/migration-candidates', name), `-- ${name}\n`);
    }
    for (const name of ['0031_cash_review_rehearsal.sql', '0032_vessel_commands_rehearsal.sql']) {
      writeFileSync(join(tree, 'tests/sql', name), `-- ${name}\n`);
    }
  }
  writeFileSync(fake, `#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case "$1" in
  run) printf '%s\\n' "\${FAKE_ID:-${id}}" ;;
  exec) case "$*" in *' -f -'*)
    if [ "\${COLLECT_SYNTHETIC_SQL:-0}" = 1 ]; then cat >> "$DOCKER_SQL_LOG"; fi
    [ "\${FAKE_FAIL_SQL:-0}" = 0 ] || exit 1 ;;
  esac ;;
  rm) exit 0 ;;
  *) exit 1 ;;
esac
`, {mode: 0o755});
  try {
    const result = spawnSync('/bin/sh', [target, ...args], {
      cwd: root,
      env: {PATH: `${directory}:/usr/bin:/bin`, DOCKER_LOG: log, DOCKER_SQL_LOG: sqlLog,
        COLLECT_SYNTHETIC_SQL: fixture.isolatedFiles ? '1' : '0', ...extra},
      encoding: 'utf8',
      timeout: 15000,
    });
    let calls = [], syntheticSql = '';
    try { calls = readFileSync(log, 'utf8').trim().split('\n').filter(Boolean); } catch { /* not invoked */ }
    try { syntheticSql = readFileSync(sqlLog, 'utf8'); } catch { /* not collected */ }
    return {result, calls, syntheticSql};
  } finally {
    rmSync(directory, {recursive: true, force: true});
  }
}

test('rehearsal rejects arbitrary container targets before Docker is invoked', () => {
  for (const args of [['vps-infra-postgres-1'], ['anything', 'postgres']]) {
    const {result, calls} = runFake(args);
    assert.equal(result.status, 64);
    assert.equal(calls.length, 0);
  }
});

test('rehearsal creates only an isolated disposable container and cleans it up', () => {
  const {result, calls} = runFake();
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /REHEARSAL_OK/);
  assert.match(calls[0], /--pull=never --network none/);
  assert.match(calls[0], /--tmpfs \/var\/lib\/postgresql\/data:/);
  assert.doesNotMatch(calls[0], /(?:^| )--(?:mount|publish|volume)(?:[= ]|$)/);
  const commands = calls.slice(1, -1);
  assert.ok(commands.length > 30, 'migrations and rehearsal assertions must be executed');
  for (const command of commands) assert.match(command, new RegExp(`^exec (?:-i )?${id} `));
  assert.equal(calls.at(-1), `rm -f ${id}`);
});

test('rehearsal applies only the complete numbered baseline and approved candidates', () => {
  const complete = runFake([], {}, {isolatedFiles: true});
  assert.equal(complete.result.status, 0, complete.result.stderr);
  assert.match(complete.syntheticSql, /baseline-0000/);
  assert.match(complete.syntheticSql, /baseline-0030/);
  assert.match(complete.syntheticSql, /0031_cash_submissions_and_reviews/);
  assert.match(complete.syntheticSql, /0032_vessel_program_commands/);
  assert.doesNotMatch(complete.syntheticSql, /unapproved-future-migration/);
  for (const fixture of [{omit: '0017'}, {duplicate: '0017'}]) {
    const failed = runFake([], {}, {isolatedFiles: true, ...fixture});
    assert.equal(failed.result.status, 1);
    assert.match(failed.result.stderr, /Expected exactly one baseline migration for 0017/);
    assert.equal(failed.calls.at(-1), `rm -f ${id}`);
  }
});

test('rehearsal refuses an invalid returned ID and cleans up on SQL failure', () => {
  const invalid = runFake([], {FAKE_ID: 'vps-infra-postgres-1'});
  assert.equal(invalid.result.status, 1);
  assert.equal(invalid.calls.length, 1, 'never exec or remove an unverified ID');
  const failure = runFake([], {FAKE_FAIL_SQL: '1'});
  assert.equal(failure.result.status, 1);
  assert.equal(failure.calls.at(-1), `rm -f ${id}`);
});
