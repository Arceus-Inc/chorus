"""The dream beat adapter — run a beat through a dream Harness (spec 03 §3, spec 05 dream seam).

A concrete :class:`~chorus.heartbeat.BeatRunner`: one ``harness.run_task`` call, its result mapped to
the chorus :class:`~chorus.heartbeat.BeatOutcome` the beat lands. The verdict rule is **passed iff the
plan fully completed** — every step in dream's final ledger is ``done``.

This module deliberately does **not** import dream. It depends only on the narrow read-only shape of
dream's ``RunTaskResult`` (the protocols below), so the SDK import stays at the composition root
(``examples/real_beat.py`` / Arceus) and the adapter is a pure, fully testable unit.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, replace
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from inspect import isawaitable
from pathlib import Path
from typing import Any, Protocol

from chorus.adapters._failure import failure_outcome
from chorus.adapters._observer import DreamObserverBridge
from chorus.adapters._pricing import TokenPricing, UsageView
from chorus.adapters._trace import beat_subagent_stats, sidecar_traces
from chorus.events import Event
from chorus.heartbeat import BeatContext, BeatDisposition, BeatOutcome
from chorus.heartbeat._todo_flush import (
    TODO_FLUSH_REMAINING_FRACTION,
    clear_todo_flush_nudge,
    write_todo_flush_nudge,
)
from chorus.outcomes import VerificationStep
from chorus.roles._manifest import DEFAULT_BEAT_TIMEOUT_S


def _utc_now() -> datetime:
    return datetime.now(UTC)


_REVIEW_FINGERPRINT_EXCLUDED_PATHS = frozenset(
    {
        "TODO.md",
        "api_verdict.json",
        "code_quality/report.json",
        "review_verdict.json",
        "security_scan/report.json",
        "test_evidence/manifest.json",
        "test_evidence/red.json",
        "test_evidence/red.txt",
        "test_plan.json",
    }
)
_REVIEW_FINGERPRINT_EXCLUDED_PREFIXES = (
    ".dream/",
    ".harness/",
    "docs/evals/",
    "docs/exec-plans/active/",
    "test_evidence/",
)


def _is_review_fingerprint_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    return normalized not in _REVIEW_FINGERPRINT_EXCLUDED_PATHS and not normalized.startswith(
        _REVIEW_FINGERPRINT_EXCLUDED_PREFIXES
    )


def _worktree_fingerprint(root: Path) -> str:
    """Hash the Git-visible worktree state, with a filesystem fallback for bare test roots."""
    digest = sha256()
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listed.returncode == 0 and status.returncode == 0:
        relative_paths = sorted(
            os.fsdecode(raw)
            for raw in listed.stdout.split(b"\0")
            if raw and _is_review_fingerprint_path(os.fsdecode(raw))
        )
    else:
        relative_paths = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and _is_review_fingerprint_path(path.relative_to(root).as_posix())
        )
    for relative_path in relative_paths:
        digest.update(relative_path.encode("utf-8", errors="surrogateescape"))
        path = root / relative_path
        if not path.exists():
            digest.update(b"\0missing\0")
        elif path.is_symlink():
            digest.update(b"\0link\0" + os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(b"\0file\0" + path.read_bytes())
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(value, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            with suppress(FileNotFoundError):
                Path(temporary_name).unlink()


class DreamStepStatus(StrEnum):
    """The dream planner step statuses a beat's verdict reads (mirrors dream ``planner.StepStatus``)."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class RunStep(Protocol):
    """One planned step — the adapter reads only its status."""

    @property
    def status(self) -> str: ...


class RunLedger(Protocol):
    """The final plan ledger — the adapter reads only its steps."""

    @property
    def steps(self) -> Sequence[RunStep]: ...


class RunSprint(Protocol):
    """One sprint's recorded evaluation outcome (``pass`` / ``needs-changes`` / ``fail`` / unset)."""

    @property
    def outcome(self) -> str | None: ...


class RunResult(Protocol):
    """The minimal read-only surface of dream's ``RunTaskResult`` the adapter depends on."""

    @property
    def final_ledger(self) -> RunLedger: ...

    @property
    def sprints(self) -> Sequence[RunSprint]: ...

    @property
    def usage_by_model(self) -> Mapping[str, UsageView]:
        """Per-model token usage dream metered for the run (empty on older dream pins → cost 0)."""
        ...


