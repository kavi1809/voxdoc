import { useState } from 'react'

const TYPE_ICONS = {
  pdf: '📕',
  docx: '📘',
  txt: '📄',
  csv: '📊',
  xlsx: '📊',
  url: '🔗',
}

export default function SummaryCard({ doc, onDelete, deleting }) {
  const [open, setOpen] = useState(false)

  return (
    <li className="card p-3">
      <div className="flex items-start gap-2">
        <span className="text-lg leading-none">{TYPE_ICONS[doc.type] || '📄'}</span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={doc.filename}>
            {doc.filename}
          </p>
          <p className="text-xs uppercase tracking-wide text-slate-400">{doc.type}</p>

          {doc.summary && (
            <>
              <p className={`mt-1 text-xs text-slate-600 ${open ? '' : 'line-clamp-2'}`}>
                {doc.summary}
              </p>
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="mt-1 text-xs font-medium text-brand-600 hover:underline"
                aria-expanded={open}
              >
                {open ? 'Show less' : 'Show more'}
              </button>
            </>
          )}
        </div>

        <button
          type="button"
          onClick={() => onDelete(doc.id)}
          disabled={deleting}
          className="shrink-0 rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
          aria-label={`Delete ${doc.filename}`}
          title="Delete"
        >
          ✕
        </button>
      </div>
    </li>
  )
}
