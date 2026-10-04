from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from typing import Any, Literal
from uuid import uuid4

import qrcode
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .service import get_fixture_cart

app = FastAPI(title="Checkout Counter Demo API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CARTS = {
    "DEMO-1001": {"cart_id": "CART-1001", "session_id": "DEMO-1001", "items": [{"product_id": "P-001", "product_name": "Arabica Coffee Beans", "quantity": 1, "unit_price": 12.50, "line_total": 12.50}, {"product_id": "P-002", "product_name": "Ceramic Travel Mug", "quantity": 2, "unit_price": 8.75, "line_total": 17.50}, {"product_id": "P-003", "product_name": "Reusable Tote Bag", "quantity": 1, "unit_price": 4.00, "line_total": 4.00}], "total": 34.0},
    "DEMO-1002": {"cart_id": "CART-1002", "session_id": "DEMO-1002", "items": [{"product_id": "P-010", "product_name": "Wireless Keyboard", "quantity": 1, "unit_price": 45.0, "line_total": 45.0}], "total": 45.0},
}
PAYMENTS: dict[str, dict[str, Any]] = {}
TRANSACTIONS: list[dict[str, Any]] = []
AUDITS: list[dict[str, Any]] = []


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10].upper()}"


class PaymentRequest(BaseModel):
    session_id: str = Field(min_length=1)
    payment_method: Literal["QR", "NFC"]
    amount: float = Field(gt=0, allow_inf_nan=False)


class QRConfirmationRequest(BaseModel):
    confirmation: Literal["DEMO-APPROVE", "DEMO-DECLINE"]


def cart_or_404(session_id: str) -> dict[str, Any]:
    clean_id = session_id.strip()
    fixture = get_fixture_cart(clean_id)
    if fixture is not None:
        return fixture
    if clean_id.upper() not in CARTS:
        raise HTTPException(404, "Cart session not found. Try DEMO-1001 or SHOP-20260928-0007.")
    return CARTS[clean_id.upper()]


def qr_bytes(url: str) -> bytes:
    code = qrcode.QRCode(version=None, box_size=10, border=4)
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def create_transaction(payment: dict[str, Any], cart: dict[str, Any]) -> None:
    transaction = {"transaction_id": payment["transaction_id"], "payment_token": payment["payment_token"], "cart_id": cart["cart_id"], "session_id": cart["session_id"], "amount": payment["amount"], "payment_method": payment["method"], "timestamp": now(), "payment_status": "successful", "items": cart["items"]}
    TRANSACTIONS.append(transaction)
    AUDITS.extend([
        {"event_id": uid("AUD"), "transaction_id": transaction["transaction_id"], "event_type": "PAYMENT_SUCCESS", "message": f"Simulated {payment['method']} payment completed", "timestamp": now()},
        {"event_id": uid("AUD"), "transaction_id": transaction["transaction_id"], "event_type": "RECEIPT_CREATED", "message": "Receipt generated for checkout", "timestamp": now()},
    ])


def status_response(payment: dict[str, Any]) -> dict[str, Any]:
    if payment["status"] == "waiting" and now() > payment["expires_at"]:
        payment["status"] = "expired"
    result = {"payment_token": payment["payment_token"], "payment_id": payment["payment_id"], "transaction_id": payment["transaction_id"], "status": payment["status"], "amount": payment["amount"], "method": payment["method"], "currency": "DEMO", "message": {"waiting": "Waiting for simulated payment", "successful": "Payment successful", "failed": "Payment failed", "expired": "Payment expired"}[payment["status"]]}
    if payment["method"] == "QR":
        result.update({"transaction_status": {"waiting": "PENDING_PAYMENT", "successful": "PAYMENT_SUCCESS", "failed": "PAYMENT_FAILED", "expired": "PAYMENT_EXPIRED"}[payment["status"]], "phone_url": payment["phone_url"], "qr_image_url": payment["qr_image_url"], "simulation_reference": payment["simulation_reference"]})
    return result


@app.get("/")
def root() -> dict[str, Any]:
    return {"name": "Checkout Counter Demo API", "docs": "/docs", "demo_sessions": ["DEMO-1001", "DEMO-1002", "SHOP-20260928-0007"]}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "demo_mode": True}


