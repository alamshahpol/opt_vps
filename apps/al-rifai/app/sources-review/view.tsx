'use client';
import {useMemo,useState} from 'react';
import Link from 'next/link';
import {Button} from '@/components/ui/button';
import {Tabs,TabsContent,TabsList,TabsTrigger} from '@/components/ui/tabs';
import {Table,TableBody,TableCell,TableHead,TableHeader,TableRow} from '@/components/ui/table';
import {Badge} from '@/components/ui/badge';
import {Card,CardContent,CardHeader,CardTitle} from '@/components/ui/card';
import {Input} from '@/components/ui/input';
import {LoadingLines,PageNotice,Unavailable,KpiCard,KpiGrid,ActionButtonDisabled,StatusBadge} from '@/app/platform/ui';
import {useApi} from '@/app/platform/ui';
import {ESCORT_SUMMARY_URL} from '@/app/platform/ops-client';

export interface EscortSummaryResponse{
  scope:'current'|'archive';
  summary:{
    draft:number;confirmed:number;review:number;confirmedEvidence:number;actionableReview:number;
    recentReview:number;unverifiedLegacy:number;dateUnverified:number;unmatched:number;incomplete:number;duplicateReview:number;
  };
  latestSourceTime:string|null;
  checkedAt:string;
}

export interface ImportAuditResponse{
  summary:{[k:string]:unknown};
  rows:unknown[];
  total:number;
  notice:string;
}

export interface EscortRow{
  id:number|string;
  clientName:string;
  motherVessel:string;
  lighterVessel:string;
  escortName:string;
  escortMobile:string;
  masterMobile:string;
  dutyDate:string;
  sourceTime:string;
  status:string;
  reasons:string|string[];
}

const reasonList=(r:EscortRow)=>Array.isArray(r.reasons)?r.reasons:String(r.reasons??'').split(',').filter(Boolean);

