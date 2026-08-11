"""Tests for SharePoint OpportunityStore (mocked httpx + MSAL — no real network)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from opportunity_ingest.config import Settings
from opportunity_ingest.models import OpportunityFields
from opportunity_ingest.storage import (
    OpportunityStore,
    SharePointOpportunityStore,
    StoreError,
    StoreWriteError,
    build_store,
    normalize_link,
)
from opportunity_ingest.storage.sharepoint_store import (
    extract_link_url,
    fields_to_graph_payload,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 15, 30, 0, tzinfo=UTC)

SITE = "site-abc"
LIST = "list-def"
GRAPH_ITEMS = f"https://graph.microsoft.com/v1.0/sites/{SITE}/lists/{LIST}/items"
GRAPH_LIST = f"https://graph.microsoft.com/v1.0/sites/{SITE}/lists/{LIST}"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = dict(
        _env_file=None,
        storage_backend="sharepoint",
        azure_tenant_id="tenant-1",
        azure_client_id="client-1",
        azure_client_secret="secret-1",
        sharepoint_site_id=SITE,
        sharepoint_list_id=LIST,
        http_timeout_seconds=30.0,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _fields(**overrides: object) -> OpportunityFields:
    base: dict[str, object] = dict(
        Title="Cloud RPA services",
        OpportunityID="PW-2026-001",
        Source="CanadaBuys",
        Buyer="PSPC",
        Link="https://canadabuys.canada.ca/en/tender-opportunities/notice/pw-2026-001",
        PublishedDate=date(2026, 8, 8),
        ClosingDate=datetime(2026, 8, 20, 14, 0, 0, tzinfo=UTC),
        Category="D302A",
        Description="Azure and RPA",
        KeywordsMatched="azure, rpa",
        RelevanceScore=42,
        Status="New",
        DateAdded=NOW,
        Notes="",
    )
    base.update(overrides)
    return OpportunityFields(**base)  # type: ignore[arg-type]


def _json_response(status: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=payload,
        request=httpx.Request("GET", "https://graph.microsoft.com/v1.0/"),
    )


class FakeTransport(httpx.BaseTransport):
    """Route Graph calls via a handler; records requests for assertions."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


@pytest.fixture
def token_provider() -> Any:
    return lambda: "test-access-token"


def test_extract_link_url_str_and_hyperlink_object():
    assert extract_link_url("https://example.com/a") == "https://example.com/a"
    assert extract_link_url({"Url": "https://example.com/b", "Description": "x"}) == (
        "https://example.com/b"
    )
    assert extract_link_url({"url": "https://example.com/c"}) == "https://example.com/c"
    assert extract_link_url(None) == ""
    assert extract_link_url(123) == "123"


def test_fields_to_graph_payload_plain_text_link_and_status():
    payload = fields_to_graph_payload(_fields())
    assert payload["Link"] == (
        "https://canadabuys.canada.ca/en/tender-opportunities/notice/pw-2026-001"
    )
    assert isinstance(payload["Link"], str)
    assert payload["Status"] == "New"
    assert payload["DateAdded"] == "2026-08-10T15:30:00Z"
    assert payload["PublishedDate"] == "2026-08-08"
    assert payload["ClosingDate"] == "2026-08-20T14:00:00Z"
    assert payload["OpportunityID"] == "PW-2026-001"
    assert payload["RelevanceScore"] == 42


def test_missing_settings_raises_store_error():
    settings = Settings(
        _env_file=None,
        storage_backend="sharepoint",
        azure_tenant_id=None,
        azure_client_id="c",
        azure_client_secret="s",
        sharepoint_site_id=SITE,
        sharepoint_list_id=LIST,
    )
    with pytest.raises(StoreError, match="AZURE_TENANT_ID"):
        SharePointOpportunityStore(settings)


def test_implements_protocol(token_provider: Any):
    store = SharePointOpportunityStore(
        _settings(),
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: _json_response(200, {}))),
        token_provider=token_provider,
    )
    assert isinstance(store, OpportunityStore)
    assert store.name == "sharepoint"


