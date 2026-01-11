"""
Projects Router
===============

API endpoints for project management.
Uses project registry for path lookups instead of fixed generations/ directory.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..validators import validate_project_name
from ..schemas import (
    ProjectCreate,
    ProjectDetail,
    ProjectImport,
    ProjectPrompts,
    ProjectPromptsUpdate,
    ProjectStats,
    ProjectSummary,
)

# Lazy imports to avoid circular dependencies
_imports_initialized = False
_check_spec_exists = None
_scaffold_project_prompts = None
_migrate_project_prompts = None
_set_analyzer_mode = None
_get_project_prompts_dir = None
_count_passing_tests = None
_ensure_database_exists = None


def _init_imports():
    """Lazy import of project-level modules."""
    global _imports_initialized, _check_spec_exists
    global _scaffold_project_prompts, _migrate_project_prompts, _set_analyzer_mode
    global _get_project_prompts_dir, _count_passing_tests, _ensure_database_exists

    if _imports_initialized:
        return

    import sys
    root = Path(__file__).parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from api.database import ensure_database_exists
    from progress import count_passing_tests
    from prompts import get_project_prompts_dir, migrate_project_prompts, scaffold_project_prompts, set_analyzer_mode
    from start import check_spec_exists

    _check_spec_exists = check_spec_exists
    _scaffold_project_prompts = scaffold_project_prompts
    _migrate_project_prompts = migrate_project_prompts
    _set_analyzer_mode = set_analyzer_mode
    _get_project_prompts_dir = get_project_prompts_dir
    _count_passing_tests = count_passing_tests
    _ensure_database_exists = ensure_database_exists
    _imports_initialized = True


def _get_registry_functions():
    """Get registry functions with lazy import."""
    import sys
    root = Path(__file__).parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from registry import (
        get_project_path,
        list_registered_projects,
        register_project,
        unregister_project,
        validate_project_path,
    )
    return register_project, unregister_project, get_project_path, list_registered_projects, validate_project_path


# Source code detection constants
_SOURCE_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.go', '.rs', '.rb', '.php', '.vue', '.svelte', '.c', '.cpp', '.h', '.cs'}
_SKIP_DIRS = {'node_modules', '.git', 'venv', '__pycache__', 'dist', 'build', '.next', 'target', '.venv', 'vendor', 'bower_components'}


def _has_source_code(project_path: Path, max_depth: int = 3) -> bool:
    """
    Check if directory contains source code files.

    Uses bounded depth-limited search to prevent timeouts on large repositories.
    Skips common dependency/build directories for efficiency.

    Args:
        project_path: Root directory to search
        max_depth: Maximum directory depth to traverse (default: 3)

    Returns:
        True if source code files are found, False otherwise
    """
    def check_dir(path: Path, depth: int) -> bool:
        if depth > max_depth:
            return False
        try:
            for item in path.iterdir():
                if item.is_file() and item.suffix.lower() in _SOURCE_EXTENSIONS:
                    return True
                if item.is_dir() and item.name not in _SKIP_DIRS:
                    if check_dir(item, depth + 1):
                        return True
        except PermissionError:
            pass
        return False

    return check_dir(project_path, 0)


router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCloneRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    repo_url: str = Field(..., min_length=1)


def _normalize_github_repo_url(repo_url: str) -> str:
    """Normalize a GitHub repo URL to an SSH clone URL."""
    url = repo_url.strip()

    # Already SSH
    if url.startswith("git@github.com:"):
        m = re.match(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
        if not m:
            raise ValueError("Invalid GitHub SSH URL")
        owner, repo = m.group(1), m.group(2)
        return f"git@github.com:{owner}/{repo}.git"

    # HTTPS
    m = re.match(r"^https?://(www\.)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if m:
        owner, repo = m.group(2), m.group(3)
        return f"git@github.com:{owner}/{repo}.git"

    raise ValueError("Only GitHub HTTPS or SSH URLs are supported")


def _get_clone_root() -> Path:
    value = os.getenv("AUTOCODER_FILESYSTEM_ROOT") or os.getenv("AUTOCODER_GENERATIONS_DIR")
    if value:
        try:
            return Path(value).resolve()
        except (OSError, ValueError):
            pass
    return (Path(__file__).parent.parent.parent / "generations").resolve()


def get_project_stats(project_dir: Path) -> ProjectStats:
    """Get statistics for a project."""
    _init_imports()
    passing, in_progress, total = _count_passing_tests(project_dir)
    percentage = (passing / total * 100) if total > 0 else 0.0
    return ProjectStats(
        passing=passing,
        in_progress=in_progress,
        total=total,
        percentage=round(percentage, 1)
    )


@router.get("", response_model=list[ProjectSummary])
async def list_projects():
    """List all registered projects."""
    _init_imports()
    _, _, _, list_registered_projects, validate_project_path = _get_registry_functions()

    projects = list_registered_projects()
    result = []

    for name, info in projects.items():
        project_dir = Path(info["path"])

        # Skip if path no longer exists
        is_valid, _ = validate_project_path(project_dir)
        if not is_valid:
            continue

        has_spec = _check_spec_exists(project_dir)
        stats = get_project_stats(project_dir)

        result.append(ProjectSummary(
            name=name,
            path=info["path"],
            has_spec=has_spec,
            stats=stats,
        ))

    return result


@router.post("", response_model=ProjectSummary)
async def create_project(project: ProjectCreate):
    """Create a new project at the specified path."""
    _init_imports()
    register_project, _, get_project_path, _, _ = _get_registry_functions()

    name = validate_project_name(project.name)
    project_path = Path(project.path).resolve()

    # Check if project name already registered
    existing = get_project_path(name)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Project '{name}' already exists at {existing}"
        )

    # Security: Check if path is in a blocked location
    from .filesystem import is_path_blocked
    if is_path_blocked(project_path):
        raise HTTPException(
            status_code=403,
            detail="Cannot create project in system or sensitive directory"
        )

    # Validate the path is usable
    if project_path.exists():
        if not project_path.is_dir():
            raise HTTPException(
                status_code=400,
                detail="Path exists but is not a directory"
            )
    else:
        # Create the directory
        try:
            project_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create directory: {e}"
            )

    # Scaffold prompts
    _scaffold_project_prompts(project_path)

    # Register in registry
    try:
        register_project(name, project_path)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to register project: {e}"
        )

    return ProjectSummary(
        name=name,
        path=project_path.as_posix(),
        has_spec=False,  # Just created, no spec yet
        stats=ProjectStats(passing=0, total=0, percentage=0.0),
    )


@router.post("/import", response_model=ProjectSummary)
async def import_project(project: ProjectImport):
    """
    Import an existing project into the system.

    This registers an existing codebase and sets it up for analysis.
    The analyzer agent will explore the codebase and create features
    for ongoing management.
    """
    _init_imports()
    register_project, _, get_project_path, _, _ = _get_registry_functions()

    name = validate_project_name(project.name)
    project_path = Path(project.path).resolve()

    # Check if project name already registered
    existing = get_project_path(name)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Project '{name}' already exists at {existing}"
        )

    # Security: Check if path is in a blocked location
    from .filesystem import is_path_blocked
    if is_path_blocked(project_path):
        raise HTTPException(
            status_code=403,
            detail="Cannot import project from system or sensitive directory"
        )

    # Validate the path exists and is a directory
    if not project_path.exists():
        raise HTTPException(
            status_code=400,
            detail="Path does not exist"
        )

    if not project_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Path is not a directory"
        )

    # Check if the directory has some source code (bounded search to prevent timeouts)
    if not _has_source_code(project_path):
        raise HTTPException(
            status_code=400,
            detail="Directory does not appear to contain source code files"
        )

    # Check for existing Claude settings that could conflict with autocoder
    claude_settings = project_path / ".claude" / "settings.local.json"
    if claude_settings.exists():
        raise HTTPException(
            status_code=400,
            detail="Project contains existing Claude settings (.claude/settings.local.json). "
                   "Please backup and remove this file before importing to avoid permission conflicts."
        )

    # Set up prompts for imported project (analyzer mode)
    _migrate_project_prompts(project_path)

    # Enable analyzer mode for this project
    _set_analyzer_mode(project_path, enabled=True)

    # Ensure database exists (empty, will be populated by analyzer)
    _ensure_database_exists(project_path)

    # Register in registry
    try:
        register_project(name, project_path)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to register project: {e}"
        )

    # Check if project already has a spec (from previous work)
    has_spec = _check_spec_exists(project_path)
    stats = get_project_stats(project_path)

    return ProjectSummary(
        name=name,
        path=project_path.as_posix(),
        has_spec=has_spec,
        stats=stats,
    )


@router.post("/clone", response_model=ProjectSummary)
async def clone_project(payload: ProjectCloneRequest):
    """Clone a GitHub repository over SSH into the configured generations directory and register it."""
    _init_imports()
    register_project, _, get_project_path, _, _ = _get_registry_functions()

    name = validate_project_name(payload.name)
    try:
        repo_url = _normalize_github_repo_url(payload.repo_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = get_project_path(name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Project '{name}' already exists at {existing}")

    dest_root = _get_clone_root()
    dest_root.mkdir(parents=True, exist_ok=True)
    dest_path = (dest_root / name).resolve()

    from .filesystem import is_path_blocked
    if is_path_blocked(dest_path):
        raise HTTPException(status_code=403, detail="Cannot clone into system or sensitive directory")

    try:
        dest_path.relative_to(dest_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Clone destination is not allowed")

    if dest_path.exists():
        raise HTTPException(status_code=409, detail=f"Destination already exists: {dest_path}")

    env = os.environ.copy()
    ssh_dir = Path.home() / ".ssh"
    ssh_key = ssh_dir / "id_rsa"
    known_hosts = ssh_dir / "known_hosts"
    if ssh_key.exists():
        env["GIT_SSH_COMMAND"] = (
            "ssh -i \"{}\" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=\"{}\""
        ).format(ssh_key.as_posix(), known_hosts.as_posix())

    proc = subprocess.run(
        ["git", "clone", repo_url, dest_path.as_posix()],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        output = (proc.stdout or "") + (proc.stderr or "")
        raise HTTPException(status_code=400, detail=f"git clone failed: {output.strip()}")

    _migrate_project_prompts(dest_path)
    _set_analyzer_mode(dest_path, enabled=True)
    _ensure_database_exists(dest_path)

    try:
        register_project(name, dest_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register project: {e}")

    has_spec = _check_spec_exists(dest_path)
    stats = get_project_stats(dest_path)
    return ProjectSummary(
        name=name,
        path=dest_path.as_posix(),
        has_spec=has_spec,
        stats=stats,
    )


@router.get("/{name}", response_model=ProjectDetail)
async def get_project(name: str):
    """Get detailed information about a project."""
    _init_imports()
    _, _, get_project_path, _, _ = _get_registry_functions()

    name = validate_project_name(name)
    project_dir = get_project_path(name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found in registry")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project directory no longer exists: {project_dir}")

    has_spec = _check_spec_exists(project_dir)
    stats = get_project_stats(project_dir)
    prompts_dir = _get_project_prompts_dir(project_dir)

    return ProjectDetail(
        name=name,
        path=project_dir.as_posix(),
        has_spec=has_spec,
        stats=stats,
        prompts_dir=str(prompts_dir),
    )


@router.delete("/{name}")
async def delete_project(name: str, delete_files: bool = False):
    """
    Delete a project from the registry.

    Args:
        name: Project name to delete
        delete_files: If True, also delete the project directory and files
    """
    _init_imports()
    _, unregister_project, get_project_path, _, _ = _get_registry_functions()

    name = validate_project_name(name)
    project_dir = get_project_path(name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    # Check if agent is running
    lock_file = project_dir / ".agent.lock"
    if lock_file.exists():
        raise HTTPException(
            status_code=409,
            detail="Cannot delete project while agent is running. Stop the agent first."
        )

    # Optionally delete files
    if delete_files and project_dir.exists():
        try:
            shutil.rmtree(project_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete project files: {e}")

    # Unregister from registry
    unregister_project(name)

    return {
        "success": True,
        "message": f"Project '{name}' deleted" + (" (files removed)" if delete_files else " (files preserved)")
    }


@router.get("/{name}/prompts", response_model=ProjectPrompts)
async def get_project_prompts(name: str):
    """Get the content of project prompt files."""
    _init_imports()
    _, _, get_project_path, _, _ = _get_registry_functions()

    name = validate_project_name(name)
    project_dir = get_project_path(name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    prompts_dir = _get_project_prompts_dir(project_dir)

    def read_file(filename: str) -> str:
        filepath = prompts_dir / filename
        if filepath.exists():
            try:
                return filepath.read_text(encoding="utf-8")
            except Exception:
                return ""
        return ""

    return ProjectPrompts(
        app_spec=read_file("app_spec.txt"),
        initializer_prompt=read_file("initializer_prompt.md"),
        coding_prompt=read_file("coding_prompt.md"),
    )


@router.put("/{name}/prompts")
async def update_project_prompts(name: str, prompts: ProjectPromptsUpdate):
    """Update project prompt files."""
    _init_imports()
    _, _, get_project_path, _, _ = _get_registry_functions()

    name = validate_project_name(name)
    project_dir = get_project_path(name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    prompts_dir = _get_project_prompts_dir(project_dir)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    def write_file(filename: str, content: str | None):
        if content is not None:
            filepath = prompts_dir / filename
            filepath.write_text(content, encoding="utf-8")

    write_file("app_spec.txt", prompts.app_spec)
    write_file("initializer_prompt.md", prompts.initializer_prompt)
    write_file("coding_prompt.md", prompts.coding_prompt)

    return {"success": True, "message": "Prompts updated"}


@router.get("/{name}/stats", response_model=ProjectStats)
async def get_project_stats_endpoint(name: str):
    """Get current progress statistics for a project."""
    _init_imports()
    _, _, get_project_path, _, _ = _get_registry_functions()

    name = validate_project_name(name)
    project_dir = get_project_path(name)

    if not project_dir:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    return get_project_stats(project_dir)
