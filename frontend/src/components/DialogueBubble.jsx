/**
 * One balloon of lettering.
 *
 * The kind comes straight from the pipeline's DialogueLine, so a thought, a
 * shout and a caption look different on screen and in the export.
 */

const STYLES = {
  speech: {
    bubble: 'rounded-[18px] bg-white text-ink-950 border border-black/15',
    tail: true,
    transform: '',
  },
  thought: {
    bubble: 'rounded-[24px] border-2 border-dashed border-white/70 bg-white/95 text-ink-950',
    tail: false,
    transform: 'italic',
  },
  shout: {
    bubble: 'bg-accent text-ink-950 border-2 border-ink-950',
    tail: true,
    transform: 'uppercase tracking-tight font-extrabold',
  },
  whisper: {
    bubble: 'rounded-[18px] border border-dashed border-white/60 bg-white/80 text-ink-900',
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
          'relative px-3 py-2 text-[13px] leading-snug shadow-md',
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
