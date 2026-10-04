import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserMultiFormatReader } from '@zxing/browser'
import QRCode from 'qrcode'
import { jsPDF } from 'jspdf'
import './styles.css'

type Item = { product_id: string; product_name: string; quantity: number; unit_price: number; line_total: number }
type Cart = { cart_id: string; session_id: string; items: Item[]; subtotal?: number; total: number; currency?: string }
type Payment = { payment_token: string; payment_id?: string; transaction_id?: string; session_id: string; amount: number; method: string; status: string; mock_url?: string; phone_url?: string; qr_image_url?: string }
type Tx = { transaction_id: string; cart_id: string; session_id: string; amount: number; payment_method: string; timestamp: string; payment_status: string; items: Item[] }

const API = import.meta.env.VITE_API_URL || 'http://localhost:5000/api'
async function api<T>(path: string, opt?: RequestInit): Promise<T> { const response = await fetch(API + path, { headers: { 'Content-Type': 'application/json' }, ...opt }); const body = await response.json().catch(() => ({})); if (!response.ok) throw Error(body.detail || 'Request failed'); return body }
const Btn = ({ children, onClick, kind = 'primary', disabled = false, type = 'button' }: { children: any; onClick?: () => void; kind?: string; disabled?: boolean; type?: 'button' | 'submit' }) => <button type={type} className={'btn ' + kind} disabled={disabled} onClick={onClick}>{children}</button>
const Card = ({ children }: { children: any }) => <section className="card">{children}</section>
const ErrorBox = ({ m }: { m: string }) => <div className="error">{m}</div>
const Status = ({ s }: { s: string }) => <span className={'status ' + s}>{s}</span>

