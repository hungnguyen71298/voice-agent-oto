"""Wire up the voice pipeline and run it.

    python -m voice_agent
"""
import sys

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import FunctionCallResultProperties, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.worker import PipelineParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

from . import audio, budget, config, tools, ui
from . import tts as tts_engine
from .metrics import LatencyProbe
from .schema import to_schema
from .tools import vehicle
from .tools.vehicle import describe_state


def transport_params() -> LocalAudioTransportParams:
    """Audio settings shared by the live microphone and the file-driven e2e run.

    No `vad_analyzer` here on purpose. Pipecat 1.7 removed it from `TransportParams`
    and moved voice activity detection into its own `VADProcessor` in the pipeline —
    but the field is still accepted silently, so passing it looks correct and does
    nothing. `scripts/e2e.py` is what caught that.
    """
    return LocalAudioTransportParams(audio_in_enabled=True, audio_out_enabled=True,
                                     input_device_index=config.INPUT_DEVICE)


def build_task(transport: BaseTransport | None = None) -> tuple[PipelineTask, LatencyProbe]:
    """Assemble the pipeline.

    Args:
        transport: Audio in and out. Defaults to the local microphone and speaker;
            `scripts/e2e.py` passes a file-backed one so the whole pipeline can be
            exercised without anybody speaking.
    """
    if transport is None:
        params = transport_params()
        transport = (audio.NativeRateAudioTransport(params, config.INPUT_RATE)
                     if config.INPUT_RATE else LocalAudioTransport(params))
    stt = OpenAISTTService(
        api_key=config.OPENROUTER_KEY, base_url=config.OPENROUTER_BASE,
        settings=OpenAISTTService.Settings(model=config.STT_MODEL, language=Language.VI,
                                           prompt=config.STT_PROMPT))
    llm = OpenAILLMService(
        api_key=config.OPENROUTER_KEY, base_url=config.OPENROUTER_BASE,
        settings=OpenAILLMService.Settings(model=config.LLM_MODEL))
    tts = tts_engine.build()

    for fn in tools.ALL:
        async def handler(params, _name=fn.__name__):
            result = tools.dispatch(_name, params.arguments)
            print(f"  🔧 {_name}({params.arguments}) → {result}", flush=True)
            ui.emit("tool", name=_name, args=str(dict(params.arguments)),
                    result=ui.summarise(result))
            ui.emit_state()
            speech = result.get("speech")
            if not speech:
                await params.result_callback(result)  # let the LLM phrase the answer
                return
            # The tool already knows the whole answer, so the second LLM round trip buys
            # nothing but latency. Speak the sentence and tell Pipecat not to re-run the
            # model. `append_to_context` keeps the turn in history for follow-up questions
            # like "tăng thêm hai độ nữa".
            await params.llm.push_frame(TTSSpeakFrame(speech, append_to_context=True))
            await params.result_callback(
                result, properties=FunctionCallResultProperties(run_llm=False))

        llm.register_function(fn.__name__, handler)

    def system_prompt() -> list[dict]:
        return [{"role": "system",
                 "content": config.SYSTEM_PROMPT.format(state=describe_state())}]

    ctx = LLMContext(system_prompt(), tools=[to_schema(f) for f in tools.ALL])
    agg = LLMContextAggregatorPair(ctx)

    async def reset():
        """Dashboard reset: forget the conversation and put the car back to defaults.

        Three steps, and the middle one is the whole reason this is not a one-liner.

        Pressed just after a tool call, reset used to clear the context and *then* that
        turn's confirmation sentence would land in the fresh context — leaving a history
        that opened with the agent speaking and no question before it. The model read
        that as unfinished work and re-ran the command on whatever it heard next.

        Flushing is not enough on its own, which the live test proved: pipecat stamps the
        frame that commits spoken text with a PTS and sends it through the transport's
        *clock* queue, so it is timed to the audio rather than queued behind the flush
        probe. The probe reaches the source and reports "drained" while that frame is
        still waiting for its playback slot. Clearing the assistant aggregator's buffer
        is what actually covers it — the commit frame then arrives to find nothing to
        write, whichever side of this function it lands on.

        Order matters at the end too: the system prompt embeds the vehicle state, so
        rebuild it after resetting the car or the agent starts out believing the old
        settings.
        """
        if not await task.flush_pipeline():
            print("  ↺ reset: pipeline did not drain in time", flush=True)
        await agg.assistant().reset()
        vehicle.reset_state()
        ctx.set_messages(system_prompt())
        print("  ↺ reset", flush=True)

    def on_fal(ms: float):
        print(f"\n  ⏱  FAL {ms:.0f} ms\n", flush=True)
        ui.emit("fal", ms=round(ms))

    probe = LatencyProbe(on_sample=on_fal)

    # VADProcessor turns raw audio into VADUserStarted/StoppedSpeaking frames; the user
    # aggregator downstream promotes those to the UserStoppedSpeakingFrame that starts the
    # FAL clock. Remove it and the pipeline goes silent — audio flows, nothing reacts.
    #
    # Two UIProbes, because no single point sees the whole turn: the user aggregator
    # consumes TranscriptionFrame, so the transcript has to be read before it, and the
    # spoken text only exists after TTS. Each probe ignores the frames it never sees.
    money = budget.Budget(config.MAX_TURNS, config.MAX_TOKENS)
    task = PipelineTask(
        Pipeline([transport.input(), ui.MicGate(),
                  VADProcessor(vad_analyzer=SileroVADAnalyzer()),
                  stt, ui.UIProbe(), agg.user(), budget.Gate(money), llm,
                  budget.Counter(money), tts, probe, ui.UIProbe(),
                  transport.output(), agg.assistant()]),
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        # Pipecat cancels the pipeline after 300s with no speech. Sensible for a phone
        # bot paying for a call; wrong for a car, where the assistant has to still be
        # listening after an hour of quiet driving. Observed as the agent simply exiting
        # mid-demo with "CancelFrame (reason: idle timeout)".
        cancel_on_idle_timeout=False)

    # Registered here, not next to `reset`, because it closes over `task`.
    ui.set_reset_handler(reset)
    return task, probe


