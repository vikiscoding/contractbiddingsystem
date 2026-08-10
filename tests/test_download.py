"""Unit tests for CanadaBuys CSV download (mocked HTTP)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from opportunity_ingest.download import (
    DEFAULT_CSV_URL,
    DownloadError,
    download_csv_bytes,
    download_csv_text,
    download_to_path,
)


def _mock_transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def test_download_csv_bytes_success():
    body = b"\xef\xbb\xbfcol1,col2\nv1,v2\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == DEFAULT_CSV_URL
        return httpx.Response(200, content=body)

    with _mock_transport(handler) as client:
        raw = download_csv_bytes(client=client)
    assert raw == body


def test_download_csv_text_strips_bom():
    body = b"\xef\xbb\xbfcol1,col2\nv1,v2\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with _mock_transport(handler) as client:
        text = download_csv_text(client=client)
    assert not text.startswith("\ufeff")
    assert text.startswith("col1,col2")


def test_download_retries_once_then_succeeds():
    calls = {"n": 0}
    body = b"a,b\n1,2\n"

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, content=body)

    with _mock_transport(handler) as client:
        raw = download_csv_bytes(client=client)
    assert raw == body
    assert calls["n"] == 2


def test_download_fails_after_one_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="error")

    with _mock_transport(handler) as client:
        with pytest.raises(DownloadError, match="after retry"):
            download_csv_bytes(client=client)
    assert calls["n"] == 2


def test_download_empty_content_raises_after_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=b"   \n")

    with _mock_transport(handler) as client:
        with pytest.raises(DownloadError, match="empty"):
            download_csv_bytes(client=client)
    assert calls["n"] == 2


def test_download_html_content_raises_after_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=b"<!DOCTYPE html><html></html>")

    with _mock_transport(handler) as client:
        with pytest.raises(DownloadError, match="HTML"):
            download_csv_bytes(client=client)
    assert calls["n"] == 2


def test_download_bom_prefixed_html_raises():
    """UTF-8 BOM before HTML must still be rejected as non-CSV."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=b"\xef\xbb\xbf<!DOCTYPE html><html></html>")

    with _mock_transport(handler) as client:
        with pytest.raises(DownloadError, match="HTML"):
            download_csv_bytes(client=client)
    assert calls["n"] == 2


def test_download_empty_then_success_on_retry():
    calls = {"n": 0}
    body = b"a,b\n1,2\n"

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, content=b"")
        return httpx.Response(200, content=body)

    with _mock_transport(handler) as client:
        raw = download_csv_bytes(client=client)
    assert raw == body
    assert calls["n"] == 2


def test_download_respects_url_override(monkeypatch):
    custom = "https://example.test/custom.csv"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"x,y\n1,2\n")

    with _mock_transport(handler) as client:
        download_csv_bytes(url=custom, client=client)
    assert seen == [custom]

    monkeypatch.setenv("CANADABUYS_CSV_URL", "https://example.test/from-env.csv")
    seen.clear()

    def handler2(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"x,y\n1,2\n")

    with _mock_transport(handler2) as client:
        download_csv_bytes(client=client)
    assert seen == ["https://example.test/from-env.csv"]


def test_invalid_http_timeout_env_raises_download_error(monkeypatch):
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "not-a-number")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"a,b\n")

    with _mock_transport(handler) as client:
        with pytest.raises(DownloadError, match="HTTP_TIMEOUT_SECONDS"):
            download_csv_bytes(client=client)


def test_download_to_path(tmp_path: Path):
    body = b"\xef\xbb\xbfh1,h2\na,b\n"
    out = tmp_path / "nested" / "sample.csv"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with _mock_transport(handler) as client:
        path = download_to_path(out, client=client)
    assert path == out
    assert out.read_bytes() == body


def test_cli_download_sample_writes_file(tmp_path: Path, monkeypatch):
    from opportunity_ingest.cli import main

    body = b"col\nval\n"
    out = tmp_path / "out.csv"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    # Patch download_to_path's client path by patching httpx.Client
    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs.setdefault("timeout", 5.0)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake_client)
    code = main(["download-sample", "--out", str(out)])
    assert code == 0
    assert out.read_bytes() == body
