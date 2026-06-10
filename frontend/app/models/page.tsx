'use client'

import { useCallback, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  HardDrive,
  Loader2,
  RefreshCw,
  Terminal,
  XCircle,
} from 'lucide-react'
import { useModels } from '@/hooks/useModels'
import type { ModelInfo } from '@/hooks/useModels'
import { TerminalOutput } from '@/components/terminal/TerminalOutput'
import type { StageStreamEvent } from '@/lib/types'

// ─── Sub-components ───────────────────────────────────────────────────────────

function ModelTypeBadge({ type }: { type: ModelInfo['type'] }) {
  const styles =
    type === 'transcription'
      ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
      : 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300'
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}>
      {type}
    </span>
  )
}

function DownloadedBadge({ downloaded }: { downloaded: boolean }) {
  if (downloaded) {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-green-600 dark:text-green-400">
        <CheckCircle2 size={13} />
        Downloaded
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1 text-xs font-medium text-zinc-400 dark:text-zinc-500">
      <HardDrive size={13} />
      Not downloaded
    </span>
  )
}

function ModelCard({
  model,
  onDownload,
  isDownloading,
  whisperxInstalled,
}: {
  model: ModelInfo
  onDownload: (id: string) => void
  isDownloading: boolean
  whisperxInstalled: boolean
}) {
  const canDownload = whisperxInstalled && !model.downloaded && !isDownloading

  return (
    <div
      className={[
        'flex items-start justify-between gap-4 rounded-xl border p-4 transition-colors',
        model.downloaded
          ? 'border-green-200 bg-green-50 dark:border-green-900/60 dark:bg-green-950/20'
          : 'border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900',
      ].join(' ')}
    >
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-zinc-900 dark:text-zinc-100">{model.label}</span>
          <ModelTypeBadge type={model.type} />
          {model.language && (
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
              lang: {model.language}
            </span>
          )}
          <DownloadedBadge downloaded={model.downloaded} />
        </div>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">{model.description}</p>
        <p className="font-mono text-xs text-zinc-400 dark:text-zinc-600">{model.hf_repo}</p>
        <p className="text-xs text-zinc-400">~{model.size_gb} GB</p>
      </div>

      <button
        onClick={() => onDownload(model.id)}
        disabled={!canDownload}
        title={
          !whisperxInstalled
            ? 'whisperx must be installed before downloading models'
            : model.downloaded
            ? 'Already downloaded'
            : isDownloading
            ? 'Download in progress…'
            : `Download ${model.label}`
        }
        className={[
          'flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
          'disabled:cursor-not-allowed disabled:opacity-40',
          canDownload
            ? 'bg-blue-600 text-white hover:bg-blue-700'
            : model.downloaded
            ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
            : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
        ].join(' ')}
      >
        {isDownloading ? (
          <Loader2 size={14} className="animate-spin" />
        ) : model.downloaded ? (
          <CheckCircle2 size={14} />
        ) : (
          <Download size={14} />
        )}
        {isDownloading ? 'Downloading…' : model.downloaded ? 'Downloaded' : 'Download'}
      </button>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ModelsPage() {
  const { models, whisperxInstalled, fetchError, isLoading, mutate } = useModels()
  const [downloadingId, setDownloadingId] = useState<string | null>(null)
  const [terminalLines, setTerminalLines] = useState<string[]>([])
  const [terminalExitCode, setTerminalExitCode] = useState<number | null>(null)
  const transcriptionModels = models.filter((m) => m.type === 'transcription')
  const alignmentModels = models.filter((m) => m.type === 'alignment')

  const handleDownload = useCallback(
    async (modelId: string) => {
      setDownloadingId(modelId)
      setTerminalLines([])
      setTerminalExitCode(null)

      // Kick off the download — backend responds with a stream URL via POST
      let res: Response
      try {
        res = await fetch('/api/models/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ modelId }),
        })
      } catch (err) {
        setTerminalLines([`\x1b[31mNetwork error: ${err}\x1b[0m\n`])
        setDownloadingId(null)
        return
      }

      if (!res.ok || !res.body) {
        const txt = await res.text().catch(() => 'unknown error')
        setTerminalLines([`\x1b[31mFailed to start download: ${txt}\x1b[0m\n`])
        setDownloadingId(null)
        return
      }

      // Read the SSE stream directly from the response body
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const processEvents = (chunk: string) => {
        buffer += chunk
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''
        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data: ')) continue
          try {
            const event: StageStreamEvent = JSON.parse(line.slice(6))
            if (event.type === 'stdout' || event.type === 'stderr') {
              setTerminalLines((prev) => [...prev, event.data])
            } else if (event.type === 'exit') {
              setTerminalExitCode(event.exitCode ?? -1)
              setDownloadingId(null)
              mutate() // refresh model status
            } else if (event.type === 'error') {
              setTerminalLines((prev) => [...prev, `\x1b[31mERROR: ${event.data}\x1b[0m\n`])
              setDownloadingId(null)
            }
          } catch {
            // ignore malformed event
          }
        }
      }

      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          processEvents(decoder.decode(value, { stream: true }))
        }
      } catch {
        // stream aborted (e.g. user navigated away)
      } finally {
        if (downloadingId === modelId) {
          setDownloadingId(null)
        }
      }
    },
    [mutate, downloadingId],
  )

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="mx-auto max-w-4xl px-4 py-10">

        {/* Header */}
        <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
              WhisperX Models
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Download transcription and alignment models used by Stage 4d (captions).
            </p>
          </div>
          <button
            onClick={() => mutate()}
            title="Refresh status"
            className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-800"
          >
            <RefreshCw size={16} />
          </button>
        </div>

        {/* whisperx installation status */}
        <div
          className={[
            'mb-6 flex items-start gap-3 rounded-xl border p-4 text-sm',
            whisperxInstalled
              ? 'border-green-200 bg-green-50 text-green-800 dark:border-green-900/60 dark:bg-green-950/20 dark:text-green-300'
              : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800/60 dark:bg-amber-950/30 dark:text-amber-300',
          ].join(' ')}
        >
          {isLoading ? (
            <Loader2 size={16} className="mt-0.5 shrink-0 animate-spin" />
          ) : whisperxInstalled ? (
            <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
          ) : (
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          )}
          <div>
            {isLoading ? (
              <p className="font-medium">Checking whisperx installation…</p>
            ) : whisperxInstalled ? (
              <p className="font-medium">whisperx is installed</p>
            ) : (
              <>
                <p className="font-medium">whisperx is not installed</p>
                <p className="mt-0.5 opacity-80">
                  Stage 4d (captions) will fail until you install it:
                </p>
                <pre className="mt-1 rounded bg-amber-100 px-2 py-1 font-mono text-xs dark:bg-amber-900/40">
                  pip install whisperx
                </pre>
              </>
            )}
          </div>
        </div>

        {/* Fetch error */}
        {fetchError && (
          <div className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-800/60 dark:bg-red-950/30 dark:text-red-300">
            <XCircle size={16} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">Failed to load model status</p>
              <p className="mt-0.5 font-mono text-xs opacity-80">{fetchError}</p>
            </div>
          </div>
        )}

        {/* Transcription models */}
        {!isLoading && transcriptionModels.length > 0 && (
          <section className="mb-8">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
              Transcription Models
            </h2>
            <div className="space-y-3">
              {transcriptionModels.map((m) => (
                <ModelCard
                  key={m.id}
                  model={m}
                  onDownload={handleDownload}
                  isDownloading={downloadingId === m.id}
                  whisperxInstalled={whisperxInstalled}
                />
              ))}
            </div>
          </section>
        )}

        {/* Alignment models */}
        {!isLoading && alignmentModels.length > 0 && (
          <section className="mb-8">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
              Alignment Models
            </h2>
            <p className="mb-3 text-xs text-zinc-400">
              Required for word-level timestamps. Without the Hindi alignment model, Stage 4d will
              produce segment-level timestamps only (no word highlighting).
            </p>
            <div className="space-y-3">
              {alignmentModels.map((m) => (
                <ModelCard
                  key={m.id}
                  model={m}
                  onDownload={handleDownload}
                  isDownloading={downloadingId === m.id}
                  whisperxInstalled={whisperxInstalled}
                />
              ))}
            </div>
          </section>
        )}

        {/* Download terminal */}
        {(downloadingId !== null || terminalLines.length > 0) && (
          <section>
            <div className="mb-2 flex items-center gap-2">
              <Terminal size={14} className="text-zinc-400" />
              <span className="text-xs font-medium text-zinc-500">
                {downloadingId ? 'Downloading…' : 'Download output'}
              </span>
              {terminalExitCode !== null && (
                terminalExitCode === 0 ? (
                  <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                    <CheckCircle2 size={12} /> Success
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-red-600 dark:text-red-400">
                    <XCircle size={12} /> Failed (exit {terminalExitCode})
                  </span>
                )
              )}
            </div>
            <TerminalOutput
              lines={terminalLines}
              isRunning={downloadingId !== null}
              exitCode={terminalExitCode}
            />
          </section>
        )}

        {/* Empty state */}
        {!isLoading && !fetchError && models.length === 0 && (
          <div className="py-20 text-center">
            <HardDrive size={32} className="mx-auto mb-3 text-zinc-300" />
            <p className="text-sm text-zinc-400">No model data returned.</p>
          </div>
        )}

        {isLoading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={24} className="animate-spin text-zinc-400" />
          </div>
        )}
      </div>
    </div>
  )
}
