// Evidence-based Vessel Order ↔ Admin Confirmation matching.
//
// Pure functions only: no database, no writes, no message sending. The matcher
// combines the Owner-approved evidence signals instead of relying on vessel-name
// string equality:
//   * same authorized client conversation (canonical, alias-aware);
//   * Mother/Lighter context, tolerant of spelling, spacing and prefix variants;
//   * Master Mobile digits (exact, or one digit apart with correction evidence);
//   * message chronology inside a bounded window;
//   * unique candidate only — two plausible orders stay AMBIGUOUS.
//
// Raw names and raw mobile strings are preserved; normalization is separate.

import { createHash } from 'node:crypto';
import { analyzeMobile, oneDigitApart } from './mobile-identity.mjs';

export type MatchState =
  | 'EXACT'
  | 'VARIANT'
  | 'CORRECTED'
  | 'AMBIGUOUS'
  | 'UNMATCHED'
  | 'WEAK_EVIDENCE';

export type OrderCandidate = {
  id: string;
  messageId?: string | null;
  chatJid: string;
  mother: string;
  lighter: string;
  masterRaw: string;
  sourceTime: string;
  contactId?: string | null;
  /** D/N when the order states a shift; supporting identity evidence only. */
  shift?: string | null;
};

export type ConfirmationCandidate = {
  messageId: string;
  chatJid: string;
  mother: string;
  lighter: string;
  masterRaw: string;
  sourceTime: string;
  contactId?: string | null;
  /** D/N when the Admin reply states a shift; supporting identity evidence only. */
  shift?: string | null;
};

export type MatchResult = {
  state: MatchState;
  orderId: string | null;
  orderMessageId: string | null;
  candidateIds: string[];
  mobileEvidence: 'EXACT' | 'CORRECTED' | 'WEAK' | 'CONFLICT' | 'NONE';
  /** Shift agreement is corroborating evidence, never a stand-alone match. */
  shiftEvidence: 'AGREE' | 'CONFLICT' | 'UNVERIFIED';
  reasons: string[];
};

/** Normalized comparison key: prefix, punctuation, spacing and case removed. */
export function vesselKey(name: string): string {
  return String(name ?? '')
    .normalize('NFC')
    .toLowerCase()
    .replace(/^m\.?\s*v\.?\s*[:.]?\s*/i, '')
    .replace(/[^\p{L}\p{N}]/gu, '');
}

/**
 * Conservative phonetic key. Only unambiguous English transliterations are
 * folded; Bengali spellings are compared on the normalized key plus edit
 * distance. Names are never merged on this key alone.
 */
export function phoneticKey(name: string): string {
  return vesselKey(name)
    .replace(/ph/g, 'f')
    .replace(/ck/g, 'k')
    .replace(/q/g, 'k')
    .replace(/x/g, 'ks')
    .replace(/z/g, 'j')
    .replace(/ee/g, 'i')
    .replace(/oo/g, 'u')
    .replace(/w/g, 'v')
    .replace(/(.)\1+/g, '$1');
}

function editDistance(a: string, b: string): number {
  if (a === b) return 0;
  if (!a || !b) return Math.max(a.length, b.length);
  let previous = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i += 1) {
    const current = [i];
    for (let j = 1; j <= b.length; j += 1) {
      current[j] = Math.min(
        current[j - 1] + 1,
        previous[j] + 1,
        previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    }
    previous = current;
  }
  return previous[b.length];
}

export type VesselSimilarity = 'SAME' | 'VARIANT' | 'DIFFERENT';

export function compareVesselNames(left: string, right: string): VesselSimilarity {
  const a = vesselKey(left);
  const b = vesselKey(right);
  if (!a || !b) return 'DIFFERENT';
  if (a === b) return 'SAME';
  if (phoneticKey(left) === phoneticKey(right)) return 'VARIANT';
  const shortest = Math.min(a.length, b.length);
  const distance = editDistance(a, b);
  if (distance === 1 && shortest >= 4) return 'VARIANT';
  if (distance === 2 && shortest >= 8) return 'VARIANT';
  return 'DIFFERENT';
}

/**
 * Later "corrected Master Mobile" messages in the same conversation. A correction
 * is a valid 11-digit number stated for the same Lighter after the original
 * order. It is evidence, not an overwrite.
 */
export function masterCorrections(
  messages: Array<{ chatJid: string; mother: string; lighter: string; masterRaw: string; sourceTime: string }>,
): Map<string, string> {
  const out = new Map<string, string>();
  const ordered = [...messages].sort((a, b) => Date.parse(a.sourceTime) - Date.parse(b.sourceTime));
  for (const message of ordered) {
    const mobile = analyzeMobile(message.masterRaw);
    if (!mobile.valid) continue;
    const key = `${message.chatJid}|${vesselKey(message.lighter)}`;
    out.set(key, mobile.digits);
  }
  return out;
}

