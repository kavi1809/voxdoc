import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ChatWindow from '../components/ChatWindow'
import DocumentPanel from '../components/DocumentPanel'
import Sidebar from '../components/Sidebar'
import {
  createWorkspace,
  deleteWorkspace,
  errorMessage,
  fetchHistory,
  listDocuments,
  listWorkspaces,
  sendMessage,
} from '../services/api'

export default function Workspace() {
  const { workspaceId } = useParams()
  const navigate = useNavigate()

  const [workspaces, setWorkspaces] = useState([])
  const [documents, setDocuments] = useState([])
  const [messages, setMessages] = useState([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  // Load workspaces once, and land on one so the app is never in a dead state.
  useEffect(() => {
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list)
        if (!workspaceId && list.length) navigate(`/workspace/${list[0].id}`, { replace: true })
      })
      .catch((err) => setError(errorMessage(err, 'Could not load workspaces')))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const refreshDocuments = useCallback(async () => {
    if (!workspaceId) return
    setDocuments(await listDocuments(workspaceId))
  }, [workspaceId])

  // Reload the panel and transcript whenever the active workspace changes.
  useEffect(() => {
    if (!workspaceId) {
      setDocuments([])
      setMessages([])
      return
    }
    setError('')
    Promise.all([listDocuments(workspaceId), fetchHistory(workspaceId)])
      .then(([docs, history]) => {
        setDocuments(docs)
        setMessages(history)
      })
      .catch((err) => setError(errorMessage(err, 'Could not load this workspace')))
  }, [workspaceId])

  async function handleCreate(name) {
    try {
      const ws = await createWorkspace(name)
      setWorkspaces((prev) => [ws, ...prev])
      navigate(`/workspace/${ws.id}`)
    } catch (err) {
      setError(errorMessage(err, 'Could not create workspace'))
    }
  }

  async function handleDeleteWorkspace(id, name) {
    if (!window.confirm(`Delete "${name}" and everything in it? This cannot be undone.`)) return
    try {
      await deleteWorkspace(id)
      const remaining = workspaces.filter((w) => w.id !== id)
      setWorkspaces(remaining)
      if (id === workspaceId) {
        navigate(remaining.length ? `/workspace/${remaining[0].id}` : '/workspace', {
          replace: true,
        })
      }
    } catch (err) {
      setError(errorMessage(err, 'Could not delete workspace'))
    }
  }

  async function handleSend(text) {
    // Show the user's message immediately; the request may take a few seconds.
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setSending(true)
    setError('')
    try {
      const res = await sendMessage(workspaceId, text)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: res.answer, tools_used: res.tools_used },
      ])
    } catch (err) {
      const message = errorMessage(err, 'The assistant could not answer')
      setError(message)
      // Roll the optimistic message back out so the transcript stays truthful.
      setMessages((prev) => prev.slice(0, -1))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex h-full">
      <Sidebar
        workspaces={workspaces}
        activeId={workspaceId}
        onSelect={(id) => navigate(`/workspace/${id}`)}
        onCreate={handleCreate}
        onDelete={handleDeleteWorkspace}
      />

      <main className="grid min-w-0 flex-1 grid-cols-[20rem_1fr] bg-white">
        <DocumentPanel
          workspaceId={workspaceId}
          documents={documents}
          onChanged={refreshDocuments}
        />

        <div className="flex min-w-0 flex-col">
          {error && (
            <div role="alert" className="border-b border-red-200 bg-red-50 px-5 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
          {!workspaceId ? (
            <div className="flex flex-1 items-center justify-center text-center text-sm text-slate-500">
              <div>
                <p className="text-3xl">👈</p>
                <p className="mt-2">Create a workspace to get started.</p>
              </div>
            </div>
          ) : (
            <ChatWindow
              messages={messages}
              onSend={handleSend}
              sending={sending}
              disabled={!workspaceId}
            />
          )}
        </div>
      </main>
    </div>
  )
}
