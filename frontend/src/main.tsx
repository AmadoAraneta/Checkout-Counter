import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import QRCode from 'qrcode'
import { jsPDF } from 'jspdf'
import './styles.css'

const peso = (value: number) => `₱${value.toFixed(2)}`

type Item = { product_id: string; product_name: string; quantity: number; unit_price: number; line_total: number }
type Cart = { cart_id: string; session_id: string; items: Item[]; subtotal: number; parking_fee: number; total: number; currency?: string }
type Payment = { payment_token: string; payment_id?: string; transaction_id?: string; session_id: string; amount: number; method: string; status: string; currency?: string; simulation_reference?: string; transaction_status?: string; mock_url?: string; phone_url?: string; qr_image_url?: string; reused?: boolean; message?: string }
type NfcStatus = { connected: boolean; port: string; baud_rate: number; event_counter?: number; last_event?: { event?: string; uid?: string; key?: string } | null; last_card_uid?: string | null; last_card_at?: string | null; last_key?: string | null; key_sequence?: string; error?: string | null }
type Tx = { transaction_id: string; cart_id: string; session_id: string; subtotal: number; parking_fee: number; amount: number; payment_method: string; timestamp: string; payment_status: string; items: Item[] }

const API = import.meta.env.VITE_API_URL || 'http://localhost:5000/api'
const BACKEND_ORIGIN = API.replace(/\/api\/?$/, '')
async function api<T>(path: string, opt?: RequestInit): Promise<T> { const response = await fetch(API + path, { headers: { 'Content-Type': 'application/json' }, ...opt }); const body = await response.json().catch(() => ({})); if (!response.ok) { const detail = typeof body.detail === 'string' ? body.detail : body.detail?.detail || body.message; throw Error(detail || 'Request failed') } return body }
function normalizedStatus(status: string) { return ({ PENDING: 'waiting', PENDING_PAYMENT: 'waiting', SUCCESS: 'successful', PAYMENT_SUCCESS: 'successful', FAILED: 'failed', PAYMENT_FAILED: 'failed', EXPIRED: 'expired' } as Record<string, string>)[status] || status }
const Btn = ({ children, onClick, kind = 'primary', disabled = false, type = 'button' }: { children: any; onClick?: () => void; kind?: string; disabled?: boolean; type?: 'button' | 'submit' }) => <button type={type} className={'btn ' + kind} disabled={disabled} onClick={onClick}>{children}</button>
const Card = ({ children }: { children: any }) => <section className="card">{children}</section>
const ErrorBox = ({ m }: { m: string }) => <div className="error">{m}</div>
const Status = ({ s }: { s: string }) => <span className={'status ' + s}>{s}</span>

