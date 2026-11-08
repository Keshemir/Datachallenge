export type Criterion = {
  id: string; title: string; section: string; evidence_policy: 'any' | 'operator' | 'first_operator'; kind: 'binary' | 'scale' | 'flag'; weight: number;
  allow_na: boolean; instructions: string; na_condition: string | null;
  scale: { value: number; description: string }[];
};
export type ChecklistRecord = { hash: string; checklist: { id: string; version: number; title: string; instructions: string; criteria: Criterion[] } };
export type Conversation = { hash: string; conversation_id: string; display_name: string; language: string; channel: string; message_count: number; has_audio: boolean; preview: string; transcription_id: string | null };
export type Message = { message_id: string; speaker: string; timestamp: string | null; text: string };
export type ConversationDetail = { hash: string; conversation: { conversation_id: string; language: string; channel: string; transcript: Message[] } };
export type Evaluation = { id: string; conversation_hash: string; checklist_hash: string; total_score: number | null; created_at: string; flagged_criteria: string[] };
export type CriterionResult = { criterion_id: string; title: string; kind: string; weight: number; earned_weight: number | null; contribution: number | null; flagged: boolean; evidence: Message[]; judgment: { decision: string; score: number | null; explanation: string; na_reason: string | null; evidence_message_ids: string[] } };
export type FullEvaluation = { id: string; checklist_hash: string; created_at: string; result: { total_score: number | null; flagged_criteria: string[]; criteria: CriterionResult[] } };
export type Turn = { id: string; speaker: string | null; start: number; end: number; text: string };
export type Transcript = { speaker_roles?: Record<string, string>; id: string; display_name: string; source_conversation_hash: string | null; duration_seconds: number; speaker_ids: string[]; has_unassigned_speech: boolean; requested_language?: string; detected_language?: string; turns: Turn[] };
export type Check = { id: string; evaluation_id: string; disagreements: { criterion_id: string; evaluation_choice: string; decision_choice: string }[] };
export type Appeal = { id: string; evaluation_id: string; criterion_id: string; criterion_title: string; conversation_hash: string; author: string; reason: string; created_at: string; status: 'submitted' | 'in_review' | 'accepted' | 'rejected'; events: { status: string; at: string; actor: string; note: string; review_id?: string }[] };
export type QAReview = { id: string; evaluation_id: string; appeal_id: string; created_at: string; reviewer: string; result: FullEvaluation['result'] };
export type Data = { conversations: Conversation[]; evaluations: Evaluation[]; transcriptions: Transcript[]; checks: Check[]; checklists: ChecklistRecord[]; appeals: Appeal[]; reviews: QAReview[] };

let csrfToken: string | null = null;
export function setCsrfToken(value: string | null) { csrfToken = value; }

export async function request<T>(path: string, body?: object | FormData, signal?: AbortSignal): Promise<T> {
  const form = body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { signal, credentials: 'same-origin', method: body ? 'POST' : 'GET', headers: body ? { ...(!form ? { 'Content-Type': 'application/json' } : {}), 'X-CQA-Request': '1', ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}) } : undefined, body: body ? (form ? body : JSON.stringify(body)) : undefined });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error('Нет соединения с сервером. Проверьте подключение и попробуйте снова.');
  }
  if (!response.ok) {
    if (path === '/transcriptions/auto-conversation' && response.status === 502) throw new Error('Расшифровка сохранена. Не удалось надёжно определить клиента и оператора. Повторите обработку или загрузите более полный разговор.');
    if (path === '/transcriptions/auto-conversation' && response.status === 422) throw new Error('Для оценки нужен разговор с двумя различимыми участниками: клиентом и оператором.');
    if (response.status === 401) {
      if (path !== '/auth/login') window.dispatchEvent(new Event('cqa-session-expired'));
      throw new Error(path === '/auth/login' ? 'Неверный пароль.' : 'Сессия завершена. Войдите снова.');
    }
    if (response.status === 403) throw new Error('Запрос отклонён защитой. Обновите страницу и войдите снова.');
    if (response.status === 413) throw new Error('Файл слишком большой. Максимум: 2 МБ для JSON и 25 МБ для аудио.');
    if (response.status === 429) throw new Error('Слишком много запросов. Подождите несколько минут и повторите.');
    if (response.status === 422) throw new Error('Не удалось прочитать данные. Проверьте формат файла и заполненные поля.');
    if (response.status === 404) throw new Error('Диалог или результат не найден. Обновите список.');
    if (response.status === 409) throw new Error('Данные уже изменились или такая запись существует. Обновите список и повторите действие.');
    if (response.status === 503) throw new Error('Оценка временно недоступна. Обратитесь к администратору.');
    if (response.status === 502) throw new Error('Не удалось завершить обработку. Результат не сохранён. Попробуйте ещё раз.');
    throw new Error('Не удалось выполнить действие. Попробуйте ещё раз.');
  }
  return response.json() as Promise<T>;
}
export async function loadData(signal?: AbortSignal): Promise<Data> {
  const [conversations, evaluations, transcriptions, checks, checklists, appeals, reviews] = await Promise.all([
    request<Conversation[]>('/conversations', undefined, signal), request<Evaluation[]>('/evaluations', undefined, signal),
    request<Transcript[]>('/transcriptions', undefined, signal), request<Check[]>('/decision-checks', undefined, signal), request<ChecklistRecord[]>('/checklists', undefined, signal),
    request<Appeal[]>('/appeals', undefined, signal), request<QAReview[]>('/qa-reviews', undefined, signal),
  ]);
  return { conversations, evaluations, transcriptions, checks, checklists, appeals, reviews };
}
export const languageName: Record<string, string> = { RU: 'Русский', KZ: 'Қазақша', EN: 'English' };
export const roleName: Record<string, string> = { operator: 'Оператор', client: 'Клиент', bot: 'Автоответчик', system: 'Система' };
export const scoreText = (value: number | null | undefined) => value == null ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value);
export const choiceText = (value: string) => ({ yes: 'Да', no: 'Нет', na: 'Не применимо' }[value] ?? value.replace('score_', ''));
export const dialogueName = (c: Conversation) => c.display_name || (c.transcription_id ? 'Расшифровка звонка' : c.conversation_id);
