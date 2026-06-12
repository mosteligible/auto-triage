from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Any

from auto_triage.config import Settings
from auto_triage.schemas import NormalizedIncident
from auto_triage.security import secret_value

PY_STACK_RE = re.compile(r'File "([^"]+)", line (\d+), in ([^\n]+)')
JS_STACK_RE = re.compile(r"\s+at\s+(?:(.*?)\s+\()?(.+?):(\d+):(\d+)\)?")

SOURCE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".mypy_cache"}


class CodebaseInspector:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def inspect(
        self,
        incident_id: str,
        incident: NormalizedIncident,
        logfire_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        repo_url = self.settings.effective_target_repo_url
        if not repo_url:
            return {
                "available": False,
                "warnings": [
                    "TARGET_REPO_URL or GITHUB_REPO is not configured; skipped code search."
                ],
                "matches": [],
            }

        workspace_dir = self.settings.effective_workspace_dir
        workspace_dir.mkdir(parents=True, exist_ok=True)
        repo_path = workspace_dir / incident_id
        if repo_path.exists():
            shutil.rmtree(repo_path)

        clone_result = await self._clone(repo_url, repo_path)
        try:
            matches = self._collect_matches(repo_path, incident, logfire_records)
            return {
                "available": True,
                "repo_url": _safe_repo_url(repo_url),
                "branch": self.settings.github_default_branch,
                "clone": clone_result,
                "matches": matches,
            }
        finally:
            if self.settings.cleanup_repo_after_triage and repo_path.exists():
                shutil.rmtree(repo_path)

    async def _clone(self, repo_url: str, destination: Path) -> dict[str, Any]:
        token = secret_value(self.settings.github_token)
        env = os.environ.copy()
        if token and "github.com" in repo_url:
            env.update(
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                    "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {token}",
                }
            )

        command = [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            self.settings.github_default_branch,
            repo_url,
            str(destination),
        ]
        result = await _run_command(command, env)
        if result["returncode"] == 0:
            return {"used_branch": self.settings.github_default_branch, **result}

        fallback_command = ["git", "clone", "--depth", "1", repo_url, str(destination)]
        fallback = await _run_command(fallback_command, env)
        if fallback["returncode"] != 0:
            raise RuntimeError(
                "git clone failed: "
                + (fallback.get("stderr") or result.get("stderr") or "unknown error")
            )
        return {"used_branch": None, "branch_fallback": True, **fallback}

    def _collect_matches(
        self,
        repo_path: Path,
        incident: NormalizedIncident,
        logfire_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        seen: set[tuple[str, int, str]] = set()

        for frame in self._stack_frames(incident, logfire_records):
            file_path = self._find_file(repo_path, frame["path"])
            if file_path is None:
                continue
            snippet = self._snippet(file_path, repo_path, frame.get("line"), reason=frame["reason"])
            key = (snippet["file"], snippet["start_line"], snippet["reason"])
            if key not in seen:
                matches.append(snippet)
                seen.add(key)
            if len(matches) >= self.settings.max_code_snippets:
                return matches

        for term in self._search_terms(incident):
            for file_path, line in self._search_text(repo_path, term):
                snippet = self._snippet(file_path, repo_path, line, reason=f"matched text: {term}")
                key = (snippet["file"], snippet["start_line"], snippet["reason"])
                if key in seen:
                    continue
                matches.append(snippet)
                seen.add(key)
                if len(matches) >= self.settings.max_code_snippets:
                    return matches

        return matches

    def _stack_frames(
        self,
        incident: NormalizedIncident,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        stacktraces = [
            incident.exception_stacktrace,
            *(record.get("exception_stacktrace") for record in records),
        ]
        frames: list[dict[str, Any]] = []
        for stacktrace in stacktraces:
            if not isinstance(stacktrace, str) or not stacktrace.strip():
                continue
            for path, line, function in PY_STACK_RE.findall(stacktrace):
                frames.append(
                    {
                        "path": path,
                        "line": int(line),
                        "function": function.strip(),
                        "reason": f"python stack frame: {function.strip()}",
                    }
                )
            for function, path, line, _column in JS_STACK_RE.findall(stacktrace):
                frames.append(
                    {
                        "path": path,
                        "line": int(line),
                        "function": (function or "<anonymous>").strip(),
                        "reason": f"javascript stack frame: {(function or '<anonymous>').strip()}",
                    }
                )

        if incident.top_frame:
            parsed = _parse_top_frame(incident.top_frame)
            if parsed:
                frames.insert(0, parsed)
        return frames

    def _search_terms(self, incident: NormalizedIncident) -> list[str]:
        terms: list[str] = []
        for term in (incident.route, incident.span_name, incident.exception_type):
            if term and 3 <= len(term) <= 120:
                terms.append(term)
        if incident.route and " " in incident.route:
            route_only = incident.route.split(" ", 1)[1]
            if route_only:
                terms.append(route_only)
        return list(dict.fromkeys(terms))

    def _search_text(self, repo_path: Path, term: str) -> list[tuple[Path, int]]:
        matches: list[tuple[Path, int]] = []
        for path in self._source_files(repo_path):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            index = text.find(term)
            if index == -1:
                continue
            line = text[:index].count("\n") + 1
            matches.append((path, line))
            if len(matches) >= self.settings.max_code_snippets:
                break
        return matches

    def _find_file(self, repo_path: Path, frame_path: str) -> Path | None:
        candidate = Path(frame_path)
        if candidate.is_absolute():
            parts = [part for part in candidate.parts if part != candidate.anchor][-6:]
        else:
            parts = candidate.parts
        if not parts:
            return None

        suffix = Path(*parts).as_posix()
        repo_root = repo_path.resolve()

        direct = (repo_path / suffix).resolve()
        if direct.exists() and direct.is_file():
            try:
                direct.relative_to(repo_root)
            except ValueError:
                pass
            else:
                return direct

        for path in self._source_files(repo_path):
            relative = self._relative_file(path, repo_path)
            if relative.endswith(suffix) or relative.endswith(Path(frame_path).name):
                return path
        return None

    def _source_files(self, repo_path: Path) -> list[Path]:
        files: list[Path] = []
        for path in repo_path.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > self.settings.max_file_bytes:
                    continue
            except OSError:
                continue
            files.append(path)
        return files

    def _snippet(
        self,
        path: Path,
        repo_path: Path,
        center_line: int | None,
        *,
        reason: str,
    ) -> dict[str, Any]:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if center_line is None:
            center_line = 1
        half_window = max(self.settings.max_snippet_lines // 2, 1)
        start = max(center_line - half_window, 1)
        end = min(start + self.settings.max_snippet_lines - 1, len(lines))
        numbered = [
            f"{line_number}: {lines[line_number - 1]}"
            for line_number in range(start, end + 1)
        ]
        return {
            "file": self._relative_file(path, repo_path),
            "start_line": start,
            "end_line": end,
            "reason": reason,
            "content": "\n".join(numbered),
        }

    @staticmethod
    def _relative_file(path: Path, repo_path: Path) -> str:
        return path.resolve().relative_to(repo_path.resolve()).as_posix()


async def _run_command(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        *command,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return {
        "returncode": process.returncode,
        "stdout": stdout.decode("utf-8", errors="ignore")[-4_000:],
        "stderr": stderr.decode("utf-8", errors="ignore")[-4_000:],
    }


def _parse_top_frame(top_frame: str) -> dict[str, Any] | None:
    parts = top_frame.rsplit(":", 2)
    if len(parts) != 3:
        return None
    path, line, function = parts
    try:
        line_number = int(line)
    except ValueError:
        return None
    return {
        "path": path,
        "line": line_number,
        "function": function.strip(),
        "reason": f"top frame: {function.strip()}",
    }


def _safe_repo_url(repo_url: str) -> str:
    return re.sub(r"https://[^/@]+@", "https://[redacted]@", repo_url)
