import path from 'path'
import { spawn } from 'child_process'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')

function resolvePython(): string {
  const bin = process.env.PYTHON_BIN ?? 'python3'
  return bin.startsWith('.') ? path.join(PIPELINE_ROOT, bin) : bin
}

export async function GET() {
  const scriptPath = path.join(PIPELINE_ROOT, 'stages', 'model_manager.py')
  const pythonBin = resolvePython()

  return new Promise<Response>((resolve) => {
    let stdout = ''
    let stderr = ''

    const proc = spawn(pythonBin, [scriptPath, 'status'], {
      cwd: PIPELINE_ROOT,
      env: { ...process.env },
    })

    proc.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString() })
    proc.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString() })

    proc.on('close', (code) => {
      if (code !== 0) {
        resolve(
          Response.json(
            {
              error: `model_manager exited with code ${code}`,
              stderr: stderr.trim(),
              models: [],
              whisperx_installed: false,
            },
            { status: 500 },
          ),
        )
        return
      }

      try {
        const data = JSON.parse(stdout.trim())
        resolve(Response.json(data))
      } catch {
        resolve(
          Response.json(
            { error: 'Invalid JSON from model_manager', models: [], whisperx_installed: false },
            { status: 500 },
          ),
        )
      }
    })

    proc.on('error', (err) => {
      resolve(
        Response.json(
          {
            error: `Failed to spawn python: ${err.message}`,
            models: [],
            whisperx_installed: false,
          },
          { status: 500 },
        ),
      )
    })
  })
}
