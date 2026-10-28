// Unified server-side authentication helpers.
//
// Identity source: the deployed Cash Portal tables (public.cash_portal_users /
// public.cash_portal_sessions) and the deployed `__Host-alrifai_cash` cookie.
// Nothing here creates a user, resets a password, or rotates a credential on
// its own: every mutation is an explicit, authenticated, CSRF-checked action
// initiated by a signed-in human.
//
// Rollout gate: ALRIFAI_UNIFIED_AUTH_MODE = off | shadow | on (default off).
//   off    → every function below is inert; the legacy Basic guard is untouched.
//   shadow → /login and /api/auth/** work and prove the credentials, but the
//            workspace still requires the legacy guard (rehearsal mode).
//   on     → a valid Cash session also authorises the workspace; the legacy
//            Basic guard remains accepted as a fallback (never removed here).

import {cookies} from 'next/headers';
import {timingSafeEqual} from 'node:crypto';
import {
  audit,
  CashPortalError,
  createSession,
  database,
  findUser,
  hashPassword,
  hashToken,
  publicUser,
  refreshCsrf,
  revokeOtherSessions,
  userById,
  verifyPassword,
} from './cash-portal';
import {
  assertUsernameChange,
  isConfiguredSuperAdmin,
  normalizeUsername,
  originAllowed,
  parseCookieHeader,
  resolveCapabilities,
  sessionCookieName,
  unifiedAuthMode,
  UnifiedAuthError,
  type UnifiedAuthMode,
} from './unified-auth-policy';
import {loadSessionIdentity, revokeSession, type UnifiedIdentity} from './unified-auth-db';

export type UnifiedSession = {identity: UnifiedIdentity; token: string; csrf: string};

export function unifiedMode(): UnifiedAuthMode {
  return unifiedAuthMode(process.env.ALRIFAI_UNIFIED_AUTH_MODE);
}

function isEnabled(): boolean {
  return unifiedMode() !== 'off';
}

/**
 * Current unified session for a server component or route handler.
 * Returns null when the feature is disabled, when no cookie is present, or when
 * the session is unknown/expired/revoked/inactive. Never throws.
 */
export async function currentIdentity(): Promise<UnifiedIdentity | null> {
  if (!isEnabled()) return null;
  const name = sessionCookieName();
  let value: string | undefined;
  try {
    value = (await cookies()).get(name)?.value;
  } catch {
    return null;
  }
  if (!value) return null;
  return loadSessionIdentity(parseCookieHeader(`${name}=${value}`, name));
}

export async function requireIdentity(): Promise<UnifiedIdentity> {
  const identity = await currentIdentity();
  if (!identity) throw new UnifiedAuthError('AUTHENTICATION_REQUIRED', 401);
  return identity;
}

/** Admin Panel gate — the established Super Admin policy, server-side only. */
export async function requireWorkspaceAdmin(): Promise<UnifiedIdentity> {
  const identity = await requireIdentity();
  if (!isConfiguredSuperAdmin(identity.id, identity.role, process.env.ALRIFAI_CASH_SUPER_ADMIN_IDS)) {
    throw new UnifiedAuthError('SUPER_ADMIN_REQUIRED', 403);
  }
  return identity;
}

export function requireUnifiedOrigin(request: Request): void {
  if (!originAllowed(request.headers.get('origin'), process.env.ALRIFAI_UNIFIED_ORIGINS)) {
    throw new UnifiedAuthError('ORIGIN_DENIED', 403);
  }
}

// ---- Login throttling -------------------------------------------------------
// Keyed on the real client address injected by the private entry (which strips
// client-supplied x-forwarded-* headers) so one noisy source cannot lock the
// Owner out. Thresholds mirror the Cash Portal policy.
const FAILURE_WINDOW_MS = 15 * 60 * 1000;
const MAX_FAILURES_PER_CLIENT = 8;
const MAX_FAILURES_SHARED = 40;
const failures = new Map<string, {count: number; until: number}>();

function clientKey(request: Request): string {
  const direct = request.headers.get('x-alrifai-client-ip');
  if (direct) return direct.trim().slice(0, 80);
  const forwarded = request.headers.get('x-forwarded-for');
  if (forwarded) return forwarded.split(',')[0].trim().slice(0, 80);
  return 'unknown';
}

