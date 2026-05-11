# FIXTURE_MODE — Per-activity fixture mode

Post-MVP development aid. When active, activities decorated with `@fixturable` return a static JSON response instead of executing real logic. Intended for mocking LLM calls and side-effects (HTTP, human tasks, child engagements) during development and dry-run testing.

## Environment variable

| Variable | Truthy values | Default |
|---|---|---|
| `FIXTURE_MODE` | `1`, `true`, `yes` (case-insensitive) | unset (disabled) |

## Applying to an activity

`@fixturable` must be the **inner** decorator (between the function definition and `@activity.defn`):

```python
from activities.fixture import fixturable
from temporalio import activity

@activity.defn(name="my_op")
@fixturable
async def my_op(payload: dict[str, Any]) -> dict[str, Any]:
    # Not executed when FIXTURE_MODE is set.
    ...
```

## Adding a fixture

1. Create `activities/fixtures/<function_name>.json` with a JSON object matching the activity's output schema.
2. Decorate the activity with `@fixturable` (see above).

The file name must match the Python function name (not the Temporal activity name if they differ).

**Example** — activity returning `HttpGetOutput`:

```json
{
  "status": 200,
  "body": "<html>fixture</html>",
  "headers": {"content-type": "text/html; charset=utf-8"}
}
```

If `FIXTURE_MODE` is set but no fixture file exists, the activity raises `FileNotFoundError` with the expected path — create the file to resolve it.

## Built-in fixtures

| Activity (fn name) | Temporal name | Fixture file |
|---|---|---|
| `http_get` | `http_get` | `activities/fixtures/http_get.json` |
| `log_message` | `log_message` | `activities/fixtures/log_message.json` |
| `create_human_task` | `create_human_task` | `activities/fixtures/create_human_task.json` |
| `record_child_engagement` | `record_child_engagement` | `activities/fixtures/record_child_engagement.json` |
| `call_specialized_agent` | `call_specialized_agent` | `activities/fixtures/call_specialized_agent.json` |

## API reference

```python
from activities.fixture import fixturable, is_fixture_mode

is_fixture_mode() -> bool
# Returns True when FIXTURE_MODE env var is set to a truthy value.

@fixturable
# Decorator. Applied inside @activity.defn.
# Reads fixture from activities/fixtures/<fn.__name__>.json when is_fixture_mode() is True.
# Raises FileNotFoundError if the fixture file is absent.
```
