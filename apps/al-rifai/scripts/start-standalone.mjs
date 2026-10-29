#!/usr/bin/env node
// Next's standalone output does not include static/public assets by default.
// Populate only the generated build tree, then run its server on loopback unless
// an operator explicitly selects another interface via ALRIFAI_START_HOST.
import {cpSync, existsSync, mkdirSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const standalone = join(root, '.next', 'standalone');
const server = join(standalone, 'server.js');
if (!existsSync(server)) {
  console.error('Standalone build missing; run "corepack pnpm build" first.');
  process.exit(1);
}
for (const [source, destination] of [
  [join(root, 'public'), join(standalone, 'public')],
  [join(root, '.next', 'static'), join(standalone, '.next', 'static')],
]) {
  if (!existsSync(source)) {
    console.error('Build assets missing; run "corepack pnpm build" first.');
    process.exit(1);
  }
  mkdirSync(destination, {recursive: true});
  cpSync(source, destination, {recursive: true, force: true});
}
process.env.HOSTNAME = process.env.ALRIFAI_START_HOST || '127.0.0.1';
process.env.PORT ||= '3000';
await import(pathToFileURL(server).href);
