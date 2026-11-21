import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import api from '../api.js'
import { Banner, Card, EmptyState, Spinner, relativeTime } from '../components/ui.jsx'

const STATUS_TONE = {
  draft: 'bg-slate-500/20 text-slate-200',
  queued: 'bg-sky-500/20 text-sky-100',
  running: 'bg-amber-500/20 text-amber-100',
  ready: 'bg-emerald-500/20 text-emerald-100',
  failed: 'bg-rose-500/20 text-rose-100',
}

export default function ProjectsPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState(null)
  const [error, setError] = useState(null)

  async function load() {
    try {
      const payload = await api.listProjects()
      setProjects(payload.projects)
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function resume(project) {
    try {
      const job = await api.generate(project.project_id)
      navigate(`/progress/${job.job_id}?project=${project.project_id}`)
    } catch (err) {
      setError(err.message)
    }
  }

  async function remove(project) {
    if (!window.confirm(`Delete "${project.title}"? This cannot be undone.`)) return
    try {
      await api.deleteProject(project.project_id)
      setProjects((previous) => previous.filter((item) => item.project_id !== project.project_id))
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold text-white">Your comics</h1>
        <Link to="/" className="btn-primary ml-auto">
          + New comic
        </Link>
      </div>

      {error ? <Banner tone="error" onDismiss={() => setError(null)}>{error}</Banner> : null}

      {projects === null ? (
        <div className="flex items-center gap-3 text-sm text-slate-400">
          <Spinner className="h-4 w-4" /> loading…
        </div>
      ) : projects.length ? (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <li key={project.project_id} className="card flex flex-col p-4">
              <div className="flex items-start gap-2">
                <h2 className="min-w-0 flex-1 truncate font-semibold text-white">{project.title}</h2>
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_TONE[project.status] || STATUS_TONE.draft}`}>
                  {project.status}
                </span>
              </div>

              <p className="mt-1 text-xs text-slate-500">
                {project.style.replace('_', ' ')} · {project.panel_count} panels · {project.page_count} page
                {project.page_count === 1 ? '' : 's'} · {project.character_count} character
                {project.character_count === 1 ? '' : 's'}
              </p>
              <p className="mt-1 text-[11px] text-slate-600">updated {relativeTime(project.updated_at)}</p>

              <div className="mt-4 flex flex-wrap gap-2">
                <Link to={`/editor/${project.project_id}`} className="btn-primary !px-3 !py-1.5 text-xs">
                  Open editor
                </Link>
                <Link to={`/export/${project.project_id}`} className="btn-ghost !px-3 !py-1.5 text-xs">
                  Export
                </Link>
                <button type="button" className="btn-ghost !px-3 !py-1.5 text-xs" onClick={() => resume(project)}>
                  Re-run
                </button>
                <button type="button" className="btn-danger ml-auto !px-3 !py-1.5 text-xs" onClick={() => remove(project)}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon="📚"
          title="No comics yet"
          action={
            <Link to="/" className="btn-primary">
              Create your first comic
            </Link>
          }
        >
          A story and 1–2 reference images per character is all it takes.
        </EmptyState>
      )}

      <Card title="Tip" bodyClassName="p-5 text-sm text-slate-400">
        Re-running a project regenerates it from the same story and seed — handy after raising the
        continuity threshold or switching image provider.
      </Card>
    </div>
  )
}
