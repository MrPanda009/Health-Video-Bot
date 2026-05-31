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
  const script = path.join(PIPELINE_ROOT, 'broll_db.py')
  const { stdout } = await execFileAsync(PYTHON_BIN, [script, ...args], {
    cwd: PIPELINE_ROOT,
    env: process.env,
    maxBuffer: 10 * 1024 * 1024, // 10 MB
  })
  return JSON.parse(stdout)
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const status = searchParams.get('status') ?? 'all'
  const validStatuses = ['active', 'missing', 'deleted', 'all']
  const resolvedStatus = validStatuses.includes(status) ? status : 'all'

  try {
    const data = await runDbCli(['list', '--status', resolvedStatus])
    return Response.json(data)
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 })
  }
}
