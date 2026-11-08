import { useEffect, useState } from 'react';
import { request, type ChecklistRecord } from './client';
import { Icon } from './Icon';

type Dataset = { hash: string; group_id: string; count: number; chats: number; calls: number };
type Preview = { ready: boolean; issues: string[]; errors: { conversation_id: string; conversation_hash: string; reason: string }[]; summary: { total: number; ok: number; error: number }; target_path: string; payload: object | null };

export function Submission({ checklists }: { checklists: ChecklistRecord[] }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadRetry, setLoadRetry] = useState(0);
  const [dataset, setDataset] = useState('');
  const [split, setSplit] = useState('dev');
  const [team, setTeam] = useState('Bibigon');
  const [rubric, setRubric] = useState(checklists[checklists.length - 1]?.hash ?? '');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [allowErrors, setAllowErrors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [downloaded, setDownloaded] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    request<Dataset[]>('/submissions/datasets', undefined, controller.signal)
      .then(rows => { if (!controller.signal.aborted) { setDatasets(rows); setDataset(rows[0]?.hash ?? ''); if (rows[0]?.group_id.toLowerCase() === 'prod') setSplit('prod'); } })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [loadRetry]);
  function reset() { setPreview(null); setAllowErrors(false); setDownloaded(false); setError(''); }
  async function check() {
    if (busy) return;
    setBusy(true); reset();
    try { setPreview(await request<Preview>('/submissions/preview', { dataset_hash: dataset, checklist_hash: rubric, split, team_name: team.trim() })); }
    catch (e) { setError(e instanceof Error ? e.message : 'Не удалось проверить результаты. Попробуйте снова.'); }
    finally { setBusy(false); }
  }
  function download() {
    if (!preview?.ready || !preview.payload || (preview.summary.error > 0 && !allowErrors)) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(preview.payload, null, 2) + '\n'], { type: 'application/json;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = 'results.json'; a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000); setDownloaded(true);
  }
  const chosen = datasets.find(d => d.hash === dataset);
  return <>
    <div className="page-heading"><div><h1>Сдача результатов</h1><p>Проверьте набор и скачайте файл для организаторов.</p></div></div>
    {error ? <div className="error-banner" role="alert">{error}{!datasets.length ? <button className="button secondary" onClick={() => setLoadRetry(n => n + 1)}>Повторить загрузку</button> : null}</div> : null}
    {loading ? <p role="status">Загружаем исходные наборы…</p> : !datasets.length ? <div className="empty-state"><Icon name="download" size={30}/><h2>Нужен исходный набор организаторов</h2><p>Загрузите ответ их API через «Загрузить диалоги» → «Загрузить файл». Он определит точный состав сдачи.</p><a className="button primary" href="#">К диалогам</a></div> : <div className="submission-workspace">
      <form className="submission-form" onSubmit={e => { e.preventDefault(); void check(); }}>
        <h2>Параметры сдачи</h2>
        <fieldset disabled={busy}>
          <label>Название команды<input value={team} maxLength={150} required onChange={e => { setTeam(e.target.value); reset(); }}/></label>
          <label>Этап<select aria-label="Этап" value={split} onChange={e => { setSplit(e.target.value); reset(); }}><option value="dev">DEV · 60 чатов и 5 звонков</option><option value="prod">PROD · 10 контрольных чатов</option></select></label>
          <label>Исходный набор{datasets.length > 1 ? <select aria-label="Исходный набор" value={dataset} onChange={e => { setDataset(e.target.value); reset(); }}>{datasets.map((d, i) => <option key={d.hash} value={d.hash}>{d.group_id} · {d.count} диалогов · набор {datasets.length - i}</option>)}</select> : <span className="submission-value">{chosen?.group_id} · {chosen?.count} диалогов</span>}</label>
          <label>Версия чек-листа{checklists.length > 1 ? <select aria-label="Версия чек-листа" value={rubric} onChange={e => { setRubric(e.target.value); reset(); }}>{checklists.map(c => <option key={c.hash} value={c.hash}>{c.checklist.title} · v{c.checklist.version}</option>)}</select> : <span className="submission-value">{checklists[0]?.checklist.title} · v{checklists[0]?.checklist.version}</span>}</label>
        </fieldset>
        <p className="submission-help">Берём последние сохранённые AI-оценки этой версии по исходным транскриптам. Повторные расшифровки и результаты апелляций в файл не входят.</p>
        <button className="button primary" disabled={busy || !team.trim() || !dataset || !rubric}>{busy ? 'Проверяем…' : 'Проверить результаты'}</button>
      </form>
      <section className="submission-result" aria-label="Результат проверки" aria-busy={busy}>
        {!preview ? <><h2>Перед выгрузкой</h2><p>Проверим состав набора, восемь критериев, итоговые баллы и ссылки на исходные реплики.</p><p>Проверка использует сохранённые результаты и не запускает оценивание заново.</p></> : <>
          <h2>{preview.ready ? preview.summary.error ? 'Файл содержит ошибки обработки' : 'Файл готов к выгрузке' : 'Нужно исправить перед выгрузкой'}</h2>
          <p role="status">Всего: <strong>{preview.summary.total}</strong> · с оценкой: <strong>{preview.summary.ok}</strong> · с ошибкой: <strong>{preview.summary.error}</strong></p>
          {preview.issues.length ? <ul className="submission-issues">{preview.issues.map(issue => <li key={issue}>{issue}</li>)}</ul> : null}
          {preview.errors.length ? <><p>Эти диалоги сохранятся с исходными ID и отметкой об ошибке. Их можно оценить и повторить проверку.</p><div className="submission-errors">{preview.errors.map((item, i) => <div key={`${item.conversation_hash}-${i}`}><a href={`#dialog/${item.conversation_hash}`}>{item.conversation_id}<Icon name="arrow" size={15}/></a><p>{item.reason}</p></div>)}</div></> : null}
          {preview.ready ? <><p className="submission-destination">Положите скачанный файл в <strong>{preview.target_path}</strong></p>{preview.summary.error > 0 ? <label className="submission-confirm"><input type="checkbox" checked={allowErrors} onChange={e => setAllowErrors(e.target.checked)}/><span>Включить записи с ошибкой обработки: {preview.summary.error}</span></label> : null}<button className="button primary" onClick={download} disabled={preview.summary.error > 0 && !allowErrors}><Icon name="download" size={17}/>Скачать results.json</button></> : null}
          {downloaded ? <p className="submission-help" role="status">Скачивание запущено. Добавьте файл в указанную папку репозитория и отправьте изменения в Git до стоп-кода.</p> : null}
        </>}
      </section>
    </div>}
  </>;
}
