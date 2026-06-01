import type { Writable } from 'stream'

// Module-level registry of active subprocess stdin handles, keyed by jobId.
// Populated by the SSE stream route; consumed by the stdin relay route.
// Only valid in a single-process Node.js environment (local dev).
export const activeStdin = new Map<string, Writable>()
