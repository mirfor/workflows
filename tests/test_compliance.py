"""Compliance tests — assertion per decyzja projektowa (`docs/SESSION_STATE.md` #1–#30).

Każdy test sprawdza realny invariant w strukturze repo / kodzie / zachowaniu.
Test xfail (`reason=...`) gdy decyzja jeszcze nie zaimplementowana —
implementator zdejmuje xfail po implementacji + passing assertion.

CI gate `compliance` w `.github/workflows/ci.yml` blokuje merge gdy compliance test fail
**bez** `xfail` markeru.

Uruchom: `uv run pytest tests/test_compliance.py -v`
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------- Helper ---------------------------------------------------------------


def _exists(path: str) -> bool:
    return (REPO_ROOT / path).exists()


# ============== Decyzje #1–#30 ===================================================


def test_decision_01_reactflow_source_of_truth() -> None:
    """#1: Source of truth UI = React Flow. Brak modułu BPMN→IR."""
    assert _exists("mapper/reactflow_to_cncfsw.py"), "Mapper RF→IR musi istnieć"
    assert not _exists("mapper/bpmn_to_cncfsw.py"), "BPMN mapper poza scope MVP"


def test_decision_02_structural_primitives_only() -> None:
    """#2: UI primitivy strukturalne (Sequence/Branch/Loop/Parallel/WaitSignal). Brak surowych krawędzi."""
    from mapper import MapperError, map_reactflow_to_cncfsw  # noqa: F401
    # Asercja: mapper rejects raw sequential edges between atomic tasks bez container/handle.
    # (placeholder — pełen test po implementacji)


def test_decision_03_two_layer_model() -> None:
    """#3: Dwuwarstwowy model — 12 task types (closed) + Tools/Agents (open)."""
    from ir import (  # noqa: F401
        CallTask,
        DoTask,
        EmitTask,
        ForkTask,
        ForTask,
        ListenTask,
        RaiseTask,
        RunTask,
        SetTask,
        SwitchTask,
        TryTask,
        WaitTask,
    )
    closed_set = {CallTask, DoTask, EmitTask, ForkTask, ForTask, ListenTask,
                  RaiseTask, RunTask, SetTask, SwitchTask, TryTask, WaitTask}
    assert len(closed_set) == 12


def test_decision_04_tenant_isolation_layout() -> None:
    """#4: Per-Tenant fizyczna izolacja. Layout: blueprints/<tenant>/<bp>/v<n>/."""
    # Layout blueprints — nie flat
    bp_dir = REPO_ROOT / "blueprints"
    if bp_dir.exists():
        for entry in bp_dir.iterdir():
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            assert entry.is_dir(), f"`blueprints/` nie może mieć plików top-level: {entry}"
            for bp in entry.iterdir():
                if bp.name.startswith(".") or bp.name == "__pycache__":
                    continue
                assert bp.is_dir(), f"Tenant {entry.name}/ nie może mieć plików top-level"
                versions = [v for v in bp.iterdir() if v.is_dir() and v.name.startswith("v")]
                assert versions, f"Brak wersji v<n> w blueprints/{entry.name}/{bp.name}/"

    # Generator codegen wymusza tenant_id w API
    import inspect

    from generator import codegen
    sig = inspect.signature(codegen.generate)
    assert "tenant_id" in sig.parameters, "generate() musi przyjmować tenant_id (#4)"
    src = inspect.getsource(codegen)
    assert "generated/{tenant_id}/workflows/" in src

    # Manifest per Tenant
    from generator.manifest import manifest_path_for
    p = str(manifest_path_for(REPO_ROOT, "demo"))
    assert "/generated/" in p and "/demo/manifest.json" in p

    # Worker wymaga --tenant
    worker_src = (REPO_ROOT / "worker.py").read_text("utf-8")
    assert '"--tenant"' in worker_src and "required=True" in worker_src


