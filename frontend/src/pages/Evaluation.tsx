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
      setLabelToast(`✓ ${manualCategory}`)
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
    ...labelingItems.map((i) => i.manual_category).filter(Boolean) as string[]
  ])].sort()

  // Group items by auto_category for grouped display
  const grouped = labelingItems.reduce<Record<string, LabelItem[]>>((acc, item) => {
    const key = item.auto_category || 'unknown'
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})

  if (loading) return <p>Loading…</p>
  if (error) return <div className="error">{error}</div>
  if (!data) return null

  const { totals, mailbox_totals, date_coverage, category_distribution, action_coverage, artifact_coverage } = data
  const progressPct = totalEmails > 0 ? Math.round((labeledCount / totalEmails) * 100) : 0

  return (
    <div className="evaluation-page">
      <h1>Evaluation</h1>
      <p className="lead">
        Manual labeling to create ground truth, then classification quality metrics (F1, precision, recall).
      </p>

      {/* Manual labeling */}
      <section className="card">
        <h2>1. Manual labeling (ground truth)</h2>
        <p className="muted">
          Label each email with the correct category. Click <strong>Confirm</strong> if the LLM got it right,
          or pick a different label from the dropdown. Emails are stratified — up to 10 per category.
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
            Unlabeled only
          </label>
          <button className="btn btn-secondary" onClick={loadSamples} disabled={labelingLoading}>
            {labelingLoading ? 'Loading…' : 'Refresh sample'}
          </button>
        </div>

        {/* Progress bar */}
        <div className="label-progress">
          <div className="label-progress-bar" style={{ width: `${progressPct}%` }} />
          <span className="label-progress-text">{labeledCount} / {totalEmails} labeled ({progressPct}%)</span>
        </div>

        {labelToast && <div className="toast success label-toast">{labelToast}</div>}

        {labelingLoading ? <p>Loading…</p> : labelingItems.length === 0 ? (
          <p className="empty">
            {showUnlabeledOnly ? 'All emails labeled! Uncheck "Unlabeled only" to review.' : 'No emails found.'}
          </p>
        ) : (
          Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([cat, items]) => (
            <div key={cat} className="label-group">
              <div className="label-group-header">
                <span className="category">{cat}</span>
                <span className="label-group-count">{items.length} emails</span>
              </div>
              {items.map((item) => (
                <div key={item.email_id} className={`labeling-row ${item.manual_category ? 'labeled' : ''}`}>
                  <div className="labeling-meta">
                    <strong className="label-subject">{(item.subject || '(no subject)').slice(0, 70)}</strong>
                    <span className="from">{item.from_addr}</span>
                    <button type="button" className="btn-expand"
                      onClick={() => setExpandedId((p) => p === item.email_id ? null : item.email_id)}>
                      {expandedId === item.email_id ? '▲ Hide' : '▼ Body'}
                    </button>
                  </div>
                  <div className="labeling-actions">
                    {item.manual_category
                      ? <span className="manual-badge">✓ {item.manual_category}</span>
                      : item.auto_category
                        ? <button className="btn btn-confirm" onClick={() => handleConfirmAuto(item)}>
                            Confirm: {item.auto_category}
                          </button>
                        : <span className="muted">No auto-label</span>
                    }
                    <select
                      value={item.manual_category ?? ''}
                      onChange={(e) => { if (e.target.value) handleSetLabel(item.email_id, e.target.value) }}
                    >
                      <option value="">{item.manual_category ? 'Correct…' : 'Wrong label…'}</option>
                      {allLabelOptions.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                  {expandedId === item.email_id && (
                    <div className="labeling-body">
                      {item.body_text ? <div className="body-text">{item.body_text}</div>
                        : <p className="muted">No body text</p>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))
        )}
      </section>

      {/* Classification metrics */}
      <section className="card">
        <h2>2. Classification quality (F1, precision, recall)</h2>
        <p className="muted">Requires manual labels. Based on {metrics?.labeled_count ?? 0} labeled emails.</p>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={refreshMetrics}
          disabled={metricsLoading}
        >
          {metricsLoading ? 'Loading…' : 'Refresh metrics'}
        </button>
        {metrics && metrics.labeled_count > 0 ? (
          <div className="metrics-block">
            <div className="stats-row">
              <div className="stat">
                <span className="stat-value">{metrics.macro.precision.toFixed(3)}</span>
                <span className="stat-label">Macro precision</span>
              </div>
              <div className="stat">
                <span className="stat-value">{metrics.macro.recall.toFixed(3)}</span>
                <span className="stat-label">Macro recall</span>
              </div>
              <div className="stat">
                <span className="stat-value">{metrics.macro.f1.toFixed(3)}</span>
                <span className="stat-label">Macro F1</span>
              </div>
            </div>
            <h3>Per-class metrics</h3>
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
                    <td><span className="category">{cat}</span></td>
                    <td>{m.precision.toFixed(3)}</td>
                    <td>{m.recall.toFixed(3)}</td>
                    <td>{m.f1.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>Confusion matrix</h3>
            <p className="muted">Rows = actual (manual), Cols = predicted (auto)</p>
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
          <p className="empty">Label at least a few emails above to see metrics.</p>
        )}
      </section>

      {/* Existing sections */}
      <section className="card">
        <h2>Corpus size</h2>
        <div className="stats-row">
          <div className="stat">
            <span className="stat-value">{totals?.raw_messages ?? 0}</span>
            <span className="stat-label">Raw messages</span>
          </div>
          <div className="stat">
            <span className="stat-value">{totals?.canonical_emails ?? 0}</span>
            <span className="stat-label">Canonical emails</span>
          </div>
          <div className="stat">
            <span className="stat-value">{totals?.mailbox_mappings ?? 0}</span>
            <span className="stat-label">Mailbox mappings</span>
          </div>
        </div>
      </section>

      <section className="card">
        <h2>Mailbox totals</h2>
        <ul>
          {mailbox_totals?.map((m) => (
            <li key={m.mailbox_id}>
              <strong>{m.mailbox_id}</strong>: {m.count} emails
            </li>
          ))}
          {(!mailbox_totals || mailbox_totals.length === 0) && <li className="empty">No mailboxes</li>}
        </ul>
      </section>

      <section className="card">
        <h2>Date coverage</h2>
        <p>
          Messages: {date_coverage?.message_received_dt?.min ?? '–'} to {date_coverage?.message_received_dt?.max ?? '–'}
        </p>
        <p>
          Emails: {date_coverage?.email_received_at?.min ?? '–'} to {date_coverage?.email_received_at?.max ?? '–'}
        </p>
      </section>

      <section className="card">
        <h2>Category distribution</h2>
        <ul>
          {category_distribution?.message_category?.map((c) => (
            <li key={c.category}>
              {c.category}: {c.count}
            </li>
          ))}
          {(!category_distribution?.message_category?.length) && <li className="empty">No data</li>}
        </ul>
      </section>

      <section className="card">
        <h2>Automation consistency (action coverage)</h2>
        <ul>
          {action_coverage?.map((a) => (
            <li key={a.action_type}>
              <code>{a.action_type}</code>: {a.count}
            </li>
          ))}
          {(!action_coverage?.length) && <li className="empty">No automation runs yet</li>}
        </ul>
      </section>

      <section className="card">
        <h2>Artifact coverage</h2>
        <ul>
          {artifact_coverage?.map((a) => (
            <li key={a.artifact_type}>
              <code>{a.artifact_type}</code>: {a.count}
            </li>
          ))}
          {(!artifact_coverage?.length) && <li className="empty">No artifacts yet</li>}
        </ul>
      </section>
    </div>
  )
}
