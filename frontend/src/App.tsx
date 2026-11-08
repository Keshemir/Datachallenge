import { useCallback, useEffect, useRef, useState } from 'react';
import { loadData, request, type Data, type Conversation, type Evaluation, dialogueName, languageName, scoreText } from './client';
import { Icon } from './Icon';
import { Dialogue } from './Dialogue';
import { ImportDialog } from './ImportDialog';
import { ChecklistView } from './ChecklistView';
import { AudioLibrary } from './AudioLibrary';
import { Submission } from './Submission';
import { AppealsQueue } from './Appeals';
import { confirmDiscard, hasUnsavedChanges } from './drafts';

export function latestEvaluations(data: Data) {
  const map = new Map<string, Evaluation>();
  for (const e of data.evaluations) if (!map.has(e.conversation_hash)) map.set(e.conversation_hash, e);
  return map;
}
export function needsReview(data: Data, e?: Evaluation) {
  return !!e && (!!e.flagged_criteria?.length || !!data.checks.find(c => c.evaluation_id === e.id)?.disagreements.length);
}
export function Status({ review, evaluated }: { review: boolean; evaluated: boolean }) {
  return <span className={`status ${review ? 'warning' : evaluated ? 'success' : 'pending'}`}><span className="status-dot" />{review ? 'Нужна проверка' : evaluated ? 'Оценён' : 'Ожидает оценки'}</span>;
}
function exportRows(rows: Conversation[], data: Data) {
  const latest = latestEvaluations(data);
  const csv = [['Диалог', 'Канал', 'Язык', 'Оценка', 'Статус'], ...rows.map(c => {
    const e = latest.get(c.hash);
    return [dialogueName(c), c.channel === 'voice call' ? 'Звонок' : 'Чат', languageName[c.language], e?.total_score == null ? '' : String(e.total_score), needsReview(data, e) ? 'Нужна проверка' : e ? 'Оценён' : 'Ожидает оценки'];
  })].map(row => row.map(v => `"${(/^[=+@\-\t\r]/.test(v) ? "'" + v : v).replaceAll('"', '""')}"`).join(';')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = 'Оценки диалогов.csv'; a.click(); URL.revokeObjectURL(url);
}

export function App({ onLogout }: { onLogout: () => Promise<void> }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState('');
  const [route, setRoute] = useState(window.location.hash.slice(1));
  const acceptedHash = useRef(window.location.hash);
  const [importOpen, setImportOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const refresh = useCallback(async () => { const next = await loadData(); setData(next); setError(''); }, []);
  useEffect(() => { const c = new AbortController(); loadData(c.signal).then(setData).catch(e => { if (!c.signal.aborted) setError(e.message); }); return () => c.abort(); }, []);
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash === acceptedHash.current) return;
      if (!confirmDiscard()) { history.replaceState(null, '', window.location.pathname + window.location.search + acceptedHash.current); return; }
      acceptedHash.current = window.location.hash;
      setRoute(window.location.hash.slice(1)); setNotice(''); window.scrollTo(0, 0);
    };
    const beforeUnload = (e: BeforeUnloadEvent) => { if (hasUnsavedChanges()) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('hashchange', onHash); window.addEventListener('beforeunload', beforeUnload);
    return () => { window.removeEventListener('hashchange', onHash); window.removeEventListener('beforeunload', beforeUnload); };
  }, []);
  const selected = route.startsWith('dialog/') ? data?.conversations.find(c => c.hash === route.slice(7).split('?')[0]) : undefined;
  const reviewCount = data ? [...latestEvaluations(data).values()].filter(e => needsReview(data, e)).length : 0;
  const section = route === 'submission' ? 'Сдача результатов' : route === 'appeals' ? 'Апелляции' : route.startsWith('audio') ? 'Аудиозаписи' : route === 'checklist' ? 'Чек-лист' : route === 'review' ? 'На проверку' : 'Диалоги';
  return <div className="app-shell">
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>К содержимому</a>
    <aside className="sidebar">
      <a className="brand" href="#" aria-label="Freedom — все диалоги"><img src="/brand/freedom.svg" alt="Freedom" /><span>Контроль качества</span></a>
      <nav className="main-nav" aria-label="Основная навигация">
        <a href="#" className={section === 'Диалоги' ? 'active' : ''} aria-current={section === 'Диалоги' ? 'page' : undefined}><Icon name="chat"/><span>Диалоги</span>{data ? <span className="nav-count">{data.conversations.length}</span> : null}</a>
        <a href="#review" className={section === 'На проверку' ? 'active' : ''} aria-current={section === 'На проверку' ? 'page' : undefined}><Icon name="flag"/><span>На проверку</span>{reviewCount > 0 ? <span className="nav-count">{reviewCount}</span> : null}</a>
        <a href="#checklist" className={section === 'Чек-лист' ? 'active' : ''} aria-current={section === 'Чек-лист' ? 'page' : undefined}><Icon name="checklist"/><span>Чек-лист</span></a>
        <a href="#audio" className={section === 'Аудиозаписи' ? 'active' : ''} aria-current={section === 'Аудиозаписи' ? 'page' : undefined}><Icon name="volume"/><span>Аудио</span></a>
        <a href="#appeals" className={section === 'Апелляции' ? 'active' : ''} aria-current={section === 'Апелляции' ? 'page' : undefined}><Icon name="checklist"/><span>Апелляции</span>{data?.appeals.some(a => ['submitted', 'in_review'].includes(a.status)) ? <span className="nav-count">{data.appeals.filter(a => ['submitted', 'in_review'].includes(a.status)).length}</span> : null}</a>
        <a href="#submission" className={section === 'Сдача результатов' ? 'active' : ''} aria-current={section === 'Сдача результатов' ? 'page' : undefined}><Icon name="download"/><span>Сдача</span></a>
      </nav>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumbs"><span>Контроль качества</span><Icon name="arrow" size={14}/><span>{section}</span>{selected ? <><Icon name="arrow" size={14}/><span className="crumb-id">{dialogueName(selected)}</span></> : null}</div><button className="button secondary logout-button" onClick={() => { if (confirmDiscard()) void onLogout().catch(e => setError(e.message)); }}>Выйти</button></header>
      <main id="main-content" tabIndex={-1} className={selected ? 'page detail-page' : 'page'}>
        {notice ? <div className="notice" role="status"><Icon name="check"/>{notice}<button className="icon-button" aria-label="Закрыть уведомление" onClick={() => setNotice('')}><Icon name="close" size={16}/></button></div> : null}
        {error ? <div className="error-banner" role="alert"><span>{error}</span><button className="button secondary" onClick={() => void refresh().catch(e => setError(e.message))}>Попробовать снова</button></div> : null}
        {!data && !error ? <div className="loading-page" role="status" aria-label="Загружаем диалоги"><div className="skeleton title-skeleton"/><div className="skeleton toolbar-skeleton"/>{Array.from({length: 6}, (_, i) => <div className="skeleton row-skeleton" key={i}/>)}</div> : null}
        {data ? selected ? <Dialogue key={`${selected.hash}:${route.split("?")[1] ?? ""}`} conversation={selected} data={data} onRefresh={refresh} onNotice={setNotice}/> : route.startsWith('dialog/') ? <div className="empty-state"><Icon name="search" size={32}/><h2>Диалог не найден</h2><a className="button primary" href="#">К списку диалогов</a></div> : route.startsWith('audio') ? <AudioLibrary key={route} data={data} recordId={route.startsWith('audio/') ? route.slice(6) : undefined} onRefresh={refresh} onImport={() => setImportOpen(true)}/> : route === 'submission' ? <Submission checklists={data.checklists}/> : route === 'appeals' ? <AppealsQueue data={data}/> : route === 'checklist' ? <ChecklistView records={data.checklists} onRefresh={refresh} onNotice={setNotice}/> : <DialogueList key={section} data={data} reviewOnly={route === 'review'} onImport={() => setImportOpen(true)}/> : null}
      </main>
    </div>
    {importOpen ? <ImportDialog onClose={() => setImportOpen(false)} onDone={async (hash, message) => { await refresh(); setImportOpen(false); if (hash) window.location.hash = `dialog/${hash}`; setNotice(message); }}/>: null}
  </div>;
}

