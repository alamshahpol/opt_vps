'use client';
import {useMemo,useState} from 'react';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/components/ui/select';
import {Sheet,SheetContent,SheetDescription,SheetFooter,SheetHeader,SheetTitle} from '@/components/ui/sheet';
import {Table,TableBody,TableCell,TableHead,TableHeader,TableRow} from '@/components/ui/table';
import {Badge} from '@/components/ui/badge';
import {AddTransactionDrawer,ActionButtonDisabled,LoadingLines,PageNotice,StatusBadge,Unavailable,bdt,useApi,fmtInt} from '@/app/platform/ui';
import {opUrl,type OperationsSnapshot} from '@/app/platform/ops-client';
import {csv,saveCsv} from '@/lib/register';
import {money} from '@/lib/operations';
import type {CashRow} from '@/lib/operations';

const METHODS=['','bkash','nagad','cash','rocket','bank','unknown'];
const SOURCES=[
  {value:'all',label:'All sources'},
  {value:'chat',label:'Identity-verified WhatsApp'},
  {value:'review',label:'Legacy extraction (identity unverified)'},
  {value:'excel',label:'Excel Cashbook (archive)'},
];

export default function TransactionsView(){
  const ops=useApi<OperationsSnapshot>(opUrl('cash'));
  const rows=useMemo(()=>ops.data?.rows??[],[ops.data?.rows]);
  const [f,setF]=useState({q:'',employee:'',from:'',to:'',status:'all',method:'all',source:'all',vessel:''});

  const employees=useMemo(()=>[...new Set(rows.map(r=>r.employeePhone||r.name).filter(Boolean))].sort(),[rows]);
  const statusOptions=useMemo(()=>[...new Set(rows.map(r=>r.status).filter(Boolean))],[rows]);

  const filtered=useMemo(()=>{
    const term=f.q.toLowerCase();
    return rows.filter(r=>
      (!f.employee||(r.employeePhone||r.name)===f.employee)&&
      (!f.from||r.date>=f.from)&&(!f.to||r.date<=f.to)&&
      (!f.method||f.method==='all'||r.method===f.method)&&
      (f.source==='all'||(f.source==='chat'&&r.identityVerified===true&&r.source!=='Excel Cashbook')||(f.source==='review'&&r.identityVerified!==true&&r.source==='WhatsApp archive')||(f.source==='excel'&&r.source==='Excel Cashbook'))&&
      (f.status==='all'||r.status===f.status)&&
      (!term||[r.id,r.name,r.employeePhone,r.payoutPhone,r.purpose,r.sourceId].join(' ').toLowerCase().includes(term)));
  },[rows,f]);

  const [detail,setDetail]=useState<CashRow|null>(null);

  const exportCsv=()=>{
    const contents=csv(['ID','Date','Time','Employee','Employee ID','Payout','Method','Amount','Source','Status','Purpose','Issues'],
      filtered.map(r=>[r.id,r.date,r.time,r.name,r.employeePhone,r.payoutPhone,r.method,(r.amountCents/100).toFixed(2),r.source,r.status??'',r.purpose,r.issues?.join('; ')??'']));
    saveCsv(contents,'al-rifai-transactions.csv');
  };

  return <div className="flex flex-col gap-3">
    {ops.data&&<PageNotice notice={ops.data.notice} sourceLabel={ops.data.sourceLabel} checkedAt={ops.data.checkedAt}/>}
    {ops.error&&<Unavailable title="Transactions unavailable" reason={ops.error}/>}

    <div className="flex flex-wrap items-center gap-2">
      <h2 className="text-sm font-semibold">Transactions <span className="font-normal text-muted-foreground">({fmtInt.format(filtered.length)} of {fmtInt.format(rows.length)} rows)</span></h2>
      <div className="ml-auto flex flex-wrap gap-2">
        <AddTransactionDrawer/>
        <Button size="sm" variant="outline" onClick={exportCsv} disabled={!rows.length}>Export</Button>
        <ActionButtonDisabled label="Reconcile" reason="Reconciliation is an Owner-authorized Cash-portal workflow."/>
      </div>
    </div>

    <div className="grid gap-2 rounded-md border p-2 sm:grid-cols-3 lg:grid-cols-4">
      <div className="grid gap-1"><Label htmlFor="t-q">Search</Label><Input id="t-q" type="search" value={f.q} onChange={e=>setF(p=>({...p,q:e.target.value}))} placeholder="ID, name, phone, purpose…"/></div>
      <div className="grid gap-1"><Label htmlFor="t-emp">Employee</Label>
        <Select value={f.employee||'all'} onValueChange={v=>setF(p=>({...p,employee:v==='all'?'':v}))}><SelectTrigger id="t-emp"><SelectValue/></SelectTrigger>
          <SelectContent><SelectItem value="all">All employees</SelectItem>{employees.slice(0,300).map(e=><SelectItem key={e} value={e}>{e}</SelectItem>)}</SelectContent></Select></div>
      <div className="grid gap-1"><Label htmlFor="t-from">From</Label><Input id="t-from" type="date" value={f.from} onChange={e=>setF(p=>({...p,from:e.target.value}))}/></div>
      <div className="grid gap-1"><Label htmlFor="t-to">To</Label><Input id="t-to" type="date" value={f.to} onChange={e=>setF(p=>({...p,to:e.target.value}))}/></div>
      <div className="grid gap-1"><Label htmlFor="t-status">Status</Label>
        <Select value={f.status} onValueChange={v=>setF(p=>({...p,status:v}))}><SelectTrigger id="t-status"><SelectValue/></SelectTrigger>
          <SelectContent><SelectItem value="all">All statuses</SelectItem>{statusOptions.map(s=><SelectItem key={s} value={s}>{s||'(none)'}</SelectItem>)}</SelectContent></Select></div>
      <div className="grid gap-1"><Label htmlFor="t-method">Payment method</Label>
        <Select value={f.method} onValueChange={v=>setF(p=>({...p,method:v}))}><SelectTrigger id="t-method"><SelectValue/></SelectTrigger>
          <SelectContent>{METHODS.map(m=><SelectItem key={m} value={m||'all'}>{m||'All'}</SelectItem>)}</SelectContent></Select></div>
      <div className="grid gap-1"><Label htmlFor="t-source">Instruction source</Label>
        <Select value={f.source} onValueChange={v=>setF(p=>({...p,source:v}))}><SelectTrigger id="t-source"><SelectValue/></SelectTrigger>
          <SelectContent>{SOURCES.map(s=><SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}</SelectContent></Select></div>
      <div className="grid items-end gap-1">
        <Unavailable compact reason="Vessel filter: Cash instruction rows carry no vessel reference — vessel-scoped filtering lives in the Vessel Register."/>
      </div>
    </div>

    {ops.loading&&<LoadingLines/>}
    {ops.data&&<div className="overflow-x-auto rounded-md border">
      <Table>
        <TableHeader><TableRow>
          <TableHead>Date</TableHead><TableHead>Employee</TableHead><TableHead>Employee ID</TableHead><TableHead>Method</TableHead>
          <TableHead className="text-right">Amount</TableHead><TableHead>Source</TableHead><TableHead>Status</TableHead><TableHead>Actions</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {filtered.slice(0,200).map(r=><TableRow key={r.id} className="cursor-pointer hover:bg-muted/40" onClick={()=>setDetail(r)}>
            <TableCell className="whitespace-nowrap">{r.date}</TableCell>
            <TableCell className="max-w-40 truncate">{r.name||'(name pending)'}</TableCell>
            <TableCell className="whitespace-nowrap tabular-nums">{r.employeePhone||'—'}</TableCell>
            <TableCell className="capitalize">{r.method}</TableCell>
            <TableCell className="whitespace-nowrap text-right tabular-nums">{money(r.amountCents)}</TableCell>
            <TableCell className="text-xs">{r.source}{r.identityVerified===true&&<Badge variant="outline" className="ml-1">verified</Badge>}</TableCell>
            <TableCell>{r.issues?.length?<StatusBadge status={'REVIEW'}/>:<StatusBadge status={r.identityVerified===true?'CONFIRMED':'UNVERIFIED'}/>}</TableCell>
            <TableCell onClick={e=>e.stopPropagation()}>
              <span className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={()=>setDetail(r)}>View</Button>
                <ActionButtonDisabled label="Edit" reason="Instruction editing requires an authorized writer; integrity of original evidence must be preserved."/>
                <ActionButtonDisabled label="Approve" reason="Approval is an Owner-authorized Cash-portal action performed by the Admin role only."/>
              </span>
            </TableCell>
          </TableRow>)}
          {!filtered.length&&!ops.loading&&<TableRow><TableCell colSpan={8} className="py-8 text-center text-sm text-muted-foreground">No rows match the filters.</TableCell></TableRow>}
        </TableBody>
      </Table>
      <p className="p-2 text-[11px] text-muted-foreground">Showing first {Math.min(200,filtered.length)} rows · use Export for the full filtered set.</p>
    </div>}

    <Sheet open={!!detail} onOpenChange={(o)=>!o&&setDetail(null)}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Transaction {detail?.id}</SheetTitle>
          <SheetDescription>Read-only record detail. Amounts are Admin instruction amounts — not verified receipts.</SheetDescription>
        </SheetHeader>
        {detail&&<div className="grid gap-2 px-4 text-sm">
          {[['Date',detail.date],['Time',detail.time],['Employee',detail.name||'—'],['Employee ID',detail.employeePhone||'—'],
            ['Payout number',detail.payoutPhone],['Method',detail.method],['Amount',bdt.format(detail.amountCents)],
            ['Source',detail.source],['Instruction source ID',detail.sourceId?`${detail.sourceId}`:'—'],
            ['Category',detail.category],['Status',detail.status||'—'],['Identity verified',detail.identityVerified===true?'Yes':'No'],
            ['Identity rule',detail.identityRule||'—'],['Sender',detail.sender],['Purpose',detail.purpose||'—'],
          ].map(([k,v])=><div key={k} className="flex justify-between gap-4 border-b pb-1"><span className="text-muted-foreground">{k}</span><span className="text-right font-medium">{String(v)}</span></div>)}
          {detail.issues?.length>0&&<div><p className="mb-1 font-medium">Review issues</p><ul className="list-disc pl-5 text-xs text-muted-foreground">{detail.issues.map((i,_i)=><li key={_i}>{i}</li>)}</ul></div>}
          <details><summary className="cursor-pointer text-muted-foreground">Original message excerpt (evidence)</summary><p className="mt-1 rounded border bg-muted/40 p-2 text-xs whitespace-pre-wrap">{detail.sourceText}</p></details>
          <SheetFooter className="flex-row justify-end gap-2">
            <Button variant="outline" onClick={()=>setDetail(null)}>Close</Button>
            <ActionButtonDisabled label="Attach evidence" reason="Evidence attachments require backend storage authorization."/>
            <ActionButtonDisabled label="Audit trail" reason="No per-row audit API is exposed yet; the Cash portal keeps its own audit table."/>
          </SheetFooter>
        </div>}
      </SheetContent>
    </Sheet>
  </div>;
}
