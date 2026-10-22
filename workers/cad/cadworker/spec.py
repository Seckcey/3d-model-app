"""FeatureSpec loading, schema validation and value resolution.

A spec is untrusted data. It is validated against the JSON schema, every
feature type must be on the allowlist, and numbers are bounded before any
geometry is built. Values may reference dimensions; a *variant* decides
whether a referenced dimension resolves to its nominal or its mid-tolerance
value.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jsonschema

SCHEMA_PATHS = [
    Path(__file__).resolve().parent / "schema" / "feature-spec-1.schema.json",
    Path(__file__).resolve().parents[3] / "packages" / "feature-spec" / "schema" / "feature-spec-1.schema.json",
]
VARIANTS = ("nominal", "mid_tolerance")
MAX_LENGTH = {"in": 120.0, "mm": 3000.0}
MM_PER = {"in": 25.4, "mm": 1.0}


class SpecError(ValueError):
    """The spec is invalid or asks for something this engine does not support."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@lru_cache(maxsize=1)
def schema() -> dict:
    for path in SCHEMA_PATHS:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("feature-spec schema not found")


def validate(spec: dict) -> None:
    validator = jsonschema.Draft202012Validator(schema())
    errors = sorted(validator.iter_errors(spec), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "(root)"
        raise SpecError("invalid_spec", f"{where}: {first.message}")
    dims = spec["dimensions"]
    for feature in spec["features"]:
        for ref in _dim_refs(feature):
            if ref not in dims:
                raise SpecError("invalid_spec", f"{feature['id']}: unknown dimension {ref}")
    ids = [f["id"] for f in spec["features"]]
    if len(ids) != len(set(ids)):
        raise SpecError("invalid_spec", "feature IDs must be unique")
    base = spec["features"][0]["type"]
    expected_base = "turned_profile" if spec["family"] == "turned" else "block"
    if base != expected_base:
        raise SpecError("invalid_spec", f"the first feature of a {spec['family']} part must be {expected_base}")


def _dim_refs(node) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        if set(node) == {"dim"}:
            return [node["dim"]]
        for value in node.values():
            refs.extend(_dim_refs(value))
    elif isinstance(node, list):
        for value in node:
            refs.extend(_dim_refs(value))
    return refs


@dataclass(frozen=True)
class Resolver:
    """Turns spec values into numbers (in spec units) for one variant."""

    spec: dict
    variant: str = "nominal"

    def __post_init__(self):
        if self.variant not in VARIANTS:
            raise SpecError("invalid_option", f"unknown variant {self.variant}")

    @property
    def units(self) -> str:
        return self.spec["units"]

    def dim(self, dim_id: str) -> float:
        d = self.spec["dimensions"][dim_id]
        nominal = float(d["nominal"])
        if self.variant == "mid_tolerance":
            upper = float(d.get("upper", 0.0))
            lower = float(d.get("lower", 0.0))
            return nominal + (upper + lower) / 2.0
        return nominal

    def __call__(self, value) -> float:
        if isinstance(value, dict):
            number = self.dim(value["dim"])
        else:
            number = float(value)
        if not math.isfinite(number) or abs(number) > MAX_LENGTH[self.units]:
            raise SpecError("out_of_range", f"value {number} is outside the supported range")
        return number

    def point(self, value) -> tuple[float, float]:
        return (self(value[0]), self(value[1]))

    def positive(self, value, what: str) -> float:
        number = self(value)
        if number <= 0:
            raise SpecError("invalid_spec", f"{what} must be positive")
        return number


def differs_by_variant(spec: dict) -> bool:
    """True if any dimension has an asymmetric tolerance (so mid != nominal)."""
    for d in spec["dimensions"].values():
        if abs(float(d.get("upper", 0.0)) + float(d.get("lower", 0.0))) > 1e-12:
            return True
    return False


def hole_diameter(feature: dict, value: Resolver, options: dict) -> tuple[float, dict | None]:
    """Modelled bore diameter for a hole and an optional thread step.

    Tapped holes follow the shop preference: CAM hole recognition only sees
    cylinders, so the shop chooses tap-drill, major or minor diameter, or a
    tap-drill bore with a major-diameter step down to thread depth.
    """
    thread = feature.get("thread")
    if feature["hole_type"] != "tapped" or not thread:
        return value.positive(feature["diameter"], f"{feature['id']} diameter"), None
    model = options.get("tapped_hole_model", "tap_drill")
    drill = thread["tap_drill"]
    if options.get("tap_drill_basis") == "form_tap" and thread.get("form_tap_drill"):
        drill = thread["form_tap_drill"]
    if model == "major_diameter":
        return float(thread["major"]), None
    if model == "minor_diameter":
        return float(thread.get("minor", drill)), None
    if model == "tap_drill_with_major_step":
        return float(drill), {"diameter": float(thread["major"]), "depth": thread["depth"]}
    return float(drill), None
