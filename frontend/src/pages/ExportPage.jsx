import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import api, { EXPORT_FORMATS, assetUrl } from '../api.js'
import { Banner, Card, EmptyState, Spinner } from '../components/ui.jsx'

export default function ExportPage() {
  const { projectId } = useParams()

  const [project, setProject] = useState(null)
  const [selected, setSelected] = useState(EXPORT_FORMATS.map((format) => format.id))
  const [results, setResults] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const payload = await api.getProject(projectId)
      setProject(payload)
      const existing = payload.exports || {}
      const ready = EXPORT_FORMATS.filter((format) => existing[format.id]).map((format) => format.id)
      if (ready.length) setResults(existing)
    } catch (err) {
      setError(err.message)
    }
  }, [projectId])

  useEffect(() => {
    load()
  }, [load])

  async function runExport() {
    setBusy(true)
    setError(null)
    try {
      const payload = await api.exportProject(projectId, selected)
      setResults(payload.exports)
      setProject(payload.project)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !project) {
    return <Banner tone="error">Could not load project {projectId}: {error}</Banner>
  }

  if (!project) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-400">
        <Spinner className="h-4 w-4" /> loading…
      </div>
    )
  }

  if (!project.panels?.length) {
    return (
      <EmptyState icon="⏳" title="Nothing to export yet">
        This project has no panels. Generate it first.
        <div className="mt-3">
          <Link to={`/editor/${projectId}`} className="btn-ghost">
            Open the editor
          </Link>
        </div>
      </EmptyState>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">Export “{project.title}”</h1>
          <p className="text-xs text-slate-500">
            {project.panels.length} panels · {project.pages.length} page(s) · {project.style.replace('_', ' ')}
          </p>
        </div>
        <Link to={`/editor/${projectId}`} className="btn-ghost ml-auto">
          ← Back to the editor
        </Link>
      </div>

      {error ? <Banner tone="error" onDismiss={() => setError(null)}>{error}</Banner> : null}

      <Card
        title="Formats"
        subtitle="Every page is composed once and reused, so all four stay in sync."
        actions={
          <button type="button" className="btn-primary" onClick={runExport} disabled={busy || !selected.length}>
            {busy ? <Spinner className="h-4 w-4" /> : '⬇'} Export {selected.length} format
            {selected.length === 1 ? '' : 's'}
          </button>
        }
      >
        <ul className="grid gap-3 sm:grid-cols-2">
          {EXPORT_FORMATS.map((format) => {
            const on = selected.includes(format.id)
            const ready = results?.[format.id]
            return (
              <li
                key={format.id}
                className={[
                  'flex items-start gap-3 rounded-xl border p-4 transition',
                  on ? 'border-accent/60 bg-accent/5' : 'border-white/10 bg-white/5',
                ].join(' ')}
              >
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 accent-accent"
                  checked={on}
                  onChange={() =>
                    setSelected((previous) =>
                      on ? previous.filter((id) => id !== format.id) : [...previous, format.id],
                    )
                  }
                />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-white">
                    <span className="mr-1.5">{format.icon}</span>
                    {format.label}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-400">{format.hint}</p>
                  {ready ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <a
                        className="btn-primary !px-3 !py-1.5 text-xs"
                        href={api.downloadUrl(projectId, format.id)}
                        download
                      >
                        Download
                      </a>
                      <a className="btn-ghost !px-3 !py-1.5 text-xs" href={assetUrl(ready)} target="_blank" rel="noreferrer">
                        Open
                      </a>
                    </div>
                  ) : (
                    <p className="mt-2 text-[11px] text-slate-600">not generated yet</p>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      </Card>

      <Card title="Preview" subtitle={`${project.pages.length} composed page(s)`}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {project.pages.map((page) => {
            const first = project.panels.find((panel) => page.panel_ids.includes(panel.panel_id))
            return (
              <figure key={page.page_id} className="overflow-hidden rounded-lg border border-white/10 bg-ink-800">
                {first?.image_url ? (
                  <img src={assetUrl(first.image_url)} alt={page.page_id} className="aspect-[2/3] w-full object-cover" />
                ) : (
                  <div className="aspect-[2/3] w-full" />
                )}
                <figcaption className="flex items-center justify-between px-3 py-2 text-[11px] text-slate-400">
                  <span>{page.page_id}</span>
                  <span>{page.template}</span>
                </figcaption>
              </figure>
            )
          })}
        </div>
      </Card>

      <Card title="Story text" subtitle="Kept with the PNG zip and the EPUB">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">{project.story_text}</p>
      </Card>
    </div>
  )
}
