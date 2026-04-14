"""Building the SSL context used for HTTPS requests."""

from __future__ import annotations

import os
import ssl
from pathlib import Path

__all__ = ["create_ssl_context"]


def create_ssl_context(
    ca_bundle: str | os.PathLike[str] | None = None,
) -> ssl.SSLContext:
    """Return a client SSL context with certificate checks turned on.

    By default the system's trusted CAs are used. Pass `ca_bundle` (a PEM
    file or a folder of hashed certificates) to trust a custom CA instead,
    for example an internal company CA or a self-signed test certificate.

    There is deliberately no way to switch verification off.
    """
    if ca_bundle is None:
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    else:
        path = Path(ca_bundle)
        if path.is_dir():
            context = ssl.create_default_context(capath=str(path))
        elif path.is_file():
            context = ssl.create_default_context(cafile=str(path))
        else:
            raise FileNotFoundError(f"CA bundle not found: {path}")

    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # These are already the defaults; set them so the intent is obvious.
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context
