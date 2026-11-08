import { useState } from 'react';
import type { ChecklistRecord } from './client';
import { Icon } from './Icon';
import { ChecklistEditor } from './ChecklistEditor';

export function ChecklistView({ records, onRefresh, onNotice }: { records: ChecklistRecord[]; onRefresh: () => Promise<void>; onNotice: (message: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState(records[0]?.hash ?? '');
  const record = records.find(r => r.hash === selected);
  if (editing && record) return <ChecklistEditor source={record} records={records} onCancel={() => setEditing(false)} onSaved={async hash => { await onRefresh(); setSelected(hash); setEditing(false); onNotice('Новая версия сохранена. Выберите её в диалоге, чтобы запустить оценку по новым правилам.'); }}/>;
  return <>
    {record ? <div className="checklist-actions"><button className="button primary" onClick={() => setEditing(true)}>Редактировать чек-лист</button></div> : null}
    <div className="page-heading"><div><h1>Чек-лист</h1><p>Единые правила оценки для каждого обращения.</p></div>{records.length > 1 ? <select aria-label="Версия чек-листа" value={selected} onChange={e => setSelected(e.target.value)}>{records.map(r => <option key={r.hash} value={r.hash}>{r.checklist.title} · v{r.checklist.version}</option>)}</select> : null}</div>
    {record ? <div className="checklist-layout"><section className="checklist-main"><div className="checklist-heading"><Icon name="checklist" size={25}/><div><h2>{record.checklist.title}</h2><p>Версия {record.checklist.version} · {record.checklist.criteria.length} критериев</p></div></div>{record.checklist.criteria.map((c, i) => <details className="rule" key={c.id}><summary><span className="criterion-number">{String(i + 1).padStart(2, '0')}</span><div><strong>{c.title}</strong><span>{c.kind === 'flag' ? 'Отдельная отметка' : c.kind === 'scale' ? `Шкала: ${c.scale.map(s => s.value).join(' / ')}` : 'Да / Нет'}{c.allow_na ? ' / N/A' : ''}</span></div><span className="rule-weight">{c.kind === 'flag' ? 'Флаг' : `Вес ${c.weight}`}</span><Icon name="chevron" size={18}/></summary><div className="rule-content"><p>{c.instructions}</p>{c.allow_na ? <div className="na-explanation"><strong>Когда ставить N/A</strong><p>{c.na_condition}</p></div> : null}{c.scale.length ? <dl className="scale-levels">{c.scale.map(s => <div key={s.value}><dt>{s.value}</dt><dd>{s.description}</dd></div>)}</dl> : null}</div></details>)}</section><aside className="checklist-note"><Icon name="shield" size={25}/><h3>Как складывается оценка</h3><p>Итог учитывает результат и вес каждого применимого критерия.</p><div><strong>Если критерий не применим</strong><p>Он исключается из расчёта, а веса остальных перераспределяются.</p></div><div><strong>Грубые ошибки</strong><p>Отмечаются отдельно и не обнуляют итоговый балл.</p></div><div><strong>Обоснование решения</strong><p>В карточке оценки можно перейти к репликам, подтверждающим ответ.</p></div></aside></div> : <div className="empty-state"><h2>Чек-лист пока не добавлен</h2><p>Для начала оценки потребуется чек-лист.</p></div>}
  </>;
}
