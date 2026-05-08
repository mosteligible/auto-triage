from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.config import Settings
from app.nodes.claim_issue import claim_issue_node
from app.nodes.discover_issues import discover_issues_node
from app.persistence.checkpoint import SQLiteCheckpointStore
from app.persistence.job_store import SQLiteJobStore
from app.state import TriageGraphState, TriageStatus
from app.tools.github_tool import GitHubTool
from app.tools.openai_agent import FixAgent, FixOutcome


@dataclass
class TriageGraph:
    settings: Settings
    job_store: SQLiteJobStore
    checkpoint_store: SQLiteCheckpointStore
    github: GitHubTool
    fix_agent: FixAgent

    def __post_init__(self) -> None:
        self._discovery_graph = self._build_discovery_graph()
        self._job_graph = self._build_job_graph()

    async def run_discovery(self) -> TriageGraphState:
        return await self._discovery_graph.ainvoke({})

    async def run_next_job(self) -> TriageGraphState:
        return await self._job_graph.ainvoke({})

    async def resume_job(self, job_id: str) -> TriageGraphState:
        return await self._job_graph.ainvoke({"job_id": job_id})

    def _build_discovery_graph(self):
        graph = StateGraph(TriageGraphState)
        graph.add_node("discover_issues", self._discover_issues)
        graph.add_edge(START, "discover_issues")
        graph.add_edge("discover_issues", END)
        return graph.compile()

    def _build_job_graph(self):
        graph = StateGraph(TriageGraphState)
        graph.add_node("claim_issue", self._claim_issue)
        graph.add_node("attempt_fix", self._attempt_fix)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "claim_issue")
        graph.add_conditional_edges(
            "claim_issue",
            self._route_after_claim,
            {"attempt_fix": "attempt_fix", "end": END},
        )
        graph.add_conditional_edges(
            "attempt_fix",
            self._route_after_attempt,
            {"finalize": "finalize", "end": END},
        )
        graph.add_edge("finalize", END)
        return graph.compile()

    async def _discover_issues(self, state: TriageGraphState) -> TriageGraphState:
        return await discover_issues_node(
            state,
            settings=self.settings,
            github=self.github,
            job_store=self.job_store,
        )

    async def _claim_issue(self, state: TriageGraphState) -> TriageGraphState:
        next_state = await claim_issue_node(
            state,
            job_store=self.job_store,
            lease_seconds=self.settings.triage_lease_seconds,
        )
        claimed_job_id = next_state.get("claimed_job_id")
        if claimed_job_id:
            self.checkpoint_store.save(claimed_job_id, {"node": "claim_issue", "state": next_state})
        return next_state

    async def _attempt_fix(self, state: TriageGraphState) -> TriageGraphState:
        job_id = state.get("claimed_job_id")
        if not job_id:
            return {**state, "message": "no claimed job to fix"}

        job = self.job_store.get(job_id)
        if job is None:
            return {**state, "message": "claimed job disappeared"}

        outcome = await self.fix_agent.attempt_fix(job)
        next_state = self._state_from_outcome(state, outcome)
        self.checkpoint_store.save(job_id, {"node": "attempt_fix", "state": next_state})

        if not outcome.should_finalize:
            requeued = job.transition(
                TriageStatus.QUEUED,
                failure_reason=outcome.failure_reason,
                locked_until=None,
            )
            self.job_store.update(requeued)
            return {**next_state, "message": outcome.failure_reason or "job requeued"}

        return next_state

    async def _finalize(self, state: TriageGraphState) -> TriageGraphState:
        job_id = state.get("claimed_job_id")
        if not job_id:
            return {**state, "message": "no claimed job to finalize"}

        job = self.job_store.get(job_id)
        if job is None:
            return {**state, "message": "claimed job disappeared"}

        errors = list(state.get("errors", []))
        if state.get("fix_success"):
            stored = self.job_store.mark_resolved(
                job_id,
                branch_name=state.get("branch_name"),
                pull_request_url=state.get("pull_request_url"),
            )
            label = self.settings.github_issue_fixed_tag
        else:
            stored = self.job_store.mark_unable_to_fix(
                job_id,
                reason=state.get("failure_reason") or "fix agent did not produce a fix",
            )
            label = self.settings.github_issue_unable_to_fix_tag

        try:
            await self.github.add_issue_label(job.issue.repository, job.issue.number, label)
        except Exception as exc:
            errors.append(f"failed to add GitHub label {label}: {exc}")

        self.checkpoint_store.save(job_id, {"node": "finalize", "state": state})
        message = f"job finalized as {stored.status.value}" if stored else "job finalization failed"
        return {**state, "errors": errors, "message": message}

    @staticmethod
    def _state_from_outcome(state: TriageGraphState, outcome: FixOutcome) -> TriageGraphState:
        next_state: TriageGraphState = {
            **state,
            "fix_success": outcome.success,
            "should_finalize": outcome.should_finalize,
        }
        if outcome.summary:
            next_state["summary"] = outcome.summary
        if outcome.branch_name:
            next_state["branch_name"] = outcome.branch_name
        if outcome.pull_request_url:
            next_state["pull_request_url"] = outcome.pull_request_url
        if outcome.failure_reason:
            next_state["failure_reason"] = outcome.failure_reason
        return next_state

    @staticmethod
    def _route_after_claim(state: TriageGraphState) -> Literal["attempt_fix", "end"]:
        return "attempt_fix" if state.get("claimed_job_id") and state.get("job_id") else "end"

    @staticmethod
    def _route_after_attempt(state: TriageGraphState) -> Literal["finalize", "end"]:
        return "finalize" if state.get("should_finalize") else "end"

