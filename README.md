# Checkout Counter Demo — Checkout Counter

A local React + TypeScript + Vite frontend connected to a Python + FastAPI backend. QR is simulated; NFC can use the included ESP32 + RC522 serial reader. No real money is processed.

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
# Optional: set the ESP32 serial port if it is not COM15
$env:NFC_SERIAL_PORT="COM15"
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

1. Enter Ticket Receipt ID `DEMO-1001` manually to load the purchase.
2. Review the items subtotal (₱34.00) plus the fixed parking fee (₱20.00); total due is ₱54.00 and continue.
3. Select simulated QR or NFC.
4. For QR, scan the displayed code or click **Approve on this device**. The phone-friendly mock URL is served by the backend.
5. For NFC, enter any four digits and detect the simulated NFC tag.
6. Download the HTML or PDF receipt, then open **History** to see the transaction and audit events.
7. For failure testing, click the failure option on the mock payment page or use an invalid session such as `BAD-SESSION`.

## Phone QR testing

The backend is already bound to `0.0.0.0`. QR URLs now replace a loopback host such as `localhost` with the laptop's detected LAN IP automatically, so the phone can open the URL when both devices are on the same Wi-Fi or hotspot. Allow Python through the firewall if prompted.

If the laptop has multiple network adapters, a VPN, or auto-detection chooses the wrong address, set `PUBLIC_BASE_URL` before starting the backend:

```powershell
$env:PUBLIC_BASE_URL="http://192.168.1.25:5000"
python -m uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

The frontend polls the backend, so approving from the phone updates the checkout screen.

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

The backend accepts the QR provider aliases `method` and `transaction_id` alongside the Checkout-Counter fields. Cart/session validation remains authoritative, so the payment amount must match the loaded cart total, including the fixed ₱20.00 parking fee.


## Physical ESP32 + RC522 NFC setup

The backend listens to the ESP32 JSON serial protocol on `COM15` at 115200 baud. The included firmware is `esp32_rfid_keypad.ino` in the project root. Upload it with Arduino IDE, close Arduino Serial Monitor, then start the backend. The NFC screen polls `/api/nfc/status`, displays the detected card UID, and also receives keypad digits.

The serial port can be changed with PowerShell before starting the backend:

```powershell
$env:NFC_SERIAL_PORT="COM15"
$env:NFC_BAUD_RATE="115200"
python -m uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

You can verify the reader connection at `http://localhost:5000/api/nfc/status`.
