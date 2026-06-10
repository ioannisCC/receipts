import { useState, useEffect, useRef, useCallback, MouseEvent as RMouseEvent } from 'react'

// ── Types ────────────────────────────────────────────────────────────────────

interface TelemetryEvent {
  stage: string
  model: string | null
  tokens_in: number
  tokens_out: number
  latency_ms: number
  cost_usd: number
  escalated: boolean
  vendor: string | null
  claim_id: string | null
}

interface Judgment {
  claim_id: string
  verdict: 'SUPPORTED' | 'SELF_REPORTED_ONLY' | 'NO_PUBLIC_RECEIPT_FOUND'
  confidence: number
  rationale: string
  receipts: string[]
  escalated: boolean
}

interface VendorResult {
  vendor: string
  url: string
  status: string
  claims: { claim: string; metric: string | null; magnitude: string | null; claim_id: string }[]
  judgments: Judgment[]
  credibility_score: number | null
  advice: string | null
  honest_ad_url: string | null
  honest_ad_claims: string[]
}

interface MarketResult {
  category: string
  vendors: VendorResult[]
  claim_inflation_index: number
  telemetry_summary?: Record<string, unknown>
}

interface RunStats {
  totalCost: number
  totalTokens: number
  escalations: number
  totalJudgments: number
  calls: number
  elapsedMs: number
}

// ── Data ─────────────────────────────────────────────────────────────────────

const EXAMPLE_TEXT =
`Intercom Fin, https://www.intercom.com/fin
Decagon, https://decagon.ai
Zendesk AI, https://www.zendesk.com/service/ai
Forethought, https://forethought.ai
Tidio, https://www.tidio.com
Freshdesk AI, https://www.freshworks.com/freshdesk`

