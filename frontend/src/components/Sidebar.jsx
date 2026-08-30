import { useState } from 'react'
import { useAuth } from '../context/AuthContext'

export default function Sidebar({ workspaces, activeId, onSelect, onCreate, onDelete }) {
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const { user, logout } = useAuth()

  async function submit(e) {
    e.preventDefault()
    const value = name.trim() || 'New workspace'
    setCreating(true)
    try {
      await onCreate(value)
      setName('')
    } finally {
      setCreating(false)
    }
  }

  return (
    <nav className="flex h-full w-60 flex-col bg-slate-900 text-slate-100">
      <div className="border-b border-slate-800 px-4 py-4">
        <h1 className="text-lg font-semibold">🎙️ Voxdoc</h1>
      </div>

      <form onSubmit={submit} className="space-y-2 border-b border-slate-800 p-3">
        <input
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-sm
                     text-slate-100 placeholder-slate-500 outline-none focus:border-brand-500"
          placeholder="New workspace name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="New workspace name"
        />
        <button type="submit" className="btn-primary w-full py-1.5 text-xs" disabled={creating}>
          {creating ? 'Creating…' : '+ New workspace'}
        </button>
      </form>

      <ul className="flex-1 space-y-1 overflow-y-auto p-2">
        {workspaces.length === 0 && (
          <li className="px-2 py-3 text-center text-xs text-slate-500">No workspaces yet.</li>
        )}
        {workspaces.map((ws) => (
          <li key={ws.id}>
            <div
              className={`group flex items-center gap-1 rounded-lg px-2.5 py-2 text-sm ${
                ws.id === activeId ? 'bg-brand-600' : 'hover:bg-slate-800'
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(ws.id)}
                className="min-w-0 flex-1 truncate text-left"
                aria-current={ws.id === activeId ? 'true' : undefined}
              >
                {ws.name}
              </button>
              <button
                type="button"
                onClick={() => onDelete(ws.id, ws.name)}
                className="shrink-0 rounded px-1 text-slate-400 opacity-0 hover:text-red-400
                           focus:opacity-100 group-hover:opacity-100"
                aria-label={`Delete workspace ${ws.name}`}
                title="Delete workspace"
              >
                ✕
              </button>
            </div>
          </li>
        ))}
      </ul>

      <div className="flex items-center justify-between border-t border-slate-800 px-3 py-3 text-xs">
        <span className="truncate text-slate-400">{user?.username}</span>
        <button type="button" onClick={logout} className="text-slate-300 hover:text-white">
          Sign out
        </button>
      </div>
    </nav>
  )
}
