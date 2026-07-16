"""Chorus capabilities exposed to the model as dream tools (Path A composition layer).

``chorus_tools`` is the seam where a chorus capability becomes **model-callable**: each tool here is a
dream ``BaseTool`` wrapping a dream-free chorus service. The dream import lives in this layer (like
``chorus_cli``) so core ``chorus`` stays dream-free. Build a role's registry with
:func:`chorus_tool_registry` and hand it to ``dream.build_harness(registry=…)``.
"""

from __future__ import annotations

from chorus_tools._analysis import (
    ChartRenderTool,
    NotebookRunTool,
    RepoSearchTool,
    WarehouseQueryTool,
    analysis_tool,
)
from chorus_tools._brand_lint import BrandFinding, BrandLintInput, BrandLintTool
from chorus_tools._code_quality import (
    CodeQualityInput,
    CodeQualityTool,
    QualityCheck,
    QualityCheckSpec,
    QualityReport,
    is_noop_quality_command,
)
from chorus_tools._code_quality import write_report as write_quality_report
from chorus_tools._decompose import DecomposeInput, DecomposeTool
from chorus_tools._design_exemplar import (
    DesignExemplarInput,
    DesignExemplarTool,
    available_exemplars,
)
from chorus_tools._design_lint import DesignFinding, DesignLintInput, DesignLintTool, DesignTokens
from chorus_tools._evidence_scan import (
    EvidenceFinding,
    EvidenceReport,
    EvidenceScanInput,
    EvidenceScanTool,
    EvidenceSpec,
    LogAssessment,
)
from chorus_tools._get_run import GetRunInput, GetRunTool
from chorus_tools._go_live import GoLiveAction, GoLiveInput, GoLiveTool
from chorus_tools._governance import (
    GOVERNANCE_TOOL_NAMES,
    GoalArchiveTool,
    GoalSetPriorityTool,
    GovernanceReadTool,
    ProposalApproveTool,
    ProposalRejectTool,
    governance_tool,
)
from chorus_tools._lattice import (
    LatticeApplyInput,
    LatticeApplyTool,
    LatticeContextInput,
    LatticeContextTool,
    LatticePacketInput,
    LatticePacketTool,
)
from chorus_tools._manager_actions import (
    AssignTaskInput,
    AssignTaskTool,
    SubmitTaskInput,
    SubmitTaskTool,
)
from chorus_tools._recall import RecallInput, RecallTool
from chorus_tools._record_decision import RecordDecisionInput, RecordDecisionTool
from chorus_tools._registry import chorus_tool_registry
from chorus_tools._secret_scan import (
    SecretFinding,
    SecretScanInput,
    SecretScanReport,
    SecretScanTool,
    scan_text,
    write_report,
)
from chorus_tools._staffing_request import (
    StaffingNeedInput,
    StaffingRequestInput,
    StaffingRequestTool,
)
from chorus_tools._submit_verdict import SubmitVerdictInput, SubmitVerdictTool
from chorus_tools._team_read import TeamReadInput, TeamReadTool
from chorus_tools._test_evidence import (
    EvidenceManifest,
    GateResult,
    GateSpec,
    TestEvidenceInput,
    TestEvidenceTool,
    TestRedInput,
    TestRedTool,
    write_bundle,
)
from chorus_tools._workforce_plan import (
    ManagementGrantInput,
    PlannedEmployeeInput,
    WorkforceCatalogReadInput,
    WorkforceCatalogReadTool,
    WorkforcePlanProposeInput,
    WorkforcePlanProposeTool,
)

__all__ = [
    "GOVERNANCE_TOOL_NAMES",
    "AssignTaskInput",
    "AssignTaskTool",
    "BrandFinding",
    "BrandLintInput",
    "BrandLintTool",
    "ChartRenderTool",
    "CodeQualityInput",
    "CodeQualityTool",
    "DecomposeInput",
    "DecomposeTool",
    "DesignExemplarInput",
    "DesignExemplarTool",
    "DesignFinding",
    "DesignLintInput",
    "DesignLintTool",
    "DesignTokens",
    "EvidenceFinding",
    "EvidenceManifest",
    "EvidenceReport",
    "EvidenceScanInput",
    "EvidenceScanTool",
    "EvidenceSpec",
    "GateResult",
    "GateSpec",
    "GetRunInput",
    "GetRunTool",
    "GoLiveAction",
    "GoLiveInput",
    "GoLiveTool",
    "GoalArchiveTool",
    "GoalSetPriorityTool",
    "GovernanceReadTool",
    "LatticeApplyInput",
    "LatticeApplyTool",
    "LatticeContextInput",
    "LatticeContextTool",
    "LatticePacketInput",
    "LatticePacketTool",
    "LogAssessment",
    "ManagementGrantInput",
    "NotebookRunTool",
    "PlannedEmployeeInput",
    "ProposalApproveTool",
    "ProposalRejectTool",
    "QualityCheck",
    "QualityCheckSpec",
    "QualityReport",
    "RecallInput",
    "RecallTool",
    "RecordDecisionInput",
    "RecordDecisionTool",
    "RepoSearchTool",
    "SecretFinding",
    "SecretScanInput",
    "SecretScanReport",
    "SecretScanTool",
    "StaffingNeedInput",
    "StaffingRequestInput",
    "StaffingRequestTool",
    "SubmitTaskInput",
    "SubmitTaskTool",
    "SubmitVerdictInput",
    "SubmitVerdictTool",
    "TeamReadInput",
    "TeamReadTool",
    "TestEvidenceInput",
    "TestEvidenceTool",
    "TestRedInput",
    "TestRedTool",
    "WarehouseQueryTool",
    "WorkforceCatalogReadInput",
    "WorkforceCatalogReadTool",
    "WorkforcePlanProposeInput",
    "WorkforcePlanProposeTool",
    "analysis_tool",
    "available_exemplars",
    "chorus_tool_registry",
    "governance_tool",
    "is_noop_quality_command",
    "scan_text",
    "write_bundle",
    "write_quality_report",
    "write_report",
]