def test_health_check_token_and_list_access(token_provider: Any):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-access-token"
        assert request.method == "GET"
        assert str(request.url).startswith(GRAPH_LIST)
        return _json_response(200, {"id": LIST, "displayName": "Contract Opportunities"})

    transport = FakeTransport(handler)
    client = httpx.Client(transport=transport)
    store = SharePointOpportunityStore(
        _settings(), http_client=client, token_provider=token_provider
    )
    store.health_check()
    assert len(transport.requests) == 1


def test_health_check_graph_403_raises(token_provider: Any):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=403,
            text='{"error":{"message":"Access denied"}}',
            request=request,
        )

    store = SharePointOpportunityStore(
        _settings(),
        http_client=httpx.Client(transport=FakeTransport(handler)),
        token_provider=token_provider,
    )
    with pytest.raises(StoreError, match="health_check"):
        store.health_check()


def test_load_existing_keys_paginates_and_normalizes_links(token_provider: Any):
    page1 = {
        "value": [
            {
                "id": "1",
                "fields": {
                    "OpportunityID": "PW-1",
                    "Link": "  HTTPS://Example.COM/Path/  ",
                },
            },
            {
                "id": "2",
                "fields": {
                    "OpportunityID": "  PW-2  ",
                    "Link": {"Url": "https://Example.COM/Other/", "Description": "x"},
                },
            },
        ],
        "@odata.nextLink": GRAPH_ITEMS + "?$skiptoken=page2",
    }
    page2 = {
        "value": [
            {
                "id": "3",
                "fields": {"OpportunityID": "PW-3", "Link": "https://example.com/three"},
            },
        ],
    }
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.method == "GET"
        url = str(request.url)
        if "skiptoken=page2" in url:
            return _json_response(200, page2)
        assert "$top=100" in url or "%24top=100" in url
        assert "OpportunityID" in url
        assert "Link" in url
        return _json_response(200, page1)

    store = SharePointOpportunityStore(
        _settings(),
        http_client=httpx.Client(transport=FakeTransport(handler)),
        token_provider=token_provider,
    )
    keys = store.load_existing_keys()
    assert calls["n"] == 2
    assert keys.opportunity_ids == {"PW-1", "PW-2", "PW-3"}
    assert normalize_link("HTTPS://Example.COM/Path/") in keys.links
    assert normalize_link("https://Example.COM/Other/") in keys.links
    assert normalize_link("https://example.com/three") in keys.links


def test_load_existing_keys_empty(token_provider: Any):
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(200, {"value": []})

    store = SharePointOpportunityStore(
        _settings(),
        http_client=httpx.Client(transport=FakeTransport(handler)),
        token_provider=token_provider,
    )
    keys = store.load_existing_keys()
    assert keys.opportunity_ids == set()
    assert keys.links == set()


def test_create_posts_plain_text_link_and_returns_id(token_provider: Any):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url).startswith(GRAPH_ITEMS)
        body = request.read()
        import json

        data = json.loads(body)
        fields = data["fields"]
        assert fields["Link"] == (
            "https://canadabuys.canada.ca/en/tender-opportunities/notice/pw-2026-001"
        )
        assert isinstance(fields["Link"], str)
        assert "Url" not in fields["Link"] if isinstance(fields["Link"], dict) else True
        assert fields["Status"] == "New"
        assert fields["DateAdded"] == "2026-08-10T15:30:00Z"
        assert fields["OpportunityID"] == "PW-2026-001"
        assert fields["Title"] == "Cloud RPA services"
        return _json_response(201, {"id": "99", "fields": fields})

    store = SharePointOpportunityStore(
        _settings(),
        http_client=httpx.Client(transport=FakeTransport(handler)),
        token_provider=token_provider,
    )
    item_id = store.create(_fields())
    assert item_id == "99"


