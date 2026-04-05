"""
Vision analysis modules - pluggable backends for image understanding.

Each module implements VisionModule protocol and can work in
degraded mode when image quality is poor.

Modules:
    motion  - Movement detection (frame differencing)
    scene   - Scene description (LLaVA via Ollama)
"""