function DialogueList({ data, reviewOnly, onImport }: { data: Data; reviewOnly: boolean; onImport: () => void }) {
  const [tab, setTab] = useState('all');
  const [search, setSearch] = useState('');
  const [searchResults, setSearchResults] = useState<Conversation[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  useEffect(() => {
    setSearchError('');
    if (!search.trim()) { setSearchResults(null); setSearching(false); return; }
    const controller = new AbortController(); setSearching(true); setSearchResults([]);
    const timer = window.setTimeout(() => {
      request<Conversation[]>(`/conversations?query=${encodeURIComponent(search.trim())}`, undefined, controller.signal)
        .then(setSearchResults).catch(e => { if (!controller.signal.aborted) setSearchError(e.message); })
        .finally(() => { if (!controller.signal.aborted) setSearching(false); });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [search]);
  const [language, setLanguage] = useState('all');
  const [channel, setChannel] = useState('all');
  const [finding, setFinding] = useState('all');
  const [page, setPage] = useState(1);
  const latest = latestEvaluations(data);
  const counts = { all: data.conversations.length, pending: data.conversations.filter(c => !latest.has(c.hash)).length, evaluated: latest.size };
  const filtered = (search.trim() ? searchResults ?? [] : data.conversations).filter(c => {
    const e = latest.get(c.hash);
    return (finding !== 'critical' || !!e?.flagged_criteria.length) && (!reviewOnly || needsReview(data, e)) && (tab === 'all' || (tab === 'pending' ? !e : !!e)) && (language === 'all' || c.language === language) && (channel === 'all' || c.channel === channel);
  }).sort((a, b) => Number(latest.has(b.hash)) - Number(latest.has(a.hash)) || a.conversation_id.localeCompare(b.conversation_id));
  const pageSize = 10, pages = Math.max(1, Math.ceil(filtered.length / pageSize)), safePage = Math.min(page, pages);
  const rows = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);
  const reset = () => { setSearch(''); setLanguage('all'); setChannel('all'); setFinding('all'); setTab('all'); setPage(1); };
  return <>
    <div className="page-heading"><div><h1>{reviewOnly ? 'На проверку' : 'Диалоги'}<span className="heading-count">{reviewOnly ? filtered.length : counts.all}</span></h1><p>{reviewOnly ? 'Грубые ошибки и расхождения в оценках — в одном месте.' : 'Все обращения клиентов и результаты оценки качества.'}</p></div><div className="heading-actions"><button className="button secondary" disabled={!filtered.length} onClick={() => exportRows(filtered, data)}><Icon name="download" size={18}/>Экспорт</button><button className="button primary" onClick={onImport}><Icon name="plus" size={19}/>Загрузить диалоги</button></div></div>
    <div className="list-panel">
      {!reviewOnly ? <div className="tabs" aria-label="Статус диалогов">{([['all', 'Все диалоги'], ['pending', 'Ожидают оценки'], ['evaluated', 'Оценены']] as const).map(([key, label]) => <button key={key} aria-pressed={tab === key} className={tab === key ? 'selected' : ''} onClick={() => { setTab(key); setPage(1); }}>{label}<span>{counts[key]}</span></button>)}</div> : null}
      <div className="list-toolbar"><label className="search-field"><Icon name="search" size={19}/><input aria-label="Поиск диалогов" placeholder="Поиск по номеру или тексту диалога" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}/>{search ? <button className="icon-button" aria-label="Очистить поиск" onClick={() => { setSearch(''); setPage(1); }}><Icon name="close" size={15}/></button> : null}</label><div className="filter-group"><select aria-label="Нарушения" value={finding} onChange={e => { setFinding(e.target.value); setPage(1); }}><option value="all">Все результаты</option><option value="critical">Грубые ошибки AI</option></select><select aria-label="Канал" value={channel} onChange={e => { setChannel(e.target.value); setPage(1); }}><option value="all">Все каналы</option><option value="agent chat">Чаты</option><option value="voice call">Звонки</option></select><select aria-label="Язык" value={language} onChange={e => { setLanguage(e.target.value); setPage(1); }}><option value="all">Все языки</option>{Object.entries(languageName).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div></div>
      <div className="table-wrap"><table className="dialogue-table"><thead><tr><th>Диалог</th><th>Канал</th><th>Язык</th><th>Оценка</th><th>Статус</th><th><span className="sr-only">Открыть</span></th></tr></thead><tbody>{rows.map(c => {
        const e = latest.get(c.hash), voice = c.channel === 'voice call';
        return <tr key={c.hash}><td><div className="dialogue-cell"><span className={`channel-icon ${voice ? 'voice' : ''}`}><Icon name={voice ? 'phone' : 'chat'} size={18}/></span><div className="dialogue-copy"><a className="dialogue-link" href={`#dialog/${c.hash}`}>{dialogueName(c)}</a><p>{c.preview || `${c.message_count} реплик`}</p>{e?.flagged_criteria.length ? <span className="critical-row-label">Грубая ошибка в AI-оценке</span> : null}<span className="mobile-row-status"><Status review={needsReview(data, e)} evaluated={!!e}/></span></div></div></td><td><span className="channel-label">{voice ? 'Звонок' : 'Чат'}</span></td><td><span className="language-tag">{c.language === 'KZ' ? 'ҚАЗ' : c.language === 'RU' ? 'РУС' : 'ENG'}</span></td><td><span className={`table-score ${e?.total_score != null && e.total_score < 70 ? 'low' : ''}`}>{scoreText(e?.total_score)}</span>{e?.total_score != null ? <span className="score-denominator"> / 100</span> : null}</td><td><Status review={needsReview(data, e)} evaluated={!!e}/></td><td><a className="icon-button open-dialogue" href={`#dialog/${c.hash}`} aria-label={`Открыть ${dialogueName(c)}`}><Icon name="arrow" size={17}/></a></td></tr>;
      })}</tbody></table></div>
      {searching ? <div className="empty-state" role="status">Ищем в диалогах…</div> : searchError ? <div className="error-banner" role="alert">{searchError}</div> : !rows.length ? <div className="empty-state"><Icon name={reviewOnly ? 'shield' : 'search'} size={34}/><h2>{reviewOnly && !search && language === 'all' && channel === 'all' ? 'Нет диалогов на проверку' : 'Диалоги не найдены'}</h2><p>{data.conversations.length ? 'Измените поиск или выберите другие фильтры.' : 'Загрузите переписку или запись звонка, чтобы начать.'}</p>{data.conversations.length ? <button className="button secondary" onClick={reset}>Сбросить фильтры</button> : <button className="button primary" onClick={onImport}>Загрузить диалоги</button>}</div> : <footer className="table-footer"><span>Показано {(safePage - 1) * pageSize + 1}–{Math.min(safePage * pageSize, filtered.length)} из {filtered.length}</span><div className="pagination"><button className="icon-button" aria-label="Предыдущая страница" disabled={safePage === 1} onClick={() => setPage(safePage - 1)}><Icon name="back" size={16}/></button>{Array.from({ length: pages }, (_, i) => i + 1).filter(n => n === 1 || n === pages || Math.abs(n - safePage) <= 1).map((n, i, ns) => <span key={n}>{i > 0 && n - ns[i - 1] > 1 ? <span className="pagination-gap">…</span> : null}<button className={safePage === n ? 'current' : ''} aria-label={`Страница ${n}`} aria-current={safePage === n ? 'page' : undefined} onClick={() => setPage(n)}>{n}</button></span>)}<button className="icon-button" aria-label="Следующая страница" disabled={safePage === pages} onClick={() => setPage(safePage + 1)}><Icon name="arrow" size={16}/></button></div></footer>}
    </div>
  </>;
}