class _DreamObserver(Protocol):
    """dream's ``RunTaskObserver`` shape — a sink for the engine's dict event stream (spec 05 §4)."""

    def on_event(self, event: dict[str, Any]) -> None: ...


class TaskHarness(Protocol):
    """A built dream Harness — the one call a beat makes (the adapter's sole dependency)."""

    async def run_task(
        self,
        *,
        task_id: str | None = None,
        intent: str,
        verification_steps: tuple[dict[str, str], ...] | None = None,
        observer: Any | None = None,
        max_sprints: int | None = None,
        harness_dir: Path | None = None,
        rubric: str | None = None,
    ) -> RunResult: ...


class _ReasoningRecorder:
    """Capture the agent's account for the episodic raw record (spec 07 §3), then forward downstream.

    dream calls ``on_event(dict)`` for every engine event. Its lifecycle/handoff kinds (``planner.*``,
    ``handoff.*``) are structural noise; the *reasoning* lives in ``role.text`` (what the model
    concluded) and its *actions* in ``role.tool.start`` / ``role.tool.result`` (the tool it called, its
    args, and the output preview). We keep exactly those and drop the rest, so the record is the
    agent's own account — not the orchestration log. Every event is still forwarded to the chorus
    observer bridge (when present) so liveness/subagent witnessing is unaffected.
    """

    _KEPT_KINDS = frozenset({"role.text", "role.tool.start", "role.tool.result"})

    def __init__(
        self,
        forward: Callable[[dict[str, Any]], None] | None,
        *,
        working_dir: Path | None = None,
        evidence_subagents: frozenset[str] = frozenset(),
    ) -> None:
        self._forward = forward
        self._events: list[dict[str, Any]] = []
        self._working_dir = working_dir
        self._evidence_subagents = evidence_subagents
        self._pending_subagents: list[tuple[str, str]] = []
        self._subagent_results: dict[str, tuple[str, bool, str, str]] = {}

    def on_event(self, event: dict[str, Any]) -> None:
        if str(event.get("kind", "")) in self._KEPT_KINDS:
            self._events.append(event)
        if event.get("tool") == "spawn_subagent":
            if event.get("kind") == "role.tool.start":
                _inp = dict(event.get("input") or {})
                name = str(_inp.get("subagent_type") or _inp.get("name") or "subagent")
                before_hash = (
                    _worktree_fingerprint(self._working_dir)
                    if name in self._evidence_subagents and self._working_dir is not None
                    else ""
                )
                self._pending_subagents.append((name, before_hash))
            elif event.get("kind") == "role.tool.result":
                name, before_hash = (
                    self._pending_subagents.pop(0) if self._pending_subagents else ("subagent", "")
                )
                if name in self._evidence_subagents and self._working_dir is not None:
                    content = str(event.get("content", event.get("content_preview", "")))
                    self._subagent_results[name] = (
                        content,
                        bool(event.get("is_error", False)),
                        before_hash,
                        _worktree_fingerprint(self._working_dir),
                    )
        if self._forward is not None:
            self._forward(event)

    def as_jsonl(self) -> str:
        """The captured account as JSON lines — one reasoning/action event per line."""
        return "\n".join(
            json.dumps(event, default=str, ensure_ascii=False) for event in self._events
        )

    def subagent_results(self) -> dict[str, tuple[str, bool, str, str]]:
        """Return evidence results with their pre-run and completion worktree fingerprints."""
        return dict(self._subagent_results)


