from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Literal
from uuid import uuid4
import json
import os
import socket
import threading
import time
from urllib.parse import urlsplit

import serial

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .service import PARKING_FEE, get_fixture_cart
from . import firestore_store
from . import shopping_sessions

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

# ESP32/RC522 serial integration. Override with NFC_SERIAL_PORT if needed.
NFC_SERIAL_PORT = os.getenv('NFC_SERIAL_PORT', 'COM16')
NFC_BAUD_RATE = int(os.getenv('NFC_BAUD_RATE', '115200'))
NFC_STATE = {
    'connected': False,
    'port': NFC_SERIAL_PORT,
    'baud_rate': NFC_BAUD_RATE,
    'last_event': None,
    'event_counter': 0,
    'last_card_uid': None,
    'last_card_at': None,
    'last_key': None,
    'key_sequence': '',
    'error': None,
}
NFC_LOCK = threading.Lock()
NFC_STOP = threading.Event()
NFC_THREAD = None
NFC_CONNECTION = None
NFC_IO_LOCK = threading.Lock()


def _send_lcd_event(event: dict) -> bool:
    global NFC_CONNECTION
    payload = (json.dumps(event, separators=(',', ':')) + '\n').encode('utf-8')
    with NFC_IO_LOCK:
        connection = NFC_CONNECTION
        if connection is None or not connection.is_open:
            return False
        try:
            connection.write(payload)
            connection.flush()
            return True
        except (serial.SerialException, OSError):
            NFC_CONNECTION = None
            return False


def _handle_nfc_event(event: dict) -> None:
    with NFC_LOCK:
        NFC_STATE['last_event'] = event
        NFC_STATE['event_counter'] += 1
        if event.get('event') == 'card_detected':
            NFC_STATE['last_card_uid'] = str(event.get('uid', ''))
            NFC_STATE['last_card_at'] = datetime.now(timezone.utc).isoformat()
        elif event.get('event') == 'key_pressed':
            key = str(event.get('key', ''))
            NFC_STATE['last_key'] = key
            if (key.isdigit() or (key == '.' and '.' not in NFC_STATE['key_sequence'])) and len(NFC_STATE['key_sequence']) < 16:
                NFC_STATE['key_sequence'] += key
            elif key == '*':
                NFC_STATE['key_sequence'] = ''


def _nfc_serial_worker() -> None:
    global NFC_CONNECTION
    while not NFC_STOP.is_set():
        try:
            with serial.Serial(NFC_SERIAL_PORT, NFC_BAUD_RATE, timeout=1) as connection:
                with NFC_IO_LOCK:
                    NFC_CONNECTION = connection
                with NFC_LOCK:
                    NFC_STATE['connected'] = True
                    NFC_STATE['error'] = None
                while not NFC_STOP.is_set():
                    raw = connection.readline()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw.decode('utf-8', errors='ignore').strip())
                        if isinstance(event, dict):
                            _handle_nfc_event(event)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
        except (serial.SerialException, OSError) as exc:
            with NFC_LOCK:
                NFC_STATE['connected'] = False
                NFC_STATE['error'] = str(exc)
            time.sleep(2)
    with NFC_LOCK:
        NFC_STATE['connected'] = False


@app.on_event('startup')
def start_nfc_serial_listener():
    global NFC_THREAD
    NFC_STOP.clear()
    NFC_THREAD = threading.Thread(target=_nfc_serial_worker, name='esp32-nfc-reader', daemon=True)
    NFC_THREAD.start()


@app.on_event('shutdown')
def stop_nfc_serial_listener():
    NFC_STOP.set()
    if NFC_THREAD and NFC_THREAD.is_alive():
        NFC_THREAD.join(timeout=2)


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid(prefix: str) -> str:
    return f'{prefix}-{uuid4().hex[:10].upper()}'


def cart_or_404(session_id: str):
    clean_id = session_id.strip()
    fixture = get_fixture_cart(clean_id)
    if fixture is not None:
        cart = fixture
    else:
        if clean_id.upper() not in CARTS:
            cart = shopping_sessions.lookup(clean_id)
        else:
            cart = CARTS[clean_id.upper()]

    subtotal = round(float(cart.get('subtotal', cart['total'])), 2)
    return {**cart, 'subtotal': subtotal, 'parking_fee': PARKING_FEE, 'total': round(subtotal + PARKING_FEE, 2)}


class PaymentRequest(BaseModel):
    session_id: str | None = Field(default=None, min_length=1)
    transaction_id: str | None = Field(default=None, min_length=1)
    payment_method: Literal['QR', 'NFC'] | None = None
    method: Literal['QR', 'NFC'] | None = None
    amount: float = Field(gt=0)
    currency: Literal['DEMO'] = 'DEMO'
    payment_token: str | None = None


class ConfirmationRequest(BaseModel):
    confirmation: Literal['DEMO-APPROVE', 'DEMO-DECLINE']


class NfcCompletionRequest(BaseModel):
    entered_amount: str = Field(min_length=1, max_length=16)
    card_uid: str = Field(min_length=1, max_length=64)


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
        'provider_status': {
            'waiting': 'PENDING',
            'successful': 'SUCCESS',
            'failed': 'FAILED',
            'expired': 'EXPIRED',
        }.get(status, status.upper()),
        'transaction_status': payment.get('transaction_status', 'PENDING_PAYMENT'),
        'simulation_reference': payment.get('simulation_reference'),
        'message': payment.get('failure_reason') or {
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


def _local_network_ip() -> str | None:
    """Return the host's LAN address, when it can be determined safely."""
    try:
        # This does not send traffic. It lets the OS choose the active LAN
        # interface, which is usually the address a phone on the same Wi-Fi
        # network can reach.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            address = sock.getsockname()[0]
            return address if address and not address.startswith('127.') else None
    except OSError:
        return None


def phone_base_url(http_request: Request) -> str:
    """Build the base URL embedded in the phone QR code."""
    configured = os.getenv('PUBLIC_BASE_URL') or os.getenv('PHONE_BASE_URL')
    if configured:
        return configured.rstrip('/')

    base = str(http_request.base_url).rstrip('/')
    parsed = urlsplit(base)
    hostname = parsed.hostname or ''
    if hostname not in {'localhost', '127.0.0.1', '0.0.0.0', '::1'}:
        return base

    lan_ip = _local_network_ip()
    if not lan_ip:
        return base

    port = f':{parsed.port}' if parsed.port else ''
    return f'{parsed.scheme}://{lan_ip}{port}'


@app.get('/')
def root():
    return {'name': 'Checkout Counter Demo API', 'docs': '/docs', 'demo_sessions': ['DEMO-1001', 'DEMO-1002', 'SHOP-20260928-0007']}


@app.get('/api/health')
def health():
    return {'status': 'ok', 'demo_mode': True,
            'archive': 'firestore' if firestore_store.enabled() else 'memory'}


@app.get('/api/nfc/status')
def nfc_status():
    with NFC_LOCK:
        return dict(NFC_STATE)


@app.post('/api/nfc/reset')
def nfc_reset():
    with NFC_LOCK:
        NFC_STATE['last_card_uid'] = None
        NFC_STATE['last_card_at'] = None
        NFC_STATE['last_key'] = None
        NFC_STATE['key_sequence'] = ''
    return {'reset': True}


class LcdDisplayRequest(BaseModel):
    mode: Literal['waiting', 'price', 'payment', 'qr', 'nfc', 'success', 'failed']
    price: str | None = None
    method: Literal['QR', 'NFC'] | None = None


@app.post('/api/lcd/display')
def lcd_display(payload: LcdDisplayRequest):
    if payload.mode == 'price':
        if not payload.price or len(payload.price) > 12:
            raise HTTPException(422, 'A price is required for LCD price mode.')
        event = {'event': 'lcd_price', 'price': payload.price}
    elif payload.mode == 'payment':
        event = {'event': 'lcd_payment_mode'}
    elif payload.mode == 'qr':
        if not payload.price or len(payload.price) > 12:
            raise HTTPException(422, 'A price is required for LCD QR mode.')
        event = {'event': 'lcd_qr_payment', 'price': payload.price}
    elif payload.mode == 'nfc':
        if not payload.price or len(payload.price) > 12:
            raise HTTPException(422, 'A price is required for LCD NFC mode.')
        event = {'event': 'lcd_nfc_payment', 'price': payload.price}
    elif payload.mode == 'success':
        event = {'event': 'lcd_success'}
    elif payload.mode == 'failed':
        if not payload.price or len(payload.price) > 12 or payload.method is None:
            raise HTTPException(422, 'Price and payment method are required for LCD failure mode.')
        event = {'event': 'lcd_failed', 'method': payload.method, 'price': payload.price}
    else:
        event = {'event': 'lcd_waiting'}
    return {'sent': _send_lcd_event(event), 'event': event}


@app.get('/api/carts/{session_id}')
def get_cart(session_id: str):
    return cart_or_404(session_id)


@app.get('/api/tickets/{ticket}/sessions')
def ticket_sessions(ticket: str):
    carts = shopping_sessions.find_ticket(ticket)
    return [{**cart, 'parking_fee': PARKING_FEE,
             'total': round(cart['subtotal'] + PARKING_FEE, 2)} for cart in carts]


@app.post('/api/payments')
def create_payment(request: PaymentRequest, http_request: Request):
    session_id = request.session_id or request.transaction_id
    payment_method = request.payment_method or request.method
    if not session_id:
        raise HTTPException(422, 'session_id or transaction_id is required.')
    if not payment_method:
        raise HTTPException(422, 'payment_method or method is required.')

    cart = cart_or_404(session_id)
    if abs(cart['total'] - request.amount) > .01:
        raise HTTPException(422, 'Payment amount does not match cart total.')

    token = request.payment_token or uid('PAY')
    existing = PAYMENTS.get(token)
    if existing:
        if existing['session_id'] != cart['session_id'] or abs(existing['amount'] - request.amount) > .01:
            raise HTTPException(409, 'Payment token already belongs to another checkout.')
        return {**payment_result(existing), 'phone_url': existing.get('phone_url'), 'qr_image_url': existing.get('qr_image_url'), 'mock_url': existing.get('mock_url'), 'simulation_only': True, 'reused': True}

    payment = {
        'payment_token': token,
        'payment_id': uid('PAYMENT-SIM'),
        'transaction_id': request.transaction_id or uid('TXN'),
        'session_id': cart['session_id'],
        'cart_snapshot': cart,
        'amount': request.amount,
        'method': payment_method,
        'status': 'waiting',
        'transaction_status': 'PENDING_PAYMENT',
        'created_at': now(),
        'expires_at': now() + timedelta(minutes=5),
        'simulation_reference': f'SIM-{payment_method}-{token.removeprefix("PAY-").removeprefix("SIM-")}',
    }
    if payment_method == 'QR':
        public_base = phone_base_url(http_request)
        phone_url = public_base + f'/phone/{token}'
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
    payment = dict(payment)
    payment['status'] = state
    payment['transaction_status'] = 'PAYMENT_SUCCESS' if state == 'successful' else 'PAYMENT_FAILED'
    if state == 'successful':
        payment['confirmed_at'] = now()
        cart = payment.get('cart_snapshot') or cart_or_404(payment['session_id'])
        transaction = {
            'transaction_id': payment['transaction_id'], 'cart_id': cart['cart_id'],
            'session_id': cart['session_id'], 'subtotal': cart['subtotal'],
            'ticket_no': cart.get('ticket_no'),
            'parking_fee': cart['parking_fee'], 'amount': payment['amount'],
            'payment_method': payment['method'], 'timestamp': now(),
            'payment_status': 'successful', 'items': cart['items'],
            'payment_id': payment['payment_id'], 'simulation_reference': payment['simulation_reference'],
        }
        events = [
            {'event_id': uid('AUD'), 'transaction_id': transaction['transaction_id'], 'event_type': 'PAYMENT_SUCCESS', 'message': f"Simulated {payment['method']} payment completed", 'timestamp': now()},
            {'event_id': uid('AUD'), 'transaction_id': transaction['transaction_id'], 'event_type': 'RECEIPT_CREATED', 'message': 'Receipt generated for checkout', 'timestamp': now()},
        ]
        firestore_store.archive(transaction, events)
        TRANSACTIONS.append(transaction)
        AUDITS.extend(events)
    PAYMENTS[token] = payment
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
def complete(token: str, payload: NfcCompletionRequest):
    payment = PAYMENTS.get(token)
    if not payment:
        raise HTTPException(404, 'Payment token not found.')
    if payment['method'] != 'NFC':
        raise HTTPException(400, 'Amount validation is only available for NFC payments.')
    if payment['status'] != 'waiting':
        return payment_result(payment)

    try:
        entered_amount = Decimal(payload.entered_amount.strip().replace(',', '.'))
    except InvalidOperation:
        entered_amount = Decimal('-1')

    expected_amount = Decimal(str(payment['amount']))
    if entered_amount.quantize(Decimal('0.01')) != expected_amount.quantize(Decimal('0.01')):
        payment['failure_reason'] = (
            'Price must be exact and same with the actual price.'
        )
        payment['card_uid'] = payload.card_uid
        return payment_result(payment)

    payment.pop('failure_reason', None)
    payment['entered_amount'] = str(entered_amount.quantize(Decimal('0.01')))
    payment['card_uid'] = payload.card_uid
    return finish(token, 'successful')


@app.post('/api/payments/{token}/fail')
def fail(token: str):
    return finish(token, 'failed')


@app.get('/api/transactions')
def transactions():
    if firestore_store.enabled():
        return firestore_store.transactions()
    return list(reversed(TRANSACTIONS))


@app.get('/api/transactions/{tid}/audit')
def audit(tid: str):
    if firestore_store.enabled():
        return firestore_store.audits(tid)
    return [event for event in AUDITS if event['transaction_id'] == tid]


@app.get('/phone/{token}', response_class=HTMLResponse)
def phone_page(token: str):
    payment = PAYMENTS.get(token)
    if not payment or payment['method'] != 'QR':
        raise HTTPException(404, 'Payment token not found')
    return HTMLResponse(f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Demo QR Payment</title>
<style>body{{font-family:Arial,sans-serif;max-width:460px;margin:30px auto;padding:20px;background:#f5f7fa;color:#153b5b}}.card{{background:#fff;padding:26px;border-radius:18px;box-shadow:0 8px 24px #193b5b1a}}button{{width:100%;padding:15px;margin-top:12px;border:0;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer}}.ok{{background:#153b5b;color:#fff}}.bad{{background:#fff0ee;color:#ae3028}}.demo{{background:#fff3dd;border:1px solid #f3d394;border-radius:10px;padding:12px;font-size:13px}}#out{{white-space:pre-wrap;text-align:center;font-weight:bold}}</style>
<div class="card"><h1>Demo QR Payment</h1><div class="demo"><b>SIMULATION ONLY</b><br>No real money is processed.</div><p>Transaction: <b>{payment['transaction_id']}</b></p><p>Amount: <b>₱{payment['amount']:.2f} DEMO</b></p><p>Includes fixed parking fee: ₱{PARKING_FEE:.2f}</p><button class="ok" onclick="confirmPayment('DEMO-APPROVE')">Approve simulated payment</button><button class="bad" onclick="confirmPayment('DEMO-DECLINE')">Decline simulated payment</button><p id="out"></p></div>
<script>async function confirmPayment(value){{document.querySelectorAll('button').forEach(b=>b.disabled=true);const r=await fetch('/api/payments/{token}/confirm',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{confirmation:value}})}});const d=await r.json();if(r.ok&&d.status==='successful'){{document.getElementById('out').textContent='PAYMENT APPROVED — opening receipt…';setTimeout(()=>window.location.href='/receipt/{token}',650);}}else{{document.getElementById('out').textContent=r.status===409?'DUPLICATE: this payment was already confirmed':(r.ok?'PAYMENT DECLINED':((d.detail&&d.detail.detail)||'Payment already confirmed'));}}}}</script>''')


@app.get('/receipt/{token}', response_class=HTMLResponse)
def receipt_page(token: str):
    payment = PAYMENTS.get(token)
    if payment is None:
        payment = next((candidate for candidate in PAYMENTS.values() if candidate['transaction_id'] == token), None)
    if not payment or payment['status'] != 'successful':
        raise HTTPException(409, 'Receipt is available only after a successful demo payment')
    confirmed = next((tx for tx in TRANSACTIONS if tx['transaction_id'] == payment['transaction_id']), None)
    timestamp = confirmed['timestamp'].isoformat() if confirmed else now().isoformat()
    return HTMLResponse(f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Payment Sent | Checkout Counter</title>
<style>body{{font-family:Arial,sans-serif;max-width:560px;margin:42px auto;padding:18px;background:#eef8f2}}.card{{background:#fff;border-radius:22px;padding:30px;box-shadow:0 10px 30px #165c3518;text-align:center}}.check{{font-size:44px;color:#13795b}}.sent{{color:#13795b;font-size:30px;font-weight:bold}}.row{{display:flex;justify-content:space-between;gap:20px;padding:14px 0;border-bottom:1px solid #e3ebe6;text-align:left}}.label{{color:#687786}}.value{{font-weight:bold;text-align:right;overflow-wrap:anywhere}}.warning{{margin-top:22px;background:#fff7df;border:1px solid #f3d394;border-radius:10px;padding:12px;text-align:left;font-size:13px}}</style>
<div class="card"><div class="check">✓</div><h1 class="sent">PAYMENT SENT</h1><p>Demo payment approved successfully</p><h2>₱{payment['amount']:.2f} DEMO</h2><div class="row"><span class="label">Date and time</span><b class="value">{timestamp}</b></div><div class="row"><span class="label">Parking fee</span><b class="value">₱{PARKING_FEE:.2f}</b></div><div class="row"><span class="label">Payment method</span><b class="value">QR</b></div><div class="row"><span class="label">Transaction ID</span><b class="value">{payment['transaction_id']}</b></div><div class="row"><span class="label">Payment ID</span><b class="value">{payment['payment_id']}</b></div><div class="row"><span class="label">Reference number</span><b class="value">{payment['simulation_reference']}</b></div><div class="warning"><b>SIMULATION ONLY</b><br>No real money was sent.</div></div>''')


@app.post('/api/reset')
def reset_demo():
    PAYMENTS.clear()
    TRANSACTIONS.clear()
    AUDITS.clear()
    return {'reset': True}
