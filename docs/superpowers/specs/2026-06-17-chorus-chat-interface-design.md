# Design: org-native chat interface for chorus

**Date:** 2026-06-17
**Status:** approved (build)

## Motivation

dream ships an interactive `chat` REPL (`python -m dream.repl chat`): a conversational
prompt loop that streams a model's reply and prints a token/timing footer. chorus today
has only a **command-driven** console (`chorus_cli`) — verbs like `hire`, `submit`,
`assign`, `tick`. This adds the dream-style **conversational** experience to chorus, but
native to chorus's domain: you chat with an **employee**, and the reply is a real **beat**
run through dream.

## What "chat" means in chorus

You `chat <employee_id>` and drop into a conversational sub-loop. Each line you type:

1. is **recorded** as a `Message` linked to the turn's task (durable audit / transcript);
2. **auto-promotes to a task** so a beat can run (see the rule below);
3. runs **one scheduler `tick_once` + `drain`** against a memory-enabled, employee-scoped
   beat service — the real dispatch path, so budget / pause / invokability gates all apply;
4. **streams** the employee's work live (`run.text` deltas as prose, `run.tool_use` /
   `run.tool_result` as dim action lines) via a chat-local render bus;
5. prints a **verdict footer** (task status, run status, this turn's spend).

Continuity is via **employee memory**: the chat's beat service builds the dream harness
with `memory=True` and a stable per-employee working dir, so the employee accumulates
memory across turns and across sessions.

### Why a beat, and why record the message separately

- A beat only dispatches for a wake carrying a `task_id` (`Scheduler.tick` releases any
  wake without one). A bare `deliver_message` wakes the employee with a `message_id` wake
  only — no beat. So a conversational reply **must** go through a task.
- `deliver_message` also enqueues a coalesced no-`task_id` wake that would *compete* with
  the task wake under `max_concurrent_runs=1` (a single `tick_once` claims one wake). So
  chat records the line with `ledger.messages.send(...)` **directly** (no wake) and drives
  the beat via the task wake alone.

### Auto-promote rule

`open_for_assignee(employee_id)` returns the most-recent **workable** task assigned to the
employee — status in `{todo, in_progress, in_review}` — or `None`.

- **None → promote:** `messages.send(...)`; `tasks.submit(Task(intent=line))`;
  `assign_task(...)` (enqueues a `task_assigned` wake with `task_id`).
- **Found → attach:** `messages.send(...)` linked to that task; enqueue a `recovery` wake
  for its `task_id` (deduped against any already-queued wake for that task) so the beat
  resumes with the steer.

In the synchronous console a turn's beat lands before the next prompt, so a passed task is
`done` (terminal) and the next line promotes a fresh task — continuity carried by memory.
The attach branch covers a residual workable task (e.g. a repair-ladder re-wake left it
`todo`).

## Components (new / changed)

| Unit | File | Responsibility |
|------|------|----------------|
| `open_for_assignee` | `chorus/ledger/repos/tasks.py` | most-recent workable task for an employee (new read query) |
| `ChatRenderBus` | `chorus_cli/_chat.py` | `EventBus` subclass; `emit(Event)` renders the streamed reply |
| `ChatBeatService` | `chorus_cli/_chat.py` | sync bridge: `run_turn()` = `asyncio.run(tick_once + drain)` over a wired `Scheduler` |
| turn + sub-loop | `chorus_cli/_chat.py` | `run_chat(...)`, `_ensure_task(...)`, footer + slash commands |
| `build_chat_service` / `chat_service_from_env` | `chorus_cli/_beats.py` | composition root: memory harness + scheduler wired with the render bus |
| `chat` verb | `chorus_cli/_commands.py` | validate employee, build service, enter sub-loop |
| `input_func` field | `chorus_cli/_context.py` | `CliSession.input_func` so the sub-loop reads input |

`ChatRenderBus` subclasses `chorus.observability.EventBus` (the `Scheduler` only ever calls
`.emit`), overriding `emit` to render; `subscribe`/`replay` stay the inherited stubs. It does
**not** implement the spec-08 fan-out/log — it's a chat-local renderer, and nothing here
fakes or unblocks the real `EventBus` work.

## Render mapping (`ChatRenderBus.emit`)

- `RUN_TEXT` → write `payload["text"]` to the stream (streamed prose; role marker on change)
- `RUN_TOOL_USE` → dim line `[tool {payload["tool"]} …]`
- `RUN_TOOL_RESULT` → dim line `[→ ok|error]` from `payload["is_error"]`
- `RUN_STARTED` / `RUN_DONE` / `RUN_EVALUATED` → optional status markers

## Slash commands (inside chat)

`/quit` `/exit` (leave chat → back to console), `/help`, `/info` (employee, active task,
model, working dir), `/task` (current/last task + runs + DoD), `/transcript` (this session's
lines). No `/stream` toggle — streaming is the point.

## Error handling

- Unknown / terminated employee → reported, never enters the loop; paused → warns the beat
  will be gated.
- No Azure creds → `chat` prints the same "no beat runner configured" guidance as `tick`
  and stays out of the loop.
- Beat errors / blocks → the scheduler strands/repairs; chat renders the resulting status in
  the footer and keeps looping (a failed turn never crashes the console).
- `EOFError` / `Ctrl-C` → leave chat cleanly, return to the console.
- Budget-gated turn → footer says gated; `/quit` then `budget raise`.

## Testing

- **Unit:** `ChatRenderBus` rendering from synthetic `Event`s; `open_for_assignee`;
  `_ensure_task` attach-vs-promote against an in-memory ledger.
- **Integration:** the full turn / sub-loop against a **fake `BeatRunner`** that emits a
  scripted `Event` stream via the injected observer and returns a `BeatOutcome` — driven
  with a scripted `input_func` + captured `StringIO`, exactly like the existing console
  tests. Asserts: message recorded, task created/attached, events rendered, footer correct,
  `/quit` exits.
- Real-provider path stays manual (like `tick` / `examples/real_beat.py`).

## Out of scope

- The spec-08 `EventBus` fan-out/log (stays a stub).
- Cross-employee chat, multi-employee rooms, async/background beats in the console.
- Persisting an explicit transcript table — the mailbox + memory are the record.
