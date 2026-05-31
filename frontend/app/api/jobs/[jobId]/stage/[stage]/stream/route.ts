import path from 'path'
import fs from 'fs'
import { spawn } from 'child_process'
import { STAGES } from '@/lib/pipeline-config'
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

  // Stage 1 gets topic + pmid as args; all others get jobId
  const args =
    stage === 'stage_1'
      ? [scriptPath, ...(topic ? [topic] : []), ...(pmid ? [pmid] : [])]
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

      proc.stdout.on('data', (chunk: Buffer) => {
        send({ type: 'stdout', data: chunk.toString() })
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

      // When no PMID given for stage 1, auto-select the top candidate after a delay
      if (stage === 'stage_1' && !pmid) {
        const timer = setTimeout(() => {
          if (!proc.killed && proc.stdin?.writable) {
            proc.stdin.write('1\n')
          }
        }, 20_000)
        proc.on('close', () => clearTimeout(timer))
      }

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
