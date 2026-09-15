# Real Transformers Whisper verification

## Runtime and model

- Source: `after/studio/backend`
- Python: 3.12.13
- PyTorch: 2.10.0+cu130
- Transformers: 5.5.0
- Tokenizers: 0.22.2
- GPU: NVIDIA GeForce RTX 5060 Ti
- Model: `openai/whisper-tiny`
- Model revision: `169d4a4341b33bc18d8881c4b69c2e104e1cc0af`
- Model download: Studio's real STT HTTP downloader, 155,434,424 bytes
- Audio: public whisper.cpp JFK sample repeated into 44-second and 220-second PCM WAV files

The server mounted the actual Studio inference router. Authentication was overridden for the disposable local process. STT routing, model loading, audio decoding, 30-second windowing, spawned worker inference, NDJSON streaming, cancellation, gallery save, and unload used the source snapshot without inference mocks.

## Streaming completion

CPU, cold model load, 44-second audio:

- initial empty progress: 0.045 seconds
- first nonempty progress after the 30-second window: 9.175 seconds
- second progress after the 44-second tail: 9.866 seconds
- complete event: 9.867 seconds
- complete event followed the partial events and matched the final partial text
- gallery save occurred with the complete result

GPU, cold device switch, 44-second audio:

- initial empty progress: 0.037 seconds
- first nonempty progress after the 30-second window: 7.183 seconds
- complete event: 7.287 seconds
- spawned CUDA worker peaked at 358 MiB in `nvidia-smi` samples
- the final 14-second window completed within the 250 ms progress throttle, so its text appeared in the complete event rather than a separate progress event

Both transcripts accurately contained the expected JFK sentence, "ask not what your country can do for you, ask what you can do for your country," across the repeated sample.

## Cancellation and recovery

The warm CPU worker transcribed a 220-second repeated public-speech file through the actual streaming route:

- initial empty progress: 0.050 seconds
- first nonempty progress after 30 seconds of audio: 1.323 seconds
- client closed the HTTP stream immediately after that partial
- no complete event was received
- no `real-whisper-cancel` gallery record was created
- at 4.334 seconds the spawned worker was alive, the model remained loaded, and the sidecar request lock was free
- worker CPU time remained `00:00:26` across a separate three-second sample, confirming inference had stopped

The next request switched the same sidecar to CUDA and completed successfully. This verifies recovery after cancellation as well as the absence of a bogus completion.

## Focused test

`test_stt_transcription_cancellation.py::test_transformers_load_inherits_disconnect_before_registration` passed with Torch installed: `1 passed in 3.17s`.

## Verdict

Real Transformers Whisper produced nonempty partial text before completion, transcribed the known speech accurately enough to identify the complete sentence, cancelled active work without saving or completing the abandoned stream, and accepted a successful request afterward. No substantive defect was observed in this scope.