const VERDICT_META = {
  SUPPORTED: {
    label: 'Publicly substantiated',
    color: 'var(--green)',
    bg: 'rgba(52, 211, 153, 0.12)',
    description: 'Independent public sources (case studies, third-party reviews, published methodology) corroborate this claim. We report public substantiation, not truth — absence of evidence here is not proof a claim is false.',
  },
  SELF_REPORTED_ONLY: {
    label: 'Self-reported only',
    color: 'var(--yellow)',
    bg: 'rgba(251, 191, 36, 0.12)',
    description: "The claim appears only on the vendor's own surfaces (site, blog, press releases). No independent public source echoes it — a signal, not a verdict on truth.",
  },
  NO_PUBLIC_RECEIPT_FOUND: {
    label: 'No public receipt',
    color: 'var(--red)',
    bg: 'rgba(248, 113, 113, 0.12)',
    description: 'We searched the public web and could not find a receipt for this claim. That does not mean the claim is false — we report public substantiation, not truth.',
  },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseVendorText(raw: string): [string, string][] {
  return raw.split('\n').map(l => l.trim()).filter(Boolean).flatMap(line => {
    const sep = line.includes('\t') ? '\t' : ','
    const parts = line.split(sep).map(s => s.trim())
    if (parts.length < 2) return []
    const url = parts[parts.length - 1]
    if (!url.startsWith('http')) return []
    return [[parts[0], url] as [string, string]]
  })
}

function scoreColor(score: number | null) {
  if (score === null) return 'var(--muted)'
  if (score >= 0.7) return 'var(--green)'
  if (score >= 0.4) return 'var(--yellow)'
  return 'var(--red)'
}

function fmtCost(n: number) { return `$${n.toFixed(4)}` }
function fmtMs(ms: number) { return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s` }

function vendorStatusLabel(v: VendorResult) {
  if (v.credibility_score !== null) return `${Math.round(v.credibility_score * 100)}%`
  if (v.status === 'unreachable') return 'not loaded'
  if (v.status === 'no_claims_extracted') return 'no claims'
  if (v.status === 'error') return 'error'
  return 'checking...'
}

function vendorStatusTitle(v: VendorResult) {
  if (v.credibility_score !== null) return 'Score out of 100 — how many claims have independent public receipts. We measure public substantiation, not truth.'
  if (v.status === 'unreachable') return 'The page could not be loaded or scraped'
  if (v.status === 'no_claims_extracted') return 'The page loaded, but no specific marketing claims were found'
  if (v.status === 'error') return 'This vendor finished with an error'
  return 'This vendor is still being checked'
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Tip({ text }: { text: string }) {
  return (
    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, lineHeight: 1.5 }}>
      {text}
    </div>
  )
}

function StatBox({ label, value, tip, mono }: { label: string; value: string; tip: string; mono?: boolean }) {
  return (
    <div style={{ textAlign: 'center', padding: '14px 8px' }}>
      <div style={{
        fontSize: mono ? 19 : 18, fontWeight: 700,
        fontFamily: mono ? 'var(--mono)' : undefined,
        color: 'var(--text)',
      }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2, padding: '0 4px', lineHeight: 1.4 }}>{tip}</div>
    </div>
  )
}

function VendorCard({ v, animIn }: { v: VendorResult; animIn: boolean }) {
  const [adviceOpen, setAdviceOpen] = useState(false)
  const [claimsOpen, setClaimsOpen] = useState(false)
  const score = v.credibility_score
  const pct = score !== null ? Math.round(score * 100) : null

  const counts = v.judgments.reduce(
    (acc, j) => { acc[j.verdict] = (acc[j.verdict] || 0) + 1; return acc },
    {} as Record<string, number>
  )

  const judgeMap = Object.fromEntries(v.judgments.map(j => [j.claim_id, j]))

  return (
    <div className="glass" style={{
      background: 'var(--surface)',
      border: `1px solid ${pct !== null ? scoreColor(score) + '60' : 'var(--border)'}`,
      borderRadius: 14,
      padding: '16px 18px',
      boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
      transition: 'opacity 0.4s ease, transform 0.4s ease',
      opacity: animIn ? 1 : 0,
      transform: animIn ? 'translateY(0)' : 'translateY(20px)',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>{v.vendor}</div>
          <a href={v.url} target="_blank" rel="noreferrer"
            style={{ color: 'var(--muted)', fontSize: 11, marginTop: 2, display: 'block', textDecoration: 'none' }}>
            {v.url}
          </a>
        </div>
        {pct !== null ? (
          <div
            title={vendorStatusTitle(v)}
            style={{
              background: scoreColor(score), color: '#fff', fontWeight: 800,
              fontSize: 18, borderRadius: 8, padding: '4px 12px', lineHeight: 1.2, cursor: 'help',
            }}>
            {vendorStatusLabel(v)}
          </div>
        ) : (
          <div
            title={vendorStatusTitle(v)}
            style={{
              fontSize: 11,
              color: v.status === 'ok' ? 'var(--muted)' : '#6b7280',
              fontStyle: 'italic',
              whiteSpace: 'nowrap',
            }}>
            {vendorStatusLabel(v)}
          </div>
        )}
      </div>

      {/* Score bar */}
      {pct !== null && (
        <div title="Bar shows the credibility score"
          style={{ height: 5, background: 'var(--surface2)', borderRadius: 3, marginBottom: 12, overflow: 'hidden', cursor: 'help' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: scoreColor(score), transition: 'width 0.8s ease' }} />
        </div>
      )}

      {/* Status message for failed pages */}
      {v.status !== 'ok' && (
        <div style={{ color: 'var(--muted)', fontSize: 12, fontStyle: 'italic', marginBottom: 8 }}>
          {v.status === 'unreachable'
            ? 'Could not load this vendor page'
            : 'No specific claims found on this page'}
        </div>
      )}

      {/* Honest ad — Magnific backdrop + DOM-text claim overlay. The image
          never typesets the figures; the numbers below are real React text,
          inspect-element legible. */}
      {v.honest_ad_url && v.honest_ad_claims.length > 0 && (
        <div
          title="The honest ad — what their marketing would say if it could only quote what's publicly substantiated."
          style={{
            position: 'relative', aspectRatio: '16 / 9',
            backgroundImage: `url(${v.honest_ad_url})`, backgroundSize: 'cover', backgroundPosition: 'center',
            borderRadius: 10, overflow: 'hidden', margin: '6px 0 12px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
          }}>
          <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.15) 45%, rgba(0,0,0,0.7) 100%)' }} />
          <div style={{ position: 'relative', padding: '14px 18px', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', color: '#fff' }}>
            <div style={{ fontSize: 10, opacity: 0.85, letterSpacing: 1, textTransform: 'uppercase', fontWeight: 700 }}>
              The honest ad · {v.vendor}
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6, opacity: 0.9 }}>What we can prove:</div>
              {v.honest_ad_claims.map((claim, i) => (
                <div key={i} style={{ fontSize: 13, marginBottom: 4, lineHeight: 1.4, fontWeight: 600 }}>✓ {claim}</div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Verdict badges */}
      {v.judgments.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 6 }}>
            Hover each badge to see what it means
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {Object.entries(counts).map(([verdict, count]) => {
              const meta = VERDICT_META[verdict as keyof typeof VERDICT_META]
              return (
                <span key={verdict} title={meta.description} style={{
                  background: meta.bg,
                  border: `1px solid ${meta.color}`,
                  color: meta.color,
                  borderRadius: 6, padding: '2px 9px', fontSize: 11, fontWeight: 600, cursor: 'help',
                }}>
                  {count} {meta.label}
                </span>
              )
            })}
          </div>
        </div>
      )}

      {/* Expand: individual claims */}
      {v.claims.length > 0 && (
        <>
          <button onClick={() => setClaimsOpen(x => !x)} style={{
            background: 'none', border: '1px solid var(--border)', color: 'var(--muted)',
            borderRadius: 6, padding: '4px 10px', fontSize: 11, cursor: 'pointer', marginRight: 6,
          }}>
            {claimsOpen ? 'Hide claims' : `Show ${v.claims.length} claims`}
          </button>
          {claimsOpen && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 8 }}>
                Each claim was pulled from their site, searched online, and then judged
              </div>
              {v.claims.map((c) => {
                const j = judgeMap[c.claim_id]
                if (!j) return null
                const meta = VERDICT_META[j.verdict]
                return (
                  <div key={c.claim_id} style={{
                    padding: '8px 12px', marginBottom: 6,
                    background: meta.bg, borderRadius: 8, borderLeft: `3px solid ${meta.color}`,
                  }}>
                    <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 4 }}>{c.claim}</div>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 11, color: meta.color, fontWeight: 600 }}>{meta.label}</span>
                      <span style={{ fontSize: 10, color: 'var(--muted)' }}>{Math.round(j.confidence * 100)}% confident</span>
                      {j.escalated && (
                        <span
                          title="The first AI was unsure — a more powerful AI re-checked this claim"
                          style={{ fontSize: 10, color: 'var(--accent2)', cursor: 'help' }}>
                          double-checked
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>{j.rationale}</div>
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}

      {/* Expand: buyer questions */}
      {v.advice && (
        <button onClick={() => setAdviceOpen(x => !x)} style={{
          background: 'none', border: '1px solid var(--border)', color: 'var(--muted)',
          borderRadius: 6, padding: '4px 10px', fontSize: 11, cursor: 'pointer', marginTop: 6,
        }}>
          {adviceOpen ? 'Hide questions' : 'Questions to ask before buying'}
        </button>
      )}
      {adviceOpen && v.advice && (
        <div style={{
          marginTop: 8, padding: '10px 14px', background: 'var(--surface2)',
          borderRadius: 8, fontSize: 12, color: 'var(--text)', lineHeight: 1.7, whiteSpace: 'pre-wrap',
        }}>
          {v.advice}
        </div>
      )}
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

type Phase = 'idle' | 'running' | 'done'

export default function App() {
  const [customText, setCustomText] = useState('')
  const [customError, setCustomError] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [stats, setStats] = useState<RunStats>({
    totalCost: 0, totalTokens: 0, escalations: 0, totalJudgments: 0, calls: 0, elapsedMs: 0,
  })
  const [vendors, setVendors] = useState<VendorResult[]>([])
  const [animedIn, setAnimedIn] = useState<Set<string>>(new Set())
  const [marketResult, setMarketResult] = useState<MarketResult | null>(null)
  const [sidebarWidth, setSidebarWidth] = useState(320)

  const startTimeRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const evtRef = useRef<EventSource | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const draggingRef = useRef(false)

  const stopTimers = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (pollRef.current) clearInterval(pollRef.current)
    if (evtRef.current) evtRef.current.close()
  }, [])

  const fetchResults = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/audit/${id}/results`)
      if (!res.ok) return
      const data: MarketResult = await res.json()
      if (!data.vendors) return
      const sorted = [...data.vendors].sort((a, b) => (b.credibility_score ?? 0) - (a.credibility_score ?? 0))
      setVendors(sorted)
      setMarketResult(data)
      setAnimedIn(prev => { const n = new Set(prev); sorted.forEach(v => n.add(v.vendor)); return n })
    } catch { /* ignore */ }
  }, [])

  const startAudit = useCallback(async () => {
    const vendorUrls = parseVendorText(customText)
    if (vendorUrls.length === 0) {
      setCustomError('No companies found. Format: Company Name, https://website.com')
      return
    }
    setCustomError('')
    stopTimers()
    setPhase('running')
    setStats({ totalCost: 0, totalTokens: 0, escalations: 0, totalJudgments: 0, calls: 0, elapsedMs: 0 })
    setVendors([])
    setAnimedIn(new Set())
    setMarketResult(null)
    startTimeRef.current = Date.now()

    timerRef.current = setInterval(() => {
      setStats(s => ({ ...s, elapsedMs: Date.now() - startTimeRef.current }))
    }, 250)

    try {
      const res = await fetch('/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category: 'Custom',
          vendor_urls: vendorUrls,
          naive: false,
          n: vendorUrls.length,
        }),
      })
      const accepted = await res.json()
      pollRef.current = setInterval(() => fetchResults(accepted.run_id), 3000)
      const es = new EventSource(accepted.stream_url)
      evtRef.current = es
      es.addEventListener('telemetry', (e) => {
        const ev: TelemetryEvent = JSON.parse(e.data)
        setStats(s => ({
          ...s,
          totalCost: s.totalCost + ev.cost_usd,
          totalTokens: s.totalTokens + ev.tokens_in + ev.tokens_out,
          escalations: ev.escalated ? s.escalations + 1 : s.escalations,
          totalJudgments: ev.stage.startsWith('judge') ? s.totalJudgments + 1 : s.totalJudgments,
          calls: s.calls + 1,
        }))
        if (ev.stage === 'market_done') { setPhase('done'); stopTimers(); fetchResults(accepted.run_id) }
      })
      es.onerror = () => { setPhase('done'); stopTimers(); fetchResults(accepted.run_id) }
    } catch (err) {
      console.error(err); setPhase('idle'); stopTimers()
    }
  }, [customText, stopTimers, fetchResults])

  // Drag-to-resize sidebar
  const startDrag = useCallback((e: RMouseEvent) => {
    e.preventDefault()
    draggingRef.current = true
    const onMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return
      setSidebarWidth(w => Math.max(240, Math.min(560, w + ev.movementX)))
    }
    const onUp = () => { draggingRef.current = false; window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [])

  useEffect(() => () => stopTimers(), [stopTimers])

  const activeVendors = parseVendorText(customText)
  const sorted = [...vendors].sort((a, b) => (b.credibility_score ?? -1) - (a.credibility_score ?? -1))

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>

      {/* Header */}
      <header className="glass" style={{
        padding: '14px 32px', borderBottom: '1px solid var(--border)', background: 'var(--surface)',
        display: 'flex', alignItems: 'center', gap: 14,
        boxShadow: '0 4px 24px rgba(0,0,0,0.30)',
      }}>
        <span style={{
          fontSize: 22, fontWeight: 900, letterSpacing: '-0.5px',
          background: 'var(--accent-grad)',
          WebkitBackgroundClip: 'text',
          backgroundClip: 'text',
          color: 'transparent',
        }}>RECEIPTS</span>
        <span style={{ background: 'var(--accent-grad)', color: '#fff', fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4 }}>BETA</span>
        <span style={{ color: 'var(--muted)', fontSize: 12 }}>
          Checks whether AI vendors can actually back up the claims on their website
        </span>
      </header>

      {/* Two-column layout */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>

        {/* Left sidebar: controls */}
        <aside className="glass" style={{
          width: sidebarWidth, flexShrink: 0,
          background: 'var(--surface)', padding: '24px 20px',
          display: 'flex', flexDirection: 'column', gap: 22, overflowY: 'auto',
          borderRight: '1px solid var(--border)',
        }}>

          {/* Vendor input */}
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>
              Which companies do you want to check?
            </div>
            <Tip text="Type one company per line: Name, https://website.com" />
            <div style={{ marginTop: 10 }}>
              <button
                onClick={() => { setCustomText(EXAMPLE_TEXT); setCustomError('') }}
                disabled={phase === 'running'}
                style={{
                  background: 'var(--surface2)', color: 'var(--accent)',
                  border: `1.5px solid var(--accent)`, borderRadius: 7,
                  padding: '6px 14px', fontSize: 12, fontWeight: 600,
                  cursor: phase === 'running' ? 'not-allowed' : 'pointer',
                  marginBottom: 10,
                }}>
                Try it out — load an example
              </button>
              <Tip text="Loads 6 real AI support tool companies so you can see how it works" />
            </div>
            <textarea
              value={customText}
              onChange={e => { setCustomText(e.target.value); setCustomError('') }}
              disabled={phase === 'running'}
              placeholder={'Company Name, https://website.com\nAnother Co, https://another.com'}
              rows={8}
              style={{
                marginTop: 10, width: '100%', boxSizing: 'border-box',
                background: 'var(--surface2)',
                border: `1.5px solid ${customError ? 'var(--red)' : customText.trim() ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 8, color: 'var(--text)', fontSize: 13,
                fontFamily: 'var(--mono)', padding: '10px 12px', resize: 'vertical', outline: 'none',
                lineHeight: 1.6,
              }}
            />
            {customError && <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 5 }}>{customError}</div>}
            {customText.trim() && !customError && (
              <div style={{ color: 'var(--green)', fontSize: 12, marginTop: 5, fontWeight: 600 }}>
                {activeVendors.length} {activeVendors.length === 1 ? 'company' : 'companies'} ready
              </div>
            )}
            <label style={{
              display: 'inline-block', marginTop: 10, background: 'var(--surface2)',
              border: '1px solid var(--border)', borderRadius: 6, padding: '6px 14px',
              fontSize: 12, color: 'var(--muted)', cursor: 'pointer',
            }}>
              Upload a CSV or TXT file
              <input type="file" accept=".csv,.txt" style={{ display: 'none' }}
                onChange={e => {
                  const f = e.target.files?.[0]; if (!f) return
                  const r = new FileReader()
                  r.onload = ev => { setCustomText(ev.target?.result as string ?? ''); setCustomError('') }
                  r.readAsText(f)
                }} />
            </label>
            <Tip text="File format: one company per row — Name, URL" />
          </div>

          {/* Run button */}
          <div>
            <button onClick={startAudit} disabled={phase === 'running'} style={{
              width: '100%',
              background: phase === 'running' ? 'var(--surface2)' : 'var(--accent)',
              color: phase === 'running' ? 'var(--muted)' : '#fff',
              border: 'none', borderRadius: 8, padding: '13px 0', fontSize: 15,
              fontWeight: 700, cursor: phase === 'running' ? 'not-allowed' : 'pointer', transition: 'all 0.15s',
            }}>
              {phase === 'running' ? 'Checking...' : phase === 'done' ? 'Run Again' : 'Check Vendors'}
            </button>
            {activeVendors.length > 0
              ? <Tip text={`Visits ${activeVendors.length} website${activeVendors.length !== 1 ? 's' : ''}, finds marketing claims, searches the web for proof, and scores each claim. Usually takes 60-90 seconds.`} />
              : <Tip text="Add at least one company above to get started." />
            }
          </div>

          {/* Legend */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', letterSpacing: '0.08em', marginBottom: 10, textTransform: 'uppercase' }}>
              What the labels mean
            </div>
            {Object.entries(VERDICT_META).map(([, m]) => (
              <div key={m.label} style={{ marginBottom: 10 }}>
                <div style={{
                  display: 'inline-block', background: m.bg, color: m.color,
                  fontWeight: 600, fontSize: 12, padding: '1px 8px', borderRadius: 5, border: `1px solid ${m.color}`,
                }}>
                  {m.label}
                </div>
                <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3, lineHeight: 1.5 }}>{m.description}</div>
              </div>
            ))}
            <div style={{ marginTop: 6 }}>
              <div style={{ fontSize: 12, color: 'var(--accent2)', fontWeight: 600 }}>double-checked</div>
              <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3, lineHeight: 1.5 }}>
                The first AI was not sure, so a stronger AI re-checked the claim
              </div>
            </div>
          </div>
        </aside>

        {/* Drag handle */}
        <div
          onMouseDown={startDrag}
          style={{
            width: 6, flexShrink: 0,
            background: 'var(--border)',
            cursor: 'col-resize',
            transition: 'background 0.15s',
            position: 'relative',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'var(--border)')}
          title="Drag to resize panel"
        />

        {/* Right: stats + results */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

          {/* Stats bar */}
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)',
            gap: 1, background: 'var(--border)', borderBottom: '1px solid var(--border)', flexShrink: 0,
          }}>
            {[
              { label: 'Total Cost', value: fmtCost(stats.totalCost), tip: 'How much this check cost in AI fees', mono: true },
              { label: 'Time', value: fmtMs(stats.elapsedMs), tip: 'How long the check has been running' },
              { label: 'AI Calls', value: String(stats.calls), tip: 'Total number of AI questions asked' },
              { label: 'Double-checked', value: stats.totalJudgments > 0 ? `${stats.escalations}/${stats.totalJudgments}` : '—', tip: 'Claims that a second AI re-checked' },
              { label: 'Progress', value: activeVendors.length > 0 ? `${vendors.length} / ${activeVendors.length}` : `${vendors.length} done`, tip: 'Companies finished vs total' },
            ].map(({ label, value, tip, mono }) => (
              <div key={label} style={{ background: 'var(--surface)' }}>
                <StatBox label={label} value={value} tip={tip} mono={mono} />
              </div>
            ))}
          </div>

          {/* Results area */}
          <main style={{ flex: 1, overflowY: 'auto', padding: '24px 28px' }}>

            {/* Idle */}
            {phase === 'idle' && (
              <div style={{ textAlign: 'center', marginTop: 60, color: 'var(--muted)' }}>
                <div style={{ fontSize: 52, fontWeight: 900, color: 'var(--accent)', opacity: 0.12, marginBottom: 16 }}>?</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>No results yet</div>
                <div style={{ fontSize: 13, maxWidth: 380, margin: '0 auto', lineHeight: 1.7, color: 'var(--muted)' }}>
                  Type in the companies you want to check on the left, or click{' '}
                  <strong style={{ color: 'var(--text)' }}>Try it out</strong> to load an example.
                  Then hit <strong style={{ color: 'var(--text)' }}>Check Vendors</strong> — results appear here as each one finishes.
                </div>
              </div>
            )}

            {/* Loading */}
            {phase === 'running' && sorted.length === 0 && (
              <div style={{ textAlign: 'center', marginTop: 60, color: 'var(--muted)' }}>
                <div style={{
                  width: 36, height: 36, border: '3px solid var(--border)',
                  borderTop: '3px solid var(--accent)', borderRadius: '50%',
                  margin: '0 auto 16px', animation: 'spin 0.9s linear infinite',
                }} />
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Reading vendor websites...</div>
                <div style={{ fontSize: 12, marginTop: 6 }}>Results appear here as each company finishes</div>
              </div>
            )}

            {/* Summary banner */}
            {phase === 'done' && marketResult && (
              <div style={{
                marginBottom: 20, padding: '14px 20px', background: 'var(--surface)',
                border: '1px solid var(--border)', borderRadius: 10,
                display: 'flex', alignItems: 'center', gap: 32, flexWrap: 'wrap',
                boxShadow: '0 1px 4px rgba(0,0,0,0.05)',
              }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2, textTransform: 'uppercase', fontWeight: 600 }}>Category</div>
                  <div style={{ fontWeight: 700, fontSize: 15 }}>{marketResult.category}</div>
                </div>
                <div title="How many claims were made for every one with an independent public receipt. Higher means more self-reported marketing copy.">
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2, textTransform: 'uppercase', fontWeight: 600 }}>Inflation score</div>
                  <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--yellow)' }}>
                    {marketResult.claim_inflation_index.toFixed(2)}x
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--muted)' }}>claims made per publicly substantiated claim</div>
                </div>
                {!!marketResult.telemetry_summary?.['claim_inflation_note'] && (
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2, textTransform: 'uppercase', fontWeight: 600 }}>Summary</div>
                    <div style={{ fontSize: 12, color: 'var(--text)' }}>
                      {String(marketResult.telemetry_summary['claim_inflation_note'])}
                    </div>
                  </div>
                )}
                <div style={{ marginLeft: 'auto', color: 'var(--green)', fontWeight: 700, fontSize: 13 }}>
                  Check complete
                </div>
              </div>
            )}

            {/* Vendor cards */}
            {sorted.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 14 }}>
                {sorted.map(v => (
                  <VendorCard key={v.vendor} v={v} animIn={animedIn.has(v.vendor)} />
                ))}
              </div>
            )}
          </main>
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
