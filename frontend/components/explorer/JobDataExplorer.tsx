import { CollapsibleSection } from './CollapsibleSection'
import { ContentPreview } from './ContentPreview'
import type { Job } from '@/lib/types'

export function JobDataExplorer({ job }: { job: Job }) {
  return (
    <div className="space-y-2">
      <CollapsibleSection
        title="Study"
        data={job.study}
        defaultOpen={!!job.study}
        empty={!job.study}
      />
      <CollapsibleSection
        title="Claims"
        data={job.claims}
        empty={!job.claims}
      />
      <CollapsibleSection
        title="Content"
        data={job.content}
        defaultOpen={!!job.content}
        empty={!job.content}
      >
        {job.content && (
          <div className="p-4">
            <ContentPreview content={job.content} assets={job.assets} />
          </div>
        )}
      </CollapsibleSection>
      <CollapsibleSection
        title="Assets"
        data={job.assets}
        empty={!job.assets}
      >
        {job.assets && (
          <div className="p-4 space-y-3">
            {job.assets.voiceover_path && (
              <div>
                <span className="text-xs font-medium text-zinc-500">Voiceover</span>
                <p className="font-mono text-xs text-zinc-700 dark:text-zinc-300 mt-0.5">
                  {job.assets.voiceover_path}
                  {job.assets.voiceover_duration_seconds != null && (
                    <span className="ml-2 text-zinc-400">
                      ({job.assets.voiceover_duration_seconds.toFixed(1)}s)
                    </span>
                  )}
                </p>
              </div>
            )}
            {job.assets.broll_video_paths?.length > 0 && (
              <div>
                <span className="text-xs font-medium text-zinc-500">
                  B-roll ({job.assets.broll_video_paths.length} segments)
                </span>
                <div className="mt-1 space-y-1">
                  {job.assets.broll_video_paths.map((b) => (
                    <div key={b.segment_name} className="text-xs text-zinc-600 dark:text-zinc-400">
                      <span className="font-medium">{b.segment_name}:</span>{' '}
                      {b.paths.length} clip(s)
                    </div>
                  ))}
                </div>
              </div>
            )}
            {job.assets.srt_path && (
              <div>
                <span className="text-xs font-medium text-zinc-500">Captions</span>
                <p className="font-mono text-xs text-zinc-700 dark:text-zinc-300 mt-0.5">
                  {job.assets.srt_path}
                </p>
              </div>
            )}
          </div>
        )}
      </CollapsibleSection>
      <CollapsibleSection
        title="Output"
        data={job.output}
        defaultOpen={!!job.output?.final_video_path}
        empty={!job.output}
      >
        {job.output && (
          <div className="p-4 space-y-3">
            {job.output.final_video_path && (
              <div>
                <span className="text-xs font-medium text-zinc-500">Final Video</span>
                <p className="font-mono text-xs text-zinc-700 dark:text-zinc-300 mt-0.5">
                  {job.output.final_video_path}
                </p>
              </div>
            )}
            {job.output.quality_checks && (
              <div>
                <span className="text-xs font-medium text-zinc-500">Quality Gate</span>
                <div className="mt-1 space-y-0.5">
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
            {job.output.youtube_url && (
              <div>
                <span className="text-xs font-medium text-zinc-500">YouTube URL</span>
                <a
                  href={job.output.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-0.5 block text-sm text-blue-600 hover:underline dark:text-blue-400"
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
