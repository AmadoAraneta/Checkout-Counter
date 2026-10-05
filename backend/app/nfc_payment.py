"""Demo-only NFC payment state machine and serial reader.

This module deliberately treats RC522 UIDs as non-financial demo identifiers.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from typing import Callable, Iterable, Optional, Protocol

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover - optional until hardware is used
    serial = None

LOG = logging.getLogger(__name__)
MONEY = Decimal("0.01")
PARKING_FEE = Decimal("50.00")
UID_RE = re.compile(r"^[0-9A-Fa-f]{4,32}$")


class PaymentStatus(str, Enum):
    WAITING_FOR_AMOUNT = "WAITING_FOR_AMOUNT"
    WAITING_FOR_NFC = "WAITING_FOR_NFC"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class PaymentConfig:
    serial_port: Optional[str] = None
    baudrate: int = 115200
    serial_timeout: float = 1.0
    approved_uids: frozenset[str] = frozenset()
    parking_fee: Decimal = PARKING_FEE


@dataclass(frozen=True)
class PaymentResult:
    transaction_id: str
    status: str
    reason: str
    requested_amount: Decimal
    parking_fee: Decimal
    total_amount: Decimal
    entered_amount: Optional[Decimal] = None
    tag_uid: Optional[str] = None
    payment_option: str = "NFC"


@dataclass
class PaymentSession:
    transaction_id: str
    requested_amount: Decimal
    payment_option: str
    status: PaymentStatus = PaymentStatus.WAITING_FOR_AMOUNT
    amount_buffer: str = ""
    result: Optional[PaymentResult] = None
    events: list[str] = field(default_factory=list)
    _parking_fee: Decimal = PARKING_FEE

    @property
    def total_amount(self) -> Decimal:
        return (self.requested_amount + self._parking_fee).quantize(MONEY)

    def display(self) -> dict[str, str]:
        return {
            "transaction_id": self.transaction_id,
            "amount": f"{self.requested_amount:.2f} DEMO",
            "parking_fee_label": "Parking Fee",
            "parking_fee": f"₱{self._parking_fee:.2f}",
            "total": f"{self.total_amount:.2f}",
            "status": self.status.value,
        }


class PaymentService:
    """Owns active transactions and publishes keypad/NFC events to them."""

    def __init__(self, config: PaymentConfig):
        self.config = config
        self._active: Optional[PaymentSession] = None
        self._history: dict[str, PaymentResult] = {}
        self._lock = threading.RLock()

    @property
    def active_session(self) -> Optional[PaymentSession]:
        with self._lock:
            return self._active

    @property
    def history(self) -> dict[str, PaymentResult]:
        with self._lock:
            return dict(self._history)

    def start_transaction(self, transaction_id: str, amount: Decimal | str, payment_option: str = "NFC") -> PaymentSession:
        amount = self._money(amount)
        if amount < 0:
            raise ValueError("transaction amount must be non-negative")
        with self._lock:
            if self._active and self._active.status in (PaymentStatus.WAITING_FOR_AMOUNT, PaymentStatus.WAITING_FOR_NFC):
                raise RuntimeError("another NFC transaction is already pending")
            self._active = PaymentSession(transaction_id, amount, payment_option.upper(), _parking_fee=self.config.parking_fee)
            return self._active

    def handle_keypad(self, key: str) -> Optional[PaymentResult]:
        key = key.strip()
        if len(key) != 1 or key not in "0123456789.#*":
            return self._fail_pending("INVALID_KEY")
        with self._lock:
            session = self._pending()
            if session is None or session.status != PaymentStatus.WAITING_FOR_AMOUNT:
                return None
            if key == "*":
                session.amount_buffer = session.amount_buffer[:-1]
                return None
            if key == "#":
                return self._submit_amount(session)
            if key == "." and "." in session.amount_buffer:
                return self._fail(session, "INVALID_AMOUNT_FORMAT")
            if "." in session.amount_buffer and len(session.amount_buffer.split(".", 1)[1]) >= 2:
                return self._fail(session, "AMOUNT_HAS_MORE_THAN_TWO_DECIMALS")
            if len(session.amount_buffer.replace(".", "")) >= 8:
                return self._fail(session, "AMOUNT_TOO_LONG")
            session.amount_buffer += key
            return None

    def handle_nfc_tag(self, uid: str) -> Optional[PaymentResult]:
        normalized = self._normalize_uid(uid)
        with self._lock:
            session = self._pending()
            if session is None or session.status != PaymentStatus.WAITING_FOR_NFC:
                return None
            if normalized is None:
                return self._fail(session, "INVALID_UID")
            if normalized not in self.config.approved_uids:
                return self._fail(session, "UNREGISTERED_UID", tag_uid=normalized)
            return self._succeed(session, tag_uid=normalized)

    def _submit_amount(self, session: PaymentSession) -> PaymentResult | None:
        if not session.amount_buffer:
            return self._fail(session, "EMPTY_AMOUNT")
        try:
            entered = self._money(session.amount_buffer)
        except (InvalidOperation, ValueError):
            return self._fail(session, "INVALID_AMOUNT_FORMAT")
        if entered != session.requested_amount:
            return self._fail(session, "AMOUNT_MISMATCH", entered_amount=entered)
        session.status = PaymentStatus.WAITING_FOR_NFC
        session.events.append("PROMPT_NFC")
        return None

    def _succeed(self, session: PaymentSession, tag_uid: str) -> PaymentResult:
        result = PaymentResult(session.transaction_id, "SUCCESS", "APPROVED", session.requested_amount,
                               session._parking_fee, (session.requested_amount + session._parking_fee).quantize(MONEY),
                               self._money(session.amount_buffer), tag_uid, session.payment_option)
        session.status, session.result = PaymentStatus.SUCCESS, result
        self._history[session.transaction_id] = result
        return result

    def _fail(self, session: PaymentSession, reason: str, entered_amount: Optional[Decimal] = None, tag_uid: Optional[str] = None) -> PaymentResult:
        result = PaymentResult(session.transaction_id, "FAILED", reason, session.requested_amount,
                               session._parking_fee, (session.requested_amount + session._parking_fee).quantize(MONEY),
                               entered_amount, tag_uid, session.payment_option)
        session.status, session.result = PaymentStatus.FAILED, result
        self._history[session.transaction_id] = result
        return result

    def _fail_pending(self, reason: str) -> Optional[PaymentResult]:
        with self._lock:
            session = self._pending()
            return self._fail(session, reason) if session else None

    def _pending(self) -> Optional[PaymentSession]:
        return self._active if self._active and self._active.status in (PaymentStatus.WAITING_FOR_AMOUNT, PaymentStatus.WAITING_FOR_NFC) else None

    @staticmethod
    def _money(value: Decimal | str) -> Decimal:
        result = Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
        if result < 0:
            raise ValueError("amount must be non-negative")
        return result

    @staticmethod
    def _normalize_uid(uid: str) -> Optional[str]:
        normalized = re.sub(r"[\s:-]", "", uid).upper()
        return normalized if UID_RE.fullmatch(normalized) else None


def load_config(environ: Optional[dict[str, str]] = None) -> PaymentConfig:
    env = environ or os.environ
    raw_uids = env.get("NFC_APPROVED_UIDS", "04A1B2C3D4")
    uids = frozenset(filter(None, (PaymentService._normalize_uid(item) for item in raw_uids.split(","))))
    return PaymentConfig(serial_port=env.get("NFC_SERIAL_PORT") or None,
                         baudrate=int(env.get("NFC_BAUDRATE", "115200")),
                         serial_timeout=float(env.get("NFC_SERIAL_TIMEOUT", "1")),
                         approved_uids=uids)


class EventSink(Protocol):
    def handle_keypad(self, key: str) -> Optional[PaymentResult]: ...
    def handle_nfc_tag(self, uid: str) -> Optional[PaymentResult]: ...


class SerialReaderService:
    """One serial-reader service for both keypad and RC522 events."""

    def __init__(self, config: PaymentConfig, sink: EventSink):
        self.config, self.sink = config, sink
        self._stop = threading.Event()
        self._serial = None

    def parse_line(self, raw_line: str) -> list[tuple[str, str]]:
        line = raw_line.strip()
        if not line:
            return []
        events: list[tuple[str, str]] = []
        # Supports the combined simulator form: 6.80# NFC_TAG:UID
        if " NFC_TAG:" in line:
            amount, tag = line.split(" NFC_TAG:", 1)
            if amount.endswith("#"):
                events.extend(("KEYPAD", ch) for ch in amount[:-1] if ch in "0123456789.")
                events.append(("KEYPAD", "#"))
                line = "NFC_TAG:" + tag.strip()
        if line.startswith("KEYPAD:"):
            key = line[7:].strip()
            if len(key) == 1 and key in "0123456789.#*":
                events.append(("KEYPAD", key))
            return events
        if line.startswith("NFC_TAG:"):
            uid = line[8:].strip()
            if uid and PaymentService._normalize_uid(uid):
                events.append(("NFC_TAG", uid))
            return events
        return events

    def process_line(self, raw_line: str) -> list[Optional[PaymentResult]]:
        results = []
        for event_type, value in self.parse_line(raw_line):
            result = self.sink.handle_keypad(value) if event_type == "KEYPAD" else self.sink.handle_nfc_tag(value)
            if result is not None:
                results.append(result)
        return results

    def run(self) -> None:
        if not self.config.serial_port:
            raise RuntimeError("NFC_SERIAL_PORT is not configured")
        if serial is None:
            raise RuntimeError("pyserial is required for hardware serial mode")
        self._serial = serial.Serial(self.config.serial_port, self.config.baudrate, timeout=self.config.serial_timeout)
        try:
            while not self._stop.is_set():
                raw = self._serial.readline()
                if raw:
                    self.process_line(raw.decode("utf-8", errors="replace"))
        finally:
            self._serial.close()

    def stop(self) -> None:
        self._stop.set()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    service = PaymentService(config)
    print("Simulated NFC payment service ready; approved demo UIDs:", ", ".join(sorted(config.approved_uids)))
    if config.serial_port:
        SerialReaderService(config, service).run()
    else:
        print("Set NFC_SERIAL_PORT to connect an ESP32 serial stream.")


if __name__ == "__main__":
    main()
