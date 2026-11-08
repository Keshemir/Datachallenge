import { useEffect, useRef, useState } from 'react';
import { request, roleName, type Data, type Transcript } from './client';
import { Icon } from './Icon';
import { AudioPlayer } from './AudioPlayer';

export function AudioLibrary({ data, recordId, onRefresh, onImport }: { data: Data; recordId?: string; onRefresh: () => Promise<void>; onImport: () => void }) {
  const [record, setRecord] = useState<Transcript | null>(null);
  const [error, setError] = useState('');
  const [playbackWarning, setPlaybackWarning] = useState('');
  const [busy, setBusy] = useState(false);
  const player = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    setRecord(null); setError(''); setPlaybackWarning('');
    if (!recordId) return;
    const controller = new AbortController();
    request<Transcript>(`/transcriptions/${recordId}`, undefined, controller.signal).then(r => { if (!controller.signal.aborted) {setRecord(r);} }).catch(e => { if(!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [recordId]);
  async function save() {
    if (!record || busy) return;
    setBusy(true);setError('');
    try { const r = await request<{hash: string}>('/transcriptions/auto-conversation', { transcription_id: record.id }); await onRefresh(); window.location.hash = `dialog/${r.hash}`; }
    catch(e) {setError(e instanceof Error ? e.message : 'Не удалось сохранить роли.');}
    finally {setBusy(false);}
  }
  const derived = data.conversations.find(c => c.transcription_id === recordId);
  const roles = record?.speaker_roles ?? {};
  const valid = record && !record.has_unassigned_speech && record.speaker_ids.length >= 2;
  return <>
    {recordId ? <a className="back-link" href="#audio"><Icon name="back" size={16}/>Все аудиозаписи</a> : null}
    <div className="page-heading"><div><h1>{recordId ? 'Расшифровка звонка' : 'Аудиозаписи'}</h1><p>{recordId ? 'Прослушайте запись и проверьте роли участников.' : 'Сохранённые записи и расшифровки разговоров.'}</p></div>{derived ? <a className="button primary" href={`#dialog/${derived.hash}`}>Открыть диалог<Icon name="arrow" size={16}/></a> : !recordId ? <button className="button primary" onClick={onImport}><Icon name="plus" size={18}/>Загрузить запись</button> : null}</div>
    {playbackWarning ? <div className="error-banner" role="alert">{playbackWarning}</div> : null}
    {error ? <div className="error-banner" role="alert">{error}</div> : null}
    {!recordId ? <div className="recording-list">{data.transcriptions.length ? data.transcriptions.map(t => { const source = data.conversations.find(c => c.hash === t.source_conversation_hash); const ready = data.conversations.some(c => c.transcription_id === t.id); return <a className="recording-row" key={t.id} href={`#audio/${t.id}`}><span className="channel-icon voice"><Icon name="volume"/></span><div><strong>{source?.conversation_id ?? t.display_name ?? 'Запись звонка'}</strong><p>{Math.floor(t.duration_seconds/60)} мин {Math.round(t.duration_seconds%60)} сек · {t.speaker_ids.length} говорящих</p></div><span className={`status ${ready ? 'success' : 'warning'}`}>{ready ? 'Диалог готов' : 'Готова к обработке'}</span><Icon name="arrow" size={18}/></a>; }) : <div className="empty-state"><Icon name="volume" size={32}/><h2>Пока нет расшифровок</h2><p>Загрузите запись или распознайте звонок из списка диалогов.</p></div>}</div> : record ? <section className="conversation-panel audio-review"><div className="audio-strip"><AudioPlayer onPlaybackStarted={() => setPlaybackWarning('')} audioRef={player} src={`/api/transcriptions/${record.id}/audio`} durationHint={record.duration_seconds}/></div><div className="role-assignment"><h2>Участники разговора</h2><p>Клиент и оператор определяются автоматически по всему разговору.</p>{record.has_unassigned_speech ? <p className="error-text">Есть фрагменты без говорящего. Для оценки нужна расшифровка с определёнными участниками.</p> : null}<button className="button primary" disabled={busy || !valid} onClick={()=>void save()}>{busy ? 'Сохраняем…' : 'Подготовить диалог'}</button></div><div className="messages">{record.turns.map(t=><article className="speech-fragment" key={t.id}><div className="message-meta"><strong>{roleName[roles[t.speaker ?? '']] ?? `Говорящий ${t.speaker ?? '?'}`}</strong><button className="timestamp-button" onClick={()=>{if(player.current){player.current.currentTime=t.start;void player.current.play().catch(()=>setPlaybackWarning('Нажмите воспроизведение в плеере.'));}}}>{Math.floor(t.start/60)}:{String(Math.floor(t.start%60)).padStart(2,'0')}</button></div><p>{t.text}</p></article>)}</div></section> : !error ? <div className="skeleton toolbar-skeleton" role="status" aria-label="Загружаем запись"/> : null}
  </>;
}