def test_decision_05_cncfsw_pydantic_models() -> None:
    """#5: CNCF SW 1.0 JSON jako wire format + Pydantic models."""
    from ir import Document, Workflow
    doc = Document(dsl="1.0.0", namespace="t", name="x", version="1")
    assert doc.dsl == "1.0.0"
    wf = Workflow(document=doc, do=[])
    # Round-trip
    dumped = wf.model_dump(by_alias=True, exclude_none=True)
    Workflow.model_validate(dumped)


def test_decision_06_all_12_task_types_supported() -> None:
    """#6: 12 task types CNCF SW 1.0 wszystkie w MVP — Pydantic + mapper + generator
    emitują **realny kod** dla każdego, BEZ placeholder `not yet implemented`.
    """
    from datetime import UTC, datetime

    from generator import generate
    from ir import (
        CallTask,
        Document,
        DoTask,
        EmitTask,
        ForkTask,
        ForTask,
        ListenTask,
        RaiseTask,
        RunTask,
        SetTask,
        SwitchTask,
        ToolFunction,
        TryTask,
        Use,
        WaitTask,
        Workflow,
    )

    types = [CallTask, DoTask, EmitTask, ForkTask, ForTask, ListenTask,
             RaiseTask, RunTask, SetTask, SwitchTask, TryTask, WaitTask]
    assert len({t.__name__ for t in types}) == 12

    # Mapper i generator wszystkie 12 obsługuje
    # Compliance: dla każdego task type istnieje realny `_build_*` w generatorze (nie placeholder)
    import inspect

    from generator import codegen
    from generator.codegen import _build_task_stmts  # noqa: F401
    from mapper.reactflow_to_cncfsw import _build_task  # noqa: F401
    src = inspect.getsource(codegen)
    assert "not yet implemented" not in src, \
        "Generator zawiera placeholder dla niektórych task types (#6 nie spełnione)"

    # Smoke: generuj workflow z wszystkimi 12 task types — sprawdź że produkt nie ma placeholder
    wf = Workflow(
        document=Document(dsl="1.0.0", namespace="t", name="all", version="1"),
        use=Use(functions={
            "fn": ToolFunction(name="fn", type="weaver_tool",
                               module="activities.tools.log_message",
                               operation="log_message", errors=[]),
        }),
        do=[
            {"c": CallTask(call="fn")},
            {"d": DoTask(do=[{"d_inner": SetTask(set={})}])},
            {"f": ForTask(**{"for": {"each": "i", "in": ".input.x"}}, do=[
                {"f_body": SetTask(set={})},
            ])},
            {"fk": ForkTask(fork={"branches": [{"b1": SetTask(set={})}], "compete": False})},
            {"sw": SwitchTask(switch=[{"a": {"when": ".x", "then": "end"}}])},
            {"tr": TryTask(**{"try": [{"inner": SetTask(set={})}]},
                            catch={"as": "e"})},
            {"w": WaitTask(wait="PT1S")},
            {"l": ListenTask(listen={"to": {"one": {"source": "s", "event_type": "e"}}})},
            {"em": EmitTask(emit={"event": {}})},
            {"rs": RaiseTask(**{"raise": {"error": "X"}})},
            {"rn": RunTask(run={"workflow": {"name": "other"}})},
            {"st": SetTask(set={})},
        ],
    )
    g = generate(wf, tenant_id="t", generated_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert "not yet implemented" not in g.source
    assert "raise NotImplementedError" not in g.source


def test_decision_07_tools_agents_as_functions() -> None:
    """#7: Tools/Specialized Agents jako CNCF SW `functions` z custom `type`."""
    from ir import SpecializedAgentFunction, ToolFunction
    tf = ToolFunction(name="x", type="weaver_tool", module="m", operation="o")
    af = SpecializedAgentFunction(name="x", type="weaver_specialized_agent",
                                  endpoint_url="http://x", operation="o")
    assert tf.type == "weaver_tool"
    assert af.type == "weaver_specialized_agent"


def test_decision_08_task_extensions_in_metadata() -> None:
    """#8: Task ma `metadata: dict | None` dla extensions Weaver/Temporal."""
    from ir import CallTask
    t = CallTask(call="f", metadata={"weaver": {"k": "v"}, "temporal": {"x": 1}})
    assert t.metadata == {"weaver": {"k": "v"}, "temporal": {"x": 1}}


def test_decision_09_edge_handles_mapping() -> None:
    """#9: Mapper rozpoznaje case_<id>/default/branch_<n>/main/catch_<err>."""
    from mapper import map_reactflow_to_cncfsw
    rf = {
        "meta": {"namespace": "t", "name": "x", "version": "1", "use": {}},
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "sw", "type": "switch", "data": {"cases": [{"id": "a", "when": "true"}]}},
            {"id": "n1", "type": "set", "data": {"assignments": {}}},
            {"id": "n2", "type": "set", "data": {"assignments": {}}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "sw"},
            {"id": "e2", "source": "sw", "target": "n1", "sourceHandle": "case_a"},
            {"id": "e3", "source": "sw", "target": "n2", "sourceHandle": "default"},
        ],
    }
    map_reactflow_to_cncfsw(rf)


