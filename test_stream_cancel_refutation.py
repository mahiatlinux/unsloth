import asyncio
import threading

import pytest

from core.inference import transcript_stream
from core.inference.stt_sidecar import WhisperSttSidecar
from core.inference.stt_mtmd_sidecar import MtmdSttSidecar
from core.inference.stt_ggml_sidecar import GgmlSttSidecar
from routes import inference


@pytest.mark.parametrize('engine,sidecar_type', [
    ('transformers', WhisperSttSidecar),
    ('mtmd', MtmdSttSidecar),
    ('gguf', GgmlSttSidecar),
])
def test_stream_close_stops_worker_without_request_watcher(monkeypatch, engine, sidecar_type):
    sidecar = sidecar_type()
    started = threading.Event()
    stopped = threading.Event()
    events = []
    saved = []

    def transcribe(raw, model, language, fast, cancel_event, on_progress=None):
        events.append(cancel_event)
        started.set()
        assert cancel_event.wait(2), 'the real sidecar cancellation method did not set the worker event'
        stopped.set()
        return {'text': 'cancelled result', 'model': model}

    monkeypatch.setattr(sidecar, 'transcribe', transcribe)
    monkeypatch.setattr(inference.account_access, 'managed_account', lambda: False)
    monkeypatch.setattr(inference, '_prepare_runtime_fallback_checkpoint', lambda *args: None)
    monkeypatch.setattr(inference, '_resolve_serving_stt_engine', lambda _engine: engine)
    monkeypatch.setattr(inference, '_stt_sidecar_for', lambda _engine: sidecar)
    monkeypatch.setattr(inference, '_stt_lifecycle', lambda: (lambda *args, **kwargs: None, None))
    monkeypatch.setattr(transcript_stream.transcript_gallery, 'save', lambda *args: saved.append(args))

    async def scenario():
        stream = transcript_stream.stream_transcript(
            lambda progress: inference._transcribe_audio_result(
                b'audio', 'tiny', None, True, engine, None, 'cpu', progress,
            ),
            'cancel refutation',
        )
        await anext(stream)
        assert await asyncio.to_thread(started.wait, 2)
        await stream.aclose()
        assert await asyncio.to_thread(stopped.wait, 2)
        assert events[0].is_set()
        assert saved == []

    asyncio.run(scenario())
