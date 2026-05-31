'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, Settings2, ExternalLink } from 'lucide-react'
import { useJob } from '@/hooks/useJob'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { ErrorBanner } from '@/components/ui/ErrorBanner'
import { StatusOverrideDialog } from '@/components/ui/StatusOverrideDialog'
import { PipelineTimeline } from '@/components/pipeline/PipelineTimeline'
import { JobDataExplorer } from '@/components/explorer/JobDataExplorer'
import { CopyButton } from '@/components/terminal/CopyButton'

export default function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const [isRunning, setIsRunning] = useState(false)
  const [showOverride, setShowOverride] = useState(false)
  const { job, isLoading, mutate } = useJob(jobId, isRunning)

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
            {job.content?.title ?? job.study?.title ?? 'Untitled Job'}
          </h1>

          {job.study?.topic && (
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              Topic: {job.study.topic}
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
              onJobUpdated={() => {
                mutate()
                setIsRunning(false)
              }}
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
