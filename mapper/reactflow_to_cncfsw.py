"""Deterministyczny mapper React Flow JSON → CNCF SW IR.

Decyzje:
- #1, #2, #9 (struktura UI, mapping krawędzi)
- #10 (trigger jako pierwszy node, persystowany w `metadata.weaver.trigger`)
- #19 (mapper jednokierunkowy; zachowanie 3 form Blueprintu)
- #25 (multi-catch UI → pojedynczy `catch` + `switch` w `catch.do`)

Format wejściowy RF JSON (zakładany):
```
{
  "meta": { "namespace": "...", "name": "...", "version": "1", "use": { ... } },
  "nodes": [ { "id": "...", "type": "<task_type>", "data": { ... }, "parentNode": "..." }, ... ],
  "edges": [ { "id": "...", "source": "...", "target": "...",
               "sourceHandle": "...", "targetHandle": "..." }, ... ]
}
```
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ir import (
    CallTask,
    Document,
    EmitTask,
    EventTrigger,
    ForkTask,
    ForTask,
    ListenTask,
    ManualTrigger,
    RaiseTask,
    RunTask,
    ScheduleTrigger,
    SetTask,
    SwitchTask,
    TryTask,
    Use,
    WaitTask,
    WebhookTrigger,
    Workflow,
)

TRIGGER_TYPES = {"manual_trigger", "webhook_trigger", "schedule_trigger", "event_trigger", "start"}
# Designer-side "end" is a visual sink node — no CNCF equivalent (workflow ends
# when all paths complete). Mapper strips end nodes from IR via _strip_end_nodes.
END_TYPES = {"end"}
ATOMIC_TASK_TYPES = {"call", "wait", "emit", "raise", "run", "set", "core.subprocess"}
CONTAINER_TASK_TYPES = {"for", "for_each", "try"}
BRANCHING_TASK_TYPES = {"switch", "fork", "listen"}


class MapperError(ValueError):
    """Błąd nieodwracalnej walidacji preconditions lub niepoprawnej struktury grafu."""


def map_reactflow_to_cncfsw(rf: dict[str, Any]) -> Workflow:
    """Główna funkcja mappera. Output jest deterministyczny dla danego inputu.

    Etapy:
    1. Walidacja preconditions (trigger count, orphan nodes, parentNode refs).
    2. Indeksowanie nodes/edges; budowa adjacency.
    3. Wykrycie trigger node (incoming==0) i przeniesienie do `metadata.weaver.trigger`.
    4. Topological build sequence dla top-level scope (parentNode is None).
    5. Multi-catch compilation (jeśli `try` ma >1 catch handlers w UI).
    6. Workflow assembly.
    """
    nodes_by_id, edges, parent_index, incoming, outgoing = _index(rf)
    meta = rf.get("meta") or {}

    _validate_preconditions(nodes_by_id, edges, parent_index, incoming, meta)

    trigger_node_id = _find_trigger(nodes_by_id, incoming)
    trigger = _build_trigger(nodes_by_id[trigger_node_id]) if trigger_node_id else None

    # F3.E.1: oblicz branch ownership — które nodes należą do którego switch case (BFS).
    # Top-level pomija owned nodes; każdy case dostaje swoje branch body inline.
    branch_owners = _compute_branch_ownership(nodes_by_id, outgoing)

    top_level_ids = [
        nid
        for nid, n in nodes_by_id.items()
        if n.get("parentNode") is None
        and nid != trigger_node_id
        and nid not in branch_owners
        # Designer-side `end` nodes are visual sinks — CNCF SW has no end task,
        # workflow completes when all paths drain. Strip from IR.
        and n.get("type") not in END_TYPES
    ]
    do = _build_sequence(
        top_level_ids,
        nodes_by_id,
        edges,
        outgoing,
        parent_index,
        trigger_node_id,
        branch_owners=branch_owners,
    )

    document = Document(
        dsl="1.0.0",
        namespace=meta.get("namespace") or "default",
        name=meta["name"],
        version=str(meta.get("version") or "1"),
        summary=meta.get("summary"),
    )
    use = _build_use(meta.get("use") or {})

    workflow_metadata: dict[str, Any] = dict(meta.get("metadata") or {})
    if trigger is not None:
        workflow_metadata.setdefault("weaver", {})["trigger"] = trigger.model_dump(
            by_alias=True, exclude_none=True
        )
    if "temporal" not in workflow_metadata and meta.get("workflowRunTimeout"):
        workflow_metadata["temporal"] = {"workflow_run_timeout": meta["workflowRunTimeout"]}

    return Workflow(
        document=document,
        use=use,
        do=do,
        metadata=workflow_metadata,
    )


# ---------- Indexing & validation -------------------------------------------------


def _index(
    rf: dict[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    dict[str | None, list[str]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    nodes_by_id = {n["id"]: n for n in rf.get("nodes", [])}
    edges = list(rf.get("edges", []))

    parent_index: dict[str | None, list[str]] = defaultdict(list)
    for nid, n in nodes_by_id.items():
        parent_index[n.get("parentNode")].append(nid)

    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in edges:
        outgoing[e["source"]].append(e)
        incoming[e["target"]].append(e)

    return nodes_by_id, edges, parent_index, incoming, outgoing


def _validate_preconditions(
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    parent_index: dict[str | None, list[str]],
    incoming: dict[str, list[dict[str, Any]]],
    meta: dict[str, Any],
) -> None:
    if not meta.get("name"):
        raise MapperError("RF JSON `meta.name` jest wymagane.")

    triggers = [nid for nid, n in nodes_by_id.items() if n.get("type") in TRIGGER_TYPES]
    if len(triggers) > 1:
        raise MapperError(f"Więcej niż jeden trigger node: {triggers}.")
    if triggers and incoming.get(triggers[0]):
        raise MapperError(f"Trigger node {triggers[0]} ma incoming edges.")

    for e in edges:
        if e["source"] not in nodes_by_id:
            raise MapperError(f"Edge {e['id']} referuje nieznany source: {e['source']}.")
        if e["target"] not in nodes_by_id:
            raise MapperError(f"Edge {e['id']} referuje nieznany target: {e['target']}.")

    for nid, n in nodes_by_id.items():
        parent = n.get("parentNode")
        if parent is not None and parent not in nodes_by_id:
            raise MapperError(f"Node {nid} referuje nieznany parentNode: {parent}.")
        if parent is not None and nodes_by_id[parent].get("type") not in CONTAINER_TASK_TYPES:
            raise MapperError(
                f"parentNode {parent} dla node {nid} nie jest container task "
                f"(`for`/`try`); typ: {nodes_by_id[parent].get('type')!r}."
            )


def _find_trigger(
    nodes_by_id: dict[str, dict[str, Any]],
    incoming: dict[str, list[dict[str, Any]]],
) -> str | None:
    for nid, n in nodes_by_id.items():
        if n.get("type") in TRIGGER_TYPES and not incoming.get(nid):
            return nid
    return None


def _build_trigger(
    node: dict[str, Any],
) -> ManualTrigger | WebhookTrigger | ScheduleTrigger | EventTrigger:
    data = node.get("data") or {}
    t = node["type"]
    # Designer-side `start` is the palette name for manual trigger (CNCF canonical).
    if t in ("manual_trigger", "start"):
        return ManualTrigger(input_schema_ref=data.get("inputSchemaRef"))
    if t == "webhook_trigger":
        return WebhookTrigger(
            path=data["path"],
            method=data.get("method", "POST"),
            auth_ref=data.get("authRef"),
        )
    if t == "schedule_trigger":
        return ScheduleTrigger(
            cron=data.get("cron"),
            every=data.get("every"),
            start_at=data.get("startAt"),
            end_at=data.get("endAt"),
            timezone=data.get("timezone"),
        )
    if t == "event_trigger":
        return EventTrigger(
            source=data["source"],
            eventType=data["eventType"],
            filter=data.get("filter"),
        )
    raise MapperError(f"Nieznany trigger type: {t!r}")


# ---------- Use registry ---------------------------------------------------------


def _build_use(use_data: dict[str, Any]) -> Use:
    """`meta.use` to JSON CNCF SW; Pydantic Use parsuje go bezpośrednio."""
    return Use.model_validate(use_data)


# ---------- Task sequence build --------------------------------------------------


def _build_sequence(
    scope_ids: list[str],
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    parent_index: dict[str | None, list[str]],
    trigger_node_id: str | None,
    *,
    branch_owners: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Topological order top-level scope; branching nodes (switch/fork/listen) zachowują
    multi-handle semantykę (case_<id>, branch_<n>, event_<id>) wewnątrz Task."""
    ordered_ids = _topological_order(scope_ids, edges, trigger_node_id)
    return [
        {nid: _build_task(nid, nodes_by_id, edges, outgoing, parent_index, branch_owners or {})}
        for nid in ordered_ids
    ]


