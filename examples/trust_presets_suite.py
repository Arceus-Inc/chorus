"""The §4 trust-presets suite — standard untouched, low-trust contained, fail-closed, end to end.

Trust is a pure per-beat narrowing (no model, no keys): each scenario runs a role config through
``apply_trust`` for a task and captures the harness posture (sandbox / permission mode) before and
after — or the denial. Writes ``reports/m1-trust-presets.html``.

    uv run python examples/trust_presets_suite.py
"""

from __future__ import annotations

import html
import sys
from dataclasses import dataclass
from pathlib import Path

from chorus.ledger import OriginKind, Task, TaskStatus
from chorus.roles import RoleBeatConfig
from chorus.trust import TrustDenied, TrustPolicy, TrustPreset
from chorus_harness import apply_trust

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m1-trust-presets.html"

# An engineer's standing posture: unrestricted + default — the most an autonomous engineer may do.
_ENGINEER = RoleBeatConfig(
    system_prompt="you are an engineer",
    sandbox="unrestricted",
    permission_mode="default",
    isolation="worktree",
    env=(("GITHUB_TOKEN", "ref:github_token"),),
)
_LOW_TRUST_ORIGINS = frozenset({OriginKind.STRANDED_RECOVERY})


@dataclass
class Scenario:
    name: str
    before: str
    after: str
    note: str


def _posture(config: RoleBeatConfig) -> str:
    return f"{config.sandbox} / {config.permission_mode}"


def _task(**over: object) -> Task:
    base: dict[str, object] = {"id": "t1", "intent": "work", "status": TaskStatus.IN_PROGRESS}
    base.update(over)
    return Task(**base)  # type: ignore[arg-type]


def _scenario(name: str, *, config: RoleBeatConfig, task: Task, policy: TrustPolicy, note: str) -> Scenario:
    before = _posture(config)
    try:
        after = _posture(apply_trust(config, task=task, policy=policy))
    except TrustDenied as exc:
        after = f"DENIED — {exc}"
    return Scenario(name, before, after, note)


def _scenarios() -> list[Scenario]:
    boundary = {"secret_ref_allowlist": ["ref:github_token"]}
    return [
        _scenario(
            "standard task",
            config=_ENGINEER, task=_task(), policy=TrustPolicy(),
            note="a trusted task keeps the role's full posture — untouched.",
        ),
        _scenario(
            "explicit low_trust_review",
            config=_ENGINEER,
            task=_task(trust_preset=TrustPreset.LOW_TRUST_REVIEW.value, trust_boundary=boundary),
            policy=TrustPolicy(),
            note="a hostile-input task is boxed in: read-only + plan-mode, no network.",
        ),
        _scenario(
            "policy-derived low-trust",
            config=_ENGINEER,
            task=_task(origin_kind=OriginKind.STRANDED_RECOVERY, trust_boundary=boundary),
            policy=TrustPolicy(low_trust_origins=_LOW_TRUST_ORIGINS),
            note="the policy auto-contains a flagged origin — no explicit preset needed.",
        ),
        _scenario(
            "low-trust, no boundary",
            config=_ENGINEER,
            task=_task(trust_preset=TrustPreset.LOW_TRUST_REVIEW.value),
            policy=TrustPolicy(),
            note="fail-closed: low-trust with no concrete scope is denied, not run.",
        ),
        _scenario(
            "low-trust, inline secret",
            config=RoleBeatConfig(
                system_prompt="x", sandbox="unrestricted", permission_mode="default",
                isolation="worktree", env=(("AWS_SECRET", "raw-key-value"),),
            ),
            task=_task(trust_preset=TrustPreset.LOW_TRUST_REVIEW.value, trust_boundary=boundary),
            policy=TrustPolicy(),
            note="fail-closed: a raw secret in env is rejected — low-trust needs a ref: handle.",
        ),
    ]


def _after_class(after: str) -> str:
    if after.startswith("DENIED"):
        return "no"
    return "ok" if "read-only" in after else "muted"


def _render(scenarios: list[Scenario]) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value))

    rows = "".join(
        f"""<tr>
          <td>{esc(s.name)}</td>
          <td><code>{esc(s.before)}</code></td>
          <td class="arrow">&rarr;</td>
          <td><code class="{_after_class(s.after)}">{esc(s.after)}</code></td>
          <td class="note">{esc(s.note)}</td>
        </tr>"""
        for s in scenarios
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>§4 trust presets — standard / low_trust_review, fail-closed</title><style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;background:#0f1115;color:#e6e8eb}}
h1{{font-size:1.4rem}} .lead{{color:#9aa0a6;max-width:78ch}}
table{{width:100%;border-collapse:collapse;margin-top:1.2rem;font-size:.9rem}}
th{{text-align:left;color:#9aa0a6;font-weight:500;font-size:.74rem;text-transform:uppercase;
letter-spacing:.05em;padding:.4rem .5rem;border-bottom:1px solid #262b33}}
td{{padding:.5rem .5rem;border-bottom:1px solid #1c2027;vertical-align:top}}
code{{background:#16191f;padding:.1rem .4rem;border-radius:4px}}
code.ok{{color:#4ade80}} code.no{{color:#f87171}}
.arrow{{color:#6b7280;text-align:center}} .note{{color:#9aa0a6;font-size:.82rem}}
.summary{{display:inline-block;margin-top:1rem;padding:.4rem .9rem;border-radius:999px;
background:#0e3a23;color:#4ade80;font-weight:700}}
</style></head><body>
<h1>§4 trust presets — a hostile-input beat is boxed in; ambiguity is denied</h1>
<p class="lead">A task's effective trust is the intersection of the employee, task, and run layers
(narrower wins), applied at chorus's per-beat materialize boundary. <code>standard</code> keeps the
role's posture; <code>low_trust_review</code> clamps to read-only + plan-mode + no-net; and anything
ambiguous — a low-trust beat with no concrete boundary, or a raw inline secret — is denied, not run.</p>
<div class="summary">{len(scenarios)} scenarios · standard untouched · low-trust contained · fail-closed</div>
<table>
<thead><tr><th>scenario</th><th>sandbox / mode before</th><th></th><th>after</th>
<th>what it shows</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<footer class="note" style="margin-top:1.2rem">examples/trust_presets_suite.py · chorus §4 trust
presets (applied at the existing materialize boundary — no dream change)</footer>
</body></html>"""


def main() -> int:
    scenarios = _scenarios()
    for s in scenarios:
        sys.stdout.write(f"{s.name:28} {s.before:24} -> {s.after}\n")
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(_render(scenarios), encoding="utf-8")
    sys.stdout.write(f"\nHTML report: {_REPORT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
