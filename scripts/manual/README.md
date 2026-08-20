# Manual Hardware And Model Checks

These scripts are intentionally outside `tests/` because they require local models, audio hardware, or a running Ollama instance. They are not part of the deterministic pytest suite.

Run from the repository root:

```bash
python scripts/manual/audio_smoke_test.py
python scripts/manual/function_gemma_smoke_test.py
python scripts/manual/voice_pipeline_smoke_test.py
python scripts/manual/ollama_benchmark.py
```