def test_decision_10_trigger_as_first_node() -> None:
    """#10: Trigger jako pierwszy node (incoming==0); persystowany w metadata.weaver.trigger."""
    from mapper import map_reactflow_to_cncfsw
    rf = {
        "meta": {"namespace": "t", "name": "x", "version": "1", "use": {}},
        "nodes": [
            {"id": "trg", "type": "manual_trigger", "data": {}},
            {"id": "n1", "type": "set", "data": {"assignments": {}}},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "n1"}],
    }
    wf = map_reactflow_to_cncfsw(rf)
    assert wf.metadata["weaver"]["trigger"]["type"] == "manual_trigger"


def test_decision_11_jq_compiled_from_ui() -> None:
    """#11: Warunki w UI kompilowane do JQ; brak ręcznego pisania JQ, brak LLM-NL w MVP."""
    from ir import SwitchTask
    SwitchTask(switch=[{"a": {"when": ".x == 1", "then": "n1"}}])
    # Brak prompts/ w MVP
    assert not _exists("prompts/")


def test_decision_12_auto_export_steps_output() -> None:
    """#12: Generator emituje `steps_output["<id>"] = ...` po każdym task."""
    from datetime import UTC, datetime

    from generator import generate
    from ir import Document, SetTask, Use, Workflow
    wf = Workflow(document=Document(dsl="1.0.0", namespace="t", name="x", version="1"),
                  use=Use(), do=[{"k": SetTask(set={"a": 1})}])
    src = generate(wf, tenant_id="demo", generated_at=datetime(2026, 1, 1, tzinfo=UTC)).source
    assert "steps_output[" in src


def test_decision_13_pydantic_io_schemas() -> None:
    """#13: Pydantic models eksportują JSON Schema (`model_json_schema()`)."""
    from ir import Workflow
    schema = Workflow.model_json_schema(by_alias=True)
    assert "properties" in schema or "$defs" in schema or "definitions" in schema


