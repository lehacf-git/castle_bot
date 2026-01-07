from __future__ import annotations

import base64
import datetime as dt
from pathlib import Path
from typing import Dict

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

def load_private_key(path: Path) -> rsa.RSAPrivateKey:
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)

def now_ms_str() -> str:
    return str(int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000))

def sign_pss_sha256(private_key: rsa.RSAPrivateKey, message: str) -> str:
    sig = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode("utf-8")

def auth_headers(
    *,
    key_id: str,
    private_key: rsa.RSAPrivateKey,
    method: str,
    path: str,
    timestamp_ms: str | None = None,
) -> Dict[str, str]:
    """Create Kalshi auth headers.

    Docs: sign a concatenation of timestamp + HTTP method + path (no query params).
    """
    ts = timestamp_ms or now_ms_str()
    path_no_q = path.split("?")[0]
    msg = f"{ts}{method.upper()}{path_no_q}"
    sig = sign_pss_sha256(private_key, msg)
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": sig,
    }
