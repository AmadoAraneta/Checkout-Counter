from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main, shopping_sessions


def raw_cart():
    return {'cartId': 'CART-LIVE', 'ticket_no': 'TKT-1002', 'status': 'ready_for_checkout',
            'items': [{'productId': 'P1', 'name': 'Milk', 'quantity': 2, 'price': 25}],
            'totalCentavos': 5000}


def test_ticket_query_uses_confirmed_fields_and_preserves_each_session(monkeypatch):
    source = Mock()
    source.where.return_value = source
    documents = []
    for session_id in ['session-a', 'session-b']:
        document = Mock(id=session_id)
        document.to_dict.return_value = raw_cart()
        documents.append(document)
    source.stream.return_value = documents
    monkeypatch.setattr(shopping_sessions, 'sessions', lambda: source)
    carts = shopping_sessions.find_ticket('1002')
    assert [cart['session_id'] for cart in carts] == ['session-a', 'session-b']
    filters = [call.kwargs['filter'] for call in source.where.call_args_list]
    assert [(item.field_path, item.value) for item in filters] == [
        ('ticket_no', 'TKT-1002'), ('status', 'ready_for_checkout')]
    assert carts[0]['subtotal'] == 50
    source.document.assert_not_called()
    source.add.assert_not_called()


def test_document_id_lookup(monkeypatch):
    source = Mock()
    document = source.document.return_value.get.return_value
    document.exists = True
    document.id = 'session-a'
    document.to_dict.return_value = raw_cart()
    monkeypatch.setattr(shopping_sessions, 'sessions', lambda: source)
    assert shopping_sessions.lookup('session-a')['session_id'] == 'session-a'
    source.document.assert_called_once_with('session-a')
    source.where.assert_not_called()


def test_missing_ticket(monkeypatch):
    source = Mock()
    source.where.return_value = source
    source.stream.return_value = []
    monkeypatch.setattr(shopping_sessions, 'sessions', lambda: source)
    with pytest.raises(HTTPException) as error:
        shopping_sessions.find_ticket('1002')
    assert error.value.status_code == 404


def test_session_must_still_be_ready(monkeypatch):
    source = Mock()
    raw = raw_cart()
    raw['status'] = 'paid'
    source.document.return_value.get.return_value.to_dict.return_value = raw
    monkeypatch.setattr(shopping_sessions, 'sessions', lambda: source)
    with pytest.raises(HTTPException) as error:
        shopping_sessions.lookup('session-a')
    assert error.value.status_code == 409


def test_mismatched_total_rejected():
    raw = raw_cart()
    raw['totalCentavos'] = 50000
    with pytest.raises(HTTPException) as error:
        shopping_sessions.normalize(raw, 'doc', 'TICKET-42')
    assert error.value.status_code == 409


def test_credentials_error_does_not_fall_back_to_demo(monkeypatch):
    monkeypatch.setattr(shopping_sessions, 'sessions', Mock(side_effect=RuntimeError('No credentials')))
    response = TestClient(main.app).get('/api/carts/TICKET-42')
    assert response.status_code == 503


def test_missing_credentials_explains_setup(monkeypatch):
    from google.auth.exceptions import DefaultCredentialsError
    monkeypatch.setattr(shopping_sessions, 'sessions', Mock(side_effect=DefaultCredentialsError('missing')))
    response = TestClient(main.app).get('/api/carts/TICKET-42')
    assert response.status_code == 503
    assert 'GOOGLE_APPLICATION_CREDENTIALS' in response.json()['detail']


def test_payment_uses_loaded_ticket_and_freezes_receipt(monkeypatch):
    monkeypatch.setenv('CHECKOUT_FIRESTORE_ENABLED', 'false')
    raw = raw_cart()
    read = Mock(side_effect=lambda ticket: shopping_sessions.normalize(raw, 'doc', ticket))
    monkeypatch.setattr(shopping_sessions, 'lookup', read)
    main.PAYMENTS.clear()
    main.TRANSACTIONS.clear()
    main.AUDITS.clear()
    client = TestClient(main.app)
    loaded = client.get('/api/carts/TICKET-42').json()
    assert loaded['total'] == 70  # Existing fixed parking fee is included.
    assert client.post('/api/payments', json={
        'session_id': 'TICKET-42', 'payment_method': 'QR', 'amount': 54}).status_code == 422
    payment = client.post('/api/payments', json={
        'session_id': 'TICKET-42', 'payment_method': 'QR', 'amount': 70}).json()
    raw['totalCentavos'] = 10000  # The source changes after payment creation.
    response = client.post(f"/api/payments/{payment['payment_token']}/confirm",
                           json={'confirmation': 'DEMO-APPROVE'})
    assert response.status_code == 200
    assert main.TRANSACTIONS[-1]['subtotal'] == 50
    assert main.TRANSACTIONS[-1]['amount'] == 70


def test_centavo_conversion_and_validation():
    raw = raw_cart()
    raw['items'][0].pop('price')
    raw['items'][0]['priceCentavos'] = 2599
    raw['totalCentavos'] = 5198
    cart = shopping_sessions.normalize(raw, 'session-a', 'TKT-1002')
    assert cart['subtotal'] == 51.98
    assert cart['items'][0]['unit_price'] == 25.99
    raw['totalCentavos'] = 51.98
    with pytest.raises(HTTPException) as error:
        shopping_sessions.normalize(raw, 'session-a', 'TKT-1002')
    assert error.value.status_code == 422


def test_ticket_endpoint_returns_all_sessions_with_separate_totals(monkeypatch):
    carts = [shopping_sessions.normalize(raw_cart(), session_id, 'TKT-1002')
             for session_id in ['session-a', 'session-b']]
    monkeypatch.setattr(shopping_sessions, 'find_ticket', lambda ticket: carts)
    response = TestClient(main.app).get('/api/tickets/1002/sessions')
    assert response.status_code == 200
    assert [cart['session_id'] for cart in response.json()] == ['session-a', 'session-b']
    assert all(cart['total'] == 70 for cart in response.json())


def test_shared_ticket_payments_remain_distinct_by_session(monkeypatch):
    monkeypatch.setenv('CHECKOUT_FIRESTORE_ENABLED', 'false')
    monkeypatch.setattr(shopping_sessions, 'lookup', lambda session_id:
                        shopping_sessions.normalize(raw_cart(), session_id, 'TKT-1002'))
    main.PAYMENTS.clear()
    main.TRANSACTIONS.clear()
    main.AUDITS.clear()
    client = TestClient(main.app)
    for session_id in ['session-a', 'session-b']:
        payment = client.post('/api/payments', json={
            'session_id': session_id, 'payment_method': 'QR', 'amount': 70}).json()
        assert payment['session_id'] == session_id
        assert client.post(f"/api/payments/{payment['payment_token']}/confirm",
                           json={'confirmation': 'DEMO-APPROVE'}).status_code == 200
    assert [tx['session_id'] for tx in main.TRANSACTIONS] == ['session-a', 'session-b']
    assert all(tx['ticket_no'] == 'TKT-1002' for tx in main.TRANSACTIONS)
