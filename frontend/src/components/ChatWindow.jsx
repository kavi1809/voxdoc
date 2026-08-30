import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import VoiceButton from './VoiceButton'

const TOOL_LABELS = {
  search_documents: '🔍 searched documents',
  run_pandas_code: '📊 analysed spreadsheet',
}

function ToolBadges({ tools }) {
  if (!tools?.length) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {tools.map((t) => (
        <span
          key={t}
          className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700"
        >
          {TOOL_LABELS[t] || t}
        </span>
      ))}
    </div>
  )
}

export default function ChatWindow({ messages, onSend, sending, disabled }) {
  const [draft, setDraft] = useState('')
  const [speakAnswers, setSpeakAnswers] = useState(false)
  const bottomRef = useRef(null)
  const spokenRef = useRef(new Set())

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  // Read new assistant answers aloud. speechSynthesis is built into the browser,
  // so voice output costs nothing and needs no backend.
  useEffect(() => {
    if (!speakAnswers || !window.speechSynthesis) return
    const last = messages[messages.length - 1]
    if (!last || last.role !== 'assistant') return

    const key = `${messages.length}:${last.content.slice(0, 40)}`
    if (spokenRef.current.has(key)) return
    spokenRef.current.add(key)

    window.speechSynthesis.cancel()
    // Strip markdown so the synthesiser doesn't read out asterisks and backticks.
    const plain = last.content.replace(/[*_`#>|]/g, '').replace(/\s+/g, ' ')
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(plain))
  }, [messages, speakAnswers])

  useEffect(() => () => window.speechSynthesis?.cancel(), [])

  function submit(e) {
    e.preventDefault()
    const text = draft.trim()
    if (!text || sending || disabled) return
    setDraft('')
    onSend(text)
  }

  function toggleSpeech() {
    if (speakAnswers) window.speechSynthesis?.cancel()
    setSpeakAnswers((v) => !v)
  }

  return (
    <section className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
        <h2 className="font-semibold">Chat</h2>
        <button
          type="button"
          onClick={toggleSpeech}
          aria-pressed={speakAnswers}
          className={`btn px-2 py-1 text-xs ${
            speakAnswers ? 'bg-brand-600 text-white' : 'border border-slate-300 bg-white'
          }`}
          title="Read answers aloud"
        >
          {speakAnswers ? '🔊 Speaking on' : '🔇 Speaking off'}
        </button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {messages.length === 0 && (
          <div className="mt-10 text-center text-sm text-slate-500">
            <p className="text-2xl">💬</p>
            <p className="mt-2">Upload a document, then ask a question about it.</p>
            <p className="mt-1 text-xs">You can type, or press 🎤 to speak.</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${
                m.role === 'user'
                  ? 'bg-brand-600 text-white'
                  : 'border border-slate-200 bg-white text-slate-800'
              }`}
            >
              {m.role === 'assistant' ? (
                <div className="prose-answer">
                  <ReactMarkdown>{m.content}</ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{m.content}</p>
              )}
              {m.role === 'assistant' && <ToolBadges tools={m.tools_used} />}
            </div>
          </div>
        ))}

        {sending && (
          <div className="flex justify-start">
            <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <div className="flex gap-1">
                {[0, 150, 300].map((d) => (
                  <span
                    key={d}
                    className="h-2 w-2 animate-bounce rounded-full bg-slate-400"
                    style={{ animationDelay: `${d}ms` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={submit} className="flex items-center gap-2 border-t border-slate-200 p-3">
        <VoiceButton onTranscript={(t) => setDraft((d) => (d ? `${d} ${t}` : t))} disabled={disabled} />
        <input
          className="input flex-1"
          placeholder={disabled ? 'Create a workspace first' : 'Ask about your documents…'}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={disabled || sending}
          aria-label="Message"
        />
        <button type="submit" className="btn-primary" disabled={disabled || sending || !draft.trim()}>
          Send
        </button>
      </form>
    </section>
  )
}
