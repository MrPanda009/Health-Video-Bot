import fs from 'fs'
import path from 'path'
import type { Job, JobSummary } from '@/lib/types'

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')
const JOBS_DIR = path.join(PIPELINE_ROOT, 'jobs')

function summarize(job: Job): JobSummary {
  return {
    job_id: job.job_id,
    status: job.status,
    created_at: job.created_at,
    updated_at: job.updated_at,
    topic: job.study?.topic ?? job.topic ?? null,
    title: job.content?.title ?? null,
    error: job.error ?? null,
  }
}

export async function GET() {
  try {
    if (!fs.existsSync(JOBS_DIR)) {
      return Response.json({ jobs: [] })
    }
    const files = fs.readdirSync(JOBS_DIR).filter((f) => f.endsWith('.json'))
    const jobs: JobSummary[] = []
    for (const file of files) {
      try {
        const raw = fs.readFileSync(path.join(JOBS_DIR, file), 'utf-8')
        const job: Job = JSON.parse(raw)
        jobs.push(summarize(job))
      } catch {
        // skip malformed files
      }
    }
    jobs.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    return Response.json({ jobs })
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 })
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}))
  const { topic, pmid, aspect_ratio } = body as {
    topic?: string
    pmid?: string
    aspect_ratio?: string
  }

  const validAspectRatios = ['9:16', '16:9']
  const resolvedAspectRatio =
    aspect_ratio && validAspectRatios.includes(aspect_ratio) ? aspect_ratio : '9:16'

  // Pre-create the job JSON so we can return a job_id immediately and redirect
  const { randomUUID } = await import('crypto')
  const jobId = randomUUID()
  const now = new Date().toISOString()
  const initialJob = {
    job_id: jobId,
    created_at: now,
    updated_at: now,
    status: 'created',
    aspect_ratio: resolvedAspectRatio,
    topic: topic || null,
    error: null,
    study: null,
    claims: null,
    content: null,
    assets: null,
    output: null,
  }
  fs.mkdirSync(JOBS_DIR, { recursive: true })
  fs.writeFileSync(path.join(JOBS_DIR, `${jobId}.json`), JSON.stringify(initialJob, null, 2))

  const PYTHON_BIN = process.env.PYTHON_BIN ?? 'python3'
  const pythonBin = PYTHON_BIN.startsWith('.')
    ? path.join(PIPELINE_ROOT, PYTHON_BIN)
    : PYTHON_BIN

  const args = [path.join(PIPELINE_ROOT, 'stages/stage_1_research.py')]
  args.push(topic ?? '')
  args.push(pmid ?? '')
  args.push(resolvedAspectRatio)
  args.push(jobId)

  const { spawn } = await import('child_process')
  const proc = spawn(pythonBin, args, {
    cwd: PIPELINE_ROOT,
    env: process.env,
    detached: true,
    stdio: 'ignore',
  })
  proc.unref()

  return Response.json({ job_id: jobId, message: 'Job creation started' }, { status: 202 })
}
