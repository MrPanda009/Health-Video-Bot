export type JobStatus =
  | 'created'
  | 'stage_1_complete'
  | 'stage_2_complete'
  | 'stage_3_complete'
  | 'stage_4_complete'
  | 'stage_5_complete'
  | 'complete'
  | 'error'

export type StageKey =
  | 'stage_1'
  | 'stage_2'
  | 'stage_3'
  | 'stage_4a'
  | 'stage_4b'
  | 'stage_4c'
  | 'stage_4d'
  | 'stage_5'
  | 'stage_6'

export interface JobError {
  stage: string
  message: string
  retries: number
}

export interface Study {
  topic: string
  pubmed_query: string
  pmid: string
  doi: string | null
  title: string
  authors: string[]
  journal: string
  year: number
  study_type: 'meta_analysis' | 'systematic_review' | 'rct' | 'cohort' | 'cross_sectional' | 'other'
  abstract: string
  full_text_available: boolean
  pdf_path: string | null
  screenshot_paths: string[]
  industry_funded: boolean | null
  funding_source: string | null
}

export interface Claims {
  core_finding: string
  effect_size: string | null
  sample_size: number
  population_description: string
  follow_up_duration: string | null
  primary_limitations: string[]
  what_study_does_not_prove: string
  key_stats: Record<string, string>
  is_causal_language_safe: boolean
  small_study_flag: boolean
  below_minimum_sample: boolean
  industry_funded_flag: boolean
  validation_warnings: string[]
}

export interface ScriptSegment {
  name: string
  hindi_text: string
  duration_hint_seconds: number
  broll_mood: string
}

export interface BrollSearchTag {
  segment_name: string
  search_terms: string[]
}

export interface ThumbnailPrompt {
  variant_id: string
  prompt: string
}

export interface ChapterTimestamp {
  title: string
  estimated_start_seconds: number
}

export interface Content {
  hindi_script: string
  script_segments: ScriptSegment[]
  title: string
  description: string
  tags: string[]
  broll_search_tags: BrollSearchTag[]
  thumbnail_prompts: ThumbnailPrompt[]
  chapter_timestamps: ChapterTimestamp[]
  validation_passed: boolean
  validation_notes: string[]
}

export interface BrollVideoPath {
  segment_name: string
  paths: string[]
}

export interface ThumbnailPath {
  variant_id: string
  path: string
}

export interface Assets {
  broll_video_paths: BrollVideoPath[]
  broll_missing_segments: string[]
  thumbnail_paths: ThumbnailPath[]
  voiceover_path: string | null
  voiceover_duration_seconds: number | null
  srt_path: string | null
  ass_path: string | null
  whisper_word_timestamps: unknown[]
  background_music_path: string | null
}

export interface QualityChecks {
  duration_in_range: boolean
  disclaimer_present: boolean
  audio_peak_ok: boolean
  audio_avg_ok: boolean
  all_passed: boolean
}

export interface Output {
  final_video_path: string | null
  final_video_duration_seconds: number | null
  quality_checks: QualityChecks | null
  youtube_upload_id: string | null
  youtube_url: string | null
  scheduled_publish_time: string | null
  thumbnails_uploaded: boolean
  srt_uploaded: boolean
}

export interface Job {
  job_id: string
  created_at: string
  updated_at: string
  status: JobStatus
  aspect_ratio: '9:16' | '16:9'
  render_mode?: 'draft' | 'final'
  topic?: string | null
  error: JobError | null
  study: Study | null
  claims: Claims | null
  content: Content | null
  assets: Assets | null
  output: Output | null
}

export interface JobSummary {
  job_id: string
  status: JobStatus
  created_at: string
  updated_at: string
  topic: string | null
  title: string | null
  render_mode: 'draft' | 'final'
  error: JobError | null
}

export interface StageDefinition {
  key: StageKey
  label: string
  script: string
  prerequisite: JobStatus | 'created'
  completedStatus: JobStatus | null
  /** For sub-stages that don't set a job status, derive completion from job data. */
  isComplete?: (job: Job) => boolean
}

