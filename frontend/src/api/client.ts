const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8001'

async function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(path, API_BASE)
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)))
  }
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
  return res.json()
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API error: ${res.status} - ${text || res.statusText}`)
  }
  return res.json()
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API error: ${res.status} - ${text || res.statusText}`)
  }
  return res.json()
}

// Inbox & email
export async function getInbox(
  mailboxId: string,
  limit = 50,
  offset = 0,
  includeBody = false
) {
  const params: Record<string, string | number> = { limit, offset }
  if (includeBody) params.include_body = 'true'
  return get<import('../types/api').InboxResponse>(
    `/mailbox/${mailboxId}/inbox`,
    params
  )
}

export async function getEmailDetail(mailboxId: string, emailId: string) {
  const mb = encodeURIComponent(mailboxId)
  const em = encodeURIComponent(emailId)
  return get<{ status: string } & import('../types/api').EmailDetail>(
    `/mailbox/${mb}/email/${em}`
  )
}

export async function getArtifacts(mailboxId: string, emailId: string) {
  const mb = encodeURIComponent(mailboxId)
  const em = encodeURIComponent(emailId)
  return get<import('../types/api').ArtifactsResponse>(
    `/mailbox/${mb}/email/${em}/artifacts`
  )
}

// Pipeline
export async function pipelineIngest(params: {
  mailbox_id: string
  mailbox_type?: string
  pages?: number
  top?: number
  parse_limit?: number
}) {
  return post<{
    status: string
    ingest: { ingested_count: number }
    parse: { processed_count: number }
    corpus_snapshot: object
  }>('/pipeline/ingest', {
    mailbox_id: params.mailbox_id,
    mailbox_type: params.mailbox_type ?? 'personal',
    pages: params.pages ?? 1,
    top: params.top ?? 100,
    parse_limit: params.parse_limit ?? 250,
  })
}

export async function pipelineAutomate(params: {
  mailbox_id: string
  user_id: string
  org_id: string
  limit?: number
  min_confidence?: number
  classify_all?: boolean
}) {
  return post<{
    status: string
    processed: Array<{ message_id: string; status: string }>
  }>('/pipeline/automate', {
    mailbox_id: params.mailbox_id,
    user_id: params.user_id,
    org_id: params.org_id,
    limit: params.limit ?? 25,
    min_confidence: params.min_confidence ?? 0.7,
    classify_all: params.classify_all ?? false,
  })
}

// Taxonomy
export async function taxonomyDiscover(params?: {
  mailbox_id?: string
  sample_limit?: number
  window_days?: number
}) {
  return post<import('../types/api').TaxonomyDiscoverResponse>('/taxonomy/discover', params ?? {})
}

export async function taxonomyApply(params: {
  user_id: string
  org_id: string
  proposed_taxonomy: Array<{ classification_id: string; name: string; description: string }>
}) {
  return post<{ status: string; classification_count: number }>('/taxonomy/apply', params)
}

// Config
export async function getConfig(userId = 'user_1', mailboxId?: string) {
  const params: Record<string, string> = { user_id: userId }
  if (mailboxId) params.mailbox_id = mailboxId
  return get<{
    status: string
    classifications: Record<string, string>
    taxonomy: Array<{ classification_id: string; name: string; description: string }>
    preferences: Record<string, unknown>
  }>('/config', params)
}

export async function configCompilePreferences(params: {
  natural_language: string
  user_id?: string
  org_id?: string
}) {
  return post<{ status: string; preferences: Record<string, unknown> }>(
    '/config/compile-preferences',
    {
      natural_language: params.natural_language,
      user_id: params.user_id ?? 'user_1',
      org_id: params.org_id ?? 'org_1',
    }
  )
}

export async function getConfigLabels(userId = 'user_1') {
  return get<{ status: string; labels: string[] }>('/config/labels', { user_id: userId })
}

export async function configApplyPreferences(params: {
  user_id: string
  org_id: string
  preferences: Record<string, unknown>
}) {
  return post<{ status: string }>('/config/apply-preferences', params)
}

// Dataset & audit
export async function getDatasetSummary() {
  return get<import('../types/api').DatasetSummary>('/dataset/summary')
}

// Evaluation
export async function getLabelingSamples(
  mailboxId: string,
  limit = 80,
  perCategory = 10,
  unlabeledOnly = true
) {
  return get<{
    status: string
    mailbox_id: string
    total_emails: number
    labeled_count: number
    items: Array<{
      email_id: string
      subject: string | null
      from_addr: string | null
      body_text: string | null
      auto_category: string | null
      manual_category: string | null
    }>
  }>(
    '/evaluation/labeling-samples',
    { mailbox_id: mailboxId, limit, per_category: perCategory, unlabeled_only: unlabeledOnly ? 'true' : 'false' }
  )
}

export async function setManualCategory(
  mailboxId: string,
  emailId: string,
  manualCategory: string
) {
  return patch<{ status: string }>(
    `/mailbox/${encodeURIComponent(mailboxId)}/email/${encodeURIComponent(emailId)}/manual-category`,
    { manual_category: manualCategory }
  )
}

export async function getClassificationMetrics(mailboxId?: string) {
  const params = mailboxId ? { mailbox_id: mailboxId } : undefined
  return get<import('../types/api').ClassificationMetrics>('/evaluation/classification-metrics', params)
}

export async function getAuditRuns(params?: { mailbox_id?: string; limit?: number; offset?: number }) {
  const q: Record<string, string | number> = {}
  if (params?.mailbox_id) q.mailbox_id = params.mailbox_id
  if (params?.limit) q.limit = params.limit
  if (params?.offset) q.offset = params.offset
  return get<import('../types/api').AuditRunsResponse>('/audit/runs', Object.keys(q).length ? q : undefined)
}
