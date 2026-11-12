"""Verify isolation and payment failure behavior without accessing Firebase."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import firestore_store, main


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv('CHECKOUT_FIRESTORE_ENABLED', 'false')
    main.PAYMENTS.clear()
    main.TRANSACTIONS.clear()
    main.AUDITS.clear()


def test_archive_only_creates_new_document(monkeypatch):
    monkeypatch.setenv('CHECKOUT_FIRESTORE_ENABLED', 'true')
    target = Mock()
    monkeypatch.setattr(firestore_store, 'collection', lambda: target)
    firestore_store.archive({'transaction_id': 'TX'}, [{'event_id': 'AUD'}])
    target.document.assert_called_once_with()
    target.document.return_value.create.assert_called_once_with({
        'transaction': {'transaction_id': 'TX'}, 'audits': [{'event_id': 'AUD'}]})
    target.document.return_value.set.assert_not_called()
    target.document.return_value.delete.assert_not_called()


def test_archive_failure_does_not_complete_payment(monkeypatch):
    client = TestClient(main.app)
    token = client.post('/api/payments', json={
        'session_id': 'DEMO-1001', 'payment_method': 'QR', 'amount': 54,
    }).json()['payment_token']

    def unavailable(*args):
        raise HTTPException(503, 'Unavailable')

    monkeypatch.setattr(firestore_store, 'archive', unavailable)
    response = client.post(f'/api/payments/{token}/confirm', json={'confirmation': 'DEMO-APPROVE'})
    assert response.status_code == 503
    assert main.PAYMENTS[token]['status'] == 'waiting'
    assert main.TRANSACTIONS == []
    assert main.AUDITS == []
    monkeypatch.setattr(firestore_store, 'archive', lambda *args: None)
    assert client.post(f'/api/payments/{token}/confirm', json={'confirmation': 'DEMO-APPROVE'}).status_code == 200
    assert len(main.TRANSACTIONS) == 1


def test_reset_does_not_access_firestore(monkeypatch):
    monkeypatch.setenv('CHECKOUT_FIRESTORE_ENABLED', 'true')
    target = Mock(side_effect=AssertionError('Reset must not touch Firestore'))
    monkeypatch.setattr(firestore_store, 'collection', target)
    assert TestClient(main.app).post('/api/reset').status_code == 200
    target.assert_not_called()


def test_history_reads_archive_after_local_reset(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setenv('CHECKOUT_FIRESTORE_ENABLED', 'true')
    transaction = {'transaction_id': 'OLD', 'timestamp': datetime.now(timezone.utc)}
    event = {'transaction_id': 'OLD', 'event_id': 'AUD'}
    monkeypatch.setattr(firestore_store, 'records', lambda: [
        {'transaction': transaction, 'audits': [event]}])
    client = TestClient(main.app)
    client.post('/api/reset')
    assert client.get('/api/transactions').json()[0]['transaction_id'] == 'OLD'
    assert client.get('/api/transactions/OLD/audit').json() == [event]
