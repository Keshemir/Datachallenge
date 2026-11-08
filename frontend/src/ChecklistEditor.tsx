import { useRef, useState } from 'react';
import { request, type ChecklistRecord, type Criterion } from './client';
import { confirmDiscard, useUnsavedChanges } from './drafts';

export function ChecklistEditor({ source, records, onSaved, onCancel }: {
  source: ChecklistRecord; records: ChecklistRecord[];
  onSaved: (hash: string) => Promise<void>; onCancel: () => void;
}) {
  const [draft, setDraft] = useState(() => structuredClone(source.checklist));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const guard = useRef(false);
  const version = Math.max(...records.filter(r => r.checklist.id === draft.id).map(r => r.checklist.version)) + 1;
  useUnsavedChanges(JSON.stringify(draft) !== JSON.stringify(source.checklist));
  function update(index: number, patch: Partial<Criterion>) {
    setDraft(d => ({ ...d, criteria: d.criteria.map((c, i) => i === index ? { ...c, ...patch } : c) }));
  }
  function changeKind(index: number, kind: Criterion['kind']) {
    update(index, { kind, weight: kind === 'flag' ? 0 : draft.criteria[index].weight || 10,
      ...(kind === 'flag' ? { allow_na: false, na_condition: null } : {}),
      scale: kind === 'scale' ? [{ value: 0, description: 'Условие не выполнено' }, { value: 1, description: 'Условие выполнено' }] : [],
    });
  }
  async function save(e: React.FormEvent) {
    e.preventDefault(); if (guard.current) return;
    setError('');
    for (const c of draft.criteria) {
      if (!c.title.trim() || !c.instructions.trim() || !c.section.trim()) { setError('Заполните название, раздел и правило каждого критерия.'); return; }
      if (c.allow_na && !c.na_condition?.trim()) { setError(`Укажите условие N/A для «${c.title}».`); return; }
      if (c.kind === 'scale' && (c.scale.length < 2 || !c.scale.some(s => s.value === 0) || !c.scale.some(s => s.value > 0) || new Set(c.scale.map(s => s.value)).size !== c.scale.length)) {
        setError(`Шкала «${c.title}»: нужны разные значения, включая 0 и положительный максимум.`); return;
      }
    }
    guard.current = true; setBusy(true);
    try {
      const result = await request<ChecklistRecord>('/checklists', { ...draft, version, criteria: draft.criteria.map(c => ({ ...c, scale: [...c.scale].sort((a, b) => a.value - b.value) })) });
      await onSaved(result.hash);
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сохранить чек-лист.'); }
    finally { guard.current = false; setBusy(false); }
  }
  return <form className="checklist-editor" onSubmit={e => void save(e)} onInvalidCapture={e => { const details = (e.target as HTMLElement).closest("details"); if (details) details.open = true; }}>
    <div className="page-heading"><div><h1>Редактирование чек-листа</h1><p>Новая версия {version}. Сохранённые оценки останутся связаны со своими правилами.</p></div></div>
    {error ? <div className="error-banner" role="alert">{error}</div> : null}
    <fieldset disabled={busy} className="editor-fields">
      <section className="editor-intro"><label className="form-field">Название<input required maxLength={200} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })}/></label>
        <label className="form-field">Общие правила оценки<textarea required rows={4} maxLength={20000} value={draft.instructions} onChange={e => setDraft({ ...draft, instructions: e.target.value })}/></label></section>
      {draft.criteria.map((c, i) => <details className="editor-criterion" key={c.id} open={undefined}>
        <summary><strong>{i + 1}. {c.title || 'Новый критерий'}</strong><span>{c.kind === 'flag' ? 'Грубая ошибка' : `Вес ${c.weight}`}</span></summary>
        <div className="editor-criterion-body">
          <div className="form-grid"><label className="form-field">Название критерия<input required maxLength={200} value={c.title} onChange={e => update(i, { title: e.target.value })}/></label>
            <label className="form-field">Раздел<input required maxLength={200} value={c.section} onChange={e => update(i, { section: e.target.value })}/></label>
            <label className="form-field">Тип ответа<select value={c.kind} onChange={e => changeKind(i, e.target.value as Criterion['kind'])}><option value="binary">Да / Нет</option><option value="scale">Шкала</option><option value="flag">Грубая ошибка — отдельный флаг</option></select></label>
            <label className="form-field">Вес<input type="number" required min={c.kind === 'flag' ? 0 : 0.01} step="any" disabled={c.kind === 'flag'} value={c.weight} onChange={e => update(i, { weight: Number(e.target.value) })}/></label></div>
          <label className="form-field">Правило оценки<textarea required rows={4} maxLength={20000} value={c.instructions} onChange={e => update(i, { instructions: e.target.value })}/></label>
          <label className="form-field">Кто должен подтвердить выполнение<select value={c.evidence_policy} onChange={e => update(i, { evidence_policy: e.target.value as Criterion['evidence_policy'] })}><option value="any">Любая реплика с подтверждением</option><option value="operator">Обязательно реплика оператора</option><option value="first_operator">Первый ответ оператора</option></select></label>
          {c.kind !== 'flag' ? <><label className="check-control"><input type="checkbox" checked={c.allow_na} onChange={e => update(i, { allow_na: e.target.checked, na_condition: e.target.checked ? '' : null })}/>Разрешить N/A</label>{c.allow_na ? <label className="form-field">Когда критерий не применим<textarea required rows={2} value={c.na_condition ?? ''} maxLength={20000} onChange={e => update(i, { na_condition: e.target.value })}/></label> : null}</> : <p className="field-help">Флаг отмечает нарушение отдельно и не обнуляет итоговую оценку.</p>}
          {c.kind === 'scale' ? <div className="scale-editor"><h3>Ступени шкалы</h3>{c.scale.map((s, n) => <div className="scale-editor-row" key={n}><label className="form-field">Баллы<input aria-label={`Баллы ступени ${n + 1}`} type="number" min={0} step="any" required value={s.value} onChange={e => update(i, { scale: c.scale.map((v, j) => j === n ? { ...v, value: Number(e.target.value) } : v) })}/></label><label className="form-field">Условие<input required aria-label={`Условие ступени ${n + 1}`} value={s.description} maxLength={20000} onChange={e => update(i, { scale: c.scale.map((v, j) => j === n ? { ...v, description: e.target.value } : v) })}/></label><button type="button" className="button secondary" disabled={c.scale.length <= 2} aria-label={`Удалить ступень ${n + 1}`} onClick={() => update(i, { scale: c.scale.filter((_, j) => j !== n) })}>Удалить</button></div>)}<button type="button" className="button secondary" onClick={() => update(i, { scale: [...c.scale, { value: Math.max(...c.scale.map(s => s.value)) + 1, description: '' }] })}>Добавить ступень</button></div> : null}
          <button type="button" className="button secondary remove-criterion" disabled={draft.criteria.length <= 1} onClick={() => { if (window.confirm(`Удалить «${c.title}» из новой версии?`)) setDraft({ ...draft, criteria: draft.criteria.filter((_, j) => i !== j) }); }}>Удалить критерий</button>
        </div></details>)}
      <button type="button" className="button secondary" disabled={draft.criteria.length >= 100} onClick={() => setDraft({ ...draft, criteria: [...draft.criteria, { id: `criterion-${crypto.randomUUID()}`, title: 'Новый критерий', section: draft.criteria[0]?.section || 'Качество', kind: 'binary', weight: 10, instructions: '', allow_na: false, na_condition: null, scale: [], evidence_policy: 'operator' }] })}>Добавить критерий</button>
      <div className="editor-save"><p>Сумма весов: <strong>{draft.criteria.reduce((n, c) => n + c.weight, 0).toLocaleString('ru-RU')}</strong>. Итог нормализуется до 100 с учётом N/A.</p><div><button type="button" className="button secondary" onClick={() => { if (confirmDiscard()) onCancel(); }}>Отменить</button><button type="submit" className="button primary">{busy ? 'Сохраняем…' : `Сохранить версию ${version}`}</button></div></div>
    </fieldset>
  </form>;
}
