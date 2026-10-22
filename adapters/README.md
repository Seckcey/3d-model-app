# Native CAD adapters (Phases 6–7)

Placeholders for the Fusion, AutoCAD and Mastercam adapters. Each runs on a licensed Windows workstation as a signed connector that polls for approved jobs over outbound HTTPS with scoped, short-lived credentials; none ever receives a remote shell. See [docs/BUILD_PLAN.md](../docs/BUILD_PLAN.md), Phases 6 and 7.

- `fusion/` — rebuild supported features as an editable timeline and save F3D + STEP.
- `autocad/` — DWG drawings first, then validated 3D solids.
- `mastercam/` — import the approved STEP, map hole colours to levels, carry the hole table, save MCAM (geometry only).
