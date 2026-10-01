# Changelog

User-facing changes to SIQE Studio. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/). When you publish a GitHub release, copy its section here into the release notes; they appear in the app's Update Center.

## [Unreleased]

## [0.1.0] - Foundation

The first version of the rebuilt platform. It replaces the original Super Image Quality Enhancer app, and absorbs the ideas from Image-modifier and Image-Modifier-.

### Added

- **Overview:** live health of every service, the GPU (name, video memory, temperature, utilisation), memory and disk, updated every few seconds.
- **System self-test:** sends a job through the whole pipeline and benchmarks your hardware (image engine speed and GPU throughput), with live progress and cancel.
- **Update Center:** the version button in the top bar tells you when a new release is out and shows its release notes and the command to update.
- **Jobs page** with live progress for everything that runs.
- **Command palette** (Ctrl K) for pages, actions and theme.
- Dark and light themes, and a layout that works on a phone.
- Previews of the five workspaces (Studio, AI Lab, Library, Flows, Forge) describing what each phase brings.
- One-command install with Docker Compose, CPU by default, NVIDIA GPU with `make up-gpu`.

### Changed

- The old TensorFlow app, Next.js frontend and notebook have been removed. Your original model returns as "SIQE Classic" in the AI Lab phase. The old code remains in git history.
