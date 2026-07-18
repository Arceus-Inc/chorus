"""Chorus capabilities exposed to the model as dream tools (Path A composition layer).

``chorus_tools`` is the seam where a chorus capability becomes **model-callable**: each tool here is a
dream ``BaseTool`` wrapping a dream-free chorus service. The dream import lives in this layer (like
``chorus_cli``) so core ``chorus`` stays dream-free. The harness factory
(:mod:`chorus_harness._factory`) binds these tools into each role's registry.
"""

from __future__ import annotations

from chorus_tools._analysis import (
    ChartRenderTool,
    NotebookRunTool,
    RepoSearchTool,
    WarehouseQueryTool,
    analysis_tool,
)
from chorus_tools._brand_lint import BrandLintTool
from chorus_tools._code_quality import CodeQualityTool, is_noop_quality_command
from chorus_tools._comment import CommentTool, ReadCommentsTool
from chorus_tools._decompose import DecomposeTool
from chorus_tools._design_exemplar import DesignExemplarTool
from chorus_tools._design_lint import DesignLintTool
from chorus_tools._evidence_scan import EvidenceScanTool
from chorus_tools._get_run import GetRunTool
from chorus_tools._go_live import GoLiveTool
from chorus_tools._governance import (
    GOVERNANCE_TOOL_NAMES,
    GoalArchiveTool,
    GoalSetPriorityTool,
    GovernanceReadTool,
    ProposalApproveTool,
    ProposalRejectTool,
    governance_tool,
)
from chorus_tools._manager_actions import AssignTaskTool, SubmitTaskTool
from chorus_tools._recall import RecallTool
from chorus_tools._record_decision import RecordDecisionTool
from chorus_tools._secret_scan import SecretScanTool
from chorus_tools._staffing_request import StaffingRequestTool
from chorus_tools._team_read import TeamReadTool
from chorus_tools._test_evidence import TestEvidenceTool, TestRedTool
from chorus_tools._workforce_plan import WorkforceCatalogReadTool, WorkforcePlanProposeTool

__all__ = [
    "GOVERNANCE_TOOL_NAMES",
    "AssignTaskTool",
    "BrandLintTool",
    "ChartRenderTool",
    "CodeQualityTool",
    "CommentTool",
    "DecomposeTool",
    "DesignExemplarTool",
    "DesignLintTool",
    "EvidenceScanTool",
    "GetRunTool",
    "GoLiveTool",
    "GoalArchiveTool",
    "GoalSetPriorityTool",
    "GovernanceReadTool",
    "NotebookRunTool",
    "ProposalApproveTool",
    "ProposalRejectTool",
    "ReadCommentsTool",
    "RecallTool",
    "RecordDecisionTool",
    "RepoSearchTool",
    "SecretScanTool",
    "StaffingRequestTool",
    "SubmitTaskTool",
    "TeamReadTool",
    "TestEvidenceTool",
    "TestRedTool",
    "WarehouseQueryTool",
    "WorkforceCatalogReadTool",
    "WorkforcePlanProposeTool",
    "analysis_tool",
    "governance_tool",
    "is_noop_quality_command",
]
