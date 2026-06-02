import path from 'path'
import fs from 'fs'
import { spawn } from 'child_process'
import { STAGES } from '@/lib/pipeline-config'
import { activeStdin } from '@/lib/active-processes'
import type { StageStreamEvent } from '@/lib/types'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')

function resolvePython(): string {
  const bin = process.env.PYTHON_BIN ?? 'python3'
  return bin.startsWith('.') ? path.join(PIPELINE_ROOT, bin) : bin
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ jobId: string; stage: string }> },
) {
  const { jobId, stage } = await params
  const url = new URL(request.url)
  const topic = url.searchParams.get('topic') ?? ''
  const pmid = url.searchParams.get('pmid') ?? ''
  const whisperModel = url.searchParams.get('whisperModel') ?? ''

  const stageDef = STAGES.find((s) => s.key === stage)
  if (!stageDef) {
    return Response.json({ error: 'Unknown stage' }, { status: 400 })
  }

  const jobFile = path.join(PIPELINE_ROOT, 'jobs', `${jobId}.json`)
  if (!fs.existsSync(jobFile)) {
    return Response.json({ error: 'Job not found' }, { status: 404 })
  }

  const scriptPath = path.join(PIPELINE_ROOT, stageDef.script)
  const pythonBin = resolvePython()

  // Read render_mode from job to decide whether to pass --draft to stage 5
  let renderMode: string | undefined
  if (stage === 'stage_5') {
    try {
      const raw = fs.readFileSync(jobFile, 'utf-8')
      renderMode = JSON.parse(raw).render_mode
    } catch { /* ignore */ }
  }

  // Stage 1: topic, pmid, '' (aspect_ratio default), jobId as pre_created_job_id
  // Stage 4d: jobId [--model <modelId>]
  // Stage 5: jobId [--draft]
  // All other stages: jobId only
  const args =
    stage === 'stage_1'
      ? [scriptPath, topic, pmid, '', jobId]
      : stage === 'stage_4d' && whisperModel
        ? [scriptPath, jobId, '--model', whisperModel]
        : stage === 'stage_5' && renderMode === 'draft'
          ? [scriptPath, jobId, '--draft']
          : [scriptPath, jobId]

  const encoder = new TextEncoder()

  const stream = new ReadableStream({
    start(controller) {
      const send = (event: StageStreamEvent) => {
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
        } catch {
          // controller may already be closed
        }
      }

      const proc = spawn(pythonBin, args, {
        cwd: PIPELINE_ROOT,
        env: { ...process.env, PYTHONUNBUFFERED: '1' },
      })

      // Register stdin so the /stdin relay endpoint can write to it
      if (stage === 'stage_1' && proc.stdin) {
        activeStdin.set(jobId, proc.stdin)
        proc.on('close', () => activeStdin.delete(jobId))
      }

      let awaitingInputSent = false
      proc.stdout.on('data', (chunk: Buffer) => {
        const text = chunk.toString()
        send({ type: 'stdout', data: text })
        // Detect the study-selection prompt and notify the client
        if (!awaitingInputSent && text.includes('Select a study')) {
          awaitingInputSent = true
          send({ type: 'awaiting_input', data: '' })
        }
      })

      proc.stderr.on('data', (chunk: Buffer) => {
        send({ type: 'stderr', data: chunk.toString() })
      })

      proc.on('close', (code) => {
        send({ type: 'exit', data: '', exitCode: code ?? -1 })
        controller.close()
      })

      proc.on('error', (err) => {
        send({ type: 'error', data: err.message })
        controller.close()
      })

      request.signal.addEventListener('abort', () => {
        proc.kill('SIGTERM')
      })
    },
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
