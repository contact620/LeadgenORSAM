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

// ── Config endpoints ───────────────────────────────────────────────────────────

export interface ConfigStatus {
  serper_api_key: boolean
  dropcontact_api_key: boolean
  anthropic_api_key: boolean
  apollo_cookies: boolean
  linkedin_cookies: boolean
  hit_threshold: number
  max_leads: number
}

export interface ConfigUpdate {
  serper_api_key?: string
  dropcontact_api_key?: string
  anthropic_api_key?: string
  hit_threshold?: number
  max_leads?: number
}

export async function getConfig(): Promise<ConfigStatus> {
  const res = await fetch('/api/config')
  if (!res.ok) throw new Error('Failed to fetch config')
  return res.json()
}

export async function saveConfig(data: ConfigUpdate): Promise<void> {
  const res = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Failed to save config')
  }
}

// ── History endpoints ────────────────────────────────────────────────────────

export interface HistoryEntry {
  job_id: string
  status: 'done' | 'error'
  apollo_url: string
  max_leads: number
  skip_gpt: boolean
  started_at: string
  finished_at: string | null
  total_leads: number
  hit_leads: number
  nohit_leads: number
  email_pct: number
  linkedin_pct: number
  phone_pct: number
  website_pct: number
  avg_score: number
  csv_filename: string | null
  error: string | null
  csv_available: boolean
}

export async function getHistory(limit = 50, offset = 0): Promise<HistoryEntry[]> {
  const res = await fetch(`/api/history?limit=${limit}&offset=${offset}`)
  if (!res.ok) throw new Error('Failed to fetch history')
  return res.json()
}

export async function getHistoryLeads(jobId: string): Promise<Lead[]> {
  const res = await fetch(`/api/history/${jobId}/leads`)
  if (!res.ok) throw new Error('Failed to fetch leads')
  return res.json()
}

export async function deleteHistoryEntry(jobId: string): Promise<void> {
  const res = await fetch(`/api/history/${jobId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete entry')
}

// ── Cookie endpoints ─────────────────────────────────────────────────────────

export async function uploadCookies(
  service: 'apollo' | 'linkedin',
  jsonText: string,
): Promise<{ count: number }> {
  const blob = new Blob([jsonText], { type: 'application/json' })
  const form = new FormData()
  form.append('file', blob, `${service}_cookies.json`)
  const res = await fetch(`/api/cookies/${service}`, { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Failed to upload cookies')
  }
  return res.json()
}
