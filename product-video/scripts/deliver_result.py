#!/usr/bin/env python3
"""Persist product-video results and optionally deliver them to Feishu.

The script deliberately uses only the Python standard library.  Every command
prints exactly one JSON object to stdout; lark-cli output is always captured.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple


PREFERRED_DESKTOP = Path(r"D:\UserData\Desktop")
LOG_FILENAME = "生图日志.txt"
DEFAULT_PREFIX = "商品视频"
RESULT_SUFFIX = "-视频提示词.txt"
SHOT_ROLES = ("hook", "hero", "use", "detail", "ending")
SHOT_KEYS = tuple("{:02d}-{}".format(index, role) for index, role in enumerate(SHOT_ROLES, 1))
MAX_IMAGE_COUNT = len(SHOT_ROLES)
CLI_TIMEOUT_SECONDS = 120

NOTICE_ENV = {
    "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
    "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
}

_READY_WORDS = {
    "active",
    "authenticated",
    "available",
    "ok",
    "ready",
    "logged_in",
    "loggedin",
    "success",
    "valid",
    "verified",
}
_AUTH_WORDS = (
    "access denied",
    "auth",
    "forbidden",
    "invalid token",
    "login required",
    "not logged",
    "permission",
    "scope",
    "token expired",
    "unauthorized",
)
_TRANSIENT_WORDS = (
    "429",
    "502",
    "503",
    "504",
    "connection refused",
    "connection reset",
    "econnreset",
    "etimedout",
    "network",
    "rate limit",
    "temporarily unavailable",
    "temporary failure",
    "timed out",
    "timeout",
)
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)((?:(?:(?:tenant|user|app)[_-]?)?access[_-]?token|"
        r"(?:tenant[_-]?|user[_-]?)?refresh[_-]?token|"
        r"app[_-]?secret|client[_-]?secret|device[_-]?code|"
        r"open[_-]?id|chat[_-]?id|user[_-]?id)\s*[=:]\s*)([^\s,;]+)"
    ),
    re.compile(
        r'(?i)("(?:(?:(?:tenant|user|app)[_-]?)?access[_-]?token|'
        r'(?:tenant[_-]?|user[_-]?)?refresh[_-]?token|'
        r'app[_-]?secret|client[_-]?secret|device[_-]?code|'
        r'open[_-]?id|chat[_-]?id|user[_-]?id)"\s*:\s*)'
        r'("[^"]*"|[^,}\s]+)'
    ),
    re.compile(r"(?i)((?:authorization)\s*[=:]\s*bearer\s+)([^\s,;]+)"),
)
_BARE_IDENTIFIER_PATTERN = re.compile(r"\b(?:ou|oc|cli)_[A-Za-z0-9_-]{8,}\b")
_BARE_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}=*")


class DeliveryError(Exception):
    """Expected, user-actionable delivery input error."""


class ParsedImage(NamedTuple):
    index: int
    role: str
    source: Path


class SavedImage(NamedTuple):
    index: int
    role: str
    path: Path


def _json_stdout(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _sanitize_text(value: Any, limit: int = 500) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + "[REDACTED]", text)
    text = _BARE_IDENTIFIER_PATTERN.sub("[REDACTED_ID]", text)
    text = _BARE_BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    return text[:limit]


def resolve_log_path(
    explicit: Optional[str], output_dir: Optional[Path] = None
) -> Path:
    """Resolve the log path without relying on a hard-coded user identity."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    if PREFERRED_DESKTOP.is_dir():
        return PREFERRED_DESKTOP / LOG_FILENAME
    home_desktop = Path.home() / "Desktop"
    if home_desktop.is_dir():
        return home_desktop / LOG_FILENAME
    codex_home_value = os.environ.get("CODEX_HOME")
    if codex_home_value:
        return Path(codex_home_value).expanduser().resolve() / "logs" / LOG_FILENAME
    home = Path.home()
    if home.is_dir():
        return home / ".codex" / "logs" / LOG_FILENAME
    base = (output_dir or Path.cwd()).expanduser().resolve()
    return base / LOG_FILENAME


