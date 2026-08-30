import { useEffect, useRef, useState } from 'react'
import { transcribeAudio } from '../services/api'

// Chrome/Edge/Safari expose the Web Speech API. It transcribes on-device or via
// the browser vendor at no cost to us, so we prefer it and only fall back to the
// Gemini endpoint (a paid API call) on browsers that lack it, mainly Firefox.
const SpeechRecognition =
  typeof window !== 'undefined' &&
  (window.SpeechRecognition || window.webkitSpeechRecognition)

export default function VoiceButton({ onTranscript, disabled }) {
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const recognitionRef = useRef(null)
  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])

  // Stop any capture still running when the component goes away.
  useEffect(() => {
    return () => {
      recognitionRef.current?.stop?.()
      if (mediaRecorderRef.current?.state === 'recording') {
        mediaRecorderRef.current.stop()
        mediaRecorderRef.current.stream?.getTracks().forEach((t) => t.stop())
      }
    }
  }, [])

  function startNative() {
    const recognition = new SpeechRecognition()
    recognition.lang = 'en-US'
    recognition.interimResults = false
    recognition.maxAlternatives = 1

    recognition.onresult = (event) => {
      const text = event.results[0][0].transcript
      if (text) onTranscript(text)
    }
    recognition.onerror = (event) => {
      setError(
        event.error === 'not-allowed'
          ? 'Microphone permission denied'
          : `Could not hear you (${event.error})`,
      )
    }
    recognition.onend = () => setRecording(false)

    recognitionRef.current = recognition
    recognition.start()
    setRecording(true)
  }

  async function startFallback() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const recorder = new MediaRecorder(stream)
    chunksRef.current = []

    recorder.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data)
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop())
      setRecording(false)
      setBusy(true)
      try {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        const { text } = await transcribeAudio(blob)
        if (text) onTranscript(text)
        else setError('Nothing was transcribed')
      } catch {
        setError('Transcription failed')
      } finally {
        setBusy(false)
      }
    }

    mediaRecorderRef.current = recorder
    recorder.start()
    setRecording(true)
  }

  async function toggle() {
    setError('')
    if (recording) {
      recognitionRef.current?.stop?.()
      if (mediaRecorderRef.current?.state === 'recording') mediaRecorderRef.current.stop()
      setRecording(false)
      return
    }
    try {
      if (SpeechRecognition) startNative()
      else await startFallback()
    } catch {
      setError('Could not access the microphone')
      setRecording(false)
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={toggle}
        disabled={disabled || busy}
        aria-pressed={recording}
        aria-label={recording ? 'Stop recording' : 'Ask by voice'}
        title={recording ? 'Stop recording' : 'Ask by voice'}
        className={`btn h-10 w-10 rounded-full p-0 ${
          recording
            ? 'animate-pulse bg-red-600 text-white hover:bg-red-700'
            : 'border border-slate-300 bg-white text-slate-600 hover:bg-slate-50'
        }`}
      >
        {busy ? '…' : '🎤'}
      </button>
      {error && (
        <span className="absolute bottom-full left-1/2 mb-1 w-44 -translate-x-1/2 rounded bg-red-50 px-2 py-1 text-center text-xs text-red-700">
          {error}
        </span>
      )}
    </div>
  )
}
