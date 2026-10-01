import pytest
from fastapi import HTTPException
from app.service import get_fixture_cart


def test_valid_camera_cart_session():
    cart = get_fixture_cart('SHOP-20260928-0007')
    assert cart['cart_id'] == 'CART-07'
    assert cart['session_id'] == 'SHOP-20260928-0007'
    assert cart['total'] == 6.80
    assert cart['subtotal'] == 6.80
    assert cart['items'][0]['product_name'] == 'Milk'


def test_camera_cart_total_mismatch():
    with pytest.raises(HTTPException) as exc_info:
        get_fixture_cart('SHOP-20260928-0008')
    assert exc_info.value.status_code == 409
    assert 'Total mismatch' in exc_info.value.detail


def test_unknown_camera_session():
    with pytest.raises(HTTPException) as exc_info:
        get_fixture_cart('SHOP-UNKNOWN-9999')
    assert exc_info.value.status_code == 404


def test_empty_session():
    with pytest.raises(HTTPException) as exc_info:
        get_fixture_cart('   ')
    assert exc_info.value.status_code == 400
