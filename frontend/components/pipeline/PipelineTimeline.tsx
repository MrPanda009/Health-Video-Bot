'use client'

import { useCallback, useEffect, useRef, useMemo, useState } from 'react'
import { SkipForward, X, Send } from 'lucide-react'
import { StageRow } from './StageRow'
import { TerminalOutput } from '@/components/terminal/TerminalOutput'
import {
  STAGES,
  STAGE_4_SUBSTAGES,
  getStageUIState,
} from '@/lib/pipeline-config'
import { useStageStream } from '@/hooks/useStageStream'
import type { Job, StageKey } from '@/lib/types'
import type { StreamParams } from '@/hooks/useStageStream'

interface PipelineTimelineProps {
  job: Job
  onJobUpdated: () => void
  autoStart?: boolean
  autoStartParams?: StreamParams
}

export function PipelineTimeline({ job, onJobUpdated, autoStart, autoStartParams }: PipelineTimelineProps) {
  const stream = useStageStream(job.job_id)
  const [customPmid, setCustomPmid] = useState('')

  const handleRun = useCallback(
    async (key: StageKey, params?: StreamParams) => {
      const res = await fetch(`/api/jobs/${job.job_id}/stage/${key}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'run', ...params }),
      })
      if (!res.ok) {
        const err = await res.json()
        alert(err.error ?? 'Failed to start stage')
        return
      }
      // Pass key directly — no React state timing dependency
      stream.start(key, params)
    },
    [job.job_id, stream],
  )

  const handleSkip = useCallback(
    async (key: StageKey | 'stage_4_group') => {
      try {
        const res = await fetch(`/api/jobs/${job.job_id}/stage/${key}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'skip' }),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          alert((err as { error?: string }).error ?? 'Skip failed')
          return
        }
        onJobUpdated()
      } catch {
        alert('Network error while skipping stage')
      }
    },
    [job.job_id, onJobUpdated],
  )

  // Auto-start stage 1 when the page opens from a freshly created job
  const hasAutoStarted = useRef(false)
  // Stable params reference so the effect doesn't re-fire on every render
  const stableParams = useMemo(() => autoStartParams, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!autoStart || hasAutoStarted.current || job.status !== 'created') return
    hasAutoStarted.current = true
    handleRun('stage_1', stableParams)
  }, [autoStart, job.status, handleRun, stableParams])

  // Refresh job state when the active stage's stream finishes
  const prevExitCode = useRef<number | null>(null)
  useEffect(() => {
    if (stream.exitCode !== null && stream.exitCode !== prevExitCode.current) {
      prevExitCode.current = stream.exitCode
      onJobUpdated()
    }
  }, [stream.exitCode, onJobUpdated])

  const activeStageLabel =
    STAGES.find((s) => s.key === stream.activeStage)?.label ?? stream.activeStage

  const mainStages = STAGES.filter(
    (s) => !STAGE_4_SUBSTAGES.includes(s.key as (typeof STAGE_4_SUBSTAGES)[number]),
  )
  const subStages = STAGES.filter((s) =>
    STAGE_4_SUBSTAGES.includes(s.key as (typeof STAGE_4_SUBSTAGES)[number]),
  )

  return (
    <div className="space-y-1">
      {mainStages.map((stage) => {
        const isAfterStage3 = stage.key === 'stage_5'
        return (
          <div key={stage.key}>
            {isAfterStage3 && (
              <div className="my-1 ml-2 rounded-lg border border-dashed border-zinc-200 p-2 dark:border-zinc-700">
                <div className="mb-1 flex items-center justify-between px-1">
                  <span className="text-xs font-medium text-zinc-500">
                    Stage 4 — Parallel Assets (4a + 4b + 4c + 4d)
                  </span>
                  <button
                    onClick={() => handleSkip('stage_4_group')}
                    title="Skip all of Stage 4 (set status to stage_4_complete)"
                    className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  >
                    <SkipForward size={11} />
                    Skip all
                  </button>
                </div>
                {subStages.map((sub) => (
                  <StageRow
                    key={sub.key}
                    stage={sub}
                    uiState={getStageUIState(sub, job.status, job.error?.stage, job)}
                    onRun={handleRun}
                    onSkip={(k) => handleSkip(k as StageKey)}
                    isRunning={stream.activeStage === sub.key && stream.isRunning}
                  />
                ))}
              </div>
            )}
            <StageRow
              stage={stage}
              uiState={getStageUIState(stage, job.status, job.error?.stage, job)}
              onRun={handleRun}
              onSkip={(k) => handleSkip(k as StageKey)}
              isRunning={stream.activeStage === stage.key && stream.isRunning}
            />
          </div>
        )
      })}

      {/* Persistent terminal panel — shown whenever a stream is active or has output */}
      {(stream.isRunning || stream.lines.length > 0) && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between px-1">
            <span className="text-xs font-medium text-zinc-500">
              {stream.isRunning ? `Running: ${activeStageLabel}` : `Finished: ${activeStageLabel}`}
            </span>
            <button
              onClick={stream.clear}
              title="Clear output"
              className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
            >
              <X size={11} />
              Clear
            </button>
          </div>

          {/* Study selector — shown when stage 1 is waiting for a choice */}
          {stream.awaitingInput && stream.activeStage === 'stage_1' && (
            <div className="mb-2 rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-800 dark:bg-blue-950">
              <p className="mb-2 text-xs font-medium text-blue-700 dark:text-blue-300">
                Select a study to continue:
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {['1', '2', '3'].map((n) => (
                  <button
                    key={n}
                    onClick={() => { setCustomPmid(''); stream.sendInput(n) }}
                    className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
                  >
                    Study {n}
                  </button>
                ))}
                <span className="text-xs text-blue-400">or paste a PMID:</span>
                <form
                  className="flex items-center gap-1"
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (customPmid.trim()) { stream.sendInput(customPmid.trim()); setCustomPmid('') }
                  }}
                >
                  <input
                    type="text"
                    value={customPmid}
                    onChange={(e) => setCustomPmid(e.target.value)}
                    placeholder="e.g. 38956175"
                    className="w-28 rounded border border-blue-300 bg-white px-2 py-1 text-xs text-zinc-900 placeholder-zinc-400 focus:outline-none dark:border-blue-700 dark:bg-zinc-900 dark:text-zinc-100"
                  />
                  <button
                    type="submit"
                    disabled={!customPmid.trim()}
                    className="rounded p-1 text-blue-600 hover:bg-blue-100 disabled:opacity-40 dark:hover:bg-blue-900"
                  >
                    <Send size={13} />
                  </button>
                </form>
              </div>
            </div>
          )}

          <TerminalOutput
            lines={stream.lines}
            isRunning={stream.isRunning}
            exitCode={stream.exitCode}
          />
        </div>
      )}
    </div>
  )
}
