import { useState, useEffect, useRef, useCallback } from 'react'

// ── Types ──────────────────────────────────────────────────────────────────

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
  claims: { claim: string; metric: string | null; magnitude: string | null }[]
  judgments: Judgment[]
  credibility_score: number | null
  advice: string | null
}

interface MarketResult {
  category: string
  vendors: VendorResult[]
  claim_inflation_index: number
}

interface RunStats {
  totalCost: number
  totalTokens: number
  escalations: number
  totalJudgments: number
  calls: number
  elapsedMs: number
}

// ── Preset vendor lists ─────────────────────────────────────────────────────

const PRESETS: Record<string, [string, string][]> = {
  'AI Support Agents': [
    ['Intercom Fin', 'https://www.intercom.com/fin'],
    ['Decagon', 'https://decagon.ai'],
    ['Zendesk AI', 'https://www.zendesk.com/service/ai'],
    ['Forethought', 'https://forethought.ai'],
    ['Tidio', 'https://www.tidio.com'],
    ['Freshdesk AI', 'https://www.freshworks.com/freshdesk'],
  ],
  'AI SDRs': [
    ['11x', 'https://www.11x.ai'],
    ['Artisan', 'https://www.artisan.co'],
    ['Qualified', 'https://www.qualified.com'],
    ['AiSDR', 'https://aisdr.com'],
    ['Regie.ai', 'https://www.regie.ai'],
    ['Outreach', 'https://www.outreach.io'],
  ],
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const VERDICT_META = {
  SUPPORTED: { emoji: '✅', label: 'Supported', color: '#22c55e' },
  SELF_REPORTED_ONLY: { emoji: '⚠️', label: 'Self-reported', color: '#f59e0b' },
  NO_PUBLIC_RECEIPT_FOUND: { emoji: '❌', label: 'No receipt', color: '#ef4444' },
}

function scoreColor(score: number | null): string {
  if (score === null) return '#64748b'
  if (score >= 0.7) return '#22c55e'
  if (score >= 0.4) return '#f59e0b'
  return '#ef4444'
}

function fmtCost(n: number): string {
  return `$${n.toFixed(4)}`
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// ── VendorCard ───────────────────────────────────────────────────────────────

function VendorCard({ v, animIn }: { v: VendorResult; animIn: boolean }) {
  const [open, setOpen] = useState(false)
  const score = v.credibility_score
  const pct = score !== null ? Math.round(score * 100) : null

  const counts = v.judgments.reduce(
    (acc, j) => { acc[j.verdict] = (acc[j.verdict] || 0) + 1; return acc },
    {} as Record<string, number>
  )

  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: '16px 18px',
      transition: 'transform 0.3s ease, opacity 0.3s ease',
      opacity: animIn ? 1 : 0,
      transform: animIn ? 'translateY(0)' : 'translateY(16px)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{v.vendor}</div>
          <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 2 }}>{v.url}</div>
        </div>
        {pct !== null && (
          <div style={{
            background: scoreColor(score),
            color: '#000',
            fontWeight: 800,
            fontSize: 18,
            borderRadius: 8,
            padding: '4px 10px',
            lineHeight: 1.2,
          }}>
            {pct}%
          </div>
        )}
      </div>

      {/* Score bar */}
      {pct !== null && (
        <div style={{ height: 4, background: 'var(--border)', borderRadius: 2, marginBottom: 12, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: scoreColor(score), transition: 'width 0.8s ease' }} />
        </div>
      )}

      {v.status !== 'ok' && (
        <div style={{ color: 'var(--muted)', fontSize: 12, fontStyle: 'italic', marginBottom: 8 }}>
          {v.status === 'unreachable' ? '⚡ Page unreachable' : '⚡ No quantified claims found'}
        </div>
      )}

      {/* Verdict badges */}
      {v.judgments.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
          {Object.entries(counts).map(([verdict, count]) => {
            const meta = VERDICT_META[verdict as keyof typeof VERDICT_META]
            return (
              <span key={verdict} style={{
                background: 'var(--surface2)',
                border: `1px solid ${meta.color}40`,
                color: meta.color,
                borderRadius: 6,
                padding: '2px 8px',
                fontSize: 11,
                fontWeight: 600,
              }}>
                {meta.emoji} {count} {meta.label}
              </span>
            )
          })}
        </div>
      )}

      {/* Expand advice */}
      {v.advice && (
        <button
          onClick={() => setOpen(x => !x)}
          style={{
            background: 'none', border: '1px solid var(--border)', color: 'var(--muted)',
            borderRadius: 6, padding: '4px 10px', fontSize: 11, cursor: 'pointer',
            marginTop: 4,
          }}
        >
          {open ? '▲ Hide advice' : '▼ Buyer advice'}
        </button>
      )}
      {open && v.advice && (
        <div style={{
          marginTop: 10, padding: '10px 12px', background: 'var(--surface2)',
          borderRadius: 8, fontSize: 12, color: '#cbd5e1', lineHeight: 1.7,
          whiteSpace: 'pre-wrap',
        }}>
          {v.advice}
        </div>
      )}
    </div>
  )
}