@app.get("/api/carts/{session_id}")
def get_cart(session_id: str) -> dict[str, Any]:
    return cart_or_404(session_id)


@app.post("/api/payments")
def create_payment(request: PaymentRequest, http_request: Request) -> dict[str, Any]:
    cart = cart_or_404(request.session_id)
    if abs(cart["total"] - request.amount) > 0.01:
        raise HTTPException(422, "Payment amount does not match cart total.")
    token = uid("PAY")
    payment = {"payment_token": token, "payment_id": uid("PAYMENT-SIM"), "transaction_id": uid("TXN"), "session_id": cart["session_id"], "amount": request.amount, "method": request.payment_method, "status": "waiting", "created_at": now(), "expires_at": now() + timedelta(minutes=5)}
    if request.payment_method == "QR":
        base_url = str(http_request.base_url).rstrip("/")
        payment["phone_url"] = f"{base_url}/phone/{token}"
        payment["qr_image_url"] = f"/api/payments/{token}/qr"
        payment["simulation_reference"] = f"SIM-QR-{token.removeprefix('PAY-')}"
        payment["mock_url"] = payment["phone_url"]
    else:
        payment["mock_url"] = f"http://localhost:5000/mock-payment/{token}"
    PAYMENTS[token] = payment
    return payment


@app.get("/api/payments/{token}")
def payment_status(token: str) -> dict[str, Any]:
    if token not in PAYMENTS:
        raise HTTPException(404, "Payment token not found.")
    return status_response(PAYMENTS[token])


@app.get("/api/payments/{token}/qr")
def payment_qr(token: str) -> Response:
    payment = PAYMENTS.get(token)
    if not payment:
        raise HTTPException(404, "Payment token not found.")
    if payment["method"] != "QR":
        raise HTTPException(409, "QR code is available only for QR payments.")
    return Response(content=qr_bytes(payment["phone_url"]), media_type="image/png")


def finish(token: str, state: str) -> dict[str, Any]:
    if token not in PAYMENTS:
        raise HTTPException(404, "Payment token not found.")
    payment = PAYMENTS[token]
    if payment["status"] == "waiting":
        payment["status"] = state
        if state == "successful":
            create_transaction(payment, cart_or_404(payment["session_id"]))
    return status_response(payment)


@app.post("/api/payments/{token}/complete")
def complete(token: str) -> dict[str, Any]:
    return finish(token, "successful")


@app.post("/api/payments/{token}/fail")
def fail(token: str) -> dict[str, Any]:
    return finish(token, "failed")


@app.post("/api/payments/{token}/confirm")
def confirm_qr(token: str, request: QRConfirmationRequest) -> dict[str, Any]:
    if token not in PAYMENTS:
        raise HTTPException(404, "Payment token not found.")
    payment = PAYMENTS[token]
    if payment["method"] != "QR":
        raise HTTPException(409, "Confirmation is available only for QR payments.")
    if payment["status"] != "waiting":
        raise HTTPException(409, detail={"status": "DUPLICATE", "detail": "Payment token already confirmed"})
    return finish(token, "successful" if request.confirmation == "DEMO-APPROVE" else "failed")


@app.get("/api/transactions")
def transactions() -> list[dict[str, Any]]:
    return list(reversed(TRANSACTIONS))


@app.get("/api/transactions/{tid}/audit")
def audit(tid: str) -> list[dict[str, Any]]:
    return [event for event in AUDITS if event["transaction_id"] == tid]


@app.post("/api/reset")
def reset_demo() -> dict[str, bool]:
    PAYMENTS.clear()
    TRANSACTIONS.clear()
    AUDITS.clear()
    return {"reset": True}


