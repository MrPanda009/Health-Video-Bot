import { activeStdin } from '@/lib/active-processes'

export async function POST(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params
  const body = await request.json().catch(() => ({}))
  const { data } = body as { data?: string }

  if (!data) return Response.json({ error: 'data is required' }, { status: 400 })

  const stdin = activeStdin.get(jobId)
  if (!stdin || !stdin.writable) {
    return Response.json({ error: 'No active process for this job' }, { status: 404 })
  }

  stdin.write(`${data}\n`)
  return Response.json({ ok: true })
}