def append_log(path: Path, fields: Mapping[str, Any]) -> Tuple[bool, Optional[str]]:
    """Append one safe, plain-text operation record."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = _datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        lines = ["", "[{}]".format(timestamp)]
        for key, value in fields.items():
            if isinstance(value, (list, tuple)):
                safe_value = " | ".join(_sanitize_text(item) for item in value)
            else:
                safe_value = _sanitize_text(value)
            lines.append("{}={}".format(key, safe_value))
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        return True, None
    except OSError as exc:
        return False, "log_write_failed:{}".format(exc.__class__.__name__)


def _run_cli(
    cli_path: str, argv: Sequence[str], cwd: Optional[Path] = None
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(NOTICE_ENV)
    return subprocess.run(
        [cli_path] + list(argv),
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_SECONDS,
        check=False,
        shell=False,
    )


def _failure_kind(completed: subprocess.CompletedProcess) -> str:
    combined = "{} {}".format(completed.stdout or "", completed.stderr or "").lower()
    if any(word in combined for word in _AUTH_WORDS):
        return "auth_or_permission_error"
    if any(word in combined for word in _TRANSIENT_WORDS):
        return "transient_network_error"
    return "lark_cli_error"


def _invoke_with_retry(
    cli_path: str, argv: Sequence[str], cwd: Optional[Path] = None
) -> Tuple[Optional[subprocess.CompletedProcess], int, str]:
    """Run lark-cli, retrying a transient network failure exactly once."""
    attempts = 0
    while attempts < 2:
        attempts += 1
        try:
            completed = _run_cli(cli_path, argv, cwd=cwd)
        except (subprocess.TimeoutExpired, ConnectionError, OSError) as exc:
            # Missing executables and filesystem errors are not network retries.
            transient = isinstance(exc, (subprocess.TimeoutExpired, ConnectionError))
            if transient and attempts == 1:
                continue
            kind = "transient_network_error" if transient else "lark_cli_unavailable"
            return None, attempts, kind
        if completed.returncode == 0:
            return completed, attempts, "ok"
        kind = _failure_kind(completed)
        if kind == "transient_network_error" and attempts == 1:
            continue
        return completed, attempts, kind
    return None, attempts, "transient_network_error"


def _normalise_word(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _truthy_ready(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _normalise_word(value) in _READY_WORDS


def _collect_scopes(user: Mapping[str, Any]) -> set:
    values: List[Any] = []
    for key in ("scope", "scopes"):
        value = user.get(key)
        if isinstance(value, str):
            values.extend(re.split(r"[\s,]+", value))
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if isinstance(item, Mapping):
                    name = item.get("name") or item.get("scope")
                    if name:
                        values.append(name)
                else:
                    values.append(item)
        elif isinstance(value, Mapping):
            values.extend(name for name, enabled in value.items() if enabled)
    return {str(item).strip() for item in values if str(item).strip()}


def _user_is_verified(root: Mapping[str, Any], user: Mapping[str, Any]) -> bool:
    user_verification_keys = ("verified", "serverVerified", "server_verified")
    present_user_verifications = [
        user.get(key) for key in user_verification_keys if key in user
    ]
    user_verification_values = [user.get(key) for key in user_verification_keys]
    if present_user_verifications:
        # Any explicit contradictory/false user verification is rejected; it
        # must not be overridden by a root-level app/bot verification result.
        if not all(_truthy_ready(value) for value in present_user_verifications):
            return False
    verification_values = list(user_verification_values)
    verification_values.extend(
        [root.get("verified"), root.get("serverVerified"), root.get("server_verified")]
    )
    verification = root.get("verification")
    if isinstance(verification, Mapping):
        verification_values.extend(
            [verification.get("verified"), verification.get("success"), verification.get("valid")]
        )
    if not any(_truthy_ready(value) for value in verification_values):
        return False
    # `auth status --verify` may report a stale local cache as needs_refresh
    # while server verification succeeds.  Reject only explicit invalid or
    # unauthorized states; the verified server result is authoritative.
    rejected_states = {
        "expired",
        "failed",
        "logged_out",
        "not_logged_in",
        "revoked",
        "unauthorized",
        "unavailable",
    }
    for value in (
        user.get("status"),
        user.get("tokenStatus", user.get("token_status")),
    ):
        word = _normalise_word(value)
        if word in rejected_states or word == "invalid" or word.startswith("invalid_"):
            return False
    if "available" in user and not _truthy_ready(user.get("available")):
        return False
    return bool(user.get("openId") or user.get("open_id"))


def _bot_is_ready(bot: Mapping[str, Any]) -> bool:
    if not bot:
        return False
    evidence = False
    for key in ("ready", "available", "verified"):
        if key in bot:
            evidence = True
            if not _truthy_ready(bot.get(key)):
                return False
    if "status" in bot:
        evidence = True
        if not _truthy_ready(bot.get("status")):
            return False
    return evidence


def _safe_probe_payload(
    mode: str,
    cli_available: bool,
    feishu_status: str,
    user_open_id: Optional[str] = None,
    user_name: Optional[str] = None,
    error: Optional[str] = None,
    cli_path: Optional[str] = None,
    bot_ready: bool = False,
) -> Dict[str, Any]:
    return {
        "ok": True,
        "delivery_mode": mode,
        "cli_available": cli_available,
        "feishu_status": feishu_status,
        "user_open_id": user_open_id,
        "user_name": user_name,
        "error": error,
        # Internal consumers need the resolved executable, but it is not secret.
        "_cli_path": cli_path,
        "_bot_ready": bot_ready,
    }


def probe_identity() -> Dict[str, Any]:
    cli_path = shutil.which("lark-cli")
    if not cli_path:
        return _safe_probe_payload("local_only", False, "cli_missing", error="cli_missing")

    completed, attempts, kind = _invoke_with_retry(
        cli_path, ["auth", "status", "--json", "--verify"]
    )
    if completed is None or completed.returncode != 0:
        return _safe_probe_payload(
            "local_only",
            True,
            "auth_unavailable",
            error="{}:attempts={}".format(kind, attempts),
            cli_path=cli_path,
        )
    try:
        payload = json.loads(completed.stdout or "{}")
    except (TypeError, ValueError):
        return _safe_probe_payload(
            "local_only",
            True,
            "invalid_auth_json",
            error="invalid_auth_json",
            cli_path=cli_path,
        )
    if not isinstance(payload, Mapping):
        return _safe_probe_payload(
            "local_only",
            True,
            "invalid_auth_json",
            error="invalid_auth_json",
            cli_path=cli_path,
        )

    identities = payload.get("identities")
    if not isinstance(identities, Mapping):
        identities = {}
    user = identities.get("user")
    bot = identities.get("bot")
    if not isinstance(user, Mapping):
        user = {}
    if not isinstance(bot, Mapping):
        bot = {}
    open_id = user.get("openId") or user.get("open_id")
    user_name = user.get("userName") or user.get("user_name")
    open_id = str(open_id) if open_id else None
    user_name = str(user_name) if user_name else None

    required_scopes = {"im:message.send_as_user", "im:message"}
    bot_ready = bool(open_id and _bot_is_ready(bot))
    if _user_is_verified(payload, user) and required_scopes.issubset(_collect_scopes(user)):
        return _safe_probe_payload(
            "user",
            True,
            "ready",
            open_id,
            user_name,
            cli_path=cli_path,
            bot_ready=bot_ready,
        )
    if bot_ready:
        return _safe_probe_payload(
            "bot",
            True,
            "ready",
            open_id,
            user_name,
            cli_path=cli_path,
            bot_ready=True,
        )
    return _safe_probe_payload(
        "local_only",
        True,
        "identity_not_ready",
        open_id,
        user_name,
        error="identity_not_ready",
        cli_path=cli_path,
    )


def _public_probe(probe: Mapping[str, Any]) -> Dict[str, Any]:
    mode = str(probe.get("delivery_mode") or "local_only")
    return {
        "delivery_mode": mode,
        "ready": mode in ("user", "bot"),
        "error": probe.get("error"),
    }


def sanitize_prefix(value: str) -> str:
    """Make a user prefix safe as one Windows filename component."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned:
        cleaned = DEFAULT_PREFIX
    stem_upper = cleaned.split(".", 1)[0].upper()
    if stem_upper in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
        r"(?:COM|LPT)[1-9]", stem_upper
    ):
        cleaned = "_" + cleaned
    return cleaned[:80].rstrip(" .") or DEFAULT_PREFIX


