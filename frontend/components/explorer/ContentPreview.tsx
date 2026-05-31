'use client'

import { CopyButton } from '@/components/terminal/CopyButton'
import type { Content } from '@/lib/types'

interface ContentPreviewProps {
  content: Content
}

export function ContentPreview({ content }: ContentPreviewProps) {
  return (
    <div className="space-y-6">
      {/* Hindi Script */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Hindi Script</h4>
          <CopyButton text={content.hindi_script} />
        </div>
        <div className="max-h-60 overflow-y-auto rounded-lg bg-zinc-50 p-4 dark:bg-zinc-900">
          <p className="whitespace-pre-wrap text-sm leading-7 text-zinc-800 dark:text-zinc-200">
            {content.hindi_script}
          </p>
        </div>
      </div>

      {/* Script Segments */}
      {content.script_segments?.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Segments
          </h4>
          <div className="divide-y divide-zinc-100 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
            {content.script_segments.map((seg) => (
              <div key={seg.name} className="px-4 py-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                    {seg.name}
                  </span>
                  <span className="text-xs text-zinc-400">{seg.duration_hint_seconds}s</span>
                  <span className="text-xs text-zinc-400">· {seg.broll_mood}</span>
                </div>
                <p className="text-sm text-zinc-700 dark:text-zinc-300">{seg.hindi_text}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* YouTube Metadata */}
      <div>
        <h4 className="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
          YouTube Metadata
        </h4>
        <div className="space-y-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <div>
            <span className="text-xs font-medium text-zinc-500">Title</span>
            <div className="mt-0.5 flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                {content.title}
              </p>
              <CopyButton text={content.title} />
            </div>
          </div>
          {content.description && (
            <div>
              <span className="text-xs font-medium text-zinc-500">Description</span>
              <div className="mt-0.5 flex items-start justify-between gap-2">
                <p className="max-h-24 overflow-y-auto whitespace-pre-wrap text-xs text-zinc-700 dark:text-zinc-300">
                  {content.description}
                </p>
                <CopyButton text={content.description} />
              </div>
            </div>
          )}
          {content.tags?.length > 0 && (
            <div>
              <span className="text-xs font-medium text-zinc-500">Tags</span>
              <div className="mt-1 flex flex-wrap gap-1">
                {content.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}
          {content.chapter_timestamps?.length > 0 && (
            <div>
              <span className="text-xs font-medium text-zinc-500">Chapters</span>
              <div className="mt-1 space-y-1">
                {content.chapter_timestamps.map((ch) => (
                  <div key={ch.title} className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                    <span className="font-mono">{ch.estimated_start_seconds}s</span>
                    <span>{ch.title}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

    </div>
  )
}
