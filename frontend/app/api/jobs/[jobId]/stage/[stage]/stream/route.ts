import path from 'path'
import fs from 'fs'
import { spawn } from 'child_process'
import { STAGES } from '@/lib/pipeline-config'
import { activeStdin } from '@/lib/active-processes'
import { readSettings } from '@/app/api/settings/route'
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
  const autoMode = url.searchParams.get('auto') === '1'

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

  // Read render_mode from job and global settings to build stage 5 args
  let renderMode: string | undefined
  if (stage === 'stage_5') {
    try {
      const raw = fs.readFileSync(jobFile, 'utf-8')
      renderMode = JSON.parse(raw).render_mode
    } catch { /* ignore */ }
  }

  // Stage 1: topic, pmid, '' (aspect_ratio default), jobId as pre_created_job_id
  // Stage 4d: jobId [--model <modelId>]
  // Stage 5: jobId [--draft] [--transition-type X] [--animation-type X] [--transition-duration X]
  // All other stages: jobId only
  let args: string[]
  if (stage === 'stage_1') {
    args = [scriptPath, topic, pmid, '', jobId]
    if (autoMode) args.push('--auto')
  } else if (stage === 'stage_4d') {
    // whisperModel query param takes precedence; fall back to settings.json
    const model = whisperModel || readSettings().pipeline.default_whisper_model
    args = [scriptPath, jobId, '--model', model]
  } else if (stage === 'stage_5') {
    args = [scriptPath, jobId]
    if (renderMode === 'draft') args.push('--draft')
    // Pass assembly settings so stage_5_assembly.py can forward them to video_assembler
    const settings = readSettings()
    const asm = settings.assembly
    args.push('--transition-type', asm.transitions_enabled ? asm.transition_type : 'none')
    args.push('--animation-type', asm.animations_enabled ? asm.animation_type : 'none')
    args.push('--transition-duration', String(asm.transition_duration))
    args.push('--caption-combine-ms', String(asm.caption_combine_ms ?? 1500))
    args.push('--font-family', asm.font_family ?? 'NotoSansDevanagari')
    const aud = settings.audio
    if (aud?.subscribe_click_sound) args.push('--click-sound', aud.subscribe_click_sound)
    if (aud?.subscribe_bell_sound) args.push('--bell-sound', aud.subscribe_bell_sound)
    // Render concurrency: 0 = auto (let remotion.config.ts decide ~half the cores)
    const concurrency = settings.pipeline?.render_concurrency
    if (typeof concurrency === 'number' && concurrency > 0) {
      args.push('--concurrency', String(concurrency))
    }
  } else {
    args = [scriptPath, jobId]
  }

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

      // Register stdin for all stages so any interactive prompt can receive input
      if (proc.stdin) {
        activeStdin.set(jobId, proc.stdin)
        proc.on('close', () => activeStdin.delete(jobId))
      }

      const INPUT_PATTERNS = [
        /select a study/i,
        /press enter/i,
        /press any key/i,
        /enter your/i,
        /\?\s*$/m,           // lines ending with "?"
        /:\s*$/m,            // lines ending with ":"
      ]

      // Track prompt state: after stdin is written the flag resets so a next prompt is detected
      let awaitingInputSent = false
      const origStdin = proc.stdin
      if (origStdin) {
        const origWrite = origStdin.write.bind(origStdin)
        // @ts-expect-error wrapping write to reset detection flag after input is sent
        origStdin.write = (...args: Parameters<typeof origWrite>) => {
          awaitingInputSent = false
          return origWrite(...args)
        }
      }

      proc.stdout.on('data', (chunk: Buffer) => {
        const text = chunk.toString()
        send({ type: 'stdout', data: text })
        if (!awaitingInputSent && INPUT_PATTERNS.some((p) => p.test(text))) {
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
