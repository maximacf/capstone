import { useState, useEffect } from 'react'
import {
  getInbox,
  getEmailDetail,
  getArtifacts,
  pipelineIngest,
  pipelineAutomate,
} from '../api/client'
import type { InboxItem, Artifact, EmailDetail } from '../types/api'

function CategoryBadge({ category }: { category: string | null }) {
  const cat = category || '–'
  const cls = `category category--${cat}`
  const icons: Record<string, string> = {
    Financial: '💰',
    General: '📧',
    External: '🌐',
    Materials: '📎',
    Other: '📁',
  }
  return <span className={cls}>{icons[cat] || '📁'} {cat}</span>
}

function Badges({ item }: { item: InboxItem }) {
  const badges: string[] = []
  if (item.has_summary) badges.push('📝 Summary')
  if (item.has_draft_reply) badges.push('✉️ Draft')
  if (item.has_translation) badges.push('🌍 Translation')
  if (item.has_extraction) badges.push('🔍 Extracted')
  if (badges.length === 0) return <span className="empty">–</span>
  return (
    <>
      {badges.map((b) => (
        <span key={b} className="badge">
          {b}
        </span>
      ))}
    </>
  )
}

function ExtractedFields({ raw }: { raw: string | Record<string, unknown> }) {
  let parsed: Record<string, unknown> | null = null
  if (typeof raw === 'object' && raw !== null) {
    parsed = raw
  } else {
    try {
      parsed = JSON.parse(raw as string)
    } catch { /* ignore */ }
  }
  if (!parsed || typeof parsed !== 'object') {
    return <p className="artifact-body">{String(raw)}</p>
  }
  const rows = Object.entries(parsed).filter(([, v]) => {
    if (v == null) return false
    const s = Array.isArray(v) ? v.join('') : String(v)
    return s.trim() !== '' && s !== 'null'
  })
  if (rows.length === 0) return <p className="artifact-body muted">No fields extracted.</p>
  return (
    <table className="extracted-fields-table">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td className="ef-key">{k.replace(/_/g, ' ')}</td>
            <td className="ef-val">{Array.isArray(v) ? v.join(', ') : String(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ArtifactBlock({ art }: { art: Artifact }) {
  const typeLabel: Record<string, string> = {
    summary: '📝 Summary',
    extracted_fields: '🔍 Extracted Fields',
    draft_reply: '✉️ Draft Reply',
    translation: '🌍 Translation',
  }

  const renderBody = () => {
    if (art.artifact_type === 'extracted_fields') {
      const raw = art.content_json ?? art.content_text
      return raw ? <ExtractedFields raw={raw as string | Record<string, unknown>} /> : null
    }
    if (art.artifact_type === 'draft_reply' && art.content_text) {
      return <blockquote className="draft-reply-body">{art.content_text}</blockquote>
    }
    if (art.content_text) {
      return <div className="artifact-body">{art.content_text}</div>
    }
    if (art.content_json) {
      return <pre>{JSON.stringify(art.content_json, null, 2)}</pre>
    }
    return null
  }

  return (
    <div className={`artifact artifact-${art.artifact_type}`}>
      <div className="artifact-type">{typeLabel[art.artifact_type] ?? art.artifact_type}</div>
      <div className="artifact-meta">{art.run_status === 'success' ? '✓ completed' : art.run_status}</div>
      {renderBody()}
    </div>
  )
}

export default function Dashboard() {
  const [mailboxId, setMailboxId] = useState('me')
  const [limit, setLimit] = useState(25)
  const [items, setItems] = useState<InboxItem[]>([])
  const [selected, setSelected] = useState<InboxItem | null>(null)
  const [emailDetail, setEmailDetail] = useState<EmailDetail | null>(null)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [ingestLoading, setIngestLoading] = useState(false)
  const [automateLoading, setAutomateLoading] = useState(false)
  const [lastAction, setLastAction] = useState<string | null>(null)
  const [ingestPages, setIngestPages] = useState(1)
  const [ingestTop, setIngestTop] = useState(20)
  const [automateLimit, setAutomateLimit] = useState(25)

  const refreshInbox = () => {
    setLoading(true)
    getInbox(mailboxId, limit)
      .then((r) => {
        setItems(r.items)
        setSelected((prev) => {
          if (r.items.length === 0) return null
          if (prev) {
            const stillThere = r.items.find((i) => i.email_id === prev.email_id)
            return stillThere || r.items[0]
          }
          return r.items[0]
        })
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    refreshInbox()
  }, [mailboxId, limit])

  useEffect(() => {
    if (!selected || !mailboxId) {
      setEmailDetail(null)
      setArtifacts([])
      return
    }
    Promise.all([
      getEmailDetail(mailboxId, selected.email_id),
      getArtifacts(mailboxId, selected.email_id),
    ])
      .then(([detail, arts]) => {
        setEmailDetail(detail as EmailDetail)
        setArtifacts(arts.items)
      })
      .catch(() => {
        setEmailDetail(null)
        setArtifacts([])
      })
  }, [selected, mailboxId])

  const handleIngest = () => {
    setIngestLoading(true)
    setLastAction(null)
    pipelineIngest({
      mailbox_id: mailboxId,
      pages: ingestPages,
      top: ingestTop,
      parse_limit: ingestPages * ingestTop,
    })
      .then((r) => {
        setLastAction(`Ingested ${r.ingest?.ingested_count ?? 0} emails, processed ${r.parse?.processed_count ?? 0}`)
        refreshInbox()
      })
      .catch((e) => setError(e.message))
      .finally(() => setIngestLoading(false))
  }

  const handleAutomate = () => {
    setAutomateLoading(true)
    setLastAction(null)
    pipelineAutomate({
      mailbox_id: mailboxId,
      user_id: 'user_1',
      org_id: 'org_1',
      limit: automateLimit,
      classify_all: true,
    })
      .then((r) => {
        const ok = r.processed?.filter((p) => p.status === 'success').length ?? 0
        setLastAction(`Automation complete — ${ok} actions processed`)
        refreshInbox()
        if (selected) {
          getArtifacts(mailboxId, selected.email_id).then((a) => setArtifacts(a.items))
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setAutomateLoading(false))
  }

  return (
    <div className="dashboard">
      <header className="page-header">
        <h1>📬 Inbox</h1>
        <div className="actions">
          <label>
            Mailbox
            <select value={mailboxId} onChange={(e) => setMailboxId(e.target.value)}>
              <option value="me">My Inbox</option>
              <option value="research_team">Research Team</option>
              <option value="enron_import">Enron Dataset</option>
            </select>
          </label>
          <label title="Number of emails to show">
            Show
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={250}>250</option>
              <option value={500}>500</option>
            </select>
          </label>
          <button
            onClick={handleIngest}
            disabled={ingestLoading}
            className="btn btn-secondary"
            title={`Fetch ${ingestPages} page(s) × ${ingestTop} from email provider`}
          >
            {ingestLoading ? 'Fetching…' : '📥 Fetch emails'}
          </button>
          <button
            onClick={handleAutomate}
            disabled={automateLoading}
            className="btn btn-primary"
            title={`Classify and process up to ${automateLimit} emails`}
          >
            {automateLoading ? 'Processing…' : '⚡ Run automation'}
          </button>
        </div>
      </header>
      {lastAction && <div className="toast success">{lastAction}</div>}
      {error && <div className="error">{error}</div>}
      {loading ? (
        <p className="muted">Loading inbox…</p>
      ) : (
        <div className="inbox-layout">
          <section className="inbox-list">
            <table className="inbox-table">
              <thead>
                <tr>
                  <th>Subject</th>
                  <th>From</th>
                  <th>Date</th>
                  <th>Category</th>
                  <th>AI Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="empty">No emails in this mailbox. Fetch emails or switch mailbox.</td>
                  </tr>
                ) : items.map((row) => (
                  <tr
                    key={row.email_id}
                    className={selected?.email_id === row.email_id ? 'selected' : ''}
                  >
                    <td>
                      <button onClick={() => setSelected(row)}>
                        {row.subject || '(no subject)'}
                      </button>
                    </td>
                    <td>{row.from_addr || '–'}</td>
                    <td>{row.received_at ? new Date(row.received_at).toLocaleDateString() : '–'}</td>
                    <td><CategoryBadge category={row.category} /></td>
                    <td><Badges item={row} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="email-detail">
            {selected ? (
              <>
                <h3>Email Details</h3>
                {emailDetail && (
                  <div className="email-meta">
                    <p><strong>Subject:</strong> {emailDetail.subject || '(none)'}</p>
                    <p><strong>From:</strong> {emailDetail.from_addr || '–'}</p>
                    <p><strong>Category:</strong> <CategoryBadge category={emailDetail.category} /></p>
                    {emailDetail.classification_history?.length ? (
                      <p style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                        <strong>Classification history:</strong>{' '}
                        {emailDetail.classification_history.slice(0, 3).map((h, i) => (
                          <span key={i}>
                            {h.category}
                            {h.confidence != null && (
                              <span className={`confidence-badge ${h.confidence >= 0.85 ? 'confidence-high' : h.confidence >= 0.6 ? 'confidence-medium' : 'confidence-low'}`} style={{ marginLeft: '0.3rem' }}>
                                {(h.confidence * 100).toFixed(0)}%
                              </span>
                            )}
                            {i < (emailDetail.classification_history?.length ?? 0) - 1 ? ' → ' : ''}
                          </span>
                        ))}
                      </p>
                    ) : null}
                  </div>
                )}
                {emailDetail?.body_text && (
                  <div className="email-body">
                    <h4>Body</h4>
                    <div className="body-text">{emailDetail.body_text}</div>
                  </div>
                )}
                <h4 style={{ marginTop: '1.25rem' }}>AI-Generated Insights</h4>
                {artifacts.length === 0 ? (
                  <p className="empty">
                    No insights yet. Click "Run automation" to generate summaries, extractions, and more.
                  </p>
                ) : (
                  artifacts.map((art) => (
                    <ArtifactBlock key={art.artifact_id} art={art} />
                  ))
                )}
              </>
            ) : (
              <p className="empty">Select an email to view details and AI insights</p>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
