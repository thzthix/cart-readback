"""Offline-only PayPal Orders wire mapping with injected fabricated exchanges.

This mapper has no HTTP implementation, credential loader or live-enable gate.
The isolated HTTPS/OAuth groundwork cannot run directly under this offline label.
The default fixture service never constructs this adapter. Genuine network and
buyer approval require separate authorization/review; fabricated tests cannot
establish PayPal acceptance or settlement.
"""

import json
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode
from uuid import UUID

from cartreadback_app.payments import PaymentRequest, ProviderAmbiguity
from cartreadback_app.provider_json import PARSER_VERSION, strict_provider_json
from cartreadback_app.validation import AppError, canonical, digest, string

SANDBOX_ENDPOINT = "https://api-m.sandbox.paypal.com"
OFFLINE_MODE = "paypal-sandbox-offline"
ORDER_PATH = "/v2/checkout/orders"
MAX_BODY_BYTES = 65536
MAX_BODY_DEPTH = 16
MAX_MINOR = 999999999
ORDER_STATUSES = {
    "CREATED",
    "SAVED",
    "APPROVED",
    "VOIDED",
    "COMPLETED",
    "PAYER_ACTION_REQUIRED",
}
CAPTURE_STATUSES = {
    "COMPLETED",
    "DECLINED",
    "PARTIALLY_REFUNDED",
    "PENDING",
    "REFUNDED",
    "FAILED",
}


def _invalid() -> AppError:
    return AppError("PAYPAL_INVALID_DATA", "Invalid offline payment data.", 409)


def _pattern(value: object, pattern: str) -> str:
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise _invalid()
    return value


def _order_id(value: object) -> str:
    return _pattern(value, r"[A-Z0-9]{1,36}")


def _uuid(value: object) -> str:
    if type(value) is not str:
        raise _invalid()
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise _invalid() from error
    if str(parsed) != value or parsed.version != 4:
        raise _invalid()
    return value


def _object(value: object, fields: set[str] | None = None) -> dict:
    if type(value) is not dict or (fields is not None and set(value) != fields):
        raise _invalid()
    return value


