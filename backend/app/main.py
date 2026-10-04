from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Literal
from uuid import uuid4

import qrcode
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .service import get_fixture_cart

app = FastAPI(title='Checkout Counter Demo API')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

CARTS = {
    'DEMO-1001': {
        'cart_id': 'CART-1001', 'session_id': 'DEMO-1001',
        'items': [
            {'product_id': 'P-001', 'product_name': 'Arabica Coffee Beans', 'quantity': 1, 'unit_price': 12.50, 'line_total': 12.50},
            {'product_id': 'P-002', 'product_name': 'Ceramic Travel Mug', 'quantity': 2, 'unit_price': 8.75, 'line_total': 17.50},
            {'product_id': 'P-003', 'product_name': 'Reusable Tote Bag', 'quantity': 1, 'unit_price': 4.00, 'line_total': 4.00},
        ], 'total': 34.0,
    },
    'DEMO-1002': {
        'cart_id': 'CART-1002', 'session_id': 'DEMO-1002',
        'items': [{'product_id': 'P-010', 'product_name': 'Wireless Keyboard', 'quantity': 1, 'unit_price': 45.0, 'line_total': 45.0}],
        'total': 45.0,
    },
}
PAYMENTS, TRANSACTIONS, AUDITS = {}, [], []


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid(prefix: str) -> str:
    return f'{prefix}-{uuid4().hex[:10].upper()}'


def cart_or_404(session_id: str):
    clean_id = session_id.strip()
    fixture = get_fixture_cart(clean_id)
    if fixture is not None:
        return fixture
    if clean_id.upper() not in CARTS:
        raise HTTPException(404, 'Cart session not found. Try DEMO-1001 or SHOP-20260928-0007.')
    return CARTS[clean_id.upper()]


class PaymentRequest(BaseModel):
    session_id: str = Field(min_length=1)
    payment_method: Literal['QR', 'NFC']
    amount: float = Field(gt=0)


class ConfirmationRequest(BaseModel):
    confirmation: Literal['DEMO-APPROVE', 'DEMO-DECLINE']


def payment_result(payment: dict) -> dict:
    status = payment['status']
    result = {
        'payment_token': payment['payment_token'],
        'payment_id': payment.get('payment_id'),
        'transaction_id': payment.get('transaction_id'),
        'session_id': payment.get('session_id'),
        'status': status,
        'amount': payment['amount'],
        'method': payment['method'],
        'currency': 'DEMO',
        'transaction_status': payment.get('transaction_status', 'PENDING_PAYMENT'),
        'simulation_reference': payment.get('simulation_reference'),
        'message': {
            'waiting': 'Waiting for simulated payment',
            'successful': 'Payment successful',
            'failed': 'Payment failed',
            'expired': 'Payment expired',
        }.get(status, status),
    }
    return result


def qr_bytes(url: str) -> bytes:
    code = qrcode.QRCode(version=None, box_size=10, border=4)
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(fill_color='black', back_color='white')
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


@app.get('/')
def root():
    return {'name': 'Checkout Counter Demo API', 'docs': '/docs', 'demo_sessions': ['DEMO-1001', 'DEMO-1002', 'SHOP-20260928-0007']}


@app.get('/api/health')
def health():
    return {'status': 'ok', 'demo_mode': True}


@app.get('/api/carts/{session_id}')
def get_cart(session_id: str):
    return cart_or_404(session_id)


