# Checkout Counter Demo — Checkout Counter

A local React + TypeScript + Vite frontend connected to a Python + FastAPI backend. QR is simulated; NFC can use the included ESP32 + RC522 serial reader. No real money is processed.

## Run in Visual Studio Code

On Windows, once dependencies are installed in `backend/.venv`, run `./backend/start.ps1` from the project root (or `./start.ps1` from `backend`). This uses the project Python environment explicitly and avoids missing-module errors from a globally installed Uvicorn. Environment variables set in that terminal are inherited.

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
# Optional: set the ESP32 serial port if it is not COM16
$env:NFC_SERIAL_PORT="COM16"
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
$env:PUBLIC_BASE_URL="http://10.22.4.155:5000"
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
- Pending payments reset when the backend restarts. Completed transactions and audit events can be archived in Firestore using the setup below.

## Firestore archive (mart-parking-fdd6b)

The backend archives successful checkout receipts and their audit events in the dedicated collection `checkout_counter_9a73c8f1b4624dd49ac3d5d4e2347f69`. It only creates documents with automatically generated IDs: it never updates or deletes Firestore documents, seeds carts, enumerates other collections, or deploys security rules. Existing collections are untouched. `/api/reset` clears local demo state only; archived history remains visible.

1. Install the updated backend requirements with `python -m pip install -r requirements.txt` from `backend`.
2. Obtain server credentials for `mart-parking-fdd6b` from Firebase project settings > Service accounts, or use Google Application Default Credentials. Keep any credential JSON outside this repository. The browser Firebase configuration alone does not authenticate this Python backend.
3. In the same PowerShell terminal that starts the backend, run:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="C:/path/outside/repository/service-account.json"
$env:CHECKOUT_FIRESTORE_ENABLED="true"
python -m uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

`backend/start.ps1` automatically loads `backend/.env` when present, and the backend now also loads that file when started directly with Uvicorn. Copy `.env.example` to `.env` to configure a new installation; both `.env` and `service-account.json` are gitignored. Relative credential paths resolve from the backend folder. Settings already defined in the terminal take precedence over `.env`. Set `CHECKOUT_FIRESTORE_ENABLED=true` and provide credentials for the `mart-parking-fdd6b` project before completing a payment. Check `GET /api/firestore/status` to verify the live connection; it reports the project, collection, enabled state, and any connection error. With Firestore enabled, a failed archive returns HTTP 503 and leaves the payment waiting so it can be retried. History and audit routes read only the dedicated collection. Pending payments, demo carts, and the backend phone receipt page remain local; archived history and audit events remain available after a restart.

No live database migration or credentials are included. The provided web API key and Analytics settings are unnecessary for this backend integration. Server access uses Google IAM; existing browser security rules remain unchanged. Successful simulated payments are still demo data. Run local tests with `CHECKOUT_FIRESTORE_ENABLED=false` to avoid writing test payments to Firestore.

## Integrated QR payment flow

### Shopping group ticket lookup

Enter `1002` or `TKT-1002` in **Ticket ID**. Checkout queries `shoppingCartWorkspaces/shopping-cart/shoppingSessions` in project `mart-parking-fdd6b`, database `(default)`, for `ticket_no == "TKT-1002"` and `status == "ready_for_checkout"`. Sessions without a ticket field or another status are excluded. Multiple matches are displayed for individual selection; all payment operations identify the cart by its session document ID. Demo IDs retain their local behavior.

Cart contents come from `items`; `totalCentavos` is an integer converted to pesos and validated against the items. Supported item prices are peso `unitPrice`/`unit_price`/`price` or integer `unitPriceCentavos`/`priceCentavos`. The existing PHP 20 parking fee is added separately. Payment creation rereads the selected session and rejects changed totals or sessions no longer ready. The receipt preserves that session ID and the ticket number in the checkout archive.

The source collection is read-only. Submit a cart using `1002` through the shopping team's dashboard to create a real test record; the checkout app does not seed it. The existing credential file belongs to `smart-shopping-cart-33ab9`; that identity must have access to `mart-parking-fdd6b`, or use a credential supplied for the correct project. Creating a new Firebase project is unnecessary.

Pending payments remain local. The application does not yet mark a source session as paid or enforce cross-system duplicate checkout prevention; coordinate this with the shopping group. A paid status must apply to individual session IDs, not the shared ticket number.

The QR option follows the Lab 4 simulated-payment workflow while using the Checkout-Counter React screens:

1. A validated cart total creates a QR payment through `POST /api/payments`.
2. The backend returns a phone URL and PNG QR image at `/api/payments/{token}/qr`.
3. A phone on the same network can approve or decline with `DEMO-APPROVE` or `DEMO-DECLINE`.
4. The React payment screen polls `/api/payments/{token}` and advances to the existing receipt/history flow after success.
5. Repeated confirmations return HTTP `409`, and reusing the same payment token is idempotent.

The backend accepts the QR provider aliases `method` and `transaction_id` alongside the Checkout-Counter fields. Cart/session validation remains authoritative, so the payment amount must match the loaded cart total, including the fixed ₱20.00 parking fee.


## Physical ESP32 + RC522 NFC setup

The backend listens to the ESP32 JSON serial protocol on `COM16` at 115200 baud. The included firmware is `esp32_rfid_keypad.ino` in the project root. Upload it with Arduino IDE, close Arduino Serial Monitor, then start the backend. The NFC screen polls `/api/nfc/status`, displays the detected card UID, and also receives keypad digits.

The serial port can be changed with PowerShell before starting the backend:

```powershell
$env:NFC_SERIAL_PORT="COM16"
$env:NFC_BAUD_RATE="115200"
python -m uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

You can verify the reader connection at `http://localhost:5000/api/nfc/status`.
