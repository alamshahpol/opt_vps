import {NextRequest} from "next/server";
import {auth,audit,bodyOptional,bodyString,CashPortalError,clearCookie,clearLoginFailures,createSession,cookieHeader,database,findUser,hashPassword,hashToken,json,loginRateLimited,noStoreHeaders,noteLoginFailure,publicUser,refreshCsrf,requireOrigin,requireCashSuperAdmin,verifyPassword,userById,isCashSuperAdmin} from "@/lib/cash-portal";
import {assertCanCreateUser,assertCanManageUser,assertCanResetPassword,CashUserPolicyError} from "@/lib/cash-user-policy";
import {CASH_SCOPE_ACCOUNT,CASH_SCOPE_CHATS,cashScopedWhere} from "@/lib/cash-scope";

export const runtime="nodejs";
export const dynamic="force-dynamic";
type Row=Record<string,unknown>;
function reply(data:unknown,status=200,headers:HeadersInit={}){return json(data,status,{...noStoreHeaders(),...headers});}
async function readBody(request:Request){try{const value=await request.json();return value&&typeof value==="object"?value as Row:{};}catch{throw new CashPortalError("INVALID_JSON",400);}}
function requireAdmin(user:{role:string}){if(user.role!=="ADMIN")throw new CashPortalError("ADMIN_REQUIRED",403);}
/** Runs a pure policy guard and maps its denial into the portal error contract. */
function policy(guard:()=>void){try{guard();}catch(e){if(e instanceof CashUserPolicyError)throw new CashPortalError(e.code,403);throw e;}}
async function activeAdminCount(){const row=await database().query<{n:number}>("SELECT count(*)::int AS n FROM public.cash_portal_users WHERE role='ADMIN' AND active=true");return Number(row.rows[0]?.n??0);}
function forced(user:{mustChangePassword:boolean}){if(user.mustChangePassword)throw new CashPortalError("PASSWORD_CHANGE_REQUIRED",403);}
function cleanUsername(value:unknown){const username=bodyString(value,80);return username&&/^[A-Za-z0-9._-]+$/.test(username)?username:undefined;}
function cleanId(value:unknown){return typeof value==="string"&&/^[a-f0-9]{64}$/.test(value)?value:undefined;}
async function handle(request:NextRequest,segments:string[]){
 const action=segments[0]||"";
 if(request.method==="POST"&&action==="login"){
  requireOrigin(request);if(loginRateLimited(request))return reply({error:"TOO_MANY_ATTEMPTS"},429,{"Retry-After":"900"});
  const body=await readBody(request),username=cleanUsername(body.username),password=typeof body.password==="string"?body.password:"";
  if(!username||!password)return reply({error:"CREDENTIALS_REQUIRED"},400);
  const row=await findUser(username);if(!row||!(await verifyPassword(password,row.password_hash))){noteLoginFailure(request);return reply({error:"INVALID_CREDENTIALS"},401);}
  clearLoginFailures(request);const session=await createSession(request,row);await audit(row.id,row.id,"LOGIN",{});
  return reply({user:session.user,csrf:session.csrf},200,{"Set-Cookie":cookieHeader(session.token)});
 }
 if(action==="me"&&request.method==="GET"){try{const result=await auth(request);return reply({user:result.user,csrf:await refreshCsrf(result.token)});}catch(e){return reply({error:e instanceof CashPortalError?e.code:"AUTHENTICATION_REQUIRED"},401);}}
 const result=await auth(request,request.method!=="GET");
 if(action==="logout"&&request.method==="POST"){await database().query("DELETE FROM public.cash_portal_sessions WHERE id=$1",[hashToken(result.token)]);await audit(result.user.id,result.user.id,"LOGOUT",{});return reply({ok:true},200,{"Set-Cookie":clearCookie()});}
 if(result.user.mustChangePassword&&!['password','summary','profile','logout'].includes(action))forced(result.user);
 if(action==="profile"&&request.method==="PATCH"){
  const body=await readBody(request),displayName=bodyOptional(body.displayName,150),email=bodyOptional(body.email,320),mobile=bodyOptional(body.mobile,50),whatsapp=bodyOptional(body.whatsappNumber,50);
  if(displayName===null||email===null||mobile===null||whatsapp===null)return reply({error:"PROFILE_FIELD_INVALID"},400);
  const row=await userById(result.user.id);if(!row)return reply({error:"USER_NOT_FOUND"},404);
  await database().query<Row>("UPDATE public.cash_portal_users SET display_name=$2,email=$3,mobile=$4,whatsapp_number=$5,version=version+1 WHERE id=$1 RETURNING *",[row.id,displayName===undefined?row.display_name:displayName,email===undefined?row.email:email,mobile===undefined?row.mobile:mobile,whatsapp===undefined?row.whatsapp_number:whatsapp]);
  await audit(row.id,row.id,"PROFILE_UPDATED",{});return reply({user:publicUser((await userById(row.id))!)});
 }
 if(action==="password"&&request.method==="POST"){
  const body=await readBody(request),current=typeof body.currentPassword==="string"?body.currentPassword:"",next=typeof body.newPassword==="string"?body.newPassword:"",confirm=typeof body.confirmPassword==="string"?body.confirmPassword:"";
  const row=await userById(result.user.id);if(!row||!(await verifyPassword(current,row.password_hash)))return reply({error:"CURRENT_PASSWORD_INVALID"},400);
  if(next.length<12||Buffer.byteLength(next)>256)return reply({error:"PASSWORD_POLICY"},400);
  if(next!==confirm)return reply({error:"PASSWORD_CONFIRMATION_MISMATCH"},400);
  const encoded=await hashPassword(next);await database().query("UPDATE public.cash_portal_users SET password_hash=$2,must_change_password=false,password_changed_at=now(),version=version+1 WHERE id=$1",[row.id,encoded]);await audit(row.id,row.id,"PASSWORD_CHANGED",{});
  const fresh=await userById(row.id);return reply({user:publicUser(fresh!)});
 }
 if(action==="users"&&request.method==="GET"){requireAdmin(result.user);const rows=await database().query<Row>("SELECT id,username,role,display_name AS \"displayName\",email,mobile,whatsapp_number AS \"whatsappNumber\",must_change_password AS \"mustChangePassword\",active,last_seen_at AS \"lastSeenAt\",created_at AS \"createdAt\" FROM public.cash_portal_users ORDER BY lower(username)");return reply({users:rows.rows});}
 if(action==="users"&&request.method==="POST"){requireAdmin(result.user);const body=await readBody(request),username=cleanUsername(body.username),password=typeof body.password==="string"?body.password:"",displayName=bodyString(body.displayName,150);if(!username||!displayName||password.length<12||Buffer.byteLength(password)>256)return reply({error:"USER_FIELDS_INVALID"},400);const requestedRole=body.role==="ADMIN"?"ADMIN":"USER";policy(()=>assertCanCreateUser(result.user,requestedRole,isCashSuperAdmin(result.user)));const id=hashToken(`cash-user:${username.toLowerCase()}`);const encoded=await hashPassword(password);try{await database().query("INSERT INTO public.cash_portal_users(id,username,password_hash,role,display_name,email,mobile,whatsapp_number,must_change_password,created_by) VALUES($1,$2,$3,$4,$5,$6,$7,$8,true,$9)",[id,username,encoded,requestedRole,displayName,bodyOptional(body.email,320),bodyOptional(body.mobile,50),bodyOptional(body.whatsappNumber,50),result.user.id]);}catch(e){if((e as {code?:string}).code==="23505")return reply({error:"USERNAME_EXISTS"},409);throw e;}await audit(result.user.id,id,"USER_CREATED",{role:requestedRole});return reply({ok:true,id},201);}
 if(action==="users"&&segments[1]&&segments[2]==="password"&&request.method==="POST"){requireAdmin(result.user);const id=cleanId(segments[1]);const body=await readBody(request),next=typeof body.newPassword==="string"?body.newPassword:"";if(!id||next.length<12||Buffer.byteLength(next)>256)return reply({error:"PASSWORD_POLICY"},400);const target=await userById(id);if(!target)return reply({error:"USER_NOT_FOUND"},404);policy(()=>assertCanResetPassword(result.user,{id:target.id,role:target.role,active:target.active},isCashSuperAdmin(result.user)));await database().query("UPDATE public.cash_portal_users SET password_hash=$2,must_change_password=true,password_changed_at=NULL,version=version+1 WHERE id=$1",[id,await hashPassword(next)]);await database().query("DELETE FROM public.cash_portal_sessions WHERE user_id=$1",[id]);await audit(result.user.id,id,"PASSWORD_RESET",{targetRole:target.role});return reply({ok:true});}
 if(action==="users"&&segments[1]&&request.method==="PATCH"){requireAdmin(result.user);const id=cleanId(segments[1]);if(!id)return reply({error:"USER_ID_INVALID"},400);const target=await userById(id);if(!target)return reply({error:"USER_NOT_FOUND"},404);const body=await readBody(request);const displayName=bodyOptional(body.displayName,150),email=bodyOptional(body.email,320),mobile=bodyOptional(body.mobile,50),whatsapp=bodyOptional(body.whatsappNumber,50);if(displayName===null||email===null||mobile===null||whatsapp===null)return reply({error:"PROFILE_FIELD_INVALID"},400);const nextRole=body.role==="ADMIN"||body.role==="USER"?body.role:target.role;const nextActive=typeof body.active==="boolean"?body.active:target.active;const activeAdmins=await activeAdminCount();policy(()=>assertCanManageUser({actor:result.user,target:{id:target.id,role:target.role,active:target.active},nextRole,nextActive,activeAdmins,superAdmin:isCashSuperAdmin(result.user)}));await database().query("UPDATE public.cash_portal_users SET display_name=$2,email=$3,mobile=$4,whatsapp_number=$5,active=$6,role=$7,version=version+1 WHERE id=$1",[id,displayName??target.display_name,email===undefined?target.email:email,mobile===undefined?target.mobile:mobile,whatsapp===undefined?target.whatsapp_number:whatsapp,nextActive,nextRole]);await audit(result.user.id,id,"USER_UPDATED",{roleBefore:target.role,roleAfter:nextRole,activeBefore:target.active,activeAfter:nextActive});return reply({ok:true});}
 if(action==="summary"&&request.method==="GET"){
  requireCashSuperAdmin(result.user);
  const q=request.nextUrl.searchParams,term=bodyString(q.get("q"),150),method=bodyString(q.get("method"),20),from=bodyString(q.get("from"),10),to=bodyString(q.get("to"),10);
  // Current and Archive are disjoint epochs. Default remains Current so no
  // pre-transition record can appear in a Current total, filter or export.
  const scope: 'CURRENT'|'ARCHIVE' = q.get("scope")==="archive"?'ARCHIVE':'CURRENT';
  const clauses=cashScopedWhere('i',scope);const args:string[]=[];
  if(term){args.push(`%${term.toLowerCase()}%`);clauses.push(`lower(concat_ws(' ',i.employee_name,i.employee_mobile,i.payout_mobile,i.purpose,i.id)) LIKE $${args.length}`);}
  if(method){args.push(method);clauses.push(`i.method=$${args.length}`);}
  if(from){args.push(from);clauses.push(`(i.source_time AT TIME ZONE 'Asia/Dhaka')::date >= $${args.length}::date`);}
  if(to){args.push(to);clauses.push(`(i.source_time AT TIME ZONE 'Asia/Dhaka')::date <= $${args.length}::date`);}
  const where=clauses.join(' AND ');
  const counts=await database().query<Row>(`SELECT (SELECT count(*) FROM public.cash_instructions i WHERE ${where})::int AS instructions,(SELECT count(*) FROM public.cash_instructions i WHERE ${where} AND i.state='REVIEW')::int AS review,(SELECT count(*) FROM public.cash_postings p JOIN public.cash_instructions i ON i.id=p.instruction_id AND i.scope_account=p.scope_account WHERE ${where})::int AS postings,(SELECT coalesce(sum(i.amount_minor),0) FROM public.cash_instructions i WHERE ${where} AND i.amount_minor>0)::bigint AS instruction_minor,(SELECT coalesce(sum(p.amount_minor),0) FROM public.cash_postings p JOIN public.cash_instructions i ON i.id=p.instruction_id AND i.scope_account=p.scope_account WHERE ${where} AND p.amount_minor>0)::bigint AS posted_minor,(SELECT coalesce(sum(p.amount_minor),0) FROM public.cash_postings p JOIN public.cash_instructions i ON i.id=p.instruction_id AND i.scope_account=p.scope_account WHERE ${where} AND p.amount_minor>0)::bigint AS total_minor,(SELECT count(DISTINCT i.employee_mobile) FROM public.cash_instructions i WHERE ${where} AND i.employee_mobile IS NOT NULL AND btrim(i.employee_mobile)<>'')::int AS employees,(SELECT count(DISTINCT i.payout_mobile) FROM public.cash_instructions i WHERE ${where} AND i.payout_mobile IS NOT NULL AND btrim(i.payout_mobile)<>'')::int AS payouts,(SELECT count(*) FROM public.cash_instructions i WHERE ${where} AND btrim(i.employee_name)<>'' AND i.employee_mobile IS NOT NULL AND btrim(i.employee_mobile)<>'' AND i.payout_mobile IS NOT NULL AND btrim(i.payout_mobile)<>'' AND i.amount_minor>0 AND btrim(i.method)<>'' AND btrim(i.purpose)<>'')::int AS complete,(SELECT count(*) FROM public.cash_instructions i WHERE ${where} AND jsonb_array_length(i.reasons)>0)::int AS notes`,args);
  // Bounded paging so Archive can page independently without loading the table.
  const limit=Math.max(1,Math.min(200,Number(q.get("limit"))||100)),offset=Math.max(0,Math.min(1000000,Number(q.get("offset"))||0));
  const rows=await database().query<Row>(`SELECT i.id,i.scope_account,i.source_ref,i.command_id,i.source_time,i.employee_name,i.employee_mobile,i.payout_mobile,i.method,i.amount_minor,i.purpose,i.state,i.reasons,p.id AS posting_id,p.created_at AS posted_at,s.chat_jid,s.message_id,s.original_sender_ref,s.submitted_by_ref,s.origin_state,s.visibility_state FROM public.cash_instructions i LEFT JOIN public.cash_postings p ON p.scope_account=i.scope_account AND p.instruction_id=i.id LEFT JOIN public.source_refs s ON s.scope_account=i.scope_account AND s.id=i.source_ref WHERE ${where} ORDER BY i.source_time DESC,i.id DESC LIMIT ${limit} OFFSET ${offset}`,args);
  return reply({scope,counts:counts.rows[0],rows:rows.rows,total:counts.rows[0]?.instructions??0,limit,offset,filters:{q:term??'',method:method??'',from:from??'',to:to??''}});
 }
 if(action==="messages"&&request.method==="GET"){
  requireCashSuperAdmin(result.user);
  const rows=await database().query<Row>(
   `SELECT o.id,o.wa_account,o.chat_jid,o.chat_type,o.message_id,o.direction,
           o.sender_jid,o.sender_phone,o.sender_push_name,o.receiver_jid,o.group_name,
           o."timestamp" AS source_time,o.message_type,o.text_content,
           p.status AS processing_status,p.processed_content,p.processing_errors
    FROM public.whatsapp_messages_original o
    LEFT JOIN public.whatsapp_messages_processing p
      ON p.original_id=o.id AND p.domain='cash'
    WHERE o.wa_account=$1 AND o.chat_jid=ANY($2::text[])
    ORDER BY o."timestamp" DESC,o.id DESC
    LIMIT 100`,
   [CASH_SCOPE_ACCOUNT,CASH_SCOPE_CHATS],
  );
  return reply({rows:rows.rows,source:"WhatsApp original archive",readOnly:true,financialAction:"NONE"});
 }
 throw new CashPortalError("NOT_FOUND",404);
}
export async function GET(request:NextRequest,{params}:{params:Promise<{path:string[]}>}){try{return await handle(request,(await params).path||[]);}catch(e){return reply({error:e instanceof CashPortalError?e.code:"CASH_PORTAL_ERROR"},e instanceof CashPortalError?e.status:500);}}
export async function POST(request:NextRequest,{params}:{params:Promise<{path:string[]}>}){try{return await handle(request,(await params).path||[]);}catch(e){return reply({error:e instanceof CashPortalError?e.code:"CASH_PORTAL_ERROR"},e instanceof CashPortalError?e.status:500);}}
export async function PATCH(request:NextRequest,{params}:{params:Promise<{path:string[]}>}){try{return await handle(request,(await params).path||[]);}catch(e){return reply({error:e instanceof CashPortalError?e.code:"CASH_PORTAL_ERROR"},e instanceof CashPortalError?e.status:500);}}
