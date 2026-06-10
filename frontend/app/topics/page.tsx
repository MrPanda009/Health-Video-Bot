'use client'

import { useState } from 'react'
import { Tag, TrendingUp, BarChart2, RefreshCw, Plus, Trash2, AlertCircle } from 'lucide-react'
import { useTopics } from '@/hooks/useTopics'
import type { Topic } from '@/lib/types'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return 'Never'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
}: {
  label: string
  value: string | number
  sub?: string
  icon: React.ElementType
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mt-0.5 rounded-lg bg-zinc-100 p-2 dark:bg-zinc-800">
        <Icon size={16} className="text-zinc-500" />
      </div>
      <div>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
        <p className="text-xl font-bold text-zinc-900 dark:text-zinc-100">{value}</p>
        {sub && <p className="max-w-[160px] truncate text-xs text-zinc-400">{sub}</p>}
      </div>
    </div>
  )
}

function TopicRow({
  topic,
  onRemove,
}: {
  topic: Topic
  onRemove: (id: string) => void
}) {
  const [confirming, setConfirming] = useState(false)

  const handleRemove = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirming) { setConfirming(true); return }
    onRemove(topic.id)
  }

  return (
    <tr className={[
      'border-b border-zinc-100 dark:border-zinc-800',
      !topic.active ? 'opacity-40' : '',
    ].join(' ')}>
      <td className="px-4 py-3">
        <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{topic.name}</p>
        {!topic.active && <span className="text-xs italic text-zinc-400">removed</span>}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-center text-sm text-zinc-700 dark:text-zinc-300">
        {topic.times_used}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-500">
        {fmtDate(topic.last_used_at)}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-400">
        {fmtDate(topic.created_at)}
      </td>
      <td className="whitespace-nowrap px-4 py-3">
        {topic.active && (
          <button
            onClick={handleRemove}
            onBlur={() => setConfirming(false)}
            className={[
              'flex items-center gap-1.5 rounded px-2 py-1 text-xs transition-colors',
              confirming
                ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                : 'text-zinc-400 hover:bg-zinc-100 hover:text-red-500 dark:hover:bg-zinc-800',
            ].join(' ')}
          >
            <Trash2 size={12} />
            {confirming ? 'Confirm?' : 'Remove'}
          </button>
        )}
      </td>
    </tr>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TopicsPage() {
  const { topics, stats, isLoading, error, mutate } = useTopics()
  const [showInactive, setShowInactive] = useState(false)
  const [newName, setNewName] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState('')

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setAdding(true)
    setAddError('')
    try {
      const res = await fetch('/api/topics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const data = await res.json()
      if (!res.ok || !data.ok) {
        setAddError(data.error ?? 'Failed to add topic')
        return
      }
      setNewName('')
      mutate()
    } catch (e) {
      setAddError(String(e))
    } finally {
      setAdding(false)
    }
  }

  const handleRemove = async (id: string) => {
    try {
      await fetch('/api/topics', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
      mutate()
    } catch {
      // non-critical
    }
  }

  const visibleTopics = showInactive ? topics : topics.filter((t) => t.active)

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="mx-auto max-w-5xl px-4 py-10">

        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">Topics</h1>
            <p className="mt-1 text-sm text-zinc-500">
              PubMed search topics — Stage 1 auto-picks the least-recently-used topic
            </p>
          </div>
          <button
            onClick={() => mutate()}
            title="Refresh"
            className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-800"
          >
            <RefreshCw size={16} />
          </button>
        </div>

        {/* Stats */}
        {stats && (
          <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Active topics" value={stats.total_active}             icon={Tag} />
            <StatCard label="Total uses"    value={stats.total_uses}               icon={BarChart2} />
            <StatCard label="Most used"     value={stats.most_used ?? '—'}         sub={stats.most_used ?? undefined} icon={TrendingUp} />
            <StatCard label="Next up (LRU)" value={stats.least_used ?? '—'}        sub={stats.least_used ?? undefined} icon={Tag} />
          </div>
        )}

        {/* Add topic form */}
        <form onSubmit={handleAdd} className="mb-6">
          <div className="flex gap-2">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. vitamin D bone health RCT"
              className="flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 placeholder-zinc-400 focus:border-blue-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
            <button
              type="submit"
              disabled={adding || !newName.trim()}
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              <Plus size={15} />
              {adding ? 'Adding…' : 'Add topic'}
            </button>
          </div>
          {addError && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
              <AlertCircle size={12} />
              {addError}
            </div>
          )}
        </form>

        {/* Show inactive toggle */}
        <div className="mb-4 flex items-center justify-between">
          <p className="text-sm text-zinc-500">
            {visibleTopics.length} topic{visibleTopics.length !== 1 ? 's' : ''}
            {!showInactive && stats && stats.total_inactive > 0
              ? ` (${stats.total_inactive} removed hidden)`
              : ''}
          </p>
          {stats && stats.total_inactive > 0 && (
            <button
              onClick={() => setShowInactive((p) => !p)}
              className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
            >
              {showInactive ? 'Hide removed' : 'Show removed'}
            </button>
          )}
        </div>

        {/* Table */}
        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800/60 dark:bg-red-950/30 dark:text-red-300">
            {String(error)}
          </div>
        ) : isLoading ? (
          <div className="py-16 text-center text-sm text-zinc-400">Loading…</div>
        ) : visibleTopics.length === 0 ? (
          <div className="py-16 text-center text-sm text-zinc-400">No topics yet. Add one above.</div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <table className="w-full">
              <thead>
                <tr className="border-b border-zinc-100 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/50">
                  <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500">Topic</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-zinc-500">Times used</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500">Last used</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500">Added</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {visibleTopics.map((t) => (
                  <TopicRow key={t.id} topic={t} onRemove={handleRemove} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
