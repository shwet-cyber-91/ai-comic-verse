import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import api, { EXPORT_FORMATS } from '../api.js'
import CharacterUploader from '../components/CharacterUploader.jsx'
import StylePicker from '../components/StylePicker.jsx'
import { Banner, Card, Field, Spinner } from '../components/ui.jsx'

const STEPS = [
  'Tell the story',
  'Pick a style',
  'Cast your characters',
  'Generate',
]

export default function CreatePage() {
  const navigate = useNavigate()

  const [step, setStep] = useState(0)
  const [title, setTitle] = useState('The Last Star Chart')
  const [storyText, setStoryText] = useState('')
  const [style, setStyle] = useState('manga')
  const [characters, setCharacters] = useState([])
  const [panelCount, setPanelCount] = useState(8)
  const [panelsPerPage, setPanelsPerPage] = useState(4)
  const [formats, setFormats] = useState(EXPORT_FORMATS.map((format) => format.id))
  const [threshold, setThreshold] = useState(0.62)
  const [styles, setStyles] = useState([])

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  // voice input
  const [recording, setRecording] = useState(false)
  const recorderRef = useRef(null)
  const chunksRef = useRef([])

  useEffect(() => {
    let cancelled = false
    api
      .styles()
      .then((payload) => !cancelled && setStyles(payload.styles))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  async function loadDemo() {
    setError(null)
    try {
      const demo = await api.demoStory()
      setTitle(demo.title)
      setStoryText(demo.story_text)
      setStyle(demo.style)
      setPanelCount(demo.panel_count)
      setPanelsPerPage(demo.panels_per_page)
      setNotice('Demo story loaded — press Generate for an instant comic.')
    } catch (err) {
      setError(`Could not load the demo story: ${err.message}`)
    }
  }

  async function transcribeBlob(blob, filename) {
    setBusy(true)
    setError(null)
    try {
      const result = await api.transcribe(new File([blob], filename, { type: blob.type || 'audio/webm' }))
      setStoryText((previous) => (previous ? `${previous}\n\n${result.text}` : result.text))
      setNotice(`Transcribed with ${result.provider}.`)
    } catch (err) {
      setError(`Transcription failed: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop()
      return
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser has no microphone API. Use the audio file upload instead.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (event) => event.data.size && chunksRef.current.push(event.data)
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop())
        setRecording(false)
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        if (blob.size) transcribeBlob(blob, 'recording.webm')
      }
      recorderRef.current = recorder
      recorder.start()
      setRecording(true)
      setError(null)
    } catch (err) {
      setError(`Microphone permission denied: ${err.message}`)
    }
  }

  async function generate() {
    if (!storyText.trim()) {
      setError('The story is empty — write or dictate something first.')
      setStep(0)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const project = await api.createProject({
        title: title.trim() || 'Untitled Comic',
        story_text: storyText,
        style,
        characters,
        panel_count: Number(panelCount),
        panels_per_page: Number(panelsPerPage),
        export_formats: formats,
        continuity_threshold: Number(threshold),
      })
      const job = await api.generate(project.project_id)
      navigate(`/progress/${job.job_id}?project=${project.project_id}`)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-6">
        <ol className="flex flex-wrap gap-2 text-xs">
          {STEPS.map((label, index) => (
            <li key={label}>
              <button
                type="button"
                onClick={() => setStep(index)}
                className={[
                  'rounded-full border px-3 py-1.5 transition',
                  index === step
                    ? 'border-accent bg-accent/15 text-white'
                    : 'border-white/10 bg-white/5 text-slate-400 hover:text-slate-200',
                ].join(' ')}
              >
                <span className="mr-1.5 font-semibold">{index + 1}</span>
                {label}
              </button>
            </li>
          ))}
        </ol>

        {notice ? <Banner tone="success" onDismiss={() => setNotice(null)}>{notice}</Banner> : null}
        {error ? <Banner tone="error" onDismiss={() => setError(null)}>{error}</Banner> : null}

        {step === 0 ? (
          <Card
            title="The story"
            subtitle="Plain prose is fine — the pipeline splits it into scenes and beats."
            actions={
              <>
                <button type="button" className="btn-ghost" onClick={loadDemo}>
                  Load demo story
                </button>
                <button
                  type="button"
                  className={recording ? 'btn-danger' : 'btn-ghost'}
                  onClick={toggleRecording}
                  disabled={busy}
                >
                  {recording ? '■ Stop recording' : '🎙 Speak the story'}
                </button>
              </>
            }
          >
            <div className="space-y-4">
              <Field label="Title">
                <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={120} />
              </Field>

              <Field
                label="Story"
                hint={`${storyText.trim() ? storyText.trim().split(/\s+/).length : 0} words · roughly ${Math.max(
                  2,
                  Math.round((storyText.trim().split(/\s+/).length || 0) / 25),
                )} panels' worth of material`}
              >
                <textarea
                  className="input min-h-[220px] resize-y leading-relaxed"
                  value={storyText}
                  onChange={(event) => setStoryText(event.target.value)}
                  placeholder="Mira lands her glider on the observatory roof at dusk…"
                />
              </Field>

              <div className="flex flex-wrap items-center gap-3">
                <label className="btn-ghost cursor-pointer">
                  Upload audio
                  <input
                    type="file"
                    accept="audio/*,video/webm"
                    className="hidden"
                    onChange={(event) => event.target.files[0] && transcribeBlob(event.target.files[0], event.target.files[0].name)}
                  />
                </label>
                {busy ? (
                  <span className="inline-flex items-center gap-2 text-sm text-slate-400">
                    <Spinner className="h-4 w-4" /> working…
                  </span>
                ) : null}
                <button type="button" className="btn-primary ml-auto" onClick={() => setStep(1)}>
                  Next: style
                </button>
              </div>
            </div>
          </Card>
        ) : null}

        {step === 1 ? (
          <Card
            title="Art style"
            subtitle="One style is locked across every panel, so the book reads consistently."
            actions={
              <>
                <button type="button" className="btn-ghost" onClick={() => setStep(0)}>
                  Back
                </button>
                <button type="button" className="btn-primary" onClick={() => setStep(2)}>
                  Next: characters
                </button>
              </>
            }
          >
            <StylePicker value={style} onChange={setStyle} styles={styles} />
          </Card>
        ) : null}

        {step === 2 ? (
          <Card
            title="Character references"
            subtitle="Optional references are used for continuity scoring; Pollinations renders from the written character description."
            actions={
              <>
                <button type="button" className="btn-ghost" onClick={() => setStep(1)}>
                  Back
                </button>
                <button type="button" className="btn-primary" onClick={() => setStep(3)}>
                  Next: generate
                </button>
              </>
            }
          >
            <CharacterUploader characters={characters} onChange={setCharacters} />
          </Card>
        ) : null}

        {step === 3 ? (
          <Card
            title="Generation settings"
            subtitle="How long, how dense, and how strictly continuity is enforced."
            actions={
              <button type="button" className="btn-ghost" onClick={() => setStep(2)}>
                Back
              </button>
            }
          >
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label={`Panels: ${panelCount}`} hint="Each panel is one rendered image.">
                <input
                  type="range"
                  min={2}
                  max={24}
                  value={panelCount}
                  onChange={(event) => setPanelCount(event.target.value)}
                  className="w-full accent-accent"
                />
              </Field>

              <Field label={`Panels per page: ${panelsPerPage}`} hint="The layout generator fits the grid to this count.">
                <input
                  type="range"
                  min={1}
                  max={9}
                  value={panelsPerPage}
                  onChange={(event) => setPanelsPerPage(event.target.value)}
                  className="w-full accent-accent"
                />
              </Field>

              <Field
                label={`Continuity threshold: ${Number(threshold).toFixed(2)}`}
                hint="Panels scoring below this are regenerated, up to twice."
                className="sm:col-span-2"
              >
                <input
                  type="range"
                  min={0.3}
                  max={0.95}
                  step={0.01}
                  value={threshold}
                  onChange={(event) => setThreshold(event.target.value)}
                  className="w-full accent-accent"
                />
              </Field>

              <div className="sm:col-span-2">
                <span className="label">Export formats</span>
                <div className="flex flex-wrap gap-2">
                  {EXPORT_FORMATS.map((format) => {
                    const on = formats.includes(format.id)
                    return (
                      <button
                        key={format.id}
                        type="button"
                        onClick={() =>
                          setFormats((previous) =>
                            on ? previous.filter((id) => id !== format.id) : [...previous, format.id],
                          )
                        }
                        className={[
                          'rounded-xl border px-3 py-2 text-left text-xs transition',
                          on ? 'border-accent bg-accent/10 text-white' : 'border-white/10 bg-white/5 text-slate-400',
                        ].join(' ')}
                      >
                        <span className="mr-1.5">{format.icon}</span>
                        <span className="font-semibold">{format.label}</span>
                        <span className="block text-[11px] text-slate-500">{format.hint}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>

            <button type="button" className="btn-primary mt-6 w-full !py-3 text-base" onClick={generate} disabled={busy}>
              {busy ? <Spinner className="h-5 w-5" /> : '⚡'} Generate comic
            </button>
          </Card>
        ) : null}
      </div>

      <aside className="space-y-4">
        <Card title="Summary">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-slate-400">Title</dt>
              <dd className="truncate text-right text-slate-100">{title || 'Untitled'}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-slate-400">Style</dt>
              <dd className="text-slate-100">{style.replace('_', ' ')}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-slate-400">Panels</dt>
              <dd className="text-slate-100">
                {panelCount} · {Math.ceil(panelCount / panelsPerPage)} page(s)
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-slate-400">Cast</dt>
              <dd className="text-right text-slate-100">
                {characters.length ? characters.map((character) => character.name).join(', ') : 'invented from the text'}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-slate-400">Exports</dt>
              <dd className="text-right text-slate-100">{formats.length ? formats.join(', ') : 'none'}</dd>
            </div>
          </dl>
        </Card>

        <Card title="How it works">
          <ol className="space-y-2 text-xs leading-relaxed text-slate-400">
            <li>1. The story is analysed for genre, cast and arc.</li>
            <li>2. Scenes are broken into one beat per panel.</li>
            <li>3. Your reference images become character sheets in vector memory.</li>
            <li>4. Each panel gets emotion, dialogue, a camera angle and a prompt.</li>
            <li>5. Panels render, then a CLIP-scored continuity check regenerates any that drifted.</li>
            <li>6. Pages are laid out, and the finished book is exported.</li>
          </ol>
        </Card>
      </aside>
    </div>
  )
}
