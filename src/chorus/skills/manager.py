"""SkillManager — sole procedural mutation path (Hermes skill_manage semantics).

Lattice validates habit drafts; Chorus ``SkillStore`` owns version rows.
``lattice_apply`` must not write habits — patterns only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from chorus.ledger import SkillOrigin
from chorus.skills._observation import SkillObservation
from chorus.skills._patch import find_and_replace
from chorus.skills._store import SkillConflictError, SkillStore

__all__ = ["SkillManager", "SkillObservation"]


class _EpisodeLike(Protocol):
    @property
    def run_id(self) -> str: ...
    @property
    def employee_id(self) -> str: ...
    @property
    def outcome(self) -> str: ...


@dataclass(frozen=True)
class _Frontmatter:
    name: str
    description: str
    when_to_use: str
    body: str
    raw: str


class SkillManager:
    """Dispatch Hermes-shaped actions against :class:`SkillStore`."""

    def __init__(
        self,
        store: SkillStore,
        *,
        employee_id: str,
        canonical_skills_root: Path | None = None,
        episodes: tuple[_EpisodeLike, ...] = (),
    ) -> None:
        self.store = store
        self.employee_id = employee_id
        self.canonical_skills_root = (
            Path(canonical_skills_root) if canonical_skills_root is not None else None
        )
        self.episodes = episodes

    def close(self) -> None:
        self.store.close()

    def apply(
        self,
        *,
        action: str,
        name: str | None = None,
        content: str | None = None,
        section: str | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        source_run_ids: list[str] | tuple[str, ...] | None = None,
        label: str | None = None,
        replace_all: bool = False,
    ) -> SkillObservation:
        action = (action or "").strip().lower()
        try:
            if action == "evolve":
                return self._evolve(
                    name=name,
                    section=section,
                    content=content,
                    source_run_ids=source_run_ids or (),
                    label=label,
                )
            if action == "create":
                return self._create(
                    name=name,
                    content=content,
                    source_run_ids=source_run_ids or (),
                    label=label,
                )
            if action == "patch":
                return self._patch(
                    name=name,
                    old_string=old_string,
                    new_string=new_string,
                    replace_all=replace_all,
                    source_run_ids=source_run_ids or (),
                    label=label,
                )
            if action == "view":
                return self._view(name=name)
            return SkillObservation.error(
                summary=f"unknown action {action!r}",
                root_cause="action not in skill_manage vocabulary",
                retry="use view|create|evolve|patch",
                stop="do not invent actions",
                next_actions=["skill_manage(action='view')"],
            )
        except SkillConflictError as exc:
            return SkillObservation.error(
                summary=str(exc),
                root_cause="slug collision",
                retry="choose a new class-level slug or evolve the existing skill",
                stop="do not overwrite via create",
                next_actions=[f"skill_manage(action='view', name={name!r})"],
            )
        except Exception as exc:
            return SkillObservation.error(
                summary=f"skill_manage failed: {exc}",
                root_cause=type(exc).__name__,
                retry="inspect view + retry with narrower inputs",
                stop="after 2 unexpected failures stop and report",
                next_actions=["skill_manage(action='view')"],
            )

    # --- actions -----------------------------------------------------------------

    def _evolve(
        self,
        *,
        name: str | None,
        section: str | None,
        content: str | None,
        source_run_ids: list[str] | tuple[str, ...],
        label: str | None,
    ) -> SkillObservation:
        if not name or not section or not content:
            return SkillObservation.error(
                summary="evolve requires name, section, and content",
                root_cause="missing required fields",
                retry="pass name=canonical-slug, section=heading, content=markdown body",
                stop="do not create a micro-slug instead",
                next_actions=["skill_manage(action='view')"],
            )
        err = self._validate_habit(
            action="evolve",
            skill=name,
            section=section,
            body=content,
            source_run_ids=tuple(source_run_ids),
        )
        if err is not None:
            return err

        existing = self.store.get_by_slug(self.employee_id, name)
        if existing is None:
            base = self._load_canonical_markdown(name)
            if base is None:
                return SkillObservation.error(
                    summary=f"unknown skill {name!r}",
                    root_cause="slug not in store or canonical_skills_root",
                    retry="view available skills; evolve a role umbrella",
                    stop="do not invent file-prefix slugs",
                    next_actions=["skill_manage(action='view')"],
                )
            fm = _parse_frontmatter(base) or _Frontmatter(
                name=name,
                description=name,
                when_to_use=f"Use when performing {name}",
                body=base,
                raw=base,
            )
            merged = _merge_section(base, section, content)
            skill, rev = self.store.create(
                employee_id=self.employee_id,
                slug=name,
                name=fm.name or name,
                description=fm.description,
                when_to_use=fm.when_to_use,
                file_inventory=[{"path": "SKILL.md", "kind": "file", "content": merged}],
                origin=SkillOrigin.EVOLVED,
                canonical_slug=name,
                action="create",
                label=label or f"EVOLVE: {section}",
                source_run_ids=source_run_ids,
            )
        else:
            head = self.store.head(existing.id)
            if head is None:
                return SkillObservation.error(
                    summary="skill has no revisions",
                    root_cause="corrupt skill head",
                    retry="restore from a known revision or recreate",
                    stop="do not patch empty history",
                )
            current = _skill_md(head.inventory())
            merged = _merge_section(current, section, content)
            rev = self.store.append_revision(
                skill_id=existing.id,
                file_inventory=[{"path": "SKILL.md", "kind": "file", "content": merged}],
                action="patch",
                label=label or f"EVOLVE: {section}",
                source_run_ids=source_run_ids,
            )
            refreshed = self.store.get(existing.id)
            assert refreshed is not None
            skill = refreshed

        return SkillObservation.ok(
            f"evolved {name!r} → revision {rev.revision_no}",
            artifacts=_artifacts(skill, rev),
            next_actions=[
                f"skill(name={name!r}) on next beat to load materialized HEAD",
                "prefer patch for small follow-up fixes",
            ],
        )

    def _create(
        self,
        *,
        name: str | None,
        content: str | None,
        source_run_ids: list[str] | tuple[str, ...],
        label: str | None,
    ) -> SkillObservation:
        if not name or not content:
            return SkillObservation.error(
                summary="create requires name and content",
                root_cause="missing required fields",
                retry="pass full SKILL.md with frontmatter + When to Use + Pitfalls",
                stop="do not create sticky-note skills",
            )
        fm = _parse_frontmatter(content)
        if fm is None:
            return SkillObservation.error(
                summary="SKILL.md must start with YAML frontmatter",
                root_cause="missing --- frontmatter",
                retry="add name, description, when_to_use frontmatter",
                stop="do not write body-only skills",
            )
        err = self._validate_habit(
            action="create",
            slug=name,
            title=fm.name or name,
            body=fm.body,
            source_run_ids=tuple(source_run_ids),
        )
        if err is not None:
            return err

        skill, rev = self.store.create(
            employee_id=self.employee_id,
            slug=name,
            name=fm.name or name,
            description=fm.description,
            when_to_use=fm.when_to_use,
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": content}],
            origin=SkillOrigin.CREATED,
            action="create",
            label=label or "Initial",
            source_run_ids=source_run_ids,
        )
        return SkillObservation.ok(
            f"created skill {name!r} revision 1",
            artifacts=_artifacts(skill, rev),
            next_actions=["prefer evolve/patch on next improvement"],
        )

    def _patch(
        self,
        *,
        name: str | None,
        old_string: str | None,
        new_string: str | None,
        replace_all: bool,
        source_run_ids: list[str] | tuple[str, ...],
        label: str | None,
    ) -> SkillObservation:
        if not name or old_string is None or new_string is None:
            return SkillObservation.error(
                summary="patch requires name, old_string, new_string",
                root_cause="missing required fields",
                retry="view skill body, then patch with exact excerpt",
                stop="after 2 misses use edit only for major overhauls",
                next_actions=[f"skill_manage(action='view', name={name!r})"],
            )
        skill = self.store.get_by_slug(self.employee_id, name)
        if skill is None:
            return SkillObservation.error(
                summary=f"unknown skill {name!r}",
                root_cause="skill not in store — evolve canonical first",
                retry="skill_manage(action='evolve', …) once, then patch",
                stop="do not create a parallel micro-skill",
                next_actions=["skill_manage(action='view')"],
            )
        head = self.store.head(skill.id)
        assert head is not None
        current = _skill_md(head.inventory())
        updated, _count, err = find_and_replace(
            current, old_string, new_string, replace_all=replace_all
        )
        if err:
            return SkillObservation.error(
                summary=f"patch failed: {err}",
                root_cause="fuzzy/exact miss or ambiguous match",
                retry="skill_manage(action='view') then narrow old_string",
                stop="after 2 misses stop; use edit only if overhauling",
                next_actions=[f"skill_manage(action='view', name={name!r})"],
                artifacts={"skill": name, "skill_id": skill.id},
            )
        rev = self.store.append_revision(
            skill_id=skill.id,
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": updated}],
            action="patch",
            label=label or "patch",
            source_run_ids=source_run_ids,
        )
        skill = self.store.get(skill.id)
        assert skill is not None
        return SkillObservation.ok(
            f"patched {name!r} → revision {rev.revision_no}",
            artifacts=_artifacts(skill, rev),
            next_actions=["load via skill tool on next beat"],
        )

    def _view(self, *, name: str | None) -> SkillObservation:
        if not name:
            active = self.store.list_active(self.employee_id)
            slugs = [s.slug for s in active]
            return SkillObservation.ok(
                f"{len(slugs)} active skill(s)",
                artifacts={"skills": slugs},
                next_actions=["skill_manage(action='view', name='<slug>')"],
            )
        skill = self.store.get_by_slug(self.employee_id, name)
        if skill is None:
            return SkillObservation.error(
                summary=f"unknown skill {name!r}",
                root_cause="not in store",
                retry="list without name",
                stop="stop inventing slugs",
                next_actions=["skill_manage(action='view')"],
            )
        head = self.store.head(skill.id)
        body = _skill_md(head.inventory()) if head else ""
        return SkillObservation.ok(
            f"view {name!r} revision {skill.latest_revision_no}",
            artifacts={
                "skill": name,
                "skill_id": skill.id,
                "revision_no": skill.latest_revision_no,
                "version_id": skill.latest_revision_id,
                "content": body,
            },
            next_actions=["patch small fixes; evolve new sections"],
        )

    def _validate_habit(
        self,
        *,
        action: str,
        source_run_ids: tuple[str, ...],
        skill: str | None = None,
        section: str | None = None,
        slug: str | None = None,
        title: str | None = None,
        body: str = "",
    ) -> SkillObservation | None:
        from datetime import UTC, datetime

        from lattice import HabitAction, HabitDraft, Proposal
        from lattice.consolidate import validate_proposal
        from lattice.contracts.episodic import RawEpisode

        habit_action = HabitAction.EVOLVE if action == "evolve" else HabitAction.CREATE
        habit = HabitDraft(
            action=habit_action,
            source_run_ids=source_run_ids,
            skill=skill,
            section=section,
            slug=slug,
            title=title,
            body=body,
        )
        now = datetime.now(UTC)
        episodes = tuple(
            RawEpisode(
                run_id=ep.run_id,
                task_id="t",
                employee_id=ep.employee_id,
                role="backend_engineer",
                scope="project",
                intent="",
                outcome=ep.outcome,
                score=1.0,
                created_at=now,
                recorded_at=now,
                artifacts=(),
                files_touched=(),
                body="",
            )
            for ep in self.episodes
        )

        class _NoAtoms:
            def list_active(self, _employee_id: str) -> list[Any]:
                return []

        result = validate_proposal(
            Proposal(employee_id=self.employee_id, habits=(habit,)),
            episodes=episodes,
            atoms=_NoAtoms(),  # type: ignore[arg-type]
            canonical_skills_root=self.canonical_skills_root,
        )
        # Also allow store slugs as known evolved skills
        if not result.ok:
            # Re-validate evolve against store slugs by injecting via known set:
            # validate_proposal only sees canonical + atoms evolved. Patch: if sole
            # error is unknown skill but store has it, accept.
            store_slugs = {s.slug for s in self.store.list_active(self.employee_id)}
            filtered = [
                e
                for e in result.errors
                if not ("unknown skill" in e and skill is not None and skill in store_slugs)
            ]
            # Canonical evolve of role skill with empty store is fine if in canonical
            if filtered:
                msg = "; ".join(filtered)
                return SkillObservation.error(
                    summary=msg,
                    root_cause="Hermes habit gate rejected draft",
                    retry=(
                        "put facts in lattice_apply patterns[]; "
                        "evolve class-level procedures with steps/pitfalls"
                    ),
                    stop="do not CREATE diary sticky notes",
                    next_actions=[
                        "lattice_apply({patterns:[…]})",
                        "skill_manage(action='evolve', …) with a real procedure body",
                    ],
                )
        return None

    def _load_canonical_markdown(self, slug: str) -> str | None:
        if self.canonical_skills_root is None:
            return None
        path = self.canonical_skills_root / slug / "SKILL.md"
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")


def _artifacts(skill: Any, rev: Any) -> dict[str, Any]:
    return {
        "skill": skill.slug,
        "skill_id": skill.id,
        "version_id": rev.id,
        "revision_no": rev.revision_no,
        "origin": skill.origin.value if hasattr(skill.origin, "value") else skill.origin,
    }


def _skill_md(inventory: list[dict[str, Any]]) -> str:
    for entry in inventory:
        if entry.get("path") == "SKILL.md":
            return str(entry.get("content") or "")
    return str(inventory[0]["content"]) if inventory else ""


def _merge_section(canonical: str, section: str, body: str) -> str:
    """Keep canonical frontmatter; append or replace ``## section`` block."""
    section_body = body.strip()
    if not section_body.startswith("## "):
        section_body = f"## {section}\n\n{section_body}"
    heading = f"## {section}"
    # Prefer heading from body if present
    for line in section_body.splitlines():
        if line.startswith("## "):
            heading = line.strip()
            break
    if heading in canonical:
        before, _, _rest = canonical.partition(heading)
        # Drop old section through next ## or EOF
        rest_lines = _rest.splitlines()
        # _rest starts after heading; find next ##
        cut = len(rest_lines)
        for i, line in enumerate(rest_lines):
            if i == 0:
                continue
            if line.startswith("## "):
                cut = i
                break
        after = "\n".join(rest_lines[cut:]).lstrip("\n") if cut < len(rest_lines) else ""
        return before.rstrip() + "\n\n" + section_body.strip() + ("\n\n" + after if after else "\n")
    return canonical.rstrip() + "\n\n" + section_body.strip() + "\n"


def _parse_frontmatter(text: str) -> _Frontmatter | None:
    if not text.lstrip().startswith("---"):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip().strip('"').strip("'")
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return _Frontmatter(
        name=meta.get("name", ""),
        description=meta.get("description", ""),
        when_to_use=meta.get("when_to_use", ""),
        body=body,
        raw=text,
    )
