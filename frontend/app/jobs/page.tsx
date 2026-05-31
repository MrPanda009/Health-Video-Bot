'use client'

import { useState } from 'react'
import { Plus, RefreshCw } from 'lucide-react'
import { JobTable } from '@/components/jobs/JobTable'
import { NewJobDialog } from '@/components/jobs/NewJobDialog'
import { useJobs } from '@/hooks/useJobs'

export default function JobsPage() {
  const { jobs, isLoading, mutate } = useJobs()
  const [showDialog, setShowDialog] = useState(false)

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="mx-auto max-w-5xl px-4 py-10">
        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
              Health Video Bot
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
