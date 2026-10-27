import {requireChatGPTUser} from '@/app/chatgpt-auth';
import {AppShell,type ShellUser} from '@/app/platform/app-shell';

/**
 * Server-side guard + shell for the unified platform routes. Reuses the
 * existing validation-password authentication; roles are display-level only
 * and every write remains behind the existing services.
 */
export async function PlatformPage(
  {children,label,title,actions,pathname}:
  {children:React.ReactNode;label:string;title?:string;actions?:React.ReactNode;pathname:string}
){
  const user=await requireChatGPTUser(pathname);  // Role display only — deriving admin flag from the fixed validation identity
  // does not grant any permission; all writes are disabled at UI level.
  const admin=(user.userId==='local-validator');
  const shellUser:ShellUser={...user,admin};
  return <AppShell user={shellUser} label={label} title={title} actions={actions}>{children}</AppShell>;
}
