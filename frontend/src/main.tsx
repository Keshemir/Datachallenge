import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { SessionGate } from './SessionGate';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode><SessionGate /></StrictMode>,
);
