'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowRight, Clock } from 'lucide-react'
import { StatusBadge } from '@/components/ui/StatusBadge'
import type { JobSummary } from '@/lib/types'

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

interface JobTableProps {
  jobs: JobSummary[]
}

export function JobTable({ jobs }: JobTableProps) {
  const router = useRouter()

  if (jobs.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-zinc-300 py-16 text-center dark:border-zinc-700">
        <p className="text-sm text-zinc-500">No jobs yet. Create your first job to get started.</p>
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900">
            <th className="px-4 py-3 text-left font-medium text-zinc-500">Topic</th>
            <th className="px-4 py-3 text-left font-medium text-zinc-500">Status</th>
            <th className="px-4 py-3 text-left font-medium text-zinc-500">Updated</th>
            <th className="px-4 py-3 text-left font-medium text-zinc-500">Job ID</th>
            <th className="px-4 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {jobs.map((job) => (
            <tr
              key={job.job_id}
              onClick={() => router.push(`/jobs/${job.job_id}`)}
              className="cursor-pointer transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-900"
            >
              <td className="max-w-xs px-4 py-3">
                <div className="truncate font-medium text-zinc-900 dark:text-zinc-100">
                  {job.title ?? job.topic ?? (
                    <span className="italic text-zinc-400">Untitled</span>
                  )}
                </div>
                {job.title && job.topic && (
                  <div className="truncate text-xs text-zinc-500">{job.topic}</div>
                )}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={job.status} />
              </td>
              <td className="px-4 py-3">
                <span className="flex items-center gap-1 text-zinc-500">
                  <Clock size={12} />
                  {relativeTime(job.updated_at)}
                </span>
              </td>
              <td className="px-4 py-3">
                <span className="font-mono text-xs text-zinc-400">
                  {job.job_id.slice(0, 8)}…
                </span>
              </td>
              <td className="px-4 py-3 text-right">
                <Link
                  href={`/jobs/${job.job_id}`}
                  onClick={(e) => e.stopPropagation()}
                  className="inline-flex items-center gap-1 text-blue-600 hover:underline dark:text-blue-400"
                >
                  Open <ArrowRight size={13} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
