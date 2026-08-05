"""A hard ceiling on what one session can spend on the LLM.

Two processors instead of one because the frames they need travel in opposite halves of
the pipeline: usage metrics are pushed *downstream* by the LLM service, so nothing sitting
in front of the model ever sees them. `Counter` goes after the LLM and adds up, `Gate`
goes before it and refuses. They share one `Budget`.

The ceiling is a stuck-loop backstop, not a quota to feel: a tool-calling model that
mis-parses its own output can retry forever, and a car sitting in a garage with the
engine on has all night to do it.
"""
from dataclasses import dataclass

from pipecat.frames.frames import Frame, LLMContextFrame, MetricsFrame, TTSSpeakFrame
from pipecat.metrics.metrics import LLMUsageMetricsData
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

REFUSAL = "Phiên làm việc đã đạt giới hạn. Bạn khởi động lại trợ lý để tiếp tục nhé."


@dataclass
class Budget:
    """Counts of what this session has used. `max_*` of 0 disables that limit."""

    max_turns: int
    max_tokens: int
    turns: int = 0
    tokens: int = 0

    def exhausted(self) -> bool:
        return ((self.max_turns and self.turns >= self.max_turns)
                or (self.max_tokens and self.tokens >= self.max_tokens))


class Counter(FrameProcessor):
    """Sits after the LLM, where usage metrics are pushed."""

    def __init__(self, budget: Budget):
        super().__init__()
        self._budget = budget

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, MetricsFrame):
            for d in frame.data:
                if isinstance(d, LLMUsageMetricsData):
                    self._budget.tokens += d.value.total_tokens
        await self.push_frame(frame, direction)


class Gate(FrameProcessor):
    """Sits before the LLM. Over budget, the question never reaches the model."""

    def __init__(self, budget: Budget):
        super().__init__()
        self._budget = budget
        self._announced = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            if self._budget.exhausted():
                # Dropping the context frame is what stops the spend. Say so once —
                # repeating the same sentence at every attempt is worse than silence.
                if not self._announced:
                    self._announced = True
                    await self.push_frame(TTSSpeakFrame(REFUSAL))
                return
            self._budget.turns += 1
        await self.push_frame(frame, direction)