def to_beat_outcome(result: RunResult, *, pricing: TokenPricing | None = None) -> BeatOutcome:
    """Map a dream run result to the chorus verdict: ``passed`` iff every plan step is ``done``.

    An empty plan is never a silent pass. ``outcome`` carries the step tally and the per-sprint
    evaluation outcomes for the audit/DoD record; ``summary`` is a one-line human gloss. When
    ``pricing`` is supplied the beat's spend is priced from dream's metered usage and lands on
    :attr:`BeatOutcome.cost_cents` for the budget gates; without it the beat is unpriced (cost 0).
    """
    steps = list(result.final_ledger.steps)
    done = sum(1 for step in steps if step.status == DreamStepStatus.DONE)
    blocked = sum(1 for step in steps if step.status == DreamStepStatus.BLOCKED)
    passed = len(steps) > 0 and done == len(steps)
    usage = result.usage_by_model
    cost_cents = pricing.cost_cents(usage) if pricing is not None else 0
    model = "+".join(sorted(usage))  # "" / "gpt-5.2" / "gpt-4+gpt-5.2"
    input_tokens = sum(u.input_tokens for u in usage.values())
    output_tokens = sum(u.output_tokens for u in usage.values())
    outcome: dict[str, object] = {
        "steps_total": len(steps),
        "steps_done": done,
        "steps_blocked": blocked,
        "sprint_outcomes": [sprint.outcome for sprint in result.sprints],
        "cost_cents": cost_cents,
    }
    summary = (
        f"plan complete: {done}/{len(steps)} steps done"
        if passed
        else f"plan incomplete: {done}/{len(steps)} done, {blocked} blocked"
    )
    return BeatOutcome(
        passed=passed,
        outcome=outcome,
        summary=summary,
        cost_cents=cost_cents,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class DreamBeatRunner:
    """Run a beat through a dream Harness and land its result as a :class:`BeatOutcome` (spec 03 §3).

    The four-way failure contract (spec 05 §5) is enforced here: a clean return is priced and mapped
    by :func:`to_beat_outcome`; a ``dream.TaskCancelled`` becomes a ``CANCELLED`` disposition and a
    ``dream.RunTaskError`` (or any other fault) an ``ERRORED`` one — a raise is never swallowed into a
    silent pass. ``asyncio.CancelledError`` propagates so structured cancellation unwinds cleanly.
    When a chorus ``observer`` is supplied it is bridged into dream so chorus witnesses the run's
    structured event stream (spec 05 §4).
    """

    def __init__(
        self,
        harness: TaskHarness,
        *,
        pricing: TokenPricing | None = None,
        max_sprints: int | None = 1,
        timeout_s: float | None = DEFAULT_BEAT_TIMEOUT_S,
        working_dir: str | Path | None = None,
        employee_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
        # name -> (artifact_path, required_claim[, evidence_read_only=True])
        # e.g. {"test_author": ("test_plan.json", {"authored": True}, False)}
        subagent_evidence: Mapping[
            str,
            tuple[str, Mapping[str, object]] | tuple[str, Mapping[str, object], bool],
        ]
        | None = None,
    ) -> None:
        self._harness = harness
        self._pricing = pricing
        self._max_sprints = max_sprints
        self._timeout_s = timeout_s
        self._working_dir = Path(working_dir) if working_dir is not None else None
        self._employee_id = employee_id
        self._clock = clock or _utc_now
        self._subagent_evidence: dict[str, tuple[str, dict[str, object], bool]] = {}
        for name, requirement in (subagent_evidence or {}).items():
            path = requirement[0]
            claim = requirement[1]
            read_only = requirement[2] if len(requirement) == 3 else True
            self._subagent_evidence[name] = (path, dict(claim), read_only)

    @property
    def working_dir(self) -> Path | None:
        """The harness working directory where per-beat context files are written, if configured."""
        return self._working_dir

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: tuple[VerificationStep, ...] = (),
        rubric: str = "",
        observer: Callable[[Event], None] | None = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        # Drop the per-beat context the worktree's capability tools read (which task/run they act for).
        # Written before the harness runs so a tool firing mid-beat finds it (spec 06 §4, M3).
        if self._working_dir is not None and run_id is not None and self._employee_id is not None:
            BeatContext(task_id=task_id, run_id=run_id, employee_id=self._employee_id).write(
                self._working_dir
            )
        # Bridge the chorus observer into dream so the run's structured events reach the event log
        # (spec 05 §4); without one, dream runs silent (no bridge allocated).
        bridge = (
            DreamObserverBridge(observer, task_id=task_id, clock=self._clock)
            if observer is not None
            else None
        )
        # Record the agent's reasoning + actions for the episodic raw record, forwarding to the bridge
        # so liveness witnessing is unchanged (spec 07 §3). It is dream's observer for this beat.
        recorder = _ReasoningRecorder(
            bridge.on_event if bridge is not None else None,
            working_dir=self._working_dir,
            evidence_subagents=frozenset(self._subagent_evidence),
        )

        def _with_record(outcome: BeatOutcome) -> BeatOutcome:
            guarded = self._guard_subagent_evidence(outcome, recorder.subagent_results())
            return replace(guarded, raw_record=recorder.as_jsonl())

        # Snapshot existing sidecar traces so we can isolate *this* beat's trace afterwards and recover
        # the subagent counters dream drops before they reach the observer (see ``_trace``).
        traces_before = (
            sidecar_traces(self._working_dir) if self._working_dir is not None else frozenset()
        )
        # dream's verification step ``kind`` must be one of {test, lint, eval} (its SprintContract
        # rejects anything else and the whole beat errors before the generator). A chorus Command DoD
        # is a generic shell command, so it maps to ``eval``; the oracle runs ``command`` regardless of
        # the kind label.
        steps: tuple[dict[str, str], ...] = tuple(
            {"kind": "eval", "command": step.command} for step in verification
        )
        # dream gets a **stable task identity** (the chorus task_id) with
        # PlanAdmission.RESUME so a later tick on the same task continues
        # needs-changes repair in-session (Hermes-simple). Fresh run_ids used to
        # mint a new Dream task every beat, which cold-started the planner and
        # dropped carry-forward. RESUME skips the planner when a ledger already
        # exists; the first beat still plans once.
        from dream.runner import PlanAdmission

        dream_task_id = task_id
        nudge_task: asyncio.Task[None] | None = None
        if self._working_dir is not None:
            clear_todo_flush_nudge(self._working_dir)
        if self._working_dir is not None and self._timeout_s is not None and self._timeout_s > 0:
            nudge_task = asyncio.create_task(self._arm_todo_flush_nudge())
        try:
            if self._working_dir is None:
                run = self._harness.run_task(
                    task_id=dream_task_id,
                    intent=intent,
                    verification_steps=steps,
                    observer=recorder,
                    max_sprints=self._max_sprints,
                    rubric=rubric,
                    plan_admission=PlanAdmission.RESUME,
                )
            else:
                run = self._harness.run_task(
                    task_id=dream_task_id,
                    intent=intent,
                    verification_steps=steps,
                    observer=recorder,
                    max_sprints=self._max_sprints,
                    harness_dir=self._working_dir / ".harness",
                    rubric=rubric,
                    plan_admission=PlanAdmission.RESUME,
                )
            result = await asyncio.wait_for(run, timeout=self._timeout_s)
        except TimeoutError as exc:
            if verification and await self._verification_passed(verification):
                return _with_record(
                    BeatOutcome(
                        passed=True,
                        summary="objective verification passed after dream timeout",
                        outcome={
                            "steps_total": len(verification),
                            "steps_done": len(verification),
                            "verified_after_timeout": True,
                            "timeout_s": self._timeout_s,
                        },
                    )
                )
            return _with_record(failure_outcome(exc))
        except asyncio.CancelledError:
            raise  # structured cancellation must propagate — never classify it as a beat outcome
        except (
            Exception
        ) as exc:  # typed by failure_outcome — a beat never crashes the dispatch loop
            return _with_record(failure_outcome(exc))
        finally:
            if nudge_task is not None:
                nudge_task.cancel()
                with suppress(asyncio.CancelledError):
                    await nudge_task
            if self._working_dir is not None:
                clear_todo_flush_nudge(self._working_dir)
            await self._close_harness()
        outcome = self._attach_subagent_stats(
            to_beat_outcome(result, pricing=self._pricing), traces_before
        )
        if not outcome.passed and verification and await self._verification_passed(verification):
            return _with_record(
                BeatOutcome(
                    passed=True,
                    summary="objective verification passed after dream returned incomplete",
                    outcome={
                        **outcome.outcome,
                        "verified_after_incomplete_dream_result": True,
                        "verification_steps": len(verification),
                    },
                    cost_cents=outcome.cost_cents,
                    model=outcome.model,
                    input_tokens=outcome.input_tokens,
                    output_tokens=outcome.output_tokens,
                )
            )
        return _with_record(outcome)

    def _guard_subagent_evidence(
        self,
        outcome: BeatOutcome,
        # name -> (typed_output_json, is_error, worktree_sha_before_review, worktree_sha_after_review)
        fresh_results: Mapping[str, tuple[str, bool, str, str]],
    ) -> BeatOutcome:
        """Reject a passing beat whose durable subagent evidence lacks valid provenance."""
        if not outcome.passed or not self._subagent_evidence:
            return outcome
        if self._working_dir is None:
            return self._subagent_evidence_failure(outcome, "working directory is unavailable")

        provenance_to_write: list[tuple[Path, dict[str, object]]] = []
        for name, (
            relative_path,
            required_claim,
            evidence_read_only,
        ) in self._subagent_evidence.items():
            artifact_path = (self._working_dir / relative_path).resolve()
            try:
                artifact_path.relative_to(self._working_dir.resolve())
            except ValueError:
                return self._subagent_evidence_failure(
                    outcome, f"{name} evidence path escapes the worktree"
                )
            provenance_path = self._working_dir / ".harness" / "subagent-evidence" / f"{name}.json"
            fresh = fresh_results.get(name)
            if fresh is not None:
                fresh_reason, fresh_artifact = self._validate_fresh_evidence(
                    name=name,
                    fresh=fresh,
                    relative_path=relative_path,
                    required_claim=required_claim,
                    evidence_read_only=evidence_read_only,
                    artifact_path=artifact_path,
                    provenance_path=provenance_path,
                    provenance_to_write=provenance_to_write,
                )
                if fresh_reason is None:
                    continue
                # A failed re-attempt must not erase what a prior beat already proved (live
                # 2026-07-17: an integrate re-beat over an already-green worktree spawned
                # test_author again, it honestly declined to re-author RED-first, and the
                # beat was demoted despite beat-1's validated provenance). The stored record
                # is the durable proof; the ratchet still binds first-time work below.
                if (
                    self._validate_stored_evidence(
                        name=name,
                        relative_path=relative_path,
                        required_claim=required_claim,
                        evidence_read_only=evidence_read_only,
                        artifact_path=artifact_path,
                        provenance_path=provenance_path,
                    )
                    is None
                ):
                    continue
                if fresh_artifact is not None:
                    # No validated prior evidence to protect: land the honest failing verdict
                    # on disk so it displaces any parent-forged artifact and documents the
                    # refusal for the repair beat.
                    _write_json_atomic(artifact_path, fresh_artifact)
                return self._subagent_evidence_failure(outcome, fresh_reason)
            stored_reason = self._validate_stored_evidence(
                name=name,
                relative_path=relative_path,
                required_claim=required_claim,
                evidence_read_only=evidence_read_only,
                artifact_path=artifact_path,
                provenance_path=provenance_path,
            )
            if stored_reason is not None:
                return self._subagent_evidence_failure(outcome, stored_reason)

        for provenance_path, provenance in provenance_to_write:
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            provenance_path.write_text(
                json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        return replace(
            outcome,
            outcome={**outcome.outcome, "subagent_evidence": "passed"},
        )

    def _validate_fresh_evidence(
        self,
        *,
        name: str,
        fresh: tuple[str, bool, str, str],
        relative_path: str,
        required_claim: dict[str, object],
        evidence_read_only: bool,
        artifact_path: Path,
        provenance_path: Path,
        provenance_to_write: list[tuple[Path, dict[str, object]]],
    ) -> tuple[str | None, dict[str, object] | None]:
        """Validate this beat's subagent output; persist artifact+provenance only when it holds.

        The claim is checked BEFORE the artifact is written: a failing re-attempt must never
        clobber evidence a prior beat validated (the caller falls back to the stored record).
        Returns ``(failure_reason, parsed_artifact)`` — the artifact rides along so the caller
        can still land an honest failing verdict when there is no prior evidence to protect.
        """
        assert self._working_dir is not None
        content, is_error, before_worktree_hash, reviewed_worktree_hash = fresh
        if is_error:
            return f"{name} subagent execution failed", None
        if evidence_read_only and before_worktree_hash != reviewed_worktree_hash:
            return f"{name} changed the worktree during independent review", None
        try:
            returned = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return f"{name} typed output was invalid or fail-open", None
        if not isinstance(returned, dict):
            return f"{name} typed output was invalid or fail-open", None
        if any(returned.get(field) != expected for field, expected in required_claim.items()):
            return f"{name} evidence does not carry the required claim", returned
        if (
            evidence_read_only
            and _worktree_fingerprint(self._working_dir) != reviewed_worktree_hash
        ):
            return f"{name} worktree changed after independent review", returned
        _write_json_atomic(artifact_path, returned)
        provenance_to_write.append(
            (
                provenance_path,
                {
                    "subagent_name": name,
                    "artifact_path": relative_path,
                    "artifact_sha256": sha256(artifact_path.read_bytes()).hexdigest(),
                    "worktree_sha256": reviewed_worktree_hash,
                    "required_claim": required_claim,
                    "evidence_read_only": evidence_read_only,
                },
            )
        )
        return None, returned

    def _validate_stored_evidence(
        self,
        *,
        name: str,
        relative_path: str,
        required_claim: dict[str, object],
        evidence_read_only: bool,
        artifact_path: Path,
        provenance_path: Path,
    ) -> str | None:
        """Validate evidence a prior beat recorded (resume / re-beat path).

        Read-only evidence pins the artifact bytes AND the worktree the reviewer saw. A
        non-read-only producer's artifact lives in a worktree later beats legitimately mutate
        (its own re-run rewrites it), so there the machine-validated provenance record is the
        durable proof and the mutable file is not re-pinned.
        """
        assert self._working_dir is not None
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return f"{name} has no machine provenance from an independent run"
        if (
            not isinstance(provenance, dict)
            or provenance.get("artifact_path") != relative_path
            or provenance.get("required_claim") != required_claim
            or provenance.get("evidence_read_only", True) is not evidence_read_only
        ):
            return f"{name} artifact changed after independent review"
        if not evidence_read_only:
            return None
        if not artifact_path.is_file():
            return f"{name} evidence artifact is missing: {relative_path}"
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return f"{name} evidence artifact is not valid JSON"
        if not isinstance(artifact, dict) or any(
            artifact.get(field) != expected for field, expected in required_claim.items()
        ):
            return f"{name} evidence does not carry the required claim"
        if provenance.get("artifact_sha256") != sha256(
            artifact_path.read_bytes()
        ).hexdigest() or provenance.get("worktree_sha256") != _worktree_fingerprint(
            self._working_dir
        ):
            return f"{name} artifact changed after independent review"
        return None

    @staticmethod
    def _subagent_evidence_failure(outcome: BeatOutcome, reason: str) -> BeatOutcome:
        return replace(
            outcome,
            passed=False,
            outcome={
                **outcome.outcome,
                "subagent_evidence": "failed",
                "subagent_evidence_reason": reason,
            },
            summary=f"subagent evidence failed: {reason}",
            disposition=BeatDisposition.DOD_FAILED,
            retryable=False,
        )

    def _attach_subagent_stats(
        self, outcome: BeatOutcome, traces_before: frozenset[Path]
    ) -> BeatOutcome:
        """Enrich a beat outcome with this beat's subagent counters (best-effort, from the trace)."""
        if self._working_dir is None:
            return outcome
        stats = beat_subagent_stats(self._working_dir, traces_before)
        if not stats:
            return outcome
        return replace(
            outcome, outcome={**outcome.outcome, "subagents": [asdict(s) for s in stats]}
        )

    async def _arm_todo_flush_nudge(self) -> None:
        """Write the TODO flush nudge when beat budget drops below the remaining threshold."""
        assert self._working_dir is not None
        assert self._timeout_s is not None
        delay = self._timeout_s * (1.0 - TODO_FLUSH_REMAINING_FRACTION)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        remaining = self._timeout_s * TODO_FLUSH_REMAINING_FRACTION
        write_todo_flush_nudge(
            self._working_dir,
            timeout_s=self._timeout_s,
            remaining_s=remaining,
        )

    async def _close_harness(self) -> None:
        close = getattr(self._harness, "aclose", None)
        if close is None:
            return
        with suppress(Exception):
            result = close()
            if isawaitable(result):
                await result

    async def _verification_passed(self, verification: tuple[VerificationStep, ...]) -> bool:
        if self._working_dir is None:
            return False
        for step in verification:
            try:
                process = await asyncio.create_subprocess_shell(
                    step.command,
                    cwd=self._working_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    await asyncio.wait_for(process.communicate(), timeout=step.timeout_s)
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        process.kill()
                        await process.wait()
                    return False
            except OSError:
                return False
            if process.returncode != 0:
                return False
        return True


__all__ = [
    "DreamBeatRunner",
    "DreamStepStatus",
    "RunResult",
    "TaskHarness",
    "UsageView",
    "to_beat_outcome",
]
