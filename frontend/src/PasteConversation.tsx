import { useRef, useState } from 'react';
import { request, type ChecklistRecord } from './client';

type ParsedText = { language: 'RU' | 'KZ' | 'EN'; turns: { speaker: string; text: string; timestamp: string; needs_review?: boolean }[] };
type Attempt = { conversationHash?: string; checklistHash?: string; evaluationId?: string; title: string };

export function PasteConversation({ onDone, onBusy, onDirty }: {
  onDone: (hash: string | null, message: string) => Promise<void>;
  onBusy: (busy: boolean) => void; onDirty: (dirty: boolean) => void;
}) {
  const [text, setText] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState('');
  const [error, setError] = useState('');
  const lock = useRef(false);
  const attempt = useRef<Attempt | null>(null);

  function edit() { attempt.current = null; setError(''); onDirty(true); }
  async function evaluate(event: React.FormEvent) {
    event.preventDefault();
    if (lock.current || !text.trim()) return;
    lock.current = true; setBusy(true); onBusy(true); setError('');
    const current: Attempt = attempt.current ?? { title: name.trim() || `Переписка ${new Date().toLocaleString('ru-RU', { timeZone: 'Asia/Qyzylorda' })}` };
    attempt.current = current;
    try {
      if (!current.conversationHash) {
        setStage('Готовим диалог…');
        const [parsed, checklists] = await Promise.all([
          request<ParsedText>('/conversations/parse-text', { text }),
          request<ChecklistRecord[]>('/checklists'),
        ]);
        const candidates = checklists.filter(c => c.checklist.id === 'freedom-chat');
        const rubric = [...(candidates.length ? candidates : checklists)].sort((a, b) => b.checklist.version - a.checklist.version)[0];
        if (!rubric) throw new Error('Для оценки нужен чек-лист. Добавьте его в разделе «Чек-лист».');
        if (!parsed.turns.length || parsed.turns.some(t => !t.speaker || t.needs_review) || !parsed.turns.some(t => t.speaker === 'operator')) {
          throw new Error('Не удалось однозначно разобрать разговор. Вставьте более полный текст, начиная каждую реплику с новой строки.');
        }
        const saved = await request<{ hash: string }>('/conversations', {
          conversation_id: current.title, channel: 'agent chat', language: parsed.language,
          transcript: parsed.turns.map(t => ({ speaker: t.speaker, text: t.text, timestamp: t.timestamp || 'Не указано' })),
        });
        current.conversationHash = saved.hash;
        current.checklistHash = rubric.hash;
      }
      if (!current.evaluationId) {
        setStage('Оцениваем диалог…');
        const result = await request<{ id: string }>('/evaluations', {
          conversation_hash: current.conversationHash, checklist_hash: current.checklistHash,
        });
        current.evaluationId = result.id;
      }
      setStage('Открываем результат…');
      onDirty(false);
      await onDone(current.conversationHash!, 'Диалог оценён. Результат справа.');
    } catch (e) {
      onDirty(true);
      setError(current.conversationHash && !current.evaluationId
        ? 'Диалог сохранён, но оценку получить не удалось. Нажмите «Оценить диалог» ещё раз.'
        : e instanceof Error ? e.message : 'Не удалось оценить диалог. Текст сохранён в форме, попробуйте снова.');
    } finally { lock.current = false; setBusy(false); onBusy(false); setStage(''); }
  }

  return <form className="paste-conversation" onSubmit={e => void evaluate(e)}>
    <fieldset disabled={busy} className="editor-fields">
      <label className="form-field">Название диалога (необязательно)<input aria-label="Название диалога" maxLength={120} value={name} onChange={e => { setName(e.target.value); edit(); }} placeholder="Например, вопрос по тарифу"/></label>
      <label className="form-field">Текст переписки<textarea aria-label="Текст переписки" required rows={10} maxLength={50000} value={text} onChange={e => { setText(e.target.value); edit(); }} placeholder={'Здравствуйте! Где найти отчёт?\nДобрый день! Откройте раздел «Документы».\nСпасибо, нашёл.'}/></label>
      <p className="field-help">Вставьте разговор целиком. Каждую реплику начинайте с новой строки.</p>
      {error ? <div className="error-banner" role="alert">{error}</div> : null}
      <button className="button primary full-width" disabled={!text.trim()}>{busy ? stage || 'Обрабатываем…' : 'Оценить диалог'}</button>
      {busy ? <p className="processing-text" role="status">{stage} Это может занять несколько минут.</p> : null}
    </fieldset>
  </form>;
}
