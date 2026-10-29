#!/usr/bin/env node
// Python's default suite is offline too, even if the caller's shell contains
// production evidence, export, credential, or database settings.
import {spawnSync} from 'node:child_process';

const env = {PYTHONDONTWRITEBYTECODE: '1'};
for (const name of ['PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'SystemRoot', 'LANG', 'TZ']) {
  if (process.env[name] !== undefined) env[name] = process.env[name];
}
for (const directory of ['tests', 'tests/disposable-cash-delivery']) {
  const result = spawnSync('python3', ['-m', 'unittest', 'discover', '-s', directory, '-p', 'test_*.py'], {
    stdio: 'inherit', env,
  });
  if (result.error) {
    console.error(`Could not start Python 3: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}
