from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from app.state import IssueRef


@dataclass(frozen=True)
class PullRequestRef:
    repository: str
    number: int
    url: str
    branch: str


class GitHubTool(Protocol):
    async def list_open_issues(self, repository: str) -> list[IssueRef]:
        ...

    async def add_issue_label(self, repository: str, issue_number: int, label: str) -> None:
        ...

    async def create_pull_request(
        self,
        repository: str,
        *,
        branch: str,
        title: str,
        body: str,
    ) -> PullRequestRef:
        ...


class McpToolInvoker(Protocol):
    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        ...


class McpGitHubTool:
    """GitHub adapter boundary for a configured MCP server.

    The MCP transport/client is intentionally injected so this module does not
    couple the graph to one server launch strategy.
    """

    def __init__(self, invoker: McpToolInvoker | None = None) -> None:
        self._invoker = invoker

    async def list_open_issues(self, repository: str) -> list[IssueRef]:
        response = await self._call(
            "github.list_issues",
            {"repository": repository, "state": "open"},
        )
        return [self._issue_from_payload(repository, issue) for issue in self._as_items(response)]

    async def add_issue_label(self, repository: str, issue_number: int, label: str) -> None:
        await self._call(
            "github.add_issue_labels",
            {
                "repository": repository,
                "issue_number": issue_number,
                "labels": [label],
            },
        )

    async def create_pull_request(
        self,
        repository: str,
        *,
        branch: str,
        title: str,
        body: str,
    ) -> PullRequestRef:
        payload = await self._call(
            "github.create_pull_request",
            {
                "repository": repository,
                "head": branch,
                "title": title,
                "body": body,
            },
        )
        return PullRequestRef(
            repository=repository,
            number=int(payload.get("number", 0)),
            url=str(payload.get("html_url") or payload.get("url") or ""),
            branch=branch,
        )

    async def _call(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if self._invoker is None:
            raise RuntimeError("GitHub MCP invoker is not configured")
        return await self._invoker.call_tool(name, arguments)

    @staticmethod
    def _as_items(response: Any) -> list[Mapping[str, Any]]:
        if isinstance(response, list):
            return [item for item in response if isinstance(item, Mapping)]
        if isinstance(response, Mapping):
            items = response.get("items") or response.get("issues") or []
            return [item for item in items if isinstance(item, Mapping)]
        return []

    @staticmethod
    def _issue_from_payload(repository: str, payload: Mapping[str, Any]) -> IssueRef:
        raw_labels = payload.get("labels") or []
        labels: list[str] = []
        for label in raw_labels:
            if isinstance(label, str):
                labels.append(label)
            elif isinstance(label, Mapping) and label.get("name"):
                labels.append(str(label["name"]))

        return IssueRef(
            repository=repository,
            number=int(payload["number"]),
            title=str(payload.get("title") or ""),
            body=payload.get("body"),
            labels=labels,
            url=payload.get("html_url") or payload.get("url"),
        )

