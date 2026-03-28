"""FastAPI web reader for browsing autonovel project content."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import markdown
import yaml
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
        request, "index.html.j2", {"sidebar": sidebar, "show_home": True}
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


# ---------------------------------------------------------------------------
# Experiment timeline helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Extract YAML frontmatter from a markdown file."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def _run_cmd(args: list[str], *, timeout: int = 10) -> str:
    """Run a command and return stdout, or empty string on failure."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        return proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _parse_bead_line(line: str) -> dict[str, Any] | None:
    """Parse a single line from ``br list --all`` output.

    Lines look like:
        ``<status> <id> [<priority>] [<type>] - <title>``
    where status is one of: ``*`` (open), ``>`` (in_progress), ``v`` (closed).
    The Unicode symbols are: open circle, half circle, check mark.
    """
    line = line.strip()
    if not line:
        return None

    # Determine status from leading symbol
    status = "open"
    if (
        line.startswith("\u2713")
        or line.startswith("\u2714")
        or line.startswith("v")
    ):
        status = "closed"
    elif (
        line.startswith("\u25d0")
        or line.startswith("\u25d1")
        or line.startswith(">")
    ):
        status = "in_progress"

    # Extract bead ID (bd-XXX pattern)
    id_match = re.search(r"(bd-\w+)", line)
    if not id_match:
        return None
    bead_id = id_match.group(1)

    # Extract title (everything after the dash separator)
    title_match = re.search(r"\]\s*-\s*(.+)$", line)
    title = title_match.group(1).strip() if title_match else bead_id

    return {"id": bead_id, "status": status, "title": title}


def _get_bead_description(bead_id: str) -> str:
    """Get the first few lines of a bead's description via ``br show``."""
    output = _run_cmd(["br", "show", bead_id])
    if not output:
        return ""
    # Skip the header line(s) and collect description text
    lines = output.strip().split("\n")
    desc_lines = []
    past_header = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            past_header = True
            continue
        if past_header and not stripped.startswith(
            ("Owner:", "Created:", "Closed:")
        ):
            desc_lines.append(stripped)
    return "\n".join(desc_lines[:6])


def _find_run_for_bead(bead_id: str) -> dict[str, Any] | None:
    """Find a write run whose draft.md frontmatter references this bead."""
    runs_dir = PROJECT_ROOT / "write" / "runs"
    if not runs_dir.is_dir():
        return None
    for d in sorted(runs_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        draft = d / "draft.md"
        if not draft.is_file():
            continue
        try:
            raw = draft.read_text(errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(raw)
        if fm.get("experiment") == bead_id:
            return {
                "run_name": d.name,
                "draft_path": f"write/runs/{d.name}/draft.md",
                "brief_path": fm.get("brief", ""),
                "title": fm.get("title", ""),
                "words": fm.get("words", 0),
                "slop_score": fm.get("slop_score"),
                "created": str(fm.get("created", "")),
            }
    return None


def _get_bead_commits(bead_id: str) -> list[dict[str, Any]]:
    """Find git commits referencing this bead ID."""
    output = _run_cmd(
        [
            "git",
            "log",
            "--oneline",
            "--format=%h|%ai|%s",
            f"--grep=Bead: {bead_id}",
        ],
        timeout=15,
    )
    commits = []
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        sha, date, subject = parts
        # Get files changed in this commit
        files_output = _run_cmd(
            [
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                sha.strip(),
            ]
        )
        changed = [
            f.strip() for f in files_output.strip().split("\n") if f.strip()
        ]
        commits.append(
            {
                "sha": sha.strip(),
                "date": date.strip()[:10],
                "subject": subject.strip(),
                "files": changed,
            }
        )
    return commits


def _get_recent_commits(count: int = 20) -> list[dict[str, Any]]:
    """Get the most recent git commits with changed files."""
    output = _run_cmd(
        ["git", "log", f"-{count}", "--format=%h|%ai|%s"],
        timeout=15,
    )
    commits = []
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        sha, date, subject = parts
        files_output = _run_cmd(
            [
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                sha.strip(),
            ]
        )
        changed = [
            f.strip() for f in files_output.strip().split("\n") if f.strip()
        ]
        commits.append(
            {
                "sha": sha.strip(),
                "date": date.strip()[:10],
                "subject": subject.strip(),
                "files": changed,
            }
        )
    return commits


def _build_experiments() -> list[dict[str, Any]]:
    """Build experiment timeline data from beads and runs."""
    bead_output = _run_cmd(["br", "list", "--all"])
    if not bead_output:
        return []

    experiments = []
    for line in bead_output.strip().split("\n"):
        parsed = _parse_bead_line(line)
        if not parsed:
            continue
        title_lower = parsed["title"].lower()
        # Filter to experiment/calibration beads only
        is_experiment = any(
            title_lower.startswith(prefix)
            for prefix in ("experiment:", "calibration:")
        )
        if not is_experiment:
            continue

        entry: dict[str, Any] = {
            "bead_id": parsed["id"],
            "status": parsed["status"],
            "title": parsed["title"],
        }

        # Get bead description snippet
        entry["description"] = _get_bead_description(parsed["id"])

        # Find matching run
        run = _find_run_for_bead(parsed["id"])
        if run:
            entry["run"] = run

        # Find related commits
        entry["commits"] = _get_bead_commits(parsed["id"])

        # Identify identity file changes from commits
        identity_files: list[str] = []
        for commit in entry["commits"]:
            for f in commit.get("files", []):
                if f.startswith("identity/") and f not in identity_files:
                    identity_files.append(f)
        entry["identity_changes"] = identity_files

        experiments.append(entry)

    return experiments


@app.get("/api/experiments")
async def api_experiments() -> dict[str, Any]:
    """Return experiment timeline and recent commits as JSON."""
    experiments = _build_experiments()
    recent = _get_recent_commits(20)
    return {"experiments": experiments, "recent_commits": recent}


@app.get("/home", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Experiment timeline homepage."""
    sidebar = _build_sidebar()
    return templates.TemplateResponse(
        request, "index.html.j2", {"sidebar": sidebar, "show_home": True}
    )
