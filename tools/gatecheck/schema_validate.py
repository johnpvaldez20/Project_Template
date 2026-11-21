#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""JSON Schema 2020-12 subset used by the gate templates.

No third-party packages. The subset covers the keywords in
docs/governance/schemas/. A keyword outside that set is an error.
"""

from __future__ import annotations

import json
import re
from typing import Any

ANNOTATIONS = {
    "$schema",
    "$id",
    "$defs",
    "$comment",
    "title",
    "description",
    "default",
    "examples",
}

KNOWN = ANNOTATIONS | {
    "$ref",
    "type",
    "const",
    "enum",
    "pattern",
    "format",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "contains",
}

_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_URI = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:[^\s]+$")


def json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values. A boolean is not a number."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return False
        return all(json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        return all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def _is_type(instance: Any, name: str) -> bool:
    if name == "object":
        return isinstance(instance, dict)
    if name == "array":
        return isinstance(instance, list)
    if name == "string":
        return isinstance(instance, str)
    if name == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if name == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if name == "boolean":
        return isinstance(instance, bool)
    if name == "null":
        return instance is None
    return False


def _number(instance: Any) -> int | float | None:
    if isinstance(instance, bool) or not isinstance(instance, (int, float)):
        return None
    return instance


def _pointer(document: Any, ref: str) -> Any:
    body = ref[1:] if ref.startswith("#") else ref
    current = document
    for part in [piece for piece in body.split("/") if piece != ""]:
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise KeyError(ref)
        current = current[part]
    return current


class SchemaSet:
    """Schemas addressed by file name, as $ref uses them."""

    def __init__(self, documents: dict[str, Any]) -> None:
        self.documents = documents

    @classmethod
    def from_documents(cls, documents: dict[str, Any]) -> SchemaSet:
        return cls(documents)

    def resolve(self, ref: str, schema_file: str) -> tuple[Any, str]:
        if ref.startswith("#"):
            return _pointer(self.documents[schema_file], ref), schema_file
        file_part, _, fragment = ref.partition("#")
        if file_part not in self.documents:
            raise KeyError(ref)
        target = self.documents[file_part]
        if fragment:
            target = _pointer(target, "#" + fragment)
        return target, file_part

    def validate_document(self, schema_file: str, instance: Any) -> tuple[bool, list[str]]:
        errors = self._validate(instance, self.documents[schema_file], schema_file, "$")
        return (not errors, errors)

    def validate_ref(self, ref: str, instance: Any) -> list[str]:
        """Validate one instance against the schema that a file reference names."""
        file_part = ref.partition("#")[0]
        return self._validate(instance, {"$ref": ref}, file_part, "$")

    def _validate(self, instance: Any, schema: Any, schema_file: str, path: str) -> list[str]:
        if not isinstance(schema, dict):
            return [f"{path}: schema is not an object"]
        unknown = sorted(set(schema) - KNOWN)
        if unknown:
            return [f"{path}: unknown schema keyword {', '.join(unknown)}"]
        if "$ref" in schema:
            return self._validate_ref(instance, schema, schema_file, path)

        errors: list[str] = []
        if "type" in schema and not _is_type(instance, schema["type"]):
            return [f"{path}: expected type {schema['type']}"]
        if "const" in schema and not json_equal(instance, schema["const"]):
            errors.append(f"{path}: const mismatch")
        if "enum" in schema and not any(json_equal(instance, item) for item in schema["enum"]):
            errors.append(f"{path}: value is not in enum")
        errors.extend(self._validate_string(instance, schema, path))
        errors.extend(self._validate_number(instance, schema, path))
        errors.extend(self._validate_array(instance, schema, schema_file, path))
        errors.extend(self._validate_object(instance, schema, schema_file, path))
        errors.extend(self._validate_combinators(instance, schema, schema_file, path))
        return errors

    def _validate_ref(self, instance: Any, schema: dict, schema_file: str, path: str) -> list[str]:
        try:
            target, target_file = self.resolve(schema["$ref"], schema_file)
        except KeyError:
            return [f"{path}: unresolved $ref {schema['$ref']}"]
        errors = self._validate(instance, target, target_file, path)
        siblings = {key: value for key, value in schema.items() if key != "$ref" and key not in ANNOTATIONS}
        if siblings:
            errors.extend(self._validate(instance, siblings, schema_file, path))
        return errors

    def _validate_string(self, instance: Any, schema: dict, path: str) -> list[str]:
        keys = {"pattern", "format", "minLength", "maxLength"}
        if not isinstance(instance, str):
            if keys & set(schema) and "type" not in schema:
                return [f"{path}: string constraint on a non-string"]
            return []
        errors: list[str] = []
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path}: does not match pattern")
        if "format" in schema:
            fmt = schema["format"]
            if fmt == "date-time" and _DATE_TIME.fullmatch(instance) is None:
                errors.append(f"{path}: is not a date-time")
            elif fmt == "uri" and _URI.fullmatch(instance) is None:
                errors.append(f"{path}: is not a uri")
            elif fmt not in {"date-time", "uri"}:
                errors.append(f"{path}: unsupported format {fmt}")
        return errors

    def _validate_number(self, instance: Any, schema: dict, path: str) -> list[str]:
        keys = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}
        if not (keys & set(schema)):
            return []
        number = _number(instance)
        if number is None:
            if "type" in schema:
                return []
            return [f"{path}: number constraint on a non-number"]
        errors: list[str] = []
        if "minimum" in schema and number < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and number > schema["maximum"]:
            errors.append(f"{path}: above maximum")
        if "exclusiveMinimum" in schema and number <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above exclusive minimum")
        if "exclusiveMaximum" in schema and number >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: not below exclusive maximum")
        return errors

    def _validate_array(
        self, instance: Any, schema: dict, schema_file: str, path: str
    ) -> list[str]:
        keys = {"minItems", "maxItems", "uniqueItems", "items", "contains"}
        if not isinstance(instance, list):
            if keys & set(schema) and "type" not in schema:
                return [f"{path}: array constraint on a non-array"]
            return []
        errors: list[str] = []
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems") is True:
            seen = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in instance]
            if len(seen) != len(set(seen)):
                errors.append(f"{path}: items are not unique")
        if "items" in schema:
            for index, item in enumerate(instance):
                errors.extend(
                    self._validate(item, schema["items"], schema_file, f"{path}/{index}")
                )
        if "contains" in schema:
            matched = any(
                not self._validate(item, schema["contains"], schema_file, path) for item in instance
            )
            if not matched:
                errors.append(f"{path}: contains failed")
        return errors

    def _validate_object(
        self, instance: Any, schema: dict, schema_file: str, path: str
    ) -> list[str]:
        keys = {
            "required",
            "properties",
            "additionalProperties",
            "minProperties",
            "maxProperties",
        }
        if not isinstance(instance, dict):
            if keys & set(schema) and "type" not in schema:
                return [f"{path}: object constraint on a non-object"]
            return []
        errors: list[str] = []
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errors.append(f"{path}: too few properties")
        if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
            errors.append(f"{path}: too many properties")
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property {key}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            child = f"{path}/{key}"
            if key in properties:
                errors.extend(self._validate(value, properties[key], schema_file, child))
            elif additional is False:
                errors.append(f"{path}: additional property {key}")
            elif isinstance(additional, dict):
                errors.extend(self._validate(value, additional, schema_file, child))
        return errors

    def _validate_combinators(
        self, instance: Any, schema: dict, schema_file: str, path: str
    ) -> list[str]:
        errors: list[str] = []
        for index, sub in enumerate(schema.get("allOf", [])):
            errors.extend(self._validate(instance, sub, schema_file, f"{path}/allOf{index}"))
        if "anyOf" in schema:
            branches = [
                self._validate(instance, sub, schema_file, path) for sub in schema["anyOf"]
            ]
            if all(branches):
                errors.append(f"{path}: anyOf failed")
        if "oneOf" in schema:
            passed = [
                not self._validate(instance, sub, schema_file, path) for sub in schema["oneOf"]
            ]
            if sum(passed) != 1:
                errors.append(f"{path}: oneOf failed")
        if "not" in schema and not self._validate(instance, schema["not"], schema_file, path):
            errors.append(f"{path}: matched not schema")
        if "if" in schema:
            matched = not self._validate(instance, schema["if"], schema_file, path)
            branch = "then" if matched else "else"
            if branch in schema:
                errors.extend(self._validate(instance, schema[branch], schema_file, path))
        return errors


def validate(instance: Any, schema: dict) -> tuple[bool, list[str]]:
    """Validate one instance against one schema document."""
    return SchemaSet.from_documents({"root": schema}).validate_document("root", instance)
