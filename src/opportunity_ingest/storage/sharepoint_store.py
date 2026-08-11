"""SharePoint OpportunityStore via Microsoft Graph (MSAL client credentials + httpx).

Activated when ``STORAGE_BACKEND=sharepoint``. Not required for day-1 (SQLite default).
Graph list create uses a multi-line plain-text ``Link`` column (string URL, never Hyperlink).

Phase 1 limitations (see also ``scripts/provision_sharepoint_list.md``):
- SharePoint lists have no UNIQUE index; this adapter does not raise ``SkipDuplicate``.
  Rely on single-writer schedule + ``load_existing_keys`` pre-check; concurrent
  ``--write`` runs can insert duplicate OpportunityID/Link rows.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from typing import Any, Self

import httpx
import msal

from opportunity_ingest.config import Settings
from opportunity_ingest.models import ExistingKeys, OpportunityFields
from opportunity_ingest.storage.base import StoreError, StoreWriteError, normalize_link

logger = logging.getLogger(__name__)

UTC = timezone.utc
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
PAGE_SIZE = 100
# Limited Graph throttle retries (429). 5xx is not retried here (fail fast for Actions).
MAX_THROTTLE_RETRIES = 3
DEFAULT_RETRY_AFTER_SECONDS = 1.0


def _fmt_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _fmt_datetime_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_link_url(raw: object) -> str:
    """Normalize Graph Link field value to a URL string.

    SharePoint multi-line plain text returns a plain ``str``. A legacy Hyperlink
    column may return ``{"Url": "...", "Description": "..."}``.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, Mapping):
        url = raw.get("Url") or raw.get("url") or ""
        return str(url) if url is not None else ""
    return str(raw)


def fields_to_graph_payload(fields: OpportunityFields) -> dict[str, Any]:
    """Map logical OpportunityFields to Graph list-item ``fields`` body.

    ``Link`` is always a plain string (multi-line text column), never a Hyperlink object.
    ``Status`` defaults to ``New``; ``DateAdded`` is ISO UTC.
    """
    opportunity_id = str(fields.OpportunityID or "").strip()
    title = str(fields.Title or "").strip()
    # Preserve full URL for humans; strip only. Dedupe normalizes on load.
    link = (fields.Link or "").strip()

    payload: dict[str, Any] = {
        "Title": title,
        "OpportunityID": opportunity_id,
        "Source": fields.Source or "CanadaBuys",
        "Link": link,
        "Status": fields.Status or "New",
        "DateAdded": _fmt_datetime_utc(fields.DateAdded)
        or _fmt_datetime_utc(datetime.now(UTC)),
        "KeywordsMatched": fields.KeywordsMatched or "",
        "RelevanceScore": int(fields.RelevanceScore),
        "Notes": fields.Notes if fields.Notes is not None else "",
    }
    if fields.Buyer is not None:
        payload["Buyer"] = fields.Buyer
    if fields.PublishedDate is not None:
        payload["PublishedDate"] = _fmt_date(fields.PublishedDate)
    if fields.ClosingDate is not None:
        payload["ClosingDate"] = _fmt_datetime_utc(fields.ClosingDate)
    if fields.Category is not None:
        payload["Category"] = fields.Category
    if fields.Description is not None:
        payload["Description"] = fields.Description
    return payload


