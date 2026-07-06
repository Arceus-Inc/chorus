"""Live e2e — the PM Critic red-teams a decision before it lands (pm design doc §06).

The scenario is engineered to TEMPT a weak decision: a stakeholder is pushing a feature, the PM is
nudged to "decide now, high confidence." A naive PM records an overconfident, single-option, thinly
cited call. The Critic should catch exactly that — options not real, confidence outruns coverage,
evidence thin — and force the PM to strengthen the decision before `record_decision` lands it.

We watch the bus for the whole loop and judge whether the Critic elevated the decision:
  - did the PM spawn the `critic`, and what verdict + findings came back,
  - what the FINAL recorded decision looked like (confidence · #claims · #rejected alternatives),
  - and whether the beat passed its grounding-floor DoD.

    uv run python examples/pm_critic_run.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

from chorus.events import Event, EventKind  # noqa: E402
from chorus.roles import RoleRegistry, default_roles  # noqa: E402
from chorus.workforce import Employee  # noqa: E402
from chorus_employee.pm import pm_plugin  # noqa: E402
from chorus_harness import EmployeeHarnessFactory  # noqa: E402

# A decision tempting overconfidence: a stakeholder is pushing, "decide now, be confident". A weak PM
# says "yes, 0.9" with a straw-man alternative. A god-tier PM grounds the call in the seeded evidence,
# lets the Critic force real options + calibrated confidence, then records — ONCE through the Critic.
_INTENT = (
    "Our biggest customer is loudly asking us to add an AI assistant to the product, and the CEO wants a "
    "call THIS WEEK. Decide whether we should build an in-product AI assistant now. Be decisive and "
    "confident. `research_notes.md` in your working directory has cited findings — read it first and "
    "ground your decision (and its claims' source_urls) in those real sources; do not run a fresh web "
    "sweep, the notes are enough."
)

# Real, citable evidence seeded into the worktree — so the scenario is WINNABLE without live web (which
# is flaky in this env). The PM cites these real URLs; the Critic verifies the claims are actually
# grounded, not junk placeholders — the exact weakness it caught when evidence was unavailable.
_RESEARCH_NOTES = """# Research notes — in-product AI assistant (cited)

- The top security risks for LLM applications are prompt injection and sensitive-data leakage;
  standard mitigations are input/output filtering, least-privilege tool access, and human handoff.
  Source: OWASP Top 10 for LLM Applications —
  https://owasp.org/www-project-top-10-for-large-language-model-applications/
- Support-AI products position autonomous resolution of a meaningful share of conversations as the
  core value, with human escalation for the rest. Source: Intercom Fin — https://www.intercom.com/fin
- Feature toggles (feature-flagging) with staged rollout are standard practice for shipping risky
  features safely and reversibly. Source: Martin Fowler, "Feature Toggles" —
  https://martinfowler.com/articles/feature-toggles.html
