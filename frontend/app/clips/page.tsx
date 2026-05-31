'use client'

import { useState } from 'react'
import { ShieldCheck, AlertTriangle, Clock, Film, RefreshCw } from 'lucide-react'
import { useClips } from '@/hooks/useClips'
import type { Clip, ClipStatus } from '@/lib/types'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDuration(sec: number | null): string {
  if (sec == null) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function fmtDate(iso: string | null): string {
  if (!iso) return 'Never'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function licenseColor(license: string): string {
  if (license.startsWith('pexels')) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
  if (license === 'pixabay') return 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300'
  return 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'
}

function statusColor(status: ClipStatus): string {
  if (status === 'active')  return 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
  if (status === 'missing') return 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
  return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
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

function TagPill({ tag }: { tag: string }) {
  return (
    <span className="inline-block rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
      {tag}
    </span>
  )
}

function ClipRow({ clip }: { clip: Clip }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <tr
      className="cursor-pointer border-b border-zinc-100 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/50"
      onClick={() => setExpanded((p) => !p)}
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-16 shrink-0 items-center justify-center rounded bg-zinc-200 dark:bg-zinc-700">
            <Film size={16} className="text-zinc-400" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
              {clip.filename}
            </p>
            <p className="truncate text-xs text-zinc-400">
              {clip.filepath.replace(/^.*\/assets\//, 'assets/')}
            </p>
          </div>
        </div>
        {expanded && (
          <div className="mt-3 space-y-2 rounded-lg bg-zinc-50 p-3 text-xs dark:bg-zinc-800/60">
            <div>
              <span className="text-zinc-500">Source URL: </span>
              <a
                href={clip.source_url.startsWith('http') ? clip.source_url : undefined}
                target="_blank"
                rel="noopener noreferrer"
                className="break-all text-blue-600 hover:underline dark:text-blue-400"
                onClick={(e) => e.stopPropagation()}
              >
                {clip.source_url}
              </a>
            </div>
            <div>
              <span className="text-zinc-500">Full path: </span>
              <span className="font-mono text-zinc-700 dark:text-zinc-300">{clip.filepath}</span>
            </div>
            <div>
              <span className="text-zinc-500">DB ID: </span>
              <span className="font-mono text-zinc-400">{clip.id}</span>
            </div>
            {clip.last_used_project && (
              <div>
                <span className="text-zinc-500">Last project: </span>
                <span className="font-mono text-zinc-700 dark:text-zinc-300">
                  {clip.last_used_project}
                </span>
              </div>
            )}
          </div>
        )}
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-700 dark:text-zinc-300">
        {clip.resolution ?? '—'}
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-700 dark:text-zinc-300">
        {fmtDuration(clip.duration_sec)}
      </td>

      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {[...clip.search_tags, ...clip.content_tags].slice(0, 4).map((t) => (
            <TagPill key={t} tag={t} />
          ))}
          {clip.search_tags.length + clip.content_tags.length > 4 && (
            <span className="text-xs text-zinc-400">
              +{clip.search_tags.length + clip.content_tags.length - 4}
            </span>
          )}
        </div>
      </td>

      <td className="whitespace-nowrap px-4 py-3">
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${licenseColor(clip.license_type)}`}>
          {clip.license_type}
        </span>
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-center">
        <span className={`inline-block min-w-[2rem] rounded-full px-2 py-0.5 text-xs font-semibold ${
          clip.times_used > 0
            ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
            : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400'
        }`}>
          {clip.times_used}
        </span>
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-500">
        {fmtDate(clip.last_used_at)}
      </td>

      <td className="whitespace-nowrap px-4 py-3">
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColor(clip.status)}`}>
          {clip.status}
        </span>
      </td>
    </tr>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

const STATUS_FILTERS: { label: string; value: string }[] = [
  { label: 'All',     value: 'all'     },
  { label: 'Active',  value: 'active'  },
  { label: 'Missing', value: 'missing' },
  { label: 'Deleted', value: 'deleted' },
]

export default function ClipsPage() {
  const [statusFilter, setStatusFilter] = useState('all')
  const [verifying, setVerifying]       = useState(false)
  const [verifyResult, setVerifyResult] = useState<{ missing_ids: string[] } | null>(null)

  const { clips, stats, isLoading, mutate } = useClips(statusFilter)

  async function handleVerify() {
    setVerifying(true)
    setVerifyResult(null)
    try {
      const res  = await fetch('/api/clips/verify', { method: 'POST' })
      const data = await res.json()
      setVerifyResult(data)
      mutate()
    } finally {
      setVerifying(false)
    }
  }

  const totalDuration = stats ? Math.round(stats.total_duration_sec) : 0

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="mx-auto max-w-7xl px-4 py-10">

        {/* Header */}
        <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
              Clip Library
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              All downloaded B-roll clips — reused across jobs to avoid duplicate downloads
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
              onClick={handleVerify}
              disabled={verifying}
              className="flex items-center gap-2 rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
            >
              <ShieldCheck size={15} />
              {verifying ? 'Checking…' : 'Verify Integrity'}
            </button>
          </div>
        </div>

        {/* Verify result banner */}
        {verifyResult && (
          <div className={[
            'mb-6 flex items-start gap-3 rounded-xl border p-4 text-sm',
            verifyResult.missing_ids.length > 0
              ? 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800/60 dark:bg-amber-950/30 dark:text-amber-300'
              : 'border-green-200 bg-green-50 text-green-800 dark:border-green-800/60 dark:bg-green-950/30 dark:text-green-300',
          ].join(' ')}>
            {verifyResult.missing_ids.length > 0 ? (
              <>
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <div>
                  <p className="font-medium">
                    {verifyResult.missing_ids.length} clip(s) marked missing — files not found on disk
                  </p>
                  <p className="mt-0.5 font-mono text-xs opacity-80">
                    {verifyResult.missing_ids.join(', ')}
                  </p>
                </div>
              </>
            ) : (
              <>
                <ShieldCheck size={16} className="mt-0.5 shrink-0" />
                <p className="font-medium">All active clips verified — every file exists on disk</p>
              </>
            )}
          </div>
        )}

        {/* Stats */}
        {stats && (
          <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard
              label="Total clips"
              value={stats.total}
              sub={`${stats.active} active`}
              icon={Film}
            />
            <StatCard
              label="Total duration"
              value={fmtDuration(totalDuration)}
              sub="across all clips"
              icon={Clock}
            />
            <StatCard
              label="Total uses"
              value={stats.total_uses ?? 0}
              sub={`${stats.unique_projects} project(s)`}
              icon={RefreshCw}
            />
            <StatCard
              label="Missing files"
              value={stats.missing}
              sub="run verify to update"
              icon={AlertTriangle}
              warn={(stats.missing ?? 0) > 0}
            />
          </div>
        )}

        {/* Filter tabs */}
        <div className="mb-4 flex gap-1 rounded-lg border border-zinc-200 bg-white p-1 dark:border-zinc-800 dark:bg-zinc-900 w-fit">
          {STATUS_FILTERS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setStatusFilter(value)}
              className={[
                'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                statusFilter === value
                  ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                  : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200',
              ].join(' ')}
            >
              {label}
              {value !== 'all' && stats && (
                <span className="ml-1.5 text-xs opacity-60">
                  {stats[value as keyof typeof stats] ?? 0}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Table */}
        <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          {isLoading ? (
            <div className="py-20 text-center text-sm text-zinc-400">Loading clips…</div>
          ) : clips.length === 0 ? (
            <div className="py-20 text-center">
              <Film size={32} className="mx-auto mb-3 text-zinc-300" />
              <p className="text-sm text-zinc-400">
                No clips found.{' '}
                {statusFilter === 'all'
                  ? 'Run Stage 4a on a job to populate the library.'
                  : `No ${statusFilter} clips.`}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-zinc-200 dark:border-zinc-700">
                    {['Clip', 'Resolution', 'Duration', 'Tags', 'License', 'Uses', 'Last used', 'Status'].map(
                      (h) => (
                        <th
                          key={h}
                          className="px-4 py-3 text-xs font-semibold uppercase tracking-wide text-zinc-500"
                        >
                          {h}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {clips.map((clip) => (
                    <ClipRow key={clip.id} clip={clip} />
                  ))}
                </tbody>
              </table>
              <div className="border-t border-zinc-100 px-4 py-2 text-right text-xs text-zinc-400 dark:border-zinc-800">
                {clips.length} clip{clips.length !== 1 ? 's' : ''}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
