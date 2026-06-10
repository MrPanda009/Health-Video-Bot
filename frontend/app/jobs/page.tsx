'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, RefreshCw, Zap } from 'lucide-react'
import { JobTable } from '@/components/jobs/JobTable'
import { NewJobDialog } from '@/components/jobs/NewJobDialog'
import { useJobs } from '@/hooks/useJobs'

export default function JobsPage() {
  const { jobs, isLoading, mutate } = useJobs()
  const [showDialog, setShowDialog] = useState(false)
  const [autoStarting, setAutoStarting] = useState(false)
  const router = useRouter()

  const handleAutoStart = async () => {
    setAutoStarting(true)
    try {
      const res = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (!res.ok) return
      const data = await res.json()
      mutate()
      router.push(`/jobs/${data.job_id}?autoStart=true`)
    } finally {
      setAutoStarting(false)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="mx-auto max-w-7xl px-4 py-10">
        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
              Jobs
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Hindi health education video pipeline
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => mutate()}
              title="Refresh"
              className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-800"
            >
              <RefreshCw size={16} />
            </button>
            <button
              onClick={handleAutoStart}
              disabled={autoStarting}
              title="Auto-start: picks the least-recently-used topic and top available study"
              className="flex items-center gap-2 rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              <Zap size={15} />
              {autoStarting ? 'Starting…' : 'Auto'}
            </button>
            <button
              onClick={() => setShowDialog(true)}
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              <Plus size={15} />
              New Job
            </button>
          </div>
        </div>

        {/* Table */}
        {isLoading ? (
          <div className="py-16 text-center text-sm text-zinc-400">Loading jobs…</div>
        ) : (
          <JobTable jobs={jobs} />
        )}
      </div>

      {showDialog && (
        <NewJobDialog
          onClose={() => setShowDialog(false)}
          onCreated={() => {
            mutate()
            setTimeout(() => mutate(), 3000)
          }}
        />
      )}
    </div>
  )
}
