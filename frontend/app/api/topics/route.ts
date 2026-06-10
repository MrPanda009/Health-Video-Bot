import { execFile } from 'child_process'
import path from 'path'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')
const PYTHON_BIN = (() => {
  const bin = process.env.PYTHON_BIN ?? 'python3'
  return bin.startsWith('.') ? path.join(PIPELINE_ROOT, bin) : bin
})()

async function runDbCli(args: string[]): Promise<unknown> {
  const script = path.join(PIPELINE_ROOT, 'study_db.py')
  const { stdout } = await execFileAsync(PYTHON_BIN, [script, ...args], {
    cwd: PIPELINE_ROOT,
    env: process.env,
    maxBuffer: 1 * 1024 * 1024,
  })
  return JSON.parse(stdout)
}

export async function GET() {
  try {
    const data = await runDbCli(['topics', 'list'])
    return Response.json(data)
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 })
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({})) as { name?: string }
    const name = (body.name ?? '').trim()
    if (!name) {
      return Response.json({ error: 'name is required' }, { status: 400 })
    }
    const data = await runDbCli(['topics', 'add', name])
    return Response.json(data, { status: 201 })
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 })
  }
}

export async function DELETE(request: Request) {
  try {
    const body = await request.json().catch(() => ({})) as { id?: string }
    const id = (body.id ?? '').trim()
    if (!id) {
      return Response.json({ error: 'id is required' }, { status: 400 })
    }
    const data = await runDbCli(['topics', 'remove', id])
    return Response.json(data)
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 })
  }
}
