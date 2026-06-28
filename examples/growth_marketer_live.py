"""Live run — the Growth Marketer (Mira) on real marketing tasks through dream on Azure OpenAI.

Not a unit test. Run it by hand to watch Mira work end to end: she is hired as a ``growth_marketer``,
the kernel generates her **action-class DoD at intake**, and each beat runs through the real
:class:`~chorus_harness.EmployeeHarnessFactory` — so the live model acts *as Mira* (her brief, her
tools, her own git worktree). A passed beat lands its artifact through her real outcome lander.

Five tasks exercise every DoD class (spec GM §8):

    "back-test 6 activation-email subject lines and rank them"  → Command       → backtest_report
    "draft a campaign brief to lift activation"                 → AgentReview    → campaign_brief
    "recommend prospecting plays + find leads for them"         → AgentReview    → growth_playbook
    "draft a batch of launch posts for social + email"          → HumanApproval  → campaign_content
    "launch the winning A/B test live to 40k users"            → HumanApproval  → experiment_launched
                                                                  (both gate — never auto-ships/publishes)

It also runs the net-new offline-eval **branch tournament** (:func:`~chorus.webplugins.run_tournament`)
on real variant scores, the **content swipe** (:func:`~chorus.webplugins.swipe_review`) on a draft
batch, and the **play recommender** (:func:`~chorus_employee.growth_marketer.recommend_plays`) on
candidate go-to-market plays — to show the score-and-rank + accept/reject primitives directly.

    AZURE_OPENAI_API_KEY=...
    AZURE_OPENAI_BASE_URL=https://<resource>.openai.azure.com/openai/v1
    AZURE_OPENAI_DEPLOYMENT=<deployment>
    uv run python examples/growth_marketer_live.py

Skips cleanly (exit 0) when those env vars are unset, so it is safe to invoke anywhere.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

import dream  # type: ignore[import-not-found]

from chorus.adapters import check_dream_contract
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.outcomes import LanderRegistry
from chorus.roles import RoleRegistry, default_roles
from chorus.webplugins import Draft, PluginKind, VariantScore, run_tournament, swipe_review
from chorus.workforce import LedgerWorkforce
from chorus.workspace import CompanyWorkspace
from chorus_cli._beats import default_pricing_from_env
from chorus_employee.growth_marketer import (
    Play,
    ScoredPlay,
    classify_action,
    growth_marketer_dod,
    growth_marketer_lander,
    growth_marketer_plugin,
    recommend_plays,
)
from chorus_harness import EmployeeHarnessFactory

# The five marketing tasks — one per action class (spec GM §8/§9).
_TASKS: tuple[tuple[str, str], ...] = (
    (
        "backtest",
        "Back-test 6 candidate subject lines for the activation email against last quarter's "
        "open-rate data; rank them by predicted lift and recommend the top 2.",
    ),
    (
        "brief",
        "Draft a campaign brief for a re-engagement push to lift 7-day activation: the hypothesis, "
        "the target audience and its size, the variants, and the power/sample-size plan.",
    ),
    (
        "prospect",
        "Recommend the top go-to-market plays to scale Arceus this quarter; for the best play, design "
        "the angled Google/LinkedIn/X search-query grid and assemble a deduped shortlist of candidate "
        "target organisations (each lead with the signal it matches). Discovery only — write the "
        "ranked plays and the lead list to the growth playbook; do not contact anyone.",
    ),
    (
        "content",
        "Draft a batch of 4 short announcement posts (2 for social, 2 for the email list); "
        "rank them and recommend the top 2 to publish.",
    ),
    (
        "launch",
        "Launch the winning subject-line A/B test live and send it to the 40k dormant-user segment.",
    ),
)


def _seed_repo(path: Path) -> None:
    """A tiny git repo so Mira branches her worktree off real trunk (like the other live examples)."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# growth\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "seed"],
        check=True,
        capture_output=True,
    )


def _show_tournament() -> None:
    """The net-new score-and-rank primitive on real numbers (spec GM §3)."""
    scores = [
        VariantScore("subj-A", 0.8, {"power": 0.82}),
        VariantScore("subj-B", 1.9, {"power": 0.91}),
        VariantScore("subj-C", 1.1, {"power": 0.78}),
        VariantScore("subj-D", 1.9, {"power": 0.88}),
    ]
    outcome = run_tournament(scores, top_k=2)
    print("\n=== offline-eval branch tournament (run_tournament, top_k=2) ===")
    for rank, s in enumerate(outcome.ranked, 1):
        ship = "  <- ship" if s in outcome.winners else ""
        print(f"  {rank}. {s.variant_id}  score={s.score:+.2f}  power={s.metrics.get('power')}{ship}")


