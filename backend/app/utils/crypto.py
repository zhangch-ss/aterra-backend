import base64
import hashlib
from cryptography.fernet import Fernet
from app.core.config import settings


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a valid Fernet key (32 url-safe base64-encoded bytes) from arbitrary secret string."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()  # 32 bytes
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_fernet_key(settings.ENCRYPT_KEY))


def encrypt_text(plain: str) -> str:
    return _fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_text(token: str) -> str:
    return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