export default function SourcesReviewView(){
  const escort=useApi<EscortSummaryResponse>(ESCORT_SUMMARY_URL);
  const [escortUrl,setEscortUrl] = useState('/api/escort-register');
  const escortRows=useApi<{rows:EscortRow[]}>(escortUrl);  const reviews=useApi<{rows:{id:string;date:string;time:string;body:string;sender:string;reason:string;status?:string}[];total:number;canWrite:boolean}>('/api/operations?view=reviews&scope=archive');
  const [q,setQ]=useState('');

  const reviewRows=(escortRows.data?.rows??[]).filter(r=>r.status==='REVIEW');
  const filtered=useMemo(()=>reviewRows.filter(r=>!q||[r.clientName,r.motherVessel,r.lighterVessel,r.escortName,r.id].join(' ').toLowerCase().includes(q.toLowerCase())),[reviewRows,q]);

  return <div className="flex flex-col gap-4">
    {escort.data&&<KpiGrid>
      <KpiCard label="Review Queue" tone="risk" value={escort.data.summary.actionableReview} hint="Actionable vessel review rows"/>
      <KpiCard label="Duplicate Alerts" tone="risk" value={escort.data.summary.duplicateReview} hint="Potential duplicate candidates"/>
      <KpiCard label="Unmatched / Reconciliation" tone="risk" value={escort.data.summary.unmatched} hint="Confirmation-match candidates"/>
      <KpiCard label="Awaiting Evidence" tone="risk" value={escort.data.summary.incomplete} hint="Incomplete assignment evidence"/>
      <KpiCard label="Identity Review (legacy)" tone="risk" hint="Identity-review candidates are on the preserved /review screen." state="unavailable"/>
      <KpiCard label="Import Reviews" tone="risk" hint="Import evidence is shown in the Archive tab of its preserved screen (/import evidence APIs are connected below)." state="unavailable"/>
    </KpiGrid>}

    {escort.error&&<Unavailable title="Review summary unavailable" reason={escort.error}/>}

    <Tabs defaultValue="vessel">
      <TabsList>
        <TabsTrigger value="vessel">Vessel review ({reviewRows.length})</TabsTrigger>
        <TabsTrigger value="identity">Identity review</TabsTrigger>
        <TabsTrigger value="import">Import review (archive)</TabsTrigger>
        <TabsTrigger value="employee">Employee requests</TabsTrigger>
      </TabsList>

      <TabsContent value="vessel" className="mt-2 flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Input type="search" value={q} onChange={e=>setQ(e.target.value)} placeholder="Filter by client, vessel, escort, ID…" className="max-w-xs" aria-label="Filter review rows"/>
          <Button size="sm" variant="outline" onClick={()=>setEscortUrl('/api/escort-register?scope=archive')}>Load Archive scope</Button>
          <Button size="sm" variant="outline" onClick={()=>setEscortUrl('/api/escort-register')}>Load Current scope</Button>
          <Link href="/vessel" className="text-xs underline-offset-2 hover:underline">Open preserved Vessel Register ↗</Link>
          <span className="ml-auto flex gap-1">
            <ActionButtonDisabled label="Approve" reason="Administrative approval is a separate Owner-authorized operation; not enabled in this UI."/>
            <ActionButtonDisabled label="Reject" reason="Rejections mutate review state; backend not authorized."/>
            <ActionButtonDisabled label="Request Correction" reason="Correction workflow backend pending."/>
          </span>
        </div>
        {escortRows.loading&&<LoadingLines/>}
        {escortRows.error&&<Unavailable title="Could not load review rows" reason={escortRows.error}/>}
        {escortRows.data&&<div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader><TableRow><TableHead>Ref.</TableHead><TableHead>Client</TableHead><TableHead>Vessels (M / L)</TableHead><TableHead>Escort</TableHead><TableHead>Duty date</TableHead><TableHead>Source time</TableHead><TableHead>Status</TableHead><TableHead>Reasons</TableHead><TableHead>Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {filtered.slice(0,100).map(r=><TableRow key={r.id}>
                <TableCell className="whitespace-nowrap tabular-nums">{r.id}</TableCell>
                <TableCell>{r.clientName}</TableCell>
                <TableCell className="whitespace-nowrap">{r.motherVessel} / {r.lighterVessel}</TableCell>
                <TableCell>{r.escortName}</TableCell>
                <TableCell className="whitespace-nowrap">{r.dutyDate||'—'}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{(r.sourceTime||'').slice(0,16).replace('T',' ')}</TableCell>
                <TableCell><StatusBadge status={r.status}/></TableCell>
                <TableCell className="max-w-64 text-[11px] text-muted-foreground">{reasonList(r).slice(0,2).join(' · ')||'—'}</TableCell>
                <TableCell><span className="flex gap-1"><ActionButtonDisabled label="View evidence" reason="Per-row evidence viewer integration pending; store read-only."/></span></TableCell>
              </TableRow>)}
              {!filtered.length&&<TableRow><TableCell colSpan={9} className="py-6 text-center text-sm text-muted-foreground">{escortRows.loading?'':`No REVIEW rows displayed (${reviewRows.length} total in scope).`}</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>}
        <p className="text-[11px] text-muted-foreground">Message bodies and source text are not rendered here; verification happens in the preserved register screens which retain full provenance.</p>
      </TabsContent>

      <TabsContent value="identity" className="mt-2">
        <Card>
          <CardHeader><CardTitle className="text-sm">Identity review workspace preserved</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3 text-sm">
            <p className="text-muted-foreground">The existing identity-review candidate UI continues to own this workflow.</p>
            <Button asChild size="sm" variant="outline"><a href="/review">Open /review</a></Button>
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="import" className="mt-2 flex flex-col gap-2">
        {reviews.loading&&<LoadingLines/>}
        {reviews.error&&<Unavailable title="Archive reviews unavailable" reason={reviews.error}/>}
        {reviews.data&&<>
          <PageNotice sourceLabel="Old application Accounts reviews" notice="Old-application Accounts messages are Archive History only; they are never merged into Current."/>
          <Badge variant="outline">{reviews.data.total} archived review items (first 100 shown)</Badge>
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Sender</TableHead><TableHead>Reason</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
              <TableBody>{(reviews.data.rows??[]).slice(0,100).map(r=><TableRow key={r.id}>
                <TableCell className="whitespace-nowrap">{r.date} {r.time}</TableCell>
                <TableCell>{r.sender}</TableCell>
                <TableCell className="max-w-72 truncate text-xs text-muted-foreground">{r.reason}</TableCell>
                <TableCell><StatusBadge status={r.status??'pending'}/></TableCell>
              </TableRow>)}</TableBody>
            </Table>
          </div>
        </>}
      </TabsContent>

      <TabsContent value="employee" className="mt-2">
        <Card>
          <CardHeader><CardTitle className="text-sm">Employee approval requests</CardTitle></CardHeader>
          <CardContent>
            <Unavailable reason="No PENDING_APPROVAL employee queue exists yet — the employee creation backend (and its tables/grants) is a separate authorized implementation. See the Backend Gap report."/>
            <div className="mt-3"><Button asChild size="sm" variant="outline"><Link href="/employees">Open Employees</Link></Button></div>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  </div>;
}
