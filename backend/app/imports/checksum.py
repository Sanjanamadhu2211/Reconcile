from __future__ import annotations

import hashlib
from typing import BinaryIO


class ImportFileError(Exception):
    """File-level error during import (encoding, size, row cap)."""

    pass


def check_size(size_bytes: int, max_mb: int) -> None:
    """Check if file size is within the allowed limit.

    Raises ImportFileError if size exceeds max_mb.
    """
    max_bytes = max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise ImportFileError(f"File size {size_bytes} bytes exceeds limit of {max_mb} MB")


def sha256_hex(stream: BinaryIO) -> str:
    """Compute SHA-256 hash of a stream, reading in 64 KiB chunks.

    Rewinds the stream to its original position after reading.
    """
    original_position = stream.tell()
    try:
        stream.seek(0)
        hasher = hashlib.sha256()
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            hasher.update(chunk)
        return hasher.hexdigest()
    finally:
        stream.seek(original_position)
