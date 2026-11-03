"""Offline checks for prepared prompts; never invokes a model or payment."""

import copy
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from cartreadback_app.inference import validate_proposal  # noqa: E402
from cartreadback_app.validation import AppError  # noqa: E402


def digest(path: Path) -> str:
    """Return SHA-256 of exact file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """Validate public artifacts and report structural limits honestly."""
    config = json.loads((ROOT / "template.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(config["input_schema"])
    input_validator = Draft202012Validator(config["input_schema"])
    output_validator = Draft202012Validator(schema)
    assert config["prompt_version"] == "cartreadback-prompt-v1"
    assert config["status"] == "prepared-not-integrated-not-model-tested"
    assert config["selected_candidate"] == "B"
    assert len(config["public_dev_examples"]) == 2
    assert config["user_template"].count("{{request_json}}") == 1
    assert config["user_template"].count("{{output_schema_json}}") == 1
    system = (ROOT / "readback-system.txt").read_text(encoding="utf-8")
    common = config["comparison"]["common_system"]
    assert system.startswith(common + "\n\nEVIDENCE DECISION CONTRACT\n")
    arm_texts = {
        "A": common
        + "\n\n"
        + config["comparison"]["arms"]["A"]["system_suffix"]
        + "\n",
        "B": system,
        "C": common + "\n",
    }
    assert len(set(arm_texts.values())) == 3
    for arm, text in arm_texts.items():
        assert (ROOT / f"arm-{arm}-system.txt").read_text(
            encoding="utf-8"
        ) == text
    assert (ROOT / "readback-user-template.txt").read_text(
        encoding="utf-8"
    ) == config["user_template"] + "\n"
    assert all(
        value is None
        for key, value in config["comparison"]["run_settings"].items()
        if key != "notes"
    )

    positive_checks = []
    for example in config["public_dev_examples"]:
        request = example["input"]
        source = request["source"]
        conditions = request["conditions"]
        expected = example["expected_output"]
        input_validator.validate(request)
        assert len({item["condition_id"] for item in conditions}) == len(
            conditions
        )
        assert len({item["kind"] for item in conditions}) == len(conditions)
        assert (
            source["sha256"]
            == hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
        )
        assert (
            json.loads(json.dumps(request, ensure_ascii=False, allow_nan=False))
            == request
        )
        output_validator.validate(expected)
        validate_proposal(source, conditions, expected)
        positive_checks.append(example["id"])

    first = config["public_dev_examples"][0]
    source = first["input"]["source"]
    conditions = first["input"]["conditions"]
    expected = first["expected_output"]
    invalid = {}

    def variant(name: str, edit) -> None:
        candidate = copy.deepcopy(expected)
        edit(candidate)
        invalid[name] = candidate

    variant("missing_match_evidence", lambda p: p[0].update(evidence=[]))
    variant("uppercase_status", lambda p: p[0].update(status="MATCH"))
    variant("extra_payment_field", lambda p: p[0].update(capture=True))
    variant(
        "wrong_source_id",
        lambda p: p[0]["evidence"][0].update(source_id="foreign"),
    )
    variant("boolean_offset", lambda p: p[0]["evidence"][0].update(start=True))
    variant("reversed_span", lambda p: p[0]["evidence"][0].update(end=1))
    variant(
        "wrong_exact_quote",
        lambda p: p[0]["evidence"][0].update(quote="Layout: DE QWERTZ."),
    )
    variant("duplicate_condition_id", lambda p: p[1].update(condition_id="c1"))
    variant(
        "foreign_condition_id", lambda p: p[1].update(condition_id="foreign")
    )
    variant(
        "control_in_explanation",
        lambda p: p[0].update(explanation="bad\ncontrol"),
    )
    invalid["missing_condition"] = copy.deepcopy(expected[:1])
    shifted = copy.deepcopy(expected)
    shifted[0]["evidence"][0]["start"] += 1
    shifted[0]["evidence"][0]["end"] += 1
    invalid["utf16_instead_of_codepoint_after_astral_emoji"] = shifted

    rejections = {}
    for name, candidate in invalid.items():
        schema_rejected = bool(list(output_validator.iter_errors(candidate)))
        try:
            validate_proposal(source, conditions, candidate)
        except AppError:
            backend_rejected = True
        else:
            backend_rejected = False
        assert backend_rejected, name
        rejections[name] = {
            "local_schema_rejected": schema_rejected,
            "existing_validator_rejected": backend_rejected,
        }

    false_match = copy.deepcopy(expected)
    false_match[1]["status"] = "match"
    false_match[1]["explanation"] = "The source proves a cable is included."
    output_validator.validate(false_match)
    validate_proposal(source, conditions, false_match)

    dependency_paths = [
        ROOT.parent / "API_CONTRACT.md",
        ROOT.parent.parent / "PROJECT_BRIEF.md",
        ROOT.parent / "cartreadback_app" / "inference.py",
        ROOT.parent / "cartreadback_app" / "validation.py",
    ]
    output = {
        "status": "offline-artifact-preflight-passed-not-model-evaluation",
        "prompt_version": config["prompt_version"],
        "command": "PYTHONDONTWRITEBYTECODE=1 python prompts/verify_artifacts.py",
        "network_calls": 0,
        "real_model_calls": 0,
        "payment_calls": 0,
        "evaluator_corpus_read": False,
        "jsonschema_version": importlib.metadata.version("jsonschema"),
        "schemas_valid": ["schema.json", "template.json#/input_schema"],
        "public_dev_examples_passed": positive_checks,
        "malformed_output_cases_rejected": rejections,
        "known_semantic_gap": {
            "observed": "Author-constructed synthetic false cable match with exact no-cable quote passes schema and existing span validator.",
            "expected_limit_observed": True,
            "meaning": "Structural checks do not establish entailment. No model produced this output.",
        },
        "artifact_sha256": {
            name: digest(ROOT / name)
            for name in [
                "readback-system.txt",
                "readback-user-template.txt",
                "arm-A-system.txt",
                "arm-B-system.txt",
                "arm-C-system.txt",
                "template.json",
                "schema.json",
                "EVALUATION_PLAN.md",
                "verify_artifacts.py",
            ]
        },
        "contract_dependency_sha256": {
            str(path.relative_to(ROOT.parent.parent)): digest(path)
            for path in dependency_paths
        },
        "arm_system_sha256": {
            arm: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for arm, value in arm_texts.items()
        },
        "not_run": [
            "real inference",
            "provider schema acceptance",
            "A/B/C comparison",
            "holdout scoring",
            "PayPal sandbox",
            "browser/customer study",
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
