import { useRef, useState } from 'react'
import { deleteDocument, errorMessage, ingestUrl, uploadDocument } from '../services/api'
import SummaryCard from './SummaryCard'

const ACCEPT = '.pdf,.docx,.txt,.csv,.xlsx'

export default function DocumentPanel({ workspaceId, documents, onChanged }) {
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState(null)
  const [url, setUrl] = useState('')
  const [busyUrl, setBusyUrl] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [error, setError] = useState('')
  const fileInputRef = useRef(null)

  async function handleFiles(files) {
    if (!workspaceId || !files?.length) return
    setError('')
    for (const file of Array.from(files)) {
      try {
        setProgress({ name: file.name, percent: 0 })
        await uploadDocument(workspaceId, file, (p) =>
          setProgress({ name: file.name, percent: p }),
        )
        await onChanged()
      } catch (err) {
        setError(errorMessage(err, `Could not upload ${file.name}`))
      } finally {
        setProgress(null)
      }
    }
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleUrl(e) {
    e.preventDefault()
    const value = url.trim()
    if (!value || !workspaceId) return
    setError('')
    setBusyUrl(true)
    try {
      await ingestUrl(workspaceId, value)
      setUrl('')
      await onChanged()
    } catch (err) {
      setError(errorMessage(err, 'Could not fetch that URL'))
    } finally {
      setBusyUrl(false)
    }
  }

  async function handleDelete(docId) {
    setDeletingId(docId)
    setError('')
    try {
      await deleteDocument(docId)
      await onChanged()
    } catch (err) {
      setError(errorMessage(err, 'Could not delete that document'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <aside className="flex h-full flex-col border-r border-slate-200 bg-slate-50">
      <header className="border-b border-slate-200 px-4 py-3">
        <h2 className="font-semibold">Documents</h2>
      </header>

      <div className="space-y-3 border-b border-slate-200 p-4">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            handleFiles(e.dataTransfer.files)
          }}
          onClick={() => fileInputRef.current?.click()}
          className={`cursor-pointer rounded-xl border-2 border-dashed p-4 text-center text-sm transition ${
            dragging
              ? 'border-brand-500 bg-brand-50'
              : 'border-slate-300 bg-white hover:border-brand-300'
          } ${!workspaceId ? 'pointer-events-none opacity-50' : ''}`}
        >
          <p className="text-xl">📁</p>
          <p className="mt-1 font-medium">Drop a file or click to browse</p>
          <p className="mt-0.5 text-xs text-slate-500">PDF, DOCX, TXT, CSV, XLSX</p>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT}
            multiple
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />
        </div>

        {progress && (
          <div>
            <p className="truncate text-xs text-slate-600">
              Uploading {progress.name}… {progress.percent}%
            </p>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200">
              <div
                className="h-full rounded-full bg-brand-600 transition-all"
                style={{ width: `${progress.percent}%` }}
              />
            </div>
          </div>
        )}

        <form onSubmit={handleUrl} className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="https://example.com/article"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={!workspaceId || busyUrl}
            aria-label="URL to ingest"
          />
          <button type="submit" className="btn-ghost" disabled={!workspaceId || busyUrl || !url.trim()}>
            {busyUrl ? '…' : 'Add'}
          </button>
        </form>

        {error && (
          <p role="alert" className="rounded bg-red-50 px-2 py-1.5 text-xs text-red-700">
            {error}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {documents.length === 0 ? (
          <p className="text-center text-xs text-slate-500">No documents yet.</p>
        ) : (
          <ul className="space-y-2">
            {documents.map((doc) => (
              <SummaryCard
                key={doc.id}
                doc={doc}
                onDelete={handleDelete}
                deleting={deletingId === doc.id}
              />
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}
