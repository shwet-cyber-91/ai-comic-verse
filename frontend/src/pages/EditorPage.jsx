import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import api from '../api.js'
import PageView from '../components/PageView.jsx'
import PanelCard, { SHOT_LABELS } from '../components/PanelCard.jsx'
import {
  Banner,
  Card,
  Drawer,
  EmotionChip,
  Field,
  Spinner,
  scoreTone,
} from '../components/ui.jsx'

const BUBBLE_KINDS = ['speech', 'thought', 'shout', 'whisper', 'narration', 'caption', 'sfx']
const EMOTIONS = [
  'neutral',
  'joy',
  'sadness',
  'anger',
  'fear',
  'surprise',
  'disgust',
  'determination',
  'love',
  'confusion',
]
const EMOTION_EXPRESSIONS = {
  neutral: 'relaxed expression, calm eyes',
  joy: 'bright open eyes, wide genuine smile, raised cheeks',
  sadness: 'downcast eyes, slight frown, lowered shoulders',
  anger: 'furrowed brows, narrowed eyes, clenched jaw',
  fear: 'wide eyes, raised brows, tense parted lips',
  surprise: 'eyes wide open, brows high, mouth slightly agape',
  disgust: 'wrinkled nose, narrowed eyes, mouth pulled to one side',
  determination: 'steady gaze, set jaw, brows drawn together',
  love: 'soft gaze, gentle smile, relaxed brows',
  confusion: 'one brow raised, head tilted, uncertain frown',
}
const TEMPLATES = [
  'auto_grid',
  'splash',
  'two_horizontal',
  'two_vertical',
  'three_strip',
  'hero_top',
  'hero_left',
  'hero_five',
  'grid_2x2',
  'grid_2x3',
  'grid_3x2',
  'grid_3x3',
]

