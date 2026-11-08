import { useEffect, useState, type FormEvent } from 'react';
import { App } from './App';
import { request, setCsrfToken } from './client';
import { Icon } from './Icon';

type Session = { authenticated: boolean; configured?: boolean; csrf_token: string | null };

export function SessionGate() {
  const [session, setSession] = useState<Session | null>(null);
  const [password, setPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    request<Session>('/auth/session', undefined, controller.signal).then(s => { if (!controller.signal.aborted) { setCsrfToken(s.csrf_token); setSession(s); } }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    const expired = () => { setCsrfToken(null); setSession({ authenticated: false, csrf_token: null }); setError('Сессия завершена. Войдите снова.'); };
    window.addEventListener('cqa-session-expired', expired);
    return () => { controller.abort(); window.removeEventListener('cqa-session-expired', expired); };
  }, [retry]);
  async function signIn(event: FormEvent) {
    event.preventDefault(); if (busy) return; setBusy(true); setError('');
    try { const s = await request<Session>('/auth/login', { password }); setPassword(''); setCsrfToken(s.csrf_token); setSession(s); }
    catch (e) { setPassword(''); setError(e instanceof Error ? e.message : 'Не удалось войти.'); }
    finally { setBusy(false); }
  }
  if (session?.authenticated) return <App onLogout={async () => { await request('/auth/logout', {}); setCsrfToken(null); setSession({ authenticated: false, csrf_token: null }); setError(''); }}/>;
  return <main className="login-page"><div className="login-panel">
    <img src="/brand/freedom.svg" alt="Freedom" className="login-brand"/>
    <span className="login-symbol"><Icon name="shield" size={28}/></span>
    <h1>Контроль качества</h1><p>Войдите, чтобы работать с диалогами и оценками.</p>
    {error ? <div className="error-banner" role="alert">{error}</div> : null}
    {!session ? error ? <button className="button secondary full-width" onClick={() => { setError(''); setRetry(n => n + 1); }}>Попробовать снова</button> : <p role="status">Проверяем доступ…</p> : session.configured === false ? <p className="setup-note">Доступ ещё не настроен. Администратору нужно задать пароль на сервере.</p> : <form onSubmit={event => void signIn(event)}>
      <label htmlFor="password">Пароль доступа</label><div className="password-field"><input id="password" name="password" type={visible ? 'text' : 'password'} autoComplete="current-password" maxLength={128} required value={password} onChange={e => setPassword(e.target.value)} disabled={busy}/><button type="button" className="password-toggle" aria-pressed={visible} onClick={() => setVisible(v => !v)}>{visible ? 'Скрыть' : 'Показать'}</button></div>
      <button className="button primary full-width" type="submit" disabled={busy || !password}>{busy ? 'Входим…' : 'Войти'}</button>
    </form>}
  </div></main>;
}