// ── Live ticker ──────────────────────────────────────────────────────────────

function StatBox({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{
        fontSize: mono ? 22 : 20,
        fontWeight: 700,
        fontFamily: mono ? 'var(--mono)' : undefined,
        color: '#e2e8f0',
      }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{label}</div>
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────────────────────

type Phase = 'idle' | 'running' | 'done'

export default function App() {
  const [category, setCategory] = useState<string>('AI Support Agents')
  const [phase, setPhase] = useState<Phase>('idle')
  const [stats, setStats] = useState<RunStats>({ totalCost: 0, totalTokens: 0, escalations: 0, totalJudgments: 0, calls: 0, elapsedMs: 0 })
  const [vendors, setVendors] = useState<VendorResult[]>([])
  const [animedIn, setAnimedIn] = useState<Set<string>>(new Set())
  const [marketResult, setMarketResult] = useState<MarketResult | null>(null)
  const [runId, setRunId] = useState<string | null>(null)

  const startTimeRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const evtRef = useRef<EventSource | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

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
      // animate new cards in
      setAnimedIn(prev => {
        const next = new Set(prev)
        sorted.forEach(v => next.add(v.vendor))
        return next
      })
    } catch { /* ignore */ }
  }, [])

  const startAudit = useCallback(async () => {
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

    const payload = {
      category,
      vendor_urls: PRESETS[category],
      naive: false,
      n: PRESETS[category].length,
    }

    try {
      const res = await fetch('/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const accepted = await res.json()
      setRunId(accepted.run_id)

      // Poll results every 3s
      pollRef.current = setInterval(() => fetchResults(accepted.run_id), 3000)

      // SSE for telemetry
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
        if (ev.stage === 'market_done') {
          setPhase('done')
          stopTimers()
          fetchResults(accepted.run_id)
        }
      })

      es.onerror = () => {
        setPhase('done')
        stopTimers()
        fetchResults(accepted.run_id)
      }
    } catch (err) {
      console.error(err)
      setPhase('idle')
      stopTimers()
    }
  }, [category, stopTimers, fetchResults])

  useEffect(() => () => stopTimers(), [stopTimers])

  const sorted = [...vendors].sort((a, b) => (b.credibility_score ?? -1) - (a.credibility_score ?? -1))

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* ── Header ── */}
      <header style={{
        padding: '20px 32px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'var(--surface)',
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 28, fontWeight: 900, letterSpacing: '-1px', color: 'var(--accent)' }}>RECEIPTS</span>
            <span style={{
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 9,
              fontWeight: 800,
              padding: '2px 6px',
              borderRadius: 4,
              letterSpacing: '0.05em',
            }}>BETA</span>
          </div>
          <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 2 }}>
            Pics or it didn't happen — for enterprise AI
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {Object.keys(PRESETS).map(k => (
            <button
              key={k}
              onClick={() => setCategory(k)}
              disabled={phase === 'running'}
              style={{
                background: category === k ? 'var(--accent)' : 'var(--surface2)',
                color: category === k ? '#fff' : 'var(--muted)',
                border: `1px solid ${category === k ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 8,
                padding: '7px 14px',
                fontSize: 13,
                fontWeight: 600,
                cursor: phase === 'running' ? 'not-allowed' : 'pointer',
                transition: 'all 0.15s',
              }}
            >{k}</button>
          ))}
          <button
            onClick={startAudit}
            disabled={phase === 'running'}
            style={{
              background: phase === 'running' ? 'var(--surface2)' : 'var(--accent)',
              color: phase === 'running' ? 'var(--muted)' : '#fff',
              border: 'none',
              borderRadius: 8,
              padding: '8px 20px',
              fontSize: 13,
              fontWeight: 700,
              cursor: phase === 'running' ? 'not-allowed' : 'pointer',
              marginLeft: 4,
              transition: 'all 0.15s',
            }}
          >
            {phase === 'running' ? '⏳ Auditing…' : phase === 'done' ? '🔄 Re-run' : '▶ Run Audit'}
          </button>
        </div>
      </header>

      {/* ── Stats Bar ── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(5, 1fr)',
        gap: 1,
        background: 'var(--border)',
        borderBottom: '1px solid var(--border)',
      }}>
        {[
          { label: 'Total Cost', value: fmtCost(stats.totalCost), mono: true },
          { label: 'Elapsed', value: fmtMs(stats.elapsedMs) },
          { label: 'LLM Calls', value: String(stats.calls) },
          { label: 'Escalations', value: stats.totalJudgments > 0 ? `${stats.escalations}/${stats.totalJudgments}` : '—' },
          { label: 'Vendors Done', value: `${vendors.length}/${PRESETS[category]?.length ?? 0}` },
        ].map(({ label, value, mono }) => (
          <div key={label} style={{ background: 'var(--surface)', padding: '14px 0' }}>
            <StatBox label={label} value={value} mono={mono} />
          </div>
        ))}
      </div>

      {/* ── Main content ── */}
      <main style={{ flex: 1, padding: '28px 32px', maxWidth: 1200, margin: '0 auto', width: '100%' }}>

        {phase === 'idle' && (
          <div style={{ textAlign: 'center', marginTop: 80 }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>🧾</div>
            <div style={{ fontSize: 24, fontWeight: 800, marginBottom: 8 }}>Ready to audit</div>
            <div style={{ color: 'var(--muted)', maxWidth: 440, margin: '0 auto' }}>
              Select a category above and click <strong style={{ color: 'var(--text)' }}>Run Audit</strong> to check which vendors can back up their claims.
            </div>
          </div>
        )}

        {(phase === 'running' || phase === 'done') && sorted.length === 0 && (
          <div style={{ textAlign: 'center', marginTop: 80 }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>
              <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite' }}>⏳</span>
            </div>
            <div style={{ color: 'var(--muted)' }}>Scraping vendor pages and verifying claims…</div>
          </div>
        )}

        {sorted.length > 0 && (
          <>
            {phase === 'done' && marketResult && (
              <div style={{
                marginBottom: 24,
                padding: '14px 20px',
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 10,
                display: 'flex',
                alignItems: 'center',
                gap: 24,
                flexWrap: 'wrap',
              }}>
                <div>
                  <span style={{ color: 'var(--muted)', fontSize: 12 }}>Category</span>
                  <div style={{ fontWeight: 700, fontSize: 16 }}>{marketResult.category}</div>
                </div>
                <div>
                  <span style={{ color: 'var(--muted)', fontSize: 12 }}>Claim Inflation Index</span>
                  <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--yellow)' }}>
                    {marketResult.claim_inflation_index.toFixed(2)}×
                  </div>
                </div>
                <div style={{ marginLeft: 'auto', color: 'var(--green)', fontWeight: 700 }}>
                  ✓ Audit complete
                </div>
              </div>
            )}

            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
              gap: 16,
            }}>
              {sorted.map(v => (
                <VendorCard key={v.vendor} v={v} animIn={animedIn.has(v.vendor)} />
              ))}
            </div>
          </>
        )}
      </main>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}
