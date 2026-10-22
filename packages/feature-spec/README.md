# FeatureSpec

The constrained description of one machined part that the geometry engine builds. In Phase 2 the drawing reader proposes it and a person confirms it; it is never executed as code.

- `schema/feature-spec-1.schema.json` — JSON Schema (draft 2020-12). Units are the drawing's; any value can reference a dimension (`{"dim": "D7"}`), which resolves to its nominal or mid-tolerance value.
- `examples/` — the three Phase 0 reference parts. Their `expect.volume` values were computed with closed-form formulas (see `workers/cad/cadworker/analytic.py` and `workers/cad/tests`), not by the CAD kernel.

| Example | Family | Exercises |
|---|---|---|
| `plate-with-holes.json` | plate | counterbored clearance holes, tapped holes, reamed dowel holes (asymmetric tolerance), bored centre hole, top-edge chamfer |
| `bracket-block.json` | prismatic | step cut (L-bracket), concave fillet, rounded pocket from a lower face, through slot, blind tapped holes on a side face |
| `stepped-shaft.json` | turned | three diameters (two with asymmetric tolerances), end chamfers, ring groove, cross hole, tapped centre hole |
