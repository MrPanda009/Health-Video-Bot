'use client'

import { useState } from 'react'
import { X, AlertTriangle } from 'lucide-react'
import type { Job, JobStatus } from '@/lib/types'

const ALL_STATUSES: JobStatus[] = [
  'created',
  'stage_1_complete',
  'stage_2_complete',
  'stage_3_complete',
  'stage_4_complete',
  'stage_5_complete',
  'complete',
  'error',
]

interface StatusOverrideDialogProps {
  job: Job
  onClose: () => void
  onUpdated: () => void
}

export function StatusOverrideDialog({ job, onClose, onUpdated }: StatusOverrideDialogProps) {
  const [selected, setSelected] = useState<JobStatus>(job.status)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSave = async () => {
    if (selected === job.status) { onClose(); return }
    setSaving(true)
    setError('')
    try {
      const res = await fetch(`/api/jobs/${job.job_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: selected }),
      })
      if (!res.ok) {
        const d = await res.json()
        setError(d.error ?? 'Failed to update status')
        return
      }
      onUpdated()
      onClose()
    } catch (err) {
      setError(String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            Override Status
          </h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            <X size={16} />
          </button>
        </div>
        <div className="space-y-4 p-6">
          <div className="flex items-start gap-2 rounded-lg bg-amber-50 p-3 dark:bg-amber-950">
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-500" />
            <p className="text-xs text-amber-700 dark:text-amber-300">
              Manually overriding status may cause stage scripts to fail if prerequisite data is
              missing from the job.
            </p>
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              New status
            </label>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value as JobStatus)}
              className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 focus:border-blue-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            >
              {ALL_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-60"
            >
              {saving ? 'Saving…' : 'Override'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
