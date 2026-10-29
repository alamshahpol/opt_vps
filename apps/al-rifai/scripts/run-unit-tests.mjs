#!/usr/bin/env node
// Offline suite: no database URL, private evidence or production configuration
// is inherited. Integration/evidence tests have separate, explicit entry points.
import {spawnSync} from 'node:child_process';

const files = [
  'escort-register', 'whatsapp-archive-ingestion', 'cash-intake-safety',
  'vessel-match', 'cash-user-policy', 'cash-approval', 'escort-confirmation-integrity',
  'duplicate-identity', 'payroll-rules', 'order-draft', 'vessel-reports',
  'vessel-commands', 'entry-rules', 'cash-submission', 'escort-register-api',
  'cash-super-admin-auth', 'vessel-health-isolation', 'vessel-url-state',
  'escort-lifecycle-ui', 'stored-history-mcp-archive', 'unified-auth-policy',
  'unified-auth-integration', 'unified-auth-shadow-loop', 'public-site-and-currency',
  'cash-password-revocation', 'install-readiness', 'business-workflows',
  'employee-program', 'identity-review-ui', 'message-mirror', 'reconciliation',
  'replay-metrics', 'request-drain', 'whatsapp-archive', 'workflow-r1-repair',
  'rehearsal-bootstrap',
].map(name => `tests/${name}.mjs`);
const env = {};
for (const name of ['PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'SystemRoot', 'LANG', 'TZ']) {
  if (process.env[name] !== undefined) env[name] = process.env[name];
}
const commands = [
  ['--experimental-strip-types', '--test', '--test-skip-pattern=uploaded WhatsApp exports remain read-only parser reference fixtures', ...files],
  ['--experimental-strip-types', 'tests/workflows.mjs'],
  ['--experimental-strip-types', 'tests/phase1-unit.mjs'],
];
for (const args of commands) {
  const result = spawnSync(process.execPath, args, {stdio: 'inherit', env});
  if (result.error) {
    console.error(`Could not start offline test runner: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}
