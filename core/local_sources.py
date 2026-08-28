"""Confine operator-selected local source paths.

Production API creation is Git-only unless an operator sets a source root.
Scan and archive re-validate immediately before use so a symlink/TOCTOU
swap after request time cannot widen the tree.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from django.conf import settings

DENIED_PREFIXES = ("/", "/etc", "/etc/deploy-hub")
DENIED_NAMES = {
    "vault.key",
    ".git",
    ".svn",
    ".hg",
    ".bzr",
    "node_modules",
    "data",
    "dist",
    "coverage",
}
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 20_000


class LocalSourceError(ValueError):
    """A local path is not an allowed source tree."""


def local_sources_allowed():
    return bool(getattr(settings, "HUB_ALLOW_LOCAL_SOURCES", False))


def configured_source_root():
    raw = str(getattr(settings, "HUB_LOCAL_SOURCE_ROOT", "") or "").strip()
    if not raw:
        return None
    return Path(raw)


def _is_env_name(name):
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def _denied_name(name):
    return name in DENIED_NAMES or _is_env_name(name)


def resolve_local_source(path, *, require_root=True, must_exist=True):
    """Return a real directory under the configured root, or raise."""
    if path in (None, ""):
        raise LocalSourceError("local source path is required")
    raw = str(path).strip()
    if raw in DENIED_PREFIXES or raw.rstrip("/") in DENIED_PREFIXES:
        raise LocalSourceError("local source path is not allowed")
    try:
        candidate = Path(raw).resolve(strict=must_exist)
    except OSError as exc:
        raise LocalSourceError("local source path does not exist") from exc
    if must_exist:
        if not candidate.is_dir():
            raise LocalSourceError("local source path must be a directory")
        mode = candidate.lstat().st_mode
        special = (
            stat.S_ISLNK(mode) or stat.S_ISSOCK(mode) or stat.S_ISFIFO(mode)
            or stat.S_ISCHR(mode) or stat.S_ISBLK(mode)
        )
        if special:
            raise LocalSourceError("local source path must be a regular directory")
    rendered = str(candidate)
    if candidate == Path("/") or rendered == "/etc" or rendered.startswith("/etc/"):
        raise LocalSourceError("local source path is not allowed")
    root = configured_source_root()
    if require_root or root is not None:
        if root is None:
            raise LocalSourceError("HUB_LOCAL_SOURCE_ROOT is required")
        try:
            root_real = root.resolve(strict=True)
        except OSError as exc:
            raise LocalSourceError("HUB_LOCAL_SOURCE_ROOT does not exist") from exc
        if candidate == root_real:
            raise LocalSourceError("local source cannot be the source root itself")
        try:
            candidate.relative_to(root_real)
        except ValueError as exc:
            raise LocalSourceError("local source path is outside HUB_LOCAL_SOURCE_ROOT") from exc
        if ".." in Path(raw).parts:
            # Raw `..` is only allowed when resolve() still lands under the root.
            try:
                Path(raw).resolve(strict=True).relative_to(root_real)
            except ValueError as exc:
                raise LocalSourceError(
                    "local source path is outside HUB_LOCAL_SOURCE_ROOT",
                ) from exc
    return candidate


def refuse_api_local_path(path):
    """Serializer-facing check. Production default is off."""
    if not str(path or "").strip():
        return None
    if not local_sources_allowed():
        raise LocalSourceError("local_path is disabled; use git_url")
    root = configured_source_root()
    return resolve_local_source(
        path, require_root=root is not None, must_exist=False,
    )


def iter_archive_members(source_dir):
    """Yield (relative posix name, bytes) for a confined build context.

    Rejects VCS metadata, env files, vault.key, special files, TOCTOU swaps,
    and oversized trees. Fail closed on read errors.
    """
    root = resolve_local_source(source_dir, require_root=bool(configured_source_root()))
    total = 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if not _denied_name(name)]
        for filename in filenames:
            if filename == "Dockerfile" or _denied_name(filename):
                continue
            path = Path(dirpath) / filename
            try:
                before = path.lstat()
            except OSError as exc:
                raise LocalSourceError(f"cannot stat {path}") from exc
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                continue
            if before.st_size > MAX_FILE_BYTES:
                raise LocalSourceError("local source file exceeds size limit")
            try:
                with path.open("rb") as handle:
                    data = handle.read(MAX_FILE_BYTES + 1)
                    after = os.fstat(handle.fileno())
            except OSError as exc:
                raise LocalSourceError(f"cannot read {path}") from exc
            if after.st_ino != before.st_ino or after.st_dev != before.st_dev:
                raise LocalSourceError("local source path changed while reading")
            if not stat.S_ISREG(after.st_mode) or stat.S_ISLNK(after.st_mode):
                raise LocalSourceError("local source path changed while reading")
            if len(data) > MAX_FILE_BYTES:
                raise LocalSourceError("local source file exceeds size limit")
            total += len(data)
            count += 1
            if total > MAX_TOTAL_BYTES or count > MAX_FILES:
                raise LocalSourceError("local source tree exceeds size limit")
            rel = path.relative_to(root).as_posix()
            yield rel, data