def _retry_after_seconds(response: httpx.Response) -> float:
    """Parse Retry-After (seconds or HTTP-date is not supported — seconds only)."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return DEFAULT_RETRY_AFTER_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_RETRY_AFTER_SECONDS


class SharePointOpportunityStore:
    """Microsoft Graph SharePoint list backend for Contract Opportunities.

    Owns an ``httpx.Client`` when constructed without ``http_client``; call
    :meth:`close` or use as a context manager to release connections. Injected
    clients are never closed by this store (caller-owned).
    """

    name: str = "sharepoint"

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.Client | None = None,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        missing = [
            name
            for name, val in (
                ("AZURE_TENANT_ID", settings.azure_tenant_id),
                ("AZURE_CLIENT_ID", settings.azure_client_id),
                ("AZURE_CLIENT_SECRET", settings.azure_client_secret),
                ("SHAREPOINT_SITE_ID", settings.sharepoint_site_id),
                ("SHAREPOINT_LIST_ID", settings.sharepoint_list_id),
            )
            if not (val and str(val).strip())
        ]
        if missing:
            raise StoreError(
                "SharePoint backend requires: "
                + ", ".join(missing)
                + ". See scripts/provision_sharepoint_list.md."
            )

        self.tenant_id = str(settings.azure_tenant_id).strip()
        self.client_id = str(settings.azure_client_id).strip()
        self.client_secret = str(settings.azure_client_secret).strip()
        self.site_id = str(settings.sharepoint_site_id).strip()
        self.list_id = str(settings.sharepoint_list_id).strip()
        self.timeout = float(settings.http_timeout_seconds or 120.0)

        self._http_client = http_client
        self._owns_client = http_client is None
        self._token_provider = token_provider
        self._msal_app: msal.ConfidentialClientApplication | None = None

    def close(self) -> None:
        """Close the owned httpx client, if any. Safe to call multiple times."""
        if self._owns_client and self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- auth -----------------------------------------------------------------

    def _msal(self) -> msal.ConfidentialClientApplication:
        if self._msal_app is None:
            authority = f"https://login.microsoftonline.com/{self.tenant_id}"
            self._msal_app = msal.ConfidentialClientApplication(
                self.client_id,
                authority=authority,
                client_credential=self.client_secret,
            )
        return self._msal_app

    def _acquire_token(self) -> str:
        """Client credentials → ``https://graph.microsoft.com/.default``.

        No process-level token cache: MSAL's ``ConfidentialClientApplication``
        already caches tokens until expiry. Custom ``token_provider`` is invoked
        on every request (tests inject a stable or sequenced provider).
        """
        if self._token_provider is not None:
            token = self._token_provider()
            if not token:
                raise StoreError("SharePoint token_provider returned an empty token")
            return token

        result = self._msal().acquire_token_for_client(scopes=GRAPH_SCOPE)
        if not result or "access_token" not in result:
            err = (result or {}).get("error_description") or (result or {}).get("error")
            raise StoreError(f"MSAL client-credentials token failed: {err or result!r}")
        return str(result["access_token"])

    # --- http -----------------------------------------------------------------

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
            )
            self._owns_client = True
        return self._http_client

    def _items_url(self) -> str:
        return f"{GRAPH_BASE}/sites/{self.site_id}/lists/{self.list_id}/items"

    def _list_url(self) -> str:
        return f"{GRAPH_BASE}/sites/{self.site_id}/lists/{self.list_id}"

    def _headers(self, *, with_content_type: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._acquire_token()}",
            "Accept": "application/json",
        }
        if with_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> httpx.Response:
        """Perform a Graph request; refresh token once on 401; limited 429 retries."""
        client = self._client()
        throttle_attempt = 0
        while True:
            try:
                response = client.request(
                    method,
                    url,
                    headers=self._headers(with_content_type=json_body is not None),
                    json=json_body,
                )
            except httpx.HTTPError as exc:
                raise StoreError(f"Graph request failed ({method} {url}): {exc}") from exc

            if response.status_code == 401 and retry_auth:
                # MSAL will refresh if needed on next acquire; token_provider is re-invoked.
                return self._request(
                    method, url, json_body=json_body, retry_auth=False
                )

            if (
                response.status_code == 429
                and throttle_attempt < MAX_THROTTLE_RETRIES
            ):
                wait = _retry_after_seconds(response)
                logger.warning(
                    "Graph 429 on %s %s; retry %s/%s after %.1fs",
                    method,
                    url,
                    throttle_attempt + 1,
                    MAX_THROTTLE_RETRIES,
                    wait,
                )
                time.sleep(wait)
                throttle_attempt += 1
                continue

            return response

    def _raise_for_status(self, response: httpx.Response, action: str) -> None:
        if response.is_success:
            return
        body = response.text
        if len(body) > 500:
            body = body[:500] + "…"
        msg = f"Graph {action} failed: HTTP {response.status_code}: {body}"
        if response.status_code >= 500 or response.status_code == 429:
            raise StoreWriteError(msg) if "create" in action else StoreError(msg)
        if "create" in action:
            raise StoreWriteError(msg)
        raise StoreError(msg)

    # --- OpportunityStore API -------------------------------------------------

    def health_check(self) -> None:
        """Acquire a token and confirm list access (GET list metadata)."""
        try:
            _ = self._acquire_token()
        except StoreError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise StoreError(f"SharePoint token acquisition failed: {exc}") from exc

        response = self._request(
            "GET",
            f"{self._list_url()}?$select=id,displayName",
        )
        self._raise_for_status(response, "health_check list access")

    def load_existing_keys(self) -> ExistingKeys:
        """Paginate list items; collect OpportunityID + normalized Link sets."""
        ids: set[str] = set()
        links: set[str] = set()

        select = "OpportunityID,Link"
        url: str | None = (
            f"{self._items_url()}"
            f"?$expand=fields($select={select})"
            f"&$top={PAGE_SIZE}"
            f"&$select=id"
        )

        while url:
            response = self._request("GET", url)
            self._raise_for_status(response, "load_existing_keys")
            try:
                data = response.json()
            except ValueError as exc:
                raise StoreError(
                    f"Graph load_existing_keys returned non-JSON: {exc}"
                ) from exc

            for item in data.get("value") or []:
                fields = item.get("fields") or {}
                oid = fields.get("OpportunityID")
                if oid is not None:
                    oid_s = str(oid).strip()
                    if oid_s:
                        ids.add(oid_s)
                link_raw = fields.get("Link")
                link_url = extract_link_url(link_raw)
                if link_url.strip():
                    links.add(normalize_link(link_url))

            next_link = data.get("@odata.nextLink")
            url = str(next_link) if next_link else None

        return ExistingKeys(opportunity_ids=ids, links=links)

    def create(self, fields: OpportunityFields) -> str:
        """POST one list item (create-only). Return Graph list item id as str.

        ``Link`` is sent as a plain-text string URL. ``Status`` defaults to
        ``New``; ``DateAdded`` is ISO UTC (via ``fields_to_graph_payload``).

        Does **not** raise ``SkipDuplicate``: SharePoint has no unique constraint
        on OpportunityID/Link (Phase 1 single-writer assumption).
        """
        opportunity_id = str(fields.OpportunityID or "").strip()
        title = str(fields.Title or "").strip()
        link = (fields.Link or "").strip()

        if not opportunity_id:
            raise StoreWriteError("OpportunityID is required for create")
        if not title:
            raise StoreWriteError(
                f"Title is required for OpportunityID={opportunity_id!r}"
            )
        if not link:
            raise StoreWriteError(
                f"Link is required for OpportunityID={opportunity_id!r}"
            )

        body = {"fields": fields_to_graph_payload(fields)}
        response = self._request("POST", self._items_url(), json_body=body)
        if not response.is_success:
            self._raise_for_status(
                response, f"create OpportunityID={opportunity_id!r}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise StoreWriteError(
                f"Graph create returned non-JSON for OpportunityID={opportunity_id!r}: {exc}"
            ) from exc

        item_id = data.get("id")
        if item_id is None or str(item_id).strip() == "":
            raise StoreWriteError(
                f"Graph create returned no item id for OpportunityID={opportunity_id!r}"
            )
        return str(item_id)
