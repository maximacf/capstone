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

  const handleApplyTaxonomy = () => {
    const toApply = proposedTaxonomy && proposedTaxonomy.length > 0 ? proposedTaxonomy : savedTaxonomy
    if (toApply.length === 0) {
      setError('Discover taxonomy first, or you already have a saved taxonomy.')
      return
    }
    setApplyLoading(true)
    setError(null)
    taxonomyApply({
      user_id: 'user_1',
      org_id: 'org_1',
      proposed_taxonomy: toApply,
    })
      .then(() => {
        setSavedTaxonomy(toApply)
        setProposedTaxonomy(null)
        setSuccess(`Applied ${toApply.length} categories`)
      })
      .catch((e) => setError(e.message))
      .finally(() => setApplyLoading(false))
  }

  const handleCompile = () => {
    const text = naturalLang.trim()
    if (!text) {
      setError('Describe your preferences')
      return
    }
    setCompileLoading(true)
    setError(null)
    configCompilePreferences({ natural_language: text })
      .then((r) => {
        setPreferences(JSON.stringify(r.preferences || {}, null, 2))
        setSuccess('Converted to JSON. Review and click Apply if ready.')
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
      .then(() => setSuccess('Preferences applied'))
      .catch((e) => setError(e.message))
      .finally(() => setPrefLoading(false))
  }

  return (
    <div className="taxonomy-page">
      <h1>Taxonomy & Config</h1>
      <p className="lead">
        Discover email categories from your inbox, apply a taxonomy, and set automation preferences.
      </p>
      {error && <div className="error">{error}</div>}
      {success && <div className="toast success">{success}</div>}

      <section className="card">
        <h2>1. Discover taxonomy</h2>
        <p>Propose categories from sampled emails (MECE principle).</p>
        <div className="form-row">
          <label>
            Mailbox
            <select value={mailboxId} onChange={(e) => setMailboxId(e.target.value)}>
              <option value="me">me</option>
              <option value="research_team">research_team</option>
              <option value="enron_import">enron_import</option>
            </select>
          </label>
          <button
            onClick={handleDiscover}
            disabled={discoverLoading}
            className="btn btn-primary"
          >
            {discoverLoading ? 'Discovering…' : 'Discover'}
          </button>
        </div>
      </section>

      <section className="card">
        <h2>2. Review & apply taxonomy</h2>
        {configLoading ? (
          <p className="muted">Loading saved config…</p>
        ) : (
          <>
            {savedTaxonomy.length > 0 && (
              <>
                <p className="muted">Current taxonomy (saved) — used by automation until you change it:</p>
                <ul className="taxonomy-list">
                  {savedTaxonomy.map((t) => (
                    <li key={t.classification_id}>
                      <code>{t.classification_id}</code> — {t.description || t.name}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {proposedTaxonomy && proposedTaxonomy.length > 0 && (
              <>
                <p className="muted" style={{ marginTop: '1rem' }}>Proposed (from Discover) — click Apply to replace your saved taxonomy:</p>
                <ul className="taxonomy-list">
                  {proposedTaxonomy.map((t) => (
                    <li key={t.classification_id}>
                      <code>{t.classification_id}</code> — {t.description || t.name}
                    </li>
                  ))}
                </ul>
                <button
                  onClick={handleApplyTaxonomy}
                  disabled={applyLoading}
                  className="btn btn-primary"
                  style={{ marginTop: '0.5rem' }}
                >
                  {applyLoading ? 'Applying…' : 'Apply proposed taxonomy'}
                </button>
              </>
            )}
            {savedTaxonomy.length === 0 && !proposedTaxonomy && (
              <p className="empty">Run Discover first to propose categories.</p>
            )}
          </>
        )}
      </section>

      <section className="card">
        <h2>3. Set automation preferences</h2>
        <p>Describe in plain English (e.g. &quot;summarize in max 5 bullet points for all emails&quot;) or edit JSON directly.</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1rem' }}>
          <textarea
            placeholder="e.g. Summarize all emails in max 5 bullet points, client-friendly style. Extract entities from client emails."
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
            {compileLoading ? 'Converting…' : 'Convert to JSON'}
          </button>
        </div>
        <p className="muted" style={{ marginTop: '0.5rem' }}>Or edit JSON directly:</p>
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
          {prefLoading ? 'Applying…' : 'Apply preferences'}
        </button>
      </section>
    </div>
  )
}
