'use client';
import {useEffect,useState,type ReactNode} from 'react';
import Link from 'next/link';
import {AlertTriangle,Banknote,CircleAlert,Inbox,Info,Users} from 'lucide-react';
import {Badge} from '@/components/ui/badge';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/components/ui/select';
import {Textarea} from '@/components/ui/textarea';
import {
  Sheet,SheetContent,SheetDescription,SheetFooter,SheetHeader,SheetTitle,SheetTrigger,
} from '@/components/ui/sheet';
import {Tooltip,TooltipContent,TooltipProvider,TooltipTrigger} from '@/components/ui/tooltip';

export const bdt=new Intl.NumberFormat('en-BD',{style:'currency',currency:'BDT',maximumFractionDigits:2});
export const fmtBDT=(amountCents:number)=>bdt.format(amountCents/100);
export const fmtInt=new Intl.NumberFormat('en-BD');

export function money(cents:number){return fmtBDT(cents);}

/** JSON fetch with loading/error/unavailable handling. Never mutates. */
export function useApi<T>(url:string|null){
  const [state,setState]=useState<{data:T|null;error:string|null;loading:boolean}>({data:null,error:null,loading:!!url});
  useEffect(()=>{
    if(!url)return;
    const controller=new AbortController();
    void (async()=>{
      // State updates run after an await boundary so the effect body stays
      // free of synchronous setState (react-compiler rule).
      await Promise.resolve();
      setState({data:null,error:null,loading:true});
      try{
        const r=await fetch(url,{headers:{Accept:'application/json'},signal:controller.signal});
        const v=await r.json().catch(()=>null);
        if(!r.ok)throw new Error((v&&v.error)||r.statusText||'Request failed');
        setState({data:v as T,error:null,loading:false});
      }catch(e:unknown){
        if(!controller.signal.aborted)setState({data:null,error:e instanceof Error?e.message:'Load failed',loading:false});
      }
    })();
    return()=>controller.abort();
  },[url]);
  return state;
}

export function LoadingLines(){return <LoadingSkeleton rows={3}/>;}

export function Unavailable({reason,title='Not available from verified data',compact=false}:{reason:string;title?:string;compact?:boolean}){
  return (
    <div className={compact?'flex items-start gap-2 text-xs text-muted-foreground':'flex flex-col gap-1 rounded-md border border-dashed p-3 text-sm'}>
      {compact?<Info className="mt-0.5 size-3.5 shrink-0" aria-hidden/>:<span className="flex items-center gap-2 font-medium text-foreground"><Info className="size-4" aria-hidden/>{title}</span>}
      {!compact&&<p className="text-muted-foreground">{reason}</p>}
      {compact&&<p>{reason}</p>}
    </div>
  );
}

export function KpiCard({
  label,labelBn,value,valueText,hint,tone,href,
  state='ok',
}:{label:string;labelBn?:string;value?:number;valueText?:string;hint?:string;tone?:'default'|'cash'|'workforce'|'risk'|'ok';href?:string;state?:'ok'|'unavailable'}){
  const display=valueText??(value===undefined?null:fmtInt.format(value));
  const body=(
    <div className="wx-kpi" data-tone={tone??'default'} data-state={state}>
      <span className="wx-kpi-label">
        {tone==='cash'&&<Banknote className="size-3.5" aria-hidden/>}
        {tone==='workforce'&&<Users className="size-3.5" aria-hidden/>}
        {tone==='risk'&&<CircleAlert className="size-3.5" aria-hidden/>}
        <span className="truncate">{label}</span>
        {labelBn&&<span className="text-[10px] opacity-70">{labelBn}</span>}
      </span>
      <strong className="wx-kpi-value">
        {state==='unavailable'||display===null?'Unavailable':display}
      </strong>
      {hint&&<span className="wx-kpi-hint">{hint}</span>}
    </div>
  );
  return href?(
    <Link href={href} className="block no-underline transition-transform hover:-translate-y-px">{body}</Link>
  ):body;
}

export function KpiGrid({children}:{children:ReactNode}){return <div className="wx-kpis">{children}</div>;}

/* ---------------- Page scaffold ---------------- */

export function PageHeader({title,description,actions,eyebrow,meta}:{
  title:string;description?:string;actions?:ReactNode;eyebrow?:string;meta?:ReactNode;
}){
  return (
    <header className="wx-header">
      <div className="wx-header-main">
        {eyebrow&&<span className="wx-eyebrow">{eyebrow}</span>}
        <h1 className="wx-title">{title}</h1>
        {description&&<p className="wx-subtitle">{description}</p>}
        {meta&&<div className="wx-meta">{meta}</div>}
      </div>
      {actions&&<div className="wx-header-actions">{actions}</div>}
    </header>
  );
}

