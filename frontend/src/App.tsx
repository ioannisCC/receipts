import { useState, useEffect, useRef, useCallback, MouseEvent as RMouseEvent } from 'react'
import { ReceiptsLogo } from './components/ReceiptsLogo'

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
    color: 'var(--verdict-good)',
    bg: 'var(--verdict-good-soft)',
    description: 'Independent public sources (case studies, third-party reviews, published methodology) corroborate this claim. We report public substantiation, not truth — absence of evidence here is not proof a claim is false.',
  },
  SELF_REPORTED_ONLY: {
    label: 'Self-reported only',
    color: 'var(--verdict-warn)',
    bg: 'var(--verdict-warn-soft)',
    description: "The claim appears only on the vendor's own surfaces (site, blog, press releases). No independent public source echoes it — a signal, not a verdict on truth.",
  },
  NO_PUBLIC_RECEIPT_FOUND: {
    label: 'No public receipt',
    color: 'var(--verdict-bad)',
    bg: 'var(--verdict-bad-soft)',
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
  if (score >= 0.7) return 'var(--verdict-good)'
  if (score >= 0.4) return 'var(--verdict-warn)'
  return 'var(--verdict-bad)'
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

function RotatingText({ phrases, intervalMs = 2800 }: { phrases: string[]; intervalMs?: number }) {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI(idx => (idx + 1) % phrases.length), intervalMs)
    return () => clearInterval(t)
  }, [phrases.length, intervalMs])
  return <span key={i} className="rotate-fade">{phrases[i]}</span>
}

function Tip({ text }: { text: string }) {
  return (
    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, lineHeight: 1.5 }}>
      {text}
    </div>
  )
}

