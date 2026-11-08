import type { CSSProperties } from 'react';
const paths = {
  play: <path d="m9 5 11 7-11 7V5Z" fill="currentColor" stroke="none"/>,
  pause: <><path d="M8 5v14M16 5v14" strokeWidth="4"/></>,
  rewind: <><path d="M4 8a8 8 0 1 1-1 7M4 3v5h5"/></>,
  muted: <><path d="m11 4-6 5H2v6h3l6 5V4ZM16 9l6 6m0-6-6 6"/></>,
  chat: <><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H5l-3 2V11.5A8.5 8.5 0 0 1 10.5 3h2a8.5 8.5 0 0 1 8.5 8.5Z"/><path d="M7 10h9M7 14h6"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  checklist: <><rect x="5" y="4" width="15" height="17" rx="2"/><path d="M9 3h7v4H9zM9 11h7M9 16h7"/></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  arrow: <path d="m9 5 7 7-7 7"/>,
  back: <path d="m14 5-7 7 7 7"/>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M4 15v5h16v-5"/></>,
  upload: <><path d="M12 16V4m-5 5 5-5 5 5M4 16v4h16v-4"/></>,
  phone: <path d="M8 3H4a1 1 0 0 0-1 1c0 9.4 7.6 17 17 17a1 1 0 0 0 1-1v-4l-5-2-2 3a14 14 0 0 1-7-7l3-2-2-5Z"/>,
  flag: <path d="M5 21V3m0 0h13l-3 5 3 5H5"/>,
  close: <path d="m6 6 12 12M6 18 18 6"/>,
  refresh: <path d="M20 7a9 9 0 1 0 1 8M20 2v6h-6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/></>,
  file: <><path d="M14 3H5v18h14V8l-5-5Z"/><path d="M14 3v5h5M8 12h8M8 16h6"/></>,
  volume: <path d="m11 4-6 5H2v6h3l6 5V4ZM16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>,
  chevron: <path d="m6 9 6 6 6-6"/>,
};
export type IconName = keyof typeof paths;
export function Icon({ name, size = 20, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>{paths[name]}</svg>;
}