export function SectionCard({title,description,actions,children,footer,flush=false}:{
  title?:string;description?:string;actions?:ReactNode;children:ReactNode;footer?:ReactNode;flush?:boolean;
}){
  return (
    <section className="wx-card">
      {(title||actions)&&(
        <div className="wx-card-head">
          <div className="min-w-0">
            {title&&<h2>{title}</h2>}
            {description&&<p>{description}</p>}
          </div>
          {actions&&<div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={flush?'wx-card-body flush':'wx-card-body'}>{children}</div>
      {footer&&<div className="wx-card-foot">{footer}</div>}
    </section>
  );
}

/** Wraps a native table in the responsive scroll/stack container. */
export function TableShell({children,label,stackable=true}:{children:ReactNode;label?:string;stackable?:boolean}){
  return (
    <div className={'wx-table-wrap'+(stackable?' stackable':'')} role="region" aria-label={label??'Data table'} tabIndex={0}>
      {children}
    </div>
  );
}

export function EmptyState({title,description,icon}:{title:string;description?:string;icon?:ReactNode}){
  return (
    <div className="wx-state">
      {icon??<Inbox className="size-7" aria-hidden/>}
      <strong>{title}</strong>
      {description&&<p>{description}</p>}
    </div>
  );
}

export function ErrorState({message,onRetry}:{message:string;onRetry?:()=>void}){
  return (
    <div className="wx-error" role="alert">
      <CircleAlert className="size-4 shrink-0" aria-hidden/>
      <span className="min-w-0 flex-1">{message}</span>
      {onRetry&&<Button size="sm" variant="outline" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function LoadingSkeleton({rows=3}:{rows?:number}){
  return <div className="wx-skeleton" role="status" aria-label="Loading">{[...Array(rows)].map((_,i)=><span key={i}/>)}</div>;
}

const PILL_TONES:[RegExp,'ok'|'warn'|'danger'|'brand'|'neutral'][]=[
  [/CONFIRMED|POSTED|APPROVED|VERIFIED|ACTIVE|OK|PAID/i,'ok'],
  [/REVIEW|PENDING|DRAFT|INCOMPLETE|PARTIAL|UNVERIFIED/i,'warn'],
  [/REJECT|FAIL|ERROR|INVALID|UNMATCHED|DISABLED|BLOCKED/i,'danger'],
  [/ADMIN|SUPER|OWNER|SESSION|UNIFIED/i,'brand'],
];

/** Semantic status pill; falls back to neutral for unknown states. */
export function StatusPill({status,label}:{status:string;label?:string}){
  const text=label??status??'UNKNOWN';
  const tone=PILL_TONES.find(([re])=>re.test(status??''))?.[1]??'neutral';
  return <span className="wx-pill" data-tone={tone}>{text}</span>;
}

export function StatusBadge({status}:{status:string}){
  const s=status||'UNKNOWN';
  const variant=/REVIEW|PENDING|DRAFT/i.test(s)?'secondary':/CONFIRMED|POSTED|APPROVED|VERIFIED/i.test(s)?'default':/REJECT|FAIL|INCOMPLETE|UNMATCHED/i.test(s)?'destructive':'outline';
  return <Badge variant={variant as 'secondary'|'default'|'destructive'|'outline'}>{s}</Badge>;
}

export function PageNotice({notice,sourceLabel,checkedAt}:{notice?:string;sourceLabel?:string;checkedAt?:string}){
  if(!notice&&!sourceLabel)return null;
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-xs">
      <AlertTriangle className="size-3.5 shrink-0" aria-hidden/>
      <span className="font-medium">{sourceLabel??'Source note'}:</span>
      <span className="min-w-0 flex-1 text-muted-foreground">{notice}</span>
      {checkedAt&&<span className="shrink-0 text-muted-foreground">checked {checkedAt.slice(0,16).replace('T',' ')}</span>}
    </div>
  );
}

/* ---------------- Drawers (UI shells; all writes disabled) ---------------- */

function DisabledSubmitReason({kind}:{kind:'transaction'|'employee'}){
  return kind==='transaction'
    ?'Saving is disabled: creating a manual cash instruction requires an authorized backend writer and validation. Requests would be recorded as PENDING_REVIEW only — no ledger posting.'
    :'Saving is disabled: activating an employee master record requires an authorized approval workflow (PENDING_APPROVAL) and backend writer. NID and contact data are restricted records.';
}

export function AddTransactionDrawer(){
  const [open,setOpen]=useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild><Button size="sm">+ Add transaction</Button></SheetTrigger>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Add transaction (draft UI)</SheetTitle>
          <SheetDescription>Submitted manual transactions enter PENDING_REVIEW and never post to the Cash Ledger automatically.</SheetDescription>
        </SheetHeader>
        <div className="grid gap-3 px-4 pb-4">
          {(['Employee','Employee ID','Vessel','Amount (BDT)'] as const).map(f=>(
            <div key={f} className="grid gap-1"><Label htmlFor={`tx-${f}`}>{f}</Label><Input id={`tx-${f}`} name={f} placeholder="Not connectable yet — backend writer pending"/></div>
          ))}
          <div className="grid gap-1">
            <Label htmlFor="tx-method">Payment method</Label>
            <Select defaultValue="bkash"><SelectTrigger id="tx-method"><SelectValue/></SelectTrigger>
              <SelectContent>{['bkash','nagad','cash','rocket','bank'].map(m=><SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="grid gap-1">
            <Label htmlFor="tx-source">Instruction source</Label>
            <Select defaultValue="manual"><SelectTrigger id="tx-source"><SelectValue/></SelectTrigger>
              <SelectContent><SelectItem value="manual">Manual entry</SelectItem><SelectItem value="whatsapp" disabled>WhatsApp (existing intake)</SelectItem></SelectContent>
            </Select>
          </div>
          <div className="grid gap-1"><Label htmlFor="tx-date">Transaction date</Label><Input id="tx-date" type="date"/></div>
          <div className="grid gap-1"><Label htmlFor="tx-evidence">Attach evidence</Label><Input id="tx-evidence" type="file" disabled aria-disabled/><p className="text-[11px] text-muted-foreground">Evidence storage backend pending.</p></div>
          <div className="grid gap-1"><Label htmlFor="tx-notes">Notes</Label><Textarea id="tx-notes" rows={3} placeholder="Purpose, references, review context"/></div>
          <SheetFooter className="flex-row justify-end gap-2">
            <Button variant="outline" onClick={()=>setOpen(false)}>Cancel</Button>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild><Button variant="secondary" disabled aria-disabled="true">Save Draft</Button></TooltipTrigger>
                <TooltipContent><DisabledSubmitReason kind="transaction"/></TooltipContent>
              </Tooltip>
              <Tooltip><TooltipTrigger asChild><Button disabled aria-disabled="true">Submit for Review</Button></TooltipTrigger><TooltipContent><DisabledSubmitReason kind="transaction"/></TooltipContent></Tooltip>
            </TooltipProvider>
          </SheetFooter>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function AddEmployeeDrawer(){
  const [open,setOpen]=useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild><Button size="sm">+ Add employee</Button></SheetTrigger>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Add employee (draft UI)</SheetTitle>
          <SheetDescription>New employee submissions would enter PENDING_APPROVAL; only an authorized Admin can activate.</SheetDescription>
        </SheetHeader>
        <div className="grid gap-3 px-4 pb-4">
          {(['Employee Name','Employee ID','Phone','NID','Vessel / Assignment','Joining Date','Salary','Emergency Contact'] as const).map(f=>(
            <div key={f} className="grid gap-1"><Label htmlFor={`emp-${f}`}>{f}</Label><Input id={`emp-${f}`} name={f} placeholder="Backend writer pending"/></div>
          ))}
          <div className="grid gap-1"><Label htmlFor="emp-notes">Notes</Label><Textarea id="emp-notes" rows={3}/></div>
          <SheetFooter className="flex-row justify-end gap-2">
            <Button variant="outline" onClick={()=>setOpen(false)}>Cancel</Button>
            <TooltipProvider>
              <Tooltip><TooltipTrigger asChild><Button variant="secondary" disabled>Save Draft</Button></TooltipTrigger><TooltipContent><DisabledSubmitReason kind="employee"/></TooltipContent></Tooltip>
              <Tooltip><TooltipTrigger asChild><Button disabled>Submit for Approval</Button></TooltipTrigger><TooltipContent><DisabledSubmitReason kind="employee"/></TooltipContent></Tooltip>
            </TooltipProvider>
          </SheetFooter>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function ActionButtonDisabled({label,reason}: {label:string;reason:string}){
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0}>
            <Button size="sm" variant="outline" disabled aria-disabled="true">{label}</Button>
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-56 text-[11px]">{reason}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