export function loginRateLimited(request: Request): boolean {
  const key = clientKey(request);
  const entry = failures.get(key);
  if (!entry) return false;
  if (entry.until <= Date.now()) {
    failures.delete(key);
    return false;
  }
  return entry.count >= (key === 'unknown' ? MAX_FAILURES_SHARED : MAX_FAILURES_PER_CLIENT);
}

export function noteLoginFailure(request: Request): void {
  const key = clientKey(request);
  const now = Date.now();
  const prior = failures.get(key);
  const next = !prior || prior.until <= now
    ? {count: 1, until: now + FAILURE_WINDOW_MS}
    : {count: prior.count + 1, until: prior.until};
  failures.set(key, next);
}

export function clearLoginFailures(request: Request): void {
  failures.delete(clientKey(request));
}

// ---- Login / logout ---------------------------------------------------------

export type LoginResult = {
  token: string;
  csrf: string;
  user: ReturnType<typeof publicUser> & {capabilities: string[]; superAdmin: boolean};
};

/**
 * Verifies the *existing* Cash Portal credential — the same stored PBKDF2 hash,
 * the same rate limit, the same session table. The password is never stored,
 * echoed, logged or compared against any other store.
 */
export async function loginWithCashCredential(
  request: Request,
  input: {username?: unknown; password?: unknown},
): Promise<LoginResult> {
  if (!isEnabled()) throw new UnifiedAuthError('UNIFIED_AUTH_DISABLED', 404);
  requireUnifiedOrigin(request);
  if (loginRateLimited(request)) throw new UnifiedAuthError('TOO_MANY_ATTEMPTS', 429);
  const username = typeof input.username === 'string' ? input.username.trim().slice(0, 80) : '';
  const password = typeof input.password === 'string' ? input.password : '';
  if (!username || !password) throw new UnifiedAuthError('CREDENTIALS_REQUIRED', 400);
  const row = await findUser(username);
  if (!row || !(await verifyPassword(password, row.password_hash))) {
    noteLoginFailure(request);
    throw new UnifiedAuthError('INVALID_CREDENTIALS', 401);
  }
  clearLoginFailures(request);
  const session = await createSession(request, row);
  await audit(row.id, row.id, 'LOGIN', {surface: 'unified'});
  return {
    token: session.token,
    csrf: session.csrf,
    user: {
      ...session.user,
      capabilities: resolveCapabilities(row.role, (row as {capabilities?: unknown}).capabilities),
      superAdmin: isConfiguredSuperAdmin(row.id, row.role, process.env.ALRIFAI_CASH_SUPER_ADMIN_IDS),
    },
  };
}

export async function logoutCurrent(token: string | null | undefined): Promise<void> {
  if (!token) return;
  await revokeSession(token);
}

// ---- Self-service credential actions (explicit user action only) ------------

export async function changeOwnPassword(
  identity: UnifiedIdentity,
  body: {currentPassword?: unknown; newPassword?: unknown; confirmPassword?: unknown},
  currentToken?: string | null,
): Promise<{otherSessionsRevoked: number}> {
  if (!isEnabled()) throw new UnifiedAuthError('UNIFIED_AUTH_DISABLED', 404);
  const current = typeof body.currentPassword === 'string' ? body.currentPassword : '';
  const next = typeof body.newPassword === 'string' ? body.newPassword : '';
  const confirm = typeof body.confirmPassword === 'string' ? body.confirmPassword : '';
  const row = await userById(identity.id);
  if (!row || !(await verifyPassword(current, row.password_hash))) {
    throw new UnifiedAuthError('CURRENT_PASSWORD_INVALID', 400);
  }
  if (next.length < 12 || Buffer.byteLength(next) > 256) throw new UnifiedAuthError('PASSWORD_POLICY', 400);
  if (next !== confirm) throw new UnifiedAuthError('PASSWORD_CONFIRMATION_MISMATCH', 400);
  if (await verifyPassword(next, row.password_hash)) throw new UnifiedAuthError('PASSWORD_UNCHANGED', 400);
  const encoded = await hashPassword(next);
  await database().query(
    'UPDATE public.cash_portal_users SET password_hash=$2,must_change_password=false,password_changed_at=now(),version=version+1 WHERE id=$1',
    [row.id, encoded],
  );
  // Credential change revokes every other session for this account. The caller's
  // own session survives so the change cannot lock the account out mid-action.
  const otherSessionsRevoked = await revokeOtherSessions(row.id, currentToken);
  await audit(row.id, row.id, 'PASSWORD_CHANGED', {surface: 'unified', otherSessionsRevoked});
  return {otherSessionsRevoked};
}

