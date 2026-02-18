export interface RunRequest {
  url: string
  max_leads: number
  skip_gpt: boolean
}

export interface JobStats {
  email_pct: number
  linkedin_pct: number
  phone_pct: number
  website_pct: number
  avg_score: number
}

export interface Lead {
  first_name?: string
  last_name?: string
  company?: string
  job_title?: string
  location?: string
  email?: string
  phone?: string
  linkedin_url?: string
  website?: string
  hit_score?: number
  is_hit?: boolean
  activity_summary?: string
  conversion_angle?: string
}

export interface JobResult {
  job_id: string
  status: 'running' | 'done' | 'error'
  total_leads: number
  hit_leads: number
  nohit_leads: number
  stats: JobStats
  leads: Lead[]
  error?: string
  csv_path?: string
}

export interface HealthCheck {
  status: string
  missing_keys: string[]
  apollo_cookies: boolean
  linkedin_cookies: boolean
  hit_threshold: number
  max_leads_default: number
}

export async function startJob(req: RunRequest): Promise<{ job_id: string }> {
  const res = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Failed to start job')
  }
  return res.json()
}

export async function getResults(jobId: string): Promise<JobResult> {
  const res = await fetch(`/api/results/${jobId}`)
  if (!res.ok) throw new Error('Failed to fetch results')
  return res.json()
}

export function getDownloadUrl(jobId: string): string {
  return `/api/download/${jobId}`
}

export async function getHealth(): Promise<HealthCheck> {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error('Health check failed')
  return res.json()
}
