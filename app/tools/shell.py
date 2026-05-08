from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True)
class CommandResult:
    args: Sequence[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class ShellTool(Protocol):
    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: int = 600,
    ) -> CommandResult:
        ...


class LocalShellTool:
    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: int = 600,
    ) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
        return CommandResult(
            args=args,
            returncode=process.returncode,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )

