"""Validation for declarative, non-authoritative connected-agent manifests."""

from __future__ import annotations

import json
import math
import re
from typing import Any

MANIFEST_SCHEMA_VERSION = 1
SUPPORTED_AGENT_PROTOCOLS = frozenset({"openai-chat-completions"})
MAX_MANIFEST_BYTES = 32_768
MAX_CAPABILITIES = 32

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PROPERTY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_SCHEMA_TYPES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)
_SCHEMA_KEYS = frozenset(
    {
        "type",
        "description",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }
)


class ManifestValidationError(ValueError):
    """Raised when an agent manifest does not satisfy the supported contract."""


def validate_capability_payload(schema: dict[str, Any], value: Any) -> None:
    """Validate a JSON payload against the manifest's supported schema subset."""
    try:
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ManifestValidationError("capability payload must contain valid JSON values") from exc
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ManifestValidationError("capability payload exceeds the 32768-byte limit")

    def check(current_schema: dict[str, Any], current: Any, path: str) -> None:
        schema_type = current_schema["type"]
        matches = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "number": lambda item: isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "null": lambda item: item is None,
        }[schema_type](current)
        if not matches:
            raise ManifestValidationError(f"{path} must have type {schema_type}")

        if "enum" in current_schema:
            enum_match = any(
                (isinstance(current, (int, float)) and not isinstance(current, bool)
                 and isinstance(item, (int, float)) and not isinstance(item, bool)
                 and current == item)
                or (type(current) is type(item) and current == item)
                for item in current_schema["enum"]
            )
            if not enum_match:
                raise ManifestValidationError(f"{path} is not an allowed enum value")

        if schema_type == "object":
            properties = current_schema.get("properties", {})
            required = current_schema.get("required", [])
            missing = set(required) - current.keys()
            if missing:
                raise ManifestValidationError(f"{path} is missing required properties")
            if not current_schema.get("additionalProperties", False):
                extra = current.keys() - properties.keys()
                if extra:
                    raise ManifestValidationError(f"{path} contains unsupported properties")
            for key, child in current.items():
                if key in properties:
                    check(properties[key], child, f"{path}.{key}")
        elif schema_type == "array":
            if len(current) < current_schema.get("minItems", 0):
                raise ManifestValidationError(f"{path} has fewer than minItems")
            if len(current) > current_schema.get("maxItems", 100_000):
                raise ManifestValidationError(f"{path} has more than maxItems")
            for index, child in enumerate(current):
                check(current_schema["items"], child, f"{path}[{index}]")
        elif schema_type == "string":
            if len(current) < current_schema.get("minLength", 0):
                raise ManifestValidationError(f"{path} is shorter than minLength")
            if len(current) > current_schema.get("maxLength", 100_000):
                raise ManifestValidationError(f"{path} is longer than maxLength")
        elif schema_type in {"number", "integer"}:
            if "minimum" in current_schema and current < current_schema["minimum"]:
                raise ManifestValidationError(f"{path} is below minimum")
            if "maximum" in current_schema and current > current_schema["maximum"]:
                raise ManifestValidationError(f"{path} is above maximum")

    check(schema, value, "payload")


def _bounded_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ManifestValidationError(f"{field} must be a non-empty string of at most {limit} characters")
    return value.strip()


def _validate_json_schema(
    value: Any, *, root: bool, depth: int, budget: list[int]
) -> dict[str, Any]:
    budget[0] += 1
    if budget[0] > 128 or depth > 8:
        raise ManifestValidationError("manifest schemas exceed the supported complexity limit")
    if not isinstance(value, dict) or set(value) - _SCHEMA_KEYS:
        raise ManifestValidationError("capability schemas must use supported JSON Schema fields")

    schema_type = value.get("type")
    if (
        not isinstance(schema_type, str)
        or schema_type not in _SCHEMA_TYPES
        or (root and schema_type != "object")
    ):
        expected = "object" if root else "a supported JSON Schema type"
        raise ManifestValidationError(f"capability schema root must have type {expected}")

    result: dict[str, Any] = {"type": schema_type}
    description = value.get("description")
    if description is not None:
        result["description"] = _bounded_text(description, "schema description", 256)

    enum = value.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum or len(enum) > 64:
            raise ManifestValidationError("schema enum must contain 1 to 64 values")
        if any(not (item is None or isinstance(item, (str, int, float, bool))) for item in enum):
            raise ManifestValidationError("schema enum values must be JSON scalars")
        if any(isinstance(item, float) and not math.isfinite(item) for item in enum):
            raise ManifestValidationError("schema enum values must be finite")
        result["enum"] = enum

    if schema_type == "object":
        properties = value.get("properties", {})
        if not isinstance(properties, dict) or len(properties) > 32:
            raise ManifestValidationError("object schema properties must be an object with at most 32 entries")
        normalized_properties: dict[str, Any] = {}
        for name, child in properties.items():
            if not isinstance(name, str) or not _PROPERTY_NAME.fullmatch(name):
                raise ManifestValidationError("schema property names must be simple identifiers")
            normalized_properties[name] = _validate_json_schema(
                child, root=False, depth=depth + 1, budget=budget
            )
        result["properties"] = normalized_properties
        required = value.get("required", [])
        if (
            not isinstance(required, list)
            or len(required) > len(normalized_properties)
            or any(not isinstance(item, str) for item in required)
            or len(required) != len(set(required))
            or not set(required).issubset(normalized_properties)
        ):
            raise ManifestValidationError("schema required entries must name declared properties")
        result["required"] = required
        additional = value.get("additionalProperties", False)
        if not isinstance(additional, bool):
            raise ManifestValidationError("additionalProperties must be a boolean")
        result["additionalProperties"] = additional
    elif schema_type == "array":
        if "items" not in value:
            raise ManifestValidationError("array schemas require an items schema")
        result["items"] = _validate_json_schema(
            value["items"], root=False, depth=depth + 1, budget=budget
        )

    if schema_type in {"string", "array"}:
        lower_key, upper_key = (
            ("minLength", "maxLength") if schema_type == "string" else ("minItems", "maxItems")
        )
        lower = value.get(lower_key)
        upper = value.get(upper_key)
        for key, bound in ((lower_key, lower), (upper_key, upper)):
            if bound is not None and (
                isinstance(bound, bool) or not isinstance(bound, int) or not 0 <= bound <= 100_000
            ):
                raise ManifestValidationError(f"{key} must be an integer between 0 and 100000")
        if lower is not None and upper is not None and lower > upper:
            raise ManifestValidationError(f"{lower_key} cannot exceed {upper_key}")
        if lower is not None:
            result[lower_key] = lower
        if upper is not None:
            result[upper_key] = upper

    if schema_type in {"number", "integer"}:
        lower = value.get("minimum")
        upper = value.get("maximum")
        for key, bound in (("minimum", lower), ("maximum", upper)):
            if bound is not None and (
                isinstance(bound, bool)
                or not isinstance(bound, (int, float))
                or (isinstance(bound, float) and not math.isfinite(bound))
            ):
                raise ManifestValidationError(f"{key} must be a finite number")
        if lower is not None and upper is not None and lower > upper:
            raise ManifestValidationError("minimum cannot exceed maximum")
        if lower is not None:
            result["minimum"] = lower
        if upper is not None:
            result["maximum"] = upper

    return result


