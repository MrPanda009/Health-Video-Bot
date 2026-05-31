'use client'

import { useState, useCallback } from 'react'
import { SkipForward } from 'lucide-react'
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
  const [activeStage, setActiveStage] = useState<StageKey | null>(null)
  const stream = useStageStream(job.job_id, activeStage)

  const handleRun = useCallback(
    async (key: StageKey, params?: StreamParams) => {
      // Validate + get stream URL from the server
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
      setActiveStage(key)
      stream.start(params)
    },
    [job.job_id, stream],
  )

  const handleSkip = useCallback(
    async (key: StageKey | 'stage_4_group') => {
      const res = await fetch(`/api/jobs/${job.job_id}/stage/${key}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'skip' }),
      })
      if (res.ok) onJobUpdated()
    },
    [job.job_id, onJobUpdated],
  )

  const mainStages = STAGES.filter(
    (s) => !STAGE_4_SUBSTAGES.includes(s.key as (typeof STAGE_4_SUBSTAGES)[number]),
  )
  const subStages = STAGES.filter((s) =>
    STAGE_4_SUBSTAGES.includes(s.key as (typeof STAGE_4_SUBSTAGES)[number]),
  )

  const stage4UIState = getStageUIState(
    { key: 'stage_4a', label: '', script: '', prerequisite: 'stage_3_complete', completedStatus: null },
    job.status,
    job.error?.stage,
  )

  return (
    <div className="space-y-1">
      {mainStages.map((stage) => {
        // Insert stage 4 sub-group after stage 3
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
                {subStages.map((sub) => {
                  const subState = getStageUIState(sub, job.status, job.error?.stage)
                  const isActive = activeStage === sub.key
                  return (
                    <StageRow
                      key={sub.key}
                      stage={sub}
                      uiState={subState}
                      onRun={handleRun}
                      onSkip={(k) => handleSkip(k as StageKey)}
                      streamLines={isActive ? stream.lines : []}
                      streamRunning={isActive && stream.isRunning}
                      streamExitCode={isActive ? stream.exitCode : null}
                      isActiveStream={isActive}
                    />
                  )
                })}
              </div>
            )}
            <StageRow
              stage={stage}
              uiState={getStageUIState(stage, job.status, job.error?.stage)}
              onRun={handleRun}
              onSkip={(k) => handleSkip(k as StageKey)}
              streamLines={activeStage === stage.key ? stream.lines : []}
              streamRunning={activeStage === stage.key && stream.isRunning}
              streamExitCode={activeStage === stage.key ? stream.exitCode : null}
              isActiveStream={activeStage === stage.key}
            />
          </div>
        )
      })}
      {/* Persistent terminal below the list when a stage is active but collapsed in StageRow */}
      {activeStage !== null && stream.lines.length === 0 && stream.isRunning && (
        <div className="mt-2">
          <TerminalOutput lines={[]} isRunning={true} exitCode={null} />
        </div>
      )}
    </div>
  )
}
