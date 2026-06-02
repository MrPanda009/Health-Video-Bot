import type { Job, JobStatus, StageDefinition, StageKey } from './types'

export const STATUS_ORDER: (JobStatus | 'created')[] = [
  'created',
  'stage_1_complete',
  'stage_2_complete',
  'stage_3_complete',
  'stage_4_complete',
  'stage_5_complete',
  'complete',
]

export const STAGES: StageDefinition[] = [
  {
    key: 'stage_1',
    label: 'Stage 1: PubMed Research',
    script: 'stages/stage_1_research.py',
    prerequisite: 'created',
    completedStatus: 'stage_1_complete',
    isComplete: (job) => !!job.study,
  },
  {
    key: 'stage_2',
    label: 'Stage 2: Claim Extraction',
    script: 'stages/stage_2_claim_extraction.py',
    prerequisite: 'stage_1_complete',
    completedStatus: 'stage_2_complete',
    isComplete: (job) => !!job.claims,
  },
  {
    key: 'stage_3',
    label: 'Stage 3: Content Generation',
    script: 'stages/stage_3_content_generation.py',
    prerequisite: 'stage_2_complete',
    completedStatus: 'stage_3_complete',
    isComplete: (job) => !!job.content,
  },
  {
    key: 'stage_4a',
    label: 'Stage 4a: B-roll Download',
    script: 'stages/stage_4a_broll.py',
    prerequisite: 'stage_3_complete',
    completedStatus: null,
    isComplete: (job) => Array.isArray(job.assets?.broll_video_paths) && job.assets.broll_video_paths.length > 0,
  },
  {
    key: 'stage_4b',
    label: 'Stage 4b: Thumbnail Generation',
    script: 'stages/stage_4b_thumbnail.py',
    prerequisite: 'stage_3_complete',
    completedStatus: null,
    isComplete: (job) => Array.isArray(job.assets?.thumbnail_paths) && job.assets.thumbnail_paths.length > 0,
  },
  {
    key: 'stage_4c',
    label: 'Stage 4c: Hindi Voiceover',
    script: 'stages/stage_4c_voiceover.py',
    prerequisite: 'stage_3_complete',
    completedStatus: null,
    isComplete: (job) => !!job.assets?.voiceover_path,
  },
  {
    key: 'stage_4d',
    label: 'Stage 4d: Whisper Captions',
    script: 'stages/stage_4d_captions.py',
    prerequisite: 'stage_3_complete',
    completedStatus: null,
    isComplete: (job) => !!job.assets?.srt_path,
  },
  {
    key: 'stage_5',
    label: 'Stage 5: FFmpeg Assembly',
    script: 'stages/stage_5_assembly.py',
    prerequisite: 'stage_4_complete',
    completedStatus: 'stage_5_complete',
  },
  {
    key: 'stage_6',
    label: 'Stage 6: YouTube Upload',
    script: 'stages/stage_6_upload.py',
    prerequisite: 'stage_5_complete',
    completedStatus: 'complete',
  },
]

export const STAGE_4_SUBSTAGES: StageKey[] = ['stage_4a', 'stage_4b', 'stage_4c', 'stage_4d']

export function getStageByKey(key: StageKey): StageDefinition | undefined {
  return STAGES.find((s) => s.key === key)
}

export function getStatusIndex(status: JobStatus | 'created'): number {
  return STATUS_ORDER.indexOf(status)
}

export type StageUIState = 'complete' | 'available' | 'locked' | 'error'

export function getStageUIState(
  stage: StageDefinition,
  jobStatus: JobStatus,
  errorStage?: string | null,
  job?: Job,
): StageUIState {
  if (jobStatus === 'error' && errorStage === stage.key) return 'error'

  const currentIdx = getStatusIndex(jobStatus)
  const prereqIdx = getStatusIndex(stage.prerequisite)

  if (stage.completedStatus) {
    const completedIdx = getStatusIndex(stage.completedStatus)
    if (currentIdx >= completedIdx) return 'complete'
    // Error state: status index is -1, so fall back to data-based completion check
    if (jobStatus === 'error' && stage.isComplete && job && stage.isComplete(job)) return 'complete'
  }

  // Sub-stages: use isComplete(job) if available, otherwise fall back to stage_4_complete
  if (!stage.completedStatus) {
    if (stage.isComplete && job && stage.isComplete(job)) return 'complete'
    const stage4Idx = getStatusIndex('stage_4_complete')
    if (currentIdx >= stage4Idx) return 'complete'
  }

  if (currentIdx >= prereqIdx) return 'available'
  return 'locked'
}

export const STATUS_LABELS: Record<JobStatus, string> = {
  created: 'Created',
  stage_1_complete: 'Stage 1 Done',
  stage_2_complete: 'Stage 2 Done',
  stage_3_complete: 'Stage 3 Done',
  stage_4_complete: 'Stage 4 Done',
  stage_5_complete: 'Stage 5 Done',
  complete: 'Complete',
  error: 'Error',
}

export const STATUS_COLORS: Record<JobStatus, string> = {
  created: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300',
  stage_1_complete: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  stage_2_complete: 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300',
  stage_3_complete: 'bg-violet-50 text-violet-700 dark:bg-violet-950 dark:text-violet-300',
  stage_4_complete: 'bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
  stage_5_complete: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
  complete: 'bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300',
  error: 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300',
}
