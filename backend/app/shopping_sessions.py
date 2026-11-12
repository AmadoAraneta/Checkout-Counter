"""Read-only ticket lookup for the shopping cart group's sessions."""
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException

from .firestore_store import PROJECT_ID

PATH = 'shoppingCartWorkspaces/shopping-cart/shoppingSessions'


def sessions():
    from google.cloud import firestore
    return firestore.Client(project=PROJECT_ID).collection(PATH)


def read_source(operation):
    from google.auth.exceptions import DefaultCredentialsError
    from google.api_core.exceptions import PermissionDenied, Unauthenticated, DeadlineExceeded
    try:
        return operation(sessions())
    except HTTPException:
        raise
    except DefaultCredentialsError as exc:
        raise HTTPException(503, 'Google credentials are missing or invalid. Set GOOGLE_APPLICATION_CREDENTIALS and restart the backend.') from exc
    except (PermissionDenied, Unauthenticated) as exc:
        raise HTTPException(503, f'Google credentials lack Firestore read access to {PROJECT_ID}. The shopping project service account needs access to this project.') from exc
    except DeadlineExceeded as exc:
        raise HTTPException(503, 'Firestore read timed out. Check the backend network connection.') from exc
    except Exception as exc:
        raise HTTPException(503, 'Cannot read shopping cart sessions. Check backend credentials and Firestore access.') from exc


def valid_id(value):
    if not value or '/' in value or len(value.encode('utf-8')) > 1500:
        raise HTTPException(400, 'Enter a valid ticket or session ID, not a document path.')
    return value.strip()


def find_ticket(ticket):
    from google.cloud.firestore_v1.base_query import FieldFilter
    ticket = valid_id(ticket).upper()
    if ticket.isdecimal():
        ticket = 'TKT-' + ticket

    def query(source):
        documents = list(source.where(filter=FieldFilter('ticket_no', '==', ticket))
                         .where(filter=FieldFilter('status', '==', 'ready_for_checkout'))
                         .stream(timeout=10, retry=None))
        if not documents:
            raise HTTPException(404, f'No ready-for-checkout sessions found for {ticket}. Submit the cart in the shopping dashboard first.')
        # Keep every match. A ticket is not a unique checkout reference.
        return [normalize(doc.to_dict(), doc.id, ticket) for doc in documents]
    return read_source(query)


def lookup(session_id):
    session_id = valid_id(session_id)

    def read(source):
        document = source.document(session_id).get(timeout=10, retry=None)
        if not document.exists:
            raise HTTPException(404, 'Shopping session not found.')
        raw = document.to_dict()
        if raw.get('status') != 'ready_for_checkout':
            raise HTTPException(409, 'This shopping session is no longer ready for checkout.')
        return normalize(raw, document.id, raw.get('ticket_no'))
    return read_source(read)


def first(data, *keys):
    return next((data[key] for key in keys if key in data), None)


def money(value):
    if isinstance(value, bool):
        raise ValueError('Invalid money')
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError('Invalid money')
    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def centavos(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('Expected a nonnegative integer amount in centavos')
    return Decimal(value) / 100


def normalize(raw, document_id, ticket_id):
    """Accept common camelCase/snake_case fields; reject incomplete totals."""
    try:
        items = raw.get(os.getenv('SHOPPING_ITEMS_FIELD', 'items'))
        if not isinstance(items, list) or not items:
            raise ValueError('Items must be a nonempty array')
        result = []
        subtotal = Decimal('0.00')
        for index, item in enumerate(items):
            quantity = first(item, 'quantity', 'qty')
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                raise ValueError('Invalid quantity')
            price_centavos = first(item, 'unitPriceCentavos', 'priceCentavos')
            price = centavos(price_centavos) if price_centavos is not None else money(first(item, 'unit_price', 'unitPrice', 'price'))
            line = money(price * quantity)
            supplied_line = first(item, 'line_total', 'lineTotal')
            if supplied_line is not None and money(supplied_line) != line:
                raise HTTPException(409, 'Shopping cart item total does not match its quantity and price.')
            subtotal += line
            result.append({
                'product_id': str(first(item, 'product_id', 'productId', 'id') or f'item-{index + 1}'),
                'product_name': str(first(item, 'product_name', 'productName', 'name') or 'Unnamed product'),
                'quantity': quantity, 'unit_price': float(price), 'line_total': float(line),
            })
        supplied = centavos(raw.get('totalCentavos'))
        if money(supplied) != subtotal:
            raise HTTPException(409, 'Shopping cart total does not match its items. Ask the cart group to refresh the ticket.')
        return {'cart_id': str(first(raw, 'cart_id', 'cartId') or document_id),
                'session_id': document_id, 'ticket_no': ticket_id, 'items': result, 'subtotal': float(subtotal),
                'total': float(subtotal), 'currency': 'DEMO'}
    except (ValueError, TypeError, InvalidOperation, AttributeError) as exc:
        raise HTTPException(422, 'Shopping session fields are incomplete or invalid. Expected items with quantity and unitPrice/price (or priceCentavos), and integer totalCentavos. Check the shopping group document schema.') from exc
