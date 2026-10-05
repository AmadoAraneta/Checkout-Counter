"""Hardware NFC orchestration for checkout payments.

The manager preserves the NFC service's serial protocol and state machine while
binding one NFC session to one Checkout-Counter payment token.  No simulated
completion is performed here: a successful result requires a real serial event
from the configured ESP32/RC522 service.
"""
from __future__ import annotations

import os
import threading
from decimal import Decimal
from typing import Any, Optional

from .nfc_payment import PaymentConfig, PaymentService, PaymentStatus, SerialReaderService


class NFCManager:
    def __init__(self) -> None:
        approved = os.getenv("NFC_APPROVED_UIDS", "04A1B2C3D4")
        uids = frozenset(
            uid for uid in (PaymentService._normalize_uid(value) for value in approved.split(",")) if uid
        )
        self.config = PaymentConfig(
            serial_port=os.getenv("NFC_SERIAL_PORT") or None,
            baudrate=int(os.getenv("NFC_BAUDRATE", "115200")),
            serial_timeout=float(os.getenv("NFC_SERIAL_TIMEOUT", "1")),
            approved_uids=uids,
            # Checkout-Counter owns the cart total. The NFC service's optional
            # parking-fee concept must not silently change the order amount.
            parking_fee=Decimal(os.getenv("NFC_PARKING_FEE", "0.00")),
        )
        self.service = PaymentService(self.config)
        self.reader: Optional[SerialReaderService] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.reader_error: Optional[str] = None
        self.payment_token: Optional[str] = None
        self._lock = threading.RLock()

    @property
    def configured(self) -> bool:
        return bool(self.config.serial_port)

    def start(self, payment_token: str, transaction_id: str, amount: float) -> dict[str, Any]:
        with self._lock:
            if not self.configured:
                raise RuntimeError("NFC_SERIAL_PORT is not configured; connect the ESP32 NFC service first.")
            if self.payment_token and self.service.active_session and self.service.active_session.status in (
                PaymentStatus.WAITING_FOR_AMOUNT,
                PaymentStatus.WAITING_FOR_NFC,
            ):
                raise RuntimeError("Another NFC payment is already in progress.")
            self.service.start_transaction(transaction_id, Decimal(str(amount)), payment_option="NFC")
            self.payment_token = payment_token
            self.reader_error = None
            self.reader = SerialReaderService(self.config, self.service)
            self.reader_thread = threading.Thread(target=self._run_reader, name="nfc-serial-reader", daemon=True)
            self.reader_thread.start()
            return self.status(payment_token)

    def _run_reader(self) -> None:
        try:
            assert self.reader is not None
            self.reader.run()
        except Exception as exc:  # serial errors must be visible to the checkout UI
            with self._lock:
                self.reader_error = str(exc)
                session = self.service.active_session
                if session and session.status in (PaymentStatus.WAITING_FOR_AMOUNT, PaymentStatus.WAITING_FOR_NFC):
                    self.service._fail(session, "SERIAL_READER_ERROR")

    def status(self, payment_token: str) -> dict[str, Any]:
        with self._lock:
            if self.payment_token != payment_token:
                return {"status": "not_started", "configured": self.configured}
            session = self.service.active_session
            if session is None:
                return {"status": "not_started", "configured": self.configured}
            result = session.result
            state = session.status.value
            mapped = {
                PaymentStatus.WAITING_FOR_AMOUNT.value: "waiting_for_amount",
                PaymentStatus.WAITING_FOR_NFC.value: "waiting_for_nfc",
                PaymentStatus.SUCCESS.value: "successful",
                PaymentStatus.FAILED.value: "failed",
                PaymentStatus.CANCELLED.value: "cancelled",
            }[state]
            return {
                "status": mapped,
                "service_status": state,
                "configured": self.configured,
                "transaction_id": session.transaction_id,
                "requested_amount": float(session.requested_amount),
                "nfc_total_amount": float(session.total_amount),
                "approved_uid_count": len(self.approved_uids),
                "reader_error": self.reader_error,
                "result": self._result(result),
            }

    def cancel(self, payment_token: str) -> dict[str, Any]:
        with self._lock:
            if self.payment_token != payment_token:
                return {"status": "cancelled", "configured": self.configured}
            session = self.service.active_session
            if session and session.status in (PaymentStatus.WAITING_FOR_AMOUNT, PaymentStatus.WAITING_FOR_NFC):
                session.status = PaymentStatus.CANCELLED
            if self.reader:
                self.reader.stop()
            return self.status(payment_token)

    @staticmethod
    def _result(result: Any) -> Optional[dict[str, Any]]:
        if result is None:
            return None
        return {
            "transaction_id": result.transaction_id,
            "status": result.status.lower(),
            "reason": result.reason,
            "requested_amount": float(result.requested_amount),
            "parking_fee": float(result.parking_fee),
            "total_amount": float(result.total_amount),
            "entered_amount": float(result.entered_amount) if result.entered_amount is not None else None,
            "tag_uid": result.tag_uid,
            "payment_option": result.payment_option,
        }

    @property
    def approved_uids(self) -> frozenset[str]:
        return self.config.approved_uids
