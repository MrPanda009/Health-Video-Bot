'use client'

import { useState, useCallback } from 'react'
import { useParams, useSearchParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, Settings2, ExternalLink, Trash2 } from 'lucide-react'
import { useJob } from '@/hooks/useJob'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { ErrorBanner } from '@/components/ui/ErrorBanner'
import { StatusOverrideDialog } from '@/components/ui/StatusOverrideDialog'
import { PipelineTimeline } from '@/components/pipeline/PipelineTimeline'
import { JobDataExplorer } from '@/components/explorer/JobDataExplorer'
import { CopyButton } from '@/components/terminal/CopyButton'

function RenderModeSelect({ jobId, initial }: { jobId: string; initial: 'draft' | 'final' }) {
  const [mode, setMode] = useState<'draft' | 'final'>(initial)
  const [saving, setSaving] = useState(false)

  async function onChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const next = e.target.value as 'draft' | 'final'
    setSaving(true)
    try {
      await fetch(`/api/jobs/${jobId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ render_mode: next }),
      })
      setMode(next)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-zinc-500">Render:</span>
      <select
        value={mode}
        onChange={onChange}
        disabled={saving}
        className={[
          'rounded border px-2 py-0.5 text-xs font-medium transition-colors focus:outline-none',
          mode === 'draft'
            ? 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
            : 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
          saving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
        ].join(' ')}
      >
        <option value="draft">Draft</option>
        <option value="final">Final</option>
      </select>
    </div>
  )
}

export default function JobDetailPage() {
  const router = useRouter()
  const { jobId } = useParams<{ jobId: string }>()
  const searchParams = useSearchParams()
  const autoStart = searchParams.get('autoStart') === 'true'
  const autoTopic = searchParams.get('topic') ?? undefined
  const autoPmid = searchParams.get('pmid') ?? undefined
  const [isRunning, setIsRunning] = useState(false)
  const [showOverride, setShowOverride] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleDelete = useCallback(async () => {
    if (!confirm('Delete this job and all its assets? This cannot be undone.')) return
    setDeleting(true)
    try {
      await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' })
      router.push('/jobs')
    } finally {
      setDeleting(false)
    }
  }, [jobId, router])
  const { job, isLoading, mutate } = useJob(jobId, isRunning)
  const handleJobUpdated = useCallback(() => {
    mutate()
    setIsRunning(false)
  }, [mutate])

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <p className="text-sm text-zinc-400">Loading…</p>
      </div>
    )
  }

  if (!job) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-zinc-50 dark:bg-zinc-950">
        <p className="text-sm text-zinc-500">Job not found.</p>
        <Link href="/jobs" className="text-sm text-blue-600 hover:underline">
          Back to jobs
        </Link>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="mx-auto max-w-4xl px-4 py-10">
        {/* Back nav */}
        <div className="mb-6">
          <Link
            href="/jobs"
            className="inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
          >
            <ArrowLeft size={14} />
            All Jobs
          </Link>
        </div>

        {/* Job Header */}
        <div className="mb-8 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={job.status} />
            <RenderModeSelect jobId={job.job_id} initial={job.render_mode ?? 'final'} />
            {job.output?.youtube_url && (
              <a
                href={job.output.youtube_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline dark:text-blue-400"
              >
                YouTube <ExternalLink size={11} />
              </a>
            )}
            <button
              onClick={() => setShowOverride(true)}
              className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-800"
            >
              <Settings2 size={12} />
              Override status
            </button>
          </div>

          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">
            {job.content?.title ?? job.study?.title ?? job.topic ?? 'Untitled Job'}
          </h1>

          {(job.study?.topic ?? job.topic) && (
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              Topic: {job.study?.topic ?? job.topic}
            </p>
          )}

          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-zinc-400">{job.job_id}</span>
            <CopyButton text={job.job_id} />
          </div>

          {job.error && <ErrorBanner error={job.error} />}
        </div>

        {/* Pipeline */}
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            Pipeline
          </h2>
          <div className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
            <PipelineTimeline
              job={job}
              onJobUpdated={handleJobUpdated}
              autoStart={autoStart}
              autoStartParams={autoStart ? { topic: autoTopic, pmid: autoPmid } : undefined}
            />
          </div>
        </section>

        {/* Data Explorer */}
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            Job Data
          </h2>
          <JobDataExplorer job={job} />
        </section>

        {/* Danger zone */}
        <section className="mt-8 border-t border-zinc-200 pt-8 dark:border-zinc-800">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            Danger Zone
          </h2>
          <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900 dark:bg-red-950/40">
            <div>
              <p className="text-sm font-medium text-red-700 dark:text-red-400">Delete this job</p>
              <p className="text-xs text-red-500 dark:text-red-500">
                Permanently removes the job file and all assets. Cannot be undone.
              </p>
            </div>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
            >
              <Trash2 size={14} />
              {deleting ? 'Deleting…' : 'Delete Job'}
            </button>
          </div>
        </section>
      </div>

      {showOverride && (
        <StatusOverrideDialog
          job={job}
          onClose={() => setShowOverride(false)}
          onUpdated={() => mutate()}
        />
      )}
    </div>
  )
}