def _minor(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_MINOR:
        raise _invalid()
    return value


def _money(value: object) -> dict:
    value = _minor(value)
    return {"currency_code": "USD", "value": f"{value // 100}.{value % 100:02}"}


def _read_money(value: object) -> int:
    money = _object(value)
    if money.get("currency_code") != "USD":
        raise _invalid()
    decimal = _pattern(money.get("value"), r"(?:0|[1-9][0-9]{0,6})\.[0-9]{2}")
    whole, cents = decimal.split(".")
    return _minor(int(whole) * 100 + int(cents))


def _item(value: object, *, wire: bool) -> dict:
    item = _object(value)
    if wire:
        sku, amount, currency = "sku", "unit_amount", None
        if item.get("quantity") != "1" or type(item.get("quantity")) is not str:
            raise _invalid()
        cents = _read_money(item.get(amount))
    else:
        _object(
            item,
            {"sku_id", "name", "quantity", "unit_amount_minor", "currency"},
        )
        sku, amount, currency = "sku_id", "unit_amount_minor", "currency"
        if type(item.get("quantity")) is not int or item["quantity"] != 1:
            raise _invalid()
        if item.get(currency) != "USD":
            raise _invalid()
        cents = _minor(item[amount])
    return {
        "sku_id": _pattern(item.get(sku), r"[A-Za-z0-9-]{1,127}"),
        "name": string(item.get("name"), "item_name", 127),
        "quantity": 1,
        "unit_amount_minor": cents,
        "currency": "USD",
    }


def _expected(value: object, merchant_id: str) -> dict:
    expected = _object(
        value,
        {
            "provider_mode",
            "intent",
            "merchant_id",
            "reference_id",
            "custom_id",
            "items",
            "amount_minor",
            "currency",
        },
    )
    if (
        expected["provider_mode"] != OFFLINE_MODE
        or expected["intent"] != "CAPTURE"
        or expected["merchant_id"] != merchant_id
        or expected["currency"] != "USD"
        or type(expected["items"]) is not list
        or len(expected["items"]) != 1
    ):
        raise _invalid()
    _uuid(expected["reference_id"])
    _pattern(expected["custom_id"], r"[a-f0-9]{64}")
    item = _item(expected["items"][0], wire=False)
    if _minor(expected["amount_minor"]) != item["unit_amount_minor"]:
        raise _invalid()
    return expected


def sandbox_approval_url(document: object) -> str | None:
    """Extract one exact sandbox checkout URL bound to the returned order ID.

    No navigation occurs. Non-approval HATEOAS links are not followed. A missing
    link remains None; multiple, live, ambiguous or malformed links are rejected.
    Opt-in offline preparation exposes the result only as nonnavigable UI text.
    """
    raw = _object(document)
    order_id = _order_id(raw.get("id"))
    links = raw.get("links", [])
    if type(links) is not list or len(links) > 32:
        raise _invalid()
    approval = []
    for link in links:
        link = _object(link)
        relation = link.get("rel")
        if type(relation) is not str:
            raise _invalid()
        if relation in {"approve", "payer-action"}:
            if link.get("method") != "GET":
                raise _invalid()
            href = link.get("href")
            # Exact comparison excludes userinfo, ports, fragments, escapes,
            # duplicate query keys, extra parameters and host suffix attacks.
            if (
                href
                != f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"
            ):
                raise _invalid()
            approval.append(href)
    if len(approval) > 1:
        raise _invalid()
    return approval[0] if approval else None


def normalize_paypal_order(document: object) -> dict:
    """Copy only returned, validated facts; never fill missing request fields.

    Sparse representations stay sparse and fail the Service verifier, retaining
    a valid known order ID for read-only reconciliation. No payer personal data,
    arbitrary HATEOAS URL or provider metadata is returned for persistence.
    """
    raw = _object(document)
    normalized = {
        "provider_mode": OFFLINE_MODE,
        "provider_order_id": _order_id(raw.get("id")),
    }
    if "status" in raw:
        if (
            type(raw["status"]) is not str
            or raw["status"] not in ORDER_STATUSES
        ):
            raise _invalid()
        normalized["status"] = raw["status"]
    if "intent" in raw:
        if raw["intent"] != "CAPTURE":
            raise _invalid()
        normalized["intent"] = raw["intent"]
    sandbox_approval_url(raw)
    if "purchase_units" not in raw:
        return normalized
    units = raw["purchase_units"]
    if type(units) is not list or len(units) != 1:
        raise _invalid()
    unit = _object(units[0])
    if "reference_id" in unit:
        normalized["reference_id"] = _uuid(unit["reference_id"])
    if "custom_id" in unit:
        normalized["custom_id"] = _pattern(unit["custom_id"], r"[a-f0-9]{64}")
    if "payee" in unit:
        payee = _object(unit["payee"])
        if "merchant_id" in payee:
            normalized["merchant_id"] = _pattern(
                payee["merchant_id"], r"[2-9A-HJ-NP-Z]{13}"
            )
    if "amount" in unit:
        normalized["amount_minor"] = _read_money(unit["amount"])
        normalized["currency"] = "USD"
        amount = unit["amount"]
        if "breakdown" in amount:
            breakdown = _object(amount["breakdown"], {"item_total"})
            if (
                _read_money(breakdown["item_total"])
                != normalized["amount_minor"]
            ):
                raise _invalid()
    if "items" in unit:
        items = unit["items"]
        if type(items) is not list or len(items) != 1:
            raise _invalid()
        normalized["items"] = [_item(items[0], wire=True)]
        if (
            "amount_minor" in normalized
            and normalized["items"][0]["unit_amount_minor"]
            != normalized["amount_minor"]
        ):
            raise _invalid()
    if "payments" in unit:
        payments = _object(unit["payments"])
        if set(payments) - {"captures"}:
            raise _invalid()
        if "captures" in payments:
            captures = payments["captures"]
            if type(captures) is not list or len(captures) > 1:
                raise _invalid()
            normalized["captures"] = []
            for capture in captures:
                capture = _object(capture)
                status = capture.get("status")
                if type(status) is not str or status not in CAPTURE_STATUSES:
                    raise _invalid()
                if capture.get("final_capture") is not True:
                    raise _invalid()
                normalized["captures"].append(
                    {
                        "capture_id": _order_id(capture.get("id")),
                        "status": status,
                        "amount_minor": _read_money(capture.get("amount")),
                        "currency": "USD",
                    }
                )
    return normalized


@dataclass(frozen=True)
class SandboxWireResponse:
    """Bounded in-memory fake response; no headers or credentials are exposed."""

    status_code: int
    body: bytes = field(repr=False)


class SandboxOfflineTransport(Protocol):
    """Injected test seam only, not an approved network transport contract."""

    def send(
        self,
        endpoint: str,
        request: PaymentRequest,
        headers: dict[str, str],
        *,
        timeout_seconds: float,
    ) -> SandboxWireResponse:
        """Exchange once without redirects, retries, authentication or fallback."""
        ...


@dataclass(frozen=True)
class OfflinePayPalSandboxAdapter:
    """Immutable wire settings captured by the existing durable dispatch fence.

    Timeout or uncertain worker startup blocks exchanges on this instance: a
    daemon test transport may still finish, so no second call may overlap it. Durable Service state
    owns UNKNOWN and never replays POST. Credentials cannot be configured here.
    """

    transport: SandboxOfflineTransport
    merchant_id: str
    timeout_seconds: float = 2.0
    buyer_return_origin: str | None = None

    def __post_init__(self) -> None:
        """Validate local settings without inspecting environment or accounts."""
        # A genuine-capable transport must never run under an offline label.
        # Arbitrary injected Python remains trusted test code, not an I/O sandbox.
        if (
            getattr(self.transport, "requires_live_authorization", False)
            is not False
        ):
            raise _invalid()
        _pattern(self.merchant_id, r"[2-9A-HJ-NP-Z]{13}")
        if self.buyer_return_origin is not None:
            _pattern(
                self.buyer_return_origin, r"http://127\.0\.0\.1:[1-9][0-9]{0,4}"
            )
            if int(self.buyer_return_origin.rsplit(":", 1)[1]) > 65535:
                raise _invalid()
        if (
            type(self.timeout_seconds) not in (int, float)
            or not 0 < self.timeout_seconds <= 30
        ):
            raise _invalid()
        object.__setattr__(self, "_flight", threading.Lock())
        object.__setattr__(self, "_blocked", False)

    @property
    def mode(self) -> str:
        """Identify fabricated sandbox-wire evidence, never genuine sandbox."""
        return OFFLINE_MODE

    @property
    def version(self) -> str:
        """Bind every configurable wire setting and defensive parser revision."""
        return "paypal-offline-wire-v1:" + digest(
            {
                "merchant_id": self.merchant_id,
                "timeout_seconds": self.timeout_seconds,
                "endpoint": SANDBOX_ENDPOINT,
                "parser": PARSER_VERSION,
                "buyer_return_origin": self.buyer_return_origin,
                "max_body_bytes": MAX_BODY_BYTES,
                "max_body_depth": MAX_BODY_DEPTH,
            }
        )

    def prepare(
        self,
        kind: str,
        expected: dict,
        provider_order_id: str | None,
    ) -> PaymentRequest:
        """Map authoritative integer USD cents to canonical Orders wire bytes."""
        expected = _expected(expected, self.merchant_id)
        if kind == "capture":
            return PaymentRequest(
                "POST",
                f"{ORDER_PATH}/{_order_id(provider_order_id)}/capture",
                "{}",
            )
        if kind != "orders" or provider_order_id is not None:
            raise _invalid()
        item = expected["items"][0]
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": expected["reference_id"],
                    "custom_id": expected["custom_id"],
                    "payee": {"merchant_id": self.merchant_id},
                    "amount": {
                        **_money(expected["amount_minor"]),
                        "breakdown": {
                            "item_total": _money(expected["amount_minor"])
                        },
                    },
                    "items": [
                        {
                            "sku": item["sku_id"],
                            "name": item["name"],
                            "quantity": "1",
                            "unit_amount": _money(item["unit_amount_minor"]),
                        }
                    ],
                }
            ],
        }
        return PaymentRequest("POST", ORDER_PATH, canonical(body))

    def prepare_checkout(
        self, expected: dict, return_state: str
    ) -> PaymentRequest:
        """Prepare inert callback URLs for injected offline tests, never navigate.

        The Service owns the random state and its durable owner/snapshot binding.
        This opt-in does not add a runtime switch or a network implementation.
        """
        if self.buyer_return_origin is None:
            raise _invalid()
        _pattern(return_state, r"[A-Za-z0-9_-]{43}")
        request = self.prepare("orders", expected, None)
        body = json.loads(request.body)
        body["payment_source"] = {
            "paypal": {
                "experience_context": {
                    "user_action": "CONTINUE",
                    "shipping_preference": "NO_SHIPPING",
                    **{
                        name: self.buyer_return_origin
                        + "/payment-return?"
                        + urlencode(
                            {
                                "order_id": expected["reference_id"],
                                "state": return_state,
                                "outcome": outcome,
                            }
                        )
                        for name, outcome in (
                            ("return_url", "approved"),
                            ("cancel_url", "cancelled"),
                        )
                    },
                }
            }
        }
        return PaymentRequest(request.method, request.path, canonical(body))

    def dispatch(self, operation_id: str, request: PaymentRequest) -> dict:
        """Exchange the exact reserved POST once with its server UUID identity."""
        _uuid(operation_id)
        if (
            type(request) is not PaymentRequest
            or request.method != "POST"
            or type(request.path) is not str
            or type(request.body) is not str
        ):
            raise _invalid()
        try:
            raw = strict_provider_json(
                request.body.encode("utf-8"),
                max_bytes=MAX_BODY_BYTES,
                max_depth=MAX_BODY_DEPTH,
            )
        except (AppError, UnicodeError):
            raise _invalid() from None
        if canonical(raw) != request.body:
            raise _invalid()
        if request.path == ORDER_PATH:
            # Round-trip through the same strict map rejects extra wire fields,
            # changed payee, unsupported charges and noncanonical money/types.
            facts = normalize_paypal_order(
                {
                    "id": "OFFLINE",
                    "intent": raw.get("intent"),
                    "purchase_units": raw.get("purchase_units"),
                }
            )
            facts.pop("provider_order_id")
            if "payment_source" in raw:
                context = _object(
                    _object(
                        _object(raw["payment_source"], {"paypal"})["paypal"],
                        {"experience_context"},
                    )["experience_context"],
                    {
                        "user_action",
                        "shipping_preference",
                        "return_url",
                        "cancel_url",
                    },
                )
                # Extract only a strict state from the exact callback shape,
                # then compare the complete canonical wire request again.
                prefix = (
                    str(self.buyer_return_origin)
                    + "/payment-return?order_id="
                    + facts["reference_id"]
                    + "&state="
                )
                url = context["return_url"]
                if type(url) is not str or not url.startswith(prefix):
                    raise _invalid()
                state = url[len(prefix) :].removesuffix("&outcome=approved")
                prepared = self.prepare_checkout(facts, state)
            else:
                prepared = self.prepare("orders", facts, None)
            if prepared != request:
                raise _invalid()
        else:
            prefix, suffix = ORDER_PATH + "/", "/capture"
            if (
                not request.path.startswith(prefix)
                or not request.path.endswith(suffix)
                or request.body != "{}"
            ):
                raise _invalid()
            _order_id(request.path[len(prefix) : -len(suffix)])
        return self._exchange(
            request,
            {
                "PayPal-Request-Id": operation_id,
                "Prefer": "return=representation",
            },
        )

    def get(self, provider_order_id: str) -> dict:
        """Read the fixed same-order path without request ID or monetary retry."""
        return self._exchange(
            PaymentRequest(
                "GET", f"{ORDER_PATH}/{_order_id(provider_order_id)}", ""
            ),
            {},
        )

    def _exchange(
        self, request: PaymentRequest, headers: dict[str, str]
    ) -> dict:
        if not self._flight.acquire(blocking=False):
            raise ProviderAmbiguity("Offline exchange already active")
        try:
            if self._blocked:
                raise ProviderAmbiguity("Offline exchange unavailable")
            completed = queue.Queue(maxsize=1)
            deadline = time.monotonic() + self.timeout_seconds

            def run():
                try:
                    result = self.transport.send(
                        SANDBOX_ENDPOINT,
                        request,
                        {
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                            **headers,
                        },
                        timeout_seconds=self.timeout_seconds,
                    )
                except Exception:
                    completed.put(None)
                else:
                    completed.put(result)

            try:
                threading.Thread(target=run, daemon=True).start()
            except Exception:
                # A start failure must not leak raw resource/OS diagnostics or
                # leave the durable operation looking safely retryable. Poison
                # the instance conservatively if worker startup is uncertain.
                object.__setattr__(self, "_blocked", True)
                raise ProviderAmbiguity(
                    "Offline exchange unavailable"
                ) from None
            try:
                response = completed.get(
                    timeout=max(0, deadline - time.monotonic())
                )
            except queue.Empty:
                object.__setattr__(self, "_blocked", True)
                raise ProviderAmbiguity("Offline exchange timed out") from None
            if time.monotonic() >= deadline:
                object.__setattr__(self, "_blocked", True)
                raise ProviderAmbiguity("Offline exchange timed out")
            allowed = {200} if request.method == "GET" else {200, 201}
            if (
                type(response) is not SandboxWireResponse
                or type(response.status_code) is not int
                or response.status_code not in allowed
            ):
                raise ProviderAmbiguity("Offline exchange outcome unknown")
            try:
                document = strict_provider_json(
                    response.body,
                    max_bytes=MAX_BODY_BYTES,
                    max_depth=MAX_BODY_DEPTH,
                )
                # A valid order identity survives malformed non-identity facts.
                # Never reconstruct those facts from the reserved request.
                identity = _order_id(document.get("id"))
                try:
                    normalized = normalize_paypal_order(document)
                    if self.buyer_return_origin is not None:
                        approval_url = sandbox_approval_url(document)
                        if approval_url:
                            normalized["approval_url"] = approval_url
                except (AppError, ValueError, TypeError, UnicodeError):
                    normalized = {
                        "provider_mode": OFFLINE_MODE,
                        "provider_order_id": identity,
                    }
                if request.path != ORDER_PATH:
                    requested_id = request.path[
                        len(ORDER_PATH) + 1 :
                    ].removesuffix("/capture")
                    if normalized["provider_order_id"] != requested_id:
                        raise _invalid()
            except (AppError, ValueError, TypeError, UnicodeError):
                raise ProviderAmbiguity(
                    "Offline representation incomplete"
                ) from None
            if time.monotonic() >= deadline:
                object.__setattr__(self, "_blocked", True)
                raise ProviderAmbiguity("Offline exchange timed out")
            return normalized
        finally:
            self._flight.release()
