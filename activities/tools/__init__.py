"""Tools registry — każdy moduł `activities/tools/<integration>.py` deklaruje:

- jeden lub więcej `@activity.defn` (Temporal activities)
- moduł-level `TOOL_MANIFEST: dict[str, Any]` zgodny z `ACTIVITY_CATALOG.md` (#18)

`scripts/build_manifest.py` agreguje `TOOL_MANIFEST` z modułów do `activities/manifest.json`.
`activities/registry.py` re-eksportuje `ALL_ACTIVITIES` dla worker startup.
"""
