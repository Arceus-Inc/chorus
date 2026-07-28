"""Renderer and budget — deterministic text, ordered eviction, disclosed trims.

No Postgres needed: the renderer is a pure function of a packet, so these run everywhere.
"""

from __future__ import annotations

from chorus.context import (
    DEFAULT_BUDGET_TOKENS,
    SECTION_BUDGETS,
    BudgetPosition,
    ContextAudience,
    Contract,
    GoalLink,
    InboxItem,
    PeerWork,
    PriorBeat,
    TaskContextPacket,
    estimate_tokens,
    render,
    sections_for,
)
from chorus.context._budget import RenderedSection, fit


def _packet(**overrides: object) -> TaskContextPacket:
    base: dict[str, object] = {
        "task_id": "t-1",
        "run_id": "run-9",
        "employee_id": "e1",
        "role": "backend_engineer",
        "what": Contract(
            intent="Implement scrubbing",
            dod_kind="command",
            dod_spec="pytest -q",
            artifact_class="pr",
        ),
        "budget": BudgetPosition(spent_cents=1200, limit_cents=50_000, beat_number=3),
        "why": (
            GoalLink(kind="goal", id="g-1", title="Ship the editor", status="active"),
            GoalLink(kind="task", id="t-0", title="Build the timeline", status="in_progress"),
        ),
    }
    base.update(overrides)
    return TaskContextPacket(**base)  # type: ignore[arg-type]


