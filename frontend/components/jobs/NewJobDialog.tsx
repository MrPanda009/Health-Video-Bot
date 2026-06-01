'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { X, Info, Monitor, Smartphone } from 'lucide-react'

interface NewJobDialogProps {
  onClose: () => void
  onCreated: () => void
}

type AspectRatio = '9:16' | '16:9'

const ASPECT_OPTIONS: { value: AspectRatio; label: string; sub: string; Icon: typeof Monitor }[] =
  [
    {
      value: '9:16',
      label: 'Shorts (9:16)',
      sub: '1080 × 1920',
      Icon: Smartphone,
    },
    {
      value: '16:9',
      label: 'Landscape (16:9)',
      sub: '1920 × 1080',
      Icon: Monitor,
    },
  ]

export function NewJobDialog({ onClose, onCreated }: NewJobDialogProps) {
  const router = useRouter()
  const [topic, setTopic] = useState('')
  const [pmid, setPmid] = useState('')
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>('9:16')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const res = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: topic.trim() || undefined,
          pmid: pmid.trim() || undefined,
          aspect_ratio: aspectRatio,
        }),
      })
      if (!res.ok) {
        const d = await res.json()
        setError(d.error ?? 'Failed to create job')
        return
      }
      const data = await res.json()
      onCreated()
      onClose()
      const qs = new URLSearchParams({ autoStart: 'true' })
      if (topic.trim()) qs.set('topic', topic.trim())
      if (pmid.trim()) qs.set('pmid', pmid.trim())
      router.push(`/jobs/${data.job_id}?${qs.toString()}`)
    } catch (err) {
      setError(String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            New Job — Stage 1
          </h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            <X size={16} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4 p-6">
          {/* Aspect ratio picker */}
          <div>
            <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              Output format
            </label>
            <div className="grid grid-cols-2 gap-2">
              {ASPECT_OPTIONS.map(({ value, label, sub, Icon }) => {
                const selected = aspectRatio === value
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setAspectRatio(value)}
                    className={[
                      'flex flex-col items-center gap-1.5 rounded-lg border px-4 py-3 text-sm transition-colors',
                      selected
                        ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300'
                        : 'border-zinc-200 text-zinc-600 hover:border-zinc-300 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800/50',
                    ].join(' ')}
                  >
                    <Icon size={20} />
                    <span className="font-medium">{label}</span>
                    <span className="text-xs opacity-70">{sub}</span>
                  </button>
                )
              })}
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              Topic <span className="font-normal text-zinc-400">(optional)</span>
            </label>
            <input
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g. gut microbiome and diabetes"
              className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 placeholder-zinc-400 focus:border-blue-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              PubMed ID <span className="font-normal text-zinc-400">(optional)</span>
            </label>
            <input
              type="text"
              value={pmid}
              onChange={(e) => setPmid(e.target.value)}
              placeholder="e.g. 38452901"
              className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 placeholder-zinc-400 focus:border-blue-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
          </div>
          <div className="flex items-start gap-2 rounded-lg bg-blue-50 p-3 dark:bg-blue-950">
            <Info size={14} className="mt-0.5 shrink-0 text-blue-500" />
            <p className="text-xs text-blue-700 dark:text-blue-300">
              If PMID is provided, Stage 1 runs non-interactively. Without a PMID, it auto-selects
              the top-ranked study after ~20 seconds. Watch the stage output for details.
            </p>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {submitting ? 'Starting…' : 'Start Stage 1'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
