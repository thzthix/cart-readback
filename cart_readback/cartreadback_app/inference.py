"""Explicit fixture suggestions and disabled real inference boundaries."""

from typing import Protocol

from cartreadback_app.validation import AppError, integer, object_fields, string

PROPOSAL_RULES = frozenset(
    {
        "RULE_RESPONSE_ID",
        "RULE_CONDITION_REFERENCE",
        "RULE_EXPLANATION",
        "RULE_CONTENT",
        "RULE_UNCLASSIFIED",
        "RULE_OUTPUT_JSON",
        "RULE_SPAN_SOURCE",
        "RULE_SPAN_FIELDS",
        "RULE_PART",
        "RULE_PREPARED_REQUEST",
        "RULE_EVIDENCE_REQUIRED",
        "RULE_ORDER",
        "RULE_RESULT_STATUS",
        "RULE_CANDIDATE_INDEX",
        "RULE_EVIDENCE_ARRAY",
        "RULE_SIGNATURE",
        "RULE_SPAN_END",
        "RULE_ENVELOPE_JSON",
        "RULE_SPAN_QUOTE_FORMAT",
        "RULE_RESULT_FIELDS",
        "RULE_SPAN_START",
        "RULE_SPAN_QUOTE",
        "RULE_ROOT_FIELDS",
        "RULE_MODEL_VERSION",
        "RULE_COUNT",
        "RULE_PARTS",
    }
)


def rejection_rule(error):
    """Return one fixed rule label, never error text or proposal values."""
    if type(error) is AppError:
        value = getattr(error, "rejection_rule", None)
        if type(value) is str and value in PROPOSAL_RULES:
            return next(item for item in PROPOSAL_RULES if item == value)
    return None


def proposal_rejection(rule):
    """Annotate an unchanged INVALID_PROPOSAL verdict with a fixed rule."""
    error = AppError("INVALID_PROPOSAL", "Invalid proposal.", 422)
    error.rejection_rule = (
        rule
        if type(rule) is str and rule in PROPOSAL_RULES
        else "RULE_UNCLASSIFIED"
    )
    return error


def _at_proposal_rule(rule, validator, *args, **kwargs):
    try:
        return validator(*args, **kwargs)
    except AppError as error:
        # Do not annotate a possibly reused exception owned by a validator.
        annotated = AppError(error.code, error.message, error.status)
        annotated.rejection_rule = rule
        raise annotated from None


FIXTURE_MODEL = {
    "provider": "synthetic-local-fixture",
    "model_version": "no-model",
    "prompt_version": "cartreadback-evidence-v1",
    "adapter_version": "fixture-patterns-v1",
    "validator_version": "strict-spans-v1",
    "is_fixture": True,
}


class InferenceAdapter(Protocol):
    """An untrusted proposal provider with no order/payment capability."""

    metadata: dict

    def propose(self, source: dict, conditions: list[dict]) -> list[dict]:
        """Return typed proposed results over exact source text."""
        ...


class DisabledModelAdapter:
    """No real model implementation or credentials are available/loaded."""

    metadata = {"provider": "disabled", "is_fixture": False}

    def propose(self, source: dict, conditions: list[dict]) -> list[dict]:
        """Fail explicitly instead of making paid calls or impersonating AI."""
        raise AppError(
            "MODEL_UNAVAILABLE", "Real model adapter is disabled.", 503
        )