function Scan({ go }: { go: (s: string) => void }) {
  const [sessionId, setSessionId] = useState('DEMO-1001')
  return <div className="narrow page"><p className="eyebrow">CHECKOUT COUNTER · SMART SHOPPING CART</p><h1>Identify cart session</h1><p className="muted">Enter the Ticket ID to see the list of purchase</p><Card><form onSubmit={e => { e.preventDefault(); if (sessionId.trim()) go(sessionId.trim()) }}><label>Ticket Receipt ID<input value={sessionId} onChange={e => setSessionId(e.target.value)} /></label><Btn type="submit" disabled={!sessionId.trim()}>See Purchase</Btn></form><p className="hint">Try DEMO-1001, DEMO-1002, or SHOP-20260928-0007.</p></Card></div>
}
function CartView({ c, go, back }: { c: Cart; go: () => void; back: () => void }) { const subtotal = c.items.reduce((sum, item) => sum + item.quantity * item.unit_price, 0); const valid = c.items.every(item => item.quantity > 0 && Math.abs(item.line_total - item.quantity * item.unit_price) < .01) && Math.abs(subtotal - c.subtotal) < .01 && Math.abs(subtotal + c.parking_fee - c.total) < .01; return <div className="page"><header><div><p className="eyebrow">PURCHASE SUMMARY</p><h1>Review Purchase</h1></div><Btn kind="ghost" onClick={back}>← Change cart</Btn></header><Card><div className="grid"><div><small>Cart ID</small><b>{c.cart_id}</b></div><div><small>Ticket Receipt ID</small><b>{c.session_id}</b></div><div><small>Items</small><b>{c.items.length}</b></div><div><small>Total due</small><b>{peso(c.total)}</b></div></div><table><thead><tr><th>Product</th><th>Qty</th><th>Unit</th><th>Total</th></tr></thead><tbody>{c.items.map(item => <tr key={item.product_id}><td>{item.product_name}<small>{item.product_id}</small></td><td>{item.quantity}</td><td>{peso(item.unit_price)}</td><td>{peso(item.line_total)}</td></tr>)}</tbody></table><div className="total"><span>Items subtotal</span><b>{peso(subtotal)}</b></div><div className="total"><span>Fixed parking fee</span><b>{peso(c.parking_fee)}</b></div><div className="total"><span>Total amount due</span><b>{peso(c.total)}</b></div>{!valid && <ErrorBox m="Cart validation failed. Payment is disabled." />}<Btn onClick={go} disabled={!valid}>Continue to payment selection →</Btn></Card></div> }
function Select({ amount, go, back }: { amount: number; go: (method: string) => void; back: () => void }) { return <div className="narrow page"><p className="eyebrow">PAYMENT SELECTION</p><h1>Choose payment method</h1><p className="muted">Amount due</p><div className="amount">{peso(amount)}</div><div className="banner">PHILIPPINE PESO · SIMULATION ONLY<br /><small>No real money is processed.</small></div><div className="options"><Card><h2>⌁ QR Payment</h2><p>Scan a QR with a phone or approve on this device.</p><Btn onClick={() => go('QR')}>Use simulated QR</Btn></Card><Card><h2>))) NFC Payment</h2><p>Use a simulated NFC tag and keypad confirmation.</p><Btn onClick={() => go('NFC')}>Use simulated NFC</Btn></Card></div><Btn kind="ghost" onClick={back}>← Back to cart</Btn></div> }
  function Pay({ p, success, back }: { p: Payment; success: () => void; back: () => void }) {
  const [status, setStatus] = useState(p.status)
  const [message, setMessage] = useState(p.message || '')
  const [keypadAmount, setKeypadAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [nfc, setNfc] = useState<NfcStatus | null>(null)
  const [detectedUid, setDetectedUid] = useState('')
  const lastEventRef = useRef('')
  const autoSubmittedRef = useRef(false)
  useEffect(() => {
    const timer = window.setInterval(async () => {
      try {
        const result = await api<any>('/payments/' + p.payment_token)
        const nextStatus = normalizedStatus(result.status)
        setStatus(nextStatus)
        if (result.message) setMessage(result.message)
        if (nextStatus === 'successful') success()
      } catch { /* payment may have expired */ }
      if (p.method === 'NFC') {
        try {
          const reader = await api<NfcStatus>('/nfc/status')
          setNfc(reader)
          if (reader.key_sequence) setKeypadAmount(reader.key_sequence)
          if (reader.last_card_uid) setDetectedUid(reader.last_card_uid)
          const event = reader.last_event
          const eventId = String(reader.event_counter || 0)
          if (eventId !== lastEventRef.current) {
            lastEventRef.current = eventId
            if (event?.event === 'card_detected' && event.uid) setDetectedUid(event.uid)
            if (event?.event === 'key_pressed' && event.key === '*') setKeypadAmount('')
          }
        } catch { setNfc(null) }
      }
    }, 700)
    return () => window.clearInterval(timer)
  }, [p.payment_token, p.method, success])
  async function finish(path = 'complete') {
    setBusy(true)
    try {
      const isQrApproval = p.method === 'QR' && path === 'complete'
      const endpoint = isQrApproval ? '/payments/' + p.payment_token + '/confirm' : '/payments/' + p.payment_token + '/' + path
      const body = isQrApproval
        ? JSON.stringify({ confirmation: 'DEMO-APPROVE' })
        : p.method === 'NFC' && path === 'complete'
          ? JSON.stringify({ entered_amount: keypadAmount, card_uid: detectedUid })
          : '{}'
      const result = await api<any>(endpoint, { method: 'POST', body })
      const nextStatus = normalizedStatus(result.status)
      setStatus(nextStatus)
      if (result.message) setMessage(result.message)
      if (nextStatus === 'successful') {
        success()
      } else if (p.method === 'NFC' && nextStatus === 'waiting' && result.message) {
        autoSubmittedRef.current = false
        setDetectedUid('')
        setKeypadAmount('')
        await api('/nfc/reset', { method: 'POST', body: '{}' }).catch(() => undefined)
      }
    } catch (error: any) {
      setStatus(error.message.includes('already confirmed') ? 'successful' : 'failed')
      if (error.message.includes('already confirmed')) success()
    } finally { setBusy(false) }
  }
  useEffect(() => {
    if (p.method === 'NFC' && status === 'waiting' && !busy && detectedUid && keypadAmount.trim() && !autoSubmittedRef.current) {
      autoSubmittedRef.current = true
      finish()
    }
  }, [detectedUid, keypadAmount, status, busy, p.method])
  const physicalNfcReady = Boolean(nfc?.connected || detectedUid)
  const nfcAmountReady = keypadAmount.trim().length > 0
  return <div className="narrow page"><p className="eyebrow">{p.method} PAYMENT</p><h1>{p.method === 'QR' ? 'Scan to pay' : 'Enter amount, then tap Card'}</h1>{p.method === 'QR' && <div className="banner">SIMULATION ONLY · PHILIPPINE PESO<br /><small>No real money is processed.</small></div>}<Card><p className="muted">Cart total</p><div className="amount">{peso(p.amount)}</div>{p.method === 'QR' ? <><img className="qr" src={p.qr_image_url} alt="QR code for simulated payment" /><p className="hint">Scan with a phone on the same network.</p><p className="hint">Phone URL: <code>{p.phone_url || p.mock_url}</code></p><Btn kind="secondary" onClick={() => finish()} disabled={busy || status !== 'waiting'}>Approve on this device</Btn></> : <><div className="nfc">)))</div><p className="waiting">Card reader ready. Place your card when the price is entered.</p><label>Amount entered on keypad<input className="pin" maxLength={16} inputMode="decimal" value={keypadAmount} onChange={e => setKeypadAmount(e.target.value.replace(/[^0-9.]/g, ''))} placeholder="Type price on matrix keypad" /></label><p className="hint">Entered amount: <b>{keypadAmount ? peso(Number(keypadAmount)) : '—'}</b></p>{message && status === 'waiting' && <p className="result failed">{message}</p>}<Btn onClick={() => finish()} disabled={busy || !physicalNfcReady || !nfcAmountReady || status !== 'waiting'}>{physicalNfcReady ? 'Validate amount and pay' : 'Waiting for Payment'}</Btn></>}{status === 'waiting' && <p className="waiting">◌ {p.method === 'QR' ? 'Waiting for QR Payment' : 'Waiting for amount and NFC payment…'}</p>}{status !== 'waiting' && <p className={'result ' + status}><Status s={status} /> {status === 'successful' ? 'Payment successful — loading receipt…' : (message || 'Payment declined. The entered amount did not match.')}</p>}{p.method === 'QR' && <Btn kind="danger" onClick={() => finish('fail')} disabled={status !== 'waiting' || busy}>Simulate payment failure</Btn>}</Card><Btn kind="ghost" onClick={back}>← Choose another method</Btn></div>
}
  function Receipt({ tx, history }: { tx: Tx; history: () => void }) { const [qr, setQr] = useState(''); useEffect(() => { QRCode.toDataURL(BACKEND_ORIGIN + '/receipt/' + tx.transaction_id).then(setQr) }, [tx.transaction_id]); function html() { return '<h1>Checkout Counter Receipt</h1><p>Transaction: ' + tx.transaction_id + '</p>' + tx.items.map(item => '<p>' + item.product_name + ' x ' + item.quantity + ' — PHP ' + item.line_total.toFixed(2) + '</p>').join('') + '<p>Items subtotal: PHP ' + tx.subtotal.toFixed(2) + '</p><p>Fixed parking fee: PHP ' + tx.parking_fee.toFixed(2) + '</p><h2>Total: PHP ' + tx.amount.toFixed(2) + '</h2>' } function downloadHtml() { const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([html()], { type: 'text/html' })); link.download = 'receipt-' + tx.transaction_id + '.html'; link.click() } function downloadPdf() { const doc = new jsPDF(); doc.text('Checkout Counter Receipt', 20, 25); doc.text('Transaction: ' + tx.transaction_id, 20, 40); let y = 50; tx.items.forEach(item => { doc.text(item.product_name + ' x ' + item.quantity + ' - PHP ' + item.line_total.toFixed(2), 20, y); y += 9 }); doc.text('Items subtotal: PHP ' + tx.subtotal.toFixed(2), 20, y + 8); doc.text('Fixed parking fee: PHP ' + tx.parking_fee.toFixed(2), 20, y + 17); doc.text('Total: PHP ' + tx.amount.toFixed(2), 20, y + 26); doc.save('receipt-' + tx.transaction_id + '.pdf') } return <div className="narrow page"><div className="success">✓</div><p className="eyebrow">PAYMENT SUCCESSFUL</p><h1>Receipt ready</h1><Card><div className="receipt-head"><b>{tx.transaction_id}</b><Status s={tx.payment_status} /></div>{tx.items.map(item => <div className="line" key={item.product_id}><span>{item.product_name} × {item.quantity}<small>{peso(item.unit_price)} each</small></span><b>{peso(item.line_total)}</b></div>)}<div className="total"><span>Items subtotal</span><b>{peso(tx.subtotal)}</b></div><div className="total"><span>Fixed parking fee</span><b>{peso(tx.parking_fee)}</b></div><div className="total"><span>Total amount</span><b>{peso(tx.amount)}</b></div><p>Cart: {tx.cart_id}<br />Session: {tx.session_id}<br />Payment: {tx.payment_method} simulation<br />Time: {new Date(tx.timestamp).toLocaleString()}</p><div className="lookup"><span>Receipt lookup QR</span>{qr && <img src={qr} />}</div><Btn onClick={downloadHtml}>Download HTML</Btn> <Btn kind="secondary" onClick={downloadPdf}>Download PDF</Btn></Card><Btn onClick={history}>View transaction history →</Btn></div> }
