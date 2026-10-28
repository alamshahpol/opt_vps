# Responsive workspace redesign — 2026-10-28 (source + isolated verification)

Scope: public homepage, dashboard, cash, vessel register, employees, transactions,
reports, admin panel, account settings. No deployment, migration, credential or
authorization-mode change.

## Design system

`app/workspace.css` + `app/platform/ui.tsx` now provide the shared vocabulary:

| Primitive | Purpose |
|---|---|
| `PageHeader` | eyebrow, title, description, actions, status meta — identical on every page |
| `SectionCard` | titled surface with optional actions and footer |
| `TableShell` | scroll container; at ≤768px the table becomes stacked record cards using `data-label` |
| `KpiCard`/`KpiGrid` | tone-coded metric tiles with tabular figures and honest "Unavailable" state |
| `StatusPill` | semantic status (ok / warn / danger / brand / neutral) |
| `EmptyState`, `ErrorState`, `LoadingSkeleton` | consistent loading, empty and failure surfaces |
| `PageNotice` | source/provenance banner |

Tokens: marine ink `#0d2333`, brand `#0f4c63`, accent `#b8902f`, 12px radius,
40px minimum control height, visible focus rings, `prefers-reduced-motion` honoured
on the public site.

## Page changes

| Page | Change |
|---|---|
| Public `/` | Corporate homepage (header, hero, three services, about, contact, footer), Login/Sign Up top-right, mobile drawer. Unchanged from the approved design; still no invented contact details. |
| `/signup` | Access-request explainer, responsive, states that no account is created. |
| Dashboard | Operational overview: header, financial KPIs, recent-instruction table (stacked on mobile), workforce/review KPIs, explicit **Instruction vs Verified vs Posted** definitions. |
| Employees | Page header, filters (search, identity scope), **filtered total vs all-record total**, responsive master table, profile sheet with instruction total and review notes, links to transactions/evidence. |
| Transactions | Header, filter bar with **filtered total**, responsive ledger, source-evidence detail sheet, explicit "not a posting" wording. |
| Admin Panel | Page header; responsive account table (stacked on mobile); profile, change username, change password, create account, roles and capability grants unchanged and still server-enforced. |
| Cash portal | Mobile: sidebar becomes a horizontal scrollable navigation strip; metrics stack 2-up then 1-up; lower grid single column; palette aligned. Cash Freeze and approval rules untouched. |
| Vessel Register | Existing responsive shell retained (bottom navigation ≤650px, metric and filter collapse); palette consistent with the workspace. |
| Insights / Income & Expenditure / Archive / Sources & Review | KPI, notice and table primitives now render the shared components; layout untouched otherwise. |

## Browser verification (headless Chromium over CDP)

8 pages × 5 widths (360, 390, 768, 1280, 1440) = **40/40 with zero horizontal
overflow**, measured as `scrollWidth − clientWidth ≤ 1`.

* Mobile drawer: opens, traps scroll, exposes Dashboard / Vessel Register /
  Transactions / Employees links (verified at 390px).
* Admin Panel rendered in an isolated `on`-mode instance: `h1` = "Admin panel",
  one account row (the Owner), labels present for profile, username change,
  password change and account creation, 0 overflow at 390/768/1440.
* Screenshots: `/tmp/opencode/redesign/shots/` (`home`, `signup`, `dashboard`,
  `employees`, `transactions`, `admin`, `vessel-register`, `cash` at 390 and 1440,
  plus `employees-before.png` from before the redesign).

## Functional verification

| Check | Result |
|---|---|
| Unit/integration suite (173) | 172 pass / 0 fail / 1 pre-existing skip |
| `tsc --noEmit` | pass |
| ESLint (`app lib release tests scripts proxy.ts db components`) | 0 errors, 0 warnings |
| `next build --webpack` | pass |
| Docker image build (typecheck + lint + build inside) | pass |
| Currency formatting | employee/dashboard/transaction totals use `fmtBDT` (regression test guards it) |
| Permission boundaries | proxy/entry/session rules unchanged; admin still redirects non–Super Admins |

## Remaining defects / decisions

1. **Admin Panel is unreachable while the mode is `shadow`.** `/admin` requires the
   legacy Basic credential, which is never the Super Admin, so it renders
   `307 → /dashboard`. The panel was verified in an isolated `on` instance. Until
   `on` is approved, credential changes are available through the Cash portal's
   own profile and password cards. Options: (a) accept and use the Cash portal,
   (b) approve a narrow session-authorised `/account` route, (c) enable `on`.
2. **Public contact details** are still intentionally absent (no invented phone,
   address or licence). Owner input required.
3. **Sign-up backend** remains informational; a persistent request queue needs a
   migration.
4. **Cash authenticated screens** were verified through CSS/layout only; the
   authenticated cash dashboard was not driven in this browser harness (session
   cookie requires a secure origin). Cash flows were functionally verified earlier.
5. Insights, Income & Expenditure, Archive and Sources & Review received the shared
   primitives but not a bespoke layout pass.
