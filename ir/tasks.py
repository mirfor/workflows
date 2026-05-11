"""12 task types CNCF SW 1.0 (#6).

Discriminator po obecności pola-klucza (`call`, `do`, `for`, `fork`, `switch`, `try`,
`wait`, `listen`, `emit`, `raise`, `run`, `set`).

`export.as` (#12) opcjonalne — gdy brak, runtime auto-eksportuje wynik pod
`steps.<node_id>.output`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field, Tag

from ir._base import IsoDuration, JqExpression, StrictModel
from ir.errors import ErrorReference
from ir.policies import RetryPolicy, TimeoutPolicy

# Forward declaration (Task referuje samo siebie w listach/zagnieżdżeniach).
Task = Any  # rebound poniżej; potrzebne, by NamedTask sparsował się przy module load
NamedTask = dict[str, "Task"]
"""Element listy `do[]`: pojedyncza para `{ <task_name>: <Task> }`. Walidator wymusza len == 1."""


class _Export(StrictModel):
    as_: JqExpression | None = Field(default=None, alias="as")
    """Wyrażenie JQ produkujące wartość do zapisania w kontekście pod `steps.<node_id>.<as>`."""
    schema_ref: str | None = Field(default=None, alias="schema")


class _TaskBase(StrictModel):
    """Wspólne pola wszystkich task types per CNCF SW spec."""

    if_: JqExpression | None = Field(default=None, alias="if")
    """Warunek wykonania (skip gdy false). UI strukturalny builder kompiluje do JQ (#11)."""

    input: dict[str, Any] | None = None
    """Inline I/O schema/transform (CNCF SW spec)."""
    output: dict[str, Any] | None = None
    export: _Export | None = None
    """Opcjonalne `export.as` — patrz #12. Bez tego runtime auto-eksportuje pod `steps.<id>.output`."""

    timeout: TimeoutPolicy | str | None = None
    """Inline `TimeoutPolicy` lub referencja do `Use.timeouts.<name>` (#20, #22)."""
    retries: RetryPolicy | str | None = None
    """Inline `RetryPolicy` lub referencja do `Use.retries.<name>` (#20, #21)."""

    metadata: dict[str, Any] | None = None
    """Extensions: `metadata.weaver.*`, `metadata.temporal.*`."""


# ---------- 12 task types -----------------------------------------------------


class _CallSpec(StrictModel):
    """Niewykorzystywane bezpośrednio — pole `call` w `CallTask` ma typ `str` (function name)."""


class CallTask(_TaskBase):
    """`call` — wywołanie funkcji z `Use.functions.<name>` (Tool / Specialized Agent)."""

    call: str = Field(..., min_length=1)
    """Nazwa funkcji w `Use.functions`."""
    with_: dict[str, Any] | None = Field(default=None, alias="with")


class DoTask(_TaskBase):
    """`do` — sekwencja podzadań."""

    do: list[NamedTask]


class _ForLoop(StrictModel):
    each: str = Field(..., min_length=1)
    """Nazwa zmiennej iteracyjnej (dostępna w body przez JQ jako `$<each>`)."""
    in_: JqExpression = Field(..., alias="in")
    """JQ produkujący kolekcję."""
    at: str | None = None
    """Opcjonalna nazwa zmiennej indeksu."""


class ForTask(_TaskBase):
    """`for` — iteracja po kolekcji."""

    for_: _ForLoop = Field(..., alias="for")
    while_: JqExpression | None = Field(default=None, alias="while")
    do: list[NamedTask]


class _ForkBranches(StrictModel):
    branches: list[NamedTask]
    compete: bool = False
    """`True` → pierwszy zakończony branch wygrywa, reszta cancel; `False` → wait-all."""


class ForkTask(_TaskBase):
    """`fork` — równoległe wykonanie branchy."""

    fork: _ForkBranches


class _SwitchCase(StrictModel):
    when: JqExpression | None = None
    """Brak `when` = `default`. Walidator wymusza co najwyżej jeden case bez `when`."""
    then: str
    """Nazwa następnego task lub `end`. Per CNCF SW spec — referencja po nazwie."""
    do: list[NamedTask] | None = None
    """Extension Weaver: inline branch body (F3.E.1).
    Mapper rebuilduje z reachability analysis; generator emituje jako body if/elif."""


class SwitchTask(_TaskBase):
    """`switch` — warunkowe rozgałęzienie (multi-handle w UI, decyzja #9)."""

    switch: list[dict[str, _SwitchCase]]
    """Każdy element to single-key dict `{ <case_id>: SwitchCase }`."""


class TryCatch(StrictModel):
    """Pojedynczy `catch` (CNCF SW singular — multi-catch UI kompiluje do switch w `do`, #25)."""

    errors: dict[str, ErrorReference] | None = None
    """`{"with": ErrorReference}` per spec. Walidator sprawdza `with.type ∈ (base ∪ tool.errors)` (#23)."""
    as_: str | None = Field(default=None, alias="as")
    """Nazwa zmiennej z error payload."""
    when: JqExpression | None = None
    except_when: JqExpression | None = Field(default=None, alias="exceptWhen")
    retry: RetryPolicy | str | None = None
    do: list[NamedTask] | None = None


class TryTask(_TaskBase):
    """`try` — error handling (#6)."""

    try_: list[NamedTask] = Field(..., alias="try")
    catch: TryCatch


class WaitTask(_TaskBase):
    """`wait` — pauza."""

    wait: IsoDuration


class _ListenStrategy(StrictModel):
    all: list[dict[str, Any]] | None = None
    any: list[dict[str, Any]] | None = None
    one: dict[str, Any] | None = None


class ListenTask(_TaskBase):
    """`listen` — subskrypcja eventów (signal/event consumption)."""

    listen: dict[str, _ListenStrategy]
    """`{"to": ListenStrategy}` per spec."""
    foreach: NamedTask | None = None


class _EmitEvent(StrictModel):
    event: dict[str, Any]
    """`{"with": {...}}` — payload."""


class EmitTask(_TaskBase):
    """`emit` — publikacja eventu."""

    emit: _EmitEvent


class _RaiseSpec(StrictModel):
    error: ErrorReference | str
    """Inline `ErrorReference` lub nazwa z `Use.errors.<name>`."""


class RaiseTask(_TaskBase):
    """`raise` — rzucenie erroru."""

    raise_: _RaiseSpec = Field(..., alias="raise")


class _RunScript(StrictModel):
    language: str
    code: str | None = None
    source: dict[str, Any] | None = None


class _RunShell(StrictModel):
    command: str
    arguments: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)


