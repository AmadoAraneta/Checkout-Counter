from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List
from fastapi import HTTPException
from .adapter import CartAdapter


def round_money(value: Any) -> float:
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def get_fixture_cart(session_id: str) -> Dict[str, Any] | None:
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail='Session ID must not be empty')
    clean_id = session_id.strip()
    raw = CartAdapter.fetch_raw_cart(clean_id)
    if not raw:
        return None
    if raw.get('status') == 'NOT_FOUND' or raw.get('cart_id') is None:
        raise HTTPException(status_code=404, detail=f"Cart session '{clean_id}' not found")
    items: List[Dict[str, Any]] = raw.get('items', [])
    subtotal = Decimal('0.00')
    normalized = []
    for item in items:
        quantity = item.get('quantity')
        if not isinstance(quantity, int) or quantity <= 0:
            raise HTTPException(status_code=422, detail=f"Invalid quantity for product {item.get('product_id')}: must be positive integer")
        unit_price = Decimal(str(item.get('unit_price')))
        line_total = (Decimal(quantity) * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        subtotal += line_total
        normalized.append({
            'product_id': str(item.get('product_id')),
            'product_name': str(item.get('name', item.get('product_name', 'Unnamed product'))),
            'quantity': quantity,
            'unit_price': round_money(unit_price),
            'line_total': float(line_total),
        })
    calculated = float(subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    if round_money(raw.get('total')) != calculated or round_money(raw.get('subtotal')) != calculated:
        raise HTTPException(status_code=409, detail=f"Total mismatch! Calculated: {calculated}, Supplied: {raw.get('total')}")
    return {'cart_id': raw['cart_id'], 'session_id': raw['session_id'], 'items': normalized, 'subtotal': calculated, 'total': calculated, 'currency': raw.get('currency', 'DEMO')}
