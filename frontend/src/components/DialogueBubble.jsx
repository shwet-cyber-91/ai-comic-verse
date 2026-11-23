/**
 * One balloon of lettering.
 *
 * The kind comes straight from the pipeline's DialogueLine, so a thought, a
 * shout and a caption look different on screen and in the export.
 */

const STYLES = {
  speech: {
    bubble: 'rounded-[46%] bg-white text-ink-950 border-2 border-ink-950 shadow-[0_3px_0_rgba(16,19,31,.18)]',
    tail: true,
    transform: '',
  },
  thought: {
    bubble: 'rounded-[46%] border-2 border-dashed border-ink-950/75 bg-white/95 text-ink-950',
    tail: false,
    transform: 'italic',
  },
  shout: {
    bubble: 'rounded-[28%] bg-accent text-white border-2 border-ink-950',
    tail: true,
    transform: 'uppercase tracking-tight font-extrabold',
  },
  whisper: {
    bubble: 'rounded-[46%] border-2 border-dashed border-ink-950/70 bg-white/90 text-ink-900',
    tail: true,
    transform: 'italic text-[0.95em]',
  },
  narration: {
    bubble: 'rounded-md border border-black/20 bg-[#fdf6e3] text-ink-950',
    tail: false,
    transform: '',
  },
  caption: {
    bubble: 'rounded-md border border-black/20 bg-[#fdf6e3] text-ink-950',
    tail: false,
    transform: '',
  },
  sfx: {
    bubble: 'bg-transparent text-white',
    tail: false,
    transform: 'font-display text-2xl uppercase',
  },
}

export default function DialogueBubble({ line, compact = false }) {
  const style = STYLES[line.kind] || STYLES.speech
  const isNarration = line.kind === 'narration' || line.kind === 'caption'

  return (
    <div className={compact ? 'max-w-full' : 'max-w-[min(90%,22rem)]'}>
      <div
        className={[
          'relative px-4 py-2.5 text-center text-[13px] leading-snug shadow-md',
          style.bubble,
          style.transform,
          compact ? 'text-[11px]' : '',
        ].join(' ')}
        style={
          line.kind === 'shout'
            ? { clipPath: 'polygon(2% 8%, 98% 0%, 100% 88%, 4% 100%)' }
            : undefined
        }
      >
        {!isNarration && line.kind !== 'sfx' && line.speaker ? (
          <span className="mr-1.5 font-bold uppercase tracking-wide opacity-70">
            {line.speaker}:
          </span>
        ) : null}
        <span>{line.text}</span>
        {style.tail ? (
          <span
            className="absolute -bottom-1.5 left-6 h-3 w-3 rotate-45 border-b border-r border-black/15 bg-inherit"
            aria-hidden="true"
          />
        ) : null}
      </div>
    </div>
  )
}

export function defaultBubblePosition(index, total) {
  return {
    x: total === 1 ? 0.5 : index % 2 === 0 ? 0.32 : 0.68,
    y: Math.min(0.2 + Math.floor(index / 2) * 0.24, 0.8),
  }
}
