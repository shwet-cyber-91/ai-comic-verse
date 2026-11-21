import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'

import api from './api.js'
import { Banner, Spinner } from './components/ui.jsx'
import CreatePage from './pages/CreatePage.jsx'
import EditorPage from './pages/EditorPage.jsx'
import ExportPage from './pages/ExportPage.jsx'
import ProgressPage from './pages/ProgressPage.jsx'
import ProjectsPage from './pages/ProjectsPage.jsx'

function NavItem({ to, children }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        [
          'rounded-lg px-3 py-1.5 text-sm font-medium transition',
          isActive ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-slate-100',
        ].join(' ')
      }
    >
      {children}
    </NavLink>
  )
}

function Placeholder({ title, children }) {
  return (
    <div className="card mx-auto max-w-xl p-8 text-center">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <p className="mt-2 text-sm text-slate-400">{children}</p>
    </div>
  )
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [healthError, setHealthError] = useState(null)

  useEffect(() => {
    let cancelled = false
    api
      .health()
      .then((payload) => !cancelled && setHealth(payload))
      .catch((error) => !cancelled && setHealthError(error.message))
    return () => {
      cancelled = true
    }
  }, [])

  const providers = health?.providers

  return (
    <div className="min-h-screen">
      <header className="no-print sticky top-0 z-30 border-b border-white/10 bg-ink-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
          <NavLink to="/" className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 grid-cols-2 grid-rows-2 gap-0.5 rounded-lg bg-accent p-1.5">
              <span className="col-span-2 bg-ink-950" />
              <span className="bg-ink-950" />
              <span className="bg-ink-950" />
            </span>
            <span className="text-lg font-bold tracking-tight text-white">
              AI Comic<span className="text-accent">Verse</span>
            </span>
          </NavLink>

          <nav className="ml-auto flex items-center gap-1">
            <NavItem to="/">Create</NavItem>
            <NavItem to="/projects">Projects</NavItem>
          </nav>

          <div className="flex items-center gap-2 text-xs">
            {providers ? (
              <>
                <span className="chip" title="Story, dialogue and camera work">
                  llm: {providers.llm}
                </span>
                <span className="chip" title="Panel rendering">
                  image: {providers.image}
                </span>
              </>
            ) : (
              <Spinner className="h-4 w-4" />
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
        {providers?.llm_fallback ? (
          <Banner tone="warning" className="mb-6">
            Gemini text analysis is unavailable, so the backend selected its text-only fallback.
            Add a valid <code>GEMINI_API_KEY</code> to <code>backend/.env</code> and restart the
            backend. Image generation remains configured separately.
          </Banner>
        ) : null}

        {providers?.image_fallback ? (
          <Banner tone="error" className="mb-6">
            The configured image provider is unavailable. Mock artwork will not be substituted;
            check the backend logs and provider configuration before generating.
          </Banner>
        ) : null}

        {healthError ? (
          <Banner tone="error" className="mb-6">
            Cannot reach the backend at <code>/api</code> — {healthError}. Start it with{' '}
            <code>uvicorn app.main:app --reload</code> from <code>backend/</code>.
          </Banner>
        ) : null}

        <Routes>
          <Route path="/" element={<CreatePage health={health} />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/progress/:jobId" element={<ProgressPage />} />
          <Route path="/editor/:projectId" element={<EditorPage />} />
          <Route path="/export/:projectId" element={<ExportPage />} />
          <Route
            path="*"
            element={<Placeholder title="Page not found">That route does not exist.</Placeholder>}
          />
        </Routes>
      </main>

      <footer className="no-print mx-auto max-w-7xl px-4 pb-10 pt-4 text-xs text-slate-500 sm:px-6">
        AI ComicVerse · styles are generic art directions (manga, anime, manhwa, Bengali comic,
        Marvel-like, DC-like) and never depict copyrighted characters.
      </footer>
    </div>
  )
}
