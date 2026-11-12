"""Append-only checkout archive, isolated from the project's other collections."""
import os

from fastapi import HTTPException


PROJECT_ID = 'mart-parking-fdd6b'
# Fixed random namespace for this installation; never use shared collection names.
COLLECTION = 'checkout_counter_9a73c8f1b4624dd49ac3d5d4e2347f69'


def enabled():
    return os.getenv('CHECKOUT_FIRESTORE_ENABLED', 'false').lower() == 'true'


def collection():
    from google.cloud import firestore
    return firestore.Client(project=PROJECT_ID).collection(COLLECTION)


def archive(transaction, events):
    if not enabled():
        return
    try:
        # Auto-generated document ID and create() cannot overwrite any document.
        collection().document().create({'transaction': transaction, 'audits': events})
    except Exception as exc:
        raise HTTPException(503, 'Firestore archive unavailable; checkout was not completed. Check backend credentials and Firestore access.') from exc


def records():
    try:
        return [snapshot.to_dict() for snapshot in collection().stream()]
    except Exception as exc:
        raise HTTPException(503, 'Firestore history unavailable. Check backend credentials and Firestore access.') from exc


def transactions():
    return sorted((record['transaction'] for record in records()), key=lambda tx: tx['timestamp'], reverse=True)


def audits(transaction_id):
    return [event for record in records() for event in record.get('audits', [])
            if event['transaction_id'] == transaction_id]