export default function EditorPage() {
  const { projectId } = useParams()

  const [project, setProject] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)

  const [pageIndex, setPageIndex] = useState(0)
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState(null)
  const [showOriginal, setShowOriginal] = useState(false)

  const load = useCallback(async () => {
    try {
      const payload = await api.getProject(projectId)
      setProject(payload)
      setLoadError(null)
      return payload
    } catch (err) {
      setLoadError(err.message)
      return null
    }
  }, [projectId])

  useEffect(() => {
    load()
  }, [load])

  const panels = project?.panels ?? []
  const selected = useMemo(
    () => panels.find((panel) => panel.panel_id === selectedId) || null,
    [panels, selectedId],
  )

  function openPanel(panel) {
    if (!panel) return
    setSelectedId(panel.panel_id)
    setDraft({
      dialogue: (panel.dialogue || []).map((line) => ({ ...line })),
      narration: panel.narration || '',
      sfx: panel.sfx || '',
      action: panel.action || '',
      emotion: panel.emotion || 'neutral',
      expression: panel.expression || '',
      characters: (panel.characters || []).join(', '),
    })
  }

  async function saveEdits() {
    if (!selected || !draft) return
    setBusy(true)
    setNotice(null)
    try {
      const payload = {
        dialogue: draft.dialogue.filter((line) => line.text.trim()),
        narration: draft.narration,
        sfx: draft.sfx,
        action: draft.action,
        emotion: draft.emotion,
        expression: draft.expression,
        characters: draft.characters
          .split(',')
          .map((name) => name.trim())
          .filter(Boolean),
      }
      const result = await api.updatePanel(projectId, selected.panel_id, payload)
      setProject(result.project)
      setNotice(`${selected.panel_id} saved — ${result.changed.join(', ') || 'nothing changed'}.`)
      setSelectedId(null)
      setDraft(null)
    } catch (err) {
      setLoadError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function regenerate(promptOverride) {
    if (!selected) return
    setBusy(true)
    setNotice(null)
    try {
      const job = await api.regeneratePanel(projectId, selected.panel_id, {
        prompt_override: promptOverride || undefined,
      })
      setNotice(`Re-rendering ${selected.panel_id} (job ${job.job_id.slice(0, 8)})…`)
      setSelectedId(null)
      setDraft(null)
      await waitForJob(job.job_id)
      await load()
      setNotice(`${selected.panel_id} re-rendered and re-scored.`)
    } catch (err) {
      setLoadError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function changeLayout(next) {
    setBusy(true)
    setNotice(null)
    try {
      const result = await api.updateLayout(projectId, next)
      setProject(result.project)
      setPageIndex(0)
      setNotice('Layout updated.')
    } catch (err) {
      setLoadError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (loadError && !project) {
    return (
      <Banner tone="error">
        Could not load project <code>{projectId}</code>: {loadError}
      </Banner>
    )
  }

  if (!project) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-400">
        <Spinner className="h-4 w-4" /> loading the comic…
      </div>
    )
  }

  const page = project.pages?.[pageIndex] || null
  const continuity = project.continuity

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-bold text-white">{project.title}</h1>
          <p className="text-xs text-slate-500">
            {project.style.replace('_', ' ')} · {panels.length} panels · {project.pages.length} pages ·{' '}
            {project.status}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn-ghost"
            onClick={() => setShowOriginal((previous) => !previous)}
            title="Toggle between the composed page and the raw panels"
          >
            {showOriginal ? 'Page view' : 'Panel view'}
          </button>
          <Link to={`/export/${projectId}`} className="btn-primary">
            Export →
          </Link>
        </div>
      </div>

      {notice ? <Banner tone="info" onDismiss={() => setNotice(null)}>{notice}</Banner> : null}
      {loadError && project ? (
        <Banner tone="error" onDismiss={() => setLoadError(null)}>
          {loadError}
        </Banner>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          {project.pages.length > 1 ? (
            <div className="flex flex-wrap gap-2">
              {project.pages.map((item, index) => (
                <button
                  key={item.page_id}
                  type="button"
                  onClick={() => setPageIndex(index)}
                  className={[
                    'rounded-lg border px-3 py-1.5 text-xs transition',
                    index === pageIndex
                      ? 'border-accent bg-accent/15 text-white'
                      : 'border-white/10 bg-white/5 text-slate-400 hover:text-slate-200',
                  ].join(' ')}
                >
                  {item.page_id}
                </button>
              ))}
            </div>
          ) : null}

          {showOriginal || !page ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {panels.map((panel) => (
                <PanelCard
                  key={panel.panel_id}
                  panel={panel}
                  selected={panel.panel_id === selectedId}
                  onSelect={openPanel}
                  className="aspect-[4/3] w-full"
                />
              ))}
            </div>
          ) : (
            <PageView page={page} panels={panels} selectedPanelId={selectedId} onSelectPanel={openPanel} />
          )}
        </div>

        <aside className="space-y-4">
          {continuity ? (
            <Card title="Continuity" subtitle={`threshold ${continuity.threshold.toFixed(2)} · ${continuity.rounds} retry round(s)`}>
              <div className="flex items-baseline gap-3">
                <span className={`text-2xl font-bold ${scoreTone(continuity.mean_score)}`}>
                  {continuity.mean_score.toFixed(2)}
                </span>
                <span className="text-xs text-slate-500">mean · worst {continuity.min_score.toFixed(2)}</span>
              </div>
              <ul className="mt-3 space-y-1.5 text-xs">
                {panels.map((panel) => (
                  <li key={panel.panel_id} className="flex items-center gap-2">
                    <button
                      type="button"
                      className="font-mono text-slate-400 hover:text-white"
                      onClick={() => openPanel(panel)}
                    >
                      {panel.panel_id}
                    </button>
                    <span className={`ml-auto font-mono ${scoreTone(panel.continuity_score)}`}>
                      {panel.continuity_score?.toFixed(3) ?? '—'}
                    </span>
                    {panel.continuity_passed === false ? (
                      <span className="rounded bg-rose-500/20 px-1.5 text-[10px] text-rose-200">low</span>
                    ) : null}
                    {panel.regenerations > 0 ? (
                      <span className="rounded bg-amber-500/20 px-1.5 text-[10px] text-amber-100">
                        ×{panel.regenerations + 1}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          <Card title="Layout">
            <Field label={`Panels per page: ${project.panels_per_page}`}>
              <input
                type="range"
                min={1}
                max={9}
                value={project.panels_per_page}
                onChange={(event) => changeLayout({ panels_per_page: Number(event.target.value) })}
                className="w-full accent-accent"
                disabled={busy}
              />
            </Field>

            <Field label="Page template" className="mt-4">
              <select
                className="input"
                value={project.pages[pageIndex]?.template || 'auto_grid'}
                onChange={(event) => changeLayout({ template: event.target.value })}
                disabled={busy}
              >
                {TEMPLATES.map((template) => (
                  <option key={template} value={template}>
                    {template}
                  </option>
                ))}
              </select>
            </Field>
            {project.pages[pageIndex]?.template_fallback ? (
              <p className="mt-2 text-xs text-amber-300">
                {project.pages[pageIndex].template_note || 'This layout does not fit the panel count; keeping your selection while using a balanced grid.'}
              </p>
            ) : (
              <p className="mt-2 text-xs text-slate-500">
                A template that does not fit the panel count falls back to a balanced grid.
              </p>
            )}
          </Card>

          {project.characters.length ? (
            <Card title="Cast">
              <ul className="space-y-3">
                {project.characters.map((character) => (
                  <li key={character.character_id} className="flex gap-3">
                    {character.reference_urls?.[0] || character.canonical_url ? (
                      <img
                        src={character.canonical_url || character.reference_urls[0]}
                        alt={character.name}
                        className="h-14 w-14 rounded-lg border border-white/10 object-cover"
                      />
                    ) : (
                      <span className="grid h-14 w-14 place-items-center rounded-lg bg-white/5 text-lg">🎭</span>
                    )}
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-white">{character.name}</p>
                      <p className="line-clamp-2 text-xs text-slate-400">{character.appearance}</p>
                      <p className="mt-0.5 text-[11px] text-slate-600">
                        {character.appearance_count} panel(s) · {character.embedding_backend || 'n/a'}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </aside>
      </div>

      <Drawer
        open={Boolean(selected && draft)}
        title={selected ? `Panel ${selected.panel_id}` : ''}
        onClose={() => {
          setSelectedId(null)
          setDraft(null)
        }}
        footer={
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" onClick={saveEdits} disabled={busy}>
              {busy ? <Spinner className="h-4 w-4" /> : null} Save changes
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => regenerate()}
              disabled={busy}
              title="Render this panel again with a new seed"
            >
              🔄 Regenerate
            </button>
          </div>
        }
      >
        {selected && draft ? (
          <div className="space-y-5">
            {selected.image_url ? (
              <img
                src={selected.image_url}
                alt={selected.scene_summary}
                className="w-full rounded-xl border border-white/10"
              />
            ) : null}

            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <EmotionChip emotion={selected.emotion} />
              {selected.camera ? <span className="chip">{SHOT_LABELS[selected.camera.shot] || selected.camera.shot}</span> : null}
              {selected.camera?.lens ? <span className="chip">{selected.camera.lens}</span> : null}
              {selected.camera?.movement ? <span className="chip">{selected.camera.movement}</span> : null}
              <span className={`chip ${scoreTone(selected.continuity_score)}`}>
                continuity {selected.continuity_score?.toFixed(3) ?? '—'}
              </span>
            </div>

            {selected.continuity_detail?.per_reference ? (
              <details className="rounded-lg border border-white/10 bg-white/5 p-3 text-xs text-slate-400">
                <summary className="cursor-pointer font-medium text-slate-300">Continuity detail</summary>
                <ul className="mt-2 space-y-1 font-mono">
                  {Object.entries(selected.continuity_detail.per_reference).map(([file, values]) => (
                    <li key={file} className="flex justify-between gap-3">
                      <span className="truncate">{file}</span>
                      <span>
                        emb {values.embedding?.toFixed(3)} · col {values.colour?.toFixed(3)}
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}

            <Field label="Scene summary">
              <textarea
                className="input min-h-[70px] resize-y"
                value={draft.action}
                onChange={(event) => setDraft({ ...draft, action: event.target.value })}
              />
            </Field>

            <Field label="Characters in panel" hint="Comma separated. These names are included in the panel prompt.">
              <input
                className="input"
                value={draft.characters}
                onChange={(event) => setDraft({ ...draft, characters: event.target.value })}
              />
            </Field>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Emotion">
                <select
                  className="input"
                  value={draft.emotion}
                  onChange={(event) => {
                    const nextEmotion = event.target.value
                    setDraft({
                      ...draft,
                      emotion: nextEmotion,
                      expression: EMOTION_EXPRESSIONS[nextEmotion] || draft.expression,
                    })
                  }}
                >
                  {EMOTIONS.map((emotion) => (
                    <option key={emotion} value={emotion}>
                      {emotion}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Expression">
                <input
                  className="input"
                  value={draft.expression}
                  onChange={(event) => setDraft({ ...draft, expression: event.target.value })}
                  placeholder="jaw set, eyes narrowed"
                />
              </Field>
            </div>

            <Field label="Narration box">
              <textarea
                className="input min-h-[60px] resize-y"
                value={draft.narration}
                onChange={(event) => setDraft({ ...draft, narration: event.target.value })}
              />
            </Field>

            <Field label="Sound effect">
              <input
                className="input"
                value={draft.sfx}
                onChange={(event) => setDraft({ ...draft, sfx: event.target.value })}
                placeholder="WHOOSH"
              />
            </Field>

            <div>
              <div className="flex items-center gap-2">
                <span className="label !mb-0">Dialogue</span>
                <button
                  type="button"
                  className="btn-ghost ml-auto !px-2.5 !py-1 text-xs"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      dialogue: [...draft.dialogue, { speaker: 'Mira', text: '', kind: 'speech', emotion: 'neutral' }],
                    })
                  }
                >
                  + Line
                </button>
              </div>

              <ul className="mt-2 space-y-3">
                {draft.dialogue.map((line, index) => (
                  <li key={index} className="rounded-xl border border-white/10 bg-white/5 p-3">
                    <div className="flex gap-2">
                      <input
                        className="input !py-1.5 text-xs"
                        value={line.speaker}
                        placeholder="Speaker"
                        onChange={(event) => {
                          const next = [...draft.dialogue]
                          next[index] = { ...line, speaker: event.target.value }
                          setDraft({ ...draft, dialogue: next })
                        }}
                      />
                      <select
                        className="input !w-auto !py-1.5 text-xs"
                        value={line.kind}
                        onChange={(event) => {
                          const next = [...draft.dialogue]
                          next[index] = { ...line, kind: event.target.value }
                          setDraft({ ...draft, dialogue: next })
                        }}
                      >
                        {BUBBLE_KINDS.map((kind) => (
                          <option key={kind} value={kind}>
                            {kind}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="btn-danger !px-2.5 !py-1.5 text-xs"
                        onClick={() =>
                          setDraft({ ...draft, dialogue: draft.dialogue.filter((_, i) => i !== index) })
                        }
                      >
                        ✕
                      </button>
                    </div>
                    <textarea
                      className="input mt-2 min-h-[54px] resize-y text-sm"
                      value={line.text}
                      placeholder="What they say"
                      onChange={(event) => {
                        const next = [...draft.dialogue]
                        next[index] = { ...line, text: event.target.value }
                        setDraft({ ...draft, dialogue: next })
                      }}
                    />
                  </li>
                ))}
                {!draft.dialogue.length ? (
                  <li className="text-xs text-slate-500">No dialogue in this panel.</li>
                ) : null}
              </ul>
            </div>

            <details className="rounded-lg border border-white/10 bg-white/5 p-3 text-xs text-slate-400">
              <summary className="cursor-pointer font-medium text-slate-300">Prompt sent to the renderer</summary>
              <p className="mt-2 leading-relaxed">{selected.visual_prompt}</p>
              {selected.negative_prompt ? (
                <p className="mt-2 leading-relaxed text-slate-500">
                  <span className="font-semibold">negative:</span> {selected.negative_prompt}
                </p>
              ) : null}
              <button
                type="button"
                className="btn-ghost mt-3 !px-2.5 !py-1 text-xs"
                onClick={() => {
                  const override = window.prompt('Prompt override for the next render:', selected.visual_prompt)
                  if (override) regenerate(override)
                }}
              >
                Regenerate with an edited prompt
              </button>
            </details>

            <p className="text-[11px] text-slate-600">Rendered by {selected.image_provider || 'unknown'} · seed {selected.seed}</p>
          </div>
        ) : null}
      </Drawer>
    </div>
  )
}

/** Poll a regeneration job until it settles. Regeneration is quick. */
async function waitForJob(jobId, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const snapshot = await api.job(jobId)
    if (snapshot.status === 'succeeded') return snapshot
    if (snapshot.status === 'failed') throw new Error(snapshot.error || 'regeneration failed')
    await new Promise((resolve) => setTimeout(resolve, 700))
  }
  throw new Error('regeneration timed out')
}