@app.post('/api/payments')
def create_payment(request: PaymentRequest, http_request: Request):
    cart = cart_or_404(request.session_id)
    if abs(cart['total'] - request.amount) > .01:
        raise HTTPException(422, 'Payment amount does not match cart total.')

    token = uid('PAY')
    payment = {
        'payment_token': token,
        'payment_id': uid('PAYMENT-SIM'),
        'transaction_id': uid('TXN'),
        'session_id': cart['session_id'],
        'amount': request.amount,
        'method': request.payment_method,
        'status': 'waiting',
        'transaction_status': 'PENDING_PAYMENT',
        'created_at': now(),
        'expires_at': now() + timedelta(minutes=5),
        'simulation_reference': f'SIM-QR-{token.removeprefix("PAY-")}',
    }
    if request.payment_method == 'QR':
        phone_url = str(http_request.base_url).rstrip('/') + f'/phone/{token}'
        payment['phone_url'] = phone_url
        payment['qr_image_url'] = str(http_request.base_url).rstrip('/') + f'/api/payments/{token}/qr'
        payment['mock_url'] = phone_url
    else:
        payment['mock_url'] = str(http_request.base_url).rstrip('/') + f'/mock-payment/{token}'
    PAYMENTS[token] = payment
    return {
        **payment_result(payment),
        'phone_url': payment.get('phone_url'),
        'qr_image_url': payment.get('qr_image_url'),
        'mock_url': payment.get('mock_url'),
        'simulation_only': True,
    }


@app.get('/api/payments/{token}/qr')
def payment_qr(token: str):
    payment = PAYMENTS.get(token)
    if not payment:
        raise HTTPException(404, 'Payment token not found.')
    if payment['method'] != 'QR':
        raise HTTPException(400, 'QR image is only available for QR payments.')
    return Response(content=qr_bytes(payment['phone_url']), media_type='image/png')


@app.get('/api/payments/{token}')
def payment_status(token: str):
    payment = PAYMENTS.get(token)
    if not payment:
        raise HTTPException(404, 'Payment token not found.')
    if payment['status'] == 'waiting' and now() > payment['expires_at']:
        payment['status'] = 'expired'
    return payment_result(payment)


def finish(token: str, state: str):
    payment = PAYMENTS.get(token)
    if not payment:
        raise HTTPException(404, 'Payment token not found.')
    if payment['status'] != 'waiting':
        return payment_result(payment)
    payment['status'] = state
    payment['transaction_status'] = 'PAYMENT_SUCCESS' if state == 'successful' else 'PAYMENT_FAILED'
    if state == 'successful':
        cart = cart_or_404(payment['session_id'])
        transaction = {
            'transaction_id': payment['transaction_id'], 'cart_id': cart['cart_id'],
            'session_id': cart['session_id'], 'amount': payment['amount'],
            'payment_method': payment['method'], 'timestamp': now(),
            'payment_status': 'successful', 'items': cart['items'],
            'payment_id': payment['payment_id'], 'simulation_reference': payment['simulation_reference'],
        }
        TRANSACTIONS.append(transaction)
        AUDITS.extend([
            {'event_id': uid('AUD'), 'transaction_id': transaction['transaction_id'], 'event_type': 'PAYMENT_SUCCESS', 'message': f"Simulated {payment['method']} payment completed", 'timestamp': now()},
            {'event_id': uid('AUD'), 'transaction_id': transaction['transaction_id'], 'event_type': 'RECEIPT_CREATED', 'message': 'Receipt generated for checkout', 'timestamp': now()},
        ])
    return payment_result(payment)


@app.post('/api/payments/{token}/confirm')
def confirm_payment(token: str, payload: ConfirmationRequest):
    payment = PAYMENTS.get(token)
    if not payment:
        raise HTTPException(404, 'Payment token not found.')
    if payment['method'] != 'QR':
        raise HTTPException(400, 'Confirmation is only available for QR payments.')
    if payment['status'] != 'waiting':
        raise HTTPException(status_code=409, detail={'status': 'DUPLICATE', 'detail': 'Payment token already confirmed'})
    return finish(token, 'successful' if payload.confirmation == 'DEMO-APPROVE' else 'failed')


@app.post('/api/payments/{token}/complete')
def complete(token: str):
    return finish(token, 'successful')


@app.post('/api/payments/{token}/fail')
def fail(token: str):
    return finish(token, 'failed')


@app.get('/api/transactions')
def transactions():
    return list(reversed(TRANSACTIONS))


@app.get('/api/transactions/{tid}/audit')
def audit(tid: str):
    return [event for event in AUDITS if event['transaction_id'] == tid]


