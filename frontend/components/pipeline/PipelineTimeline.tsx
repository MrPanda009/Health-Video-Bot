'use client'

import { useCallback, useEffect, useRef } from 'react'
import { SkipForward, X } from 'lucide-react'
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
}

export function PipelineTimeline({ job, onJobUpdated }: PipelineTimelineProps) {
  const stream = useStageStream(job.job_id)

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
                    uiState={getStageUIState(sub, job.status, job.error?.stage)}
                    onRun={handleRun}
                    onSkip={(k) => handleSkip(k as StageKey)}
                    isRunning={stream.activeStage === sub.key && stream.isRunning}
                  />
                ))}
              </div>
            )}
            <StageRow
              stage={stage}
              uiState={getStageUIState(stage, job.status, job.error?.stage)}
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
