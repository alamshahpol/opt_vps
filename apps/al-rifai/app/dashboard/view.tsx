'use client';
import {useMemo} from 'react';
import {KpiCard,KpiGrid,PageNotice,Unavailable,LoadingLines,bdt,useApi} from '@/app/platform/ui';
import {opUrl,instructionBuckets,type OperationsSnapshot,ESCORT_SUMMARY_URL} from '@/app/platform/ops-client';
import type {EscortSummaryResponse} from '@/app/sources-review/view';

export default function DashboardView(){
  const ops=useApi<OperationsSnapshot>(opUrl('cash'));
  const escort=useApi<EscortSummaryResponse>(ESCORT_SUMMARY_URL);

  const rows=useMemo(()=>ops.data?.rows??[],[ops.data]);
  const buckets=useMemo(()=>instructionBuckets(rows),[rows]);
  const pending=useMemo(()=>rows.filter(r=>r.issues?.length),[rows]);
  const pendingCents=buckets.pendingCents;

  const financial=(<>{
    [
      <KpiCard key="ti" label="Total Instructions" labelBn="মোট নির্দেশনা" tone="cash" value={ops.data?.summary.total} hint="Verified Cash instruction rows (Current scope)" href="/transactions"/>,
      <KpiCard key="amt" label="Instruction Total" labelBn="মোট" tone="cash" valueText={ops.data?bdt.format(ops.data.summary.amountCents):undefined} hint="Admin instruction amounts — not verified receipts" href="/transactions"/>,
      <KpiCard key="pend" label="Pending Amount" labelBn="অপেক্ষমাণ" tone="risk" valueText={ops.data?bdt.format(pendingCents):undefined} hint={`${pending.length} rows with review issues`} href="/sources-review"/>,

      // Posted ledger amounts are maintained behind the Cash portal and its
      // super-admin scope; the platform reports an honest unavailable state.
      <KpiCard key="posted" label="Posted Amount" labelBn="পোস্ট করা" tone="cash" hint="Cash Ledger postings live behind the Cash portal (super-admin scope). Connect via Cash portal to view." state="unavailable"/>,
      <KpiCard key="today" label={"Today's Paid"} labelBn="আজ" tone="cash" valueText={buckets.hasToday?bdt.format(buckets.today):undefined} state={buckets.hasToday?'ok':'unavailable'} hint={buckets.hasToday?'Instruction amounts dated today (Dhaka): not confirmed receipts':'No instruction rows dated today'}/>,
      <KpiCard key="week" label="Last Week" labelBn="গত সপ্তাহ" tone="cash" valueText={bdt.format(buckets.week)} hint="Trailing 7 days, instruction amounts only" href="/insights"/>,
      <KpiCard key="month" label="This Month Total" labelBn="এই মাস" tone="cash" valueText={bdt.format(buckets.month)} hint="Current Dhaka month instruction amounts" href="/income-expenditure"/>,    ]
  }</>);

  const workforce=(
    <>
      <KpiCard label="Active Employees" labelBn="কর্মচারী" tone="workforce" value={ops.data?.summary.employees} hint="Distinct employee identities in paid instructions" href="/employees"/>
      <KpiCard label="New Employees This Month" labelBn="নতুন" tone="workforce" hint="Joining dates are not present in verified payment data yet. Employee joining history requires the HR backend." state="unavailable"/>
      <KpiCard key="today" label={"Today's Instructions"} labelBn="আজ" tone="cash" value={buckets.todayCount} href="/transactions"/>
      <KpiCard label="Approved Transactions" labelBn="অনুমোদিত" tone="workforce" hint="Approval state is held in the Cash portal; this read-only snapshot records identity-verified instruction rows." state="unavailable"/>
      <KpiCard label="Pending Instructions" labelBn="অপেক্ষমাণ" tone="risk" value={pending.length} hint="Rows with verification issues in review" href="/sources-review"/>
      <KpiCard label="Rejected Transactions" labelBn="বাতিল" tone="risk" hint="Rejection records are not exposed by any verified read-only API yet." state="unavailable"/>
    </>
  );

  const s=escort.data?.summary;
  const risk=(s?(
    <>
      <KpiCard key="dup" label="Duplicate Alerts" labelBn="ডুপ্লিকেট" tone="risk" value={s.duplicateReview} hint="Vessel duplicate candidates in review" href="/sources-review"/>
      <KpiCard label="Unmatched Payments" labelBn="অমিল" tone="risk" value={s.unmatched} hint="Reconciliation candidates awaiting decision" href="/sources-review"/>
      <KpiCard label="Review Queue" labelBn="পর্যালোচনা" tone="risk" value={s.actionableReview} hint="Actionable vessel review rows" href="/sources-review"/>
      <KpiCard label="Awaiting Evidence" labelBn="প্রমাণ" tone="risk" value={s.incomplete} hint="Rows with incomplete assignment evidence" href="/sources-review"/>
    </>
  ):(
    <>
      <KpiCard key="dup" label="Duplicate Alerts" labelBn="ডুপ্লিকেট" tone="risk" hint="Escort register summary unavailable." state="unavailable"/>
      <KpiCard label="Unmatched Payments" labelBn="অমিল" tone="risk" hint="Payment reconciliation lives in the Cash portal." state="unavailable"/>
      <KpiCard label="Review Queue" labelBn="পর্যালোচনা" tone="risk" hint="Loading…" state="unavailable"/>
      <KpiCard label="Awaiting Evidence" labelBn="প্রমাণ" tone="risk" hint="Loading…" state="unavailable"/>
    </>
  ));

  return <div className="flex flex-col gap-4">
    {ops.error&&<Unavailable title="Could not load Cash snapshot" reason={ops.error}/>}
    {!ops.error&&ops.loading&&<LoadingLines/>}
    {ops.data&&<>
      <PageNotice notice={ops.data.notice} sourceLabel={ops.data.sourceLabel} checkedAt={ops.data.checkedAt}/>
      {rows.length===0&&<Unavailable compact reason="No instruction rows are present in the verified snapshot — figures show what exists only."/>}
      <section aria-label="Financial overview">
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">Financial overview</h2>
        <KpiGrid>{financial}</KpiGrid>
      </section>
      <section aria-label="Workforce overview">
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">Workforce</h2>
        <KpiGrid>{workforce}</KpiGrid>
      </section>
      <section aria-label="Risk and review">
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">Risk &amp; review</h2>
        <KpiGrid>{risk}</KpiGrid>
      </section>
      {escort.error&&<Unavailable compact reason={`Vessel summary unavailable: ${escort.error}`}/>}
    </>}
  </div>;
}
