#!/usr/bin/env node
// Exercise the production standalone layout without Docker, private data,
// credentials, a database, or live worker configuration. Build first.
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync} from 'node:fs';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {basename, join, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
if (!existsSync(join(root, '.next/standalone/server.js'))) {
  console.error('Standalone build missing; run "corepack pnpm build" first.');
  process.exit(1);
}
const stage = mkdtempSync(join(tmpdir(), 'alrifai-clean-smoke-'));
let server;

// Reproduce the build-stage COPY instructions rather than silently resolving
// worker dependencies from this checkout's node_modules. This does not build
// or run Docker, and cannot prove OS packages or actual container permissions.
function stageRuntime() {
  const lines = readFileSync(join(root, 'Dockerfile'), 'utf8').split(/\r?\n/);
  const copies = lines.filter(line => /^COPY --from=build --chown=\S+\s/.test(line));
  assert.ok(copies.length >= 5, 'Dockerfile runtime copy instructions missing');
  for (const line of copies) {
    const tokens = line.split(/\s+/).slice(3);
    const destination = tokens.pop();
    assert.ok(destination?.startsWith('./') || destination?.startsWith('/app/'), `Unexpected runtime destination: ${destination}`);
    const dest = resolve(stage, destination.startsWith('/app/') ? destination.slice('/app/'.length) : destination);
    assert.ok(dest === stage || dest.startsWith(stage + sep), 'Invalid runtime destination');
    for (const source of tokens) {
      assert.ok(source.startsWith('/app/') && !source.includes('..'), `Unexpected runtime source: ${source}`);
      const from = resolve(root, source.slice('/app/'.length));
      assert.ok(existsSync(from), `Missing build input: ${source}`);
      if (statSync(from).isDirectory()) {
        mkdirSync(dest, {recursive: true});
        cpSync(from, dest, {recursive: true, force: true, verbatimSymlinks: true});
      } else {
        const target = destination.endsWith('/') ? join(dest, basename(from)) : dest;
        mkdirSync(resolve(target, '..'), {recursive: true});
        cpSync(from, target);
      }
    }
  }
  for (const name of ['next', 'pg', 'zod']) {
    const path = realpathSync(join(stage, 'node_modules', name));
    assert.ok(path.startsWith(stage + sep), `${name} resolved outside the staged runtime`);
  }
}

function unusedPort() {
  return new Promise((accept, reject) => {
    const socket = createServer();
    socket.once('error', reject);
    socket.listen(0, '127.0.0.1', () => {
      const port = socket.address().port;
      socket.close(error => error ? reject(error) : accept(port));
    });
  });
}

function runWorker(env, name, expectedStatus, expectedMessage) {
  const result = spawnSync(process.execPath, ['--experimental-strip-types', join(stage, 'scripts', name)], {
    cwd: stage, env, encoding: 'utf8', timeout: 10_000,
  });
  assert.ifError(result.error);
  assert.equal(result.status, expectedStatus, `${name} status: ${result.stderr}`);
  assert.match(result.stdout + result.stderr, expectedMessage, `${name} did not fail closed as expected`);
}

async function stopServer(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  await new Promise(resolveExit => {
    const timer = setTimeout(() => {child.kill('SIGKILL'); resolveExit();}, 5_000);
    child.once('exit', () => {clearTimeout(timer); resolveExit();});
    child.kill('SIGTERM');
  });
}

function waitForReady(child) {
  return new Promise((accept, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`Standalone server did not become ready: ${output}`)), 30_000);
    function receive(chunk) {
      output = (output + chunk.toString()).slice(-10_000);
      if (/Ready in/i.test(output)) {
        clearTimeout(timer);
        accept();
      }
    }
    child.stdout.on('data', receive);
    child.stderr.on('data', receive);
    child.once('error', error => {clearTimeout(timer); reject(error);});
    child.once('exit', code => {clearTimeout(timer); reject(new Error(`Standalone server exited (${code}): ${output}`));});
  });
}

try {
  stageRuntime();
  const port = await unusedPort();
  const reviewPassword = join(stage, 'fixture-review-password');
  writeFileSync(reviewPassword, 'synthetic-test-only\n', {mode: 0o600});
  const env = {
    PATH: process.env.PATH ?? '/usr/bin:/bin', HOME: stage,
    NODE_ENV: 'production', NEXT_TELEMETRY_DISABLED: '1', HOSTNAME: '127.0.0.1', PORT: String(port),
    ALRIFAI_EVIDENCE_DIR: join(stage, 'no-private-evidence'),
    PGPASSWORD_FILE: join(stage, 'no-db-password'),
    ALRIFAI_REVIEW_PASSWORD_FILE: reviewPassword,
    ALRIFAI_VALIDATION_PASSWORD_FILE: join(stage, 'no-web-password'),
    ALRIFAI_VESSEL_AUTH_DB: join(stage, 'no-vessel-auth.db'),
    ALRIFAI_LIVE_CASH_SYNC: '0', ALRIFAI_VESSEL_PROCESSING_ENABLED: '0',
    ALRIFAI_MESSAGE_MIRROR_ENABLED: '0',
  };

  // These processors create no DB connection when their disabled gates reject.
  runWorker(env, 'process-cash.ts', 1, /CASH_REVIEW_ONLY_MODE_REQUIRED/);
  runWorker(env, 'process-vessel.ts', 1, /VESSEL_PROCESSING_DISABLED/);
  runWorker(env, 'message-mirror-worker.ts', 0, /Message Mirror worker disabled/);
  runWorker(env, 'message-ingestion-worker.ts', 1, /WhatsApp ingestion worker stopped/);

  server = spawn(process.execPath, ['server.js'], {cwd: stage, env, stdio: ['ignore', 'pipe', 'pipe']});
  await waitForReady(server);
  let base = `http://127.0.0.1:${port}`;
  async function get(path, expected) {
    const response = await fetch(base + path, {redirect: 'manual', signal: AbortSignal.timeout(10_000)});
    assert.equal(response.status, expected, `${path} returned ${response.status}, expected ${expected}`);
    return response;
  }
  const home = await (await get('/', 200)).text();
  assert.ok(/Marine survey, security and vessel escort operations/i.test(home), 'Unexpected public homepage');
  await get('/signup', 200);
  const protectedPage = await get('/dashboard', 401);
  assert.match(protectedPage.headers.get('www-authenticate') ?? '', /basic/i);
  await get('/api/operations', 401);
  await get('/api/health', 503);
  const css = /(?:href|src)="(\/_next\/static\/[^\"]+\.css(?:\?[^\"]*)?)"/.exec(home)?.[1];
  assert.ok(css, 'Public page did not reference a built stylesheet');
  await get(css, 200);
  await stopServer(server);
  server = undefined;

  // The local `pnpm start` entry point must also serve the standalone assets.
  const localPort = await unusedPort();
  server = spawn(process.execPath, [join(root, 'scripts/start-standalone.mjs')], {
    cwd: root, env: {...env, ALRIFAI_START_HOST: '127.0.0.1', PORT: String(localPort)},
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  await waitForReady(server);
  base = `http://127.0.0.1:${localPort}`;
  await get('/', 200);
  await get(css, 200);
  await get('/dashboard', 401);
  console.log('Standalone and local-start public pages/assets served; protected routes and database health failed closed.');
  console.log('Packaged workers loaded and remained disabled without production configuration.');
} finally {
  await stopServer(server);
  rmSync(stage, {recursive: true, force: true});
}
