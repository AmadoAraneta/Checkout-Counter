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

## Hardware NFC payment integration

The NFC option now uses the payment state machine and serial protocol from the companion `nfc_payment_service_vscode` project. The combined project includes the ESP32 firmware in `firmware/esp32_rc522_keypad.ino` and must be flashed to an ESP32 connected to an RC522 reader and matrix keypad.

Configure the backend before starting it:

```env
NFC_SERIAL_PORT=/dev/ttyUSB0
NFC_APPROVED_UIDS=04A1B2C3D4,DEADBEEF
NFC_BAUDRATE=115200
NFC_SERIAL_TIMEOUT=1
```

The backend starts one serial reader for the active Checkout-Counter payment. The cart total is sent as the requested NFC amount; the keypad must submit that exact amount followed by `#`, then an approved NFC UID must be read. The NFC service's original optional parking-fee calculation is configured to `0.00` by default in the checkout integration so it cannot silently change the cart/order total; override `NFC_PARKING_FEE` only when that fee is an intentional part of the order.

The integrated NFC endpoints are:

```text
POST /api/payments/{token}/nfc/start
GET  /api/payments/{token}/nfc/status
POST /api/payments/{token}/nfc/cancel
```

The browser polls the status endpoint. Success is converted into the existing Checkout-Counter transaction, receipt, and audit flow; failure, cancellation, serial/device errors, and the five-minute payment timeout remain visible as payment states and do not create a completed order.

The ESP32-to-backend serial protocol is unchanged:

```text
KEYPAD:6
KEYPAD:.
KEYPAD:#
NFC_TAG:04A1B2C3D4
```
