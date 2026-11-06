import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError } from '../api/http';
import { useAuth } from '../context/AuthContext';
import { AlertIcon, ArrowRightIcon, Logo, Spinner } from './Icons';

const COPY = {
  login: {
    title: 'Welcome back',
    sub: 'Log in to continue your conversations.',
    submit: 'Log in',
    switchText: "Don't have an account?",
    switchLink: '/signup',
    switchLabel: 'Sign up',
  },
  signup: {
    title: 'Create your account',
    sub: 'Start working through problems in minutes.',
    submit: 'Create account',
    switchText: 'Already have an account?',
    switchLink: '/login',
    switchLabel: 'Log in',
  },
};

export default function AuthPage({ mode }) {
  const copy = COPY[mode];
  const { login, signup } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await (mode === 'login' ? login(email.trim(), password) : signup(email.trim(), password));
      navigate('/', { replace: true }); // straight into the chat application
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not reach the server. Please try again.');
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-ink p-12 text-white lg:flex">
        <div
          className="absolute inset-0 opacity-[0.05]"
          style={{
            backgroundImage:
              'linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)',
            backgroundSize: '96px 96px',
          }}
        />
        <Link to="/" className="relative flex items-center gap-2.5" aria-label="Back to home">
          <Logo className="h-7 w-7" />
          <span className="text-[15px] font-bold uppercase tracking-[0.12em]">Problem Solver</span>
        </Link>
        <div className="relative">
          <h2 className="text-6xl font-black uppercase leading-[0.9] tracking-display xl:text-7xl">
            Think it
            <br />
            through.
            <br />
            <span className="text-accent-500">Solve it.</span>
          </h2>
          <p className="mt-6 max-w-sm text-white/65">Your conversations are saved to your account and private to you.</p>
        </div>
        <div className="relative h-1 w-24 bg-accent-500" />
      </aside>

      <main className="flex min-h-full flex-col bg-white px-5 py-8 sm:px-10">
        <Link to="/" className="flex items-center gap-2.5 text-ink lg:hidden" aria-label="Back to home">
          <Logo className="h-7 w-7" />
          <span className="text-[15px] font-bold uppercase tracking-[0.12em]">Problem Solver</span>
        </Link>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10">
          <h1 className="text-4xl font-black uppercase leading-none tracking-display text-ink">{copy.title}</h1>
          <p className="mt-3 text-zinc-600">{copy.sub}</p>

          <form onSubmit={onSubmit} className="mt-8 space-y-5" noValidate>
            {error && (
              <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800">
                <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            <div>
              <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-ink">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input py-3"
                placeholder="you@example.com"
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-ink">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                minLength={mode === 'signup' ? 8 : undefined}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input py-3"
                placeholder={mode === 'signup' ? 'At least 8 characters' : 'Your password'}
              />
            </div>
            <button type="submit" disabled={busy || !email || !password} className="btn-ink btn-lg group w-full btn-pill">
              {busy ? (
                <>
                  <Spinner /> Please wait
                </>
              ) : (
                <>
                  {copy.submit}
                  <ArrowRightIcon className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
                </>
              )}
            </button>
          </form>

          <p className="mt-8 text-sm text-zinc-600">
            {copy.switchText}{' '}
            <Link to={copy.switchLink} className="font-semibold text-ink underline underline-offset-4 hover:text-accent-600">
              {copy.switchLabel}
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
