"""get_credentials, save_credentials — access/refresh tokens encrypted at rest.

Key management: a Fernet key generated once and stored at
`<OPENTICKER_HOME>/secret.key` (mode 0600, own-user-only). Simplest option
that keeps a self-hosted single-user install from ever writing a plaintext
broker token to disk, without requiring a separate secrets manager.
"""

import os
import tempfile
from datetime import datetime

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from openticker.ports.models import Credentials
from openticker.storage.sqlite.engine import get_data_dir, get_engine
from openticker.storage.sqlite.models import CredentialRow


def _get_or_create_key() -> bytes:
    """The key, made on first use. The daemon's threads may all ask at once
    on a new home: the key is written whole to a file of its own and linked
    into place, which fails if another thread got there first, so nobody
    reads a key half-written."""
    key_path = get_data_dir() / "secret.key"
    if key_path.exists():
        return key_path.read_bytes()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd, staged = tempfile.mkstemp(dir=key_path.parent, prefix=".secret.key.")
    try:
        with os.fdopen(fd, "wb") as staged_file:  # mkstemp's file is 0600
            staged_file.write(key)
        os.link(staged, key_path)
    except FileExistsError:
        return key_path.read_bytes()
    finally:
        os.unlink(staged)
    return key


def _fernet() -> Fernet:
    return Fernet(_get_or_create_key())


def save_credentials(credentials: Credentials) -> None:
    fernet = _fernet()
    row = CredentialRow(
        broker=credentials.broker,
        access_token_encrypted=fernet.encrypt(credentials.access_token.encode()),
        refresh_token_encrypted=(
            fernet.encrypt(credentials.refresh_token.encode())
            if credentials.refresh_token is not None
            else None
        ),
        expires_at=(
            credentials.expires_at.isoformat() if credentials.expires_at is not None else None
        ),
    )
    with Session(get_engine()) as session:
        session.merge(row)
        session.commit()


def get_credentials(broker: str) -> Credentials | None:
    fernet = _fernet()
    with Session(get_engine()) as session:
        row = session.scalar(select(CredentialRow).where(CredentialRow.broker == broker))
    if row is None:
        return None
    return Credentials(
        broker=row.broker,
        access_token=fernet.decrypt(row.access_token_encrypted).decode(),
        refresh_token=(
            fernet.decrypt(row.refresh_token_encrypted).decode()
            if row.refresh_token_encrypted is not None
            else None
        ),
        expires_at=(datetime.fromisoformat(row.expires_at) if row.expires_at is not None else None),
    )
