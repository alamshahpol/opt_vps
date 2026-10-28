import {NextRequest} from "next/server";
import {clearCookie,cookieHeader,json,noStoreHeaders} from "@/lib/cash-portal";
import {
  assertCsrf,
  authErrorBody,
  changeOwnPassword,
  changeOwnUsername,
  currentCsrf,
  currentSession,
  loginWithCashCredential,
  logoutCurrent,
  requireUnifiedOrigin,
  unifiedMode,
} from "@/lib/unified-auth";
import {sanitizeReturnTo,UnifiedAuthError} from "@/lib/unified-auth-policy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

function reply(data: unknown, status = 200, headers: HeadersInit = {}) {
  return json(data, status, {...noStoreHeaders(), ...headers});
}

async function readBody(request: Request): Promise<Row> {
  try {
    const value = await request.json();
    return value && typeof value === "object" ? (value as Row) : {};
  } catch {
    throw new UnifiedAuthError("INVALID_JSON", 400);
  }
}

async function handle(request: NextRequest, segments: string[]) {
  const action = segments[0] || "";
  if (unifiedMode() === "off") return reply({error: "UNIFIED_AUTH_DISABLED"}, 404);

  // Sign in with the existing Cash Portal credential. Same store, same hash,
  // same session table — no second password is introduced.
  if (request.method === "POST" && action === "login") {
    const body = await readBody(request);
    const result = await loginWithCashCredential(request, {
      username: body.username,
      password: body.password,
    });
    return reply(
      {
        user: result.user,
        csrf: result.csrf,
        redirect: sanitizeReturnTo(typeof body.next === "string" ? body.next : "/dashboard"),
      },
      200,
      {"Set-Cookie": cookieHeader(result.token)},
    );
  }

  if (request.method === "POST" && action === "logout") {
    requireUnifiedOrigin(request);
    const {token} = await currentSession(request);
    await assertCsrf(request, token);
    await logoutCurrent(token);
    return reply({ok: true}, 200, {"Set-Cookie": clearCookie()});
  }

  if (request.method === "GET" && action === "session") {
    const {identity, csrf} = await currentCsrf(request);
    return reply({user: identity, csrf});
  }

  // Voluntary, authenticated, password-confirmed credential changes only.
  if (request.method === "POST" && action === "password") {
    requireUnifiedOrigin(request);
    const {identity, token} = await currentSession(request);
    await assertCsrf(request, token);
    const body = await readBody(request);
    await changeOwnPassword(identity, body);
    return reply({ok: true});
  }

  if (request.method === "POST" && action === "username") {
    requireUnifiedOrigin(request);
    const {identity, token} = await currentSession(request);
    await assertCsrf(request, token);
    const body = await readBody(request);
    const username = await changeOwnUsername(identity, body);
    return reply({ok: true, username});
  }

  throw new UnifiedAuthError("NOT_FOUND", 404);
}

async function guarded(request: NextRequest, segments: string[]) {
  try {
    return await handle(request, segments);
  } catch (error) {
    const mapped = authErrorBody(error);
    return reply({error: mapped.error}, mapped.status, mapped.headers);
  }
}

export async function GET(request: NextRequest, {params}: {params: Promise<{path: string[]}>}) {
  return guarded(request, (await params).path || []);
}

export async function POST(request: NextRequest, {params}: {params: Promise<{path: string[]}>}) {
  return guarded(request, (await params).path || []);
}