def _compute_branch_ownership(
    nodes_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    """BFS branch ownership dla switch / fork / try (catch handlers).

    Nodes osiągalne wyłącznie z jednej gałęzi → owned by that branch
    (klucz: node_id, wartość: <branching_id>:<handle_or_case>).
    Nodes shared (multi-branch reachable) → bez ownera, pozostają w top-level scope.
    """
    case_reach: dict[str, set[str]] = {}

    # Switch — outgoing edges per case_<id>/default
    for branching_id, n in nodes_by_id.items():
        if n.get("type") not in {"switch", "fork", "listen"}:
            continue
        for edge in outgoing.get(branching_id, []):
            handle = edge.get("sourceHandle") or "default"
            target = edge["target"]
            label = f"{branching_id}:{handle}"
            case_reach[label] = _bfs_excluding_switches(target, outgoing, nodes_by_id)

    # Try — `data.catches[]` referuje nodes po nazwie w `do: [<node_id>, ...]`
    for try_id, n in nodes_by_id.items():
        if n.get("type") != "try":
            continue
        for ci, c in enumerate(n.get("data", {}).get("catches", []) or []):
            for handler_id in c.get("do") or []:
                if handler_id in nodes_by_id:
                    label = f"{try_id}:catch_{ci}_{handler_id}"
                    case_reach[label] = _bfs_excluding_switches(handler_id, outgoing, nodes_by_id)

    # Każdy node przypisany do swojego owner-a tylko jeśli należy do dokładnie 1 case
    ownership: dict[str, str] = {}
    for label, reach in case_reach.items():
        for nid in reach:
            other_owners = [lbl for lbl, r in case_reach.items() if lbl != label and nid in r]
            if other_owners:
                ownership.pop(nid, None)
                continue
            if nid in ownership and ownership[nid] != label:
                ownership.pop(nid, None)
                continue
            ownership[nid] = label
    return ownership


def _bfs_excluding_switches(
    start: str,
    outgoing: dict[str, list[dict[str, Any]]],
    nodes_by_id: dict[str, dict[str, Any]],
) -> set[str]:
    """BFS od `start`, NIE przekraczając kolejnych switch nodes (zatrzymanie na ich targetach)."""
    visited: set[str] = {start}
    queue = [start]
    while queue:
        cur = queue.pop(0)
        for e in outgoing.get(cur, []):
            t = e["target"]
            if t in visited:
                continue
            visited.add(t)
            # Zatrzymaj się na switch — jego branche należą do tego switch, nie tego (ważne dla nested)
            if nodes_by_id.get(t, {}).get("type") == "switch":
                continue
            queue.append(t)
    return visited


def _topological_order(
    scope_ids: list[str],
    edges: list[dict[str, Any]],
    trigger_node_id: str | None,
) -> list[str]:
    """Kolejność: target-y triggera najpierw (FIFO po sourceHandle), potem reszta alfabetycznie."""
    relevant = set(scope_ids)
    indeg: dict[str, int] = dict.fromkeys(scope_ids, 0)
    for e in edges:
        if e["source"] in relevant and e["target"] in relevant:
            indeg[e["target"]] += 1

    trigger_targets: list[str] = []
    if trigger_node_id:
        for e in edges:
            if (
                e["source"] == trigger_node_id
                and e["target"] in relevant
                and e["target"] not in trigger_targets
            ):
                trigger_targets.append(e["target"])

    initial = [nid for nid in trigger_targets if indeg[nid] == 0]
    other_zero = sorted(nid for nid, d in indeg.items() if d == 0 and nid not in initial)
    queue = initial + other_zero

    seen: set[str] = set()
    ordered: list[str] = []
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        ordered.append(nid)
        added: list[str] = []
        for e in edges:
            if e["source"] == nid and e["target"] in indeg and e["target"] not in seen:
                indeg[e["target"]] -= 1
                if indeg[e["target"]] == 0:
                    added.append(e["target"])
        added.sort()
        queue.extend(added)

    if len(ordered) < len(scope_ids):
        unreached = set(scope_ids) - seen
        raise MapperError(
            f"Cykl lub niedostępne nodes w top-level scope: {sorted(unreached)}. "
            "Pętle są dozwolone tylko w container `for` body."
        )
    return ordered


def _build_task(
    nid: str,
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    parent_index: dict[str | None, list[str]],
    branch_owners: dict[str, str] | None = None,
) -> Any:
    branch_owners = branch_owners or {}
    node = nodes_by_id[nid]
    raw_t = node["type"]
    data = node.get("data") or {}
    common = _common_task_fields(data)

    # Designer-side render type aliases ("step", "stepNode", "decisionPointNode")
    # carry the real CNCF kind in data.stepType. Translate before dispatching so
    # the rest of the dispatch table sees canonical kinds only.
    t = _translate_designer_type(raw_t, data)

    if t == "call":
        # Some Core Skills (human_task, ai_skill, timer, weaver_transform) carry
        # `with` fields directly on `data` instead of `data.with` — palette UX
        # writes intent/title/form_schema at top level. Collect them.
        call_target = data.get("function") or _function_for_core_skill(data.get("stepType"))
        if not call_target:
            raise MapperError(
                f"call node {nid} brak funkcji (data.function ani Core Skill fallback)."
            )
        with_payload = data.get("with")
        if with_payload is None:
            with_payload = _core_skill_with(data)
        # Ensure Core Skill calls get a default timeout so generator can emit
        # start_to_close_timeout (Temporal requirement). Designer palette
        # for human_task/ai_skill/timer/etc. may not set data.timeout.
        common.setdefault("timeout", "default_timeout")
        return CallTask(call=call_target, **{"with": with_payload}, **common)
    if t == "wait":
        return WaitTask(wait=data["duration"], **common)
    if t == "emit":
        return EmitTask(emit={"event": {"with": data.get("event") or {}}}, **common)
    if t == "raise":
        err = data.get("error")
        if isinstance(err, str):
            return RaiseTask(**{"raise": {"error": err}}, **common)
        return RaiseTask(**{"raise": {"error": err or {}}}, **common)
    if t == "set":
        return SetTask(set=data.get("assignments") or {}, **common)
    if t == "run":
        return RunTask(run=data["run"], **common)
    if t == "core.subprocess":
        sub_agent_id = data["subAgentId"]
        mode = data.get("mode", "wait")
        return RunTask(
            run={"workflow": {"name": sub_agent_id, "mode": mode, "input": data.get("input")}},
            **common,
        )

    if t == "switch":
        return _build_switch(nid, data, outgoing, nodes_by_id, edges, parent_index, branch_owners)
    if t == "fork":
        return _build_fork(nid, data, outgoing, nodes_by_id, edges, parent_index)
    if t == "listen":
        return ListenTask(
            listen={"to": data.get("to") or {}},
            foreach=None,
            **common,
        )

    if t == "for":
        return _build_for(nid, data, parent_index, nodes_by_id, edges, outgoing, common)
    if t == "try":
        return _build_try(nid, data, parent_index, nodes_by_id, edges, outgoing, common)

    raise MapperError(f"Nieznany task type: {t!r} dla node {nid}.")


# ──────────────────────────────────────────────────────────────────────────────
# Designer ↔ CNCF type translation
# ──────────────────────────────────────────────────────────────────────────────

# Designer palette emits node.type ∈ {"step", "stepNode", "decisionPointNode",
# "for_each", "start", "end", ...} (visual renderer keys). The real semantic
# step type lives in node.data.stepType. Map data.stepType -> CNCF kind so
# mapper dispatch sees canonical kinds regardless of which palette / round-trip
# path produced the node.

# Core Skills that resolve to CNCF `call` task with a builtin Tool function.
_CORE_SKILL_TO_TOOL: dict[str, str] = {
    "human_task": "create_human_task",
    "ai_skill": "ai_skill_invoke",
    "ai_briefing": "ai_briefing_generate",
    "weaver_transform": "weaver_transform_run",
}

# Designer stepType -> CNCF task kind (used by mapper dispatch).
_STEPTYPE_TO_CNCF: dict[str, str] = {
    # Core Skills that are tool calls
    "human_task": "call",
    "ai_skill": "call",
    "ai_briefing": "call",
    "weaver_transform": "call",
    # Delegate to Agent (subprocess in code, sub-agent in UI)
    "subprocess": "core.subprocess",
    "core.subprocess": "core.subprocess",
    # Timer is a wait
    "timer": "wait",
    # CNCF kinds pass through
    "call": "call",
    "set": "set",
    "wait": "wait",
    "emit": "emit",
    "raise": "raise",
    "run": "run",
    "switch": "switch",
    "fork": "fork",
    "listen": "listen",
    "for": "for",
    "for_each": "for",
    "try": "try",
}

# node.type passthrough — already CNCF kind
_TYPE_PASSTHROUGH = {
    "call", "set", "wait", "emit", "raise", "run", "core.subprocess",
    "switch", "fork", "listen", "for", "for_each", "try",
}


def _translate_designer_type(raw_type: str, data: dict[str, Any]) -> str:
    """Resolve a CNCF task kind from a (possibly designer-side) node type + data.stepType.

    Order of precedence:
      1. node.type already CNCF kind -> use it (passthrough).
      2. data.stepType maps to CNCF kind -> use it.
      3. Otherwise return raw_type (downstream dispatch will raise on unknown).
    """
    if raw_type in _TYPE_PASSTHROUGH:
        return raw_type
    step_type = data.get("stepType")
    if isinstance(step_type, str) and step_type in _STEPTYPE_TO_CNCF:
        return _STEPTYPE_TO_CNCF[step_type]
    return raw_type


def _function_for_core_skill(step_type: Any) -> str | None:
    """For Core Skill steps (human_task, ai_skill, ...) that lack data.function,
    derive the builtin Tool name from stepType."""
    if isinstance(step_type, str):
        return _CORE_SKILL_TO_TOOL.get(step_type)
    return None


def _core_skill_with(data: dict[str, Any]) -> dict[str, Any]:
    """Compose the `with` payload for Core Skill calls from top-level data fields.
    Palette UX writes intent/title/form_schema directly on data; mapper composes
    them into the `with` map for the underlying tool.

    For human_task: inject runtime context placeholders (resolved by generator's
    expression evaluator at execution time) for fields the activity needs but
    only the runtime knows (tenant_id, engagement_id, workflow_id).
    """
    step_type = data.get("stepType")
    if step_type == "human_task":
        return {
            # Runtime context — generator's eval('${...}') resolves at activity-call time.
            "tenant_id": "${ $context.tenant_id }",
            "engagement_id": "${ $context.engagement_id }",
            "form_id": data.get("form_id") or "approval-form",
            "assignee": data.get("assignee") or "*",
            # Static / designer-side metadata
            "intent": data.get("intent") or "approval",
            "title": data.get("title") or "",
            "description": data.get("description") or "",
            "due_in_hours": data.get("due_in_hours") or 24,
            "decision_options": data.get("decision_options") or "",
            "form_schema": data.get("form_schema") or {"fields": []},
        }
    if step_type in ("ai_skill", "ai_briefing"):
        return {
            "model": data.get("model") or "claude-sonnet-4-6",
            "prompt": data.get("prompt") or "",
            "temperature": data.get("temperature"),
            "max_tokens": data.get("max_tokens"),
        }
    if step_type == "weaver_transform":
        return {"script": data.get("script") or ""}
    if step_type == "timer":
        return {"duration": data.get("duration") or "PT0S"}
    return {}


def _common_task_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Wspólne opcjonalne pola taska (timeout, retries, if, export, metadata)."""
    out: dict[str, Any] = {}
    if "if" in data:
        out["if"] = data["if"]
    if "timeout" in data:
        out["timeout"] = data["timeout"]
    if "retries" in data:
        out["retries"] = data["retries"]
    if "export" in data:
        out["export"] = data["export"]
    if "metadata" in data:
        out["metadata"] = data["metadata"]
    if "input" in data:
        out["input"] = data["input"]
    if "output" in data:
        out["output"] = data["output"]
    return out


def _build_switch(
    nid: str,
    data: dict[str, Any],
    outgoing: dict[str, list[dict[str, Any]]],
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    parent_index: dict[str | None, list[str]],
    branch_owners: dict[str, str],
) -> SwitchTask:
    """Multi outgoing edges; sourceHandle = `case_<id>` lub `default`.

    F3.E.1: dla każdego case rebuilduje branch body z owned nodes (extension `do[]`),
    żeby generator emitował if/elif/else z body inline (nie tylko jump-em).
    """
    cases_by_handle = {e.get("sourceHandle", "out"): e["target"] for e in outgoing.get(nid, [])}
    cases: list[dict[str, Any]] = []
    declared = data.get("cases") or []

    def _owned_branch_seq(handle: str, target: str) -> list[dict[str, Any]] | None:
        """Zbuduj sekwencję NamedTask z nodes oznakowanych ownerem `<switch_id>:<handle>`."""
        label = f"{nid}:{handle}"
        owned = sorted(n for n, owner in branch_owners.items() if owner == label)
        if not owned:
            return None
        # Topological order — używamy tych samych edges, ale ograniczamy do owned set
        ordered = _topological_order(owned, edges, trigger_node_id=None)
        # Zapewnij że target jest pierwszy
        if target in ordered:
            ordered = [target] + [n for n in ordered if n != target]
        return [
            {n: _build_task(n, nodes_by_id, edges, outgoing, parent_index, branch_owners)}
            for n in ordered
        ]

    for c in declared:
        cid = c["id"]
        when = c.get("when")
        handle_key = f"case_{cid}"
        target = cases_by_handle.get(handle_key) or cases_by_handle.get(cid)
        if not target:
            raise MapperError(f"switch {nid}: brak edge dla case {cid!r}.")
        case_obj: dict[str, Any] = {"then": target}
        if when is not None:
            case_obj["when"] = when
        do_seq = _owned_branch_seq(handle_key, target)
        if do_seq:
            case_obj["do"] = do_seq
        cases.append({cid: case_obj})

    if "default" in cases_by_handle:
        target = cases_by_handle["default"]
        case_obj = {"then": target}
        do_seq = _owned_branch_seq("default", target)
        if do_seq:
            case_obj["do"] = do_seq
        cases.append({"default": case_obj})

    return SwitchTask(switch=cases)


def _build_fork(
    nid: str,
    data: dict[str, Any],
    outgoing: dict[str, list[dict[str, Any]]],
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    parent_index: dict[str | None, list[str]],
) -> ForkTask:
    """Multi outgoing edges; sourceHandle = `branch_<n>`."""
    branches: list[dict[str, Any]] = []
    by_handle = sorted(outgoing.get(nid, []), key=lambda e: e.get("sourceHandle", ""))
    for e in by_handle:
        target_id = e["target"]
        # MVP: każdy branch = pojedynczy task (linear sequence wymagałoby dalszego scope-owania)
        branches.append(
            {target_id: _build_task(target_id, nodes_by_id, edges, outgoing, parent_index)}
        )
    return ForkTask(fork={"branches": branches, "compete": bool(data.get("compete", False))})


def _build_for(
    nid: str,
    data: dict[str, Any],
    parent_index: dict[str | None, list[str]],
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    common: dict[str, Any],
) -> ForTask:
    body_ids = parent_index.get(nid, [])
    body_seq = _build_sequence(body_ids, nodes_by_id, edges, outgoing, parent_index, None)
    return ForTask(
        **{
            "for": {
                "each": data["each"],
                "in": data["in"],
                "at": data.get("at"),
            },
            "while": data.get("while"),
        },
        do=body_seq,
        **common,
    )


def _build_try(
    nid: str,
    data: dict[str, Any],
    parent_index: dict[str | None, list[str]],
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    common: dict[str, Any],
) -> TryTask:
    """Container `try` — body to nodes z parentNode==<nid>.

    Multi-catch UI (decyzja #25) → pojedynczy `catch` z `switch` w `catch.do`.
    Format `data.catches`: lista `[{ "errorType": "...", "as": "...",
                                      "do": [<task_node_id>, ...] }, ...]`.
    """
    body_ids = parent_index.get(nid, [])
    try_seq = _build_sequence(body_ids, nodes_by_id, edges, outgoing, parent_index, None)

    catches = data.get("catches") or []
    if not catches:
        raise MapperError(f"try {nid}: brak `catches[]`.")

    if len(catches) == 1:
        c = catches[0]
        catch_obj = _build_catch_block(c, nodes_by_id, edges, outgoing, parent_index)
    else:
        catch_obj = _compile_multi_catch(catches, nodes_by_id, edges, outgoing, parent_index)

    return TryTask(**{"try": try_seq}, catch=catch_obj, **common)


def _build_catch_block(
    catch: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    parent_index: dict[str | None, list[str]],
) -> Any:
    """Pojedynczy catch handler."""
    handler_ids: Iterable[str] = catch.get("do") or []
    handler_seq = _build_sequence(
        list(handler_ids), nodes_by_id, edges, outgoing, parent_index, None
    )
    return {
        "errors": ({"with": {"type": catch["errorType"]}} if catch.get("errorType") else None),
        "as": catch.get("as"),
        "when": catch.get("when"),
        "do": handler_seq or None,
    }


def _compile_multi_catch(
    catches: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    parent_index: dict[str | None, list[str]],
) -> dict[str, Any]:
    """Multi-catch UI helper (#25) → pojedynczy `catch` + `switch` task w `do`.

    Każdy catch z UI staje się case w syntetycznym `switch`; `when` matchuje `error.type`.
    """
    switch_cases: list[dict[str, Any]] = []
    for c in catches:
        err_type = c.get("errorType")
        cid = err_type or "default"
        handler_ids = c.get("do") or []
        case: dict[str, Any] = {"then": handler_ids[0] if handler_ids else "end"}
        if err_type:
            case["when"] = f'.error.type == "{err_type}"'
        switch_cases.append({cid: case})
        # Jeśli handler ma >1 task, wstaw je do catch.do jako poprzedzający block
        # (uproszczone MVP — pełny branching wymagałby zagnieżdżonej sekwencji per case)

    synthetic_switch = {
        "name": "_synthetic_multicatch_switch",
        "switch": switch_cases,
    }

    # Build catch.do: pojedynczy synthetic switch + (płaskie) handler tasks z wszystkich catches
    catch_do_seq: list[dict[str, Any]] = [
        {synthetic_switch["name"]: SwitchTask(switch=switch_cases)}
    ]
    for c in catches:
        for hid in c.get("do") or []:
            if hid in nodes_by_id:
                catch_do_seq.append(
                    {hid: _build_task(hid, nodes_by_id, edges, outgoing, parent_index)}
                )

    return {
        "errors": None,
        "as": "error",
        "do": catch_do_seq,
    }
