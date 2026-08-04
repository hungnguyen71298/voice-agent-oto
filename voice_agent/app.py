"""Wire up the voice pipeline and run it.

    python -m voice_agent
"""
import sys

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.worker import PipelineParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

from . import config, tools
from .metrics import LatencyProbe
from .schema import to_schema
from .tools.vehicle import describe_state


def build_task() -> tuple[PipelineTask, LatencyProbe]:
    """Assemble the pipeline. Split out from `run()` so tests and benchmarks can reuse it."""
    transport = LocalAudioTransport(LocalAudioTransportParams(
        audio_in_enabled=True, audio_out_enabled=True, vad_analyzer=SileroVADAnalyzer()))
    stt = OpenAISTTService(api_key=config.OPENROUTER_KEY, base_url=config.OPENROUTER_BASE,
                           model=config.STT_MODEL, language=Language.VI)
    llm = OpenAILLMService(api_key=config.OPENROUTER_KEY, base_url=config.OPENROUTER_BASE,
                           model=config.LLM_MODEL)
    tts = OpenAITTSService(api_key=config.OPENROUTER_KEY, base_url=config.OPENROUTER_BASE,
                           model=config.TTS_MODEL, voice=config.TTS_VOICE)

    for fn in tools.ALL:
        async def handler(params, _name=fn.__name__):
            result = tools.dispatch(_name, params.arguments)
            print(f"  🔧 {_name}({params.arguments}) → {result}", flush=True)
            await params.result_callback(result)

        llm.register_function(fn.__name__, handler)

    ctx = LLMContext(
        [{"role": "system", "content": config.SYSTEM_PROMPT.format(state=describe_state())}],
        tools=[to_schema(f) for f in tools.ALL])
    agg = LLMContextAggregatorPair(ctx)
    probe = LatencyProbe(on_sample=lambda ms: print(f"\n  ⏱  FAL {ms:.0f} ms\n", flush=True))

    task = PipelineTask(
        Pipeline([transport.input(), stt, agg.user(), llm, tts, probe,
                  transport.output(), agg.assistant()]),
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True))
    return task, probe


async def run():
    if not config.OPENROUTER_KEY:
        sys.exit("Missing OPENROUTER_API_KEY — see .env.example")

    task, probe = build_task()
    print(f"STT={config.STT_MODEL}\nLLM={config.LLM_MODEL}\nTTS={config.TTS_MODEL}\n"
          f"KB={len(tools.knowledge.DOCS)} chunks\n\nStart speaking (Ctrl+C to quit)...",
          flush=True)
    try:
        await PipelineRunner(handle_sigint=True).run(task)
    finally:
        if s := probe.summary():
            print(f"\nFAL: n={s['n']}  p50={s['p50']:.0f}ms  p95={s['p95']:.0f}ms  "
                  f"max={s['max']:.0f}ms  discarded={s['discarded']}")