def validate_agent_manifest(value: Any) -> dict[str, Any]:
    """Validate and normalize the supported version-1 connected-agent manifest.

    Manifests describe peer claims. They do not grant permissions or authorize
    egress, and are not proof that the remote endpoint implements a capability.
    """
    if not isinstance(value, dict):
        raise ManifestValidationError("agent manifest must be an object")
    try:
        encoded_input = json.dumps(
            value, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ManifestValidationError("agent manifest must contain valid JSON values") from exc
    if len(encoded_input) > MAX_MANIFEST_BYTES:
        raise ManifestValidationError("agent manifest exceeds the 32768-byte limit")
    allowed_keys = {
        "schema_version",
        "agent_id",
        "name",
        "version",
        "protocol",
        "description",
        "capabilities",
    }
    if set(value) - allowed_keys:
        raise ManifestValidationError("agent manifest contains unsupported fields")
    version = value.get("schema_version")
    if isinstance(version, bool) or version != MANIFEST_SCHEMA_VERSION:
        raise ManifestValidationError(
            f"unsupported agent manifest schema_version {version!r}"
        )

    agent_id = _bounded_text(value.get("agent_id"), "agent_id", 128)
    if not _IDENTIFIER.fullmatch(agent_id):
        raise ManifestValidationError("agent_id must be a simple identifier")
    protocol = _bounded_text(value.get("protocol"), "protocol", 64)
    if protocol not in SUPPORTED_AGENT_PROTOCOLS:
        raise ManifestValidationError(f"unsupported agent protocol {protocol!r}")

    capabilities = value.get("capabilities")
    if not isinstance(capabilities, list) or len(capabilities) > MAX_CAPABILITIES:
        raise ManifestValidationError(
            f"capabilities must be a list of at most {MAX_CAPABILITIES} entries"
        )
    normalized_capabilities = []
    seen_names: set[str] = set()
    schema_budget = [0]
    for capability in capabilities:
        if not isinstance(capability, dict) or set(capability) - {
            "name",
            "description",
            "input_schema",
            "output_schema",
        }:
            raise ManifestValidationError("each capability must use the supported manifest fields")
        name = _bounded_text(capability.get("name"), "capability name", 64)
        if not _IDENTIFIER.fullmatch(name) or name in seen_names:
            raise ManifestValidationError("capability names must be unique simple identifiers")
        seen_names.add(name)
        normalized = {"name": name}
        description = capability.get("description")
        if description is not None:
            normalized["description"] = _bounded_text(description, "capability description", 256)
        for key in ("input_schema", "output_schema"):
            normalized[key] = _validate_json_schema(  # type: ignore[assignment]
                capability.get(key), root=False, depth=0, budget=schema_budget
            )
        normalized_capabilities.append(normalized)

    result = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "agent_id": agent_id,
        "name": _bounded_text(value.get("name"), "name", 128),
        "version": _bounded_text(value.get("version"), "version", 64),
        "protocol": protocol,
        "capabilities": normalized_capabilities,
    }
    if "description" in value:
        result["description"] = _bounded_text(value["description"], "description", 512)
    try:
        encoded = json.dumps(result, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ManifestValidationError("agent manifest must contain valid JSON values") from exc
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ManifestValidationError("agent manifest exceeds the 32768-byte limit")
    return result
