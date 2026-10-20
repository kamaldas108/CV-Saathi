"""One student's CV session: notebook, design, screen step and sample-mode interviewer."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .design import DesignSettings
from .notebook import CvNotebook
from .sample_interviewer import SampleInterviewer


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    owner: str = ""
    notebook: CvNotebook = field(default_factory=CvNotebook)
    design: DesignSettings = field(default_factory=DesignSettings)
    design_revision: int = 0
    step: str = "interview"
    interviewer: SampleInterviewer = field(default_factory=SampleInterviewer)
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)
    live_socket: Any = None
    tasks: set = field(default_factory=set)
    usage: dict[str, int] = field(default_factory=dict)
    tool_failures: dict[str, int] = field(default_factory=dict)
    drafting: bool = False
    draft_task: Any = None

    def reset(self) -> None:
        """Start over (F12): clear the notebook and design, and stop background work."""
        for task in list(self.tasks):
            task.cancel()
        self.tasks.clear()
        if self.draft_task is not None:
            self.draft_task.cancel()
            self.draft_task = None
        self.drafting = False
        self.notebook = CvNotebook()
        self.design = DesignSettings()
        self.design_revision += 1
        self.step = "interview"
        self.interviewer = SampleInterviewer()
        self.tool_failures.clear()
        self.updated_at = time.monotonic()

    async def close_live(self) -> None:
        if self.live_socket is not None:
            try:
                await self.live_socket.close(code=1000)
            except Exception:
                pass
            self.live_socket = None
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        self.tasks.clear()