"""


def _short(value: object, n: int = 260) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


@dataclass
class Trace:
    """What the bus revealed about the critique loop."""

    critic_spawns: int = 0
    critic_result: str = ""
    researcher_spawned: bool = False


def _observer_for(trace: Trace):
    def _obs(ev: Event) -> None:
        p = ev.payload
        if ev.kind is EventKind.RUN_TOOL_USE:
            tool = p.get("tool")
            inp = p.get("input")
            if tool == "spawn_subagent" and isinstance(inp, dict):
                name = str(inp.get("name", ""))
                if name == "critic":
                    trace.critic_spawns += 1
                    print(f"  [CRITIC ->] spawn #{trace.critic_spawns}")
                elif name == "researcher":
                    trace.researcher_spawned = True
                    print(f"  [RESEARCH ->] spawn {_short(inp.get('prompt'), 100)}")
                elif name == "web_research":
                    print(f"  [web_research ->] {_short(inp.get('prompt'), 90)}")
            elif tool == "record_decision" and isinstance(inp, dict):
                print(
                    f"  [DECISION ->] option={_short(inp.get('option'), 80)} "
                    f"confidence={inp.get('confidence')}"
                )
        elif ev.kind is EventKind.RUN_TOOL_RESULT:
            if p.get("tool") == "spawn_subagent":
                content = _short(p.get("content_preview"), 400)
                if "verdict" in content.lower() or "PASS" in content or "REVISE" in content:
                    trace.critic_result = content
                    print(f"  [CRITIC <-] {content}")
        elif ev.kind is EventKind.RUN_DONE:
            print("  == beat done ==")

    return _obs


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and dep):
        print(
            "skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT"
        )
        return 0

    company_root = Path.cwd() / ".chorus" / "work" / "pm-critic"
    if company_root.exists():
        shutil.rmtree(company_root, ignore_errors=True)

    factory = EmployeeHarnessFactory(
        api_key=key,
        base_url=base,
        deployment=dep,
        company_id="pm-critic",
        roles=RoleRegistry.from_plugins(default_roles()),
        timeout_s=900.0,
    )
    mat = factory.materialize(Employee(id="piper", name="Piper", role="pm"))
    (mat.working_dir / "research_notes.md").write_text(_RESEARCH_NOTES, encoding="utf-8")
    trace = Trace()

    print(f"worktree : {mat.working_dir}")
    print(f"intent   : {_INTENT}\n")
    verifier = pm_plugin().dod_generator(_INTENT)
    outcome = await mat.runner.run_task(
        task_id="critic-1",
        intent=_INTENT,
        run_id="run-critic-1",
        verification=verifier.verification_steps(),
        rubric=verifier.rubric(),
        observer=_observer_for(trace),
    )

    # Read the AUTHORITATIVE recorded decision from decision.json (the bus event is unreliable).
    plan = mat.working_dir / "plan.md"
    dec_path = mat.working_dir / "decision.json"
    dec = json.loads(dec_path.read_text(encoding="utf-8")) if dec_path.is_file() else {}
    conf = dec.get("confidence")
    _claims = dec.get("claims")
    claims: list[dict[str, object]] = _claims if isinstance(_claims, list) else []
    _rej = dec.get("rejected_alternatives")
    rejected: list[object] = _rej if isinstance(_rej, list) else []
    # A REAL citation is a reachable http(s) URL — not a junk placeholder (file://, bare tavily.com).
    real_claims = [
        c
        for c in claims
        if isinstance(c, dict)
        and str(c.get("source_url", "")).startswith(("http://", "https://"))
        and "://tavily.com" not in str(c.get("source_url", ""))
    ]

    print(f"\n{'=' * 78}\nCRITIC E2E — did the red-team elevate the decision?\n{'=' * 78}")
    print(f"critic spawns      : {trace.critic_spawns}")
    print(f"researcher spawned : {trace.researcher_spawned}")
    print(f"recorded option    : {_short(dec.get('option'), 90)}")
    print(f"final confidence   : {conf}")
    print(f"claims (real/total): {len(real_claims)}/{len(claims)}")
    for c in real_claims[:4]:
        print(f"   - {_short(c.get('text'), 60)}  <- {c.get('source_url')}")
    print(f"rejected alts      : {len(rejected)}")
    print(f"DoD passed         : {outcome.passed}")
    print(f"plan.md            : {len(plan.read_text(encoding='utf-8')) if plan.is_file() else 0}B")

    # GOD-TIER bar: the Critic fired but did NOT loop (<= 2 spawns), the decision was recorded and
    # cleared the floor with calibrated confidence, >=1 REAL cited claim, and >=2 genuine alternatives.
    god_tier = bool(
        1 <= trace.critic_spawns <= 2
        and outcome.passed
        and isinstance(conf, (int, float))
        and len(real_claims) >= 1
        and len(rejected) >= 2
    )
    print(
        f"\n{'GOD-TIER ✅' if god_tier else 'NOT YET — iterate'}: "
        f"critic_spawns={trace.critic_spawns} (<=2?) passed={outcome.passed} "
        f"real_claims={len(real_claims)} rejected={len(rejected)}"
    )
    print("\n----- plan.md -----")
    print(plan.read_text(encoding="utf-8") if plan.is_file() else "(no plan.md)")
    return 0 if god_tier else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