def test_create_validation_errors(token_provider: Any):
    store = SharePointOpportunityStore(
        _settings(),
        http_client=httpx.Client(
            transport=FakeTransport(lambda r: _json_response(500, {}))
        ),
        token_provider=token_provider,
    )
    with pytest.raises(StoreWriteError, match="OpportunityID"):
        store.create(_fields(OpportunityID=""))
    with pytest.raises(StoreWriteError, match="Title"):
        store.create(_fields(Title="  "))
    with pytest.raises(StoreWriteError, match="Link"):
        store.create(_fields(Link=""))


def test_create_graph_error_raises_store_write_error(token_provider: Any):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=400,
            text='{"error":{"message":"Invalid request"}}',
            request=request,
        )

    store = SharePointOpportunityStore(
        _settings(),
        http_client=httpx.Client(transport=FakeTransport(handler)),
        token_provider=token_provider,
    )
    with pytest.raises(StoreWriteError, match="create"):
        store.create(_fields())


def test_factory_sharepoint_builds_store():
    settings = _settings()
    built = build_store(settings)
    assert isinstance(built, SharePointOpportunityStore)
    assert built.name == "sharepoint"
    assert built.site_id == SITE
    assert built.list_id == LIST


def test_factory_sharepoint_missing_secret_raises():
    settings = Settings(
        _env_file=None,
        storage_backend="sharepoint",
        azure_tenant_id="t",
        azure_client_id="c",
        azure_client_secret=None,
        sharepoint_site_id=SITE,
        sharepoint_list_id=LIST,
    )
    with pytest.raises(StoreError, match="AZURE_CLIENT_SECRET"):
        build_store(settings)


def test_token_via_msal_client_credentials(monkeypatch: pytest.MonkeyPatch):
    """MSAL ConfidentialClientApplication path (no custom token_provider)."""
    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {"access_token": "msal-token"}
    mock_cls = MagicMock(return_value=mock_app)
    monkeypatch.setattr(
        "opportunity_ingest.storage.sharepoint_store.msal.ConfidentialClientApplication",
        mock_cls,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer msal-token"
        return _json_response(200, {"id": LIST, "displayName": "Contract Opportunities"})

    store = SharePointOpportunityStore(
        _settings(),
        http_client=httpx.Client(transport=FakeTransport(handler)),
    )
    store.health_check()
    mock_cls.assert_called_once()
    kwargs = mock_cls.call_args
    assert kwargs[0][0] == "client-1" or kwargs.args[0] == "client-1"
    mock_app.acquire_token_for_client.assert_called_with(
        scopes=["https://graph.microsoft.com/.default"]
    )


def test_msal_token_failure_raises(monkeypatch: pytest.MonkeyPatch):
    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {
        "error": "invalid_client",
        "error_description": "bad secret",
    }
    monkeypatch.setattr(
        "opportunity_ingest.storage.sharepoint_store.msal.ConfidentialClientApplication",
        MagicMock(return_value=mock_app),
    )
    store = SharePointOpportunityStore(_settings())
    with pytest.raises(StoreError, match="MSAL"):
        store.health_check()


def test_create_retries_auth_on_401(token_provider: Any):
    tokens = iter(["stale-token", "fresh-token"])

    def provider() -> str:
        return next(tokens)

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers["Authorization"]
        calls.append(auth)
        if auth == "Bearer stale-token":
            return httpx.Response(status_code=401, text="unauthorized", request=request)
        body_fields = {
            "Title": "Cloud RPA services",
            "OpportunityID": "PW-2026-001",
        }
        return _json_response(201, {"id": "7", "fields": body_fields})

    # token_provider is used each acquire; invalidate clears cache so second call gets next.
    store = SharePointOpportunityStore(
        _settings(),
        http_client=httpx.Client(transport=FakeTransport(handler)),
        token_provider=provider,
    )
    # First token cached as stale; 401 invalidates; second acquire returns fresh.
    item_id = store.create(_fields())
    assert item_id == "7"
    assert calls == ["Bearer stale-token", "Bearer fresh-token"]
