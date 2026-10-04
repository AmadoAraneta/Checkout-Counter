from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def setup_function():
    client.post('/api/reset')


def create_qr_payment():
    return client.post('/api/payments', json={
        'session_id': 'DEMO-1001',
        'payment_method': 'QR',
        'amount': 34.0,
    })


def test_qr_payment_returns_qr_metadata_and_png():
    response = create_qr_payment()
    assert response.status_code == 200
    body = response.json()
    assert body['phone_url'].endswith('/phone/' + body['payment_token'])
    assert body['qr_image_url'].endswith('/qr')
    qr = client.get(body['qr_image_url'])
    assert qr.status_code == 200
    assert qr.headers['content-type'] == 'image/png'
    assert qr.content.startswith(b'\x89PNG')


def test_phone_confirmation_creates_checkout_transaction_and_receipt():
    payment = create_qr_payment().json()
    token = payment['payment_token']
    confirmed = client.post(f'/api/payments/{token}/confirm', json={'confirmation': 'DEMO-APPROVE'})
    assert confirmed.status_code == 200
    assert confirmed.json()['status'] == 'successful'
    assert client.get(f'/api/payments/{token}').json()['transaction_status'] == 'PAYMENT_SUCCESS'
    receipt = client.get(f'/receipt/{token}')
    assert receipt.status_code == 200
    assert 'PAYMENT SENT' in receipt.text
    assert payment['transaction_id'] in receipt.text


def test_qr_confirmation_rejects_duplicate_confirmation():
    payment = create_qr_payment().json()
    token = payment['payment_token']
    client.post(f'/api/payments/{token}/confirm', json={'confirmation': 'DEMO-DECLINE'})
    duplicate = client.post(f'/api/payments/{token}/confirm', json={'confirmation': 'DEMO-APPROVE'})
    assert duplicate.status_code == 409
    assert duplicate.json()['detail']['status'] == 'DUPLICATE'


def test_payment_method_and_non_finite_amount_are_rejected():
    invalid_method = client.post('/api/payments', json={'session_id': 'DEMO-1001', 'payment_method': 'CARD', 'amount': 34})
    assert invalid_method.status_code == 422
    invalid_amount = client.post('/api/payments', json={'session_id': 'DEMO-1001', 'payment_method': 'QR', 'amount': 'NaN'})
    assert invalid_amount.status_code == 422