class FixtureInferenceAdapter:
    """Match only authored fixture claim lines; this is not AI inference."""

    metadata = FIXTURE_MODEL

    def propose(self, source: dict, conditions: list[dict]) -> list[dict]:
        """Produce repeatable synthetic proposals, never acting on instructions."""
        results = []
        patterns = {
            "layout": {
                "UK_QWERTY": "Layout: UK_QWERTY.",
                "DE_QWERTZ": "Layout: DE_QWERTZ.",
                "US_QWERTY": "Layout: US_QWERTY.",
            },
            "included_cable": {
                "USB-C to USB-C": "Included cable: USB-C to USB-C.",
                "USB-A to USB-C": "Included cable: USB-A to USB-C.",
                "none": "Included cable: none.",
            },
        }
        for condition in conditions:
            facts = []
            for fact, quote in patterns[condition["kind"]].items():
                # Recognize whole authored lines only, not quoted instructions.
                if quote in source["text"].splitlines():
                    start = source["text"].index(quote)
                    facts.append(
                        (
                            fact,
                            {
                                "source_id": source["source_id"],
                                "start": start,
                                "end": start + len(quote),
                                "quote": quote,
                            },
                        )
                    )
                elif (
                    condition["kind"] == "included_cable"
                    and fact == "none"
                    and "Included cable: none. Cable sold separately."
                    in source["text"].splitlines()
                ):
                    start = source["text"].index(quote)
                    facts.append(
                        (
                            fact,
                            {
                                "source_id": source["source_id"],
                                "start": start,
                                "end": start + len(quote),
                                "quote": quote,
                            },
                        )
                    )
            if len(facts) != 1:
                status = "unknown"
                explanation = (
                    "The source contains contradictory explicit facts."
                    if facts
                    else "The source does not explicitly state this fact."
                )
            else:
                actual = facts[0][0]
                matches = actual == condition["value"] or (
                    condition["value"] == "any cable" and actual != "none"
                )
                status = "match" if matches else "conflict"
                explanation = f"The explicit source states {actual}."
            results.append(
                {
                    "condition_id": condition["condition_id"],
                    "status": status,
                    "explanation": explanation,
                    "evidence": [span for _, span in facts],
                }
            )
        return results


def validate_proposal(
    source: dict,
    conditions: list[dict],
    proposal: object,
) -> list[dict]:
    """Validate schema and exact spans, not unrestricted semantic correctness."""
    if type(proposal) is not list or len(proposal) != len(conditions):
        raise proposal_rejection("RULE_COUNT")
    expected = {condition["condition_id"] for condition in conditions}
    observed = set()
    for result in proposal:
        _at_proposal_rule(
            "RULE_RESULT_FIELDS",
            object_fields,
            result,
            {
                "condition_id",
                "status",
                "explanation",
                "evidence",
            },
        )
        cid = result["condition_id"]
        if type(cid) is not str or cid not in expected or cid in observed:
            raise proposal_rejection("RULE_CONDITION_REFERENCE")
        observed.add(cid)
        if type(result["status"]) is not str or result["status"] not in {
            "match",
            "conflict",
            "unknown",
        }:
            raise proposal_rejection("RULE_RESULT_STATUS")
        if type(result["explanation"]) is not str or not (
            1 <= len(result["explanation"]) <= 500
        ):
            raise proposal_rejection("RULE_EXPLANATION")
        _at_proposal_rule(
            "RULE_EXPLANATION",
            string,
            result["explanation"],
            "explanation",
            500,
        )
        evidence = result["evidence"]
        if type(evidence) is not list or len(evidence) > 4:
            raise proposal_rejection("RULE_EVIDENCE_ARRAY")
        if result["status"] != "unknown" and not evidence:
            raise proposal_rejection("RULE_EVIDENCE_REQUIRED")
        for span in evidence:
            _at_proposal_rule(
                "RULE_SPAN_FIELDS",
                object_fields,
                span,
                {"source_id", "start", "end", "quote"},
            )
            _at_proposal_rule(
                "RULE_SPAN_QUOTE_FORMAT",
                string,
                span["quote"],
                "quote",
                1000,
                multiline=True,
            )
            start = _at_proposal_rule(
                "RULE_SPAN_START",
                integer,
                span["start"],
                "start",
                0,
                len(source["text"]),
            )
            end = _at_proposal_rule(
                "RULE_SPAN_END",
                integer,
                span["end"],
                "end",
                start + 1,
                len(source["text"]),
            )
            if span["source_id"] != source["source_id"]:
                raise proposal_rejection("RULE_SPAN_SOURCE")
            if (
                type(span["quote"]) is not str
                or source["text"][start:end] != span["quote"]
            ):
                raise proposal_rejection("RULE_SPAN_QUOTE")
    return proposal
