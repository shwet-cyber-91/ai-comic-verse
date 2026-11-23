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
          'rounded-lg px-3 py-2 text-sm font-medium transition',
          isActive
            ? 'bg-accent/15 text-white shadow-[inset_0_0_0_1px_rgba(139,124,246,.25)]'
            : 'text-slate-400 hover:bg-white/5 hover:text-slate-100',
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

function BrandMark() {
  return (
    <svg
      viewBox="0 0 40 40"
      className="h-10 w-10 shrink-0"
      fill="none"
      aria-label="AI ComicVerse logo"
    >
      <defs>
        <linearGradient id="brand-gradient" x1="6" y1="4" x2="34" y2="36" gradientUnits="userSpaceOnUse">
          <stop stopColor="#B6ADFF" />
          <stop offset="1" stopColor="#6857DB" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="36" height="36" rx="11" fill="url(#brand-gradient)" />
      <path d="M9 10.5h15.5v10.5H15l-6 5v-15.5Z" fill="#10131F" />
      <path d="M18.5 19h12.5v10.5h-7l-5.5 4V19Z" fill="#10131F" opacity=".88" />
      <circle cx="14" cy="16" r="1.5" fill="#B6ADFF" />
      <path d="M19.5 15.5l2.5 2.5" stroke="#B6ADFF" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
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
      <header className="no-print sticky top-0 z-30 border-b border-white/[0.07] bg-ink-950/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
          <NavLink to="/" className="flex items-center gap-2.5">
            <BrandMark />
            <span className="text-[17px] font-bold tracking-tight text-white">
              AI Comic<span className="bg-gradient-to-r from-accent-soft to-cyan-300 bg-clip-text text-transparent">Verse</span>
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
