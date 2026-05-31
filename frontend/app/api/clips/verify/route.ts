import { execFile } from 'child_process'
import path from 'path'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')
const PYTHON_BIN = (() => {
  const bin = process.env.PYTHON_BIN ?? 'python3'
  return bin.startsWith('.') ? path.join(PIPELINE_ROOT, bin) : bin
})()

export async function POST() {
  try {
    const script = path.join(PIPELINE_ROOT, 'broll_db.py')
    const { stdout } = await execFileAsync(PYTHON_BIN, [script, 'verify'], {
      cwd: PIPELINE_ROOT,
      env: process.env,
      maxBuffer: 1 * 1024 * 1024,
    })
    const data = JSON.parse(stdout)
    return Response.json(data)
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 })
  }
}