def _safe_suffix(source: Path) -> str:
    suffix = source.suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix or ""):
        return suffix
    return ".png"


def _image_target(
    output_dir: Path, prefix: str, index: int, role: str, source: Path
) -> Path:
    return output_dir / "{}-{:02d}-{}{}".format(
        prefix, index, role, _safe_suffix(source)
    )


def _result_target(output_dir: Path, prefix: str) -> Path:
    return output_dir / (prefix + RESULT_SUFFIX)


def _same_file(source: Path, destination: Path) -> bool:
    if not destination.exists():
        return False
    try:
        return os.path.samefile(str(source), str(destination))
    except OSError:
        return source.resolve() == destination.resolve()


def _prefix_conflicts(
    output_dir: Path, prefix: str, images: Sequence[ParsedImage]
) -> bool:
    provided = {(image.index, image.role): image.source for image in images}
    if output_dir.is_dir():
        entries = [path for path in output_dir.iterdir() if path.is_file()]
        for index, role in enumerate(SHOT_ROLES, start=1):
            filename_prefix = "{}-{:02d}-{}.".format(prefix, index, role).lower()
            source = provided.get((index, role))
            for existing in entries:
                if not existing.name.lower().startswith(filename_prefix):
                    continue
                if source is None or not _same_file(source, existing):
                    return True
    return _result_target(output_dir, prefix).exists()


