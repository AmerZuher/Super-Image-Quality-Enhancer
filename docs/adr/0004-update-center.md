# 0004. In-app Update Center fed by GitHub releases

- **Status:** Accepted, 1 October 2026
- **Raised by:** the owner ("I will create releases, so add the update button to let users see the new patches with release notes")

## Context

Users run SIQE Studio on their own machines, so they only learn about fixes and features if the app tells them. The owner publishes releases on GitHub and writes the notes there.

## Decision

- The backend reads `GET /repos/{SIQE_UPDATE_REPO}/releases` at most every 6 hours, with ETags, and caches the parsed list in `app_settings`. Drafts and non-semver tags are ignored; pre-releases are hidden unless `SIQE_UPDATE_INCLUDE_PRERELEASES=true`.
- `GET /api/updates` returns the running version, newer releases with their Markdown notes, the running version's own notes, and any check error. `?refresh=true` forces a check.
- The top bar shows the version; it becomes "vX.Y.Z available" when there is a newer release. It opens a drawer with the notes (Markdown with raw HTML disabled) and the update commands.
- Publishing a release triggers `.github/workflows/release.yml`, which pushes `api`, `ai` and `web` images to GHCR tagged `X.Y.Z`, `X.Y` and `latest` (not for pre-releases).

## Alternatives considered

- **One-click self-update:** needs the Docker socket inside a container, which is root-equivalent access to the host. Rejected for now; could return as an opt-in sidecar.
- **Polling from the browser directly to GitHub:** leaks usage to GitHub from every client and multiplies rate-limit use. The server-side cache avoids both.

## Consequences

- Release notes are user-facing; write them for users, not as commit logs.
- The app keeps working offline and shows the last known releases with a short explanation.
- First-time installs build from source (`make up`) until a release has published images.
