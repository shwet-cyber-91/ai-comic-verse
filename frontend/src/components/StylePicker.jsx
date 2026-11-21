import { useEffect, useState } from 'react'

import api from '../api.js'

/** Style chooser. The presets come from the backend, so they cannot drift. */
export default function StylePicker({ value, onChange, styles: provided }) {
  const [styles, setStyles] = useState(provided || [])
  const [error, setError] = useState(null)

  useEffect(() => {
    if (provided?.length) {
      setStyles(provided)
      return
    }
    let cancelled = false
    api
      .styles()
      .then((payload) => !cancelled && setStyles(payload.styles))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [provided])

  if (error) return <p className="text-sm text-rose-300">Could not load styles: {error}</p>

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {styles.map((style) => {
        const selected = style.id === value
        return (
          <button
            key={style.id}
            type="button"
            onClick={() => onChange(style.id)}
            aria-pressed={selected}
            className={[
              'group overflow-hidden rounded-xl border p-3 text-left transition',
              selected
                ? 'border-accent bg-accent/10 shadow-inset'
                : 'border-white/10 bg-white/5 hover:border-white/25 hover:bg-white/10',
            ].join(' ')}
          >
            <div className="flex items-center gap-2">
              <span className="flex gap-1">
                {(style.palette || []).slice(0, 4).map((colour) => (
                  <span
                    key={colour}
                    className="h-4 w-4 rounded-full border border-black/30"
                    style={{ background: colour }}
                  />
                ))}
              </span>
              <span className="font-semibold text-white">{style.name}</span>
              {selected ? <span className="ml-auto text-accent">✓</span> : null}
            </div>
            <p className="mt-2 text-xs leading-relaxed text-slate-400">{style.description}</p>
            {style.best_for?.length ? (
              <p className="mt-2 text-[11px] text-slate-500">Best for: {style.best_for.join(', ')}</p>
            ) : null}
          </button>
        )
      })}
      {!styles.length ? <p className="text-sm text-slate-400">Loading styles…</p> : null}
    </div>
  )
}