function StatBox({ label, value, tip, mono }: { label: string; value: string; tip: string; mono?: boolean }) {
  return (
    <div style={{ textAlign: 'left', padding: '16px 22px' }} title={tip}>
      <div style={{
        fontSize: 10, color: 'var(--muted)', marginBottom: 6,
        textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.12em',
      }}>
        {label}
      </div>
      <div style={{
        fontSize: 22, fontWeight: 600,
        fontFamily: mono ? 'var(--font-mono)' : 'var(--font-serif)',
        color: 'var(--text)', letterSpacing: '-0.02em', lineHeight: 1,
      }}>
        {value}
      </div>
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
      borderRadius: 18,
      padding: '20px 22px',
      transition: 'opacity 0.4s ease, transform 0.4s ease',
      opacity: animIn ? 1 : 0,
      transform: animIn ? 'translateY(0)' : 'translateY(20px)',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-serif)', fontWeight: 600, fontSize: 19, color: 'var(--text)', letterSpacing: '-0.01em', lineHeight: 1.25 }}>
            {v.vendor}
          </div>
          <a href={v.url} target="_blank" rel="noreferrer"
            style={{ color: 'var(--muted)', fontSize: 11, marginTop: 3, display: 'block', textDecoration: 'none', fontFamily: 'var(--font-mono)' }}>
            {v.url.replace(/^https?:\/\//, '')}
          </a>
        </div>
        {pct !== null ? (
          <div
            title={vendorStatusTitle(v)}
            style={{
              color: scoreColor(score), fontFamily: 'var(--font-serif)', fontWeight: 600,
              fontSize: 28, lineHeight: 1, letterSpacing: '-0.02em', cursor: 'help',
            }}>
            {pct}
          </div>
        ) : (
          <div
            title={vendorStatusTitle(v)}
            style={{
              fontSize: 11,
              color: 'var(--muted)',
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
          style={{ height: 2, background: 'rgba(15,23,42,0.06)', borderRadius: 2, marginBottom: 14, overflow: 'hidden', cursor: 'help' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: scoreColor(score), transition: 'width 0.8s ease', opacity: 0.7 }} />
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

      {/* Verdict badges — neutral pills */}
      {v.judgments.length > 0 && (
        <div style={{ marginBottom: 14, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {Object.entries(counts).map(([verdict, count]) => {
            const meta = VERDICT_META[verdict as keyof typeof VERDICT_META]
            return (
              <span key={verdict} title={meta.description} style={{
                background: meta.bg,
                color: meta.color,
                borderRadius: 9999,
                padding: '3px 11px',
                fontSize: 11,
                fontWeight: 500,
                letterSpacing: '-0.005em',
                cursor: 'help',
              }}>
                <strong style={{ fontWeight: 600 }}>{count}</strong> {meta.label.toLowerCase()}
              </span>
            )
          })}
        </div>
      )}

      {/* Expand: individual claims */}
      {v.claims.length > 0 && (
        <>
          <button onClick={() => setClaimsOpen(x => !x)} className="pill" style={{ height: 30, fontSize: 12, padding: '0 14px', marginRight: 6 }}>
            {claimsOpen ? 'Hide claims' : `${v.claims.length} claim${v.claims.length === 1 ? '' : 's'}`}
          </button>
          {claimsOpen && (
            <div style={{ marginTop: 12 }}>
              {v.claims.map((c) => {
                const j = judgeMap[c.claim_id]
                if (!j) return null
                const meta = VERDICT_META[j.verdict]
                return (
                  <div key={c.claim_id} style={{
                    padding: '12px 14px', marginBottom: 8,
                    background: meta.bg, borderRadius: 12,
                    border: '1px solid rgba(15,23,42,0.05)',
                  }}>
                    <div style={{ fontSize: 13, color: 'var(--text)', marginBottom: 6, fontFamily: 'var(--font-serif)', fontWeight: 500, lineHeight: 1.4 }}>
                      {c.claim}
                    </div>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 4 }}>
                      <span style={{ fontSize: 10, color: meta.color, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                        {meta.label}
                      </span>
                      <span style={{ fontSize: 10, color: 'var(--muted)' }}>{Math.round(j.confidence * 100)}% confidence</span>
                      {j.escalated && (
                        <span
                          title="Cheap-tier model was uncertain — frontier model re-checked this claim"
                          style={{ fontSize: 10, color: 'var(--accent)', cursor: 'help', fontWeight: 500 }}>
                          re-checked
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-2)', lineHeight: 1.5 }}>{j.rationale}</div>
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}

      {/* Expand: buyer questions */}
      {v.advice && (
        <button onClick={() => setAdviceOpen(x => !x)} className="pill" style={{ height: 30, fontSize: 12, padding: '0 14px', marginTop: 8 }}>
          {adviceOpen ? 'Hide questions' : 'Questions for the vendor'}
        </button>
      )}
      {adviceOpen && v.advice && (
        <div style={{
          marginTop: 10, padding: '14px 16px',
          background: 'var(--surface-2)',
          borderRadius: 12,
          border: '1px solid var(--border)',
          fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.65, whiteSpace: 'pre-wrap',
          fontFamily: 'var(--font-serif)',
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

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (!f) return
    const r = new FileReader()
    r.onload = ev => { setCustomText(ev.target?.result as string ?? ''); setCustomError('') }
    r.readAsText(f)
  }

  return (
    <>
      {/* Aurora gradient backdrop — radial blooms over a diagonal warm→cool
          base, with two slowly drifting linear-gradient layers on top. */}
      <div className="aurora-bg" />

      {/* Tiny floating header — only shown when audit is running/done.
          In demo idle the brand sits big in the centre of the hero. */}
      {phase !== 'idle' && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 20,
          padding: '24px 36px',
          display: 'flex', alignItems: 'center', gap: 12,
          pointerEvents: 'none',
        }}>
          <div className="reveal-fade d-0" style={{
            display: 'flex', alignItems: 'center', gap: 10,
            color: 'var(--text)',
          }}>
            <ReceiptsLogo size={20} className="headline-fade" />
            <span className="headline-fade" style={{
              fontFamily: 'var(--font-sans)', fontSize: 20, fontWeight: 700,
              letterSpacing: '-0.035em', lineHeight: 1,
            }}>Receipts</span>
          </div>
          <span className="reveal-fade d-1" style={{
            color: 'var(--muted)', fontSize: 12,
            fontFamily: 'var(--font-sans)',
          }}>
            Burden of proof{' '}
            <RotatingText phrases={[
              'for AI vendor claims.',
              'at market scale.',
              'with public receipts.',
            ]} />
          </span>
        </div>
      )}

      {phase === 'idle' ? (
        /* ───── IDLE HERO (demo) ───── */
        <div style={{
          minHeight: '100vh',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: '64px 24px 80px',
        }}>
          <div style={{ maxWidth: 660, width: '100%', textAlign: 'center' }}>

            {/* Receipts brand — big, centred */}
            <div className="reveal-up d-0" style={{ marginBottom: 14, color: 'oklch(0.18 0.02 270 / 0.85)' }}>
              <ReceiptsLogo size={44} />
            </div>
            <h1 className="reveal-up d-1 headline-fade" style={{
              fontFamily: 'var(--font-sans)',
              fontSize: 'clamp(56px, 8vw, 112px)',
              fontWeight: 700, letterSpacing: '-0.055em', lineHeight: 1,
              margin: 0, marginBottom: 16,
            }}>
              Receipts
            </h1>

            <div className="reveal-up d-2" style={{
              color: 'var(--text-2)',
              fontSize: 'clamp(17px, 2vw, 22px)',
              fontFamily: 'var(--font-sans)', fontWeight: 400,
              lineHeight: 1.4, letterSpacing: '-0.01em',
              marginBottom: 36, maxWidth: 560,
              marginLeft: 'auto', marginRight: 'auto',
            }}>
              Burden of proof,{' '}
              <RotatingText phrases={[
                'at market scale.',
                'across every vendor.',
                'with public receipts.',
              ]} />
            </div>

            <div className="reveal-up d-3" style={{ marginBottom: 18 }}>
              <textarea
                value={customText}
                onChange={e => { setCustomText(e.target.value); setCustomError('') }}
                placeholder={'Intercom Fin, https://www.intercom.com/fin\nDecagon, https://decagon.ai\n…'}
                rows={6}
                style={{
                  width: '100%', boxSizing: 'border-box',
                  background: 'rgba(255,255,255,0.65)',
                  border: `1px solid ${customError ? 'var(--verdict-bad)' : 'var(--border)'}`,
                  borderRadius: 18, color: 'var(--text)', fontSize: 13.5,
                  fontFamily: 'var(--font-mono)', padding: '18px 22px',
                  resize: 'vertical', outline: 'none', lineHeight: 1.75,
                  boxShadow: '0 10px 40px rgba(15,23,42,0.06), inset 0 1px 0 rgba(255,255,255,0.9)',
                  backdropFilter: 'blur(20px) saturate(180%)',
                  WebkitBackdropFilter: 'blur(20px) saturate(180%)',
                  transition: 'border-color 0.2s, box-shadow 0.2s',
                }}
              />
              {customError && (
                <div style={{ color: 'var(--verdict-bad)', fontSize: 12, marginTop: 8, textAlign: 'left' }}>
                  {customError}
                </div>
              )}
            </div>

            <div className="reveal-up d-4" style={{ marginBottom: 14 }}>
              <button
                onClick={startAudit}
                disabled={activeVendors.length === 0}
                className="pill pill-primary"
                style={{ height: 52, fontSize: 14.5, padding: '0 36px', minWidth: 220 }}
              >
                Audit the market →
              </button>
            </div>

            <div className="reveal-up d-5" style={{
              fontSize: 12, color: 'var(--muted)',
              display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 14,
              flexWrap: 'wrap',
            }}>
              {activeVendors.length > 0 ? (
                <span>{activeVendors.length} {activeVendors.length === 1 ? 'vendor' : 'vendors'} parsed · usually 15–60s</span>
              ) : (
                <>
                  <button
                    onClick={() => { setCustomText(EXAMPLE_TEXT); setCustomError('') }}
                    style={{
                      background: 'none', border: 'none', color: 'var(--accent)',
                      fontSize: 12, cursor: 'pointer', fontFamily: 'var(--font-sans)',
                      textDecoration: 'underline', textUnderlineOffset: 3, padding: 0,
                    }}>
                    load 6 example vendors
                  </button>
                  <span>·</span>
                  <label style={{
                    cursor: 'pointer', textDecoration: 'underline', textUnderlineOffset: 3,
                    color: 'var(--muted)',
                  }}>
                    upload .csv / .txt
                    <input type="file" accept=".csv,.txt" style={{ display: 'none' }} onChange={handleFileUpload} />
                  </label>
                </>
              )}
            </div>
          </div>
        </div>
      ) : (
      /* ───── ACTIVE LAYOUT (running / done) ───── */
      <div className="reveal-fade" style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column',
        paddingTop: 56,
      }}>
        {/* Two-column layout */}
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>

        {/* Left sidebar: controls — slides in from the left */}
        <aside className="reveal-left d-1" style={{
          width: sidebarWidth, flexShrink: 0,
          background: 'rgba(255,255,255,0.35)',
          backdropFilter: 'blur(20px) saturate(180%)',
          WebkitBackdropFilter: 'blur(20px) saturate(180%)',
          padding: '28px 24px',
          display: 'flex', flexDirection: 'column', gap: 26, overflowY: 'auto',
          borderRight: '1px solid var(--border)',
        }}>

          {/* Vendor input */}
          <div>
            <div style={{
              fontFamily: 'var(--font-serif)', fontWeight: 600, fontSize: 18,
              color: 'var(--text)', marginBottom: 2, letterSpacing: '-0.01em',
            }}>
              Which vendors?
            </div>
            <Tip text="One per line: Name, https://website.com" />
            <div style={{ marginTop: 12 }}>
              <button
                onClick={() => { setCustomText(EXAMPLE_TEXT); setCustomError('') }}
                disabled={phase === 'running'}
                className="pill"
                style={{ height: 32, fontSize: 12 }}>
                Load example
              </button>
            </div>
            <textarea
              value={customText}
              onChange={e => { setCustomText(e.target.value); setCustomError('') }}
              disabled={phase === 'running'}
              placeholder={'Company Name, https://website.com\nAnother Co, https://another.com'}
              rows={7}
              style={{
                marginTop: 12, width: '100%', boxSizing: 'border-box',
                background: 'rgba(255,255,255,0.6)',
                border: `1px solid ${customError ? 'var(--verdict-bad)' : 'var(--border)'}`,
                borderRadius: 12, color: 'var(--text)', fontSize: 13,
                fontFamily: 'var(--font-mono)', padding: '12px 14px', resize: 'vertical', outline: 'none',
                lineHeight: 1.65,
                transition: 'border-color 0.15s',
              }}
            />
            {customError && <div style={{ color: 'var(--verdict-bad)', fontSize: 12, marginTop: 6 }}>{customError}</div>}
            {customText.trim() && !customError && (
              <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 6 }}>
                {activeVendors.length} {activeVendors.length === 1 ? 'vendor' : 'vendors'} parsed
              </div>
            )}
            <label className="pill" style={{ marginTop: 10, height: 30, fontSize: 11 }}>
              Upload .csv / .txt
              <input type="file" accept=".csv,.txt" style={{ display: 'none' }}
                onChange={e => {
                  const f = e.target.files?.[0]; if (!f) return
                  const r = new FileReader()
                  r.onload = ev => { setCustomText(ev.target?.result as string ?? ''); setCustomError('') }
                  r.readAsText(f)
                }} />
            </label>
          </div>

          {/* Run button */}
          <div>
            <button onClick={startAudit} disabled={phase === 'running'}
              className="pill pill-primary"
              style={{ width: '100%', height: 48, fontSize: 14, fontWeight: 500 }}>
              {phase === 'running' ? 'Auditing…' : phase === 'done' ? 'Audit again' : 'Audit the market'}
            </button>
            {activeVendors.length > 0
              ? <Tip text={`Reads ${activeVendors.length} page${activeVendors.length !== 1 ? 's' : ''}, hunts public receipts, scores. ≈ 15–90s.`} />
              : <Tip text="Add at least one vendor above to start." />
            }
          </div>

          {/* Legend */}
          <div>
            <div style={{
              fontFamily: 'var(--font-sans)', fontSize: 10, fontWeight: 600,
              color: 'var(--muted)', letterSpacing: '0.12em',
              marginBottom: 12, textTransform: 'uppercase',
            }}>
              Verdicts
            </div>
            {Object.entries(VERDICT_META).map(([, m]) => (
              <div key={m.label} style={{ marginBottom: 12 }}>
                <span style={{
                  display: 'inline-block', background: m.bg, color: m.color,
                  fontWeight: 500, fontSize: 11, padding: '2px 10px', borderRadius: 9999,
                  letterSpacing: '-0.005em',
                }}>
                  {m.label}
                </span>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5, lineHeight: 1.55 }}>{m.description}</div>
              </div>
            ))}
            <div style={{ marginTop: 4 }}>
              <span style={{
                display: 'inline-block', fontSize: 11, color: 'var(--accent)', fontWeight: 500,
                padding: '2px 10px', borderRadius: 9999,
                background: 'var(--accent-soft)',
              }}>re-checked</span>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5, lineHeight: 1.55 }}>
                Cheap-tier was uncertain — frontier model re-judged this claim. The visible cost of the cascade routing.
              </div>
            </div>
          </div>
        </aside>

        {/* Drag handle */}
        <div
          onMouseDown={startDrag}
          style={{
            width: 1, flexShrink: 0,
            background: 'var(--border)',
            cursor: 'col-resize',
            transition: 'background 0.15s, width 0.15s',
            position: 'relative',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'var(--text-2)'; e.currentTarget.style.width = '2px' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'var(--border)'; e.currentTarget.style.width = '1px' }}
          title="Drag to resize panel"
        />

        {/* Right: stats + results */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

          {/* Stats bar — slides down from the top */}
          <div className="reveal-down d-2" style={{
            display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)',
            background: 'rgba(255,255,255,0.45)',
            backdropFilter: 'blur(20px) saturate(180%)',
            WebkitBackdropFilter: 'blur(20px) saturate(180%)',
            borderBottom: '1px solid var(--border)',
            flexShrink: 0,
          }}>
            {[
              { label: 'Total cost', value: fmtCost(stats.totalCost), tip: 'AI inference spend on this audit', mono: true },
              { label: 'Elapsed', value: fmtMs(stats.elapsedMs), tip: 'Wall-clock time since the audit started' },
              { label: 'Calls', value: String(stats.calls), tip: 'External calls measured by the telemetry bus' },
              { label: 'Re-checked', value: stats.totalJudgments > 0 ? `${stats.escalations}/${stats.totalJudgments}` : '—', tip: 'Cheap-tier escalations to the frontier model — the cascade in action' },
              { label: 'Progress', value: activeVendors.length > 0 ? `${vendors.length} / ${activeVendors.length}` : `${vendors.length} done`, tip: 'Vendors completed vs total' },
            ].map(({ label, value, tip, mono }, i) => (
              <div key={label} className={`reveal-up d-${3 + i}`} style={{
                borderLeft: i === 0 ? 'none' : '1px solid var(--border)',
              }}>
                <StatBox label={label} value={value} tip={tip} mono={mono} />
              </div>
            ))}
          </div>

          {/* Results area — fades in after the stats bar lands */}
          <main className="reveal-fade d-3" style={{ flex: 1, overflowY: 'auto', padding: '32px 36px' }}>

            {/* Loading */}
            {phase === 'running' && sorted.length === 0 && (
              <div style={{ textAlign: 'center', marginTop: 100, color: 'var(--muted)' }}>
                <div style={{
                  width: 32, height: 32, border: '2px solid var(--border)',
                  borderTop: '2px solid var(--text)', borderRadius: '50%',
                  margin: '0 auto 18px', animation: 'spin 0.9s linear infinite',
                }} />
                <div style={{ fontSize: 14, color: 'var(--text)', fontFamily: 'var(--font-serif)', fontWeight: 500, letterSpacing: '-0.005em' }}>
                  Reading vendor pages…
                </div>
                <div style={{ fontSize: 12, marginTop: 6 }}>Cards appear as each vendor finishes</div>
              </div>
            )}

            {/* Summary banner */}
            {phase === 'done' && marketResult && (
              <div className="glass" style={{
                marginBottom: 28, padding: '20px 24px',
                borderRadius: 18,
                display: 'flex', alignItems: 'baseline', gap: 40, flexWrap: 'wrap',
              }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 4, textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.12em' }}>Category</div>
                  <div style={{ fontFamily: 'var(--font-serif)', fontWeight: 600, fontSize: 22, letterSpacing: '-0.015em' }}>{marketResult.category}</div>
                </div>
                <div title="How many claims were made for every one with an independent public receipt. Higher means more self-reported marketing copy.">
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 4, textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.12em' }}>Inflation</div>
                  <div style={{ fontFamily: 'var(--font-serif)', fontWeight: 600, fontSize: 22, color: 'var(--verdict-warn)', letterSpacing: '-0.015em' }}>
                    {marketResult.claim_inflation_index.toFixed(2)}×
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>claims per substantiated claim</div>
                </div>
                {!!marketResult.telemetry_summary?.['claim_inflation_note'] && (
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 4, textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.12em' }}>Note</div>
                    <div style={{ fontSize: 13, color: 'var(--text-2)', fontFamily: 'var(--font-serif)', fontStyle: 'italic' }}>
                      {String(marketResult.telemetry_summary['claim_inflation_note'])}
                    </div>
                  </div>
                )}
                <div style={{ marginLeft: 'auto', color: 'var(--verdict-good)', fontSize: 12, fontWeight: 500, letterSpacing: '-0.005em' }}>
                  Audit complete
                </div>
              </div>
            )}

            {/* Vendor cards */}
            {sorted.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 18 }}>
                {sorted.map(v => (
                  <VendorCard key={v.vendor} v={v} animIn={animedIn.has(v.vendor)} />
                ))}
              </div>
            )}
          </main>
        </div>
      </div>
      </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </>
  )
}