def _choose_output_prefix(
    output_dir: Path, requested: str, images: Sequence[ParsedImage]
) -> str:
    base = sanitize_prefix(requested)
    if not _prefix_conflicts(output_dir, base, images):
        return base
    timestamp = _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = "{}-{}".format(base, timestamp)
    counter = 2
    while _prefix_conflicts(output_dir, candidate, images):
        candidate = "{}-{}-{:02d}".format(base, timestamp, counter)
        counter += 1
    return candidate


def _copy_without_overwrite(source: Path, destination: Path) -> None:
    """Copy one file using exclusive creation so an existing result is safe."""
    created = False
    try:
        with source.open("rb") as reader:
            with destination.open("xb") as writer:
                created = True
                shutil.copyfileobj(reader, writer)
        shutil.copystat(str(source), str(destination))
    except Exception:
        # Only remove a partial file created by this function.
        try:
            if created and destination.exists():
                destination.unlink()
        except OSError:
            pass
        raise


def _parse_image_specs(images: Sequence[str]) -> List[ParsedImage]:
    if len(images) > MAX_IMAGE_COUNT:
        raise DeliveryError("at_most_{}_images_allowed".format(MAX_IMAGE_COUNT))
    explicit: List[Tuple[str, str]] = []
    bare: List[str] = []
    for raw in images:
        key, separator, value = raw.partition("=")
        if separator and key in SHOT_KEYS:
            explicit.append((key, value))
        elif separator and re.fullmatch(r"\d{2}-[A-Za-z0-9_-]+", key):
            raise DeliveryError("invalid_image_role:{}".format(key))
        else:
            bare.append(raw)
    if explicit and bare:
        raise DeliveryError("cannot_mix_role_images_and_bare_paths")

    parsed: List[ParsedImage] = []
    if explicit:
        seen = set()
        for key, value in explicit:
            if key in seen:
                raise DeliveryError("duplicate_image_role:{}".format(key))
            seen.add(key)
            index = SHOT_KEYS.index(key) + 1
            parsed.append(ParsedImage(index, SHOT_ROLES[index - 1], Path(value).expanduser().resolve()))
        parsed.sort(key=lambda item: item.index)
    else:
        semantic_pattern = re.compile(
            r"(?:^|-)(0[1-5])-(hook|hero|use|detail|ending)(?=\.[^.]+$)", re.IGNORECASE
        )
        for position, value in enumerate(bare, start=1):
            source = Path(value).expanduser().resolve()
            match = semantic_pattern.search(source.name)
            if match:
                inferred_index = int(match.group(1))
                inferred_role = match.group(2).lower()
                if inferred_index != position or inferred_role != SHOT_ROLES[position - 1]:
                    raise DeliveryError("bare_images_must_be_contiguous_from_01")
            parsed.append(ParsedImage(position, SHOT_ROLES[position - 1], source))
    for image in parsed:
        if not image.source.is_file():
            raise DeliveryError("image_not_found:{}".format(image.source))
    return parsed


