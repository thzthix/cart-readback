"""Explicit fixture suggestions and disabled real inference boundaries."""

from typing import Protocol

from cartreadback_app.validation import AppError, integer, object_fields, string

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
        raise AppError("INVALID_PROPOSAL", "Wrong result count.", 422)
    expected = {condition["condition_id"] for condition in conditions}
    observed = set()
    for result in proposal:
        object_fields(
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
            raise AppError(
                "INVALID_PROPOSAL", "Wrong condition reference.", 422
            )
        observed.add(cid)
        if type(result["status"]) is not str or result["status"] not in {
            "match",
            "conflict",
            "unknown",
        }:
            raise AppError("INVALID_PROPOSAL", "Wrong result status.", 422)
        if type(result["explanation"]) is not str or not (
            1 <= len(result["explanation"]) <= 500
        ):
            raise AppError("INVALID_PROPOSAL", "Invalid explanation.", 422)
        string(result["explanation"], "explanation", 500)
        evidence = result["evidence"]
        if type(evidence) is not list or len(evidence) > 4:
            raise AppError("INVALID_PROPOSAL", "Invalid evidence array.", 422)
        if result["status"] != "unknown" and not evidence:
            raise AppError("INVALID_PROPOSAL", "Missing supporting span.", 422)
        for span in evidence:
            object_fields(span, {"source_id", "start", "end", "quote"})
            string(span["quote"], "quote", 1000, multiline=True)
            start = integer(span["start"], "start", 0, len(source["text"]))
            end = integer(span["end"], "end", start + 1, len(source["text"]))
            if (
                span["source_id"] != source["source_id"]
                or type(span["quote"]) is not str
                or source["text"][start:end] != span["quote"]
            ):
                raise AppError(
                    "INVALID_PROPOSAL", "Evidence span mismatch.", 422
                )
    return proposal