class _RunWorkflow(StrictModel):
    namespace: str | None = None
    name: str
    version: str | None = None
    input: dict[str, Any] | None = None
    mode: Literal["wait", "fire_and_forget"] = "wait"


class _RunContainer(StrictModel):
    image: str
    command: str | None = None
    arguments: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)


class _RunSpec(StrictModel):
    script: _RunScript | None = None
    shell: _RunShell | None = None
    workflow: _RunWorkflow | None = None
    container: _RunContainer | None = None


class RunTask(_TaskBase):
    """`run` — uruchomienie zewnętrznego procesu/workflow."""

    run: _RunSpec


class SetTask(_TaskBase):
    """`set` — mutacja kontekstu (przypisanie wartości pod klucze w globalnym kontekście)."""

    set: dict[str, Any]


# ---------- Discriminated union ----------------------------------------------


def _task_discriminator(v: Any) -> str | None:
    """Rozpoznanie task type po obecności pola-klucza (CNCF SW spec).

    Kolejność: pola dyskryminujące najpierw (call, for, fork, switch, try, wait, listen, emit,
    raise, run, set), `do` jako ostatni — bo ForTask/TryTask również MAJĄ `do` field jako body,
    a discriminator musi zwrócić bardziej-specific tag dla nich.
    """
    discriminator_order = (
        "call",
        "for",
        "fork",
        "switch",
        "try",
        "wait",
        "listen",
        "emit",
        "raise",
        "run",
        "set",
        "do",  # last resort — czysty DoTask
    )
    if not isinstance(v, dict):
        for key in discriminator_order:
            attr = key + "_" if key in {"for", "try", "raise"} else key
            if getattr(v, attr, None) is not None:
                return key
        return None
    for key in discriminator_order:
        if key in v:
            return key
    return None


Task = Annotated[  # type: ignore[misc]
    Annotated[CallTask, Tag("call")]
    | Annotated[DoTask, Tag("do")]
    | Annotated[ForTask, Tag("for")]
    | Annotated[ForkTask, Tag("fork")]
    | Annotated[SwitchTask, Tag("switch")]
    | Annotated[TryTask, Tag("try")]
    | Annotated[WaitTask, Tag("wait")]
    | Annotated[ListenTask, Tag("listen")]
    | Annotated[EmitTask, Tag("emit")]
    | Annotated[RaiseTask, Tag("raise")]
    | Annotated[RunTask, Tag("run")]
    | Annotated[SetTask, Tag("set")],
    Discriminator(_task_discriminator),
]


# Rebind po Task (zastępuje forward-ref `dict[str, "Task"]` z góry pliku).
NamedTask = dict[str, Task]  # type: ignore[misc]


# Wymuszenie rebuild dla każdego task type (bo używają NamedTask w forward).
for _cls in (
    DoTask,
    ForTask,
    ForkTask,
    TryTask,
    TryCatch,
    ListenTask,
    _SwitchCase,
):
    _cls.model_rebuild(_types_namespace={"Task": Task, "NamedTask": NamedTask})
