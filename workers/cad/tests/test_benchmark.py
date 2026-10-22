"""Geometry engine tests. Expected values come from the specs (the drawing's
numbers) and closed-form formulas, never from the engine's own output."""

from __future__ import annotations

import copy
import json
import math
import uuid
from pathlib import Path

import pytest

from cadworker import analytic, build, export, naming, pipeline, tasks, validate
from cadworker.spec import SpecError
from cadworker.spec import validate as validate_spec

EXAMPLES = Path(__file__).resolve().parents[3] / "packages" / "feature-spec" / "examples"
NAMES = ["plate-with-holes", "bracket-block", "stepped-shaft"]


def load(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def staging(tmp_path, monkeypatch):
    monkeypatch.setenv("STAGING_ROOT", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("name", NAMES)
def test_specs_are_schema_valid(name):
    validate_spec(load(name))


@pytest.mark.parametrize("name", NAMES)
def test_closed_form_volume_matches_hand_calculation(name):
    spec = load(name)
    assert analytic.volume(spec) == pytest.approx(spec["expect"]["volume"], abs=2e-6)


def test_hand_formulas_for_the_plate():
    """Spot-check the calculator itself with the plate worked by hand."""
    c = 0.030
    box = 6 * 4 * 0.5
    chamfer = c * c * (6 + 4) - 4 / 3 * c ** 3
    cyl = lambda d, h: math.pi / 4 * d * d * h  # noqa: E731
    holes = 4 * (cyl(0.266, 0.5) + cyl(0.438, 0.266) - cyl(0.266, 0.266))
    holes += 4 * cyl(0.201, 0.5) + 2 * cyl(0.25, 0.5) + cyl(1.0, 0.5)
    assert analytic.volume(load("plate-with-holes")) == pytest.approx(box - chamfer - holes, rel=1e-12)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("variant", ["nominal", "mid_tolerance"])
@pytest.mark.parametrize("model", ["tap_drill", "tap_drill_with_major_step", "major_diameter"])
def test_reference_parts_pass_every_check(name, variant, model):
    spec = load(name)
    options = {"tapped_hole_model": model}
    built = build.build(spec, variant, options)
    report = validate.validate(spec, built, variant=variant, options=options)
    failures = [c for c in report["checks"] if c["status"] == "fail"]
    assert report["passed"], failures
    assert report["summary"]["bbox"] == pytest.approx(spec["expect"]["bbox"], abs=1e-6)


def test_mid_tolerance_moves_asymmetric_dimensions_only():
    spec = load("plate-with-holes")
    nominal = build.build(spec, "nominal").holes
    mid = build.build(spec, "mid_tolerance").holes
    dowel_nom = next(h for h in nominal if h.feature == "H3").diameter / 25.4
    dowel_mid = next(h for h in mid if h.feature == "H3").diameter / 25.4
    assert dowel_nom == pytest.approx(0.2500)
    assert dowel_mid == pytest.approx(0.25025)  # .2500 +.0005/-.0000
    clear_nom = next(h for h in nominal if h.feature == "H1").diameter
    clear_mid = next(h for h in mid if h.feature == "H1").diameter
    assert clear_nom == clear_mid  # symmetric tolerance: unchanged


def test_missing_feature_cannot_pass():
    """A plausible-looking solid with a feature silently dropped must fail."""
    spec = load("plate-with-holes")
    full = build.build(spec)
    broken_spec = copy.deepcopy(spec)
    broken_spec["features"] = [f for f in broken_spec["features"] if f["id"] != "H4"]
    broken = build.build(broken_spec)
    broken.holes = full.holes  # validate against what the drawing requires
    report = validate.validate(spec, broken, variant="nominal", options={})
    failed = {(c["check"], c["feature"]) for c in report["checks"] if c["status"] == "fail"}
    assert ("hole_diameter", "H4") in failed
    assert ("volume", "") in failed
    assert not report["passed"]


def test_misplaced_hole_fails_position_check():
    spec = load("plate-with-holes")
    full = build.build(spec)
    shifted = copy.deepcopy(spec)
    for f in shifted["features"]:
        if f["id"] == "H3":
            f["positions"][0] = [1.505, 2.0]  # .005" off
    bad = build.build(shifted)
    bad.holes = full.holes
    report = validate.validate(spec, bad, variant="nominal", options={})
    position = [c for c in report["checks"] if c["check"] == "hole_position" and c["feature"] == "H3"]
    assert position[0]["status"] == "fail"
    assert position[0]["measured"] == pytest.approx([1.505, 2.0], abs=1e-6)
    assert position[1]["status"] == "pass"


def test_blind_hole_depth_is_measured():
    spec = load("bracket-block")
    built = build.build(spec)
    report = validate.validate(spec, built, variant="nominal", options={})
    depths = [c for c in report["checks"] if c["check"] == "hole_depth"]
    assert len(depths) == 2
    assert all(c["measured"] == pytest.approx(0.5, abs=1e-6) for c in depths)


def test_tapped_hole_major_step_geometry():
    spec = load("bracket-block")
    options = {"tapped_hole_model": "tap_drill_with_major_step"}
    report = validate.validate(spec, build.build(spec, "nominal", options), variant="nominal",
                               options=options)
    steps = [c for c in report["checks"] if c["check"].startswith("thread_step")]
    assert {c["check"] for c in steps} == {"thread_step_diameter", "thread_step_depth"}
    assert all(c["status"] == "pass" for c in steps)
    diameter = next(c for c in steps if c["check"] == "thread_step_diameter")
    assert diameter["measured"] == pytest.approx(0.190)


@pytest.mark.parametrize("units", ["mm", "in"])
def test_step_export_round_trip_and_units(tmp_path, units):
    spec = load("stepped-shaft")
    result = pipeline.run_part(spec, "nominal", {"step_units": units}, tmp_path)
    assert result["validation"]["passed"], [c for c in result["validation"]["checks"]
                                            if c["status"] != "pass"]
    step = tmp_path / result["files"][0]["name"]
    assert step.name == f"BENCH-SHAFT-03_REVA_NOMINAL-{units.upper()}.step"
    assert export.declared_unit(step) == units
    header = step.read_text()[:2000]
    assert "The drawing governs" in header and "BENCH-SHAFT-03" in header
    report = json.loads((tmp_path / result["files"][2]["name"]).read_text())
    tapped = next(row for row in report["hole_table"] if row["feature"] == "H1")
    assert tapped["thread"] == "1/4-20 UNC-2B ↧ .50"
    assert tapped["modeled_diameter"] == 0.201 and tapped["depth"] == 0.6
    assert "disclaimer" in report


def test_unsupported_and_invalid_specs_are_refused():
    spec = load("plate-with-holes")
    sink = copy.deepcopy(spec)
    sink["features"][1]["countersink"] = {"diameter": 0.5, "angle": 82}
    with pytest.raises(SpecError) as exc:
        build.build(sink)
    assert exc.value.code == "unsupported_feature"

    unknown = copy.deepcopy(spec)
    unknown["features"].append({"id": "K1", "type": "knurl"})
    with pytest.raises(SpecError):
        validate_spec(unknown)

    dangling = copy.deepcopy(spec)
    dangling["features"][1]["diameter"] = {"dim": "D99"}
    with pytest.raises(SpecError):
        validate_spec(dangling)

    outside = copy.deepcopy(spec)
    outside["features"][3]["positions"] = [[9.0, 9.0]]
    with pytest.raises(SpecError) as exc:
        build.build(outside)
    assert exc.value.code == "feature_failed"


def test_blind_hole_breaking_through_is_caught_by_validation():
    """The builder cannot know the leg is only .750 thick at that height, but the
    measured bore depth exposes the break-through."""
    spec = load("bracket-block")
    spec["features"][-1]["depth"] = 0.9
    report = validate.validate(spec, build.build(spec), variant="nominal", options={})
    depths = [c for c in report["checks"] if c["check"] == "hole_depth"]
    assert all(c["status"] == "fail" for c in depths)
    assert depths[0]["measured"] == pytest.approx(0.75, abs=1e-6)
    assert not report["passed"]


def test_task_contract(staging):
    job_id = str(uuid.uuid4())
    result = tasks.run(job_id, [load("bracket-block")], {"also_export_mid_tolerance": True})
    assert result["ok"] is True
    assert [p["variant"] for p in result["parts"]] == ["nominal", "mid_tolerance"]
    for part in result["parts"]:
        for entry in part["files"]:
            path = staging / job_id / entry["name"]
            assert path.stat().st_size == entry["size"]
            assert pipeline._sha256(path) == entry["sha256"]
    assert tasks.run("../../etc", [load("bracket-block")], {})["error"]["code"] == "invalid_job"
    bad = load("bracket-block")
    bad["features"][0]["type"] = "turned_profile"
    failed = tasks.run(str(uuid.uuid4()), [bad], {})
    assert failed["ok"] is False and failed["error"]["retryable"] is False


def test_filename_pattern():
    assert naming.filename("{customer}_{part}_R{rev}_{kind}", part="BP 10/01", rev="C",
                           variant="mid_tolerance", units="in", customer="Acme") == \
        "Acme_BP_10_01_RC_MIDTOL-IN"
    assert naming.filename("{part}-{rev}", part="X", rev="A", variant="nominal", units="mm") == \
        "X-A_NOMINAL-MM"
