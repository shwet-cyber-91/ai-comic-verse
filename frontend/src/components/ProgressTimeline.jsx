import { useEffect, useState } from 'react'

import api from '../api.js'
import { ProgressBar, Spinner } from './ui.jsx'

const LEVEL_DOT = {
  info: 'bg-slate-500',
  success: 'bg-emerald-400',
  warning: 'bg-amber-400',
  error: 'bg-rose-400',
}

/**
 * Live pipeline view driven by SSE (`GET /api/jobs/{jobId}/events`).
 *
 * The server replays everything already emitted, so a page reload mid-run picks
 * the log back up from the beginning rather than from the reconnect point.
 */
export default function ProgressTimeline({ jobId, onFinished }) {
  const [nodes, setNodes] = useState([])
  const [state, setState] = useState(null)
  const [events, setEvents] = useState([])
  const [connectionError, setConnectionError] = useState(null)

  useEffect(() => {
    let cancelled = false
    api
      .pipelineNodes()
      .then((payload) => !cancelled && setNodes(payload.nodes))
      .catch(() => !cancelled && setNodes([]))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!jobId) return undefined

    const source = new EventSource(api.jobEventsUrl(jobId))

    source.addEventListener('state', (message) => {
      setConnectionError(null)
      try {
        setState(JSON.parse(message.data))
      } catch {
        /* a malformed frame is not worth breaking the screen over */
      }
    })

    source.addEventListener('progress', (message) => {
      try {
        const event = JSON.parse(message.data)
        setEvents((previous) =>
          previous.some((item) => item.seq === event.seq) ? previous : [...previous, event],
        )
      } catch {
        /* ignore */
      }
    })

    source.addEventListener('end', (message) => {
      source.close()
      let status = 'succeeded'
      try {
        status = JSON.parse(message.data).status
      } catch {
        /* default to succeeded */
      }
      onFinished?.(status)
    })

    source.addEventListener('error', () => {
      // EventSource fires this on a normal close too, so only report it while the
      // server has not told us the job is over.
      setConnectionError((previous) => previous ?? 'the progress stream closed unexpectedly')
    })

    return () => source.close()
  }, [jobId, onFinished])

  const completed = state?.completed_nodes ?? []
  const current = state?.current_node
  const progress = state?.progress ?? 0

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
      <div className="card p-5">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold text-white">Pipeline</h2>
          {state && ['queued', 'running'].includes(state.status) ? (
            <Spinner className="ml-auto h-4 w-4 text-accent" />
          ) : null}
        </div>

        <ProgressBar value={progress} className="mt-3" />
        <p className="mt-2 text-xs text-slate-400">
          {completed.length}/{state?.total_nodes || nodes.length || 14} stages ·{' '}
          {Math.round(progress * 100)}%
        </p>

        <ol className="mt-5 space-y-1.5">
          {nodes.map((node) => {
            const done = completed.includes(node.name)
            const active = current === node.name
            return (
              <li
                key={node.name}
                className={[
                  'flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-sm transition',
                  active ? 'bg-accent/10 text-white' : done ? 'text-slate-200' : 'text-slate-500',
                ].join(' ')}
              >
                <span
                  className={[
                    'mt-1 h-2.5 w-2.5 shrink-0 rounded-full',
                    done ? 'bg-emerald-400' : active ? 'animate-pulse bg-accent' : 'bg-white/15',
                  ].join(' ')}
                  aria-hidden="true"
                />
                <span className="min-w-0">
                  <span className="font-medium">{node.label}</span>
                  <span className="block text-[11px] leading-snug text-slate-500">
                    {node.description}
                  </span>
                </span>
                {done ? <span className="ml-auto text-xs text-emerald-400">✓</span> : null}
              </li>
            )
          })}
        </ol>
      </div>

      <div className="card flex max-h-[70vh] flex-col p-0">
        <header className="flex items-center gap-3 border-b border-white/10 px-5 py-4">
          <h2 className="text-base font-semibold text-white">Live log</h2>
          <span className="chip ml-auto">{events.length} events</span>
        </header>

        {connectionError ? (
          <p className="border-b border-white/10 px-5 py-2 text-xs text-amber-300">{connectionError}</p>
        ) : null}

        {state?.error ? (
          <p className="border-b border-white/10 bg-rose-500/10 px-5 py-3 text-sm text-rose-200">
            {state.error}
          </p>
        ) : null}

        <ol className="flex-1 space-y-1 overflow-y-auto px-5 py-4 font-mono text-[12px] leading-relaxed">
          {events.map((event) => (
            <li key={event.seq} className="flex gap-2.5">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${LEVEL_DOT[event.level] || LEVEL_DOT.info}`} />
              <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">
                {event.node ? <span className="text-slate-500">{event.node} </span> : null}
                <span
                  className={
                    event.level === 'error'
                      ? 'text-rose-300'
                      : event.level === 'warning'
                        ? 'text-amber-300'
                        : event.level === 'success'
                          ? 'text-emerald-300'
                          : 'text-slate-300'
                  }
                >
                  {event.message}
                </span>
              </span>
            </li>
          ))}
          {!events.length ? (
            <li className="py-6 text-center text-slate-500">Waiting for the first stage…</li>
          ) : null}
        </ol>
      </div>
    </div>
  )
}