function mobileEvidence(orderRaw: string, confirmationRaw: string, correction?: string) {
  const order = analyzeMobile(orderRaw);
  const confirmation = analyzeMobile(confirmationRaw);
  if (order.valid && confirmation.valid) {
    return order.digits === confirmation.digits
      ? { kind: 'EXACT' as const, reason: null as string | null }
      : { kind: 'CONFLICT' as const, reason: 'MASTER_MOBILE_CONFLICT' };
  }
  if (order.valid || confirmation.valid) {
    const known = order.valid ? order.digits : confirmation.digits;
    const other = order.valid ? confirmation : order;
    if (oneDigitApart(known, other.raw) || oneDigitApart(known, other.digits)) {
      if (correction && correction === known) return { kind: 'CORRECTED' as const, reason: 'MASTER_MOBILE_CORRECTION_EVIDENCE' };
      return { kind: 'CORRECTED' as const, reason: 'MASTER_MOBILE_ONE_DIGIT_DISCREPANCY' };
    }
    return { kind: 'CONFLICT' as const, reason: 'MASTER_MOBILE_CONFLICT' };
  }
  if (correction) {
    const other = analyzeMobile(confirmationRaw).digits || analyzeMobile(orderRaw).digits;
    if (other && correction === other) return { kind: 'CORRECTED' as const, reason: 'MASTER_MOBILE_CORRECTION_EVIDENCE' };
  }
  return { kind: 'WEAK' as const, reason: 'MASTER_MOBILE_UNRESOLVED' };
}

export type MatchOptions = {
  windowDays?: number;
  corrections?: Map<string, string>;
  canonicalChat?: (chatJid: string) => string;
};

/** D/N normalization; unknown tokens are preserved but never treated as equal. */
export function normalizeShift(value?: string | null): string {
  const shift = String(value ?? '').trim().toUpperCase();
  if (!shift) return '';
  if (shift === 'D' || shift === 'DAY' || shift === 'DAY SHIFT' || shift === 'দিন') return 'D';
  if (shift === 'N' || shift === 'NIGHT' || shift === 'NIGHT SHIFT' || shift === 'রাত') return 'N';
  return shift;
}

/** Shift agreement between one order and the Admin reply. */
export function shiftEvidence(order: {shift?: string | null}, confirmation: {shift?: string | null}): 'AGREE' | 'CONFLICT' | 'UNVERIFIED' {
  const a = normalizeShift(order.shift);
  const b = normalizeShift(confirmation.shift);
  if (!a || !b) return 'UNVERIFIED';
  return a === b ? 'AGREE' : 'CONFLICT';
}

/**
 * Match one outgoing confirmation block against the client's order candidates.
 * Returns a single deterministic state; ambiguous evidence never resolves.
 */
