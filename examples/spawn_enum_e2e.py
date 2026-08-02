"""Live E2E for spawn_subagent enum + forge veto (lean W1 / W1b).

Cases (pointers):
  1. SCHEMA — tools_wire enum = generalPurpose + Bex Specs
  2. GP_LLM — model must spawn generalPurpose; child returns summary
  3. FORGE_LLM — model told to write test_plan.json without spawn → PRE_TOOL block
  4. FLOW_LLM — live task: GP scout → test_author (evidence) under continue hook

Writes reports/spawn-enum-e2e-report.html with pass/fail + spawn flow diagram.

    uv run python examples/spawn_enum_e2e.py
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dream import build_harness
from dream.roles._manifest import RoleManifest
from dream.session import SessionOptions
from dream.subagents import SubagentSet
from dream.subagents._projection import build_subagent_set
from dream.tools._registry import ToolSource
from dream.tools.builtin import default_registry
from dream.tools.builtin.spawn_subagent import GENERAL_PURPOSE, SpawnSubagentTool

from chorus_cli._env import load_env_file
from chorus_employee.backend_engineer._subagents import (
    API_VERIFIER_SUBAGENT,
    CODE_REVIEWER_SUBAGENT,
    TEST_AUTHOR_SUBAGENT,
)
from chorus_harness._dream_hooks import (
    BeatContextKind,
    BeatContextSection,
    DangerousToolVetoHook,
    EvidenceContinueHook,
    EvidenceForgeVetoHook,
    EvidenceRequirement,
    ProtectedEvidencePath,
    VolatileBeatPacket,
    VolatileBeatPacketHook,
)
from chorus_harness._factory import _project_spec, dream_tool_names

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "spawn-enum-e2e-report.html"
_SPECS = (TEST_AUTHOR_SUBAGENT, CODE_REVIEWER_SUBAGENT, API_VERIFIER_SUBAGENT)
_PARENT_TOOLS = (
    "read_file",
    "write_file",
    "edit_file",
    "grep",
    "glob",
    "run_command",
    "spawn_subagent",
)


@dataclass
class CaseResult:
    id: str
    title: str
    pointer: str
    ok: bool
    detail: str
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Capture:
    events: list[dict[str, Any]] = field(default_factory=list)

    def on_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("kind", ""))
        if kind in {"role.tool.start", "role.tool.result", "role.text", "role.session.opened"}:
            self.events.append(event)


def _log(msg: str = "") -> None:
    print(msg, flush=True)


def _subagent_set() -> SubagentSet:
    parent = frozenset(dream_tool_names(_PARENT_TOOLS))
    agents = [_project_spec(s, parent) for s in _SPECS]
    return build_subagent_set(tier1_agents=agents, parent_tools=parent)


def _build(
    workdir: Path,
    *,
    continue_hook: bool,
    volatile_token: str | None = None,
) -> Any:
    registry = default_registry()
    if registry.get("spawn_subagent") is None:
        registry.register(SpawnSubagentTool(), source=ToolSource.DEFAULT)
    harness = build_harness(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        base_url=os.environ["AZURE_OPENAI_BASE_URL"],
        working_dir=workdir,
        registry=registry,
        skills=False,
        memory=False,
        max_turns=12,
        subagents=_subagent_set(),
    )
    harness.register_hook(DangerousToolVetoHook())
    protected = tuple(
        ProtectedEvidencePath(s.evidence_path, s.name)
        for s in _SPECS
        if s.evidence_path is not None
    )
    if protected:
        harness.register_hook(EvidenceForgeVetoHook(protected))
    if continue_hook:
        evidence = tuple(
            EvidenceRequirement(s.name, s.evidence_path, dict(s.evidence_claim))
            for s in _SPECS
            if s.evidence_path is not None and s.evidence_claim is not None
        )
        if evidence:
            harness.register_hook(
                EvidenceContinueHook(evidence, working_dir=workdir)
            )
    if volatile_token is not None:
        harness.register_hook(
            VolatileBeatPacketHook(
                VolatileBeatPacket(
                    sections=(
                        BeatContextSection(
                            kind=BeatContextKind.INBOX,
                            content=f"## Live checkpoint context\n{volatile_token}",
                        ),
                    )
                )
            )
        )
    return harness


def _manifest() -> RoleManifest:
    return RoleManifest(
        name="generator",
        description="E2E generator with spawn",
        system_prompt=(
            "You are a coding agent with spawn_subagent. "
            "Follow the user instructions exactly. Prefer tool calls over prose. "
            "Do not spawn extra specialists unless the user asks or a tool error tells you to."
        ),
        system_prompt_mode="replace",
        tools=_PARENT_TOOLS,
        permission_mode="dontAsk",
    )


def _spawn_starts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e
        for e in events
        if e.get("kind") == "role.tool.start" and e.get("tool") == "spawn_subagent"
    ]


def _spawn_types(events: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for e in _spawn_starts(events):
        inp = e.get("input") or {}
        out.append(str(inp.get("subagent_type") or inp.get("name") or ""))
    return out


def case_schema() -> CaseResult:
    """Pointer: enum must list generalPurpose + Spec names before any LLM call."""
    from dream.tools.builtin.spawn_subagent import build_spawn_parameters, spawn_type_names

    names = spawn_type_names(_subagent_set())
    schema = build_spawn_parameters(SpawnSubagentTool().input_schema(), _subagent_set())
    enum = schema["properties"]["subagent_type"]["enum"]
    need = {GENERAL_PURPOSE, "test_author", "code_reviewer", "api_verifier"}
    ok = set(enum) == need and enum[0] == GENERAL_PURPOSE
    return CaseResult(
        id="SCHEMA",
        title="Dynamic subagent_type enum",
        pointer="tools_wire enum = generalPurpose + Bex Specs (schema-first action space)",
        ok=ok,
        detail=f"enum={enum} names_helper={names}",
    )


async def case_gp_llm() -> CaseResult:
    """Pointer: model must call spawn_subagent(subagent_type=generalPurpose)."""
    workdir = Path(tempfile.mkdtemp(prefix="spawn-enum-gp-"))
    (workdir / "NOTES.md").write_text(
        "# Notes\nAlpha feature ships Friday.\nBeta blocked on auth.\n",
        encoding="utf-8",
    )
    harness = _build(workdir, continue_hook=False)
    cap = _Capture()
    prompt = (
        "Call spawn_subagent exactly once with:\n"
        f'  subagent_type="{GENERAL_PURPOSE}"\n'
        '  goal="Read NOTES.md and return a 2-bullet summary of blockers and dates."\n'
        '  context="path=NOTES.md"\n'
        "Do not solve it yourself. Do not spawn any other subagent_type. "
        "After the tool returns, reply with DONE and the summary."
    )
    try:
        result = await harness.run_role(
            _manifest(),
            prompt,
            options=SessionOptions(max_turns=8, metadata={}),
            observer=cap,  # type: ignore[arg-type]
        )
        final = result.final_text or ""
        err = ""
    except Exception as exc:
        final, err = "", f"{type(exc).__name__}: {exc}"
    await harness.aclose()
    types = _spawn_types(cap.events)
    spawn_errors = [
        e
        for e in cap.events
        if e.get("kind") == "role.tool.result"
        and e.get("tool") == "spawn_subagent"
        and e.get("is_error")
    ]
    role_errs = [e for e in cap.events if e.get("kind") == "role.error"]
    ok = (
        bool(types)
        and types[0] == GENERAL_PURPOSE
        and types.count(GENERAL_PURPOSE) >= 1
        and not spawn_errors
        and "DONE" in final.upper()
        and not err
    )
    return CaseResult(
        id="GP_LLM",
        title="Live LLM → generalPurpose spawn",
        pointer="Catch-all isolation: GP child, goal+context, parent sees summary only",
        ok=ok,
        detail=(
            f"spawn_types={types} final={final[:240]!r} "
            f"err={err!r} role_errs={role_errs[:2]!r}"
        ),
        events=cap.events,
    )


async def case_forge_llm() -> CaseResult:
    """Pointer: parent write to test_plan.json must be PRE_TOOL blocked (forge veto)."""
    workdir = Path(tempfile.mkdtemp(prefix="spawn-enum-forge-"))
    harness = _build(workdir, continue_hook=False)
    cap = _Capture()
    prompt = (
        "You MUST call write_file with path='test_plan.json' and content "
        '\'{"authored": true, "files": [], "covers": []}\'. '
        "Do not call spawn_subagent. After the write attempt, stop with the error text."
    )
    try:
        result = await harness.run_role(
            _manifest(),
            prompt,
            options=SessionOptions(max_turns=6, metadata={}),
            observer=cap,  # type: ignore[arg-type]
        )
        final = result.final_text or ""
        err = ""
    except Exception as exc:
        final, err = "", f"{type(exc).__name__}: {exc}"
    await harness.aclose()
    blocked = False
    write_results = 0
    for e in cap.events:
        if e.get("kind") != "role.tool.result" or e.get("tool") != "write_file":
            continue
        write_results += 1
        content = str(e.get("content", e.get("content_preview", "")))
        if e.get("is_error") and (
            "forge" in content.lower()
            or "blocked" in content.lower()
            or "spawn_subagent" in content.lower()
            or "evidence" in content.lower()
        ):
            blocked = True
    plan_exists = (workdir / "test_plan.json").exists()
    ok = blocked and not plan_exists and not err
    return CaseResult(
        id="FORGE_LLM",
        title="Live LLM forge → PRE_TOOL veto",
        pointer="Recovery contract: block write + safe_retry=spawn_subagent(subagent_type=test_author)",
        ok=ok,
        detail=(
            f"blocked={blocked} plan_exists={plan_exists} "
            f"write_results={write_results} final={final[:160]!r} err={err!r}"
        ),
        events=cap.events,
    )


async def case_batch_llm() -> CaseResult:
    """Wave B: one tool call fans two typed tasks out concurrently."""
    workdir = Path(tempfile.mkdtemp(prefix="spawn-enum-batch-"))
    (workdir / "NOTES.md").write_text(
        "# Release\nShip Tuesday. Risk: missing auth ownership check.\n",
        encoding="utf-8",
    )
    harness = _build(workdir, continue_hook=False)
    cap = _Capture()
    prompt = (
        "Call spawn_subagent exactly once with tasks=["
        "{subagent_type:'generalPurpose', goal:'Read NOTES.md and report the ship date', "
        "context:'path=NOTES.md'}, "
        "{subagent_type:'code_reviewer', goal:'Review NOTES.md only and return your typed verdict', "
        "context:'path=NOTES.md'}]. Do not call spawn_subagent separately. "
        "After the batch result arrives, reply BATCH_OK and summarize both results."
    )
    try:
        result = await harness.run_role(
            _manifest(),
            prompt,
            options=SessionOptions(max_turns=12, metadata={}),
            observer=cap,  # type: ignore[arg-type]
        )
        final = result.final_text or ""
        err = ""
    except Exception as exc:
        final, err = "", f"{type(exc).__name__}: {exc}"
    await harness.aclose()
    starts = _spawn_starts(cap.events)
    tasks = starts[0].get("input", {}).get("tasks", []) if starts else []
    spawn_errors = [
        event
        for event in cap.events
        if event.get("kind") == "role.tool.result"
        and event.get("tool") == "spawn_subagent"
        and event.get("is_error")
    ]
    ok = len(starts) == 1 and len(tasks) == 2 and not spawn_errors and "BATCH_OK" in final and not err
    return CaseResult(
        id="BATCH_LLM",
        title="Live LLM sync tasks[] fan-out",
        pointer="Wave B: one bounded concurrent batch, typed result in input order",
        ok=ok,
        detail=f"spawn_calls={len(starts)} tasks={len(tasks)} final={final[:220]!r} err={err!r}",
        events=cap.events,
    )


async def case_background_llm() -> CaseResult:
    """Wave C: parent writes a marker while a slow child remains detached."""
    workdir = Path(tempfile.mkdtemp(prefix="spawn-enum-background-"))
    harness = _build(workdir, continue_hook=False)
    cap = _Capture()
    prompt = (
        "Follow this exact sequence. First call spawn_subagent with "
        "subagent_type='generalPurpose', background=true, and goal='Use run_command to run "
        "sleep 3, then return the exact token CHILD_BG_42'. When that tool returns dispatched, "
        "immediately call write_file(path='parent-kept-working.txt', content='PARENT_WORKED') "
        "without waiting or polling. Continue useful work until the child completion arrives as a "
        "new user message. Then reply BACKGROUND_OK and include CHILD_BG_42."
    )
    try:
        result = await harness.run_role(
            _manifest(),
            prompt,
            options=SessionOptions(max_turns=14, metadata={}),
            observer=cap,  # type: ignore[arg-type]
        )
        final = result.final_text or ""
        err = ""
    except Exception as exc:
        final, err = "", f"{type(exc).__name__}: {exc}"
    starts = [
        event
        for event in cap.events
        if event.get("kind") == "role.tool.start"
        and event.get("tool") in {"spawn_subagent", "write_file"}
    ]
    tools = [str(event.get("tool")) for event in starts]
    ordered = "spawn_subagent" in tools and "write_file" in tools and tools.index(
        "spawn_subagent"
    ) < tools.index("write_file")
    marker = workdir / "parent-kept-working.txt"
    ok = (
        ordered
        and marker.is_file()
        and marker.read_text(encoding="utf-8") == "PARENT_WORKED"
        and "BACKGROUND_OK" in final
        and "CHILD_BG_42" in final
        and not err
    )
    await harness.aclose()
    return CaseResult(
        id="BACKGROUND_LLM",
        title="Live LLM background keep-working",
        pointer="Wave C: handle now, parent tool next, completion as later user turn",
        ok=ok,
        detail=f"parent_tools={tools} marker={marker.exists()} final={final[:240]!r} err={err!r}",
        events=cap.events,
    )


async def case_volatile_llm() -> CaseResult:
    """Wave D: a changing packet reaches the model through user-context injection."""
    checkpoint_marker = "VOLATILE_PACKET_73"
    workdir = Path(tempfile.mkdtemp(prefix="spawn-enum-volatile-"))
    harness = _build(workdir, continue_hook=False, volatile_token=checkpoint_marker)
    cap = _Capture()
    try:
        result = await harness.run_role(
            _manifest(),
            "Read the live checkpoint context attached to this user turn. Reply VOLATILE_OK and its exact token. Do not call tools.",
            options=SessionOptions(max_turns=4, metadata={}),
            observer=cap,  # type: ignore[arg-type]
        )
        final = result.final_text or ""
        err = ""
    except Exception as exc:
        final, err = "", f"{type(exc).__name__}: {exc}"
    ok = "VOLATILE_OK" in final and checkpoint_marker in final and not err
    await harness.aclose()
    return CaseResult(
        id="VOLATILE_LLM",
        title="Live LLM volatile user packet",
        pointer="Wave D: roster/inbox/lattice/failures ride USER_PROMPT_SUBMIT",
        ok=ok,
        detail=f"final={final[:220]!r} err={err!r}",
        events=cap.events,
    )


async def case_flow_llm() -> CaseResult:
    """Pointer: full mini flow — GP scout then test_author under evidence continue."""
    workdir = Path(tempfile.mkdtemp(prefix="spawn-enum-flow-"))
    (workdir / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    harness = _build(workdir, continue_hook=True)
    cap = _Capture()
    prompt = (
        "Task: prepare TDD for add() in app.py.\n"
        "1) First spawn_subagent(subagent_type='generalPurpose', "
        "goal='List functions in app.py and suggest one pytest case', context='path=app.py').\n"
        "2) Then spawn_subagent(subagent_type='test_author', "
        "goal='Author a failing pytest for add(2,3)==5 in test_app.py; write test_plan.json', "
        "context='path=app.py').\n"
        "Use those exact subagent_type values. Do not forge test_plan.json yourself."
    )
    try:
        result = await harness.run_role(
            _manifest(),
            prompt,
            options=SessionOptions(max_turns=14, metadata={}),
            observer=cap,  # type: ignore[arg-type]
        )
        final = result.final_text or ""
        err = ""
    except Exception as exc:
        final, err = "", f"{type(exc).__name__}: {exc}"
    await harness.aclose()
    types = _spawn_types(cap.events)
    plan_ok = (workdir / "test_plan.json").exists()
    ok = GENERAL_PURPOSE in types and "test_author" in types and plan_ok and not err
    return CaseResult(
        id="FLOW_LLM",
        title="Live task spawn flow (GP → specialist)",
        pointer="Hybrid ReAct: typed spawn for isolation, then specialist for evidence contract",
        ok=ok,
        detail=(
            f"spawn_types={types} plan={plan_ok} "
            f"final={final[:200]!r} err={err!r}"
        ),
        events=cap.events,
    )


def _live_flow_mermaid(flow: CaseResult | None) -> str:
    """Build mermaid from actual FLOW_LLM spawn sequence (not a static cartoon)."""
    lines = [
        "flowchart TD",
        "  U[User intent: TDD for add] --> G[Generator session]",
    ]
    if not flow or not flow.events:
        lines.extend(
            [
                "  G -->|spawn_subagent| R{subagent_type enum}",
                f"  R -->|{GENERAL_PURPOSE}| GP[Fresh delegate child]",
                "  R -->|test_author| TA[Inline co-writer]",
                "  GP -->|summary| G",
                "  TA -->|test_plan.json| G",
            ]
        )
        return "\n".join(lines)

    types = _spawn_types(flow.events)
    prev = "G"
    seen: dict[str, int] = {}
    for i, t in enumerate(types):
        seen[t] = seen.get(t, 0) + 1
        nid = f"S{i}"
        label = t.replace('"', "")
        kind = "delegate" if t == GENERAL_PURPOSE else (
            "inline+evidence" if t == "test_author" else "delegate critic"
        )
        lines.append(f'  {prev} -->|spawn #{i + 1}| {nid}["{label}<br/>{kind}"]')
        lines.append(f"  {nid} -->|summary / artifacts| G")
        prev = "G"
    if (flow.ok and "test_author" in types) or "plan=True" in flow.detail:
        lines.append("  G --> DONE[Beat evidence ready]")
        lines.append("  DONE:::ok")
    lines.append("  classDef ok fill:#d8eddf,stroke:#1d6b3c")
    # architecture legend
    lines.append(
        f"  LEG[enum: {GENERAL_PURPOSE} + Specs] -.-> G"
    )
    return "\n".join(lines)


def _architecture_mermaid() -> str:
    return "\n".join(
        [
            "flowchart LR",
            "  P[Parent generator] -->|spawn_subagent| E{subagent_type}",
            f"  E -->|{GENERAL_PURPOSE}| GP[Hermes delegate<br/>goal+context firewall]",
            "  E -->|test_author| TA[Inline co-writer<br/>writes evidence]",
            "  E -->|code_reviewer / api_verifier| CR[Hermes delegate critic]",
            "  GP -->|budgeted summary| P",
            "  TA -->|test_plan.json + provenance| P",
            "  CR -->|verdict + provenance| P",
            "  P -->|forge write_file evidence| V[EvidenceForgeVetoHook<br/>PRE_TOOL block]",
            "  V -->|safe_retry hint| P",
        ]
    )


def _write_html(cases: list[CaseResult], elapsed: float) -> None:
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    rows = "".join(
        f"<tr class='{'ok' if c.ok else 'bad'}'><td><code>{c.id}</code></td>"
        f"<td>{html.escape(c.title)}</td><td>{html.escape(c.pointer)}</td>"
        f"<td>{'PASS' if c.ok else 'FAIL'}</td>"
        f"<td><pre>{html.escape(c.detail)}</pre></td></tr>"
        for c in cases
    )
    flow = next((c for c in cases if c.id == "FLOW_LLM"), None)
    live = _live_flow_mermaid(flow)
    arch = _architecture_mermaid()
    timeline = ""
    for c in cases:
        if not c.events:
            continue
        steps = []
        for e in c.events:
            if e.get("kind") != "role.tool.start":
                continue
            inp = e.get("input") or {}
            label = e.get("tool")
            if label == "spawn_subagent":
                label = f"spawn:{inp.get('subagent_type') or inp.get('name')}"
            steps.append(
                f"<li><code>{html.escape(str(label))}</code> "
                f"{html.escape(json.dumps(inp)[:140])}</li>"
            )
        timeline += (
            f"<h3>{html.escape(c.id)} tool timeline "
            f"<span class='meta'>(includes nested child tools via observer)</span></h3>"
            f"<ol>{''.join(steps) or '<li>(none)</li>'}</ol>"
        )

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Spawn enum E2E report</title>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";
  mermaid.initialize({{ startOnLoad: true, theme: "neutral" }});
</script>
<style>
  body {{ font-family: "Source Sans 3", system-ui, sans-serif; max-width: 980px; margin: 2rem auto; padding: 0 1rem; background: #e8e4dc; color: #17140f; }}
  h1 {{ font-family: Georgia, serif; }}
  table {{ width: 100%; border-collapse: collapse; background: #faf7f2; border: 1px solid #cfc5b8; font-size: 0.88rem; }}
  th, td {{ border-bottom: 1px solid #cfc5b8; padding: 0.5rem; vertical-align: top; text-align: left; }}
  tr.ok td:nth-child(4) {{ color: #1d6b3c; font-weight: 700; }}
  tr.bad td:nth-child(4) {{ color: #8f1f33; font-weight: 700; }}
  pre {{ white-space: pre-wrap; font-size: 0.75rem; margin: 0; }}
  .mermaid {{ background: #faf7f2; border: 1px solid #cfc5b8; padding: 1rem; }}
  .meta {{ color: #655c52; font-size: 0.9rem; }}
  .pointers {{ background: #faf7f2; border-left: 4px solid #2f5d50; padding: 0.75rem 1rem; }}
</style></head><body>
<h1>Spawn enum x Hermes child — live E2E</h1>
<p class="meta">elapsed {elapsed:.1f}s · {sum(1 for c in cases if c.ok)}/{len(cases)} passed · branch feat/hooks-parallel-subagents</p>
<div class="pointers">
<strong>Harness pointers under test</strong>
<ol>
<li><code>SCHEMA</code> — schema-first action space: dynamic <code>subagent_type</code> enum</li>
<li><code>GP_LLM</code> — catch-all isolation via Hermes delegate (goal+context)</li>
<li><code>FORGE_LLM</code> — PRE_TOOL forge veto + recovery hint to spawn</li>
<li><code>BATCH_LLM</code> — bounded synchronous <code>tasks[]</code> fan-out</li>
<li><code>BACKGROUND_LLM</code> — detached child + parent keeps working + idle delivery</li>
<li><code>VOLATILE_LLM</code> — changing beat packet injected on the user turn</li>
<li><code>FLOW_LLM</code> — live task: GP → test_author with evidence continue</li>
</ol>
</div>
<h2>Results</h2>
<table>
<thead><tr><th>ID</th><th>Case</th><th>Harness pointer</th><th>Result</th><th>Detail</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<h2>Architecture: how spawn routes</h2>
<pre class="mermaid">
{arch}
</pre>
<h2>Live FLOW_LLM spawn sequence</h2>
<pre class="mermaid">
{live}
</pre>
{timeline}
</body></html>"""
    _REPORT.write_text(doc, encoding="utf-8")
    _log(f"report → {_REPORT}")


async def _main_async() -> int:
    load_env_file(Path(__file__).resolve().parents[1] / ".env", override=True)
    if not all(
        os.environ.get(k)
        for k in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_DEPLOYMENT")
    ):
        _log("skipping: need AZURE_OPENAI_* in .env")
        return 0

    t0 = time.time()
    cases: list[CaseResult] = [case_schema()]
    _log(f"[{cases[-1].id}] {'PASS' if cases[-1].ok else 'FAIL'} {cases[-1].detail}")

    for runner in (
        case_gp_llm,
        case_forge_llm,
        case_batch_llm,
        case_background_llm,
        case_volatile_llm,
        case_flow_llm,
    ):
        c = await runner()
        cases.append(c)
        _log(f"[{c.id}] {'PASS' if c.ok else 'FAIL'} {c.detail}")

    elapsed = time.time() - t0
    _write_html(cases, elapsed)
    return 0 if all(c.ok for c in cases) else 1


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
