export const CASH_SCOPE_ACCOUNT = 'wa-01' as const;
export const CASH_SCOPE_CHAT = '8801844836824@s.whatsapp.net' as const;
// Native-LID address for the same approved Accountant direct chat.
export const CASH_SCOPE_CHAT_LID = '19460614262828@lid' as const;
export const CASH_SCOPE_OWNER = '8801880446111@s.whatsapp.net' as const;
// Native-LID address paired to the configured Owner device.
export const CASH_SCOPE_OWNER_LID = '93282931581172@lid' as const;
export const CASH_SCOPE_ACCOUNTANT = '8801844836824@s.whatsapp.net' as const;
export const CASH_SCOPE_NAME = 'Cash Payment' as const;
export const CASH_SCOPE_CHATS = [CASH_SCOPE_CHAT,CASH_SCOPE_CHAT_LID] as const;

// Provenance epochs. Records are separated by provenance, never by message date.
export const CASH_CURRENT_EPOCH = 'CANONICAL_BACKFILL_20261026' as const;
export const CASH_ARCHIVE_EPOCH = 'LEGACY_PRE_TRANSITION_20261026' as const;

export function isCashScopeChat(chatJid: string){
 return (CASH_SCOPE_CHATS as readonly string[]).includes(chatJid);
}

export function isCashScopeOwner(sender: string){
 const base=sender.replace(/@.*$/,'').replace(/:\d+$/,'');
 return base===CASH_SCOPE_OWNER.replace(/@.*$/,'')||base===CASH_SCOPE_OWNER_LID.replace(/@.*$/,'');
}

// Server-owned scope. The browser cannot select another account, chat, or
// cash account through the /cash API.
export function cashScopeWhere(alias: string) {
  return [
    `${alias}.scope_account = '${CASH_SCOPE_ACCOUNT}'`,
    `${alias}.cash_account = '${CASH_SCOPE_NAME}'`,
  ];
}

// Current and Archive are disjoint by dataset epoch. Both use the same
// server-owned scope; the browser can only choose which epoch to read.
export function cashEpochWhere(alias: string, scope: 'CURRENT'|'ARCHIVE') {
  return `${alias}.dataset_epoch = '${scope==='ARCHIVE'?CASH_ARCHIVE_EPOCH:CASH_CURRENT_EPOCH}'`;
}

export function cashScopedWhere(alias: string, scope: 'CURRENT'|'ARCHIVE') {
  return [...cashScopeWhere(alias),cashEpochWhere(alias,scope)];
}
