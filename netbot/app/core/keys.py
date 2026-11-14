"""Claves derivadas: cada finalidad usa una clave propia, nunca el secreto de firma."""
import hashlib
import hmac


def derive_key(root: str, purpose: str) -> str:
    return hmac.new(root.encode(), f'netbot:{purpose}'.encode(), hashlib.sha256).hexdigest()
