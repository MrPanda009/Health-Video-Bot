'use client'

import { useState } from 'react'
import { BookOpen, Clock, CheckCircle, RefreshCw, ExternalLink } from 'lucide-react'
import { useStudies } from '@/hooks/useStudies'
import type { StudyEntry, StudyEntryStatus } from '@/lib/types'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

function statusColor(status: StudyEntryStatus): string {
  if (status === 'active')
    return 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
  return 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  warn,
}: {
  label: string
  value: string | number
  sub?: string
  icon: React.ElementType
  warn?: boolean
}) {
  return (
    <div className={[
      'flex items-start gap-3 rounded-xl border p-4',
      warn
        ? 'border-amber-200 bg-amber-50 dark:border-amber-800/60 dark:bg-amber-950/30'
        : 'border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900',
    ].join(' ')}>
      <div className={[
        'mt-0.5 rounded-lg p-2',
        warn ? 'bg-amber-100 dark:bg-amber-900/40' : 'bg-zinc-100 dark:bg-zinc-800',
      ].join(' ')}>
        <Icon size={16} className={warn ? 'text-amber-600 dark:text-amber-400' : 'text-zinc-500'} />
      </div>
      <div>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
        <p className="text-xl font-bold text-zinc-900 dark:text-zinc-100">{value}</p>
        {sub && <p className="text-xs text-zinc-400">{sub}</p>}
      </div>
    </div>
  )
}

function StudyRow({ study }: { study: StudyEntry }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <tr
      className="cursor-pointer border-b border-zinc-100 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/50"
      onClick={() => setExpanded((p) => !p)}
    >
      <td className="px-4 py-3">
        <div className="min-w-0">
          <p className="line-clamp-2 text-sm font-medium text-zinc-900 dark:text-zinc-100">
            {study.title}
          </p>
          <p className="mt-0.5 text-xs text-zinc-400">
            {study.authors.slice(0, 2).join(', ')}{study.authors.length > 2 ? ' et al.' : ''}
          </p>
        </div>
        {expanded && (
          <div className="mt-3 space-y-1.5 rounded-lg bg-zinc-50 p-3 text-xs dark:bg-zinc-800/60">
            <div>
              <span className="text-zinc-500">PMID: </span>
              <a
                href={`https://pubmed.ncbi.nlm.nih.gov/${study.pmid}/`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-blue-600 hover:underline dark:text-blue-400"
                onClick={(e) => e.stopPropagation()}
              >
                {study.pmid}
              </a>
            </div>
            {study.doi && (
              <div>
                <span className="text-zinc-500">DOI: </span>
                <span className="font-mono text-zinc-700 dark:text-zinc-300">{study.doi}</span>
              </div>
            )}
            {study.last_used_job && (
              <div>
                <span className="text-zinc-500">Job: </span>
                <a
                  href={`/jobs/${study.last_used_job}`}
                  className="font-mono text-blue-600 hover:underline dark:text-blue-400"
                  onClick={(e) => e.stopPropagation()}
                >
                  {study.last_used_job.slice(0, 8)}…
                </a>
              </div>
            )}
          </div>
        )}
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-500">
        <span className="block max-w-[140px] truncate">{study.topic}</span>
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-500">
        {study.journal
          ? <span className="block max-w-[120px] truncate">{study.journal}</span>
          : '—'}
        {study.year && <span className="block text-zinc-400">{study.year}</span>}
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-500">
        {fmtDate(study.last_used_at)}
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-500">
        {study.status === 'cooldown' ? fmtDate(study.cooldown_until) : '—'}
      </td>

      <td className="whitespace-nowrap px-4 py-3">
        <div className="flex items-center gap-2">
          <span className={[
            'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
            statusColor(study.status),
          ].join(' ')}>
            {study.status === 'cooldown' ? 'In cooldown' : 'Available'}
          </span>
          <a
            href={`https://pubmed.ncbi.nlm.nih.gov/${study.pmid}/`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink size={12} />
          </a>
        </div>
      </td>
    </tr>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type FilterTab = 'all' | 'active' | 'cooldown'

export default function StudiesPage() {
  const [filter, setFilter] = useState<FilterTab>('all')
  const { studies, stats, isLoading, error, mutate } = useStudies(filter)

  const tabs: { key: FilterTab; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'active', label: 'Available' },
    { key: 'cooldown', label: 'In cooldown' },
  ]

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="mx-auto max-w-7xl px-4 py-10">

        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">Study History</h1>
            <p className="mt-1 text-sm text-zinc-500">PubMed studies used in video jobs</p>
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
          <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-3">
            <StatCard label="Total studied"  value={stats.total}       icon={BookOpen} />
            <StatCard label="Available"      value={stats.active}      icon={CheckCircle} />
            <StatCard label="In cooldown"    value={stats.in_cooldown} icon={Clock} warn={stats.in_cooldown > 0} />
          </div>
        )}

        {/* Filter tabs */}
        <div className="mb-4 flex w-fit gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setFilter(t.key)}
              className={[
                'rounded-md px-3 py-1.5 text-sm transition-colors',
                filter === t.key
                  ? 'bg-white font-medium text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-100'
                  : 'text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300',
              ].join(' ')}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Table */}
        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800/60 dark:bg-red-950/30 dark:text-red-300">
            {String(error)}
          </div>
        ) : isLoading ? (
          <div className="py-16 text-center text-sm text-zinc-400">Loading…</div>
        ) : studies.length === 0 ? (
          <div className="py-16 text-center text-sm text-zinc-400">
            No studies found.{filter !== 'all' && ' Try switching to "All".'}
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <table className="w-full">
              <thead>
                <tr className="border-b border-zinc-100 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/50">
                  <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500">Title</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500">Topic</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500">Journal</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500">Last used</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500">Cooldown until</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500">Status</th>
                </tr>
              </thead>
              <tbody>
                {studies.map((s) => <StudyRow key={s.pmid} study={s} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
