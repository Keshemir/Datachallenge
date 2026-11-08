import { useEffect, useRef, useState } from 'react';
import { request, dialogueName, languageName, roleName, choiceText, scoreText, type Conversation, type ConversationDetail, type Data, type FullEvaluation, type Transcript, type CriterionResult } from './client';
import { Icon } from './Icon';
import { AudioPlayer } from './AudioPlayer';
import { AppealsPanel } from './Appeals';
import { confirmDiscard } from './drafts';

export function Dialogue({ conversation: c, data, onRefresh, onNotice }: { conversation: Conversation; data: Data; onRefresh: () => Promise<void>; onNotice: (message: string) => void }) {
  const linkedId = new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('evaluation');
  const initialEvaluation = data.evaluations.find(e => e.conversation_hash === c.hash && e.id === linkedId) ?? data.evaluations.find(e => e.conversation_hash === c.hash);
  const [rubric, setRubric] = useState(initialEvaluation?.checklist_hash ?? data.checklists[0]?.hash ?? '');
  const [chosenEvaluation, setChosenEvaluation] = useState(linkedId ?? '');
  const candidates = data.evaluations.filter(e => e.conversation_hash === c.hash && e.checklist_hash === rubric);
  const evaluationId = candidates.find(e => e.id === chosenEvaluation)?.id ?? candidates[0]?.id;
  const transcriptionId = c.transcription_id ?? data.transcriptions.find(t => t.source_conversation_hash === c.hash)?.id;
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [evaluation, setEvaluation] = useState<FullEvaluation | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [playbackWarning, setPlaybackWarning] = useState('');
  const [busy, setBusy] = useState('');
  const [audioView, setAudioView] = useState(false);
  const [resultTab, setResultTab] = useState(window.location.hash.includes('appeal=') ? 'appeals' : 'score');
  const [scoreSource, setScoreSource] = useState('ai');
  const [highlight, setHighlight] = useState('');
  const player = useRef<HTMLAudioElement>(null);
  const inFlight = useRef(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(''); setPlaybackWarning(''); setEvaluation(null);
    Promise.all([
      request<ConversationDetail>(`/conversations/${c.hash}`, undefined, controller.signal),
      evaluationId ? request<FullEvaluation>(`/evaluations/${evaluationId}`, undefined, controller.signal) : Promise.resolve(null),
      transcriptionId ? request<Transcript>(`/transcriptions/${transcriptionId}`, undefined, controller.signal) : Promise.resolve(null),
    ]).then(([d, e, t]) => { if (!controller.signal.aborted) { setDetail(d); setEvaluation(e); setTranscript(t); } })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [c.hash, evaluationId, transcriptionId, retry]);
  async function act(label: string, run: () => Promise<void>) {
    if (inFlight.current || !confirmDiscard()) return;
    inFlight.current = true; setBusy(label); setError('');
    try { await run(); await onRefresh(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Не удалось выполнить действие. Попробуйте ещё раз.'); }
    finally { inFlight.current = false; setBusy(''); }
  }
  function reveal(id: string) {
    setAudioView(false); setHighlight(id);
    requestAnimationFrame(() => document.getElementById(`message-${id}`)?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center' }));
  }
  const check = data.checks.find(r => r.evaluation_id === evaluationId);
  const roles = transcript?.speaker_roles ?? {};
  const qaReview = data.reviews.find(r => r.evaluation_id === evaluationId);
  const shownResult = scoreSource === 'qa' && qaReview ? qaReview.result : evaluation?.result;
  const currentChecklist = data.checklists.find(r => r.hash === rubric);
  const dateLabel = (date: string) => new Date(date).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Qyzylorda' });
  function downloadReport() {
    if (!evaluation) return;
    const content = { dialogue: dialogueName(c), language: c.language, checklist: currentChecklist?.checklist.title, version: currentChecklist?.checklist.version, evaluated_at: evaluation.created_at, qa_review: qaReview ?? null, score: evaluation.result.total_score, critical_errors: evaluation.result.flagged_criteria, criteria: evaluation.result.criteria.map(r => ({ criterion: r.title, answer: r.judgment.decision, score: r.judgment.score, explanation: r.judgment.explanation, evidence: r.evidence })) };
    const url = URL.createObjectURL(new Blob([JSON.stringify(content, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = `Оценка-${c.conversation_id.replace(/[^a-zA-Z0-9_-]/g, '_')}.json`; a.click(); URL.revokeObjectURL(url);
  }
  return <>
    <a className="back-link" href="#"><Icon name="back" size={16}/>Все диалоги</a>
    <div className="page-heading detail-heading"><div><h1>{dialogueName(c)}</h1><div className="detail-meta"><span><Icon name={c.channel === 'voice call' ? 'phone' : 'chat'} size={16}/>{c.channel === 'voice call' ? 'Звонок' : 'Чат'}</span><span>{languageName[c.language]}</span><span>{c.message_count} реплик</span></div></div><button className="button secondary" disabled={!evaluation || !!busy} onClick={downloadReport}><Icon name="download" size={18}/>Скачать оценку</button></div>
    {playbackWarning ? <div className="error-banner" role="alert">{playbackWarning}</div> : null}
    {error ? <div className="error-banner" role="alert"><span>{error}</span><button className="button secondary" disabled={!!busy} onClick={() => setRetry(n => n + 1)}>Обновить</button></div> : null}
    {busy ? <div className="processing-banner" role="status"><span className="loading-dot"/>{busy}<span>Результат появится здесь. Не закрывайте страницу.</span></div> : null}
    <div className="dialogue-workspace">
      <section className="conversation-panel" aria-label="Содержание диалога">
        <div className="panel-heading"><h2>{audioView ? 'Расшифровка' : 'Диалог'}</h2>{c.channel === 'voice call' && !c.transcription_id ? <div className="segmented"><button aria-pressed={!audioView} onClick={() => setAudioView(false)}>Текст</button><button aria-pressed={audioView} onClick={() => setAudioView(true)}>Аудио</button></div> : <span className="muted small">Исходные реплики</span>}</div>
        {transcript ? <div className="audio-strip"><div className="audio-caption"><Icon name="volume" size={17}/><strong>Запись звонка</strong><span>{Math.floor(transcript.duration_seconds / 60)} мин {Math.round(transcript.duration_seconds % 60)} сек</span></div><AudioPlayer onPlaybackStarted={() => setPlaybackWarning('')} audioRef={player} src={`/api/transcriptions/${transcript.id}/audio`} durationHint={transcript.duration_seconds}/></div> : null}
        {audioView && !transcript ? <div className="empty-state"><Icon name="volume" size={36}/><h3>Расшифруйте запись</h3><p>Получите текст с таймкодами и разделением говорящих.</p><button className="button primary" disabled={!!busy || !c.has_audio} onClick={() => void act('Распознаём запись…', async () => { const r = await request<Transcript>('/transcriptions', { conversation_hash: c.hash }); setTranscript(r); const prepared = await request<{ hash: string }>('/transcriptions/auto-conversation', { transcription_id: r.id }); window.location.hash = `dialog/${prepared.hash}`; })}>Расшифровать аудио</button></div> : audioView && transcript ? <>
          <div className="role-assignment"><h3>Участники разговора</h3><p>Клиент и оператор определяются автоматически по всему разговору.</p>{!c.transcription_id ? <button className="button primary" disabled={!!busy || transcript.has_unassigned_speech || transcript.speaker_ids.length < 2} onClick={() => void act('Определяем участников…', async () => { const result = await request<{ hash: string }>('/transcriptions/auto-conversation', { transcription_id: transcript.id }); window.location.hash = `dialog/${result.hash}`; onNotice('Диалог готов к оценке.'); })}>Подготовить диалог</button> : null}</div>
          <div className="messages stt-messages">{transcript.turns.map(t => <article className="speech-fragment" key={t.id}><div className="message-meta"><strong>{roles[t.speaker ?? ''] ? roleName[roles[t.speaker ?? '']] : `Говорящий ${t.speaker ?? '?'}`}</strong><button className="timestamp-button" onClick={() => { if (player.current) { player.current.currentTime = t.start; void player.current.play().catch(() => setPlaybackWarning('Нажмите воспроизведение в плеере.')); } }}>{Math.floor(t.start / 60)}:{String(Math.floor(t.start % 60)).padStart(2, '0')}</button></div><p>{t.text}</p></article>)}</div>
        </> : loading ? <div className="message-loading" role="status" aria-label="Загружаем диалог">{[0,1,2,3].map(n => <div key={n} className="skeleton message-skeleton"/>)}</div> : detail ? <div className="messages">{detail.conversation.transcript.map(m => <article id={`message-${m.message_id}`} tabIndex={-1} key={m.message_id} className={`message ${m.speaker} ${highlight === m.message_id ? 'highlighted' : ''}`}><div className="message-meta"><strong>{roleName[m.speaker] ?? m.speaker}</strong><span>{m.timestamp}</span></div><div className="message-bubble">{m.text}</div></article>)}<div className="end-of-dialogue">Конец диалога</div></div> : null}
      </section>
      <aside className="evaluation-panel" aria-label="Оценка диалога">
        <div className="panel-heading"><h2>Оценка качества</h2><Icon name="shield" size={20}/></div>
        <div className="rubric-select">{data.checklists.length > 1 ? <><label htmlFor="rubric">Чек-лист</label><select id="rubric" value={rubric} disabled={!!busy} onChange={e => { if (confirmDiscard()) { setRubric(e.target.value); setChosenEvaluation(''); setScoreSource('ai'); } }}>{data.checklists.map(r => <option key={r.hash} value={r.hash}>{r.checklist.title} · v{r.checklist.version}</option>)}</select></> : <><span className="rubric-label">Чек-лист</span><p className="rubric-name">{currentChecklist ? `${currentChecklist.checklist.title} · v${currentChecklist.checklist.version}` : 'Чек-лист не выбран'}</p></>}</div>
        {loading ? <div className="score-loading"><div className="skeleton row-skeleton"/><div className="skeleton row-skeleton"/></div> : evaluation ? <>
          {qaReview ? <div className="assessment-source"><label>Источник оценки<select aria-label="Источник оценки" value={scoreSource} onChange={e => setScoreSource(e.target.value)}><option value="ai">Исходная AI-оценка</option><option value="qa">После проверки QA</option></select></label><p>AI: {scoreText(evaluation.result.total_score)} · QA: {scoreText(qaReview.result.total_score)}</p></div> : null}
          <div className="score-summary"><div><span className="score-label">Итоговая оценка</span><div className="big-score">{scoreText(shownResult?.total_score)}<span>/ 100</span></div></div><div className={`score-summary-note ${shownResult?.flagged_criteria.length ? 'critical-note' : ''}`}><Icon name={shownResult?.flagged_criteria.length ? 'flag' : 'check'} size={17}/><span>{shownResult?.flagged_criteria.length ? 'Есть грубая ошибка' : 'Без грубых ошибок'}</span></div></div>
          <div className="result-tabs tabs"><button aria-pressed={resultTab === 'score'} className={resultTab === 'score' ? 'selected' : ''} onClick={() => setResultTab('score')}>Критерии<span>{evaluation.result.criteria.length}</span></button><button aria-pressed={resultTab === 'verify'} className={resultTab === 'verify' ? 'selected' : ''} onClick={() => setResultTab('verify')}>Перепроверка{check?.disagreements.length ? <span>{check.disagreements.length}</span> : null}</button><button aria-pressed={resultTab === 'appeals'} className={resultTab === 'appeals' ? 'selected' : ''} onClick={() => setResultTab('appeals')}>Апелляции</button></div>
          {resultTab === 'score' ? <div className="criteria-results">{shownResult?.criteria.map((r, index) => <CriterionRow key={r.criterion_id} result={r} index={index} reveal={reveal}/>)}</div> : resultTab === 'verify' ? <div className="verification"><h3>{check ? check.disagreements.length ? 'Есть расхождения' : 'Оценки совпали' : 'Независимая перепроверка'}</h3><p>{check ? 'Перепроверка не меняет исходную оценку. Спорные решения стоит проверить по диалогу.' : 'Повторный анализ помогает найти спорные решения по отдельным критериям.'}</p>{check?.disagreements.map(d => <div className="disagreement" key={d.criterion_id}><strong>{currentChecklist?.checklist.criteria.find(c => c.id === d.criterion_id)?.title ?? d.criterion_id}</strong><dl><div><dt>Оценка</dt><dd>{choiceText(d.evaluation_choice)}</dd></div><div><dt>Перепроверка</dt><dd>{choiceText(d.decision_choice)}</dd></div></dl></div>)}<button className="button secondary full-width" disabled={!!busy} onClick={() => void act('Перепроверяем критерии…', async () => { await request('/decision-checks', { evaluation_id: evaluation.id }); onNotice('Перепроверка завершена.'); })}><Icon name="refresh" size={17}/>{check ? 'Перепроверить ещё раз' : 'Перепроверить оценку'}</button></div> : null}
          {currentChecklist && detail ? <div hidden={resultTab !== 'appeals'}><AppealsPanel key={evaluation.id} evaluation={evaluation} checklist={currentChecklist} messages={detail.conversation.transcript} data={data} onRefresh={onRefresh}/></div> : null}
          <div className="evaluation-footer">{candidates.length > 1 ? <label>История оценок<select aria-label="История оценок" value={evaluationId} disabled={!!busy} onChange={e => { if (confirmDiscard()) { setChosenEvaluation(e.target.value); setScoreSource('ai'); } }}>{candidates.map((r, i) => <option key={r.id} value={r.id}>{dateLabel(r.created_at)} — {scoreText(r.total_score)}{i === 0 ? ' (последняя)' : ''}</option>)}</select></label> : <span className="muted small">Оценено {dateLabel(evaluation.created_at)}</span>}<button className="button secondary full-width" disabled={!!busy} onClick={() => void act('Оцениваем диалог…', async () => { const r = await request<FullEvaluation>('/evaluations', { conversation_hash: c.hash, checklist_hash: rubric }); setChosenEvaluation(r.id); onNotice('Новая оценка сохранена.'); })}><Icon name="refresh" size={17}/>Оценить повторно</button></div>
        </> : <div className="empty-state evaluation-empty"><span className="empty-symbol"><Icon name="checklist" size={28}/></span><h3>Диалог готов к оценке</h3><p>Проверьте обращение по чек-листу. Для каждого критерия появятся объяснение и подтверждающие реплики.</p><button className="button primary full-width" disabled={!!busy || !rubric || !detail} onClick={() => void act('Оцениваем диалог…', async () => { const r = await request<FullEvaluation>('/evaluations', { conversation_hash: c.hash, checklist_hash: rubric }); setChosenEvaluation(r.id); onNotice('Оценка сохранена.'); })}>Оценить диалог</button></div>}
      </aside>
    </div>
  </>;
}

function CriterionRow({ result: r, index, reveal }: { result: CriterionResult; index: number; reveal: (id: string) => void }) {
  const j = r.judgment;
  const positive = r.kind === 'flag' ? !r.flagged : j.decision === 'yes' || j.decision === 'score' && r.earned_weight === r.weight;
  const label = j.decision === 'na' ? 'N/A' : r.kind === 'flag' ? (r.flagged ? 'Есть ошибка' : 'Нет ошибок') : `${positive ? 'Да' : j.decision === 'score' && (j.score ?? 0) > 0 ? 'Частично' : 'Нет'} · ${scoreText(r.earned_weight)} из ${scoreText(r.weight)}`;
  const tone = j.decision === 'na' ? 'neutral' : positive ? 'good' : 'bad';
  return <details className={`criterion-result ${tone}`}><summary><span className="criterion-number">{String(index + 1).padStart(2, '0')}</span><strong>{r.title}</strong><span className="answer">{label}</span><Icon name="chevron" size={15}/></summary><div className="criterion-body"><p>{j.explanation}</p>{j.na_reason ? <p className="muted">{j.na_reason}</p> : null}{r.evidence.map(m => <button className="evidence" key={m.message_id} onClick={() => reveal(m.message_id)}><span>{roleName[m.speaker]}<span>{m.timestamp}<Icon name="arrow" size={13}/></span></span><q>{m.text}</q></button>)}{!r.evidence.length ? <span className="muted small">Решение основано на проверке участка диалога.</span> : null}</div></details>;
}
