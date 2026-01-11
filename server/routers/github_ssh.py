from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/github-ssh", tags=["github-ssh"])


GITHUB_KNOWN_HOSTS = """github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\ngithub.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=\ngithub.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=\n"""


class GithubSshStatusResponse(BaseModel):
    configured: bool
    fingerprint: str | None = None


class GithubSshKeyRequest(BaseModel):
    private_key: str = Field(..., min_length=32)


class GithubSshTestResponse(BaseModel):
    success: bool
    output: str


def _ssh_dir() -> Path:
    return Path.home() / ".ssh"


def _key_path() -> Path:
    return _ssh_dir() / "id_rsa"


def _known_hosts_path() -> Path:
    return _ssh_dir() / "known_hosts"


def _config_path() -> Path:
    return _ssh_dir() / "config"


def _normalize_key(text: str) -> str:
    key = text.strip()
    if "BEGIN" not in key or "PRIVATE KEY" not in key:
        raise HTTPException(status_code=400, detail="Invalid private key format")
    if "\\r" in key:
        key = key.replace("\\r", "")
    if not key.endswith("\n"):
        key += "\n"
    return key


def _ensure_ssh_files(private_key: str) -> None:
    ssh_dir = _ssh_dir()
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    key_path = _key_path()
    key_path.write_text(_normalize_key(private_key), encoding="utf-8")
    os.chmod(key_path, 0o600)

    known_hosts_path = _known_hosts_path()
    existing = ""
    if known_hosts_path.exists():
        try:
            existing = known_hosts_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""

    lines = []
    seen = set()
    for line in (existing + "\n" + GITHUB_KNOWN_HOSTS).splitlines():
        line = line.strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)

    known_hosts_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(known_hosts_path, 0o644)

    config_path = _config_path()
    config_text = "Host github.com\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/id_rsa\n  IdentitiesOnly yes\n  StrictHostKeyChecking yes\n  UserKnownHostsFile ~/.ssh/known_hosts\n"
    config_path.write_text(config_text, encoding="utf-8")
    os.chmod(config_path, 0o600)


def _fingerprint_from_key(private_key: str) -> str:
    normalized = _normalize_key(private_key)
    sha = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return sha[:12]


def _is_configured() -> bool:
    key_path = _key_path()
    if not key_path.exists():
        return False
    try:
        text = key_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(re.search(r"BEGIN.*PRIVATE KEY", text))


@router.get("/status", response_model=GithubSshStatusResponse)
async def github_ssh_status():
    configured = _is_configured()
    fingerprint = None
    if configured:
        try:
            fingerprint = _fingerprint_from_key(_key_path().read_text(encoding="utf-8"))
        except Exception:
            fingerprint = None
    return GithubSshStatusResponse(configured=configured, fingerprint=fingerprint)


@router.post("/key", response_model=GithubSshStatusResponse)
async def github_ssh_set_key(payload: GithubSshKeyRequest):
    _ensure_ssh_files(payload.private_key)
    return GithubSshStatusResponse(configured=True, fingerprint=_fingerprint_from_key(payload.private_key))


@router.post("/key-file", response_model=GithubSshStatusResponse)
async def github_ssh_set_key_file(file: UploadFile = File(...)):
    data = await file.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Key file must be UTF-8 text")
    _ensure_ssh_files(text)
    return GithubSshStatusResponse(configured=True, fingerprint=_fingerprint_from_key(text))


@router.post("/test", response_model=GithubSshTestResponse)
async def github_ssh_test():
    if not _is_configured():
        raise HTTPException(status_code=400, detail="GitHub SSH key not configured")

    cmd = [
        "ssh",
        "-T",
        "git@github.com",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={_known_hosts_path().as_posix()}",
        "-i",
        _key_path().as_posix(),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")

    # GitHub returns exit code 1 for successful auth but no shell access.
    success = (
        "successfully authenticated" in output.lower()
        or "you've successfully authenticated" in output.lower()
        or proc.returncode == 1
    )

    return GithubSshTestResponse(success=success, output=output.strip())