def _show_play_recommender() -> None:
    """The net-new play recommender on candidate go-to-market plays (spec GM §3; reuses tournament)."""
    scored = [
        ScoredPlay(
            Play("series-a", "Just raised Series A", "Seed-to-B startups", "hiring, scaling", "funding PR"),
            0.7,
            {"reach": 0.6, "intent": 0.8},
        ),
        ScoredPlay(
            Play("cto-gap", "CTO just stepped down", "Series A-to-C", "interim leadership gap", "role change"),
            1.4,
            {"reach": 0.4, "intent": 0.95},
        ),
        ScoredPlay(
            Play("vendor-ask", "Asking for vendor recs", "ML teams", "public 'anyone recommend' post", "forum ask"),
            1.1,
            {"reach": 0.7, "intent": 0.9},
        ),
    ]
    rec = recommend_plays(scored, top_k=2)
    print("\n=== play recommender (recommend_plays, top_k=2) ===")
    for rank, play in enumerate(rec.ranked, 1):
        run = "  <- run this cycle" if play in rec.winners else ""
        print(f"  {rank}. {play.id}  {play.title}{run}")


def _show_swipe() -> None:
    """The net-new content swipe on a draft batch (spec GM §3; Result/Polsia 'swipe like Tinder')."""
    drafts = [
        Draft("post-1", PluginKind.SOCIAL, "Ship faster with X — try it free."),
        Draft("post-2", PluginKind.SOCIAL, "We rewrote onboarding. Here's why."),
        Draft("mail-1", PluginKind.EMAIL_CRM, "You left something half-done…"),
    ]
    review = swipe_review(drafts, accept={"post-2", "mail-1"})  # the human keeps two
    print("\n=== content swipe review (swipe_review) ===")
    for d in drafts:
        verdict = "accept -> publish" if d in review.accepted else "reject"
        print(f"  {d.id} [{d.channel.value}]  {verdict}")


async def main() -> int:
    check_dream_contract(dream)
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    # The net-new primitives first — deterministic, no model needed.
    _show_tournament()
    _show_play_recommender()
    _show_swipe()

    base = Path(tempfile.mkdtemp(prefix="chorus-growth-live-"))
    seed = base / "seed"
    _seed_repo(seed)
    lg = SqliteLedger.open(str(base / "ledger.db"))
    try:
        # Mira is registrable, not a kernel default — she joins the v0 roster through the same path.
        registry = RoleRegistry.from_plugins([*default_roles(), growth_marketer_plugin()])
        LedgerWorkforce(lg.employees).hire(name="mira", role="growth_marketer")

        factory = EmployeeHarnessFactory(
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="acme",
            roles=registry,
            pricing=default_pricing_from_env(),
            seed=seed,
            work_root=base / "work",
            ledger=lg,
            # The prospecting playbook is a large artifact (ranked plays + query grid + lead list);
            # give every beat a wider wall-clock so it lands rather than timing out mid-write.
            timeout_s=float(os.environ.get("GM_TIMEOUT_S", "300")),
        )
        workspace = CompanyWorkspace(factory.company_root, seed=seed)
        workspace.worktree_for("mira")  # pre-create Mira's worktree

        scheduler = Scheduler(
            ledger=lg,
            workforce=LedgerWorkforce(lg.employees),
            beat_runner_for=factory,
            roles=registry,
            landers=LanderRegistry.from_landers([growth_marketer_lander(factory.company_root)]),
            max_concurrent_runs=1,
            max_review_rounds=1,
        )

        # Submit each task, set its DoD (the action-class verifier), and assign to Mira.
        # Optional GM_TASKS="prospect,brief" runs only a subset (handy for re-checking one beat).
        only = {k.strip() for k in os.environ.get("GM_TASKS", "").split(",") if k.strip()}
        tasks = tuple(t for t in _TASKS if not only or t[0] in only)
        ids: dict[str, str] = {}
        for key, intent in tasks:
            task = lg.tasks.submit(Task(id=f"gm-{key}", intent=intent, status=TaskStatus.TODO))
            lg.dod.create(task.id, growth_marketer_dod(intent))
            assign_task(lg, task.id, "mira")
            ids[key] = task.id
            print(f"\nsubmitted [{key}] dod={classify_action(intent).value} -> {growth_marketer_dod(intent).kind.value}")

        # Drive the scheduler until the tasks settle (the launch task parks at the human gate).
        for _ in range(40):
            if all(
                (t := lg.tasks.get(tid)) is not None
                and t.status in (TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.REJECTED)
                for tid in ids.values()
            ):
                break
            await scheduler.tick_once()
            await scheduler.drain()

        print("\n=== results ===")
        worktree = workspace.worktree_for("mira").path
        for key, tid in ids.items():
            landed = lg.tasks.get(tid)
            dod = lg.dod.get_for_task(tid)
            status = landed.status.value if landed is not None else "?"
            verdict = dod.verdict if dod is not None else None
            print(f"\n[{key}] status={status}")
            if verdict is not None:
                print(f"  verdict={verdict}")
            for doc in (
                "backtest_report.md",
                "campaign_brief.md",
                "campaign_content.md",
                "experiment_launch.md",
                "growth_playbook.md",
                "backtest.py",
            ):
                p = worktree / doc
                if p.is_file():
                    head = p.read_text(encoding="utf-8").strip().splitlines()[:6]
                    print(f"  wrote {doc}:")
                    for line in head:
                        print(f"    | {line}")
        print(f"\nMira's worktree: {worktree}")
        return 0
    finally:
        lg.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