@app.get('/phone/{token}', response_class=HTMLResponse)
def phone_page(token: str):
    payment = PAYMENTS.get(token)
    if not payment or payment['method'] != 'QR':
        raise HTTPException(404, 'Payment token not found')
    return HTMLResponse(f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Demo QR Payment</title>
<style>body{{font-family:Arial,sans-serif;max-width:460px;margin:30px auto;padding:20px;background:#f5f7fa;color:#153b5b}}.card{{background:#fff;padding:26px;border-radius:18px;box-shadow:0 8px 24px #193b5b1a}}button{{width:100%;padding:15px;margin-top:12px;border:0;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer}}.ok{{background:#153b5b;color:#fff}}.bad{{background:#fff0ee;color:#ae3028}}.demo{{background:#fff3dd;border:1px solid #f3d394;border-radius:10px;padding:12px;font-size:13px}}#out{{white-space:pre-wrap;text-align:center;font-weight:bold}}</style>
<div class="card"><h1>Demo QR Payment</h1><div class="demo"><b>SIMULATION ONLY</b><br>No real money is processed.</div><p>Transaction: <b>{payment['transaction_id']}</b></p><p>Amount: <b>€{payment['amount']:.2f} DEMO</b></p><button class="ok" onclick="confirmPayment('DEMO-APPROVE')">Approve simulated payment</button><button class="bad" onclick="confirmPayment('DEMO-DECLINE')">Decline simulated payment</button><p id="out"></p></div>
<script>async function confirmPayment(value){{document.querySelectorAll('button').forEach(b=>b.disabled=true);const r=await fetch('/api/payments/{token}/confirm',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{confirmation:value}})}});const d=await r.json();document.getElementById('out').textContent=r.ok?'PAYMENT '+(d.status==='successful'?'APPROVED':'DECLINED'):((d.detail&&d.detail.detail)||'Payment already confirmed');}}</script>''')


@app.get('/receipt/{token}', response_class=HTMLResponse)
def receipt_page(token: str):
    payment = PAYMENTS.get(token)
    if not payment or payment['status'] != 'successful':
        raise HTTPException(409, 'Receipt is available only after a successful demo payment')
    confirmed = next((tx for tx in TRANSACTIONS if tx['transaction_id'] == payment['transaction_id']), None)
    timestamp = confirmed['timestamp'].isoformat() if confirmed else now().isoformat()
    return HTMLResponse(f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Payment Sent | Checkout Counter</title>
<style>body{{font-family:Arial,sans-serif;max-width:560px;margin:42px auto;padding:18px;background:#eef8f2}}.card{{background:#fff;border-radius:22px;padding:30px;box-shadow:0 10px 30px #165c3518;text-align:center}}.check{{font-size:44px;color:#13795b}}.sent{{color:#13795b;font-size:30px;font-weight:bold}}.row{{display:flex;justify-content:space-between;gap:20px;padding:14px 0;border-bottom:1px solid #e3ebe6;text-align:left}}.label{{color:#687786}}.value{{font-weight:bold;text-align:right;overflow-wrap:anywhere}}.warning{{margin-top:22px;background:#fff7df;border:1px solid #f3d394;border-radius:10px;padding:12px;text-align:left;font-size:13px}}</style>
<div class="card"><div class="check">✓</div><h1 class="sent">PAYMENT SENT</h1><p>Demo payment approved successfully</p><h2>€{payment['amount']:.2f} DEMO</h2><div class="row"><span class="label">Date and time</span><b class="value">{timestamp}</b></div><div class="row"><span class="label">Payment method</span><b class="value">QR</b></div><div class="row"><span class="label">Transaction ID</span><b class="value">{payment['transaction_id']}</b></div><div class="row"><span class="label">Payment ID</span><b class="value">{payment['payment_id']}</b></div><div class="row"><span class="label">Reference number</span><b class="value">{payment['simulation_reference']}</b></div><div class="warning"><b>SIMULATION ONLY</b><br>No real money was sent.</div></div>''')


@app.post('/api/reset')
def reset_demo():
    PAYMENTS.clear()
    TRANSACTIONS.clear()
    AUDITS.clear()
    return {'reset': True}
