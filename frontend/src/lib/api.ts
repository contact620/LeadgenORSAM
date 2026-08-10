export interface ApolloFilters {
  person_titles: string[]
  locations: string[]
  industries: string[]
  employee_ranges: string[]
  seniority: string[]
  email_status: string[]
  keywords: string[]
}

export interface RunRequest {
  url?: string
  filters?: ApolloFilters
  max_leads: number
  skip_gpt: boolean
  enrich_instructions?: string
}

export interface JobStats {
  email_pct: number
  linkedin_pct: number
  phone_pct: number
  website_pct: number
  avg_score: number
  email_count: number
  linkedin_count: number
  phone_count: number
  website_count: number
  icp_hot_count: number
  icp_warm_count: number
  icp_cold_count: number
  icp_disqualified_count: number
}

export interface Lead {
  first_name?: string
  last_name?: string
  company?: string
  job_title?: string
  location?: string
  email?: string
  email_status?: string
  email_confidence?: number
  email_verification_provider?: string
  phone?: string
  linkedin_url?: string
  website?: string
  hit_score?: number
  is_hit?: boolean
  activity_summary?: string
  conversion_angle?: string
  digital_maturity?: string
  estimated_budget?: string
  business_signals?: string
  icp_score?: number
  icp_tier?: string
  icp_rationale?: string
  icp_scores_detail?: string
  website_coherent?: boolean
  website_rejected?: string
  website_check_reason?: string
  disqualification_reason?: string
  evidence_level?: 'none' | 'weak' | 'sufficient'
  evidence_verified?: boolean
  facts_json?: string
  is_duplicate?: boolean
  first_seen_at?: string
}

export interface RerunParams {
  url: string
  max_leads: number
  skip_gpt: boolean
}

export interface Template {
  id: string
  name: string
  apollo_url: string
  max_leads: number
  skip_gpt: boolean
  created_at: string
  last_used_at: string | null
  run_count: number
}

export interface LeadPool {
  pool_id: string
  name: string
  apollo_url: string
  created_at: string
  scrape_job_id: string
  total_leads: number
  hit_leads: number
  enriched_leads: number
}

export interface PoolLead {
  id: number
  pool_id: string
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
  is_hit: boolean
  is_duplicate: boolean
  enriched: boolean
  enriched_at?: string
  // Enrichment data (merged from enrich_data JSON)
  icp_score?: number
  icp_tier?: string
  activity_summary?: string
  conversion_angle?: string
  digital_maturity?: string
  estimated_budget?: string
  business_signals?: string
}

export interface JobResult {
  job_id: string
  status: 'running' | 'done' | 'error' | 'completed_with_errors'
  total_leads: number
  hit_leads: number
  nohit_leads: number
  stats: JobStats
  leads: Lead[]
  error?: string
  csv_path?: string
  executive_summary?: string
  provider_status?: Record<string, { status: string; reason: string | null; leads_affected: number }>
}

export interface HealthCheck {
  status: string
  missing_keys: string[]
  apollo_cookies: boolean
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

export async function cancelJob(jobId: string): Promise<void> {
  const res = await fetch(`/api/cancel/${jobId}`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to cancel job')
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
  perplexity_api_key: boolean
  hunter_api_key: boolean
  apollo_cookies: boolean
  hit_threshold: number
  max_leads: number
  services: string[]
}

export interface ConfigUpdate {
  serper_api_key?: string
  dropcontact_api_key?: string
  anthropic_api_key?: string
  perplexity_api_key?: string
  hunter_api_key?: string
  hit_threshold?: number
  max_leads?: number
  services?: string[]
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
  // Mirrors JobResult['status']: the backend persists 'running' while a job is
  // in flight and 'completed_with_errors' when a critical provider degraded.
  status: 'running' | 'done' | 'error' | 'completed_with_errors'
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

// ── Template endpoints ──────────────────────────────────────────────────────

export async function getTemplates(): Promise<Template[]> {
  const res = await fetch('/api/templates')
  if (!res.ok) throw new Error('Failed to fetch templates')
  return res.json()
}

export async function createTemplate(data: { name: string; apollo_url: string; max_leads: number; skip_gpt: boolean }): Promise<Template> {
  const res = await fetch('/api/templates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create template')
  return res.json()
}

export async function deleteTemplate(id: string): Promise<void> {
  const res = await fetch(`/api/templates/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete template')
}

export async function runTemplate(id: string): Promise<{ job_id: string }> {
  const res = await fetch(`/api/templates/${id}/run`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to run template')
  return res.json()
}

// ── Lead Pool endpoints ──────────────────────────────────────────────────────

export async function startScrapeJob(data: { url: string; max_leads: number; pool_name: string }): Promise<{ job_id: string }> {
  const res = await fetch('/api/scrape', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to start scrape job')
  return res.json()
}

export async function startEnrichJob(data: { pool_id: string; batch_size: number }): Promise<{ job_id: string }> {
  const res = await fetch('/api/enrich', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to start enrich job')
  return res.json()
}

export async function getPools(): Promise<LeadPool[]> {
  const res = await fetch('/api/pools')
  if (!res.ok) throw new Error('Failed to fetch pools')
  return res.json()
}

export async function getPoolDetail(poolId: string): Promise<LeadPool> {
  const res = await fetch(`/api/pools/${poolId}`)
  if (!res.ok) throw new Error('Failed to fetch pool')
  return res.json()
}

export async function getPoolLeads(poolId: string, onlyHit = false, onlyUnenriched = false, limit = 0): Promise<PoolLead[]> {
  const params = new URLSearchParams()
  if (onlyHit) params.set('only_hit', 'true')
  if (onlyUnenriched) params.set('only_unenriched', 'true')
  if (limit) params.set('limit', String(limit))
  const res = await fetch(`/api/pools/${poolId}/leads?${params}`)
  if (!res.ok) throw new Error('Failed to fetch pool leads')
  return res.json()
}

export async function deletePool(poolId: string): Promise<void> {
  const res = await fetch(`/api/pools/${poolId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete pool')
}

// ── Cookie endpoints ─────────────────────────────────────────────────────────

export async function uploadCookies(
  service: 'apollo',
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
