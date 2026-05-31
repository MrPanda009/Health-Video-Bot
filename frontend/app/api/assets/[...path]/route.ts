import fs from 'fs'
import path from 'path'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')
const ASSETS_ROOT = path.join(PIPELINE_ROOT, 'assets')

const MIME: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.mp4': 'video/mp4',
  '.wav': 'audio/wav',
  '.mp3': 'audio/mpeg',
  '.pdf': 'application/pdf',
  '.srt': 'text/plain',
  '.ass': 'text/plain',
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path: segments } = await params
  const filePath = path.join(ASSETS_ROOT, ...segments)

  // Path traversal guard
  if (!filePath.startsWith(ASSETS_ROOT)) {
    return new Response('Forbidden', { status: 403 })
  }

  if (!fs.existsSync(filePath)) {
    return new Response('Not found', { status: 404 })
  }

  const ext = path.extname(filePath).toLowerCase()
  const contentType = MIME[ext] ?? 'application/octet-stream'
  const buffer = fs.readFileSync(filePath)

  return new Response(buffer, {
    headers: { 'Content-Type': contentType },
  })
}