def _beat(number: int, **overrides: object) -> PriorBeat:
    base: dict[str, object] = {
        "run_id": f"run-{number}",
        "beat_number": number,
        "employee_id": "e1",
        "status": "succeeded",
        "phase": "needs_rework",
        "recovery_hint": "rework",
        "passed": False,
        "outcome": "needs_changes",
        "verdict_notes": ("wrong vectors",),
        "summary": "tried the naive approach",
    }
    base.update(overrides)
    return PriorBeat(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------- audiences


def test_evaluator_never_sees_prior_beats() -> None:
    """A gate must judge this artifact, not this artifact's history.

    Including prior verdicts would make the same deliverable pass or fail depending on what came
    before it — exactly the property a verifier must not have.
    """
    packet = _packet(prior_beats=(_beat(1), _beat(2)))

    text = render(packet, audience=ContextAudience.EVALUATOR).text

    assert "Where you left off" not in text
    assert "wrong vectors" not in text
    assert "What done means" in text
    assert "Why this task exists" in text


def test_planner_gets_history_because_it_cannot_ask_for_it() -> None:
    """The planner is toolless — push is the only channel it has."""
    packet = _packet(prior_beats=(_beat(1),))

    text = render(packet, audience=ContextAudience.PLANNER).text

    assert "Where you left off" in text
    assert "wrong vectors" in text
    assert "Budget" in text


def test_generator_gets_everything() -> None:
    packet = _packet(
        prior_beats=(_beat(1),),
        inbox=(InboxItem(message_id="m1", from_id="founder", body="ping"),),
        peers=(PeerWork(task_id="t-2", intent="build api", status="in_progress"),),
    )

    text = render(packet, audience=ContextAudience.GENERATOR).text

    for heading in (
        "What done means",
        "Why this task exists",
        "Where you left off",
        "Unread messages",
        "peers are building",
        "Budget",
    ):
        assert heading in text


def test_audience_section_sets_are_explicit() -> None:
    assert "prior_beats" not in sections_for(ContextAudience.EVALUATOR)
    assert "prior_beats" in sections_for(ContextAudience.PLANNER)
    assert sections_for(ContextAudience.GENERATOR) >= sections_for(ContextAudience.PLANNER)


# ------------------------------------------------------------ absence/first beat


def test_first_beat_says_so_rather_than_omitting_the_section() -> None:
    """ "No prior beats" and "I wasn't told about prior beats" must not look the same."""
    text = render(_packet(), audience=ContextAudience.GENERATOR).text

    assert "first beat on this task" in text


def test_missing_dod_is_stated_not_silently_dropped() -> None:
    packet = _packet(what=Contract(intent="explore the space"))

    text = render(packet).text

    assert "none recorded for this task" in text
    assert packet.what.scope_guard in text


# ------------------------------------------------------------------ budget


def test_section_caps_sum_to_the_default_budget() -> None:
    """The table is the design; drift between caps and ceiling would be silent."""
    assert sum(section.max_tokens for section in SECTION_BUDGETS) == DEFAULT_BUDGET_TOKENS


def test_oldest_beats_are_evicted_first_and_the_trim_is_disclosed() -> None:
    """Under pressure the packet keeps the most recent attempt and says what it dropped."""
    beats = tuple(_beat(n, summary="x" * 900) for n in range(1, 7))
    packet = _packet(prior_beats=beats)

    rendered = render(packet, audience=ContextAudience.GENERATOR)

    assert "prior_beats" in rendered.truncated
    assert "run-6" in rendered.text  # newest survives
    assert "run-1" not in rendered.text  # oldest goes first
    assert "earlier beat(s) omitted" in rendered.text
    assert "get_run(run_id=…)" in rendered.text


def test_at_least_one_prior_beat_always_survives() -> None:
    """A single enormous beat is still worth more than silence about it."""
    packet = _packet(prior_beats=(_beat(1, summary="x" * 20_000),))

    rendered = render(packet, audience=ContextAudience.GENERATOR)

    assert "Beat 1" in rendered.text


def test_why_chain_keeps_the_ends_and_reports_the_middle() -> None:
    """Root and immediate parent carry the meaning; the middle of a deep chain is restatement."""
    links = tuple(
        GoalLink(kind="task", id=f"t-{n}", title="a very long intent " * 20, status="in_progress")
        for n in range(12)
    )
    packet = _packet(why=links)

    rendered = render(packet, audience=ContextAudience.GENERATOR)

    assert "why" in rendered.truncated
    assert "t-0" in rendered.text  # root
    assert "t-11" in rendered.text  # immediate parent
    assert "intermediate level(s) omitted" in rendered.text


def test_contract_and_budget_survive_an_impossible_budget() -> None:
    """Dropping the contract to save tokens is a false economy — the beat would be blind."""
    packet = _packet(prior_beats=(_beat(1),), inbox=(InboxItem("m1", "founder", "ping"),))

    rendered = render(packet, audience=ContextAudience.GENERATOR, budget_tokens=1)

    assert "What done means" in rendered.text
    assert "### Budget" in rendered.text
    assert "prior_beats" in rendered.truncated


def test_fit_drops_lowest_rank_first_and_keeps_order() -> None:
    sections = (
        RenderedSection("budget", "b" * 40),
        RenderedSection("prior_beats", "p" * 4_000),
        RenderedSection("what", "w" * 40),
    )

    kept, dropped = fit(sections, budget_tokens=100)

    assert [section.name for section in kept] == ["what", "budget"]
    assert dropped == ("prior_beats",)


def test_live_peers_outrank_finished_ones() -> None:
    """A finished sibling is history; a live one can collide with this beat."""
    peers = tuple(
        PeerWork(
            task_id=f"t-{n}",
            intent="build " + "x" * 400,
            status="done",
            is_live=(n == 9),
        )
        for n in range(10)
    )
    packet = _packet(peers=peers)

    rendered = render(packet, audience=ContextAudience.GENERATOR)

    assert "peers" in rendered.truncated
    assert "t-9" in rendered.text


# -------------------------------------------------------------- determinism


def test_render_is_deterministic() -> None:
    packet = _packet(prior_beats=(_beat(1), _beat(2)))

    first = render(packet, audience=ContextAudience.GENERATOR)
    second = render(packet, audience=ContextAudience.GENERATOR)

    assert first.text == second.text
    assert first.truncated == second.truncated


def test_reported_token_count_matches_the_text() -> None:
    rendered = render(_packet(), audience=ContextAudience.GENERATOR)

    assert rendered.tokens == estimate_tokens(rendered.text)
    assert rendered.tokens <= DEFAULT_BUDGET_TOKENS


def test_every_section_stays_inside_its_own_cap() -> None:
    """The invariant that makes ``fit`` a safety net rather than the active decision-maker.

    If a section can overshoot its ceiling, the global pass starts dropping whole sections — and the
    first casualty is ``prior_beats``, the one the packet exists for. Item-level eviction plus the
    clip backstop must keep every section inside its allocation no matter how large one entry is.
    """
    packet = _packet(
        prior_beats=tuple(_beat(n, summary="x" * 5_000) for n in range(1, 5)),
        inbox=tuple(InboxItem(f"m{n}", "founder", "y" * 3_000) for n in range(4)),
        peers=tuple(
            PeerWork(task_id=f"t-{n}", intent="z" * 3_000, status="in_progress") for n in range(4)
        ),
        why=tuple(
            GoalLink(kind="task", id=f"t-{n}", title="w" * 2_000, status="in_progress")
            for n in range(6)
        ),
    )

    rendered = render(packet, audience=ContextAudience.GENERATOR)

    caps = {section.name: section.max_tokens for section in SECTION_BUDGETS}
    for block in rendered.text.split("\n\n### "):
        for name, heading in (
            ("why", "Why this task exists"),
            ("prior_beats", "Where you left off"),
            ("inbox", "Unread messages"),
            ("peers", "peers are building"),
        ):
            if heading in block:
                assert estimate_tokens(block) <= caps[name] + 40  # + heading/footer slack
    # nothing was dropped wholesale: every section survived, merely trimmed
    assert "Where you left off" in rendered.text
    assert "Unread messages" in rendered.text
    assert rendered.tokens <= DEFAULT_BUDGET_TOKENS


def test_snapshot_generator_render() -> None:
    """Golden output. A diff here is a deliberate change to what every beat is told."""
    packet = _packet(
        prior_beats=(
            _beat(
                1,
                run_id="run-abc",
                files_touched=("src/scrub.py",),
                verdict_notes=("base62 alphabet order is wrong",),
                summary="tried the naive approach",
            ),
        ),
        inbox=(
            InboxItem(
                message_id="m1", from_id="founder", body="prioritise correctness", task_id="t-1"
            ),
        ),
    )

    text = render(packet, audience=ContextAudience.GENERATOR).text

    assert text == "\n\n".join(
        [
            "## Task context",
            "### What done means",
            "Implement scrubbing",
            "**Definition of done (Command):** pytest -q\n**Artifact class:** pr",
            "Stay inside the assigned scope. The parent objective above is context for keeping this "
            "task faithful to what was delegated — it is not permission to widen the work.",
            "### Why this task exists",
            "- **goal** `g-1` — Ship the editor _(active)_\n"
            "- **task** `t-0` — Build the timeline _(in_progress)_",
            "### Where you left off — 1 prior beat(s) on this task",
            "**Beat 1** · `run-abc` · needs_rework\n"
            "- next step: **rework**\n"
            "- files touched: `src/scrub.py`\n"
            "- evaluator: base62 alphabet order is wrong\n"
            "- account: tried the naive approach",
            "### Unread messages",
            "- from **founder** (task `t-1`): prioritise correctness",
            "### Budget",
            "Beat 3 · 1200 cents spent of 50000 · 48800 remaining",
        ]
    )
