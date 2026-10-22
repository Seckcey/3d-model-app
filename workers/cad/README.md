# Geometry worker

CadQuery / Open CASCADE worker. It consumes `cad.build_parts` tasks from the `cad` queue, builds each FeatureSpec (nominal, plus mid-tolerance when any tolerance is asymmetric), verifies the solid, exports STEP and GLB, reopens the STEP, and returns file hashes. It has no database access and no outbound network.

| Module | Role |
|---|---|
| `spec.py` | Schema validation, allowlist, value resolution (nominal / mid-tolerance), tapped-hole representation |
| `build.py` | Deterministic interpreter: one function per allowed feature type |
| `measure.py` | Reads the exact B-rep: bounding box, validity, hole axes, depths |
| `validate.py` | Checks: valid single solid, extents, origin on datums, closed-form volume, each hole's diameter, position and depth |
| `analytic.py` | Closed-form volumes, independent of the kernel |
| `export.py` | STEP with face colours by hole type, part name, declared units and a header stating that the drawing governs; GLB display mesh |
| `pipeline.py` | Build → validate → export → reopen → re-check → report |
| `tasks.py` | Celery task contract and error mapping (`unsupported_feature`, `invalid_spec`, `timeout`, `cad_crash`) |
