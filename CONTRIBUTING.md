# Contributing to SPICA

Thanks for your interest in contributing!

## Development Setup

```sh
git clone https://github.com/YOUR_USERNAME/spica.git
cd spica

# Python environment + dependencies (uses Tsinghua mirror by default)
make deps

# Download speech models (~480MB, from hf-mirror)
make models

# Bundle DSH runtime (~883MB)
make deps-dsh

# Build web frontend
cd web && npm install && npm run build && cd ..

# Run tests
make test

# Start server
make up  # → http://127.0.0.1:8666
```

## Project Structure

```
server/          Python FastAPI backend
  voice/         Speech pipeline (VAD, wake word, ASR, speaker verification)
  agent/         DSH SDK bridge, prompt rewriting, routing, session management
  evolution/     Self-evolution (memory, skill harvesting)
  media/         MusicFree integration, taste learning
  tts/           Qwen3-TTS engine, narration, voice packs
  sessions/      Session persistence
  ws/            WebSocket protocol, REST API
web/             React + TypeScript frontend (Vite)
runtime/         Bundled dependencies (DSH, MusicFree)
models/          Downloaded speech/TTS models (gitignored)
tests/           104+ unit tests
```

## Guidelines

- **Visual design**: Follow `docs/design/effect-layer-spec.md` (hard constraints)
- **Tests**: All changes must pass `make test` (104+ tests)
- **Commits**: Use conventional commits (`feat:`, `fix:`, `docs:`, etc.)
- **Security**: Never commit API keys, credentials, or large binary files
- **Philosophy**: Less is more. Every UI element must earn its place.

## Reporting Issues

Please include:
- OS and Python/Node versions (`make check` output)
- Server log excerpt (`make log`)
- Steps to reproduce
