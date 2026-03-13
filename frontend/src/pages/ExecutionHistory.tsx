import { useState, useEffect } from 'react'
import { getAuditRuns } from '../api/client'
import type { ExecutionRun } from '../types/api'

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

  if (loading) return <p>Loading…</p>
  if (error) return <div className="error">{error}</div>

  return (
    <div className="execution-page">
      <h1>Execution History</h1>
      <p className="lead">
        Audit trail of automation runs for evaluation and traceability (Section 3.5).
      </p>
      <div className="stats-row">
        <div className="stat">
          <span className="stat-value">{totalRuns}</span>
          <span className="stat-label">Total runs</span>
        </div>
        <div className="stat success">
          <span className="stat-value">{successCount}</span>
          <span className="stat-label">Success</span>
        </div>
        <div className="stat failed">
          <span className="stat-value">{failedCount}</span>
          <span className="stat-label">Failed</span>
        </div>
      </div>
      <table className="runs-table">
        <thead>
          <tr>
            <th>Started</th>
            <th>Mailbox</th>
            <th>Action</th>
            <th>Status</th>
            <th>Subject</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.run_id} className={r.status === 'failed' ? 'failed' : ''}>
              <td>{r.started_at ? new Date(r.started_at).toLocaleString() : '–'}</td>
              <td>{r.mailbox_id}</td>
              <td><code>{r.action_type}</code></td>
              <td>
                <span className={`status-badge ${r.status}`}>{r.status}</span>
              </td>
              <td>{r.subject ? (r.subject as string).slice(0, 50) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <p className="empty">No automation runs yet.</p>}
    </div>
  )
}