function Scan({ go }: { go: (s: string) => void }) {
  const video = useRef<HTMLVideoElement>(null); const reader = useRef<BrowserMultiFormatReader>(); const [devices, setDevices] = useState<MediaDeviceInfo[]>([]); const [deviceId, setDeviceId] = useState(''); const [sessionId, setSessionId] = useState('DEMO-1001'); const [scanning, setScanning] = useState(false); const [err, setErr] = useState('')
  useEffect(() => { navigator.mediaDevices?.enumerateDevices().then(all => { const cameras = all.filter(device => device.kind === 'videoinput'); setDevices(cameras); const preferred = cameras.find(device => /integrated|internal|built-in|front/i.test(device.label)); setDeviceId(preferred?.deviceId || cameras[0]?.deviceId || '') }).catch(() => setErr('Unable to list camera devices. Use the manual fallback.')); return () => stopCamera() }, [])
  function stopCamera() { reader.current = undefined; const stream = video.current?.srcObject as MediaStream | null; stream?.getTracks().forEach(track => track.stop()); if (video.current) video.current.srcObject = null; setScanning(false) }
async function startCamera() {
  setErr('')
  setScanning(true)

  try {
    // Wait for React to render the <video> element
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => resolve())
    })

    if (!video.current) {
      throw new Error('Video element is not ready')
    }

    reader.current = new BrowserMultiFormatReader()

    await reader.current.decodeFromVideoDevice(
      deviceId || undefined,
      video.current,
      (result) => {
        if (!result) return

        const value = result.getText().trim()

        if (!value) return

        setSessionId(value)
        stopCamera()
        go(value)
      }
    )
  } catch (error: any) {
    stopCamera()

    if (
      error?.name === 'NotAllowedError' ||
      error?.name === 'PermissionDeniedError'
    ) {
      setErr(
        'Camera permission denied. Please allow camera access in the browser.'
      )
    } else {
      setErr(
        'Unable to start the camera. Please check that no other application is using it.'
      )
    }
  }
}
  return <div className="narrow page"><p className="eyebrow">WORKSTREAM A · CHECKOUT FOUNDATION</p><h1>Identify cart session</h1><p className="muted">Scan the final Cart barcode or QR code, or enter a session ID manually.</p><Card>{devices.length > 0 && <label>Camera source<select value={deviceId} onChange={e => { setDeviceId(e.target.value); if (scanning) stopCamera() }} disabled={scanning}>{devices.map((device, index) => <option key={device.deviceId || index} value={device.deviceId}>{device.label || `Camera ${index + 1}`}</option>)}</select></label>}<div className="camera">{scanning ? <video ref={video} autoPlay muted playsInline /> : <div>▣<small>Camera scanner ready</small></div>}</div><Btn onClick={scanning ? stopCamera : startCamera} kind={scanning ? 'danger' : 'primary'}>{scanning ? 'Stop camera' : 'Use camera scanner'}</Btn>{err && <ErrorBox m={err} />}<hr /><form onSubmit={e => { e.preventDefault(); if (sessionId.trim()) go(sessionId.trim()) }}><label>Session ID<input value={sessionId} onChange={e => setSessionId(e.target.value)} /></label><Btn type="submit" disabled={!sessionId.trim()}>Load cart</Btn></form><p className="hint">Try DEMO-1001, DEMO-1002, or SHOP-20260928-0007.</p></Card></div>
}
function CartView({ c, go, back }: { c: Cart; go: () => void; back: () => void }) { const total = c.items.reduce((sum, item) => sum + item.quantity * item.unit_price, 0); const valid = c.items.every(item => item.quantity > 0 && Math.abs(item.line_total - item.quantity * item.unit_price) < .01) && Math.abs(total - c.total) < .01; return <div className="page"><header><div><p className="eyebrow">CART SUMMARY</p><h1>Review cart</h1></div><Btn kind="ghost" onClick={back}>← Change cart</Btn></header><Card><div className="grid"><div><small>Cart ID</small><b>{c.cart_id}</b></div><div><small>Session ID</small><b>{c.session_id}</b></div><div><small>Items</small><b>{c.items.length}</b></div><div><small>Backend total</small><b>€{c.total.toFixed(2)}</b></div></div><table><thead><tr><th>Product</th><th>Qty</th><th>Unit</th><th>Total</th></tr></thead><tbody>{c.items.map(item => <tr key={item.product_id}><td>{item.product_name}<small>{item.product_id}</small></td><td>{item.quantity}</td><td>€{item.unit_price.toFixed(2)}</td><td>€{item.line_total.toFixed(2)}</td></tr>)}</tbody></table><div className="total"><span>Recalculated total</span><b>€{total.toFixed(2)}</b></div>{!valid && <ErrorBox m="Cart validation failed. Payment is disabled." />}<Btn onClick={go} disabled={!valid}>Continue to payment selection →</Btn></Card></div> }
function Select({ amount, go, back }: { amount: number; go: (method: string) => void; back: () => void }) { return <div className="narrow page"><p className="eyebrow">PAYMENT SELECTION</p><h1>Choose payment method</h1><p className="muted">Amount due</p><div className="amount">€{amount.toFixed(2)}</div><div className="banner">DEMO CURRENCY · SIMULATION ONLY<br /><small>No real money is processed.</small></div><div className="options"><Card><h2>⌁ QR Payment</h2><p>Scan a QR with a phone or approve on this device.</p><Btn onClick={() => go('QR')}>Use simulated QR</Btn></Card><Card><h2>))) NFC Payment</h2><p>Use a simulated NFC tag and keypad confirmation.</p><Btn onClick={() => go('NFC')}>Use simulated NFC</Btn></Card></div><Btn kind="ghost" onClick={back}>← Back to cart</Btn></div> }
function Pay({ p, success, back }: { p: Payment; success: () => void; back: () => void }) {
  const [status, setStatus] = useState(p.status)
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const timer = window.setInterval(async () => {
      try {
        const result = await api<any>('/payments/' + p.payment_token)
        setStatus(result.status)
        if (result.status === 'successful') success()
      } catch { /* payment may have expired */ }
    }, 2000)
    return () => window.clearInterval(timer)
  }, [p.payment_token, success])
  async function finish(path = 'complete') {
    setBusy(true)
    try {
      const result = await api<any>('/payments/' + p.payment_token + '/' + path, { method: 'POST', body: '{}' })
      setStatus(result.status)
      if (result.status === 'successful') success()
    } finally { setBusy(false) }
  }
  return <div className="narrow page"><p className="eyebrow">{p.method} PAYMENT</p><h1>{p.method === 'QR' ? 'Scan to pay' : 'Tap simulated NFC tag'}</h1><div className="banner">SIMULATION ONLY · DEMO CURRENCY<br /><small>No real money is processed.</small></div><Card><p className="muted">Amount</p><div className="amount">€{p.amount.toFixed(2)}</div>{p.method === 'QR' ? <><img className="qr" src={p.qr_image_url} alt="QR code for simulated payment" /><p className="hint">Scan with a phone on the same network.</p><p className="hint">Phone URL: <code>{p.phone_url || p.mock_url}</code></p><Btn kind="secondary" onClick={() => finish()} disabled={busy || status !== 'waiting'}>Approve on this device</Btn></> : <><div className="nfc">)))</div><input className="pin" maxLength={4} inputMode="numeric" value={pin} onChange={e => setPin(e.target.value.replace(/\D/g, ''))} placeholder="••••" /><Btn onClick={() => finish()} disabled={busy || pin.length !== 4 || status !== 'waiting'}>Detect simulated NFC tag</Btn></>}{status === 'waiting' && <p className="waiting">◌ Waiting for simulated payment…</p>}{status !== 'waiting' && <p className={'result ' + status}><Status s={status} /> {status === 'successful' ? 'Payment successful' : 'Payment ' + status}</p>}<Btn kind="danger" onClick={() => finish('fail')} disabled={status !== 'waiting' || busy}>Simulate payment failure</Btn></Card><Btn kind="ghost" onClick={back}>← Choose another method</Btn></div>
}
function Receipt({ tx, history }: { tx: Tx; history: () => void }) { const [qr, setQr] = useState(''); useEffect(() => { QRCode.toDataURL(location.origin + '/receipt/' + tx.transaction_id).then(setQr) }, [tx.transaction_id]); function html() { return '<h1>Checkout Counter Receipt</h1><p>Transaction: ' + tx.transaction_id + '</p>' + tx.items.map(item => '<p>' + item.product_name + ' x ' + item.quantity + ' — €' + item.line_total.toFixed(2) + '</p>').join('') + '<h2>Total: €' + tx.amount.toFixed(2) + '</h2>' } function downloadHtml() { const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([html()], { type: 'text/html' })); link.download = 'receipt-' + tx.transaction_id + '.html'; link.click() } function downloadPdf() { const doc = new jsPDF(); doc.text('Checkout Counter Receipt', 20, 25); doc.text('Transaction: ' + tx.transaction_id, 20, 40); let y = 50; tx.items.forEach(item => { doc.text(item.product_name + ' x ' + item.quantity + ' - EUR ' + item.line_total.toFixed(2), 20, y); y += 9 }); doc.text('Total: EUR ' + tx.amount.toFixed(2), 20, y + 8); doc.save('receipt-' + tx.transaction_id + '.pdf') } return <div className="narrow page"><div className="success">✓</div><p className="eyebrow">PAYMENT SUCCESSFUL</p><h1>Receipt ready</h1><Card><div className="receipt-head"><b>{tx.transaction_id}</b><Status s={tx.payment_status} /></div>{tx.items.map(item => <div className="line" key={item.product_id}><span>{item.product_name} × {item.quantity}<small>€{item.unit_price.toFixed(2)} each</small></span><b>€{item.line_total.toFixed(2)}</b></div>)}<div className="total"><span>Total amount</span><b>€{tx.amount.toFixed(2)}</b></div><p>Cart: {tx.cart_id}<br />Session: {tx.session_id}<br />Payment: {tx.payment_method} simulation<br />Time: {new Date(tx.timestamp).toLocaleString()}</p><div className="lookup"><span>Receipt lookup QR</span>{qr && <img src={qr} />}</div><Btn onClick={downloadHtml}>Download HTML</Btn> <Btn kind="secondary" onClick={downloadPdf}>Download PDF</Btn></Card><Btn onClick={history}>View transaction history →</Btn></div> }
function History({ back }: { back: () => void }) { const [list, setList] = useState<Tx[]>([]); const [audit, setAudit] = useState<Record<string, any[]>>({}); useEffect(() => { api<Tx[]>('/transactions').then(setList) }, []); return <div className="page"><header><div><p className="eyebrow">AUDIT & REPORTING</p><h1>Transaction history</h1></div><Btn onClick={back}>New checkout</Btn></header><Card>{!list.length ? <p>No transactions yet. Complete a simulated checkout first.</p> : <table><thead><tr><th>Transaction</th><th>Status</th><th>Amount</th><th>Method</th><th>Timestamp</th><th>Audit</th></tr></thead><tbody>{list.map(tx => <tr key={tx.transaction_id}><td>{tx.transaction_id}<small>{tx.session_id}</small></td><td><Status s={tx.payment_status} /></td><td>€{tx.amount.toFixed(2)}</td><td>{tx.payment_method}</td><td>{new Date(tx.timestamp).toLocaleString()}</td><td><Btn kind="ghost" onClick={async () => setAudit({ ...audit, [tx.transaction_id]: await api<any[]>('/transactions/' + tx.transaction_id + '/audit') })}>View events</Btn>{audit[tx.transaction_id]?.map(event => <small className="audit" key={event.event_id}>{event.event_type}: {event.message}</small>)}</td></tr>)}</tbody></table>}</Card></div> }
function App() { const [step, setStep] = useState('scan'); const [cart, setCart] = useState<Cart>(); const [payment, setPayment] = useState<Payment>(); const [tx, setTx] = useState<Tx>(); const [error, setError] = useState(''); async function load(id: string) { try { setError(''); setCart(await api<Cart>('/carts/' + encodeURIComponent(id))); setStep('cart') } catch (e: any) { setError(e.message) } } async function chooseMethod(method: string) { try { setError(''); setPayment(await api<Payment>('/payments', { method: 'POST', body: JSON.stringify({ session_id: cart!.session_id, payment_method: method, amount: cart!.total }) })); setStep('pay') } catch (e: any) { setError(e.message) } } async function success() { const transactions = await api<Tx[]>('/transactions'); setTx(transactions[0]); setStep('receipt') } function newCheckout() { setStep('scan'); setCart(undefined); setPayment(undefined); setTx(undefined) } return <><nav><b>Checkout Counter <small>DEMO FOUNDATION</small></b><span><button onClick={newCheckout}>New checkout</button> <button onClick={() => setStep('history')}>History</button></span></nav>{error && <div className="global"><ErrorBox m={error} /><button onClick={() => setError('')}>Dismiss</button></div>}{step === 'scan' && <Scan go={load} />}{step === 'cart' && cart && <CartView c={cart} go={() => setStep('select')} back={() => setStep('scan')} />}{step === 'select' && cart && <Select amount={cart.total} go={chooseMethod} back={() => setStep('cart')} />}{step === 'pay' && payment && <Pay p={payment} success={success} back={() => setStep('select')} />}{step === 'receipt' && tx && <Receipt tx={tx} history={() => setStep('history')} />}{step === 'history' && <History back={newCheckout} />}<footer>Demo/simulation only · ZXing camera + JSON API + FastAPI</footer></> }
createRoot(document.getElementById('root')!).render(<App />)