@app.get("/phone/{token}", response_class=HTMLResponse)
def phone_page(token: str) -> HTMLResponse:
    payment = PAYMENTS.get(token)
    if not payment or payment["method"] != "QR":
        raise HTTPException(404, "QR payment not found")
    return HTMLResponse(f"""<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><title>Demo QR Payment</title><style>body{{font-family:Arial;max-width:460px;margin:30px auto;padding:20px;background:#f4f7fb}}.card{{background:#fff;padding:26px;border-radius:16px;box-shadow:0 8px 24px #ccd}}.warning{{background:#fff7df;border:1px solid #f3cf66;padding:12px;border-radius:10px}}.row{{display:flex;justify-content:space-between;border-bottom:1px solid #e6ebf1;padding:12px 0}}button{{width:100%;padding:15px;margin-top:12px;border:0;border-radius:10px;font-size:16px;font-weight:700}}.ok{{background:#13795b;color:#fff}}.bad{{background:#fff;color:#b42318;border:1px solid #e2a5a5}}#result{{margin-top:18px;font-weight:700;text-align:center}}</style><div class='card'><h1>Demo QR Payment</h1><div class='warning'><b>SIMULATION ONLY</b><br>No real money is processed.</div><p class='row'><span>Transaction ID</span><b>{escape(payment['transaction_id'])}</b></p><p class='row'><span>Amount</span><b>{payment['amount']:.2f} DEMO</b></p><p class='row'><span>Payment method</span><b>QR</b></p><button class='ok' onclick=confirmPayment('DEMO-APPROVE')>Pay Demo</button><button class='bad' onclick=confirmPayment('DEMO-DECLINE')>Decline Demo</button><p id='result'></p></div><script>async function confirmPayment(value){{const r=await fetch('/api/payments/{token}/confirm',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{confirmation:value}})}});const d=await r.json();document.getElementById('result').textContent=r.status===409?'DUPLICATE: this payment was already confirmed':d.status==='successful'?'PAYMENT APPROVED — opening receipt…':'PAYMENT FAILED — demo payment declined';if(d.status==='successful')setTimeout(()=>location.href='/receipt/{token}',650)}}</script>""")


@app.get("/receipt/{token}", response_class=HTMLResponse)
def receipt_page(token: str) -> HTMLResponse:
    payment = PAYMENTS.get(token)
    if not payment or payment["method"] != "QR":
        raise HTTPException(404, "QR payment not found")
    if payment["status"] != "successful":
        raise HTTPException(409, "Receipt is available only after a successful demo payment")
    return HTMLResponse(f"""<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><title>Payment Sent</title><style>body{{font-family:Arial;max-width:460px;margin:30px auto;padding:20px;background:#f4f7fb}}.card{{background:#fff;padding:26px;border-radius:16px;box-shadow:0 8px 24px #ccd}}.sent{{background:#d8f5e4;border:3px solid #65c78f;border-radius:16px;padding:20px;text-align:center;color:#087443}}.row{{display:flex;justify-content:space-between;border-bottom:1px solid #e6ebf1;padding:12px 0}}</style><div class='card'><div class='sent'><h1>PAYMENT SENT</h1><p>Demo payment approved successfully.</p></div><p class='row'><span>Transaction ID</span><b>{escape(payment['transaction_id'])}</b></p><p class='row'><span>Payment ID</span><b>{escape(payment['payment_id'])}</b></p><p class='row'><span>Amount</span><b>{payment['amount']:.2f} DEMO</b></p><p class='row'><span>Method</span><b>QR</b></p><p class='row'><span>Reference</span><b>{escape(payment['simulation_reference'])}</b></p></div>""")


@app.get("/mock-payment/{token}", response_class=HTMLResponse)
def mock_page(token: str) -> HTMLResponse:
    if token not in PAYMENTS:
        raise HTTPException(404, "Payment token not found.")
    return HTMLResponse(f"""<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><title>Demo Payment</title><div style='font-family:Arial;max-width:460px;margin:30px auto;padding:20px'><h1>Checkout Demo</h1><p><b>SIMULATION ONLY</b> — no real money is processed.</p><button onclick=finish('/complete')>Approve simulated payment</button><button onclick=finish('/fail')>Fail simulated payment</button><pre id='out'></pre><script>async function finish(path){{let r=await fetch('/api/payments/{token}'+path,{{method:'POST'}});document.getElementById('out').textContent=await r.text()}}</script></div>""")
