"""New-product offline tests; historical SessionClose results do not apply."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from cartreadback_app.catalog import fixtures, validate_product
from cartreadback_app.inference import (
    DisabledModelAdapter,
    FixtureInferenceAdapter,
    validate_proposal,
)
from cartreadback_app.payments import (
    DisabledPayPalSandboxAdapter,
    FixturePaymentAdapter,
)
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import (
    AppError,
    canonical,
    parse_json,
    text_hash,
)


class Workflow:
    def __init__(self, service, sid=None):
        self.service = service
        self.sid = sid or service.store.session(None)[0]["sid"]
        self.result = service.bootstrap(self.sid)

    @property
    def checkout(self):
        return self.result["checkout"]

    def analyze(
        self, sku="KB-UK-C2C", layout="UK_QWERTY", cable="USB-C to USB-C"
    ):
        body = {
            "expected_revision": self.result["revision"],
            "sku_id": sku,
            "conditions": [{"kind": "layout", "value": layout}],
        }
        if cable:
            body["conditions"].append(
                {"kind": "included_cable", "value": cable}
            )
        self.result = self.service.mutate(self.sid, "analyze", body)
        return self.result

    def confirm_body(self):
        c = self.checkout
        return {
            "expected_revision": self.result["revision"],
            "review_id": c["review_id"],
            "snapshot_hash": c["snapshot_hash"],
            "confirmed_sku_id": c["sku_id"],
            "confirmed_condition_ids": [
                item["condition_id"] for item in c["conditions"]
            ],
            "acknowledged_unknown_ids": [
                item["condition_id"]
                for item in c["results"]
                if item["status"] == "unknown"
            ],
            "acknowledged_conflict_ids": [
                item["condition_id"]
                for item in c["results"]
                if item["status"] == "conflict"
            ],
        }

    def confirm(self):
        self.result = self.service.mutate(
            self.sid, "confirm", self.confirm_body()
        )
        return self.result

    def create_body(self):
        c = self.checkout
        return {
            "expected_revision": self.result["revision"],
            "review_id": c["review_id"],
            "snapshot_hash": c["snapshot_hash"],
            "confirmation_id": c["confirmation_id"],
        }

    def create(self, key=None):
        self.result = self.service.mutate(
            self.sid,
            "orders",
            self.create_body(),
            idempotency_key=key or str(uuid4()),
        )
        return self.result

    def action(self, action, **extra):
        c = self.checkout
        body = {
            "expected_revision": self.result["revision"],
            "snapshot_hash": c["snapshot_hash"],
        }
        if action == "capture":
            body.update(
                confirmation_id=c["confirmation_id"], final_confirmation=True
            )
        body.update(extra)
        self.result = self.service.mutate(
            self.sid,
            action,
            body,
            c["order"]["order_id"],
            str(uuid4()) if action == "capture" else None,
        )
        return self.result

    def ready(self):
        self.analyze()
        self.confirm()
        self.create()
        self.action("fixture-approve")
        self.action("verify")


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "db.sqlite3"
        self.store = Store(self.path)
        self.service = Service(self.store)
        self.addCleanup(lambda: self.service.close())
        self.flow = Workflow(self.service)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(AppError) as caught:
            function(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def count(self, table):
        repository = (
            self.service.payments
            if table == "fixture_provider_orders"
            else self.store
        )
        with repository.connect() as connection:
            return connection.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]

    def test_six_valid_synthetic_products_and_identical_source_baseline(self):
        catalog = fixtures()
        self.assertEqual(6, len({p["sku_id"] for p in catalog}))
        for product in catalog:
            validate_product(product)
            self.assertIn("SYNTHETIC", product["source"]["text"])
            self.assertEqual(
                text_hash(product["source"]["text"]),
                product["source"]["sha256"],
            )

    def test_happy_path_explicit_separate_approval_verify_capture(self):
        self.flow.ready()
        self.assertEqual("SERVER_RECHECKED", self.flow.checkout["state"])
        self.assertEqual([], self.provider_document()["captures"])
        self.flow.action("capture")
        self.assertEqual("COMPLETED", self.flow.checkout["state"])
        self.assertEqual(1, len(self.provider_document()["captures"]))
        self.assertEqual(2, self.count("operations"))

    def provider_document(self):
        return self.service.payments.get(
            self.flow.checkout["order"]["provider_order_id"]
        )

    def test_iso_geometry_does_not_make_de_layout_match_uk(self):
        self.flow.analyze("KB-DE-A2C")
        self.assertEqual(
            ["conflict", "conflict"],
            [r["status"] for r in self.flow.checkout["results"]],
        )

    def test_unknown_requires_exact_individual_ack_not_converted_to_match(self):
        self.flow.analyze("KB-UK-UNKNOWN")
        body = self.flow.confirm_body()
        body["acknowledged_unknown_ids"] = []
        self.assert_code(
            "ACKNOWLEDGEMENT_REQUIRED",
            self.service.mutate,
            self.flow.sid,
            "confirm",
            body,
        )
        self.flow.confirm()
        self.assertEqual("unknown", self.flow.checkout["results"][1]["status"])

    def test_conflict_kept_visible_after_ack(self):
        self.flow.analyze("KB-US-NONE")
        body = self.flow.confirm_body()
        body["acknowledged_conflict_ids"] = ["c1"]
        self.assert_code(
            "ACKNOWLEDGEMENT_REQUIRED",
            self.service.mutate,
            self.flow.sid,
            "confirm",
            body,
        )
        self.flow.confirm()
        self.assertEqual(
            ["conflict", "conflict"],
            [r["status"] for r in self.flow.checkout["results"]],
        )

    def test_contradictory_source_and_absence_are_unknown_not_match(self):
        self.flow.analyze("KB-AMBIGUOUS")
        self.assertEqual(
            ["unknown", "unknown"],
            [r["status"] for r in self.flow.checkout["results"]],
        )
        self.assertEqual(2, len(self.flow.checkout["results"][0]["evidence"]))

    def test_injected_catalog_instruction_cannot_change_condition_or_capture(
        self,
    ):
        self.flow.analyze("KB-UK-INJECT", layout="DE_QWERTZ")
        self.assertEqual("conflict", self.flow.checkout["results"][0]["status"])
        self.assertEqual(0, self.count("orders"))
        self.assertEqual(0, self.count("operations"))

    def test_condition_edits_invalidate_prior_review_and_confirmation(self):
        self.flow.analyze()
        self.flow.confirm()
        old = self.flow.create_body()
        self.flow.analyze(layout="DE_QWERTZ")
        old["expected_revision"] = self.flow.result["revision"]
        self.assert_code(
            "STALE_SNAPSHOT",
            self.service.mutate,
            self.flow.sid,
            "orders",
            old,
            idempotency_key=str(uuid4()),
        )
        self.assertIsNone(self.flow.checkout["confirmation_id"])

    def test_catalog_source_price_revision_and_model_changes_invalidate_consent(
        self,
    ):
        for kind in [
            "price",
            "source",
            "source_revision",
            "catalog_revision",
            "model",
            "prompt",
        ]:
            with self.subTest(kind=kind):
                store = Store(Path(self.temp.name) / f"{kind}.db")
                inference = FixtureInferenceAdapter()
                inference.metadata = deepcopy(inference.metadata)
                service = Service(store, inference)
                flow = Workflow(service)
                flow.analyze()
                flow.confirm()
                product = fixtures()[0]
                if kind == "price":
                    product["price_minor"] += 1
                elif kind == "source":
                    product["source"]["text"] += "\nNew authoritative text."
                    product["source"]["sha256"] = text_hash(
                        product["source"]["text"]
                    )
                elif kind == "source_revision":
                    product["source"]["revision"] += 1
                elif kind == "catalog_revision":
                    product["catalog_revision"] += 1
                else:
                    inference.metadata[f"{kind}_version"] += "-new"
                store.replace_product(product)
                self.assert_code("STALE_SNAPSHOT", flow.create)
                restored = service.bootstrap(flow.sid)["checkout"]
                self.assertTrue(restored["stale"])
                self.assertIsNone(restored["confirmation_id"])

    def test_source_change_after_verify_cannot_capture(self):
        self.flow.ready()
        p = fixtures()[0]
        p["price_minor"] += 10
        self.store.replace_product(p)
        self.assert_code("STALE_SNAPSHOT", self.flow.action, "capture")
        self.assertEqual(1, self.count("operations"))

    def test_no_reanalysis_or_new_checkout_after_any_created_order(self):
        self.flow.ready()
        self.assert_code("INVALID_STATE", self.flow.analyze)
        self.assertEqual(1, self.count("orders"))

    def test_no_approval_or_capture_from_page_visit_or_unapproved_verify(self):
        self.flow.analyze()
        self.flow.confirm()
        self.flow.create()
        self.service.bootstrap(self.flow.sid)
        self.assert_code("ORDER_NOT_APPROVED", self.flow.action, "verify")
        self.assert_code("INVALID_STATE", self.flow.action, "capture")
        self.assertEqual("CREATED", self.provider_document()["status"])

    def test_final_confirmation_is_exact_true(self):
        self.flow.ready()
        for value in [False, 1, "true", None, [], {}]:
            self.assert_code(
                "ACKNOWLEDGEMENT_REQUIRED",
                self.flow.action,
                "capture",
                final_confirmation=value,
            )
        self.assertEqual(1, self.count("operations"))

    def test_money_and_provider_fields_cannot_be_client_supplied(self):
        self.flow.analyze()
        self.flow.confirm()
        for field, value in [
            ("amount", 1),
            ("currency", "JPY"),
            ("quantity", 2),
            ("owner", "other"),
            ("provider_order_id", "fake"),
        ]:
            body = self.flow.create_body() | {field: value}
            self.assert_code(
                "INVALID_FIELDS",
                self.service.mutate,
                self.flow.sid,
                "orders",
                body,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(0, self.count("orders"))

    def test_bool_float_money_and_source_digest_corruption_rejected(self):
        for field, value in [
            ("price_minor", True),
            ("price_minor", 79.0),
            ("price_minor", -1),
            ("quantity", True),
            ("currency", "EUR"),
        ]:
            product = fixtures()[0]
            product[field] = value
            with self.assertRaises(AppError):
                self.store.replace_product(product)
        product = fixtures()[0]
        product["source"]["sha256"] = "0" * 64
        self.assert_code("INVALID_CATALOG", self.store.replace_product, product)

    def test_foreign_owner_and_order_cannot_be_used(self):
        self.flow.ready()
        other = Workflow(self.service)
        body = {
            "expected_revision": 0,
            "snapshot_hash": self.flow.checkout["snapshot_hash"],
        }
        self.assert_code(
            "NOT_FOUND",
            self.service.mutate,
            other.sid,
            "verify",
            body,
            self.flow.checkout["order"]["order_id"],
        )

    def test_idempotency_conflict_and_fresh_keys_do_not_duplicate(self):
        self.flow.analyze()
        self.flow.confirm()
        body = self.flow.create_body()
        key = str(uuid4())
        self.flow.create(key)
        same = body | {"expected_revision": self.flow.result["revision"]}
        result = self.service.mutate(
            self.flow.sid, "orders", same, idempotency_key=key
        )
        self.assertEqual(self.flow.result["revision"], result["revision"])
        forged = same | {"confirmation_id": "forged"}
        self.assert_code(
            "IDEMPOTENCY_CONFLICT",
            self.service.mutate,
            self.flow.sid,
            "orders",
            forged,
            idempotency_key=key,
        )
        self.assert_code(
            "INVALID_STATE",
            self.service.mutate,
            self.flow.sid,
            "orders",
            same,
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(1, self.count("fixture_provider_orders"))

    def test_simultaneous_create_and_capture_have_single_business_operations(
        self,
    ):
        self.flow.analyze()
        self.flow.confirm()
        body = self.flow.create_body()

        def create(_):
            try:
                return self.service.mutate(
                    self.flow.sid, "orders", body, idempotency_key=str(uuid4())
                )
            except AppError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(create, range(12)))
        self.assertEqual(1, sum(isinstance(r, dict) for r in results))
        self.flow.result = self.service.bootstrap(self.flow.sid)
        self.flow.action("fixture-approve")
        self.flow.action("verify")
        body = {
            "expected_revision": self.flow.result["revision"],
            "snapshot_hash": self.flow.checkout["snapshot_hash"],
            "confirmation_id": self.flow.checkout["confirmation_id"],
            "final_confirmation": True,
        }
        order_id = self.flow.checkout["order"]["order_id"]

        def capture(_):
            try:
                return self.service.mutate(
                    self.flow.sid, "capture", body, order_id, str(uuid4())
                )
            except AppError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(capture, range(12)))
        self.assertEqual(1, sum(isinstance(r, dict) for r in results))
        self.assertEqual(2, self.count("operations"))
        self.assertEqual(1, len(self.provider_document()["captures"]))

    def test_timeout_after_capture_reconciles_same_order_without_retry(self):
        self.service.payments = FixturePaymentAdapter(
            "capture_timeout_after_success"
        )
        self.flow.ready()
        self.flow.action("capture")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assert_code("INVALID_STATE", self.flow.action, "capture")
        self.assert_code("INVALID_STATE", self.flow.analyze)
        self.service.close()
        restarted = Service(Store(self.path))
        self.flow = Workflow(restarted, self.flow.sid)
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.flow.action("reconcile")
        self.assertEqual("COMPLETED", self.flow.checkout["state"])
        self.assertEqual(1, self.count("fixture_provider_orders"))
        self.assertEqual(2, self.count("operations"))

    def test_timeout_before_completion_stays_unknown_after_approved_lookup(
        self,
    ):
        self.service.payments = FixturePaymentAdapter(
            "capture_timeout_before_success"
        )
        self.flow.ready()
        self.flow.action("capture")
        for _ in range(3):
            self.flow.action("reconcile")
            self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assert_code("INVALID_STATE", self.flow.action, "capture")
        self.assertEqual(2, self.count("operations"))

    def test_create_timeout_has_local_id_but_no_invented_provider_lookup(self):
        self.service.payments = FixturePaymentAdapter(
            "create_timeout_after_success"
        )
        self.flow.analyze()
        self.flow.confirm()
        self.flow.create()
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertIsNone(self.flow.checkout["order"]["provider_order_id"])
        self.flow.action("reconcile")
        self.assertEqual(
            "CREATE_OUTCOME_UNKNOWN",
            self.flow.checkout["order"]["reconciliation_code"],
        )
        self.assertEqual(1, self.count("fixture_provider_orders"))

    def test_pending_capture_is_not_completed(self):
        self.service.payments = FixturePaymentAdapter("capture_pending")
        self.flow.ready()
        self.flow.action("capture")
        self.flow.action("reconcile")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])

    def test_crash_after_durable_capture_reservation_requires_reconciliation(
        self,
    ):
        class CrashProvider(FixturePaymentAdapter):
            def capture(self, provider_order_id, request_id):
                raise SystemExit("synthetic process failure before observation")

        self.flow.ready()
        self.service.payments = CrashProvider()
        with self.assertRaises(SystemExit):
            self.flow.action("capture")
        self.service.close()
        self.flow = Workflow(Service(Store(self.path)), self.flow.sid)
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.flow.action("reconcile")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assert_code("INVALID_STATE", self.flow.action, "capture")
        self.assertEqual(2, self.count("operations"))

    def test_mutated_remote_order_rechecked_before_capture(self):
        self.flow.ready()
        with self.service.payments.connect() as connection:
            doc = self.service.payments.get(
                self.flow.checkout["order"]["provider_order_id"]
            )
            doc["amount_minor"] = 1
            connection.execute(
                "UPDATE fixture_provider_orders SET document = ?",
                (canonical(doc),),
            )
        self.flow.action("capture")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertEqual(1, self.count("operations"))

    def test_invalid_proposal_is_blocked_and_cannot_confirm(self):
        class BadAdapter(FixtureInferenceAdapter):
            def propose(self, source, conditions):
                result = super().propose(source, conditions)
                result[0]["evidence"][0]["end"] = 999999
                return result

        self.service.inference = BadAdapter()
        self.flow.analyze()
        self.assertEqual("ANALYSIS_BLOCKED", self.flow.checkout["state"])
        self.assertIsNone(self.flow.checkout["snapshot_hash"])
        self.assertEqual(0, self.count("orders"))

    def test_unicode_codepoint_spans_and_malformed_spans(self):
        p = fixtures()[0]
        p["source"]["text"] = "⌨️🧪\n" + p["source"]["text"]
        p["source"]["sha256"] = text_hash(p["source"]["text"])
        self.store.replace_product(p)
        self.flow.analyze()
        result = self.flow.checkout["results"][0]
        span = result["evidence"][0]
        self.assertEqual(
            span["quote"], p["source"]["text"][span["start"] : span["end"]]
        )
        for value in [True, 1.0, -1, 99999]:
            bad = deepcopy(self.flow.checkout["results"])
            bad[0]["evidence"][0]["start"] = value
            with self.assertRaises(AppError):
                validate_proposal(
                    p["source"], self.flow.checkout["conditions"], bad
                )

    def test_real_adapters_are_explicitly_disabled_without_network_or_credentials(
        self,
    ):
        self.assert_code(
            "MODEL_UNAVAILABLE", DisabledModelAdapter().propose, {}, []
        )
        self.assert_code(
            "PAYPAL_UNAVAILABLE", DisabledPayPalSandboxAdapter().create
        )

    def test_unvalidated_fault_scenarios_never_crash_typeerror(self):
        for value in [[], {}, True, 4, "unknown"]:
            self.assert_code(
                "INVALID_FIXTURE_FAULT", FixturePaymentAdapter, value
            )

    def test_strict_json_nesting_duplicates_constants_and_types(self):
        for body in [
            b'{"x":1,"x":2}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b"[]",
            b'{"x":\xff}',
            b'{"x":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}",
        ]:
            with self.assertRaises(AppError):
                parse_json(body)
        self.assertEqual(
            {"text": '[[["'}, parse_json(json.dumps({"text": '[[["'}).encode())
        )


if __name__ == "__main__":
    unittest.main()
