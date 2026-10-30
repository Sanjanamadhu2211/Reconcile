from __future__ import annotations

import io

import pytest

from app.imports.checksum import ImportFileError, check_size, sha256_hex


class TestCheckSize:
    def test_within_limit(self):
        check_size(1024 * 1024, 10)  # 1 MB, limit 10 MB

    def test_at_limit(self):
        check_size(10 * 1024 * 1024, 10)  # exactly 10 MB

    def test_exceeds_limit(self):
        with pytest.raises(ImportFileError) as exc:
            check_size(11 * 1024 * 1024, 10)
        assert "exceeds limit" in str(exc.value)

    def test_zero_size(self):
        check_size(0, 10)


class TestSha256Hex:
    def test_empty_stream(self):
        stream = io.BytesIO(b"")
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert sha256_hex(stream) == expected

    def test_simple_content(self):
        stream = io.BytesIO(b"hello world")
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert sha256_hex(stream) == expected

    def test_rewinds_stream(self):
        stream = io.BytesIO(b"test content")
        stream.seek(5)
        assert stream.tell() == 5
        sha256_hex(stream)
        assert stream.tell() == 5  # Should be rewound

    def test_large_content_chunks(self):
        # Create content larger than 64 KiB to test chunking
        content = b"x" * (128 * 1024)
        stream = io.BytesIO(content)
        hash1 = sha256_hex(stream)
        # Verify consistency
        stream2 = io.BytesIO(content)
        hash2 = sha256_hex(stream2)
        assert hash1 == hash2

    def test_unicode_content(self):
        stream = io.BytesIO("hello世界".encode())
        # Just verify it doesn't error and produces a hash
        result = sha256_hex(stream)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)
