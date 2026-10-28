import type {Metadata} from 'next';
import Link from 'next/link';
import {ArrowLeft, ShieldCheck} from 'lucide-react';
import SiteNav from '../public-site/site-nav';
import '../public-site.css';

export const metadata: Metadata = {
  title: 'Request access · AL-RIFA’I Integrated Services',
  description: 'Account access for AL-RIFA’I clients is provisioned after verification. Signing up never grants access to operational data.',
  robots: {index: true, follow: true},
};

const STEPS = [
  {
    title: 'Speak with your AL-RIFA’I operations contact',
    body: 'Engagements and portal accounts are arranged directly with the operations desk, so the requesting company and its contact person are verified first.',
  },
  {
    title: 'Verification of the requesting party',
    body: 'We confirm the company, the named contact and the services in scope before an account is created. No account is created from this page.',
  },
  {
    title: 'Account issued by an administrator',
    body: 'An administrator provisions the account with a temporary password. You are asked to set your own password at first sign-in.',
  },
  {
    title: 'Scoped access only',
    body: 'Each account sees only the functions it has been granted. Financial posting and approval remain separate, restricted actions.',
  },
];

export default function SignUpPage() {
  return (
    <div className="site">
      <SiteNav />
      <main id="main" className="site-main">
        <div className="site-page">
          <Link href="/" style={{display: 'inline-flex', alignItems: 'center', gap: '.4rem', fontSize: '.85rem', color: 'var(--site-ink-soft)'}}>
            <ArrowLeft size={14} /> Back to home
          </Link>
          <section className="site-panel" style={{marginTop: '1.25rem'}}>
            <span className="site-eyebrow">Request access</span>
            <h1>Accounts are provisioned after verification</h1>
            <p className="site-lead">
              AL-RIFA’I does not run self-service registration. This page explains how an account is
              issued; it does not create one and it grants no access to operational data.
            </p>
            <ol className="site-steps">
              {STEPS.map((step) => (
                <li key={step.title}>
                  <div>
                    <strong>{step.title}</strong>
                    <span>{step.body}</span>
                  </div>
                </li>
              ))}
            </ol>
            <p className="site-callout">
              <ShieldCheck size={15} style={{verticalAlign: '-2px', marginRight: '.35rem'}} />
              Signing up never grants access to client, personnel or financial records. Access is
              issued by an authorised administrator and limited to the permissions assigned to that
              account.
            </p>
            <div className="site-hero-actions" style={{marginTop: '1.5rem'}}>
              <a className="site-btn site-btn-primary" href="/login">I already have an account</a>
              <Link className="site-btn site-btn-ghost" href="/">Back to home</Link>
            </div>
          </section>
        </div>
      </main>
      <footer className="site-footer">
        <div className="site-footer-bottom">
          <span>© {new Date().getFullYear()} AL-RIFA’I Integrated Services. All rights reserved.</span>
          <span><Link href="/login">Login</Link> · <Link href="/">Home</Link></span>
        </div>
      </footer>
    </div>
  );
}
