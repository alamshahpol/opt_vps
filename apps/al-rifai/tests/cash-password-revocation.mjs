// Session-revocation parity on the Cash Portal password endpoint.
//
// The three behavioural cases (3 sessions → other 2 rejected; wrong current
// password → no revocation; admin/unified path unchanged) are executed against a
// real server in the isolated release harness. This file pins the source
// invariants that make those behaviours hold, so a refactor cannot silently
// remove the protection.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const source = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const cashRoute = source('app/api/cash/[...path]/route.ts');
const portal = source('lib/cash-portal.ts');
const unified = source('lib/unified-auth.ts');

const passwordBlock = (() => {
  const start = cashRoute.indexOf('if(action==="password"&&request.method==="POST")');
  assert.ok(start > -1, 'cash password handler present');
  return cashRoute.slice(start, cashRoute.indexOf('if(action==="users"', start));
})();

test('one revocation implementation is shared by both password paths', () => {
  // The SQL lives only in the session store, not duplicated per route.
  const sqlCount = (portal.match(/DELETE FROM public\.cash_portal_sessions/g) || []).length;
  assert.equal(sqlCount, 1);
  assert.doesNotMatch(unified, /DELETE FROM public\.cash_portal_sessions/);
  // The admin reset path may delete every session for its target, but the
  // self-service handler must not carry its own copy of the "except caller" SQL.
  assert.doesNotMatch(passwordBlock, /DELETE FROM public\.cash_portal_sessions/);
  assert.match(unified, /revokeOtherSessions\(row\.id, currentToken\)/);
  assert.match(passwordBlock, /revokeOtherSessions\(row\.id,result\.token\)/);
});

test('a successful change revokes other sessions and keeps the caller signed in', () => {
  // The caller's own token is the one excluded from the delete.
  assert.match(portal, /user_id=\$1 AND \(\$2='' OR id<>\$2\)/);
  assert.match(portal, /return Number\(revoked\.rows\[0\]\?\.n\?\?0\)/);
  assert.ok(passwordBlock.indexOf('revokeOtherSessions') > passwordBlock.indexOf('UPDATE public.cash_portal_users'));
  // The audit row records how many sessions were removed.
  assert.match(passwordBlock, /audit\(row\.id,row\.id,"PASSWORD_CHANGED",\{surface:"cash",otherSessionsRevoked\}\)/);
  assert.match(passwordBlock, /otherSessionsRevoked\}/);
});

test('a failed current-password check performs no write and no revocation', () => {
  const verified = passwordBlock.indexOf('CURRENT_PASSWORD_INVALID');
  const update = passwordBlock.indexOf('UPDATE public.cash_portal_users');
  const revoke = passwordBlock.indexOf('revokeOtherSessions');
  const audit = passwordBlock.indexOf('PASSWORD_CHANGED');
  assert.ok(verified > -1 && update > -1 && revoke > -1 && audit > -1);
  assert.ok(verified < update, 'verification precedes the password write');
  assert.ok(verified < revoke, 'verification precedes revocation');
  assert.ok(verified < audit, 'verification precedes the audit row');
  // Every failure path returns before the write.
  const guard = passwordBlock.slice(Math.max(0, passwordBlock.lastIndexOf('if(', verified)), update);
  assert.match(guard, /CURRENT_PASSWORD_INVALID/);
  assert.match(guard, /return reply\(\{error:"CURRENT_PASSWORD_INVALID"\},400\)/);
});

test('the existing guards, policy and cookie attributes are untouched', () => {
  assert.match(portal, /__Host-alrifai_cash/);
  assert.match(portal, /HttpOnly; Secure; SameSite=Strict/);
  // CSRF is enforced by the shared auth() helper the route calls for mutations.
  assert.match(portal, /x-csrf-token/);
  assert.match(cashRoute, /await auth\(request,request\.method!=="GET"\)/);
  assert.match(cashRoute, /function requireOrigin|requireOrigin\(request\)/);
  assert.match(passwordBlock, /next\.length<12/);
  assert.match(passwordBlock, /PASSWORD_CONFIRMATION_MISMATCH/);
  // The admin reset path still removes every session for the target.
  assert.match(cashRoute, /DELETE FROM public\.cash_portal_sessions WHERE user_id=\$1/);
});
