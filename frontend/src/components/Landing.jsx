import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useReveal, useScrolled } from '../hooks/useReveal';
import { ArrowRightIcon, CloseIcon, Logo, MenuIcon } from './Icons';

const NAV = [
  { href: '#features', label: 'Features' },
  { href: '#how', label: 'How it works' },
  { href: '#product', label: 'The workspace' },
];

function Wordmark({ light = false }) {
  return (
    <Link to="/" className={`flex items-center gap-2.5 ${light ? 'text-white' : 'text-ink'}`} aria-label="AI Problem Solver home">
      <Logo className="h-7 w-7" />
      <span className="text-[15px] font-bold uppercase tracking-[0.12em]">Problem Solver</span>
    </Link>
  );
}

function Header() {
  const scrolled = useScrolled(40);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  const solid = scrolled || open;
  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background-color,border-color,backdrop-filter] duration-300 ${
        solid ? 'border-b border-white/10 bg-ink/90 backdrop-blur-md' : 'border-b border-transparent bg-transparent'
      }`}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8 lg:h-[72px]">
        <Wordmark light />
        <nav className="hidden items-center gap-9 md:flex" aria-label="Primary">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className="text-sm font-medium text-white/70 transition-colors hover:text-white">
              {n.label}
            </a>
          ))}
        </nav>
        <div className="hidden items-center gap-3 md:flex">
          <Link to="/login" className="btn btn-pill px-5 text-white hover:bg-white/10">
            Log in
          </Link>
          <Link to="/signup" className="btn-light btn-pill px-5">
            Sign up
          </Link>
        </div>
        <button
          type="button"
          className="inline-flex h-10 w-10 items-center justify-center rounded-full text-white hover:bg-white/10 md:hidden"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls="mobile-menu"
          aria-label={open ? 'Close menu' : 'Open menu'}
        >
          {open ? <CloseIcon className="h-5 w-5" /> : <MenuIcon className="h-5 w-5" />}
        </button>
      </div>
      {open && (
        <div id="mobile-menu" className="h-[calc(100dvh-4rem)] overflow-y-auto bg-ink px-5 pb-10 pt-6 md:hidden">
          <nav className="flex flex-col" aria-label="Mobile">
            {NAV.map((n) => (
              <a
                key={n.href}
                href={n.href}
                onClick={() => setOpen(false)}
                className="border-b border-white/10 py-5 text-3xl font-bold tracking-tight text-white"
              >
                {n.label}
              </a>
            ))}
          </nav>
          <div className="mt-8 flex flex-col gap-3">
            <Link to="/signup" className="btn-light btn-lg btn-pill">
              Sign up
            </Link>
            <Link to="/login" className="btn-outline-light btn-lg btn-pill">
              Log in
            </Link>
          </div>
        </div>
      )}
    </header>
  );
}

function Hero() {
  return (
    <section className="relative isolate flex min-h-[100svh] flex-col justify-end overflow-hidden bg-ink text-white">
      {/* Architectural grid and a single accent block: structure, not decoration. */}
      <div
        className="hero-fade absolute inset-x-0 top-0 -z-10 h-[55%] opacity-[0.06]"
        style={{
          '--d': '200ms',
          backgroundImage:
            'linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)',
          backgroundSize: '96px 96px',
          WebkitMaskImage: 'linear-gradient(to bottom, #000, transparent)',
          maskImage: 'linear-gradient(to bottom, #000, transparent)',
        }}
      />
      <div
        className="hero-fade absolute -right-24 top-0 -z-10 hidden h-full w-[38vw] bg-accent-500 lg:block"
        style={{ '--d': '400ms', clipPath: 'polygon(32% 0, 100% 0, 100% 100%, 0% 100%)' }}
      />

      <div className="mx-auto w-full max-w-7xl px-5 pb-14 pt-32 sm:px-8 sm:pb-20 lg:pb-24">
        <p className="hero-in mb-6 text-xs font-semibold uppercase tracking-[0.25em] text-white/60 sm:text-sm" style={{ '--d': '150ms' }}>
          Conversational problem solving
        </p>
        <h1
          className="hero-in max-w-5xl text-[clamp(3.5rem,10.5vw,9rem)] font-black uppercase leading-[0.88] tracking-display"
          style={{ '--d': '300ms' }}
        >
          Think it
          <br />
          through.
          <br />
          <span className="text-accent-500">Solve it.</span>
        </h1>
        <div className="rule-grow mt-10 h-px max-w-5xl bg-white/30" style={{ '--d': '800ms' }} />
        <div className="mt-8 flex flex-col gap-10 lg:flex-row lg:items-end lg:justify-between">
          <p className="hero-in max-w-xl text-lg leading-relaxed text-white/75 sm:text-xl" style={{ '--d': '900ms' }}>
            AI Problem Solver is a focused workspace for working through hard problems in conversation. Describe the
            situation, get structured answers as they are written, and pick up exactly where you left off.
          </p>
          <div className="hero-in flex flex-col gap-3 sm:flex-row" style={{ '--d': '1050ms' }}>
            <Link to="/signup" className="btn-light btn-lg btn-pill group">
              Get started
              <ArrowRightIcon className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
            </Link>
            <Link to="/login" className="btn-outline-light btn-lg btn-pill">
              Log in
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

const FEATURES = [
  {
    title: 'Live responses',
    text: 'Answers appear word by word as they are written, with clear status updates while your request is prepared and answered.',
  },
  {
    title: 'Full control',
    text: 'Stop a response the moment you have what you need, or regenerate it for another take on the same question.',
  },
  {
    title: 'Readable by design',
    text: 'Lists, tables, links and code blocks are formatted properly, and every code block and message has a one-click copy action.',
  },
  {
    title: 'A history that stays put',
    text: 'Every conversation is saved to your account. Rename it, reopen it on any device, and continue where you stopped.',
  },
  {
    title: 'Private to your account',
    text: 'Conversations are tied to your login and are never visible to other users. Passwords are hashed with Argon2id.',
  },
  {
    title: 'Resilient streaming',
    text: 'A response keeps generating if your connection drops. Reconnect and the rest of it is waiting for you.',
  },
];

function Features() {
  return (
    <section id="features" className="scroll-mt-16 bg-white px-5 py-24 sm:px-8 sm:py-32">
      <div className="mx-auto max-w-7xl">
        <div className="reveal grid gap-8 lg:grid-cols-12">
          <p className="text-xs font-semibold uppercase tracking-[0.25em] text-accent-600 lg:col-span-3">Features</p>
          <h2 className="text-[clamp(2.25rem,6vw,5rem)] font-black uppercase leading-[0.95] tracking-display text-ink lg:col-span-9">
            Built for the way
            <br className="hidden sm:block" /> problems actually unfold.
          </h2>
        </div>
        <div className="mt-16 grid border-t border-ink sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <article
              key={f.title}
              className="reveal group border-b border-zinc-200 py-9 transition-colors duration-300 hover:bg-zinc-50 sm:px-8 sm:[&:nth-child(2n)]:border-l sm:[&:nth-child(2n)]:border-zinc-200 lg:[&:nth-child(3n+1)]:border-l-0 lg:[&:nth-child(n)]:border-l lg:[&:nth-child(3n+1)]:border-zinc-200 lg:first:border-l-0"
              style={{ '--d': `${(i % 3) * 90}ms` }}
            >
              <span className="font-mono text-sm text-zinc-400">{String(i + 1).padStart(2, '0')}</span>
              <h3 className="mt-5 text-2xl font-bold tracking-tight text-ink">{f.title}</h3>
              <p className="mt-3 max-w-sm text-[15px] leading-7 text-zinc-600">{f.text}</p>
              <div className="mt-6 h-0.5 w-8 origin-left bg-accent-500 transition-all duration-500 ease-out group-hover:w-16" />
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

const STEPS = [
  { title: 'Create your account', text: 'Sign up with an email address and password. It takes less than a minute.' },
  { title: 'Describe the problem', text: 'Write it the way you would explain it to a colleague. Add detail in follow-ups as you go.' },
  { title: 'Work it through', text: 'Read the answer as it streams in, ask follow-ups, regenerate, or stop. Return to it any time.' },
];

function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-16 bg-ink px-5 py-24 text-white sm:px-8 sm:py-32">
      <div className="mx-auto max-w-7xl">
        <p className="reveal text-xs font-semibold uppercase tracking-[0.25em] text-accent-500">How it works</p>
        <h2 className="reveal mt-6 max-w-4xl text-[clamp(2.25rem,6vw,5rem)] font-black uppercase leading-[0.95] tracking-display">
          Three steps from question to answer.
        </h2>
        <ol className="mt-16 grid gap-px bg-white/15 lg:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="reveal bg-ink py-10 lg:px-10 lg:first:pl-0 lg:last:pr-0" style={{ '--d': `${i * 120}ms` }}>
              <span className="block text-[clamp(4rem,9vw,7rem)] font-black leading-none tracking-display text-white/15">
                {String(i + 1).padStart(2, '0')}
              </span>
              <h3 className="mt-6 text-2xl font-bold tracking-tight">{s.title}</h3>
              <p className="mt-3 max-w-sm text-[15px] leading-7 text-white/65">{s.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/** A static composition of the real interface, for illustration only. */
function ProductPreview() {
  return (
    <div className="reveal overflow-hidden rounded-2xl border border-zinc-300 bg-white shadow-[0_30px_80px_-30px_rgba(0,0,0,0.35)]" aria-hidden="true">
      <div className="flex items-center gap-2 border-b border-zinc-200 bg-zinc-50 px-4 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
        <span className="ml-3 text-xs text-zinc-500">Example conversation</span>
      </div>
      <div className="grid md:grid-cols-[220px_1fr]">
        <div className="hidden border-r border-zinc-200 bg-zinc-50 p-4 md:block">
          <div className="rounded-lg bg-ink px-3 py-2 text-xs font-semibold text-white">New chat</div>
          <p className="mb-2 mt-5 text-[10px] font-semibold uppercase tracking-widest text-zinc-400">Recent</p>
          {['Migration plan for the billing service', 'Why is the nightly build failing', 'Budget model assumptions'].map((t, i) => (
            <div key={t} className={`truncate rounded-md px-3 py-2 text-xs ${i === 0 ? 'bg-zinc-200/80 font-medium text-ink' : 'text-zinc-600'}`}>
              {t}
            </div>
          ))}
        </div>
        <div className="space-y-5 p-5 sm:p-8">
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-2xl rounded-br-md bg-zinc-100 px-4 py-2.5 text-sm text-ink">
              How should we split the billing service out of the monolith without downtime?
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-zinc-500">AI Problem Solver</div>
            <p className="text-sm leading-7 text-zinc-800">A staged migration keeps risk low. Work through it in this order:</p>
            <ol className="my-2 list-decimal space-y-1 pl-5 text-sm leading-7 text-zinc-800">
              <li>Define the billing boundary and its data ownership.</li>
              <li>Route reads through an internal API behind a feature flag.</li>
              <li>Dual-write, verify parity, then cut over writes.</li>
            </ol>
            <div className="my-3 overflow-hidden rounded-lg bg-zinc-900">
              <div className="flex justify-between bg-zinc-800 px-3 py-1.5 font-mono text-[11px] text-zinc-300">
                <span>yaml</span>
                <span>Copy code</span>
              </div>
              <pre className="overflow-hidden p-3 font-mono text-[12px] leading-5 text-zinc-100">{`flags:\n  billing_service_reads: 10%`}</pre>
            </div>
            <div className="flex items-center gap-2 text-xs text-zinc-500">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
              <span>Generating response...</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Product() {
  return (
    <section id="product" className="scroll-mt-16 overflow-hidden bg-zinc-100 px-5 py-24 sm:px-8 sm:py-32">
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-8 lg:grid-cols-12 lg:items-end">
          <h2 className="reveal text-[clamp(2.25rem,6vw,5rem)] font-black uppercase leading-[0.95] tracking-display text-ink lg:col-span-7">
            One calm workspace.
          </h2>
          <p className="reveal text-lg leading-8 text-zinc-600 lg:col-span-5" style={{ '--d': '100ms' }}>
            A conversation list on one side, the conversation on the other. Nothing else competes for your attention,
            on a phone or on a desktop.
          </p>
        </div>
        <div className="mt-14">
          <ProductPreview />
        </div>
      </div>
    </section>
  );
}

function CallToAction() {
  return (
    <section className="relative overflow-hidden bg-accent-500 px-5 py-24 text-ink sm:px-8 sm:py-36">
      <div className="mx-auto max-w-7xl">
        <h2 className="reveal max-w-5xl text-[clamp(2.75rem,9vw,8rem)] font-black uppercase leading-[0.9] tracking-display">
          Bring the next problem here.
        </h2>
        <div className="reveal mt-12 flex flex-col gap-3 sm:flex-row" style={{ '--d': '150ms' }}>
          <Link to="/signup" className="btn-ink btn-lg btn-pill group">
            Create your account
            <ArrowRightIcon className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
          </Link>
          <Link to="/login" className="btn btn-lg btn-pill border border-ink/40 text-ink hover:border-ink hover:bg-ink/10">
            Log in
          </Link>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="bg-ink px-5 pb-10 pt-16 text-white sm:px-8">
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-12 md:grid-cols-12">
          <div className="md:col-span-6">
            <Wordmark light />
            <p className="mt-5 max-w-sm text-sm leading-6 text-white/55">
              A focused workspace for working through problems in conversation.
            </p>
          </div>
          <nav className="md:col-span-3" aria-label="Product">
            <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-white/40">Product</h3>
            <ul className="mt-5 space-y-3 text-sm">
              {NAV.map((n) => (
                <li key={n.href}>
                  <a href={n.href} className="text-white/75 transition-colors hover:text-white">
                    {n.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          <nav className="md:col-span-3" aria-label="Account">
            <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-white/40">Account</h3>
            <ul className="mt-5 space-y-3 text-sm">
              <li>
                <Link to="/login" className="text-white/75 transition-colors hover:text-white">
                  Log in
                </Link>
              </li>
              <li>
                <Link to="/signup" className="text-white/75 transition-colors hover:text-white">
                  Sign up
                </Link>
              </li>
            </ul>
          </nav>
        </div>
        <div className="mt-16 flex flex-col gap-2 border-t border-white/15 pt-6 text-xs text-white/40 sm:flex-row sm:justify-between">
          <span>&copy; {new Date().getFullYear()} AI Problem Solver</span>
          <span>AI responses can contain mistakes. Verify anything important.</span>
        </div>
      </div>
    </footer>
  );
}

export default function Landing() {
  useReveal();
  return (
    <div className="bg-ink">
      <a href="#features" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <Header />
      <main>
        <Hero />
        <Features />
        <HowItWorks />
        <Product />
        <CallToAction />
      </main>
      <Footer />
    </div>
  );
}
