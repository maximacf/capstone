import { useEffect, useState } from 'react'
import {
  taxonomyDiscover,
  taxonomyApply,
  configApplyPreferences,
  configCompilePreferences,
  getConfig,
} from '../api/client'
import type { TaxonomyItem } from '../types/api'

export default function Taxonomy() {
  const [mailboxId, setMailboxId] = useState('me')
  const [savedTaxonomy, setSavedTaxonomy] = useState<TaxonomyItem[]>([])
  const [proposedTaxonomy, setProposedTaxonomy] = useState<TaxonomyItem[] | null>(null)
  const [discoverLoading, setDiscoverLoading] = useState(false)
  const [applyLoading, setApplyLoading] = useState(false)
  const [prefLoading, setPrefLoading] = useState(false)
  const [compileLoading, setCompileLoading] = useState(false)
  const [naturalLang, setNaturalLang] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [preferences, setPreferences] = useState(
    JSON.stringify(
      {
        summarize: true,
        summarize_on_labels: [],
        summary_style: 'client_friendly',
        summary_length: 'short',
        translate: false,
        extract: true,
        extract_on_labels: [],
      },
      null,
      2
    )
  )
  const [configLoading, setConfigLoading] = useState(true)

  useEffect(() => {
    setConfigLoading(true)
    getConfig('user_1', mailboxId)
      .then((r) => {
        if (r.taxonomy?.length) {
          setSavedTaxonomy(r.taxonomy)
        }
        if (r.preferences && Object.keys(r.preferences).length > 0) {
          setPreferences(JSON.stringify(r.preferences, null, 2))
        }
      })
      .catch(() => {})
      .finally(() => setConfigLoading(false))
  }, [mailboxId])

  const handleDiscover = () => {
    setDiscoverLoading(true)
    setError(null)
    taxonomyDiscover({ mailbox_id: mailboxId, sample_limit: 50 })
      .then((r) => {
        setProposedTaxonomy(r.proposed_taxonomy || [])
        setSuccess(`Discovered ${r.proposed_taxonomy?.length ?? 0} categories. Review below and click Apply if you want to use them.`)
      })
      .catch((e) => setError(e.message))
      .finally(() => setDiscoverLoading(false))
  }

  const handleApplyTaxonomy = (source?: 'proposed' | 'saved') => {
    const toApply = source === 'saved' ? savedTaxonomy
      : source === 'proposed' ? (proposedTaxonomy || [])
      : (proposedTaxonomy && proposedTaxonomy.length > 0 ? proposedTaxonomy : savedTaxonomy)
    const filtered = toApply.filter((t) => t.classification_id.trim() !== '')
    if (filtered.length === 0) {
      setError('Add at least one category with a name.')
      return
    }
    setApplyLoading(true)
    setError(null)
    taxonomyApply({
      user_id: 'user_1',
      org_id: 'org_1',
      proposed_taxonomy: filtered,
    })
      .then(() => {
        setSavedTaxonomy(filtered)
        setProposedTaxonomy(null)
        setSuccess(`Applied ${filtered.length} categories`)
      })
      .catch((e) => setError(e.message))
      .finally(() => setApplyLoading(false))
  }

  const handleCompile = () => {
    const text = naturalLang.trim()
    if (!text) {
      setError('Describe your preferences in plain English first.')
      return
    }
    setCompileLoading(true)
    setError(null)
    configCompilePreferences({ natural_language: text })
      .then((r) => {
        setPreferences(JSON.stringify(r.preferences || {}, null, 2))
        setSuccess('Converted to settings. Review below and click Save when ready.')
      })
      .catch((e) => setError(e.message))
      .finally(() => setCompileLoading(false))
  }

  const handleApplyPreferences = () => {
    let prefs: Record<string, unknown>
    try {
      prefs = JSON.parse(preferences) as Record<string, unknown>
    } catch {
      setError('Invalid JSON for preferences')
      return
    }
    setPrefLoading(true)
    setError(null)
    configApplyPreferences({
      user_id: 'user_1',
      org_id: 'org_1',
      preferences: prefs,
    })
      .then(() => setSuccess('Preferences saved successfully!'))
      .catch((e) => setError(e.message))
      .finally(() => setPrefLoading(false))
  }

  const catIcons: Record<string, string> = {
    financial: '💰', general: '📧', external: '🌐', materials: '📎', other: '📁',
  }

  return (
    <div className="taxonomy-page">
      <h1>⚙️ Settings</h1>
      <p className="lead">
        Configure how Mailgine understands and processes your emails.
      </p>
      {error && <div className="error">{error}</div>}
      {success && <div className="toast success">{success}</div>}

      <section className="card">
        <h2>📂 Step 1 — Discover Email Categories</h2>
        <p className="muted">
          Let the AI scan your inbox and suggest meaningful categories for organizing your emails.
        </p>
        <div className="form-row">
          <label>
            Mailbox
            <select value={mailboxId} onChange={(e) => setMailboxId(e.target.value)}>
              <option value="me">My Inbox</option>
              <option value="research_team">Research Team</option>
              <option value="enron_import">Enron Dataset</option>
            </select>
          </label>
          <button
            onClick={handleDiscover}
            disabled={discoverLoading}
            className="btn btn-primary"
          >
            {discoverLoading ? 'Analyzing…' : '🔍 Discover categories'}
          </button>
        </div>
      </section>

      <section className="card">
        <h2>✅ Step 2 — Review & Apply Categories</h2>
        {configLoading ? (
          <p className="muted">Loading saved settings…</p>
        ) : (
          <>
            {savedTaxonomy.length > 0 && (
              <>
                <p className="muted">Your current categories — used for all automation:</p>
                <ul className="taxonomy-list">
                  {savedTaxonomy.map((t, idx) => (
                    <li key={t.classification_id + idx} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span>{catIcons[t.classification_id.toLowerCase()] || '📁'}</span>
                      <input
                        value={t.classification_id}
                        onChange={(e) => {
                          const updated = [...savedTaxonomy]
                          updated[idx] = { ...updated[idx], classification_id: e.target.value }
                          setSavedTaxonomy(updated)
                        }}
                        style={{ width: '160px', fontFamily: 'monospace', fontSize: '0.85rem', padding: '0.25rem 0.4rem', border: '1px solid #d0d5dd', borderRadius: '6px' }}
                        title="Category name"
                      />
                      <span style={{ color: '#999' }}>—</span>
                      <input
                        value={t.description || t.name}
                        onChange={(e) => {
                          const updated = [...savedTaxonomy]
                          updated[idx] = { ...updated[idx], description: e.target.value, name: e.target.value }
                          setSavedTaxonomy(updated)
                        }}
                        style={{ flex: 1, fontSize: '0.85rem', padding: '0.25rem 0.4rem', border: '1px solid #d0d5dd', borderRadius: '6px' }}
                        title="Description"
                      />
                      <button
                        onClick={() => setSavedTaxonomy(savedTaxonomy.filter((_, i) => i !== idx))}
                        title="Remove category"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.1rem', color: '#e74c3c', padding: '0.2rem' }}
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                  <button
                    onClick={() => setSavedTaxonomy([...savedTaxonomy, { classification_id: '', name: '', description: '' }])}
                    className="btn btn-secondary"
                    style={{ fontSize: '0.85rem' }}
                  >
                    ➕ Add category
                  </button>
                  <button
                    onClick={() => handleApplyTaxonomy('saved')}
                    disabled={applyLoading}
                    className="btn btn-primary"
                  >
                    {applyLoading ? 'Saving…' : '💾 Save changes'}
                  </button>
                </div>
              </>
            )}
            {proposedTaxonomy && proposedTaxonomy.length > 0 && (
              <>
                <p className="muted" style={{ marginTop: '1rem' }}>
                  New suggestions from AI — edit, remove, or add categories before applying:
                </p>
                <ul className="taxonomy-list">
                  {proposedTaxonomy.map((t, idx) => (
                    <li key={t.classification_id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span>{catIcons[t.classification_id.toLowerCase()] || '📁'}</span>
                      <input
                        value={t.classification_id}
                        onChange={(e) => {
                          const updated = [...proposedTaxonomy]
                          updated[idx] = { ...updated[idx], classification_id: e.target.value }
                          setProposedTaxonomy(updated)
                        }}
                        style={{ width: '160px', fontFamily: 'monospace', fontSize: '0.85rem', padding: '0.25rem 0.4rem', border: '1px solid #d0d5dd', borderRadius: '6px' }}
                        title="Category name"
                      />
                      <span style={{ color: '#999' }}>—</span>
                      <input
                        value={t.description || t.name}
                        onChange={(e) => {
                          const updated = [...proposedTaxonomy]
                          updated[idx] = { ...updated[idx], description: e.target.value, name: e.target.value }
                          setProposedTaxonomy(updated)
                        }}
                        style={{ flex: 1, fontSize: '0.85rem', padding: '0.25rem 0.4rem', border: '1px solid #d0d5dd', borderRadius: '6px' }}
                        title="Description"
                      />
                      <button
                        onClick={() => setProposedTaxonomy(proposedTaxonomy.filter((_, i) => i !== idx))}
                        title="Remove category"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.1rem', color: '#e74c3c', padding: '0.2rem' }}
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                  <button
                    onClick={() => setProposedTaxonomy([...proposedTaxonomy, { classification_id: '', name: '', description: '' }])}
                    className="btn btn-secondary"
                    style={{ fontSize: '0.85rem' }}
                  >
                    ➕ Add category
                  </button>
                  <button
                    onClick={() => handleApplyTaxonomy('proposed')}
                    disabled={applyLoading}
                    className="btn btn-primary"
                  >
                    {applyLoading ? 'Applying…' : '✅ Apply categories'}
                  </button>
                </div>
              </>
            )}
            {savedTaxonomy.length === 0 && !proposedTaxonomy && (
              <p className="empty">No categories yet. Click "Discover categories" above to get started.</p>
            )}
          </>
        )}
      </section>

      <section className="card">
        <h2>🎛️ Step 3 — Automation Preferences</h2>
        <p className="muted">
          Tell the AI what to do with your emails. Describe it in plain English and we'll convert it to settings.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1rem' }}>
          <textarea
            placeholder="e.g. Summarize all emails in max 5 bullet points. Extract key dates and amounts from financial emails. Draft replies for external emails."
            value={naturalLang}
            onChange={(e) => setNaturalLang(e.target.value)}
            rows={3}
            className="pref-editor"
          />
          <button
            onClick={handleCompile}
            disabled={compileLoading}
            className="btn btn-primary"
          >
            {compileLoading ? 'Converting…' : '🔄 Convert to settings'}
          </button>
        </div>
        <p className="muted" style={{ marginTop: '0.5rem' }}>
          Advanced: edit the JSON settings directly
        </p>
        <textarea
          value={preferences}
          onChange={(e) => setPreferences(e.target.value)}
          rows={14}
          className="pref-editor"
        />
        <button
          onClick={handleApplyPreferences}
          disabled={prefLoading}
          className="btn btn-secondary"
        >
          {prefLoading ? 'Saving…' : '💾 Save preferences'}
        </button>
      </section>
    </div>
  )
}
