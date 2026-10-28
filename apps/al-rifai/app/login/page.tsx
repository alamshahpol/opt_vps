import type {Metadata} from 'next';
import {redirect} from 'next/navigation';
import {currentIdentity, unifiedMode} from '@/lib/unified-auth';
import {sanitizeReturnTo} from '@/lib/unified-auth-policy';
import LoginView from './view';

export const dynamic = 'force-dynamic';
export const metadata: Metadata = {title: 'Sign in · AL-RIFA’I', robots: {index: false, follow: false}};

/**
 * Unified sign-in surface.
 *
 * Uses the existing verified Cash Portal credential (public.cash_portal_users)
 * and the deployed session cookie. It never renames, resets or rotates any
 * account: the Owner's live username and password stay exactly as they are.
 */
export default async function LoginPage({searchParams}: {searchParams: Promise<Record<string, string | string[] | undefined>>}) {
  const params = await searchParams;
  const raw = typeof params.next === 'string' ? params.next : '/dashboard';
  const next = sanitizeReturnTo(raw);
  const mode = unifiedMode();
  if (mode === 'off') redirect('/');
  const identity = await currentIdentity();
  if (identity) redirect(next);
  return <LoginView next={next} mode={mode} />;
}
