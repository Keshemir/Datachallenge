import { useLayoutEffect, useRef } from 'react';

// Track only dirty-state presence; do not persist texts or credentials in browser storage.
const dirtyForms = new Set<symbol>();
export const hasUnsavedChanges = () => dirtyForms.size > 0;
export function confirmDiscard() {
  return !hasUnsavedChanges() || window.confirm('Есть несохранённые изменения. Выйти и потерять их?');
}
export function useUnsavedChanges(dirty: boolean) {
  const id = useRef(Symbol('draft'));
  useLayoutEffect(() => {
    const key = id.current;
    if (dirty) dirtyForms.add(key); else dirtyForms.delete(key);
    return () => { dirtyForms.delete(key); };
  }, [dirty]);
}