function History({ back }: { back: () => void }) { const [list, setList] = useState<Tx[]>([]); const [audit, setAudit] = useState<Record<string, any[]>>({}); useEffect(() => { api<Tx[]>('/transactions').then(setList) }, []); return <div className="page"><header><div><p className="eyebrow">AUDIT & REPORTING</p><h1>Transaction history</h1></div><Btn onClick={back}>New checkout</Btn></header><Card>{!list.length ? <p>No transactions yet. Complete a simulated checkout first.</p> : <table><thead><tr><th>Transaction</th><th>Status</th><th>Amount</th><th>Method</th><th>Timestamp</th><th>Audit</th></tr></thead><tbody>{list.map(tx => <tr key={tx.transaction_id}><td>{tx.transaction_id}<small>{tx.session_id}</small></td><td><Status s={tx.payment_status} /></td><td>{peso(tx.amount)}</td><td>{tx.payment_method}</td><td>{new Date(tx.timestamp).toLocaleString()}</td><td><Btn kind="ghost" onClick={async () => setAudit({ ...audit, [tx.transaction_id]: await api<any[]>('/transactions/' + tx.transaction_id + '/audit') })}>View events</Btn>{audit[tx.transaction_id]?.map(event => <small className="audit" key={event.event_id}>{event.event_type}: {event.message}</small>)}</td></tr>)}</tbody></table>}</Card></div> }
function App() { const [step, setStep] = useState('scan'); const [cart, setCart] = useState<Cart>(); const [payment, setPayment] = useState<Payment>(); const [tx, setTx] = useState<Tx>(); const [error, setError] = useState(''); async function load(id: string) { try { setError(''); setCart(await api<Cart>('/carts/' + encodeURIComponent(id))); setStep('cart') } catch (e: any) { setError(e.message) } } async function chooseMethod(method: string) { try { setError(''); setPayment(await api<Payment>('/payments', { method: 'POST', body: JSON.stringify({ session_id: cart!.session_id, payment_method: method, amount: cart!.total }) })); setStep('pay') } catch (e: any) { setError(e.message) } } async function success() { const transactions = await api<Tx[]>('/transactions'); setTx(transactions[0]); setStep('receipt') } function newCheckout() { setStep('scan'); setCart(undefined); setPayment(undefined); setTx(undefined) } return <><nav><b>Checkout Counter <small>SMART SHOPPING CART</small></b><span><button onClick={newCheckout}>New checkout</button> <button onClick={() => setStep('history')}>History</button></span></nav>{error && <div className="global"><ErrorBox m={error} /><button onClick={() => setError('')}>Dismiss</button></div>}{step === 'scan' && <Scan go={load} />}{step === 'cart' && cart && <CartView c={cart} go={() => setStep('select')} back={() => setStep('scan')} />}{step === 'select' && cart && <Select amount={cart.total} go={chooseMethod} back={() => setStep('cart')} />}{step === 'pay' && payment && <Pay p={payment} success={success} back={() => setStep('select')} />}{step === 'receipt' && tx && <Receipt tx={tx} history={() => setStep('history')} />}{step === 'history' && <History back={newCheckout} />}<footer>Demo/simulation only · JSON API + FastAPI · Philippine peso display</footer></> }
createRoot(document.getElementById('root')!).render(<App />)
