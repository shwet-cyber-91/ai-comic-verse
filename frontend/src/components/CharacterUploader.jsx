import { useRef, useState } from 'react'

import api, { assetUrl } from '../api.js'
import { Spinner } from './ui.jsx'

/**
 * Collects 1-2 reference images per character.
 *
 * Files are uploaded immediately through POST /api/characters/refs, which
 * returns the storage-relative paths the generation request carries. That keeps
 * the create request small and makes the previews show the references used by
 * the continuity checker.
 */
export default function CharacterUploader({ characters, onChange }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const inputRef = useRef(null)

  async function handleFiles(files) {
    if (!files?.length) return
    if (!name.trim()) {
      setError('Give the character a name before adding reference images.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const character = await api.uploadReferences(name.trim(), description, files)
      onChange([...characters, character])
      setName('')
      setDescription('')
      if (inputRef.current) inputRef.current.value = ''
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function remove(target) {
    onChange(characters.filter((character) => character !== target))
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="label">Character name</span>
          <input
            className="input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Mira"
            maxLength={64}
          />
        </label>
        <label className="block">
          <span className="label">Short description (optional)</span>
          <input
            className="input"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="patched flight jacket, copper goggles"
            maxLength={280}
          />
        </label>
      </div>

      <div
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          handleFiles(event.dataTransfer.files)
        }}
        className="rounded-xl border border-dashed border-white/20 bg-white/5 px-4 py-5 text-center"
      >
        <p className="text-sm text-slate-300">
          Drop 1-2 reference images here, or{' '}
          <label className="cursor-pointer font-semibold text-accent underline">
            browse
            <input
              ref={inputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/bmp"
              multiple
              className="hidden"
              onChange={(event) => handleFiles(event.target.files)}
            />
          </label>
        </p>
        <p className="mt-1 text-xs text-slate-500">
          A face and full-body image give the continuity checker more visual detail.
        </p>
        {busy ? (
          <p className="mt-3 inline-flex items-center gap-2 text-sm text-slate-300">
            <Spinner className="h-4 w-4" /> uploading…
          </p>
        ) : null}
      </div>

      {error ? <p className="text-sm text-rose-300">{error}</p> : null}

      {characters.length ? (
        <ul className="grid gap-3 sm:grid-cols-2">
          {characters.map((character) => (
            <li key={`${character.name}-${character.reference_images[0]}`} className="card flex gap-3 p-3">
              <img
                src={assetUrl(character.reference_images[0])}
                alt={`${character.name} reference`}
                className="h-20 w-20 shrink-0 rounded-lg border border-white/10 object-cover"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate font-semibold text-white">{character.name}</p>
                  <button
                    type="button"
                    className="ml-auto text-xs text-slate-400 hover:text-rose-300"
                    onClick={() => remove(character)}
                  >
                    remove
                  </button>
                </div>
                {character.description ? (
                  <p className="mt-1 line-clamp-2 text-xs text-slate-400">{character.description}</p>
                ) : null}
                <p className="mt-1 text-[11px] text-slate-500">
                  {character.reference_images.length} reference image
                  {character.reference_images.length === 1 ? '' : 's'}
                </p>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-slate-500">
          No characters yet — the pipeline will infer a cast from the story text. Add names and
          descriptions to guide Pollinations image generation.
        </p>
      )}
    </div>
  )
}
