import { useRef, useState } from 'react';
import { confirmDiscard, useUnsavedChanges } from './drafts';
import { dialogueName, request, roleName, scoreText, type Appeal, type ChecklistRecord, type Data, type FullEvaluation, type Message } from './client';

export const appealStatus: Record<string, string> = { submitted: 'Подана', in_review: 'На рассмотрении', accepted: 'Принята', rejected: 'Отклонена' };
const dateText = (value: string) => new Date(value).toLocaleString('ru-RU', { timeZone: 'Asia/Qyzylorda', dateStyle: 'short', timeStyle: 'short' });

export function AppealsQueue({ data }: { data: Data }) {
  const [status, setStatus] = useState('open');
  const rows = data.appeals.filter(a => status === 'all' || (status === 'open' ? ['submitted', 'in_review'].includes(a.status) : a.status === status));
  return <>
    <div className="page-heading"><div><h1>Апелляции</h1><p>Обращения по спорным критериям и история решений.</p></div><label className="queue-filter">Статус<select aria-label="Статус" value={status} onChange={e => setStatus(e.target.value)}><option value="open">Открытые</option><option value="all">Все апелляции</option>{Object.entries(appealStatus).map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label></div>
    <div className="appeals-queue">{rows.length ? rows.map(a => {
      const conversation = data.conversations.find(c => c.hash === a.conversation_hash);
      return <article className="appeal-queue-row" key={a.id}><div><span className={`status ${a.status === 'accepted' ? 'success' : 'warning'}`}>{appealStatus[a.status]}</span><h2><a href={`#dialog/${a.conversation_hash}?evaluation=${a.evaluation_id}&appeal=${a.id}`}>{conversation ? dialogueName(conversation) : 'Диалог'} · {a.criterion_title}</a></h2><p>{a.reason}</p><span className="muted small">{a.author} · {dateText(a.created_at)}</span></div><a className="button secondary" href={`#dialog/${a.conversation_hash}?evaluation=${a.evaluation_id}&appeal=${a.id}`}>Рассмотреть</a></article>;
    }) : <div className="empty-state"><h2>Апелляций пока нет</h2><p>Подать апелляцию можно в карточке оценки на вкладке «Апелляции».</p></div>}</div>
  </>;
}

export function AppealsPanel({ evaluation, checklist, messages, data, onRefresh }: {
  evaluation: FullEvaluation; checklist: ChecklistRecord; messages: Message[]; data: Data; onRefresh: () => Promise<void>;
}) {
  const [criterion, setCriterion] = useState(checklist.checklist.criteria[0]?.id ?? '');
  const [author, setAuthor] = useState('');
  const [reason, setReason] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const guard = useRef(false);
  const appeals = data.appeals.filter(a => a.evaluation_id === evaluation.id);
  const duplicate = appeals.some(a => a.criterion_id === criterion && ['submitted', 'in_review'].includes(a.status));
  useUnsavedChanges(formOpen && (!!author || !!reason || criterion !== checklist.checklist.criteria[0]?.id));
  async function submit(e: React.FormEvent) {
    e.preventDefault(); if (guard.current) return;
    guard.current = true; setBusy(true); setError('');
    try {
      await request('/appeals', { evaluation_id: evaluation.id, criterion_id: criterion, author: author.trim(), reason: reason.trim() });
      setReason(''); setFormOpen(false); await onRefresh();
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось подать апелляцию.'); }
    finally { guard.current = false; setBusy(false); }
  }
  return <div className="appeals-panel">
    <h3>Апелляции по этой оценке</h3><p className="field-help">Исходная AI-оценка сохраняется. Принятое решение QA создаёт отдельный результат.</p>
    {error ? <div className="error-banner" role="alert">{error}</div> : null}
    {!formOpen ? <button className="button secondary full-width" onClick={() => setFormOpen(true)}>Подать апелляцию</button> : <form onSubmit={e => void submit(e)} className="appeal-form"><fieldset disabled={busy} className="editor-fields">
      <label className="form-field">Критерий<select aria-label="Критерий" value={criterion} onChange={e => setCriterion(e.target.value)}>{checklist.checklist.criteria.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label>
      <label className="form-field">Ваше имя<input required maxLength={120} value={author} onChange={e => setAuthor(e.target.value)}/></label>
      <label className="form-field">Почему вы не согласны?<textarea aria-label="Почему вы не согласны?" required maxLength={20000} rows={4} value={reason} onChange={e => setReason(e.target.value)} placeholder="Укажите, какое действие или реплику оценили неверно."/></label>
      {duplicate ? <p className="error-text" role="status">По этому критерию уже есть открытая апелляция.</p> : null}
      <div className="form-actions"><button type="button" className="button secondary" onClick={() => { if (confirmDiscard()) { setFormOpen(false); setReason(''); setAuthor(''); } }}>Отменить</button><button className="button primary" disabled={duplicate || !author.trim() || !reason.trim()}>{busy ? 'Отправляем…' : 'Отправить апелляцию'}</button></div>
    </fieldset></form>}
    <p className="field-help">Общее рабочее пространство: имена в истории вводятся вручную.</p>
    {appeals.length ? appeals.map(a => <AppealReview key={a.id} appeal={a} evaluation={evaluation} checklist={checklist} messages={messages} data={data} onRefresh={onRefresh}/>) : <p className="field-help">По этой версии оценки обращений нет.</p>}
  </div>;
}

function AppealReview({ appeal: a, evaluation, checklist, messages, data, onRefresh }: {
  appeal: Appeal; evaluation: FullEvaluation; checklist: ChecklistRecord; messages: Message[]; data: Data; onRefresh: () => Promise<void>;
}) {
  const c = checklist.checklist.criteria.find(c => c.id === a.criterion_id)!;
  const qa = data.reviews.find(r => r.evaluation_id === evaluation.id);
  const judgment = (qa?.result ?? evaluation.result).criteria.find(r => r.criterion_id === a.criterion_id)!.judgment;
  const [reviewer, setReviewer] = useState(a.events.find(e => e.status === 'in_review')?.actor ?? '');
  const [outcome, setOutcome] = useState('accepted');
  const [choice, setChoice] = useState(judgment.decision === 'score' ? `score_${judgment.score}` : judgment.decision);
  const [note, setNote] = useState('');
  const [naReason, setNaReason] = useState(judgment.na_reason ?? '');
  const [evidence, setEvidence] = useState<string[]>(judgment.evidence_message_ids);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const guard = useRef(false);
  useUnsavedChanges(['submitted', 'in_review'].includes(a.status) && (
    reviewer !== (a.events.find(e => e.status === 'in_review')?.actor ?? '') || !!note ||
    choice !== (judgment.decision === 'score' ? `score_${judgment.score}` : judgment.decision) ||
    naReason !== (judgment.na_reason ?? '') || outcome !== 'accepted' ||
    JSON.stringify(evidence) !== JSON.stringify(judgment.evidence_message_ids)
  ));
  async function act(e: React.FormEvent) {
    e.preventDefault(); if (guard.current) return;
    setError('');
    const score = choice.startsWith('score_') ? Number(choice.slice(6)) : null;
    if (a.status === 'in_review' && outcome === 'accepted') {
      const positive = choice === 'yes' || (score !== null && score > 0);
      if (positive && !evidence.length) { setError('Выберите подтверждающие реплики.'); return; }
      if (positive && c.evidence_policy === 'operator' && !messages.some(m => evidence.includes(m.message_id) && m.speaker === 'operator')) { setError('Нужна подтверждающая реплика оператора.'); return; }
      if (positive && c.evidence_policy === 'first_operator' && !evidence.includes(messages.find(m => m.speaker === 'operator')?.message_id ?? '')) { setError('Выберите первый ответ оператора.'); return; }
      if (choice === 'na' && !naReason.trim()) { setError('Объясните, почему выполнено условие N/A.'); return; }
    }
    guard.current = true; setBusy(true);
    try {
      if (a.status === 'submitted') await request(`/appeals/${a.id}/start`, { reviewer: reviewer.trim() });
      else await request(`/appeals/${a.id}/resolve`, { reviewer: reviewer.trim(), outcome, note: note.trim(), judgment: outcome === 'accepted' ? {
        criterion_id: c.id, decision: score === null ? choice : 'score', score, explanation: note.trim(), evidence_message_ids: evidence,
        checked_range: { start_message_id: messages[0].message_id, end_message_id: messages[messages.length - 1].message_id }, na_reason: choice === 'na' ? naReason.trim() : null,
      } : null });
      await onRefresh();
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сохранить решение.'); }
    finally { guard.current = false; setBusy(false); }
  }
  const review = data.reviews.find(r => r.appeal_id === a.id);
  return <details className="appeal-review" open><summary><strong>{a.criterion_title}</strong><span className="status">{appealStatus[a.status]}</span></summary>
    <ol className="appeal-history">{a.events.map((event, i) => <li key={i}><strong>{appealStatus[event.status]} · {event.actor}</strong><time>{dateText(event.at)}</time><p>{event.note}</p></li>)}</ol>
    {review ? <p className="review-score">Итог после этого решения QA: <strong>{scoreText(review.result.total_score)} / 100</strong></p> : null}
    {error ? <div className="error-banner" role="alert">{error}</div> : null}
    {['submitted', 'in_review'].includes(a.status) ? <form onSubmit={e => void act(e)}><fieldset disabled={busy} className="editor-fields">
      <label className="form-field">Специалист QA<input required maxLength={120} value={reviewer} onChange={e => setReviewer(e.target.value)}/></label>
      {a.status === 'in_review' ? <>
        <label className="form-field">Решение<select aria-label="Решение" value={outcome} onChange={e => setOutcome(e.target.value)}><option value="accepted">Принять апелляцию</option><option value="rejected">Отклонить апелляцию</option></select></label>
        {outcome === 'accepted' ? <>
          <p className="field-help">Правило: {c.instructions}</p>
          <label className="form-field">Ответ после проверки<select aria-label="Ответ после проверки" value={choice} onChange={e => setChoice(e.target.value)}>{c.kind === 'scale' ? c.scale.map(s => <option key={s.value} value={`score_${s.value}`}>{s.value} — {s.description}</option>) : <><option value="yes">Да</option><option value="no">Нет</option></>}{c.allow_na ? <option value="na">N/A — не применимо</option> : null}</select></label>
          {choice === 'na' ? <label className="form-field">Основание N/A<span>{c.na_condition}</span><textarea required rows={2} value={naReason} onChange={e => setNaReason(e.target.value)} maxLength={20000}/></label> : null}
          <fieldset className="evidence-picker"><legend>Подтверждающие реплики</legend><div>{messages.map(m => <label key={m.message_id}><input type="checkbox" checked={evidence.includes(m.message_id)} onChange={e => setEvidence(ids => e.target.checked ? [...ids, m.message_id] : ids.filter(id => id !== m.message_id))}/><span><strong>{roleName[m.speaker]} · {m.timestamp}</strong>{m.text}</span></label>)}</div></fieldset>
          <p className="field-help">Для отсутствующего действия проверяется весь диалог. Положительный ответ требует цитаты.</p>
        </> : null}
        <label className="form-field">Обоснование решения<textarea aria-label="Обоснование решения" required maxLength={20000} rows={3} value={note} onChange={e => setNote(e.target.value)}/></label>
      </> : null}
      <button className="button primary full-width" disabled={!reviewer.trim() || (a.status === 'in_review' && !note.trim())}>{busy ? 'Сохраняем…' : a.status === 'submitted' ? 'Взять на рассмотрение' : 'Сохранить решение QA'}</button>
    </fieldset></form> : null}
  </details>;
}
