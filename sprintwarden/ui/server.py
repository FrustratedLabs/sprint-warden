"""``sprint ui``: a local, read-only portfolio dashboard.

Serves one static page plus a small JSON API over ``http.server``. No network
access, no CDN, no build step. It reads every project in the global registry
straight from its ``.sprint/`` folder on each request, so it is always current.

    GET /api/projects                       portfolio summaries (failing first)
    GET /api/projects/<key>                 sprints, ACs, latest run, baseline, exceptions
    GET /api/projects/<key>/runs?limit=50   run history, newest first
    GET /api/projects/<key>/runs/<run-id>   one run record
    GET /api/board                          every sprints-mode project's sprints, for the board

Binds to 127.0.0.1 and rejects requests whose Host header isn't localhost, so a
web page can't reach it through DNS rebinding.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from sprintwarden import __version__, registry, runs
from sprintwarden import baseline as bl
from sprintwarden.config import find_root, load_config
from sprintwarden.sprintfile import load_sprints
from sprintwarden.util import SprintError

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/icons.js": ("icons.js", "text/javascript; charset=utf-8"),
    "/theme.js": ("theme.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
STATUS_ORDER = {"error": 0, "fail": 1, "stale": 2, "none": 3, "pass": 4}
_RUN_ID = re.compile(r"^\d{8}T\d{6,9}Z-[0-9a-f]{4}$")


# --------------------------------------------------------------------------- data


def _keyed_projects() -> list[tuple[str, Path]]:
    """Registry entries with a unique, URL-safe key each."""
    out: list[tuple[str, Path]] = []
    used: set[str] = set()
    for path in registry.load():
        key = path.name
        try:
            key = load_config(path).key or key
        except SprintError:
            pass
        key = re.sub(r"[^A-Za-z0-9_.-]", "-", key) or "project"
        base, n = key, 2
        while key.lower() in used:
            key = f"{base}-{n}"
            n += 1
        used.add(key.lower())
        out.append((key, path))
    return out


def _summary(key: str, path: Path) -> dict[str, Any]:
    from sprintwarden.commands import project_status

    base: dict[str, Any] = {"key": key, "path": str(path), "name": path.name}
    if not (path / ".sprint" / "config.toml").is_file():
        return base | {"status": "error", "error": "no .sprint/config.toml (moved or deleted?)"}
    try:
        cfg = load_config(path)
        st = project_status(cfg)
    except SprintError as exc:
        return base | {"status": "error", "error": str(exc)}
    latest = st.get("latest") or {}
    sprint = st.get("sprint")
    acs = sprint.get("acs_state", []) if sprint else []
    if not latest:
        status = "none"
    elif latest.get("result") != "pass":
        status = "fail"
    elif st.get("stale"):
        status = "stale"
    else:
        status = "pass"
    counts = {s: 0 for s in ("planned", "active", "closed", "parked")}
    for s in st.get("sprints") or []:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    upcoming = next((s for s in st.get("sprints") or [] if s["status"] == "planned"), None)
    return base | {
        "name": st["project"],
        "project_key": st["key"],
        "stack": st["stack"],
        "mode": st["mode"],
        "status": status,
        "stale": st.get("stale"),
        "sprint": {"id": sprint["id"], "title": sprint["title"], "goal": sprint.get("goal", "")}
        if sprint
        else None,
        "acs": {"satisfied": sum(1 for a in acs if a["state"] == "satisfied"), "total": len(acs)},
        "latest": {
            "id": latest.get("id"),
            "result": latest.get("result"),
            "timestamp": latest.get("timestamp"),
            "agent": latest.get("agent"),
            "trigger": latest.get("trigger"),
            "head": (latest.get("git") or {}).get("head"),
            "totals": latest.get("totals"),
            "counts": latest.get("counts"),
        }
        if latest
        else None,
        "baseline": st.get("baseline"),
        "branch": (st.get("git") or {}).get("branch"),
        "board": counts,
        "next": {"id": upcoming["id"], "title": upcoming["title"]} if upcoming else None,
        "roadmap": [
            {"id": s["id"], "title": s["title"], "status": s["status"]}
            for s in st.get("sprints") or []
        ],
    }


def list_projects() -> list[dict[str, Any]]:
    items = [_summary(k, p) for k, p in _keyed_projects()]
    items.sort(key=lambda s: (STATUS_ORDER.get(s["status"], 9), s.get("name", "").lower()))
    return items


def _find(key: str) -> Path | None:
    return next((p for k, p in _keyed_projects() if k.lower() == key.lower()), None)


def board_sprints(cfg, latest: dict[str, Any]) -> list[dict[str, Any]]:
    """Every sprint with what a board card needs, oldest first.

    ``stats`` are the sprint's test counts in the latest run. A closed sprint is
    ``regressed`` when any of its tests now fail or have gone missing. The first
    planned sprint (lowest number) is ``next``.
    """
    if not cfg.sprints_mode:
        return []
    acs_all = {(a["sprint"], a["id"]): a for a in latest.get("acs_all", [])}
    by_sprint = latest.get("by_sprint") or {}
    failing: dict[str, int] = {}
    for f in latest.get("failing") or []:
        failing[f.get("sprint")] = failing.get(f.get("sprint"), 0) + 1
    missing: dict[str, int] = {}
    for m in latest.get("missing") or []:
        missing[m.get("sprint")] = missing.get(m.get("sprint"), 0) + 1
    out: list[dict[str, Any]] = []
    next_seen = False
    for s in load_sprints(cfg.paths.sprints, strict=False)[0]:
        data = s.to_json()
        data.pop("body", None)
        data["acs"] = [
            a | {"result": acs_all.get((s.id, a["id"]), {"state": "no-tests", "tests": []})}
            for a in data["acs"]
        ]
        states = [a["result"].get("state", "no-tests") for a in data["acs"]]
        data["ac_summary"] = {
            "total": len(states),
            "satisfied": states.count("satisfied"),
            "failing": states.count("failing"),
            "no_tests": states.count("no-tests"),
        }
        stats = by_sprint.get(s.id) or {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
        data["stats"] = stats
        data["failing"] = max(failing.get(s.id, 0), stats.get("failed", 0))
        data["missing"] = missing.get(s.id, 0)
        data["regressed"] = s.status == "closed" and bool(data["failing"] or data["missing"])
        data["next"] = s.status == "planned" and not next_seen
        next_seen = next_seen or data["next"]
        out.append(data)
    return out


def board() -> dict[str, Any]:
    """Sprints of every sprints-mode project, for the all-projects board."""
    projects: list[dict[str, Any]] = []
    other = 0
    for key, path in _keyed_projects():
        try:
            cfg = load_config(path)
        except SprintError:
            other += 1
            continue
        if not cfg.sprints_mode:
            other += 1
            continue
        summary = _summary(key, path)
        latest = runs.load_latest(cfg.paths) or {}
        projects.append(
            {
                "key": key,
                "name": summary.get("name", path.name),
                "project_key": summary.get("project_key"),
                "status": summary["status"],
                "sprints": board_sprints(cfg, latest),
            }
        )
    projects.sort(key=lambda p: p["name"].lower())
    return {"projects": projects, "without_sprints": other, "version": __version__}


def project_detail(key: str) -> dict[str, Any] | None:
    from sprintwarden.commands import project_status

    path = _find(key)
    if path is None:
        return None
    summary = _summary(key, path)
    if summary["status"] == "error":
        return summary
    cfg = load_config(path)
    st = project_status(cfg)
    latest = runs.load_latest(cfg.paths) or {}
    sprints = list(reversed(board_sprints(cfg, latest)))  # newest first
    return summary | {
        "status_detail": st,
        "sprints": sprints,
        "latest_run": latest or None,
        "removals": [a.to_json() for a in bl.load_removals(cfg.paths)],
        "skips": [a.to_json() for a in bl.load_skips(cfg.paths)],
        "allure_url": cfg.allure_url,
        "id_pattern": cfg.id_pattern,
    }


def project_runs(key: str, limit: int = 50) -> list[dict[str, Any]] | None:
    path = _find(key)
    if path is None:
        return None
    try:
        cfg = load_config(path)
    except SprintError:
        return []
    return runs.list_runs(cfg.paths, max(1, min(limit, 1000)))


def project_run(key: str, run_id: str) -> dict[str, Any] | None:
    path = _find(key)
    if path is None or not _RUN_ID.match(run_id):
        return None
    try:
        cfg = load_config(path)
    except SprintError:
        return None
    latest = runs.load_latest(cfg.paths)
    if latest and latest.get("id") == run_id:
        return latest  # the richer version
    return runs.load_run(cfg.paths, run_id)


# --------------------------------------------------------------------------- http


class Handler(BaseHTTPRequestHandler):
    server_version = f"sprintwarden/{__version__}"
    allowed_hosts: set[str] = set()

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
        if getattr(self.server, "verbose", False):
            sys.stderr.write("sprint ui: " + (fmt % args) + "\n")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in self.allowed_hosts

    def _send(self, status: int, body: bytes, ctype: str, *, cache: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.send_header("Cache-Control", "max-age=60" if cache else "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(
            status,
            json.dumps(data, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._host_ok():
            self._error(HTTPStatus.FORBIDDEN, "forbidden host")
            return
        url = urlparse(self.path)
        path = unquote(url.path)
        if path in STATIC:
            name, ctype = STATIC[path]
            body = resources.files("sprintwarden").joinpath("ui", "static", name).read_bytes()
            self._send(200, body, ctype, cache=name != "index.html")
            return
        parts = [p for p in path.split("/") if p]
        if not parts or parts[0] != "api":
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            self._api(parts[1:], parse_qs(url.query))
        except Exception as exc:  # never kill the server thread on one bad project
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def _api(self, parts: list[str], query: dict[str, list[str]]) -> None:
        if parts == ["projects"]:
            self._json({"projects": list_projects(), "version": __version__})
            return
        if parts == ["board"]:
            self._json(board())
            return
        if parts == ["version"]:
            self._json({"version": __version__})
            return
        if len(parts) >= 2 and parts[0] == "projects":
            key = parts[1]
            if len(parts) == 2:
                data = project_detail(key)
            elif len(parts) == 3 and parts[2] == "runs":
                try:
                    limit = int((query.get("limit") or ["50"])[0])
                except ValueError:
                    self._error(HTTPStatus.BAD_REQUEST, "limit must be a number")
                    return
                items = project_runs(key, limit)
                data = None if items is None else {"runs": items}
            elif len(parts) == 4 and parts[2] == "runs":
                data = project_run(key, parts[3])
            else:
                data = None
            if data is None:
                self._error(HTTPStatus.NOT_FOUND, "no such project or run")
            else:
                self._json(data)
            return
        self._error(HTTPStatus.NOT_FOUND, "not found")

    def _read_only(self) -> None:
        self._error(HTTPStatus.METHOD_NOT_ALLOWED, "the dashboard is read-only")

    do_POST = do_PUT = do_DELETE = do_PATCH = _read_only


def make_server(
    host: str = "127.0.0.1", port: int = 7777, *, verbose: bool = False
) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SprintError("the dashboard only binds to localhost (127.0.0.1)")
    server = ThreadingHTTPServer((host, port), Handler)
    real_port = server.server_address[1]
    Handler.allowed_hosts = {f"{h}:{real_port}" for h in ("127.0.0.1", "localhost", "[::1]")}
    server.verbose = verbose  # type: ignore[attr-defined]
    server.daemon_threads = True
    return server


def serve_in_thread(port: int = 0) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = make_server(port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def cmd_ui(env, args):
    from sprintwarden.commands import Outcome

    here = find_root(env.cwd)
    if here is not None and here.resolve() not in registry.load():
        registry.register(here)
    try:
        server = make_server(args.host, args.port)
    except OSError as exc:
        raise SprintError(
            f"can't listen on {args.host}:{args.port} ({exc})", hint="try --port 0"
        ) from exc
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    n = len(registry.load())
    print(
        f"sprintwarden dashboard: {url}  ({n} project{'s' if n != 1 else ''}; Ctrl+C to stop)",
        flush=True,
    )
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return Outcome(0)
