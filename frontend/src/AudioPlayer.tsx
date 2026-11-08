import { useRef, useState, type RefObject } from 'react';
import { Icon } from './Icon';

function timeLabel(seconds: number) {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
}

export function AudioPlayer({ src, durationHint = 0, audioRef, onPlaybackStarted }: {
  src: string; durationHint?: number; audioRef?: RefObject<HTMLAudioElement | null>; onPlaybackStarted?: () => void;
}) {
  // Key the inner player by source so every new recording starts with clean UI state.
  return <Player key={src} src={src} durationHint={durationHint} audioRef={audioRef} onPlaybackStarted={onPlaybackStarted}/>;
}

function Player({ src, durationHint, audioRef, onPlaybackStarted }: {
  src: string; durationHint: number; audioRef?: RefObject<HTMLAudioElement | null>; onPlaybackStarted?: () => void;
}) {
  const localRef = useRef<HTMLAudioElement>(null);
  const ref = audioRef ?? localRef;
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(durationHint);
  const [ready, setReady] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [muted, setMuted] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState('');
  function updateTime() {
    const audio = ref.current;
    if (!audio) return;
    setCurrent(audio.currentTime);
    if (Number.isFinite(audio.duration) && audio.duration > 0) setDuration(audio.duration);
  }
  async function toggle() {
    const audio = ref.current;
    if (!audio) return;
    if (!audio.paused) { audio.pause(); return; }
    setError('');
    try { await audio.play(); }
    catch (e) { if (!(e instanceof DOMException && e.name === 'AbortError')) setError('Не удалось воспроизвести запись. Попробуйте загрузить её снова.'); }
  }
  function seek(value: number) {
    if (!ref.current || !ready) return;
    ref.current.currentTime = Math.max(0, Math.min(duration, value));
    setCurrent(ref.current.currentTime);
  }
  return <div className="recording-player" role="group" aria-label="Аудиоплеер записи звонка">
    <audio ref={ref} src={src} preload="metadata" className="recording-media"
      onLoadedMetadata={() => { updateTime(); setReady(true); }} onDurationChange={updateTime}
      onTimeUpdate={updateTime} onSeeked={() => { updateTime(); setWaiting(false); }}
      onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
      onEnded={() => { setPlaying(false); updateTime(); }}
      onWaiting={() => setWaiting(true)} onPlaying={() => { setWaiting(false); setError(''); onPlaybackStarted?.(); }} onCanPlay={() => setWaiting(false)}
      onVolumeChange={() => setMuted(!!ref.current?.muted)} onRateChange={() => setSpeed(ref.current?.playbackRate ?? 1)}
      onError={() => { setReady(false); setPlaying(false); setWaiting(false); setError('Запись недоступна. Проверьте соединение и попробуйте снова.'); }}/>
    <div className="player-main">
      <button type="button" className="player-play" aria-label={playing ? 'Пауза' : 'Воспроизвести запись'} onClick={() => void toggle()}><Icon name={playing ? 'pause' : 'play'} size={22}/></button>
      <div className="player-timeline">
        <div className="player-caption"><span>{waiting && playing ? 'Загружаем аудио…' : 'Запись разговора'}</span><span className="player-time">{timeLabel(current)} <span>/ {duration > 0 ? timeLabel(duration) : '—:—'}</span></span></div>
        <div className="player-track"><progress max={duration || 1} value={Math.min(current, duration || 1)} aria-hidden="true"/><input type="range" min={0} max={duration || 1} step={0.1} value={Math.min(current, duration || 1)} disabled={!ready || duration <= 0} aria-label="Позиция в записи" aria-valuetext={`${timeLabel(current)} из ${timeLabel(duration)}`} onChange={e => seek(Number(e.target.value))}/></div>
      </div>
      <div className="player-tools">
        <button type="button" className="player-skip" disabled={!ready} aria-label="Назад на 10 секунд" onClick={() => seek(current - 10)}><Icon name="rewind" size={17}/><span>10</span></button>
        <label className="player-speed"><span className="sr-only">Скорость воспроизведения</span><select aria-label="Скорость воспроизведения" value={speed} onChange={e => { if (ref.current) ref.current.playbackRate = Number(e.target.value); }}>{[0.75, 1, 1.25, 1.5, 2].map(rate => <option key={rate} value={rate}>{rate.toLocaleString('ru-RU')}×</option>)}</select></label>
        <button type="button" className="player-mute" aria-label={muted ? 'Включить звук' : 'Выключить звук'} aria-pressed={muted} onClick={() => { if (ref.current) ref.current.muted = !ref.current.muted; }}><Icon name={muted ? 'muted' : 'volume'} size={19}/></button>
      </div>
    </div>
    {error ? <div className="player-error" role="alert"><span>{error}</span><button type="button" className="button secondary" onClick={() => { setError(''); setReady(false); setWaiting(false); ref.current?.load(); }}>Загрузить снова</button></div> : null}
  </div>;
}
