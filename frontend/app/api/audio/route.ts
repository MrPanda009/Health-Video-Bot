import fs from 'fs'
import path from 'path'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')
const MUSIC_ROOT = path.join(PIPELINE_ROOT, 'assets', 'music')

const AUDIO_EXTS = new Set(['.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'])

// Lists audio files in assets/music/ — used by the Settings page to populate the
// Subscribe Animation sound dropdowns.
export async function GET() {
  try {
    if (!fs.existsSync(MUSIC_ROOT)) {
      return Response.json({ files: [] })
    }
    const files = fs
      .readdirSync(MUSIC_ROOT)
      .filter((name) => AUDIO_EXTS.has(path.extname(name).toLowerCase()))
      .sort((a, b) => a.localeCompare(b))
    return Response.json({ files })
  } catch (err) {
    return Response.json({ error: String(err), files: [] }, { status: 500 })
  }
}
