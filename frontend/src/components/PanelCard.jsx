import { assetUrl } from '../api.js'
import DialogueBubble, { defaultBubblePosition } from './DialogueBubble.jsx'
import { EmotionChip, scoreTone } from './ui.jsx'

const SHOT_LABELS = {
  establishing_wide: 'establishing',
  wide: 'wide',
  medium: 'medium',
  medium_close: 'medium close',
  close_up: 'close-up',
  extreme_close_up: 'extreme close-up',
  over_the_shoulder: 'OTS',
  low_angle: 'low angle',
  high_angle: 'high angle',
  bird_eye: "bird's eye",
  dutch_angle: 'dutch angle',
}

function lettering(panel) {
  const lines = [...(panel.dialogue || [])]
  if (panel.narration) lines.unshift({ speaker: 'Narrator', text: panel.narration, kind: 'narration' })
  if (panel.sfx) lines.push({ speaker: '', text: panel.sfx, kind: 'sfx' })
  return lines
}

/** A single panel as it appears on the page. Click to edit it. */
export default function PanelCard({ panel, selected = false, onSelect, showMeta = true, className = '' }) {
  if (!panel) return null
  const lines = lettering(panel)

  return (
    <figure
      className={[
        'group panel-art cursor-pointer transition',
        selected ? 'ring-4 ring-accent ring-offset-2 ring-offset-ink-950' : 'hover:border-accent/60',
        className,
      ].join(' ')}
      onClick={() => onSelect?.(panel)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onSelect?.(panel)
        }
      }}
      tabIndex={0}
      role="button"
      aria-label={`Panel ${panel.panel_id}${panel.scene_summary ? `: ${panel.scene_summary}` : ''}`}
    >
      {panel.image_url ? (
        <img
          src={assetUrl(panel.image_url)}
          alt={panel.scene_summary || `Panel ${panel.panel_id}`}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      ) : (
        <div className="flex h-full min-h-[140px] w-full items-center justify-center bg-ink-800 text-xs text-slate-500">
          not rendered yet
        </div>
      )}

      {lines.length ? (
        <div className="pointer-events-none absolute inset-0 flex flex-col justify-between gap-2 p-2">
          <div className="flex flex-col items-start gap-1.5">
            {lines
              .filter((line) => line.kind === 'narration' || line.kind === 'caption')
              .map((line, index) => (
                <DialogueBubble key={`narration-${index}`} line={line} compact />
              ))}
          </div>
          {lines
            .filter((line) => line.kind !== 'narration' && line.kind !== 'caption')
            .slice(0, 3)
            .map((line, index, visible) => {
              const position = line.position || defaultBubblePosition(index, visible.length)
              return (
                <div
                  key={`line-${index}`}
                  className="absolute max-w-[62%] -translate-x-1/2 -translate-y-1/2"
                  style={{ left: `${position.x * 100}%`, top: `${position.y * 100}%` }}
                >
                  <DialogueBubble line={line} compact />
                </div>
              )
            })}
        </div>
      ) : null}

      {showMeta ? (
        <figcaption className="pointer-events-none absolute left-1.5 top-1.5 flex flex-wrap items-center gap-1.5 opacity-0 transition group-hover:opacity-100">
          <span className="rounded bg-ink-950/85 px-1.5 py-0.5 text-[10px] font-semibold text-white">
            {panel.panel_id}
          </span>
          {panel.camera ? (
            <span className="rounded bg-ink-950/85 px-1.5 py-0.5 text-[10px] text-slate-200">
              {SHOT_LABELS[panel.camera.shot] || panel.camera.shot}
            </span>
          ) : null}
          <EmotionChip emotion={panel.emotion} />
          {panel.continuity_score !== null && panel.continuity_score !== undefined ? (
            <span className={`rounded bg-ink-950/85 px-1.5 py-0.5 text-[10px] ${scoreTone(panel.continuity_score)}`}>
              continuity {panel.continuity_score.toFixed(2)}
            </span>
          ) : null}
          {panel.is_edited ? (
            <span className="rounded bg-accent/90 px-1.5 py-0.5 text-[10px] font-semibold text-ink-950">
              edited
            </span>
          ) : null}
          {panel.regenerations > 0 ? (
            <span className="rounded bg-ink-950/85 px-1.5 py-0.5 text-[10px] text-amber-200">
              ×{panel.regenerations + 1}
            </span>
          ) : null}
        </figcaption>
      ) : null}
    </figure>
  )
}

export { SHOT_LABELS, lettering }
