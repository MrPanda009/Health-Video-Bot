import fs from 'fs'
import path from 'path'
import { rm } from 'fs/promises'
import type { Job, JobStatus } from '@/lib/types'

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')
const JOBS_DIR = path.join(PIPELINE_ROOT, 'jobs')

const VALID_STATUSES: JobStatus[] = [
  'created',
  'stage_1_complete',
  'stage_2_complete',
  'stage_3_complete',
  'stage_4_complete',
  'stage_5_complete',
  'complete',
  'error',
]

function jobPath(jobId: string) {
  return path.join(JOBS_DIR, `${jobId}.json`)
}

function readJob(jobId: string): Job | null {
  const p = jobPath(jobId)
  if (!fs.existsSync(p)) return null
  return JSON.parse(fs.readFileSync(p, 'utf-8'))
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params
  const job = readJob(jobId)
  if (!job) return Response.json({ error: 'Job not found' }, { status: 404 })
  return Response.json({ job })
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params
  const body = await request.json().catch(() => ({}))
  const { status, render_mode } = body as { status?: JobStatus; render_mode?: 'draft' | 'final' }

  const job = readJob(jobId)
  if (!job) return Response.json({ error: 'Job not found' }, { status: 404 })

  if (status !== undefined) {
    if (!VALID_STATUSES.includes(status)) {
      return Response.json({ error: 'Invalid status' }, { status: 400 })
    }
    job.status = status

    const newIdx = VALID_STATUSES.indexOf(status)
    // Roll back downstream data when moving to an earlier status so that
    // sub-stage isComplete() checks don't show stale "complete" state.
    if (newIdx <= VALID_STATUSES.indexOf('stage_3_complete')) {
      // Clear stage-4 sub-stage fields
      if (job.assets) {
        job.assets.broll_video_paths = []
        job.assets.broll_missing_segments = []
        job.assets.thumbnail_paths = []
        job.assets.voiceover_path = null
        job.assets.voiceover_duration_seconds = null
        job.assets.srt_path = null
        job.assets.ass_path = null
        job.assets.whisper_word_timestamps = []
      }
      // Clear stage-5 output
      job.output = null
    } else if (newIdx <= VALID_STATUSES.indexOf('stage_4_complete')) {
      job.output = null
    }

    if (newIdx <= VALID_STATUSES.indexOf('stage_2_complete')) {
      job.content = null
    }
    if (newIdx <= VALID_STATUSES.indexOf('stage_1_complete')) {
      job.claims = null
    }
    if (newIdx <= VALID_STATUSES.indexOf('created')) {
      job.study = null
    }
  }

  if (render_mode !== undefined) {
    if (render_mode !== 'draft' && render_mode !== 'final') {
      return Response.json({ error: 'render_mode must be draft or final' }, { status: 400 })
    }
    job.render_mode = render_mode
  }

  job.updated_at = new Date().toISOString()
  fs.writeFileSync(jobPath(jobId), JSON.stringify(job, null, 2))

  return Response.json({ job })
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params

  const jPath = jobPath(jobId)
  if (!fs.existsSync(jPath)) return Response.json({ error: 'Job not found' }, { status: 404 })

  // Delete job JSON
  fs.unlinkSync(jPath)

  // Delete assets directory (mirrors stage_0_clean.py delete_job_data)
  const assetsDir = path.join(PIPELINE_ROOT, 'assets', jobId)
  if (fs.existsSync(assetsDir)) {
    await rm(assetsDir, { recursive: true, force: true })
  }

  return Response.json({ ok: true })
}
