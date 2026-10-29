#!/usr/bin/env node
// Non-mutating prerequisite check. Never reads the contents of credentials or
// private evidence and never connects to a database or WhatsApp bridge.
import {accessSync, constants, statSync} from 'node:fs';
import {createRequire} from 'node:module';
import {join} from 'node:path';

const require = createRequire(import.meta.url);
const strict = process.argv.slice(2).includes('--strict');
if (process.argv.slice(2).some(arg => arg !== '--strict')) {
  console.error('Usage: node scripts/install-check.mjs [--strict]');
  process.exit(2);
}

function readableFile(path) {
  try {
    accessSync(path, constants.R_OK);
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

const [major, minor] = process.versions.node.split('.').map(Number);
const nodeReady = major > 22 || (major === 22 && minor >= 13);
let dependenciesReady = false;
try {
  require.resolve('next/package.json');
  require.resolve('pg/package.json');
  require.resolve('zod/package.json');
  dependenciesReady = true;
} catch {
  // A clean checkout has no dependencies until the frozen-lockfile install.
}

const evidenceDir = process.env.ALRIFAI_EVIDENCE_DIR || '/var/lib/vps/al-rifai/evidence';
const evidenceFiles = [
  'accounts-snapshot.json', 'chat-archive.json', 'conversation-snapshot.json',
  'operations.json', 'recovered-programs.json',
];
const evidenceCount = evidenceFiles.filter(name => readableFile(join(evidenceDir, name))).length;
const validationReady = readableFile(process.env.ALRIFAI_VALIDATION_PASSWORD_FILE || '/run/secrets/validation_password');
const databaseReady = readableFile(process.env.PGPASSWORD_FILE || '/run/secrets/database_password');
// Cash portal and live-Cash reader currently use this fixed runtime path.
const reviewReady = readableFile('/etc/vps/apps/al-rifai/auth/pg-password');

const line = (name, ready, detail = '') => console.log(`${ready ? 'OK' : 'MISSING'}  ${name}${detail ? `: ${detail}` : ''}`);
line('Node.js >=22.13', nodeReady, process.versions.node);
line('Installed application dependencies', dependenciesReady);
line('Private evidence files readable', evidenceCount === evidenceFiles.length, `${evidenceCount}/${evidenceFiles.length}`);
line('Validation password file readable', validationReady);
line('Database password file readable', databaseReady);
line('Cash review password file readable', reviewReady);
console.log('File checks only: contents, checksum validity, database/schema, TLS, permissions and WhatsApp are NOT verified.');
console.log('No credentials or business data were read; no services or migrations were started.');

if (!nodeReady || !dependenciesReady || (strict && (evidenceCount !== evidenceFiles.length || !validationReady || !databaseReady || !reviewReady))) {
  process.exitCode = 1;
}
