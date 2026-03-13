import { useState, useEffect } from 'react'
import { getAuditRuns } from '../api/client'
import type { ExecutionRun } from '../types/api'

const actionIcons: Record<string, string> = {
  summary: '📝',
  extracted_fields: '🔍',
  draft_reply: '✉️',
  translation: '🌍',
  classify: '🏷️',
}

export default function ExecutionHistory() {
  const [items, setItems] = useState<ExecutionRun[]>([])
  const [totalRuns, setTotalRuns] = useState(0)
  const [successCount, setSuccessCount] = useState(0)
  const [failedCount, setFailedCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getAuditRuns({ limit: 100 })
      .then((r) => {
        setItems(r.items)
        setTotalRuns(r.total_runs)
        setSuccessCount(r.success_count)
        setFailedCount(r.failed_count)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="muted" style={{ padding: '2rem' }}>Loading activity log…</p>
  if (error) return <div className="error">{error}</div>

  return (
    <div className="execution-page">
      <h1>📋 Activity Log</h1>
      <p className="lead">
        Every automation action is logged here for full transparency and traceability.
      </p>
      <div className="stats-row">
        <div className="stat">
          <span className="stat-value">{totalRuns}</span>
          <span className="stat-label">Total actions</span>
        </div>
        <div className="stat success">
          <span className="stat-value">{successCount}</span>
          <span className="stat-label">Successful</span>
        </div>
        <div className="stat failed">
          <span className="stat-value">{failedCount}</span>
          <span className="stat-label">Failed</span>
        </div>
      </div>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="runs-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Mailbox</th>
              <th>Action</th>
              <th>Status</th>
              <th>Email Subject</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.run_id} className={r.status === 'failed' ? 'failed' : ''}>
                <td>{r.started_at ? new Date(r.started_at).toLocaleString() : '–'}</td>
                <td>{r.mailbox_id}</td>
                <td>
                  <span style={{ marginRight: '0.3rem' }}>{actionIcons[r.action_type] || '⚡'}</span>
                  {r.action_type}
                </td>
                <td>
                  <span className={`status-badge ${r.status}`}>{r.status}</span>
                </td>
                <td style={{ maxWidth: '280px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {r.subject ? (r.subject as string).slice(0, 60) : '–'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length === 0 && <p className="empty">No automation runs yet. Go to the Inbox and click "Run automation" to get started.</p>}
    </div>
  )
}