export async function changeOwnUsername(
  identity: UnifiedIdentity,
  body: {currentPassword?: unknown; username?: unknown},
): Promise<string> {
  if (!isEnabled()) throw new UnifiedAuthError('UNIFIED_AUTH_DISABLED', 404);
  const current = typeof body.currentPassword === 'string' ? body.currentPassword : '';
  const next = normalizeUsername(body.username);
  if (!next) throw new UnifiedAuthError('USERNAME_INVALID', 400);
  const row = await userById(identity.id);
  if (!row || !(await verifyPassword(current, row.password_hash))) {
    throw new UnifiedAuthError('CURRENT_PASSWORD_INVALID', 400);
  }
  assertUsernameChange(row.username, next);
  try {
    await database().query(
      'UPDATE public.cash_portal_users SET username=$2,username_changed_at=now(),version=version+1 WHERE id=$1',
      [row.id, next],
    );
  } catch (error) {
    if ((error as {code?: string}).code === '23505') throw new UnifiedAuthError('USERNAME_EXISTS', 409);
    if ((error as {code?: string}).code === '42703') throw new UnifiedAuthError('USERNAME_CHANGE_MIGRATION_REQUIRED', 503);
    throw error;
  }
  await audit(row.id, row.id, 'USERNAME_CHANGED', {from: row.username, to: next});
  return next;
}

/** CSRF helpers shared with the Cash Portal session row. */
export async function currentSession(request: Request): Promise<{identity: UnifiedIdentity; token: string}> {
  const identity = await requireIdentity();
  const token = parseCookieHeader(request.headers.get('cookie'), sessionCookieName());
  if (!token) throw new UnifiedAuthError('AUTHENTICATION_REQUIRED', 401);
  return {identity, token};
}

/** Issues a fresh CSRF token for the caller's existing session (read-only use). */
export async function currentCsrf(request: Request): Promise<{identity: UnifiedIdentity; token: string; csrf: string}> {
  const {identity, token} = await currentSession(request);
  const csrf = await refreshCsrf(token);
  return {identity, token, csrf};
}

export async function assertCsrf(request: Request, token: string | null | undefined): Promise<string> {
  if (!token) throw new UnifiedAuthError('AUTHENTICATION_REQUIRED', 401);
  const supplied = request.headers.get('x-csrf-token') ?? '';
  if (!/^[a-f0-9]{64}$/.test(supplied)) throw new UnifiedAuthError('CSRF_DENIED', 403);
  const row = await database().query<{csrf_hash: string}>(
    'SELECT csrf_hash FROM public.cash_portal_sessions WHERE id=$1',
    [hashToken(token)],
  );
  const stored = row.rows[0]?.csrf_hash;
  if (!stored || stored.length !== 64) throw new UnifiedAuthError('CSRF_DENIED', 403);
  const suppliedHash = Buffer.from(hashToken(supplied), 'hex');
  const storedHash = Buffer.from(stored, 'hex');
  if (suppliedHash.length !== storedHash.length || !timingSafeEqual(suppliedHash, storedHash)) {
    throw new UnifiedAuthError('CSRF_DENIED', 403);
  }
  return supplied;
}

/** Maps policy/portal errors onto the JSON contract used by the Cash API. */
export function authErrorBody(error: unknown): {error: string; status: number; headers: Record<string, string>} {
  if (error instanceof UnifiedAuthError) {
    return {error: error.code, status: error.status, headers: {'Cache-Control': 'no-store'}};
  }
  if (error instanceof CashPortalError) {
    return {error: error.code, status: error.status, headers: {'Cache-Control': 'no-store'}};
  }
  return {error: 'AUTH_ERROR', status: 500, headers: {'Cache-Control': 'no-store'}};
}
