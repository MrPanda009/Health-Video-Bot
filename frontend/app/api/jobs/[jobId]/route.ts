import fs from 'fs'
import path from 'path'
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
  const { status } = body as { status?: JobStatus }

  if (!status || !VALID_STATUSES.includes(status)) {
    return Response.json({ error: 'Invalid status' }, { status: 400 })
  }

  const job = readJob(jobId)
  if (!job) return Response.json({ error: 'Job not found' }, { status: 404 })

  job.status = status
  job.updated_at = new Date().toISOString()
  fs.writeFileSync(jobPath(jobId), JSON.stringify(job, null, 2))

  return Response.json({ job })
}