async def run_task(task: PipelineTask, *, auto_end: bool = True):
    """Run a built pipeline to completion. Separated so e2e can drive one it owns.

    Args:
        task: The pipeline to run.
        auto_end: Pipecat's default ends the runner as soon as every root worker is
            finished. A live microphone never finishes, so that is right here — but a
            file-backed transport is "finished" the moment it is started, which cancels
            the pipeline before a single frame goes in. `scripts/e2e.py` passes False
            and sends its own `EndFrame`.
    """
    await PipelineRunner(handle_sigint=True).run(task, auto_end=auto_end)


async def run():
    if not config.OPENROUTER_KEY:
        sys.exit("OPENROUTER_API_KEY is missing or still the placeholder.\n"
                 "  cp .env.example .env   then paste a real key from https://openrouter.ai/keys")

    task, probe = build_task()
    runner = await ui.start(config.UI_PORT, config.UI_HOST)
    voice = config.PIPER_VOICE if config.TTS_ENGINE == "piper" else config.EDGE_VOICE
    dashboard = f"http://{config.UI_HOST}:{config.UI_PORT}" if runner else "off (UI_PORT=0)"
    print(f"STT={config.STT_MODEL}\nLLM={config.LLM_MODEL}\n"
          f"TTS={config.TTS_ENGINE}/{voice}\n"
          f"KB={len(tools.knowledge.DOCS)} chunks\nDashboard: {dashboard}\n\n"
          f"Start speaking (Ctrl+C to quit)...", flush=True)
    try:
        await run_task(task)
    finally:
        if runner:
            await runner.cleanup()
        if s := probe.summary():
            print(f"\nFAL: n={s['n']}  p50={s['p50']:.0f}ms  p95={s['p95']:.0f}ms  "
                  f"max={s['max']:.0f}ms  discarded={s['discarded']}")
