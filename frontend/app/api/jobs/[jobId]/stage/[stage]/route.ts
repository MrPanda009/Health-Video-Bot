import fs from 'fs'
import path from 'path'
import type { Job, JobStatus } from '@/lib/types'
import { STAGES, STATUS_ORDER, STAGE_4_SUBSTAGES } from '@/lib/pipeline-config'

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')
const JOBS_DIR = path.join(PIPELINE_ROOT, 'jobs')

function jobPath(jobId: string) {
  return path.join(JOBS_DIR, `${jobId}.json`)
}

function readJob(jobId: string): Job | null {
  const p = jobPath(jobId)
  if (!fs.existsSync(p)) return null
  return JSON.parse(fs.readFileSync(p, 'utf-8'))
}

function writeJob(job: Job) {
  fs.writeFileSync(jobPath(job.job_id), JSON.stringify(job, null, 2))
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ jobId: string; stage: string }> },
) {
  const { jobId, stage } = await params
  const body = await request.json().catch(() => ({}))
  const { action, topic, pmid } = body as {
    action: 'run' | 'skip'
    topic?: string
    pmid?: string
  }

  const job = readJob(jobId)
  if (!job) return Response.json({ error: 'Job not found' }, { status: 404 })

  // Handle skip
  if (action === 'skip') {
    // Special case: skip all of stage 4 sub-stages as a group
    if (stage === 'stage_4_group') {
      job.status = 'stage_4_complete'
      job.updated_at = new Date().toISOString()
      writeJob(job)
      return Response.json({ job })
    }

    const stageDef = STAGES.find((s) => s.key === stage)
    if (!stageDef) return Response.json({ error: 'Unknown stage' }, { status: 400 })

    // Sub-stages don't change job status individually
    if (STAGE_4_SUBSTAGES.includes(stageDef.key as (typeof STAGE_4_SUBSTAGES)[number])) {
      return Response.json({ job, message: 'Sub-stage skipped (no status change)' })
    }

    if (stageDef.completedStatus) {
      job.status = stageDef.completedStatus
      job.updated_at = new Date().toISOString()
      writeJob(job)
    }
    return Response.json({ job })
  }

  // Handle run — validate prerequisite
  if (action === 'run') {
    const stageDef = STAGES.find((s) => s.key === stage)
    if (!stageDef) return Response.json({ error: 'Unknown stage' }, { status: 400 })

    const currentIdx = STATUS_ORDER.indexOf(job.status as JobStatus | 'created')
    const prereqIdx = STATUS_ORDER.indexOf(stageDef.prerequisite)

    if (currentIdx < prereqIdx) {
      return Response.json(
        { error: `Job must be at '${stageDef.prerequisite}' to run this stage` },
        { status: 409 },
      )
    }

    // Return stream URL for the client to open
    const qs = new URLSearchParams()
    if (topic) qs.set('topic', topic)
    if (pmid) qs.set('pmid', pmid)

    return Response.json({
      streamUrl: `/api/jobs/${jobId}/stage/${stage}/stream?${qs.toString()}`,
    })
  }

  return Response.json({ error: 'action must be run or skip' }, { status: 400 })
}
