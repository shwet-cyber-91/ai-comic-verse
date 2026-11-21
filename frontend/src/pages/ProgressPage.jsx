import { useCallback, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import ProgressTimeline from '../components/ProgressTimeline.jsx'
import { Banner } from '../components/ui.jsx'

export default function ProgressPage() {
  const { jobId } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const projectId = params.get('project')

  const [status, setStatus] = useState('running')

  const finished = useCallback(
    (finalStatus) => {
      setStatus(finalStatus)
      if (finalStatus === 'succeeded' && projectId) {
        // let the editor load a project that is already complete
        setTimeout(() => navigate(`/editor/${projectId}`), 900)
      }
    },
    [navigate, projectId],
  )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold text-white">Generating your comic</h1>
        <span className="chip">job {jobId?.slice(0, 8)}</span>
        {status === 'succeeded' ? (
          <span className="chip !border-emerald-400/40 !text-emerald-200">done — opening the editor…</span>
        ) : null}
      </div>

      {status === 'failed' ? (
        <Banner tone="error">
          Generation failed. The log below has the full story. Common causes: a provider key that is set
          but rejected, or an unreachable image API. Check <code>GET /api/health</code> for the providers
          actually in use.
        </Banner>
      ) : null}

      <ProgressTimeline jobId={jobId} onFinished={finished} />

      <div className="flex flex-wrap gap-2">
        {projectId ? (
          <>
            <Link to={`/editor/${projectId}`} className="btn-ghost">
              Open the editor now
            </Link>
            <Link to={`/export/${projectId}`} className="btn-ghost">
              Export
            </Link>
          </>
        ) : null}
        <Link to="/" className="btn-ghost ml-auto">
          New comic
        </Link>
      </div>
    </div>
  )
}
