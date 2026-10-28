import type {Metadata} from 'next';
import {ArrowRight, CheckCircle2, ClipboardCheck, LifeBuoy, ShieldCheck, Ship} from 'lucide-react';
import SiteNav from './public-site/site-nav';
import './public-site.css';

export const metadata: Metadata = {
  title: 'AL-RIFA’I · Marine Survey, Security and Vessel Escort Services',
  description:
    'AL-RIFA’I provides marine survey and inspection, security guard services and vessel escort operations, supported by source-linked operational records.',
  robots: {index: true, follow: true},
};

const SERVICES = [
  {
    icon: <Ship size={22} />,
    title: 'Marine Survey & Inspection',
    body: 'Condition and readiness inspections for vessels and marine operations, recorded against the specific vessel and survey context.',
    points: ['Pre- and post-voyage inspection', 'Vessel condition reporting', 'Findings retained with source evidence'],
  },
  {
    icon: <ShieldCheck size={22} />,
    title: 'Security Guard Services',
    body: 'Deployed guarding for sites and cargo operations, with attendance and instruction records kept against the assigned personnel.',
    points: ['Site and cargo guarding', 'Shift attendance records', 'Escalation to the operations desk'],
  },
  {
    icon: <LifeBuoy size={22} />,
    title: 'Vessel Escort Services',
    body: 'Escort teams assigned to lighter and vessel movements, with each assignment linked to the originating client instruction.',
    points: ['Lighter and vessel movements', 'Named escort assignments', 'Assignment and duration records'],
  },
];

export default function PublicHome() {
  return (
    <div className="site">
      <SiteNav />

      <main id="main" className="site-main">
        <section className="site-hero">
          <div className="site-hero-inner">
            <div>
              <span className="site-badge"><ClipboardCheck size={14} /> Operations supported by source-linked records</span>
              <h1>Marine survey, security and vessel escort operations.</h1>
              <p>
                AL-RIFA’I coordinates inspection, guarding and escort work for vessel and cargo
                operations, with every client instruction traced back to the message or document
                it came from.
              </p>
              <div className="site-hero-actions">
                <a className="site-btn site-btn-primary" href="#services">Our services <ArrowRight size={16} /></a>
                <a className="site-btn site-btn-ghost" href="/login">Client login</a>
              </div>
            </div>
            <aside className="site-hero-card" aria-label="How engagements are run">
              <h2>How an engagement runs</h2>
              <ul className="site-hero-list">
                <li><CheckCircle2 size={16} /> The client instruction is captured once, with its original source retained.</li>
                <li><CheckCircle2 size={16} /> Personnel and vessel details are confirmed before work is assigned.</li>
                <li><CheckCircle2 size={16} /> Assignment, duration and outcome are recorded against that instruction.</li>
                <li><CheckCircle2 size={16} /> Accounts remain review-only until a payment is separately approved.</li>
              </ul>
            </aside>
          </div>
        </section>

        <section className="site-section" id="services" aria-labelledby="services-title">
          <span className="site-eyebrow">Services</span>
          <h2 className="site-h2" id="services-title">Three operating divisions, one records standard</h2>
          <p className="site-lead">
            Each division runs on the same discipline: the request, the people assigned and the
            evidence are kept together, so a figure can always be traced to its origin.
          </p>
          <div className="site-grid">
            {SERVICES.map((service) => (
              <article className="site-card" key={service.title}>
                <span className="site-card-icon" aria-hidden="true">{service.icon}</span>
                <h3>{service.title}</h3>
                <p>{service.body}</p>
                <ul>{service.points.map((point) => <li key={point}>{point}</li>)}</ul>
              </article>
            ))}
          </div>
        </section>

        <section className="site-section site-section-alt" id="about" aria-labelledby="about-title">
          <div className="site-split">
            <div>
              <span className="site-eyebrow">About the company</span>
              <h2 className="site-h2" id="about-title">Operational support built on verifiable records</h2>
              <p className="site-lead">
                AL-RIFA’I works with vessel and cargo operations that need inspection, guarding and
                escort work carried out to a documented standard. Our internal systems are built
                around the original instruction: what was asked, by whom, for which vessel, and
                which people were assigned.
              </p>
              <p className="site-lead" style={{marginTop: '1rem'}}>
                Records are separated by dataset scope, so current operations are never mixed with
                archived history. Access to operational data is limited to verified account holders;
                public pages such as this one carry no client, personnel or financial information.
              </p>
            </div>
            <div className="site-facts">
              <div className="site-fact">
                <strong>Source-linked instructions</strong>
                <span>Client requests are tied to the original message or document rather than a transcription.</span>
              </div>
              <div className="site-fact">
                <strong>Named accountability</strong>
                <span>Escorts and guards are identified by their employee reference, separate from any payout number.</span>
              </div>
              <div className="site-fact">
                <strong>Review before payment</strong>
                <span>Instruction amounts are not treated as payments; posting requires separate approval.</span>
              </div>
              <div className="site-fact">
                <strong>Private by default</strong>
                <span>Operational pages require an authorised account; signing up does not grant access.</span>
              </div>
            </div>
          </div>
        </section>

        <section className="site-section" id="contact" aria-labelledby="contact-title">
          <div className="site-contact">
            <div>
              <span className="site-eyebrow">Contact</span>
              <h2 id="contact-title">Start with your AL-RIFA’I operations contact</h2>
              <p>
                New engagements and account access are arranged directly with the operations desk so
                that the requesting party is verified before any work is assigned. Existing clients
                can sign in to review their own instructions and assignments.
              </p>
              <p className="site-contact-note">
                We do not publish direct phone numbers or street addresses on this page; they are
                provided through your existing AL-RIFA’I contact.
              </p>
            </div>
            <div className="site-contact-actions">
              <a className="site-btn site-btn-accent" href="/login">Client login</a>
              <a className="site-btn site-btn-ghost" href="/signup">Request access</a>
            </div>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="site-footer-inner">
          <div>
            <div className="site-brand" style={{marginBottom: '.75rem'}}>
              <span className="site-mark" aria-hidden="true"><Ship size={18} /></span>
              <span className="site-brand-text"><strong>AL-RIFA’I</strong><span>Integrated Services</span></span>
            </div>
            <p style={{fontSize: '.86rem', color: 'var(--site-ink-soft)', lineHeight: 1.6, maxWidth: '34ch'}}>
              Marine survey and inspection, security guarding and vessel escort operations.
            </p>
          </div>
          <div>
            <h4>Services</h4>
            <ul>
              <li><a href="#services">Marine Survey &amp; Inspection</a></li>
              <li><a href="#services">Security Guard Services</a></li>
              <li><a href="#services">Vessel Escort Services</a></li>
            </ul>
          </div>
          <div>
            <h4>Access</h4>
            <ul>
              <li><a href="/login">Login</a></li>
              <li><a href="/signup">Sign Up</a></li>
              <li><a href="/cash">Accounts portal</a></li>
            </ul>
          </div>
        </div>
        <div className="site-footer-bottom">
          <span>© {new Date().getFullYear()} AL-RIFA’I Integrated Services. All rights reserved.</span>
          <span>Operational data is restricted to authorised accounts.</span>
        </div>
      </footer>
    </div>
  );
}
