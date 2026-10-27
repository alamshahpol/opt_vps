export type NavItem={
  href:string;
  label:string;
  labelBn?:string;
  icon:string; // lucide-react icon name, resolved in app-shell
  description:string;
  restricted?:boolean;
};

export const NAV_ITEMS:NavItem[]=[
  {href:"/dashboard",label:"Dashboard",icon:"LayoutDashboard",description:"Unified financial, workforce and review overview"},
  {href:"/transactions",label:"Transactions",labelBn:"লেনদেন",icon:"ArrowLeftRight",description:"Cash instructions, payment records and evidence"},
  {href:"/employees",label:"Employees",labelBn:"কর্মচারী",icon:"Users",description:"Employee master records and payment statements"},
  {href:"/insights",label:"Operational Insights",labelBn:"পরিসংখ্যান",icon:"ChartLine",description:"Workforce, payment and vessel analytics"},
  {href:"/income-expenditure",label:"Income & Expenditure",labelBn:"আয়-ব্যয়",icon:"Wallet",description:"Financial analysis with verified data only"},
  {href:"/archive",label:"Archive",labelBn:"আর্কাইভ",icon:"Archive",description:"Historical messages, cashbook and program history"},
  {href:"/sources-review",label:"Sources & Review",labelBn:"উৎস ও পর্যালোচনা",icon:"ClipboardCheck",description:"Review queue, evidence and verification"},
  {href:"/assistant",label:"Assistant",icon:"Sparkles",description:"Ask anything about verified records"},
];

// Preserved, not deleted: consolidation targets for legacy navigation items.
export const CONSOLIDATED_LINKS:Record<string,string>={
  "Program Workflow":"/vessel",
  "Conversations / Hermes":"/conversations",
  "Accountant Messages":"/sources-review",
  "Message mirror":"/message-mirror",
  "Report assistant":"/assistant",
};

import {LayoutDashboard,ArrowLeftRight,Users,ChartLine,Wallet,Archive,ClipboardCheck,Sparkles,type LucideIcon} from 'lucide-react';

export const NAV_ICONS:Record<string,LucideIcon>={
  LayoutDashboard,
  ArrowLeftRight,
  Users,
  ChartLine,
  Wallet,
  Archive,
  ClipboardCheck,
  Sparkles,
};

export function navItemForPath(pathname:string):NavItem{
  const matches=NAV_ITEMS.filter((item)=>pathname===item.href||pathname.startsWith(item.href+"/"));
  return matches.sort((a,b)=>b.href.length-a.href.length)[0]??NAV_ITEMS[0];
}
