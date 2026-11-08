import { useEffect, useRef, useState } from 'react';
import { request, type Transcript } from './client';
import { Icon } from './Icon';
import { AudioPlayer } from './AudioPlayer';
import { PasteConversation } from './PasteConversation';
import { useUnsavedChanges } from './drafts';

export function ImportDialog({ onClose, onDone }: { onClose: () => void; onDone: (hash: string | null, message: string) => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const [record, setRecord] = useState<Transcript | null>(null);
  const lock = useRef(false);
  const [mode, setMode] = useState('paste');
  const [pasteDirty, setPasteDirty] = useState(false);
  useUnsavedChanges(pasteDirty);
  function close() { if (!busy && (!pasteDirty || window.confirm('Закрыть без сохранения переписки?'))) onClose(); }
  const isAudio = file && !file.name.toLowerCase().endsWith('.json');
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  function selectFile(next: File | undefined) {
    setError('');
    if (!next) return;
    if (!/\.(json|mp3|wav|flac|m4a|mp4|ogg)$/i.test(next.name)) { setError('Выберите JSON с диалогами или аудиофайл MP3, WAV, FLAC, M4A, MP4, OGG.'); return; }
    const limit = next.name.toLowerCase().endsWith('.json') ? 2 : 25;
    if (next.size > limit * 1024 * 1024) { setError(`Файл больше ${limit} МБ. Выберите файл меньшего размера.`); return; }
    setFile(next);
  }
  async function submit() {
    if (lock.current || !file) return;
    if (pasteDirty && !window.confirm('Загрузить файл и закрыть несохранённую переписку?')) return;
    lock.current = true; setBusy(true); setError('');
    try {
      if (record) {
        const result = await request<{ hash: string }>('/transcriptions/auto-conversation', { transcription_id: record.id });
        await onDone(result.hash, 'Запись распознана. Диалог готов к оценке.');
      } else if (isAudio) {
        const form = new FormData(); form.append('file', file);
        const result = await request<Transcript>('/transcriptions/upload', form); setRecord(result);
        const prepared = await request<{ hash: string }>('/transcriptions/auto-conversation', { transcription_id: result.id });
        await onDone(prepared.hash, 'Запись распознана. Клиент и оператор определены автоматически.');
      } else {
        let body: unknown;
        try { body = JSON.parse(await file.text()); } catch { throw new Error('В файле некорректный JSON. Проверьте содержимое и загрузите его снова.'); }
        if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('Нужен объект диалога или набор в формате организаторов.');
        if ('data' in body) {
          const result = await request<{ count: number; conversation_hashes: string[] }>('/conversations/import', body);
          await onDone(result.count === 1 ? result.conversation_hashes[0] : null, `Импорт завершён. Диалогов в файле: ${result.count}.`);
        } else {
          const result = await request<{ hash: string }>('/conversations', body);
          await onDone(result.hash, 'Диалог загружен и готов к оценке.');
        }
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось завершить обработку. Расшифровка сохраняется отдельно, если распознавание уже завершилось.'); }
    finally { lock.current = false; setBusy(false); }
  }
  const canConfirm = record && !record.has_unassigned_speech && record.speaker_ids.length >= 2;
  return <dialog className="import-dialog" ref={dialog} aria-labelledby="import-title" onCancel={event => { event.preventDefault(); close(); }}>
    <div className="dialog-header"><div><h2 id="import-title">{record ? 'Расшифровка записи' : 'Загрузить диалоги'}</h2><p>{record ? 'Клиент и оператор определяются автоматически по разговору.' : 'Добавьте переписку или запись разговора.'}</p></div><button className="icon-button" aria-label="Закрыть загрузку" disabled={busy} onClick={close}><Icon name="close"/></button></div>
    {!record ? <div className="import-methods tabs" aria-label="Способ загрузки"><button aria-pressed={mode === 'paste'} className={mode === 'paste' ? 'selected' : ''} disabled={busy} onClick={() => setMode('paste')}>Вставить переписку</button><button aria-pressed={mode === 'file'} className={mode === 'file' ? 'selected' : ''} disabled={busy} onClick={() => setMode('file')}>Загрузить файл</button></div> : null}
    <div className="dialog-body">
      <div hidden={mode !== 'paste' || !!record}><PasteConversation onDone={onDone} onBusy={setBusy} onDirty={setPasteDirty}/></div>
      <div hidden={mode !== 'file' && !record}>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {record ? <div className="import-roles"><AudioPlayer src={`/api/transcriptions/${record.id}/audio`} durationHint={record.duration_seconds}/><div className="role-fields">{record.speaker_ids.map((id, index) => <div key={id}><strong>Участник {index + 1}</strong><p className="speaker-example">{record.turns.find(t => t.speaker === id)?.text}</p></div>)}</div>{record.speaker_ids.length < 2 ? <p className="error-text">Обнаружен один участник. Для оценки разговора нужна запись с клиентом и оператором.</p> : null}{record.has_unassigned_speech ? <p className="error-text">Не все говорящие определены. Сохранённая расшифровка требует дополнительной проверки.</p> : null}</div> : <>
        <div className={`upload-zone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`} onDragOver={e => { e.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); if (!busy) selectFile(e.dataTransfer.files[0]); }}>
          <span className="upload-symbol"><Icon name={file ? 'file' : 'upload'} size={29}/></span>
          <h3>{file ? file.name : 'Перетащите файл сюда'}</h3><p>{file ? `${(file.size / 1024 / 1024).toFixed(2)} МБ` : 'или выберите его на компьютере'}</p>
          <button className="button secondary" disabled={busy} onClick={() => fileInput.current?.click()}>{file ? 'Выбрать другой файл' : 'Выбрать файл'}</button>
          <input className="sr-only" tabIndex={-1} ref={fileInput} type="file" accept=".json,.mp3,.wav,.flac,.m4a,.mp4,.ogg" aria-label="Файл с диалогами" onChange={e => selectFile(e.target.files?.[0])}/>
        </div>
        <div className="upload-formats"><div><Icon name="chat" size={18}/><span><strong>Переписка</strong>Готовый набор JSON · до 2 МБ. Обычный текст можно вставить на соседней вкладке.</span></div><div><Icon name="phone" size={18}/><span><strong>Запись звонка</strong>MP3, WAV, FLAC, M4A, MP4, OGG · до 25 МБ и 15 минут</span></div></div>
      </>}
      {busy ? <p className="processing-text" role="status">{isAudio && !record ? 'Распознаём запись. Это может занять несколько минут.' : 'Сохраняем диалоги…'}</p> : null}
      </div>
    </div>
    <div className="dialog-footer"><button className="button secondary" disabled={busy} onClick={close}>{record ? 'Закрыть' : 'Отмена'}</button>{mode === 'file' || record ? <button className="button primary" disabled={busy || !file || !!record && !canConfirm} onClick={() => void submit()}>{busy ? 'Обрабатываем…' : record ? 'Подготовить диалог' : isAudio ? 'Распознать запись' : 'Загрузить'}</button> : null}</div>
  </dialog>;
}
