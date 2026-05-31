'use client'

import { CollapsibleSection } from './CollapsibleSection'
import { ContentPreview } from './ContentPreview'
import type { Job } from '@/lib/types'

function assetUrl(filePath: string): string {
  return '/api/assets/' + filePath.replace(/^.*assets\//, '')
}

export function JobDataExplorer({ job }: { job: Job }) {
  return (
    <div className="space-y-2">
      {/* Study */}
      <CollapsibleSection
        title="Study"
        data={job.study}
        defaultOpen={false}
        empty={!job.study}
      >
        {job.study && (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {/* Screenshots */}
            {job.study.screenshot_paths?.length > 0 && (
              <div className="p-4">
                <p className="mb-2 text-xs font-medium text-zinc-500">
                  Screenshots ({job.study.screenshot_paths.length})
                </p>
                <div className="flex flex-wrap gap-3">
                  {job.study.screenshot_paths.map((p, i) => (
                    <a
                      key={p}
                      href={assetUrl(p)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group relative h-32 w-48 shrink-0 overflow-hidden rounded border border-zinc-200 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={assetUrl(p)}
                        alt={`Screenshot ${i + 1}`}
                        className="h-full w-full object-cover transition-transform group-hover:scale-105"
                      />
                      <div className="absolute inset-x-0 bottom-0 bg-black/40 px-2 py-0.5 text-[10px] text-white opacity-0 transition-opacity group-hover:opacity-100">
                        View Full Screenshot
                      </div>
                    </a>
                  ))}
                </div>
              </div>
            )}

            {/* Raw JSON */}
            <pre className="max-h-80 overflow-auto p-4 font-mono text-xs leading-5 text-zinc-700 dark:text-zinc-300">
              {JSON.stringify(job.study, null, 2)}
            </pre>
          </div>
        )}
      </CollapsibleSection>

      {/* Claims */}
      <CollapsibleSection
        title="Claims"
        data={job.claims}
        empty={!job.claims}
      />

      {/* Content */}
      <CollapsibleSection
        title="Content"
        data={job.content}
        defaultOpen={false}
        empty={!job.content}
      >
        {job.content && (
          <div className="p-4">
            <ContentPreview content={job.content} />
          </div>
        )}
      </CollapsibleSection>

      {/* Assets */}
      <CollapsibleSection
        title="Assets"
        data={job.assets}
        defaultOpen={false}
        empty={!job.assets}
      >
        {job.assets && (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {/* Voiceover */}
            {job.assets.voiceover_path && (
              <div className="p-4">
                <div className="mb-1.5 flex items-center gap-2">
                  <p className="text-xs font-medium text-zinc-500">Voiceover</p>
                  {job.assets.voiceover_duration_seconds != null && (
                    <span className="text-xs text-zinc-400">
                      {job.assets.voiceover_duration_seconds.toFixed(1)}s
                    </span>
                  )}
                </div>
                <audio
                  controls
                  src={assetUrl(job.assets.voiceover_path)}
                  className="w-full rounded"
                />
              </div>
            )}

            {/* Thumbnails */}
            {job.assets.thumbnail_paths?.length > 0 && (
              <div className="p-4">
                <p className="mb-2 text-xs font-medium text-zinc-500">
                  Thumbnails ({job.assets.thumbnail_paths.length})
                </p>
                <div className="grid grid-cols-3 gap-3">
                  {job.assets.thumbnail_paths.map((t) => (
                    <a
                      key={t.variant_id}
                      href={assetUrl(t.path)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="space-y-1"
                    >
                      <p className="text-center text-xs text-zinc-500">{t.variant_id}</p>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={assetUrl(t.path)}
                        alt={t.variant_id}
                        className="w-full rounded border border-zinc-200 hover:opacity-80 dark:border-zinc-700"
                      />
                    </a>
                  ))}
                </div>
              </div>
            )}

            {/* B-roll */}
            {job.assets.broll_video_paths?.length > 0 && (
              <div className="p-4">
                <p className="mb-2 text-xs font-medium text-zinc-500">
                  B-roll ({job.assets.broll_video_paths.length} segments)
                </p>
                <div className="space-y-4">
                  {job.assets.broll_video_paths.map((b) => (
                    <div key={b.segment_name}>
                      <p className="mb-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-400">
                        {b.segment_name}
                      </p>
                      <div className="grid grid-cols-2 gap-2">
                        {b.paths.map((p) => (
                          <video
                            key={p}
                            src={assetUrl(p)}
                            controls
                            muted
                            className="w-full rounded border border-zinc-200 dark:border-zinc-700"
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Captions */}
            {job.assets.srt_path && (
              <div className="p-4">
                <p className="mb-1 text-xs font-medium text-zinc-500">Captions (SRT)</p>
                <a
                  href={assetUrl(job.assets.srt_path)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-600 hover:underline dark:text-blue-400"
                >
                  {job.assets.srt_path}
                </a>
              </div>
            )}
          </div>
        )}
      </CollapsibleSection>

      {/* Output */}
      <CollapsibleSection
        title="Output"
        data={job.output}
        defaultOpen={false}
        empty={!job.output}
      >
        {job.output && (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {/* Final video */}
            {job.output.final_video_path && (
              <div className="p-4">
                <p className="mb-2 text-xs font-medium text-zinc-500">Final Video</p>
                <video
                  src={assetUrl(job.output.final_video_path)}
                  controls
                  className="mx-auto max-h-[480px] w-auto rounded border border-zinc-200 dark:border-zinc-700"
                  style={{ maxWidth: '100%' }}
                />
              </div>
            )}

            {/* Quality gate */}
            {job.output.quality_checks && (
              <div className="p-4">
                <p className="mb-1 text-xs font-medium text-zinc-500">Quality Gate</p>
                <div className="space-y-0.5">
                  {Object.entries(job.output.quality_checks).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-2 text-xs">
                      <span
                        className={
                          v === true
                            ? 'text-green-500'
                            : v === false
                            ? 'text-red-500'
                            : 'text-zinc-400'
                        }
                      >
                        {v === true ? '✓' : v === false ? '✗' : '—'}
                      </span>
                      <span className="text-zinc-600 dark:text-zinc-400">{k}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* YouTube URL */}
            {job.output.youtube_url && (
              <div className="p-4">
                <p className="mb-0.5 text-xs font-medium text-zinc-500">YouTube URL</p>
                <a
                  href={job.output.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:underline dark:text-blue-400"
                >
                  {job.output.youtube_url}
                </a>
              </div>
            )}
          </div>
        )}
      </CollapsibleSection>
    </div>
  )
}
