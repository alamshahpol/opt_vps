// Shadow-mode redirect-cycle regression (2026-10-28 ERR_TOO_MANY_REDIRECTS).
//
// Incident: with a valid `__Host-alrifai_cash` session cookie the sign-in page
// forwarded the visitor to /dashboard, while shadow mode refused to authorise
// that route and sent the browser back to /login:
//
//   /login 307 -> /dashboard 302 -> /login?next=%2Fdashboard 307 -> ...
//
// This test replays the two cooperating decisions with a *valid session* and
// asserts the shipped policy terminates the chain. It deliberately includes the
// pre-fix rule so the original loop is reproduced and would fail again if the
// guard were removed.
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  sanitizeReturnTo,
  signedInRedirectTarget,
  unifiedAuthMode,
} from '../lib/unified-auth-policy.ts';

const PROTECTED = ['/dashboard', '/admin', '/review'];

/** proxy.ts decision for a document navigation without the legacy credential. */
function proxyDecision(mode, path, hasSession) {
  if (mode === 'off') return {status: 401, location: null};
  if (mode === 'on' && hasSession) return {status: 200, location: null};
  // shadow (and on without a session): document navigation goes to /login.
  return {status: 302, location: `/login?next=${encodeURIComponent(path)}`};
}

/** app/login/page.tsx decision. `forwardAlways` models the pre-fix defect. */
function loginDecision(mode, url, hasSession, {forwardAlways = false} = {}) {
  if (!hasSession) return {status: 200, location: null};
  const query = url.includes('?') ? url.slice(url.indexOf('?') + 1) : '';
  const requested = new URLSearchParams(query).get('next') || '/dashboard';
  const target = forwardAlways ? sanitizeReturnTo(requested) : signedInRedirectTarget(mode, requested);
  return target ? {status: 307, location: target} : {status: 200, location: null};
}

function walk(start, mode, {hasSession = true, forwardAlways = false, maxHops = 8} = {}) {
  const hops = [];
  let url = start;
  for (let i = 0; i < maxHops; i += 1) {
    const path = url.split('?')[0];
    const decision = mode === 'off'
      ? {status: 401, location: null}
      : path === '/login'
        ? loginDecision(mode, url, hasSession, {forwardAlways})
        : proxyDecision(mode, path, hasSession);
    hops.push({url, status: decision.status, location: decision.location});
    if (hops.filter((hop) => hop.url === url).length > 1) return {hops, terminated: false, looped: true};
    if (!decision.location) return {hops, terminated: true, looped: false};
    url = decision.location;
  }
  return {hops, terminated: false, looped: true};
}

test('the pre-fix rule reproduces the production loop with a valid session', () => {
  const preFix = walk('/login', 'shadow', {hasSession: true, forwardAlways: true});
  assert.equal(preFix.looped, true, 'the old unconditional forward must cycle');
  assert.deepEqual(preFix.hops.slice(0, 4).map((hop) => `${hop.status} ${hop.url}`), [
    '307 /login',
    '302 /dashboard',
    '307 /login?next=%2Fdashboard',
    '302 /dashboard',
  ]);
});

test('shadow + valid cookie: /login renders instead of looping', () => {
  for (const start of ['/login', '/login?next=%2Fdashboard', '/login?next=%2Fadmin']) {
    const result = walk(start, 'shadow');
    assert.equal(result.terminated, true, `${start} terminates`);
    assert.equal(result.looped, false, `${start} does not repeat a URL`);
    assert.equal(result.hops.length, 1);
    assert.equal(result.hops[0].status, 200);
  }
});

test('shadow + valid cookie: dashboard, admin and review stay behind the legacy guard', () => {
  for (const path of PROTECTED) {
    const result = walk(path, 'shadow');
    assert.equal(result.terminated, true);
    assert.equal(result.looped, false);
    // First hop refuses the session (302 to /login), second hop is the form.
    assert.equal(result.hops[0].status, 302);
    assert.equal(result.hops[0].location, `/login?next=${encodeURIComponent(path)}`);
    assert.equal(result.hops[1].status, 200);
    assert.ok(!result.hops.some((hop) => hop.status === 200 && hop.url.split('?')[0] !== '/login'),
      'no protected page is authorised by the session in shadow');
  }
});

test('shadow without a cookie is unchanged and never redirects from /login', () => {
  const result = walk('/login', 'shadow', {hasSession: false});
  assert.equal(result.hops.length, 1);
  assert.equal(result.hops[0].status, 200);
});

test('off mode keeps the legacy guard and cannot loop', () => {
  for (const path of ['/login', ...PROTECTED]) {
    const result = walk(path, 'off');
    assert.equal(result.hops.length, 1);
    assert.equal(result.hops[0].status, 401);
  }
});

test('on mode (isolated model only) forwards once and then authorises', () => {
  const fromLogin = walk('/login', 'on');
  assert.equal(fromLogin.looped, false);
  assert.deepEqual(fromLogin.hops.map((hop) => `${hop.status} ${hop.url}`), [
    '307 /login',
    '200 /dashboard',
  ]);
  const fromProtected = walk('/admin', 'on');
  assert.deepEqual(fromProtected.hops.map((hop) => `${hop.status} ${hop.url}`), ['200 /admin']);
});

test('unknown or absent mode degrades to off, never to a redirect', () => {
  assert.equal(unifiedAuthMode(undefined), 'off');
  assert.equal(unifiedAuthMode('enabled'), 'off');
  for (const mode of [unifiedAuthMode(undefined), unifiedAuthMode('enabled')]) {
    const result = walk('/login', mode, {hasSession: true, forwardAlways: true});
    assert.equal(result.hops[0].status, 401);
  }
});
