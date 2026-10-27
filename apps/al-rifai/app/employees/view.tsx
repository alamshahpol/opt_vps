'use client';
import {useMemo,useState} from 'react';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/components/ui/select';
import {Sheet,SheetContent,SheetDescription,SheetFooter,SheetHeader,SheetTitle} from '@/components/ui/sheet';
import {Table,TableBody,TableCell,TableHead,TableHeader,TableRow} from '@/components/ui/table';
import {AddEmployeeDrawer,ActionButtonDisabled,LoadingLines,PageNotice,Unavailable,bdt,useApi,fmtInt} from '@/app/platform/ui';
import {opUrl,type OperationsSnapshot} from '@/app/platform/ops-client';
import {csv,saveCsv} from '@/lib/register';

export interface StatementRow{
  identity:string;employeePhone:string|null;name:string;aliases:number;
  payments:number;amountCents:number;lastDate:string;needsReview:number;
}

export default function EmployeesView(){
  const ops=useApi<OperationsSnapshot>(opUrl('employees'));
  const rows=useMemo(()=>((ops.data?.rows??[]) as unknown as StatementRow[]),[ops.data?.rows]);
  const [q,setQ]=useState('');
  const [scopeVerified,setScopeVerified]=useState<'paid'|'unverified'>('paid');
  const filtered=useMemo(()=>rows.filter(r=>{
    if(scopeVerified==='paid'&&!r.employeePhone)return false;
    if(scopeVerified==='unverified'&&r.employeePhone)return false;
    return !q||[r.identity,r.name,String(r.employeePhone??'')].join(' ').toLowerCase().includes(q.toLowerCase());
  }),[rows,q,scopeVerified]);
  const [detail,setDetail]=useState<StatementRow|null>(null);

  const exportCsv=()=>{
    saveCsv(csv(['Identity','Name','Employee phone','Payment count','Total (BDT)','Last date','Needs review'],
      filtered.map(r=>[r.identity,r.name,r.employeePhone??'',r.payments,(r.amountCents/100).toFixed(2),r.lastDate,r.needsReview])),'al-rifai-employee-statements.csv');
  };

  return <div className="flex flex-col gap-3">
    {ops.data&&<PageNotice notice={ops.data.notice} sourceLabel={ops.data.sourceLabel} checkedAt={ops.data.checkedAt}/>}
    {ops.error&&<Unavailable title="Employee data unavailable" reason={ops.error}/>}
    <Unavailable compact reason="Restricted personal data (NID, emergency contacts) is never transmitted from the verified read APIs; the drawer below creates request tickets only once an authorized writer exists."/>

    <div className="flex flex-wrap items-center gap-2">
      <h2 className="text-sm font-semibold">Employee master <span className="font-normal text-muted-foreground">({fmtInt.format(filtered.length)} of {fmtInt.format(rows.length)})</span></h2>
      <p className="text-xs text-muted-foreground">Employee ID reference = verified Escort Mobile identity · payout numbers are separate</p>
      <div className="ml-auto flex gap-2">
        <AddEmployeeDrawer/>
        <Button size="sm" variant="outline" onClick={exportCsv} disabled={!rows.length}>Export</Button>
      </div>
    </div>

    <div className="grid gap-2 rounded-md border p-2 sm:grid-cols-4">
      <div className="grid gap-1"><Label htmlFor="e-q">Search</Label><Input id="e-q" type="search" value={q} onChange={e=>setQ(e.target.value)} placeholder="Name, ID, phone…"/></div>
      <div className="grid gap-1"><Label htmlFor="e-scope">Scope</Label>
        <Select value={scopeVerified} onValueChange={v=>setScopeVerified(v as 'paid'|'unverified')}><SelectTrigger id="e-scope"><SelectValue/></SelectTrigger>
          <SelectContent><SelectItem value="paid">Identity-verified (paid instructions)</SelectItem><SelectItem value="unverified">Name-only (identity pending)</SelectItem></SelectContent></Select></div>
      <div className="grid gap-1"><Label>Current assignment</Label><Unavailable compact reason="Duty/vessel assignment data lives in the Vessel Register; a joined employee–assignment API is pending." /></div>
      <div className="grid gap-1"><Label>Restricted</Label><Unavailable compact reason="NID, emergency contact and salary are not exposed by any verified API."/></div>
    </div>

    {ops.loading&&<LoadingLines/>}
    {ops.data&&<div className="overflow-x-auto rounded-md border">
      <Table>
        <TableHeader><TableRow>
          <TableHead>Employee ID</TableHead><TableHead>Name</TableHead><TableHead>Mobile</TableHead><TableHead className="text-right">Payments</TableHead>
          <TableHead className="text-right">Total (BDT)</TableHead><TableHead>Last date</TableHead><TableHead>Status</TableHead><TableHead>Actions</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {filtered.slice(0,200).map(r=><TableRow key={r.identity} className="cursor-pointer hover:bg-muted/40" onClick={()=>setDetail(r)}>
            <TableCell className="whitespace-nowrap tabular-nums">{r.employeePhone??'record-only'}</TableCell>
            <TableCell className="max-w-44 truncate">{r.name}</TableCell>
            <TableCell className="whitespace-nowrap tabular-nums">{r.employeePhone??'—'}</TableCell>
            <TableCell className="text-right tabular-nums">{fmtInt.format(r.payments)}</TableCell>
            <TableCell className="text-right tabular-nums">{bdt.format(r.amountCents)}</TableCell>
            <TableCell className="whitespace-nowrap">{r.lastDate||'—'}</TableCell>
            <TableCell>{r.needsReview?<span className="text-xs text-amber-600">issues in review</span>:<span className="text-xs text-muted-foreground">clear on newest rows</span>}</TableCell>
            <TableCell onClick={e=>e.stopPropagation()}><span className="flex gap-1"><Button size="sm" variant="ghost" onClick={()=>setDetail(r)}>Profile</Button></span></TableCell>
          </TableRow>)}
        </TableBody>
      </Table>
    </div>}

    <Sheet open={!!detail} onOpenChange={o=>!o&&setDetail(null)}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{detail?.name||'Employee'}</SheetTitle>
          <SheetDescription>Derived from verified payment instructions only. Full HR master data is not published by any read API yet.</SheetDescription>
        </SheetHeader>
        {detail&&<div className="grid gap-2 px-4 text-sm">
          {[['Employee ID (Authoritative Ref)',detail.employeePhone??'record-only'],['Alias names',detail.name],['Recorded aliases',String(detail.aliases)],['Payment instructions',String(detail.payments)],['Instruction total',bdt.format(detail.amountCents)],['Most recent instruction',detail.lastDate||'—'],['Rows needing review',String(detail.needsReview)]].map(([k,v])=>
            <div key={k} className="flex justify-between gap-4 border-b pb-1"><span className="text-muted-foreground">{k}</span><span className="text-right font-medium">{String(v)}</span></div>)}
          <SheetFooter className="flex-row justify-end gap-2">
            <Button variant="outline" onClick={()=>setDetail(null)}>Close</Button>
            <ActionButtonDisabled label="Employment history" reason="Requires employee–duty join API (backend gap)."/>
            <ActionButtonDisabled label="Edit profile" reason="Employee master writes are restricted (ir_review_runtime grant; pending approval)."/>
          </SheetFooter>
        </div>}
      </SheetContent>
    </Sheet>
  </div>;
}
