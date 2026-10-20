"""Small shared helpers: TOML I/O, atomic writes, time, hashing."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

__all__ = [
    "atomic_write_text",
    "dump_toml",
    "hash_tree",
    "load_toml",
    "move_noreplace",
    "now_iso",
    "parse_age",
    "parse_iso",
    "parse_value",
    "tomllib",
]


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file."""
    with path.open("rb") as f:
        return tomllib.load(f)


def atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically via a temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def dump_toml(path: Path, data: dict[str, Any]) -> None:
    """Serialize *data* to *path* atomically."""
    atomic_write_text(path, tomli_w.dumps(_drop_none(data)))


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value if v is not None]
    return value


def now_iso() -> str:
    """Current local time as ISO 8601 with offset, second precision."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime | None:
    """Parse an ISO timestamp; naive values are treated as local time."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


_DURATION_RE = re.compile(r"^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)(?:\.\d+)?$")


def parse_duration(value: str) -> int | None:
    """Seconds in a Slurm duration (``[D-][H:]MM:SS``, e.g. sacct ``Elapsed``)."""
    match = _DURATION_RE.match(str(value).strip())
    if not match:
        return None
    days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def format_duration(seconds: int) -> str:
    """``HH:MM:SS``, or ``D-HH:MM:SS`` from one day on."""
    days, rest = divmod(max(int(seconds), 0), 86400)
    text = f"{rest // 3600:02d}:{rest % 3600 // 60:02d}:{rest % 60:02d}"
    return f"{days}-{text}" if days else text


_AGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([dhw]?)\s*$")


def parse_age(value: str) -> timedelta:
    """Parse ``30d`` / ``12h`` / ``2w`` / ``30`` (days) into a timedelta."""
    match = _AGE_RE.match(value)
    if not match:
        from runops.errors import UsageError

        raise UsageError(f"invalid duration {value!r}; use e.g. 30d, 12h, 2w")
    amount = float(match.group(1))
    unit = match.group(2) or "d"
    return {
        "d": timedelta(days=amount),
        "h": timedelta(hours=amount),
        "w": timedelta(weeks=amount),
    }[unit]


def parse_value(raw: str) -> Any:
    """Parse a ``--set`` value as a TOML literal, falling back to a string."""
    try:
        return tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw


def hash_tree(root: Path) -> str:
    """Content hash of all regular files under *root* (path + bytes)."""
    digest = hashlib.sha256()
    if root.is_dir():
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b"\0")
            digest.update(hash_file(path).encode())
            digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def hash_file(path: Path) -> str:
    """SHA-256 of a file as ``sha256:<hex>``."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


_NOREPLACE_UNSUPPORTED = {errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP}


def _renameat2_noreplace(src: Path, dst: Path) -> bool:
    """True if renamed; False if the kernel/filesystem lacks RENAME_NOREPLACE."""
    if sys.platform != "linux":
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        func = libc.renameat2
    except (OSError, AttributeError):
        return False
    func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    func.restype = ctypes.c_int
    at_fdcwd, rename_noreplace = -100, 1
    if func(at_fdcwd, os.fsencode(src), at_fdcwd, os.fsencode(dst), rename_noreplace) == 0:
        return True
    code = ctypes.get_errno()
    if code in _NOREPLACE_UNSUPPORTED:
        return False  # e.g. Lustre on KUDPC returns EINVAL
    raise OSError(code, os.strerror(code), str(dst))


def move_noreplace(src: Path, dst: Path) -> None:
    """Rename *src* to *dst* without replacing anything and without copying.

    Uses ``renameat2(RENAME_NOREPLACE)`` where the filesystem supports it, and
    otherwise an existence check followed by ``rename`` (callers hold the
    project lock). A cross-filesystem move is refused instead of copied.
    """
    from runops.errors import UsageError

    if dst.exists() or dst.is_symlink():
        raise UsageError(f"{dst} already exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not _renameat2_noreplace(src, dst):
            os.rename(src, dst)
    except OSError as exc:
        if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
            raise UsageError(f"{dst} already exists") from None
        if exc.errno == errno.EXDEV:
            raise UsageError(
                f"cannot move {src} to {dst}: different filesystems; move it manually"
            ) from None
        raise
