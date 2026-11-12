"""Append-only checkout archive, isolated from the project's other collections."""
import os
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / '.env', override=False)


PROJECT_ID = 'mart-parking-fdd6b'
# Fixed random namespace for this installation; never use shared collection names.
COLLECTION = 'checkout_counter_9a73c8f1b4624dd49ac3d5d4e2347f69'


def enabled():
    return os.getenv('CHECKOUT_FIRESTORE_ENABLED', 'false').lower() == 'true'


def credential_path():
    configured = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if not configured:
        return None
    path = Path(configured).expanduser()
    return str(path if path.is_absolute() else BACKEND_DIR / path)


@lru_cache(maxsize=1)
def client():
    from google.cloud import firestore
    from google.oauth2 import service_account

    credentials_file = credential_path()
    options = {'project': PROJECT_ID}
    if credentials_file:
        if not Path(credentials_file).is_file():
            raise FileNotFoundError(f'Firestore credential file was not found: {credentials_file}')
        options['credentials'] = service_account.Credentials.from_service_account_file(credentials_file)
    return firestore.Client(**options)


def collection():
    return client().collection(COLLECTION)


def status():
    if not enabled():
        return {'enabled': False, 'connected': False, 'project': PROJECT_ID, 'collection': COLLECTION}
    try:
        next(collection().limit(1).stream(), None)
        return {'enabled': True, 'connected': True, 'project': PROJECT_ID, 'collection': COLLECTION}
    except Exception as exc:
        return {'enabled': True, 'connected': False, 'project': PROJECT_ID,
                'collection': COLLECTION, 'error': str(exc)}


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
