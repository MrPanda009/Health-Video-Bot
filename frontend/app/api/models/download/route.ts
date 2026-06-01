import path from 'path'
import { spawn } from 'child_process'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')

function resolvePython(): string {
  const bin = process.env.PYTHON_BIN ?? 'python3'
  return bin.startsWith('.') ? path.join(PIPELINE_ROOT, bin) : bin
}

// POST /api/models/download  { modelId: string }
// Returns an SSE stream of the download progress
export async function POST(request: Request) {
  const body = await request.json().catch(() => ({})) as { modelId?: string }
  const { modelId } = body

  if (!modelId) {
    return Response.json({ error: 'modelId is required' }, { status: 400 })
  }

  const scriptPath = path.join(PIPELINE_ROOT, 'stages', 'model_manager.py')
  const pythonBin = resolvePython()
  const encoder = new TextEncoder()

  const stream = new ReadableStream({
    start(controller) {
      const send = (type: string, data: string, exitCode?: number) => {
        const event = JSON.stringify({ type, data, ...(exitCode !== undefined ? { exitCode } : {}) })
        try {
          controller.enqueue(encoder.encode(`data: ${event}\n\n`))
        } catch {
          // controller already closed
        }
      }

      const proc = spawn(pythonBin, [scriptPath, 'download', modelId], {
        cwd: PIPELINE_ROOT,
        env: { ...process.env, PYTHONUNBUFFERED: '1' },
      })

      proc.stdout.on('data', (chunk: Buffer) => send('stdout', chunk.toString()))
      proc.stderr.on('data', (chunk: Buffer) => send('stderr', chunk.toString()))

      proc.on('close', (code) => {
        send('exit', '', code ?? -1)
        controller.close()
      })

      proc.on('error', (err) => {
        send('error', err.message)
        controller.close()
      })

      request.signal.addEventListener('abort', () => proc.kill('SIGTERM'))
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