export interface StageStreamEvent {
  type: 'stdout' | 'stderr' | 'exit' | 'error' | 'awaiting_input'
  data: string
  exitCode?: number
}

// ─── Clip library ─────────────────────────────────────────────────────────────

export type ClipStatus = 'active' | 'missing' | 'deleted'

export interface Clip {
  id: string
  filename: string
  filepath: string
  source_url: string
  search_tags: string[]
  content_tags: string[]
  resolution: string | null
  duration_sec: number | null
  license_type: string
  times_used: number
  last_used_at: string | null
  last_used_project: string | null
  status: ClipStatus
  created_at: string
}

export interface ClipStats {
  total: number
  active: number
  missing: number
  deleted: number
  total_uses: number
  unique_projects: number
  total_duration_sec: number
}

// ─── Study history ────────────────────────────────────────────────────────────

export type StudyEntryStatus = 'active' | 'cooldown'

export interface StudyEntry {
  pmid: string
  topic: string
  title: string
  authors: string[]
  journal: string | null
  year: number | null
  doi: string | null
  study_type: string | null
  last_used_at: string | null
  last_used_job: string | null
  cooldown_until: string | null
  created_at: string
  status: StudyEntryStatus
}

export interface StudyStats {
  total: number
  active: number
  in_cooldown: number
}

// ─── Topic pool ───────────────────────────────────────────────────────────────

export interface Topic {
  id: string
  name: string
  times_used: number
  last_used_at: string | null
  created_at: string
  active: boolean
}

export interface TopicStats {
  total_active: number
  total_inactive: number
  total_uses: number
  most_used: string | null
  least_used: string | null
}

// ─── App settings ─────────────────────────────────────────────────────────────

export interface AssemblySettings {
  animations_enabled: boolean
  animation_type: 'ken_burns' | 'slide_in' | 'zoom_punch'
  transitions_enabled: boolean
  transition_type: 'crossfade'
  transition_duration: number
  caption_combine_ms: number
  font_family: string
}

export interface PipelineSettings {
  default_render_mode: 'draft' | 'final'
  default_whisper_model: string
  /** Frames Remotion renders in parallel in Stage 5. 0 = auto (~half the CPU cores). */
  render_concurrency: number
}

export interface AudioSettings {
  subscribe_click_sound: string // filename under assets/music/
  subscribe_bell_sound: string
}

export interface AppSettings {
  assembly: AssemblySettings
  pipeline: PipelineSettings
  audio: AudioSettings
}

// ─── LLM providers ──────────────────────────────────────────────────────────
// Mirrors `_OPENAI_COMPAT` + provider resolution in stages/stage_2 & stage_3.
// `keyEnv` is the .env var holding that provider's API key (null for "auto").
// `placeholder` is the model-id hint shown in the free-text model field.

export const LLM_PROVIDERS = [
  { id: 'auto',       label: 'Auto',       keyEnv: null,                 placeholder: 'claude-sonnet-4-6' },
  { id: 'anthropic',  label: 'Anthropic',  keyEnv: 'ANTHROPIC_API_KEY',  placeholder: 'claude-sonnet-4-6' },
  { id: 'openai',     label: 'OpenAI',     keyEnv: 'OPENAI_API_KEY',     placeholder: 'gpt-4o' },
  { id: 'groq',       label: 'Groq',       keyEnv: 'GROQ_API_KEY',       placeholder: 'llama-3.3-70b-versatile' },
  { id: 'nvidia',     label: 'NVIDIA',     keyEnv: 'NVIDIA_API_KEY',     placeholder: 'meta/llama-3.3-70b-instruct' },
  { id: 'openrouter', label: 'OpenRouter', keyEnv: 'OPENROUTER_API_KEY', placeholder: 'meta-llama/llama-3.3-70b-instruct' },
] as const

export type LLMProviderId = (typeof LLM_PROVIDERS)[number]['id']
