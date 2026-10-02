"""Talking to a running SIQE Studio over HTTP, for the ``siqe flows``, ``upload`` and ``run`` commands.

These work from any computer that can reach the app: set ``SIQE_URL`` (default
``http://localhost:8080``) and, when the app asks for keys, ``SIQE_API_KEY``.
"""

import json
import time
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:8080"
FINAL = ("succeeded", "failed", "cancelled")


class ClientError(Exception):
    """A failure to show the user: what went wrong and, when known, how to fix it."""

    def __init__(self, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.fix = fix


@dataclass
class RunResult:
    run: dict[str, Any]
    items: list[dict[str, Any]]


def image_files(paths: Iterable[Path]) -> list[Path]:
    """Files to upload: each image named, and the images inside each folder named (recursively)."""
    from siqe.imaging.formats import INPUT_EXTENSIONS

    extensions = frozenset(INPUT_EXTENSIONS.split())
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(
                p
                for p in sorted(path.rglob("*"))
                if p.is_file() and p.suffix.lower() in extensions and not p.name.startswith(".")
            )
        elif path.is_file():
            found.append(path)
        else:
            raise ClientError(f"{path} doesn't exist.")
    return list(dict.fromkeys(found))


class Client:
    def __init__(
        self,
        url: str = DEFAULT_URL,
        key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.http = httpx.Client(
            base_url=url.rstrip("/") + "/api", headers=headers, timeout=60.0, transport=transport
        )
        self.url = url
        self.sleep = sleep

    def close(self) -> None:
        self.http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ClientError(
                f"Couldn't reach SIQE Studio at {self.url} ({exc.__class__.__name__}).",
                "Check the app is running and SIQE_URL points at it.",
            ) from exc
        if response.status_code >= 400:
            try:
                problem = response.json()
            except ValueError:
                problem = {}
            detail = problem.get("detail") or f"The server answered {response.status_code}."
            fix = problem.get("fix")
            if response.status_code == 401 and not self.http.headers.get("Authorization"):
                fix = "Set SIQE_API_KEY to a key from Settings (or `siqe keys create`)."
            raise ClientError(detail, fix)
        return response

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params or None).json()

    def post(self, path: str, body: Any) -> Any:
        return self._request("POST", path, json=body).json()

    # ------------------------------------------------------------------ flows

    def flows(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self.get("/flows")
        return result

    def resolve_flow(self, ref: str) -> dict[str, Any]:
        """A flow by id, by name (case-insensitive), or from a ``.flow.json`` file."""
        path = Path(ref)
        if ref.endswith(".json") and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ClientError(f"{path} isn't a readable flow file: {exc}") from exc
            for flow in self.flows():
                if flow["name"] == data.get("name") and flow["document"] == data.get("document"):
                    return flow
            imported: dict[str, Any] = self.post("/flows/import", data)
            return imported
        flows = self.flows()
        for flow in flows:
            if flow["id"] == ref:
                return flow
        named = [f for f in flows if f["name"].casefold() == ref.casefold()]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            raise ClientError(f"More than one flow is called '{ref}'.", "Use the flow's id instead.")
        raise ClientError(f"No flow called '{ref}'.", "See your flows with `siqe flows list`.")

    def resolve_album(self, ref: str) -> str:
        """An album's id, from its id or its name (case-insensitive)."""
        albums: list[dict[str, Any]] = self.get("/library/albums")
        for album in albums:
            if album["id"] == ref:
                return ref
        named = [a["id"] for a in albums if a["name"].casefold() == ref.casefold()]
        if len(named) == 1:
            return str(named[0])
        raise ClientError(
            f"No album called '{ref}'." if not named else f"More than one album is called '{ref}'.",
            "Use the album's id, or check its name in the Library.",
        )

    # ----------------------------------------------------------------- upload

    def upload(
        self, files: list[Path], progress: Callable[[Path, dict[str, Any]], None] | None = None
    ) -> list[str]:
        ids: list[str] = []
        for path in files:
            with path.open("rb") as fh:
                response = self._request(
                    "POST",
                    "/assets",
                    params={"filename": path.name},
                    content=fh,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=None,
                )
            body = response.json()
            ids.append(body["asset"]["id"])
            if progress:
                progress(path, body)
        return ids

    def wait_ready(self, ids: list[str], timeout: float = 1800) -> tuple[list[str], list[str]]:
        """Wait until uploaded images are ready to use. Returns (ready, failed) ids."""
        pending, ready, failed = list(ids), [], []
        deadline = time.monotonic() + timeout
        while pending:
            still: list[str] = []
            for asset_id in pending:
                status = self.get(f"/assets/{asset_id}")["status"]
                if status == "ready":
                    ready.append(asset_id)
                elif status == "failed":
                    failed.append(asset_id)
                else:
                    still.append(asset_id)
            pending = still
            if pending:
                if time.monotonic() > deadline:
                    raise ClientError(
                        "Uploaded images are still being prepared.", "Try the run again shortly."
                    )
                self.sleep(1.0)
        return ready, failed

    # -------------------------------------------------------------------- run

    def start_run(
        self, flow_id: str, source: dict[str, Any], *, dry_run: bool = False, limit: int | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"source": source, "dry_run": dry_run}
        if limit:
            body["limit"] = limit
        run: dict[str, Any] = self.post(f"/flows/{flow_id}/runs", body)
        return run

    def follow(self, run_id: str, every: float = 2.0) -> Iterator[RunResult]:
        """Yield the run as it progresses, ending once it has finished."""
        while True:
            detail = self.get(f"/flows/runs/{run_id}", limit=500)
            result = RunResult(run=detail["run"], items=detail["items"])
            yield result
            if result.run["state"] in FINAL:
                return
            self.sleep(every)

    def download(self, run_id: str, folder: Path) -> list[Path]:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f".siqe-run-{run_id}.zip"
        try:
            with self.http.stream("GET", f"/flows/runs/{run_id}/download", timeout=None) as response:
                if response.status_code >= 400:
                    response.read()
                    try:
                        problem = response.json()
                    except ValueError:
                        problem = {}
                    raise ClientError(problem.get("detail") or "The download failed.", problem.get("fix"))
                with target.open("wb") as fh:
                    for chunk in response.iter_bytes():
                        fh.write(chunk)
            with zipfile.ZipFile(target) as zf:
                root = folder.resolve()
                names = []
                for member in zf.namelist():
                    destination = (folder / member).resolve()
                    if root not in destination.parents:
                        continue  # never write outside the chosen folder
                    zf.extract(member, folder)
                    names.append(destination)
            return names
        finally:
            target.unlink(missing_ok=True)
