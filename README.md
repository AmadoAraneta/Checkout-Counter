# Checkout Counter Demo — Workstream A

A local React + TypeScript + Vite frontend connected to a Python + FastAPI backend. QR and NFC are simulations only; no real money is processed.

## Run in Visual Studio Code

Extract the ZIP and open the `checkout-system` folder in VS Code. Open two terminals.

### Terminal 1: backend

```bash
cd backend
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

Backend: http://localhost:5000 · API docs: http://localhost:5000/docs

### Terminal 2: frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Test flow

1. Use manual Session ID `DEMO-1001` (or use the ZXing camera scanner with a barcode containing that text).
2. Review the cart total (€34.00) and continue.
3. Select simulated QR or NFC.
4. For QR, scan the displayed code or click **Approve on this device**. The phone-friendly mock URL is served by the backend.
5. For NFC, enter any four digits and detect the simulated NFC tag.
6. Download the HTML or PDF receipt, then open **History** to see the transaction and audit events.
7. For failure testing, click the failure option on the mock payment page or use an invalid session such as `BAD-SESSION`.

## Phone QR testing

The backend is already bound to `0.0.0.0`. Find the laptop IP with `ipconfig` (Windows) or `ip addr`/`ifconfig` (macOS/Linux). Replace `localhost` in the generated URL with the laptop IP, for example:

`http://192.168.1.25:5000/phone/PAY-ABC123`

Connect the phone and laptop to the same Wi-Fi/hotspot and allow Python through the firewall if prompted. The frontend polls the backend, so approving from the phone updates the checkout screen.

## Optional configuration

Create `frontend/.env.local` if the backend is hosted elsewhere:

```env
VITE_API_URL=http://localhost:5000/api
```

## Architecture

- `backend/app/main.py`: FastAPI routes, Pydantic request validation, mock carts, in-memory payments/transactions/audits, CORS, and phone mock page.
- `frontend/src/main.tsx`: typed React views for scan, cart summary, payment selection, QR/NFC payment, receipt, and transaction history.
- The frontend uses one centralized JSON API helper and validates totals before enabling payment.
- In-memory data resets when the backend restarts. This is intentional for a deterministic demo.

## Integrated QR payment flow

The QR option follows the Lab 4 simulated-payment workflow while using the Checkout-Counter React screens:

1. A validated cart total creates a QR payment through `POST /api/payments`.
2. The backend returns a phone URL and PNG QR image at `/api/payments/{token}/qr`.
3. A phone on the same network can approve or decline with `DEMO-APPROVE` or `DEMO-DECLINE`.
4. The React payment screen polls `/api/payments/{token}` and advances to the existing receipt/history flow after success.
5. Repeated confirmations return HTTP `409`, and reusing the same payment token is idempotent.

The backend accepts the QR provider aliases `method` and `transaction_id` alongside the Checkout-Counter fields. Cart/session validation remains authoritative, so the payment amount must match the loaded cart total.
