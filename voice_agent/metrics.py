"""First Audio Latency measurement, per the definition in the brief."""
import statistics
import time

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    TTSAudioRawFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class LatencyProbe(FrameProcessor):
    """FAL = first response audio frame played - moment the system decided the user stopped.

    Sits at the end of the pipeline, just before the transport output, so it sees
    exactly the frame about to reach the speaker.
    ponytail: does not subtract the device output buffer (~20-40ms), so the reported
    number is slightly optimistic. For more precision, read `outputBufferDacTime`
    from PortAudio.
    """

    def __init__(self, on_sample=None):
        super().__init__()
        self.t0 = None
        self.samples: list[float] = []
        self.discarded = 0  # turns dropped to barge-in — reported alongside p50, never hidden
        self._on_sample = on_sample

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            # Barge-in: audio from the interrupted turn is still in flight. Arriving
            # after the new turn started its clock, it would read as an impossibly
            # fast FAL. Drop the turn being measured.
            self.t0 = None
            self.discarded += 1
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self.t0 = time.monotonic()
        elif isinstance(frame, TTSAudioRawFrame) and self.t0 is not None:
            ms = (time.monotonic() - self.t0) * 1000
            self.t0 = None
            self.samples.append(ms)
            if self._on_sample:
                self._on_sample(ms)
        await self.push_frame(frame, direction)

    def summary(self) -> dict:
        """p50/p95/max over measured turns. Empty when nothing has been measured."""
        if not self.samples:
            return {}
        s = sorted(self.samples)
        return {"n": len(s), "p50": statistics.median(s),
                "p95": s[max(0, round(len(s) * 0.95) - 1)], "max": s[-1],
                "discarded": self.discarded}
