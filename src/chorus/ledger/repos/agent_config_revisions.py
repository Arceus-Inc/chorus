"""AgentConfigRevisionRepo — append-only snapshots of effective harness configuration."""

from __future__ import annotations

from chorus.ledger._models import (
    AgentConfigRevision,
    AgentIdentity,
    AgentsMdReference,
    EffectiveToolPin,
    ProviderModelConfig,
    SandboxProfile,
    SkillRevisionPin,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class AgentConfigRevisionRepo:
    """Create and read immutable agent-configuration snapshots."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def create(self, revision: AgentConfigRevision) -> AgentConfigRevision:
        try:
            advanced = self._conn.execute(
                "INSERT INTO agent_config_revision_head (agent_id, latest_revision_no) "
                "VALUES (?, ?) "
                "ON CONFLICT (company_id, agent_id) DO UPDATE "
                "SET latest_revision_no = EXCLUDED.latest_revision_no "
                "WHERE agent_config_revision_head.latest_revision_no < EXCLUDED.latest_revision_no "
                "RETURNING latest_revision_no",
                (revision.agent.value, revision.revision_no),
            ).fetchone()
            if advanced is None:
                raise ValueError("agent config revision number must increase")
            self._conn.execute(
                "INSERT INTO agent_config_revision ("
                "id, agent_id, revision_no, agents_md_revision, agents_md_content, provider, "
                "model, sandbox_profile, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    revision.id,
                    revision.agent.value,
                    revision.revision_no,
                    revision.agents_md.revision,
                    revision.agents_md.content,
                    revision.provider_model.provider,
                    revision.provider_model.model,
                    revision.sandbox_profile.value,
                    utcnow_iso(),
                ),
            )
            for position, skill_pin in enumerate(revision.skill_pins):
                self._conn.execute(
                    "INSERT INTO agent_config_revision_skill "
                    "(agent_config_revision_id, skill_revision_id, position) VALUES (?, ?, ?)",
                    (revision.id, skill_pin.skill_revision_id, position),
                )
            for position, tool_pin in enumerate(revision.tool_pins):
                self._conn.execute(
                    "INSERT INTO agent_config_revision_tool "
                    "(agent_config_revision_id, identifier, provenance, position) VALUES (?, ?, ?, ?)",
                    (revision.id, tool_pin.identifier, tool_pin.provenance, position),
                )
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()
        return require_persisted(self.get(revision.id), revision.id)

    def get(self, revision_id: str) -> AgentConfigRevision | None:
        row = self._conn.execute(
            "SELECT * FROM agent_config_revision WHERE id = ?", (revision_id,)
        ).fetchone()
        if row is None:
            return None
        skill_rows = self._conn.execute(
            "SELECT skill_revision_id FROM agent_config_revision_skill "
            "WHERE agent_config_revision_id = ? ORDER BY position",
            (revision_id,),
        ).fetchall()
        tool_rows = self._conn.execute(
            "SELECT identifier, provenance FROM agent_config_revision_tool "
            "WHERE agent_config_revision_id = ? ORDER BY position",
            (revision_id,),
        ).fetchall()
        return _row_to_agent_config_revision(
            row,
            tuple(SkillRevisionPin(skill_row["skill_revision_id"]) for skill_row in skill_rows),
            tuple(
                EffectiveToolPin(tool_row["identifier"], tool_row["provenance"])
                for tool_row in tool_rows
            ),
        )

    def list(self, agent: AgentIdentity) -> list[AgentConfigRevision]:
        rows = self._conn.execute(
            "SELECT id FROM agent_config_revision WHERE agent_id = ? ORDER BY revision_no",
            (agent.value,),
        ).fetchall()
        return [require_persisted(self.get(row["id"]), row["id"]) for row in rows]


def _row_to_agent_config_revision(
    row: LedgerRow,
    skill_pins: tuple[SkillRevisionPin, ...],
    tool_pins: tuple[EffectiveToolPin, ...],
) -> AgentConfigRevision:
    return AgentConfigRevision(
        id=row["id"],
        agent=AgentIdentity(row["agent_id"]),
        revision_no=row["revision_no"],
        agents_md=AgentsMdReference(row["agents_md_revision"], row["agents_md_content"]),
        provider_model=ProviderModelConfig(row["provider"], row["model"]),
        sandbox_profile=SandboxProfile(row["sandbox_profile"]),
        skill_pins=skill_pins,
        tool_pins=tool_pins,
        created_at=from_iso(row["created_at"]),
    )