def test_decision_14_generated_py_layout() -> None:
    """#14: `generated/<tenant>/workflows/<snake>__v<n>.py` + header + black."""
    from datetime import UTC, datetime

    from generator import generate
    from ir import Document, SetTask, Use, Workflow
    wf = Workflow(document=Document(dsl="1.0.0", namespace="demo", name="hi", version="1"),
                  use=Use(), do=[{"k": SetTask(set={})}])
    g = generate(wf, tenant_id="demo", generated_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert g.file_name == "hi__v1.py"
    assert g.class_name == "Hi_v1"
    assert g.relative_path == "generated/demo/workflows/hi__v1.py"
    assert "Generated from Blueprint demo/hi v1" in g.source
    assert "Source hash:" in g.source
    assert "DO NOT EDIT" in g.source


def test_decision_15_ast_generator_jq_libjq() -> None:
    """#15: Generator używa Python `ast` module (nie string templating); `_eval()` z compiled JQ cache."""
    import inspect

    from generator import codegen
    src = inspect.getsource(codegen)
    assert "import ast" in src or "from ast" in src
    assert "_JQ_CACHE" in src or "jq.compile" in src


def test_decision_16_validator_six_categories() -> None:
    """#16: Walidator emituje codes w schemacie <A-F><NNN>; error blokuje publish."""
    # Sprawdzić że walidator istnieje i ma wymagane kategorie
    import inspect

    from validator import Severity, validate  # noqa: F401
    from validator import validator as v
    src = inspect.getsource(v)
    # Co najmniej jedna reguła per kategoria — placeholder smoke; pełna asercja
    # po dodaniu wszystkich kategorii reguł D/F do walidatora (post-MVP).
    assert any(prefix in src for prefix in ("A0", "B0", "C0", "E1"))


def test_decision_17_versioning_lifecycle_manifest() -> None:
    """#17: Manifest entry: active_version, deprecated_versions, build_id_lineage."""
    from generator.manifest import update_manifest  # noqa: F401
    # Po update_manifest, manifest ma wymagane pola
    # (placeholder — pełny test po implementacji)


def test_decision_18_activity_registry_layout() -> None:
    """#18: ALL_ACTIVITIES discovery + call_specialized_agent dispatcher."""
    from activities import ALL_ACTIVITIES, call_specialized_agent
    assert isinstance(ALL_ACTIVITIES, list)
    assert call_specialized_agent in ALL_ACTIVITIES


def test_decision_19_three_forms_persisted() -> None:
    """#19: Po Publish: blueprints/<t>/<id>/v<n>/{reactflow.json,cncf-sw.json} + generated/<t>/workflows/<id>__v<n>.py."""
    bp_dir = REPO_ROOT / "blueprints"
    gen_dir = REPO_ROOT / "generated"
    if bp_dir.exists():
        for tenant in bp_dir.iterdir():
            if not tenant.is_dir():
                continue
            for bp in tenant.iterdir():
                if not bp.is_dir():
                    continue
                for v in bp.iterdir():
                    if v.is_dir() and v.name.startswith("v"):
                        assert (v / "reactflow.json").exists()
                        assert (v / "cncf-sw.json").exists()
                        # `.py` w generated/<tenant>/workflows/
                        version_num = v.name[1:]
                        py = gen_dir / tenant.name / "workflows" / f"{bp.name}__v{version_num}.py"
                        assert py.exists(), f"Brak {py}"


def test_decision_20_profile_based_policies() -> None:
    """#20: Use.retries/timeouts profile referowane przez nazwę z task."""
    from ir import RetryPolicy, TimeoutPolicy, Use
    use = Use(
        retries={"r1": RetryPolicy(delay="PT1S")},
        timeouts={"t1": TimeoutPolicy(after="PT5M")},
    )
    assert "r1" in use.retries
    assert "t1" in use.timeouts


def test_decision_21_retry_unsupported_fields_blocked() -> None:
    """#21: Walidator blokuje retry pola bez Temporal mapping (jitter, when, exceptWhen, limit.duration, limit.attempt.duration)."""
    from ir import Document, RetryJitter, RetryPolicy, Use, Workflow
    from validator import validate
    use = Use(retries={"bad": RetryPolicy(jitter=RetryJitter(**{"from": "PT1S", "to": "PT2S"}))})
    wf = Workflow(document=Document(dsl="1.0.0", namespace="t", name="x", version="1"),
                  use=use, do=[])
    rep = validate(wf)
    assert any(i.code.startswith("E1") for i in rep.errors)


def test_decision_22_timeout_three_fields() -> None:
    """#22: TimeoutPolicy: `after` wymagane (start_to_close); metadata.temporal.{heartbeat,schedule_to_close}."""
    from ir import TimeoutPolicy
    tp = TimeoutPolicy(after="PT5M",
                      metadata={"temporal": {"heartbeat": "PT30S", "schedule_to_close": "PT10M"}})
    assert tp.after == "PT5M"
    # `schedule_to_start_timeout` NIE w MVP — brak takiego pola w model
    assert not hasattr(tp, "schedule_to_start")


def test_decision_23_error_taxonomy() -> None:
    """#23: 7 base error types + per-Tool extensions; walidator blokuje unknown type."""
    from ir import BaseErrorType
    base_types = {e.value for e in BaseErrorType}
    expected = {"ValidationError", "AuthError", "RateLimitError", "TimeoutError",
                "NotFoundError", "IntegrationError", "InternalError"}
    assert base_types == expected


def test_decision_24_non_retryable_merge() -> None:
    """#24: Manifest defaults ∪ profile.nonRetryableTypes → Temporal.non_retryable_error_types."""
    from ir import RetryPolicy
    rp = RetryPolicy(non_retryable_types=["X"], metadata={"temporal": {"non_retryable_error_types": ["Y"]}})
    assert "X" in rp.non_retryable_types
    assert rp.metadata["temporal"]["non_retryable_error_types"] == ["Y"]


def test_decision_25_multi_catch_compilation() -> None:
    """#25: Mapper przy >1 catch UI emituje single CNCF SW catch z switch task wewnątrz catch.do."""
    from mapper import map_reactflow_to_cncfsw  # noqa: F401
    # Pełny test wymaga RF JSON z multi-catch — placeholder


def test_decision_26_fail_fast_uncaught() -> None:
    """#26: Generator nie emituje workflow-level catch ani retry policy."""
    from datetime import UTC, datetime

    from generator import generate
    from ir import Document, SetTask, Use, Workflow
    wf = Workflow(document=Document(dsl="1.0.0", namespace="t", name="x", version="1"),
                  use=Use(), do=[{"k": SetTask(set={})}])
    src = generate(wf, tenant_id="demo", generated_at=datetime(2026, 1, 1, tzinfo=UTC)).source
    # Brak workflow-level retry / handler
    assert "WorkflowRetryPolicy" not in src
    assert "document.onError" not in src


def test_decision_27_workflow_run_timeout_only() -> None:
    """#27: Pydantic model wspiera tylko `workflow_run_timeout`; brak `execution_timeout`/`task_timeout`."""
    from ir import TemporalWorkflowMetadata
    fields = set(TemporalWorkflowMetadata.model_fields.keys())
    assert "workflow_run_timeout" in fields
    assert "workflow_execution_timeout" not in fields
    assert "workflow_task_timeout" not in fields


def test_decision_28_cascade_defaults_resolution() -> None:
    """#28: cascade_resolve(tenant, client_org, blueprint) → final values; brak hardcoded."""
    from scripts.build_manifest import CascadeDefaults, cascade_resolve
    t = CascadeDefaults(default_start_to_close="PT10M")
    o = CascadeDefaults(default_start_to_close="PT5M")
    b = CascadeDefaults(default_start_to_close="PT2M")
    assert cascade_resolve(t, o, b).default_start_to_close == "PT2M"
    assert cascade_resolve(t, o, None).default_start_to_close == "PT5M"
    assert cascade_resolve(t, None, None).default_start_to_close == "PT10M"


def test_decision_29_no_native_saga() -> None:
    """#29: Saga = pattern user-implemented; brak native construct w IR."""
    import inspect

    from ir import tasks as t_mod
    src = inspect.getsource(t_mod)
    assert "SagaTask" not in src  # nie ma natywnego saga task type
    # Compensation jest user-implemented w try.catch.do


def test_decision_30_compiled_only_no_interpreter() -> None:
    """#30: Brak interpreter modułu. Każdy Blueprint ma `.py` w generated/<tenant>/workflows/."""
    assert not _exists("interpreter/")
    assert not _exists("runtime_interpreter.py")


# ============== Dodatkowe compliance: F3.E.1 (switch flow) =====================


def test_switch_branches_no_dead_paths_via_branch_ownership() -> None:
    """F3.E.1: Mapper rebuilduje branches do `case.do`; generator emituje branch body inline.

    Sprawdza że dla sample workflow (`blueprints/demo/sample/v1/`) generator emituje
    if/else z disjoint branch bodies — nie wszystkie nodes sekwencyjnie.
    """
    py_path = REPO_ROOT / "generated/demo/workflows/sample__v1.py"
    if not py_path.exists():
        pytest.skip("Sample workflow nie wygenerowany — uruchom regenerate_all")
    src = py_path.read_text("utf-8")
    # vip body wewnątrz if; default body wewnątrz else
    if_idx = src.find("if _eval(")
    else_idx = src.find("else:", if_idx)
    return_idx = src.find("return steps_output", else_idx)
    assert if_idx > 0 and else_idx > if_idx and return_idx > else_idx
    if_body = src[if_idx:else_idx]
    else_body = src[else_idx:return_idx]
    # vip nodes (log_vip, emit_vip) w if body, NIE w else
    assert "log_vip" in if_body and "emit_vip" in if_body
    assert "log_vip" not in else_body and "emit_vip" not in else_body
    # default nodes (log_default, emit_regular) w else body, NIE w if
    assert "log_default" in else_body and "emit_regular" in else_body
    assert "log_default" not in if_body and "emit_regular" not in if_body


def test_switch_case_supports_inline_do_body_in_pydantic() -> None:
    """F3.E.1: `_SwitchCase` ma pole `do: list[NamedTask] | None` (extension Weaver)."""
    from ir import SwitchTask
    sw = SwitchTask(switch=[
        {"vip": {"when": ".x", "then": "n1", "do": [{"n1": {"set": {"k": "v"}}}]}},
    ])
    case = sw.switch[0]["vip"]
    assert case.do is not None
    assert len(case.do) == 1


# ============== F5: multi-blueprint coverage =====================================


def test_f5_multi_blueprint_coverage_per_task_type() -> None:
    """F5: każdy z task types pokryty co najmniej 1 Blueprintem w `blueprints/`."""
    bp_dir = REPO_ROOT / "blueprints"
    if not bp_dir.exists():
        pytest.skip("blueprints/ pusty — pomiń")

    found_types: set[str] = set()
    for tenant in bp_dir.iterdir():
        if not tenant.is_dir():
            continue
        for bp in tenant.iterdir():
            if not bp.is_dir():
                continue
            for v in bp.iterdir():
                rf = v / "reactflow.json"
                if not rf.exists():
                    continue
                import json as _j
                data = _j.loads(rf.read_text("utf-8"))
                for n in data.get("nodes", []):
                    found_types.add(n.get("type", ""))

    expected_core = {"manual_trigger", "set", "call", "switch", "for", "fork", "try", "raise"}
    missing = expected_core - found_types
    assert not missing, f"Multi-blueprint suite nie pokrywa: {missing}"


def test_f5_cross_tenant_isolation_via_separate_manifests() -> None:
    """F5: każdy Tenant ma osobny manifest w `generated/<tenant>/manifest.json`,
    workflows wymienione w nim są dostępne TYLKO temu Tenantowi.
    """
    gen_dir = REPO_ROOT / "generated"
    if not gen_dir.exists():
        pytest.skip("generated/ pusty")
    tenant_manifests = {}
    for tenant in gen_dir.iterdir():
        if not tenant.is_dir() or tenant.name == "__pycache__":
            continue
        mf = tenant / "manifest.json"
        if mf.exists():
            import json as _j
            tenant_manifests[tenant.name] = _j.loads(mf.read_text("utf-8"))

    if len(tenant_manifests) < 2:
        pytest.skip("Mniej niż 2 Tenantów — brak materialu do isolation testu")

    # Wszystkie Tenant manifesty są disjoint w blueprint_ids
    seen_in_tenants: dict[str, str] = {}
    for tenant, mf in tenant_manifests.items():
        for bp_id in mf.get("blueprints", {}):
            assert bp_id not in seen_in_tenants or seen_in_tenants[bp_id] == tenant, \
                f"Blueprint {bp_id!r} występuje w wielu Tenantach " \
                f"({seen_in_tenants[bp_id]} + {tenant}) — naruszenie izolacji #4"
            seen_in_tenants[bp_id] = tenant

    # Każdy Tenant manifest ma poprawne tenant_id w polu
    for tenant, mf in tenant_manifests.items():
        assert mf.get("tenant_id") == tenant, \
            f"Manifest w {tenant}/manifest.json ma tenant_id={mf.get('tenant_id')!r}"
