import { useState, useEffect, useCallback } from 'react'
import {
  getDatasetSummary,
  getLabelingSamples,
  setManualCategory,
  getClassificationMetrics,
  getConfigLabels,
} from '../api/client'
import type { DatasetSummary, ClassificationMetrics } from '../types/api'

const FALLBACK_LABELS = [
  'Research', 'Financial', 'General', 'Internal', 'External', 'Materials',
  'Other', 'Security', 'Client', 'Trades', 'Market',
]

type LabelItem = {
  email_id: string
  subject: string | null
  from_addr: string | null
  body_text: string | null
  auto_category: string | null
  manual_category: string | null
}

const catIcons: Record<string, string> = {
  Financial: '💰', General: '📧', External: '🌐', Materials: '📎', Other: '📁',
  financial: '💰', general: '📧', external: '🌐', materials: '📎', other: '📁',
}

export default function Evaluation() {
  const [data, setData] = useState<DatasetSummary | null>(null)
  const [metrics, setMetrics] = useState<ClassificationMetrics | null>(null)
  const [labelingItems, setLabelingItems] = useState<LabelItem[]>([])
  const [totalEmails, setTotalEmails] = useState(0)
  const [labeledCount, setLabeledCount] = useState(0)
  const [labelMailbox, setLabelMailbox] = useState('enron_import')
  const [showUnlabeledOnly, setShowUnlabeledOnly] = useState(true)
  const [loading, setLoading] = useState(true)
  const [labelingLoading, setLabelingLoading] = useState(false)
  const [metricsLoading, setMetricsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [labelToast, setLabelToast] = useState<string | null>(null)
  const [labelOptions, setLabelOptions] = useState<string[]>(FALLBACK_LABELS)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    getDatasetSummary()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const loadSamples = useCallback(() => {
    setLabelingLoading(true)
    getLabelingSamples(labelMailbox, 80, 10, showUnlabeledOnly)
      .then((r) => {
        setLabelingItems(r.items as LabelItem[])
        setTotalEmails(r.total_emails ?? 0)
        setLabeledCount(r.labeled_count ?? 0)
      })
      .catch(() => setLabelingItems([]))
      .finally(() => setLabelingLoading(false))
  }, [labelMailbox, showUnlabeledOnly])

  useEffect(() => { loadSamples() }, [loadSamples])

  useEffect(() => {
    getClassificationMetrics(labelMailbox).then(setMetrics).catch(() => setMetrics(null))
  }, [labelMailbox])

  useEffect(() => {
    getConfigLabels()
      .then((r) => setLabelOptions(r.labels?.length ? r.labels : FALLBACK_LABELS))
      .catch(() => {})
  }, [])

  const refreshMetrics = () => {
    setMetricsLoading(true)
    getClassificationMetrics(labelMailbox)
      .then(setMetrics)
      .catch(() => setMetrics(null))
      .finally(() => setMetricsLoading(false))
  }

  const handleSetLabel = async (emailId: string, manualCategory: string) => {
    try {
      const wasAlreadyLabeled = labelingItems.find((i) => i.email_id === emailId)?.manual_category
      await setManualCategory(labelMailbox, emailId, manualCategory)
      setLabelingItems((prev) =>
        showUnlabeledOnly
          ? prev.filter((i) => i.email_id !== emailId)
          : prev.map((i) => i.email_id === emailId ? { ...i, manual_category: manualCategory } : i)
      )
      if (!wasAlreadyLabeled) setLabeledCount((c) => c + 1)
      setLabelToast(`✓ Labeled as ${manualCategory}`)
      setTimeout(() => setLabelToast(null), 1500)
      refreshMetrics()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const handleConfirmAuto = (item: LabelItem) => {
    if (item.auto_category) handleSetLabel(item.email_id, item.auto_category)
  }

  const allLabelOptions = [...new Set([
    ...labelOptions,
    ...labelingItems.map((i) => i.auto_category).filter(Boolean) as string[],
    ...labelingItems.map((i) => i.manual_category).filter(Boolean) as string[]
  ])].sort()

  const grouped = labelingItems.reduce<Record<string, LabelItem[]>>((acc, item) => {
    const key = item.auto_category || 'unknown'
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})

  if (loading) return <p className="muted" style={{ padding: '2rem' }}>Loading evaluation data…</p>
  if (error) return <div className="error">{error}</div>
  if (!data) return null

  const { totals, mailbox_totals, date_coverage, category_distribution, action_coverage, artifact_coverage } = data
  const progressPct = totalEmails > 0 ? Math.round((labeledCount / totalEmails) * 100) : 0

  return (
    <div className="evaluation-page">
      <h1>📊 Evaluation</h1>
      <p className="lead">
        Label emails to build ground truth, then measure classification quality with precision, recall, and F1 scores.
      </p>

      <section className="card">
        <h2>🏷️ Manual Labeling</h2>
        <p className="muted">
          Review each email's AI-assigned category. Click <strong>Confirm</strong> if correct,
          or pick the right label from the dropdown.
        </p>

        <div className="labeling-controls">
          <label>
            Mailbox
            <select value={labelMailbox} onChange={(e) => setLabelMailbox(e.target.value)}>
              {[...new Set([
                ...(mailbox_totals?.map((m) => m.mailbox_id) ?? []),
                'me', 'enron_import',
              ])].map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={showUnlabeledOnly}
              onChange={(e) => setShowUnlabeledOnly(e.target.checked)} />
            Show unlabeled only
          </label>
          <button className="btn btn-secondary" onClick={loadSamples} disabled={labelingLoading}>
            {labelingLoading ? 'Loading…' : '🔄 Refresh'}
          </button>
        </div>

        <div className="label-progress">
          <div className="label-progress-bar" style={{ width: `${progressPct}%` }} />
        </div>
        <span className="label-progress-text">{labeledCount} / {totalEmails} labeled ({progressPct}%)</span>

        {labelToast && <div className="toast success label-toast">{labelToast}</div>}

        {labelingLoading ? <p className="muted">Loading emails…</p> : labelingItems.length === 0 ? (
          <p className="empty">
            {showUnlabeledOnly ? 'All emails labeled! Uncheck "Show unlabeled only" to review.' : 'No emails found.'}
          </p>
        ) : (
          Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([cat, items]) => (
            <div key={cat} className="label-group">
              <div className="label-group-header">
                <span className={`category category--${cat}`}>
                  {catIcons[cat] || '📁'} {cat}
                </span>
                <span className="label-group-count">{items.length} email{items.length !== 1 ? 's' : ''}</span>
              </div>
              {items.map((item) => (
                <div key={item.email_id} className={`labeling-row ${item.manual_category ? 'labeled' : ''}`}>
                  <div className="labeling-meta">
                    <strong className="label-subject">{(item.subject || '(no subject)').slice(0, 70)}</strong>
                    <span className="from">{item.from_addr}</span>
                    <button type="button" className="btn-expand"
                      onClick={() => setExpandedId((p) => p === item.email_id ? null : item.email_id)}>
                      {expandedId === item.email_id ? '▲ Hide' : '▼ Preview'}
                    </button>
                  </div>
                  <div className="labeling-actions">
                    {item.manual_category
                      ? <span className="manual-badge">✓ {item.manual_category}</span>
                      : item.auto_category
                        ? <button className="btn btn-confirm" onClick={() => handleConfirmAuto(item)}>
                            ✓ Confirm: {item.auto_category}
                          </button>
                        : <span className="muted">No auto-label</span>
                    }
                    <select
                      value={item.manual_category ?? ''}
                      onChange={(e) => { if (e.target.value) handleSetLabel(item.email_id, e.target.value) }}
                    >
                      <option value="">{item.manual_category ? 'Change…' : 'Correct to…'}</option>
                      {allLabelOptions.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                  {expandedId === item.email_id && (
                    <div className="labeling-body">
                      {item.body_text ? <div className="body-text">{item.body_text}</div>
                        : <p className="muted">No body text available</p>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))
        )}
      </section>

      <section className="card">
        <h2>📈 Classification Quality</h2>
        <p className="muted">
          How accurate is the AI? Based on {metrics?.labeled_count ?? 0} manually labeled emails.
        </p>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={refreshMetrics}
          disabled={metricsLoading}
          style={{ marginBottom: '1rem' }}
        >
          {metricsLoading ? 'Calculating…' : '🔄 Refresh metrics'}
        </button>
        {metrics && metrics.labeled_count > 0 ? (
          <div className="metrics-block">
            <div className="stats-row">
              <div className="stat">
                <span className="stat-value">{(metrics.macro.precision * 100).toFixed(1)}%</span>
                <span className="stat-label">Precision</span>
              </div>
              <div className="stat">
                <span className="stat-value">{(metrics.macro.recall * 100).toFixed(1)}%</span>
                <span className="stat-label">Recall</span>
              </div>
              <div className="stat">
                <span className="stat-value">{(metrics.macro.f1 * 100).toFixed(1)}%</span>
                <span className="stat-label">F1 Score</span>
              </div>
            </div>
            <h3>Per-Category Breakdown</h3>
            <table className="runs-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Precision</th>
                  <th>Recall</th>
                  <th>F1</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(metrics.per_class).map(([cat, m]) => (
                  <tr key={cat}>
                    <td>
                      <span className={`category category--${cat}`}>
                        {catIcons[cat] || '📁'} {cat}
                      </span>
                    </td>
                    <td>{(m.precision * 100).toFixed(1)}%</td>
                    <td>{(m.recall * 100).toFixed(1)}%</td>
                    <td>{(m.f1 * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>Confusion Matrix</h3>
            <p className="muted">Rows = your label, Columns = AI prediction</p>
            <table className="confusion-matrix">
              <thead>
                <tr>
                  <th></th>
                  {Object.keys(metrics.per_class).map((p) => (
                    <th key={p}>{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.keys(metrics.per_class).map((actual) => (
                  <tr key={actual}>
                    <th>{actual}</th>
                    {Object.keys(metrics.per_class).map((pred) => {
                      const cell = metrics.confusion_matrix.find(
                        (c) => c.actual === actual && c.predicted === pred
                      )
                      return (
                        <td key={pred} className={actual === pred ? 'diagonal' : ''}>
                          {cell?.count ?? 0}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty">Label some emails above to see how well the AI is performing.</p>
        )}
      </section>

      <section className="card">
        <h2>📦 Dataset Overview</h2>
        <div className="stats-row">
          <div className="stat">
            <span className="stat-value">{totals?.raw_messages ?? 0}</span>
            <span className="stat-label">Raw messages</span>
          </div>
          <div className="stat">
            <span className="stat-value">{totals?.canonical_emails ?? 0}</span>
            <span className="stat-label">Unique emails</span>
          </div>
          <div className="stat">
            <span className="stat-value">{totals?.mailbox_mappings ?? 0}</span>
            <span className="stat-label">Mailbox links</span>
          </div>
        </div>

        {mailbox_totals && mailbox_totals.length > 0 && (
          <>
            <h3 style={{ margin: '1rem 0 0.5rem' }}>Mailboxes</h3>
            <div className="stats-row">
              {mailbox_totals.map((m) => (
                <div key={m.mailbox_id} className="stat">
                  <span className="stat-value">{m.count}</span>
                  <span className="stat-label">{m.mailbox_id}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {date_coverage && (
          <p className="muted" style={{ marginTop: '0.5rem' }}>
            Date range: {date_coverage?.email_received_at?.min ?? '–'} to {date_coverage?.email_received_at?.max ?? '–'}
          </p>
        )}
      </section>

      {(category_distribution?.message_category?.length || action_coverage?.length || artifact_coverage?.length) && (
        <section className="card">
          <h2>📊 Coverage Summary</h2>
          {category_distribution?.message_category?.length ? (
            <>
              <h3 style={{ margin: '0 0 0.5rem' }}>Categories</h3>
              <div className="stats-row">
                {category_distribution.message_category.map((c) => (
                  <div key={c.category} className="stat">
                    <span className="stat-value">{c.count}</span>
                    <span className="stat-label">{catIcons[c.category] || '📁'} {c.category}</span>
                  </div>
                ))}
              </div>
            </>
          ) : null}
          {action_coverage?.length ? (
            <>
              <h3 style={{ margin: '1rem 0 0.5rem' }}>Automation Actions</h3>
              <div className="stats-row">
                {action_coverage.map((a) => (
                  <div key={a.action_type} className="stat">
                    <span className="stat-value">{a.count}</span>
                    <span className="stat-label">{a.action_type}</span>
                  </div>
                ))}
              </div>
            </>
          ) : null}
          {artifact_coverage?.length ? (
            <>
              <h3 style={{ margin: '1rem 0 0.5rem' }}>Generated Artifacts</h3>
              <div className="stats-row">
                {artifact_coverage.map((a) => (
                  <div key={a.artifact_type} className="stat">
                    <span className="stat-value">{a.count}</span>
                    <span className="stat-label">{a.artifact_type}</span>
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </section>
      )}
    </div>
  )
}