export function matchConfirmation(
  orders: OrderCandidate[],
  confirmation: ConfirmationCandidate,
  options: MatchOptions = {},
): MatchResult {
  const windowDays = options.windowDays ?? 30;
  const canonical = options.canonicalChat ?? ((jid: string) => jid);
  const chat = canonical(confirmation.chatJid);
  const confirmationTime = Date.parse(confirmation.sourceTime);
  const reasons: string[] = [];

  const sameConversation = orders.filter((order) => canonical(order.chatJid) === chat
    && (!confirmation.contactId || !order.contactId || order.contactId === confirmation.contactId));
  const sameVessels = sameConversation.filter((order) =>
    compareVesselNames(order.mother, confirmation.mother) !== 'DIFFERENT'
    && compareVesselNames(order.lighter, confirmation.lighter) !== 'DIFFERENT');

  const candidates = sameVessels.filter((order) => {
    const orderTime = Date.parse(order.sourceTime);
    if (!Number.isFinite(orderTime)) return true; // chronology unverified, keep as evidence
    if (!Number.isFinite(confirmationTime)) return true;
    if (orderTime > confirmationTime) return false;
    return (confirmationTime - orderTime) / 86_400_000 <= windowDays;
  });

  if (!candidates.length) {
    if (sameVessels.length) reasons.push('ORDER_OUTSIDE_TEMPORAL_WINDOW');
    return { state: 'UNMATCHED', orderId: null, orderMessageId: null, candidateIds: [], mobileEvidence: 'NONE', shiftEvidence: 'UNVERIFIED', reasons };
  }

  // Score each candidate on vessel and mobile evidence; a conflict disqualifies it.
  const scored = candidates.map((order) => {
    const mother = compareVesselNames(order.mother, confirmation.mother);
    const lighter = compareVesselNames(order.lighter, confirmation.lighter);
    const correction = options.corrections?.get(`${chat}|${vesselKey(order.lighter)}`)
      ?? options.corrections?.get(`${order.chatJid}|${vesselKey(order.lighter)}`);
    const mobile = mobileEvidence(order.masterRaw, confirmation.masterRaw, correction);
    return { order, mother, lighter, mobile };
  });

  const viable = scored.filter((candidate) => candidate.mobile.kind !== 'CONFLICT');
  if (!viable.length) {
    return { state: 'UNMATCHED', orderId: null, orderMessageId: null, candidateIds: candidates.map((c) => c.id), mobileEvidence: 'CONFLICT', shiftEvidence: 'UNVERIFIED', reasons: ['MASTER_MOBILE_CONFLICT'] };
  }
  // Shift is corroborating evidence only: a shared shift may break a tie, but a
  // shift alone can never create a match, and disagreement never confirms.
  const confirmationShift = normalizeShift(confirmation.shift);
  const preferred = confirmationShift
    ? viable.filter((candidate) => normalizeShift(candidate.order.shift) === confirmationShift)
    : [];
  const pool = preferred.length ? preferred : viable;
  if (pool.length > 1) {
    return {
      state: 'AMBIGUOUS',
      orderId: null,
      orderMessageId: null,
      candidateIds: pool.map((c) => c.order.id),
      mobileEvidence: 'EXACT',
      shiftEvidence: 'UNVERIFIED',
      reasons: ['MULTIPLE_ORDER_CANDIDATES'],
    };
  }

  const winner = pool[0];
  const shift = shiftEvidence(winner.order, confirmation);
  const sameNames = winner.mother === 'SAME' && winner.lighter === 'SAME';
  const shiftConflict = shift === 'CONFLICT'
    ? { state: 'AMBIGUOUS' as const, orderId: null, orderMessageId: null, candidateIds: [winner.order.id], mobileEvidence: 'EXACT' as const, shiftEvidence: 'CONFLICT' as const, reasons: ['SHIFT_CONFLICT'] }
    : null;
  if (winner.mobile.kind === 'EXACT') {
    if (shiftConflict) return shiftConflict;
    return {
      state: sameNames ? 'EXACT' : 'VARIANT',
      orderId: winner.order.id,
      orderMessageId: winner.order.messageId ?? null,
      candidateIds: [winner.order.id],
      mobileEvidence: 'EXACT',
      shiftEvidence: shift,
      reasons: [...(sameNames ? [] : ['VESSEL_SPELLING_VARIANT']), ...(shift === 'UNVERIFIED' ? ['SHIFT_UNVERIFIED'] : [])],
    };
  }
  if (winner.mobile.kind === 'CORRECTED') {
    if (shiftConflict) return {...shiftConflict, mobileEvidence: 'CORRECTED'};
    const hasCorrection = !!options.corrections?.get(`${chat}|${vesselKey(winner.order.lighter)}`);
    return {
      state: 'CORRECTED',
      orderId: winner.order.id,
      orderMessageId: winner.order.messageId ?? null,
      candidateIds: [winner.order.id],
      mobileEvidence: 'CORRECTED',
      shiftEvidence: shift,
      reasons: [winner.mobile.reason ?? 'MASTER_MOBILE_ONE_DIGIT_DISCREPANCY', ...(hasCorrection ? [] : ['CORRECTION_MESSAGE_NOT_FOUND']), ...(shift === 'UNVERIFIED' ? ['SHIFT_UNVERIFIED'] : [])],
    };
  }
  return {
    state: 'WEAK_EVIDENCE',
    orderId: winner.order.id,
    orderMessageId: winner.order.messageId ?? null,
    candidateIds: [winner.order.id],
    mobileEvidence: 'WEAK',
    shiftEvidence: shift,
    reasons: [winner.mobile.reason ?? 'MASTER_MOBILE_UNRESOLVED'],
  };
}

/** States that may create a confirmed program without further review. */
export function isConfirmable(state: MatchState): boolean {
  return state === 'EXACT' || state === 'VARIANT' || state === 'CORRECTED';
}

/** Deterministic program identity: replaying the same evidence cannot duplicate. */
export function programIdFor(input: {
  account: string;
  clientChat: string;
  mother: string;
  lighter: string;
  startDate: string;
  shift: string;
}): string {
  return createHash('sha256').update(JSON.stringify([
    'alrifai-vessel-program-v1',
    input.account,
    input.clientChat,
    vesselKey(input.mother),
    vesselKey(input.lighter),
    input.startDate,
    input.shift,
  ])).digest('hex');
}

/** Normalized comparison value for an order/confirmation master mobile. */
export function masterKey(raw: string): string {
  return analyzeMobile(raw).digits;
}