def _copy_images(
    images: Sequence[ParsedImage], output_dir: Path, prefix: str
) -> Tuple[List[SavedImage], str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_prefix = _choose_output_prefix(output_dir, prefix, images)
    local_images: List[SavedImage] = []
    for image in images:
        destination = _image_target(
            output_dir, selected_prefix, image.index, image.role, image.source
        )
        if not _same_file(image.source, destination):
            _copy_without_overwrite(image.source, destination)
        local_images.append(
            SavedImage(image.index, image.role, destination.resolve())
        )
    return local_images, selected_prefix


def _write_result_text(output_dir: Path, prefix: str, result_text: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = _result_target(output_dir, prefix)
    with destination.open("x", encoding="utf-8-sig", newline="\n") as handle:
        handle.write(result_text)
        if result_text and not result_text.endswith("\n"):
            handle.write("\n")
    return destination.resolve()


def _delivery_summary(delivery: Mapping[str, Any]) -> str:
    status = str(delivery.get("delivery_status") or "failed")
    identity = str(delivery.get("identity") or "local_only")
    if status == "sent":
        label = "mixed" if identity == "mixed" else "sent/{}".format(identity)
    elif status == "dry_run":
        label = "dry_run/{}".format(identity)
    elif status == "local_only":
        label = "local_only"
    else:
        label = "failed"
    reason = delivery.get("error") or delivery.get("fallback_reason")
    if not reason:
        reason = "发送完成" if status == "sent" else "仅预演，未真实发送"
    return "{} — {}".format(label, _sanitize_text(reason, limit=240))


def _append_delivery_status(result_path: Path, summary: str) -> None:
    # The file already starts with a UTF-8 BOM. Appending plain UTF-8 keeps a
    # single BOM and remains directly readable in Windows Notepad.
    with result_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n飞书投递：{}\n".format(summary))


def _content_digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


def _content_digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _idempotency_key(
    run_id: str,
    kind: str,
    index: Optional[int] = None,
    content_digest: Optional[str] = None,
) -> str:
    raw = "product-video:{}:{}".format(run_id, kind)
    if index is not None:
        raw += ":{:02d}".format(index)
    if content_digest:
        raw += ":{}".format(content_digest)
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "-", raw).strip("-")
    if not safe:
        safe = "product-video"
    if len(safe) > 96:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        safe = safe[:79] + "-" + digest
    return safe


def _send_results(
    probe: Mapping[str, Any],
    local_images: Sequence[SavedImage],
    result_text: str,
    run_id: str,
    dry_run: bool,
) -> Dict[str, Any]:
    mode = str(probe.get("delivery_mode") or "local_only")
    cli_path = probe.get("_cli_path")
    open_id = probe.get("user_open_id")
    if mode not in ("user", "bot") or not cli_path or not open_id:
        return {
            "delivery_status": "local_only",
            "identity": "local_only",
            "images_sent": 0,
            "error": probe.get("error") or probe.get("feishu_status"),
        }

    sent = 0
    identities_used = set()
    fallback_reason: Optional[str] = None
    bot_ready = bool(probe.get("_bot_ready"))

    def identity_result(current: str) -> str:
        if len(identities_used) > 1:
            return "mixed"
        if identities_used:
            return next(iter(identities_used))
        return current

    def send_one(
        identity: str,
        flag: str,
        value: str,
        key: str,
        cwd: Path,
    ) -> Tuple[bool, int, str]:
        argv = [
            "im",
            "+messages-send",
            "--as",
            identity,
            "--user-id",
            str(open_id),
            flag,
            value,
            "--idempotency-key",
            key,
        ]
        if dry_run:
            argv.append("--dry-run")
        completed, attempts, kind = _invoke_with_retry(str(cli_path), argv, cwd=cwd)
        return bool(completed is not None and completed.returncode == 0), attempts, kind

    with tempfile.TemporaryDirectory(prefix="product-video-lark-") as temporary:
        stage_dir = Path(temporary).resolve()
        staged: List[SavedImage] = []
        for image in local_images:
            destination = stage_dir / image.path.name
            shutil.copy2(str(image.path), str(destination))
            staged.append(SavedImage(image.index, image.role, destination))

        for staged_image in staged:
            relative_image = "./{}".format(staged_image.path.name)
            key = _idempotency_key(
                run_id,
                "image",
                staged_image.index,
                _content_digest_file(staged_image.path),
            )
            success, attempts, kind = send_one(
                mode, "--image", relative_image, key, stage_dir
            )
            if not success and mode == "user" and bot_ready:
                fallback_reason = "{}:image={}:attempts={}".format(
                    kind, staged_image.index, attempts
                )
                mode = "bot"
                success, attempts, kind = send_one(
                    mode, "--image", relative_image, key, stage_dir
                )
            if not success:
                return {
                    "delivery_status": "failed",
                    "identity": identity_result(mode),
                    "images_sent": 0 if dry_run else sent,
                    "error": "{}:image={}:attempts={}".format(
                        kind, staged_image.index, attempts
                    ),
                    "fallback_reason": fallback_reason,
                }
            identities_used.add(mode)
            sent += 1

        text_key = _idempotency_key(
            run_id,
            "text",
            content_digest=_content_digest_bytes(result_text.encode("utf-8")),
        )
        success, attempts, kind = send_one(
            mode, "--text", result_text, text_key, stage_dir
        )
        if not success and mode == "user" and bot_ready:
            fallback_reason = "{}:text:attempts={}".format(kind, attempts)
            mode = "bot"
            success, attempts, kind = send_one(
                mode, "--text", result_text, text_key, stage_dir
            )
        if not success:
            return {
                "delivery_status": "failed",
                "identity": identity_result(mode),
                "images_sent": 0 if dry_run else sent,
                "error": "{}:text:attempts={}".format(kind, attempts),
                "fallback_reason": fallback_reason,
            }
        identities_used.add(mode)
    return {
        "delivery_status": "dry_run" if dry_run else "sent",
        "identity": identity_result(mode),
        "images_sent": 0 if dry_run else sent,
        "error": None,
        "fallback_reason": fallback_reason,
    }


def execute_probe(run_id: str, output_dir: Optional[str], log_file: Optional[str]) -> Dict[str, Any]:
    output_path = Path(output_dir).expanduser().resolve() if output_dir else Path.cwd()
    probe = probe_identity()
    log_path = resolve_log_path(log_file, output_path)
    log_ok, log_error = append_log(
        log_path,
        {
            "command": "probe",
            "run_id": run_id,
            "input_paths": [],
            "output_paths": [],
            "image_count": 0,
            "identity": probe.get("delivery_mode"),
            "feishu_status": probe.get("feishu_status"),
            "error_summary": probe.get("error") or "none",
            "local_saved": "not_applicable",
        },
    )
    result = _public_probe(probe)
    result.update(
        {
            "command": "probe",
            "run_id": run_id,
            "log_file": str(log_path),
            "log_status": "written" if log_ok else log_error,
        }
    )
    return result


def execute_deliver(
    images: Sequence[str],
    result_text: str,
    output_dir: str,
    run_id: str,
    dry_run: bool,
    log_file: Optional[str],
    prefix: str = DEFAULT_PREFIX,
) -> Dict[str, Any]:
    output_path = Path(output_dir).expanduser().resolve()
    parsed_images = _parse_image_specs(images)
    local_images, selected_prefix = _copy_images(parsed_images, output_path, prefix)
    result_path = _write_result_text(output_path, selected_prefix, result_text)
    try:
        probe = probe_identity()
        delivery = _send_results(probe, local_images, result_text, run_id, dry_run)
    except Exception as exc:
        # Local files are already durable; an unexpected Feishu/staging problem
        # must not hide them from the caller.
        delivery = {
            "delivery_status": "failed",
            "identity": "local_only",
            "images_sent": 0,
            "error": "delivery_internal_error:{}".format(exc.__class__.__name__),
        }
    summary = _delivery_summary(delivery)
    try:
        _append_delivery_status(result_path, summary)
    except OSError as exc:
        delivery = {
            "delivery_status": "failed",
            "identity": delivery.get("identity") or "local_only",
            "images_sent": delivery.get("images_sent", 0),
            "error": "result_status_append_failed:{}".format(exc.__class__.__name__),
        }
        summary = _delivery_summary(delivery)
    local_paths = [str(image.path) for image in local_images] + [str(result_path)]
    log_path = resolve_log_path(log_file, output_path)
    log_ok, log_error = append_log(
        log_path,
        {
            "command": "deliver",
            "run_id": run_id,
            "input_paths": [str(image.source) for image in parsed_images],
            "output_paths": local_paths,
            "image_count": len(local_images),
            "identity": delivery.get("identity"),
            "feishu_status": summary,
            "error_summary": delivery.get("error") or delivery.get("fallback_reason") or "none",
            "local_saved": True,
        },
    )
    return {
        "ok": delivery.get("delivery_status") in ("sent", "dry_run", "local_only"),
        "command": "deliver",
        "run_id": run_id,
        "output_prefix": selected_prefix,
        "delivery_status": delivery.get("delivery_status"),
        "identity": delivery.get("identity"),
        "images_sent": delivery.get("images_sent"),
        "error": delivery.get("error"),
        "delivery_summary": summary,
        "local_paths": local_paths,
        "log_file": str(log_path),
        "log_status": "written" if log_ok else log_error,
    }


def execute_log(
    output_dir: str,
    run_id: str,
    event: str,
    source: Optional[str],
    shot: Optional[str],
    status: Optional[str],
    detail: Optional[str],
    output: Optional[str],
    log_file: Optional[str],
) -> Dict[str, Any]:
    """Append a safe image-generation lifecycle event without using lark-cli."""
    output_path = Path(output_dir).expanduser().resolve()
    log_path = resolve_log_path(log_file, output_path)
    log_ok, log_error = append_log(
        log_path,
        {
            "command": "log",
            "run_id": run_id,
            "event": event,
            "source_path": Path(source).expanduser().resolve() if source else "none",
            "shot": shot or "none",
            "status": status or "none",
            "detail": detail or "none",
            "output_path": Path(output).expanduser().resolve() if output else "none",
        },
    )
    return {
        "ok": log_ok,
        "command": "log",
        "run_id": run_id,
        "event": event,
        "log_file": str(log_path),
        "log_status": "written" if log_ok else log_error,
    }


def _log_command_failure(args: argparse.Namespace, error: str) -> Dict[str, Any]:
    command = getattr(args, "command", "unknown")
    output_value = getattr(args, "output_dir", None)
    output_dir = Path(output_value).expanduser().resolve() if output_value else Path.cwd()
    log_path = resolve_log_path(getattr(args, "log_file", None), output_dir)
    images = list(getattr(args, "image", None) or [])
    input_paths: List[str] = []
    for item in images:
        key, separator, value = item.partition("=")
        path_value = value if separator and key in SHOT_KEYS else item
        input_paths.append(str(Path(path_value).expanduser().resolve()))
    existing: List[str] = []
    if output_dir.is_dir():
        prefix = sanitize_prefix(getattr(args, "prefix", DEFAULT_PREFIX))
        for index, role in enumerate(SHOT_ROLES, start=1):
            existing.extend(
                str(path.resolve())
                for path in output_dir.glob("{}-{:02d}-{}.*".format(prefix, index, role))
            )
        result_path = _result_target(output_dir, prefix)
        if result_path.is_file():
            existing.append(str(result_path.resolve()))
    log_ok, log_error = append_log(
        log_path,
        {
            "command": command,
            "run_id": getattr(args, "run_id", "unknown"),
            "input_paths": input_paths,
            "output_paths": existing,
            "image_count": len(images),
            "identity": "not_selected",
            "feishu_status": "not_attempted",
            "error_summary": error,
            "local_saved": bool(existing),
        },
    )
    return {
        "log_file": str(log_path),
        "log_status": "written" if log_ok else log_error,
        "local_paths": existing,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser("probe", help="Inspect local Feishu delivery readiness")
    probe_parser.add_argument("--run-id", default="probe")
    probe_parser.add_argument("--output-dir")
    probe_parser.add_argument("--log-file")

    deliver_parser = subparsers.add_parser(
        "deliver", help="Persist and deliver zero to five result images plus text"
    )
    deliver_parser.add_argument("--image", action="append", default=[])
    deliver_parser.add_argument("--result-text-stdin", action="store_true", required=True)
    deliver_parser.add_argument("--output-dir", required=True)
    deliver_parser.add_argument("--run-id", required=True)
    deliver_parser.add_argument("--dry-run", action="store_true")
    deliver_parser.add_argument("--log-file")
    deliver_parser.add_argument("--prefix", default=DEFAULT_PREFIX)

    log_parser = subparsers.add_parser("log", help="Append one safe image-generation event")
    log_parser.add_argument("--output-dir", required=True)
    log_parser.add_argument("--run-id", required=True)
    log_parser.add_argument("--event", required=True)
    log_parser.add_argument("--source")
    log_parser.add_argument("--shot")
    log_parser.add_argument("--status")
    log_parser.add_argument("--detail")
    log_parser.add_argument("--output")
    log_parser.add_argument("--log-file")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args: Optional[argparse.Namespace] = None
    try:
        args = parser.parse_args(argv)
        if args.command == "probe":
            result = execute_probe(args.run_id, args.output_dir, args.log_file)
        elif args.command == "deliver":
            result_text = sys.stdin.read()
            result = execute_deliver(
                args.image,
                result_text,
                args.output_dir,
                args.run_id,
                args.dry_run,
                args.log_file,
                args.prefix,
            )
        else:
            result = execute_log(
                args.output_dir,
                args.run_id,
                args.event,
                args.source,
                args.shot,
                args.status,
                args.detail,
                args.output,
                args.log_file,
            )
        _json_stdout(result)
        return 0 if result.get("ok", True) else 1
    except DeliveryError as exc:
        error = _sanitize_text(exc)
        result: Dict[str, Any] = {
            "ok": False,
            "delivery_status": "failed",
            "error": error,
            "local_paths": [],
        }
        if args is not None:
            result.update(_log_command_failure(args, error))
        _json_stdout(result)
        return 2
    except Exception as exc:  # Keep stdout machine-readable without exposing internals.
        error = "internal_error:{}".format(exc.__class__.__name__)
        result = {"ok": False, "delivery_status": "failed", "error": error, "local_paths": []}
        if args is not None:
            result.update(_log_command_failure(args, error))
        _json_stdout(result)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
