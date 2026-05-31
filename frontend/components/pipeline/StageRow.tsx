'use client'

import {
  CheckCircle2,
  Circle,
  Loader2,
  Play,
  SkipForward,
  XCircle,
} from 'lucide-react'
import type { StageDefinition, StageKey } from '@/lib/types'
import type { StageUIState } from '@/lib/pipeline-config'
import type { StreamParams } from '@/hooks/useStageStream'

interface StageRowProps {
  stage: StageDefinition
  uiState: StageUIState
  onRun: (key: StageKey, params?: StreamParams) => void
  onSkip: (key: StageKey) => void
  isRunning: boolean
}

export function StageRow({ stage, uiState, onRun, onSkip, isRunning }: StageRowProps) {
  const icon = {
    complete: <CheckCircle2 size={18} className="text-green-500" />,
    available: <Circle size={18} className="text-zinc-400" />,
    locked: <Circle size={18} className="text-zinc-300 dark:text-zinc-600" />,
    error: <XCircle size={18} className="text-red-500" />,
  }[uiState]

  return (
    <div className="flex items-center gap-3 rounded-lg px-3 py-2.5 hover:bg-zinc-50 dark:hover:bg-zinc-900">
      <div className="shrink-0">
        {isRunning ? (
          <Loader2 size={18} className="animate-spin text-blue-500" />
        ) : (
          icon
        )}
      </div>
      <span
        className={`flex-1 text-sm ${
          uiState === 'locked'
            ? 'text-zinc-400 dark:text-zinc-600'
            : 'text-zinc-800 dark:text-zinc-200'
        }`}
      >
        {stage.label}
      </span>
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => onRun(stage.key)}
          disabled={uiState === 'locked' || isRunning}
          title={uiState === 'locked' ? 'Prerequisites not met' : 'Run this stage'}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 enabled:bg-blue-600 enabled:text-white enabled:hover:bg-blue-700"
        >
          <Play size={11} />
          Run
        </button>
        <button
          onClick={() => onSkip(stage.key)}
          disabled={isRunning}
          title="Skip this stage (advance status without running)"
          className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 enabled:bg-zinc-100 enabled:text-zinc-700 enabled:hover:bg-zinc-200 dark:enabled:bg-zinc-800 dark:enabled:text-zinc-300 dark:enabled:hover:bg-zinc-700"
        >
          <SkipForward size={11} />
          Skip
        </button>
      </div>
    </div>
  )
}
