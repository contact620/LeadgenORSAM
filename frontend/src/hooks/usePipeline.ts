import { useState, useRef, useCallback } from 'react'
import { startJob, getResults, type JobResult, type RunRequest } from '@/lib/api'

export interface ProgressEvent {
  step: number
  step_name: string
  message: string
  progress: number
  total_progress: number
}

export type PipelineStatus = 'idle' | 'running' | 'done' | 'error'

export interface PipelineState {
  status: PipelineStatus
  jobId: string | null
  events: ProgressEvent[]
  latestEvent: ProgressEvent | null
  result: JobResult | null
  error: string | null
}

export function usePipeline() {
  const [state, setState] = useState<PipelineState>({
    status: 'idle',
    jobId: null,
    events: [],
    latestEvent: null,
    result: null,
    error: null,
  })

  const esRef = useRef<EventSource | null>(null)

  const startPipeline = useCallback(async (req: RunRequest) => {
    setState({ status: 'running', jobId: null, events: [], latestEvent: null, result: null, error: null })

    try {
      const { job_id } = await startJob(req)

      setState(s => ({ ...s, jobId: job_id }))

      // Open SSE stream
      const es = new EventSource(`/api/stream/${job_id}`)
      esRef.current = es

      es.addEventListener('progress', (e: MessageEvent) => {
        const payload = JSON.parse(e.data)
        const event: ProgressEvent = payload.data
        setState(s => ({
          ...s,
          events: [...s.events.slice(-99), event],
          latestEvent: event,
        }))
      })

      es.addEventListener('done', () => {
        es.close()
        esRef.current = null
        getResults(job_id).then(result => {
          setState(s => ({ ...s, status: 'done', result }))
        })
      })

      es.addEventListener('error', (e: MessageEvent) => {
        es.close()
        esRef.current = null
        let errorMsg = 'Pipeline failed'
        try {
          const payload = JSON.parse(e.data)
          errorMsg = payload.data?.message ?? errorMsg
        } catch {/* raw SSE error */}
        setState(s => ({ ...s, status: 'error', error: errorMsg }))
      })

      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) {
          setState(s => {
            if (s.status === 'running') {
              return { ...s, status: 'error', error: 'Connection to server lost' }
            }
            return s
          })
        }
      }
    } catch (err) {
      setState(s => ({
        ...s,
        status: 'error',
        error: err instanceof Error ? err.message : String(err),
      }))
    }
  }, [])

  const reset = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
    setState({ status: 'idle', jobId: null, events: [], latestEvent: null, result: null, error: null })
  }, [])

  return { state, startPipeline, reset }
}
