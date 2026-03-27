"""FastAPI web reader for browsing autonovel project content."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import markdown
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
READER_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Autonovel Reader")
app.mount(
    "/static", StaticFiles(directory=str(READER_DIR / "static")), name="static"
)
templates = Jinja2Templates(directory=str(READER_DIR / "templates"))

MD_EXTENSIONS = ["tables", "fenced_code", "codehilite", "toc", "nl2br"]


def _safe_resolve(rel_path: str) -> Path:
    """Resolve a relative path within the project root. Raise on traversal."""
    resolved = (PROJECT_ROOT / rel_path).resolve()
    if not str(resolved).startswith(str(PROJECT_ROOT)):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return resolved


def _word_count(text: str) -> int:
    return len(text.split())


def _render_markdown(text: str) -> str:
    return markdown.markdown(text, extensions=MD_EXTENSIONS)


def _render_json(text: str) -> str:
    try:
        obj = json.loads(text)
        return json.dumps(obj, indent=2)
    except json.JSONDecodeError:
        return text


def _build_sidebar() -> dict[str, Any]:
    """Build the sidebar navigation structure."""
    sidebar: dict[str, Any] = {}

    # IDENTITY
    identity_items = []
    identity_files = [
        "identity/self.md",
        "identity/soul.md",
        "identity/pen_name.md",
        "identity/voice_priors.json",
        "identity/inspirations.md",
        "identity/fandom_context.md",
    ]
    for f in identity_files:
        p = PROJECT_ROOT / f
        if p.exists():
            identity_items.append({"name": p.name, "path": f})
    sidebar["IDENTITY"] = identity_items

    # WRITING - briefs
    briefs_items = []
    briefs_dir = PROJECT_ROOT / "briefs"
    if briefs_dir.is_dir():
        for p in sorted(briefs_dir.iterdir()):
            if p.is_file():
                briefs_items.append(
                    {"name": p.name, "path": f"briefs/{p.name}"}
                )

    # WRITING - runs
    runs_items = []
    runs_dir = PROJECT_ROOT / "write" / "runs"
    if runs_dir.is_dir():
        for d in sorted(runs_dir.iterdir()):
            if d.is_dir():
                state_file = d / "state.json"
                run_info: dict[str, Any] = {
                    "name": d.name,
                    "path": f"write/runs/{d.name}",
                }
                if state_file.exists():
                    try:
                        state = json.loads(state_file.read_text())
                        run_info["state"] = state.get("state", "unknown")
                        run_info["words"] = state.get("total_words", 0)
                        run_info["slop"] = state.get("slop_score", None)
                    except (json.JSONDecodeError, OSError):
                        pass
                runs_items.append(run_info)

    sidebar["WRITING"] = {"briefs": briefs_items, "runs": runs_items}

    # SPECS
    specs_items = []
    specs_files = [
        "specs/api-proxy.md",
        "specs/identity.md",
        "specs/write-loop.md",
        "specs/soul-and-muse.md",
    ]
    for f in specs_files:
        p = PROJECT_ROOT / f
        if p.exists():
            specs_items.append({"name": p.name, "path": f})
    sidebar["SPECS"] = specs_items

    # DOCS
    docs_items = []
    docs_files = [
        "README.md",
        "PLAN.md",
        "methodology.md",
        "CRAFT.md",
        "ANTI-SLOP.md",
        "ANTI-PATTERNS.md",
        "PIPELINE.md",
        "WORKFLOW.md",
    ]
    for f in docs_files:
        p = PROJECT_ROOT / f
        if p.exists():
            docs_items.append({"name": p.name, "path": f})
    sidebar["DOCS"] = docs_items

    # CONFIG
    config_items = []
    config_files = [
        "write/config.json",
        ".env.example",
        "pyproject.toml",
    ]
    for f in config_files:
        p = PROJECT_ROOT / f
        if p.exists():
            config_items.append({"name": p.name, "path": f})
    sidebar["CONFIG"] = config_items

    return sidebar


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    sidebar = _build_sidebar()
    return templates.TemplateResponse(
        request, "index.html.j2", {"sidebar": sidebar}
    )


@app.get("/file/{path:path}")
async def get_file(path: str) -> dict[str, Any]:
    """Return file content rendered for display."""
    resolved = _safe_resolve(path)

    # Handle directory (e.g., a run directory)
    if resolved.is_dir():
        return _render_directory(path, resolved)

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    raw = resolved.read_text(errors="replace")
    suffix = resolved.suffix.lower()

    result: dict[str, Any] = {
        "path": path,
        "filename": resolved.name,
        "type": suffix,
    }

    if suffix == ".md":
        result["html"] = _render_markdown(raw)
        result["words"] = _word_count(raw)
    elif suffix == ".json":
        result["formatted"] = _render_json(raw)
    elif suffix in {
        ".txt",
        ".py",
        ".toml",
        ".cfg",
        ".ini",
        ".yaml",
        ".yml",
        ".tsv",
    }:
        result["text"] = raw
        result["words"] = _word_count(raw)
    else:
        result["text"] = raw

    return result


def _render_directory(path: str, resolved: Path) -> dict[str, Any]:
    """Render a directory listing, with special handling for run directories."""
    result: dict[str, Any] = {
        "path": path,
        "filename": resolved.name,
        "type": "directory",
    }

    # Check for state.json (run directory)
    state_file = resolved / "state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            result["state"] = state
        except (json.JSONDecodeError, OSError):
            pass

    # List files in directory
    files = []
    for f in sorted(resolved.iterdir()):
        if f.is_file():
            files.append(
                {
                    "name": f.name,
                    "path": f"{path}/{f.name}",
                    "size": f.stat().st_size,
                }
            )
    result["files"] = files

    # If there's a draft file, include its rendered content
    for f in sorted(resolved.iterdir()):
        if f.is_file() and f.suffix == ".md" and "draft" in f.name.lower():
            raw = f.read_text(errors="replace")
            result["draft_html"] = _render_markdown(raw)
            result["draft_words"] = _word_count(raw)
            result["draft_file"] = f.name
            break

    return result


@app.get("/beads")
async def get_beads() -> dict[str, Any]:
    """Run br list and return formatted output."""
    try:
        proc = subprocess.run(
            ["br", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        return {
            "output": proc.stdout,
            "error": proc.stderr if proc.returncode != 0 else None,
        }
    except FileNotFoundError:
        return {"output": "", "error": "br command not found"}
    except subprocess.TimeoutExpired:
        return {"output": "", "error": "br list timed out"}


@app.get("/runs")
async def get_runs() -> list[dict[str, Any]]:
    """List write/runs/ with state summaries."""
    runs_dir = PROJECT_ROOT / "write" / "runs"
    if not runs_dir.is_dir():
        return []

    runs = []
    for d in sorted(runs_dir.iterdir()):
        if not d.is_dir():
            continue
        run_info: dict[str, Any] = {
            "id": d.name,
            "path": f"write/runs/{d.name}",
        }
        state_file = d / "state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                run_info["state"] = state.get("state", "unknown")
                run_info["total_words"] = state.get("total_words", 0)
                run_info["slop_score"] = state.get("slop_score", None)
            except (json.JSONDecodeError, OSError):
                run_info["state"] = "error"
        else:
            run_info["state"] = "no state"
        runs.append(run_info)

    return runs
