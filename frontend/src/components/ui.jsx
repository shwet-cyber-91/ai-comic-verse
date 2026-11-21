/** Small shared UI pieces. No component library - just Tailwind. */

export function Spinner({ className = 'h-5 w-5' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

const TONES = {
  info: 'border-sky-400/30 bg-sky-400/10 text-sky-100',
  success: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
  warning: 'border-amber-400/30 bg-amber-400/10 text-amber-100',
  error: 'border-rose-400/30 bg-rose-400/10 text-rose-100',
}

export function Banner({ tone = 'info', children, className = '', onDismiss }) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${TONES[tone]} ${className}`}
    >
      <div className="flex-1 leading-relaxed">{children}</div>
      {onDismiss ? (
        <button type="button" onClick={onDismiss} className="text-current/70 hover:text-current" aria-label="Dismiss">
          ✕
        </button>
      ) : null}
    </div>
  )
}

export function Card({ title, subtitle, actions, children, className = '', bodyClassName = 'p-5' }) {
  return (
    <section className={`card ${className}`}>
      {title || actions ? (
        <header className="flex flex-wrap items-center gap-3 border-b border-white/10 px-5 py-4">
          <div className="min-w-0">
            {title ? <h2 className="truncate text-base font-semibold text-white">{title}</h2> : null}
            {subtitle ? <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p> : null}
          </div>
          {actions ? <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

export function Field({ label, hint, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      {label ? <span className="label">{label}</span> : null}
      {children}
      {hint ? <span className="mt-1.5 block text-xs text-slate-500">{hint}</span> : null}
    </label>
  )
}

export function ProgressBar({ value = 0, className = '' }) {
  const percent = Math.max(0, Math.min(100, Math.round(value * 100)))
  return (
    <div className={`h-2 overflow-hidden rounded-full bg-white/10 ${className}`}>
      <div
        className="h-full rounded-full bg-gradient-to-r from-accent-deep via-accent to-accent-soft transition-all duration-500"
        style={{ width: `${percent}%` }}
      />
    </div>
  )
}

export function EmptyState({ icon = '✨', title, children, action }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-white/15 px-6 py-12 text-center">
      <span className="text-3xl" aria-hidden="true">
        {icon}
      </span>
      <h3 className="text-base font-semibold text-white">{title}</h3>
      {children ? <p className="max-w-md text-sm text-slate-400">{children}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}

export function Skeleton({ className = 'h-4 w-full' }) {
  return (
    <div
      className={`animate-shimmer rounded-md bg-gradient-to-r from-white/5 via-white/10 to-white/5 ${className}`}
      style={{ backgroundSize: '1000px 100%' }}
    />
  )
}

export function Drawer({ open, title, onClose, children, footer }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative ml-auto flex h-full w-full max-w-md flex-col border-l border-white/10 bg-ink-900 shadow-comic animate-fade-up"
      >
        <header className="flex items-center gap-3 border-b border-white/10 px-5 py-4">
          <h2 className="text-base font-semibold text-white">{title}</h2>
          <button type="button" className="btn-ghost ml-auto !px-2.5 !py-1.5" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <footer className="border-t border-white/10 px-5 py-4">{footer}</footer> : null}
      </aside>
    </div>
  )
}

export function relativeTime(value) {
  if (!value) return ''
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`
  return `${Math.floor(seconds / 86400)} d ago`
}

export const EMOTION_COLOURS = {
  neutral: 'bg-slate-500/20 text-slate-200',
  joy: 'bg-amber-400/20 text-amber-100',
  sadness: 'bg-sky-500/20 text-sky-100',
  anger: 'bg-rose-500/20 text-rose-100',
  fear: 'bg-violet-500/20 text-violet-100',
  surprise: 'bg-fuchsia-500/20 text-fuchsia-100',
  disgust: 'bg-lime-600/20 text-lime-100',
  determination: 'bg-orange-500/20 text-orange-100',
  love: 'bg-pink-500/20 text-pink-100',
  confusion: 'bg-teal-500/20 text-teal-100',
}

export function EmotionChip({ emotion }) {
  if (!emotion) return null
  const tone = EMOTION_COLOURS[emotion] || EMOTION_COLOURS.neutral
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}>{emotion}</span>
}

export function scoreTone(score) {
  if (score === null || score === undefined) return 'text-slate-400'
  if (score >= 0.75) return 'text-emerald-300'
  if (score >= 0.62) return 'text-amber-300'
  return 'text-rose-300'
}
