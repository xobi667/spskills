#!/usr/bin/env python3
"""Validate a product-video material package without modifying its images."""

import argparse
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}
REQUIRED_FILES = (
    "source-manifest.json",
    "product-profile.json",
    "creative-brief.md",
    "storyboard.json",
    "storyboard.md",
    "prompts/flow.md",
    "prompts/capcut.md",
    "prompts/universal.json",
)
DEFAULT_PURPOSES = ("hook", "hero", "use", "detail", "ending")
SHOT_FIELDS = (
    "id",
    "sequence",
    "purpose",
    "duration_seconds",
    "scene",
    "product_action",
    "shot_size",
    "camera_angle",
    "camera_movement",
    "keyframe",
    "prompt_en",
    "negative_prompt_en",
)
PROFILE_LIST_FIELDS = (
    "visible_facts",
    "colors",
    "materials",
    "brand_text",
    "must_preserve",
    "uncertainties",
    "source_images",
)
START_MARKER = "<!-- product-video-validator:start -->"
END_MARKER = "<!-- product-video-validator:end -->"


class UserInputError(Exception):
    """Raised for invalid invocation input."""


class Validation:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def parse_ratio(value: str) -> Tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("ratio must use W:H, for example 9:16")
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ratio values must be integers") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("ratio values must be positive")
    return width, height


def ratio_text(ratio: Tuple[int, int]) -> str:
    return "%d:%d" % ratio


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def load_json(path: Path, validation: Validation, label: str) -> Optional[object]:
    text = read_text(path)
    if text is None:
        validation.error("%s cannot be read as UTF-8: %s" % (label, path.name))
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        validation.error("%s is invalid JSON: %s" % (label, exc))
        return None


def is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def validate_required_files(package: Path, validation: Validation) -> None:
    for relative in REQUIRED_FILES:
        path = package / relative
        if not path.exists():
            validation.error("required file is missing: %s" % relative)
        elif not path.is_file():
            validation.error("required path is not a file: %s" % relative)
        else:
            try:
                if path.stat().st_size == 0:
                    validation.error("required file is empty: %s" % relative)
            except OSError as exc:
                validation.error("required file cannot be inspected: %s (%s)" % (relative, exc))


def validate_manifest(package: Path, validation: Validation) -> None:
    path = package / "source-manifest.json"
    if not path.is_file() or path.stat().st_size == 0:
        return
    value = load_json(path, validation, "source-manifest.json")
    if not isinstance(value, dict):
        if value is not None:
            validation.error("source-manifest.json must contain a JSON object")
        return
    if value.get("schema_version") != "1.0":
        validation.warning("source-manifest.json schema_version is not 1.0")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        validation.error("source-manifest.json must contain at least one source")


def validate_profile(package: Path, validation: Validation) -> None:
    path = package / "product-profile.json"
    if not path.is_file() or path.stat().st_size == 0:
        return
    value = load_json(path, validation, "product-profile.json")
    if not isinstance(value, dict):
        if value is not None:
            validation.error("product-profile.json must contain a JSON object")
        return
    if value.get("schema_version") != "1.0":
        validation.error("product-profile.json schema_version must be 1.0")
    for field in ("project_name", "category", "confirmation_status"):
        if not is_nonempty_string(value.get(field)):
            validation.error("product-profile.json field %s must be a non-empty string" % field)
    if value.get("confirmation_status") not in ("auto_locked", "confirmed"):
        validation.error(
            "product-profile.json confirmation_status must be auto_locked or confirmed"
        )
    for field in PROFILE_LIST_FIELDS:
        item = value.get(field)
        if not isinstance(item, list):
            validation.error("product-profile.json field %s must be an array" % field)
        elif any(not isinstance(entry, str) for entry in item):
            validation.error("product-profile.json field %s must contain only strings" % field)
    must_preserve = value.get("must_preserve")
    if isinstance(must_preserve, list) and not must_preserve:
        validation.error("product-profile.json must_preserve must not be empty")
    source_images = value.get("source_images")
    if isinstance(source_images, list) and not source_images:
        validation.error("product-profile.json source_images must not be empty")


def safe_keyframe_path(value: object) -> Optional[PurePosixPath]:
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        return None
    if pure.parts[0] != "keyframes":
        return None
    return pure


def verify_image(path: Path) -> Tuple[int, int]:
    with Image.open(path) as opened:
        transposed = ImageOps.exif_transpose(opened)
        transposed.load()
        return transposed.size


def validate_storyboard(
    package: Path,
    validation: Validation,
    expected_shots: int,
    target_ratio: Tuple[int, int],
    ratio_tolerance: float,
) -> Tuple[Optional[Dict[str, object]], List[str]]:
    path = package / "storyboard.json"
    if not path.is_file() or path.stat().st_size == 0:
        return None, []
    raw = load_json(path, validation, "storyboard.json")
    if not isinstance(raw, dict):
        if raw is not None:
            validation.error("storyboard.json must contain a JSON object")
        return None, []

    if raw.get("schema_version") != "1.0":
        validation.error("storyboard.json schema_version must be 1.0")
    if not is_nonempty_string(raw.get("project_name")):
        validation.error("storyboard.json project_name must be a non-empty string")
    if raw.get("aspect_ratio") != ratio_text(target_ratio):
        validation.error(
            "storyboard.json aspect_ratio must be %s" % ratio_text(target_ratio)
        )
    if raw.get("product_profile_path") != "product-profile.json":
        validation.error("storyboard.json product_profile_path must be product-profile.json")
    if not is_positive_number(raw.get("target_duration_seconds")):
        validation.error("storyboard.json target_duration_seconds must be positive")

    shots = raw.get("shots")
    if not isinstance(shots, list):
        validation.error("storyboard.json shots must be an array")
        return raw, []
    if len(shots) != expected_shots:
        validation.error(
            "storyboard.json must contain exactly %d shots; found %d"
            % (expected_shots, len(shots))
        )

    ids = set()
    sequences = []
    durations: List[float] = []
    referenced: List[str] = []
    target_value = target_ratio[0] / target_ratio[1]

    for position, shot in enumerate(shots, 1):
        label = "shot[%d]" % (position - 1)
        if not isinstance(shot, dict):
            validation.error("%s must be a JSON object" % label)
            continue
        for field in SHOT_FIELDS:
            if field not in shot:
                validation.error("%s is missing field %s" % (label, field))
        for field in (
            "id",
            "purpose",
            "scene",
            "product_action",
            "shot_size",
            "camera_angle",
            "camera_movement",
            "keyframe",
            "prompt_en",
            "negative_prompt_en",
        ):
            if field in shot and not is_nonempty_string(shot.get(field)):
                validation.error("%s field %s must be a non-empty string" % (label, field))

        sequence = shot.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            validation.error("%s sequence must be an integer" % label)
        else:
            sequences.append(sequence)
            expected_id = "shot-%02d" % sequence
            if shot.get("id") != expected_id:
                validation.error("%s id must match sequence as %s" % (label, expected_id))

        shot_id = shot.get("id")
        if isinstance(shot_id, str):
            if shot_id in ids:
                validation.error("duplicate shot id: %s" % shot_id)
            ids.add(shot_id)

        if expected_shots == 5 and position <= len(DEFAULT_PURPOSES):
            if shot.get("purpose") != DEFAULT_PURPOSES[position - 1]:
                validation.error(
                    "%s purpose must be %s" % (label, DEFAULT_PURPOSES[position - 1])
                )

        duration = shot.get("duration_seconds")
        if not is_positive_number(duration):
            validation.error("%s duration_seconds must be a finite positive number" % label)
        else:
            durations.append(float(duration))

        pure = safe_keyframe_path(shot.get("keyframe"))
        if pure is None:
            validation.error(
                "%s keyframe must be a safe POSIX relative path under keyframes/" % label
            )
            continue
        relative = pure.as_posix()
        referenced.append(relative)
        if not re.match(r"^keyframes/shot-\d{2}-[a-z0-9-]+\.[a-z0-9]+$", relative):
            validation.warning("%s keyframe filename is nonstandard: %s" % (label, relative))
        keyframe = package.joinpath(*pure.parts)
        if not keyframe.exists():
            validation.error("%s keyframe is missing: %s" % (label, relative))
        elif not keyframe.is_file() or keyframe.stat().st_size == 0:
            validation.error("%s keyframe is empty or not a file: %s" % (label, relative))
        else:
            try:
                width, height = verify_image(keyframe)
                actual = width / height if height else 0.0
                relative_error = abs(actual - target_value) / target_value if target_value else 1.0
                if relative_error > ratio_tolerance:
                    validation.error(
                        "%s keyframe ratio %dx%d differs from %s by %.2f%%"
                        % (label, width, height, ratio_text(target_ratio), relative_error * 100)
                    )
            except (OSError, ValueError, UnidentifiedImageError) as exc:
                validation.error("%s keyframe cannot be decoded: %s" % (label, exc))

    if sequences != list(range(1, len(shots) + 1)):
        validation.error("shot sequence values must be continuous and ordered from 1")
    target_duration = raw.get("target_duration_seconds")
    if is_positive_number(target_duration) and len(durations) == len(shots):
        if abs(sum(durations) - float(target_duration)) > 0.1:
            validation.error(
                "shot duration total %.3f does not match target_duration_seconds %.3f"
                % (sum(durations), float(target_duration))
            )
    return raw, referenced


def validate_keyframe_inventory(
    package: Path,
    validation: Validation,
    referenced: List[str],
) -> None:
    folder = package / "keyframes"
    if not folder.exists():
        validation.error("keyframes directory is missing")
        return
    if not folder.is_dir():
        validation.error("keyframes path is not a directory")
        return
    actual = {
        path.relative_to(package).as_posix()
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    }
    expected = set(referenced)
    for extra in sorted(actual - expected):
        validation.error("unreferenced keyframe image: %s" % extra)
    if len(actual) != len(referenced):
        validation.error(
            "keyframe image count %d does not match referenced shot count %d"
            % (len(actual), len(referenced))
        )


def validate_markdown_prompts(
    package: Path,
    validation: Validation,
    expected_shots: int,
) -> None:
    for relative in ("prompts/flow.md", "prompts/capcut.md"):
        path = package / relative
        if not path.is_file() or path.stat().st_size == 0:
            continue
        text = read_text(path)
        if text is None:
            validation.error("%s cannot be read as UTF-8" % relative)
            continue
        for index in range(1, expected_shots + 1):
            if not re.search(r"shot[\s-]*0?%d\b" % index, text, re.IGNORECASE):
                validation.warning("%s does not visibly label Shot %02d" % (relative, index))


def validate_universal(
    package: Path,
    validation: Validation,
    expected_shots: int,
) -> None:
    path = package / "prompts/universal.json"
    if not path.is_file() or path.stat().st_size == 0:
        return
    value = load_json(path, validation, "prompts/universal.json")
    if not isinstance(value, dict):
        if value is not None:
            validation.error("prompts/universal.json must contain a JSON object")
        return
    if value.get("schema_version") != "1.0":
        validation.error("prompts/universal.json schema_version must be 1.0")
    shots = value.get("shots")
    if not isinstance(shots, list):
        validation.error("prompts/universal.json shots must be an array")
    elif len(shots) != expected_shots:
        validation.error(
            "prompts/universal.json must contain exactly %d shots" % expected_shots
        )
    else:
        for index, shot in enumerate(shots, 1):
            if not isinstance(shot, dict):
                validation.error("universal shot %d must be an object" % index)
                continue
            for field in ("id", "keyframe", "duration_seconds", "prompt_en", "negative_prompt_en"):
                if field not in shot:
                    validation.error("universal shot %d is missing field %s" % (index, field))


def validate_failed_file(package: Path, validation: Validation) -> None:
    path = package / "failed.txt"
    if not path.exists():
        return
    if not path.is_file():
        validation.error("failed.txt is not a file")
        return
    text = read_text(path)
    if text is None:
        validation.error("failed.txt cannot be read as UTF-8")
    elif text.strip():
        validation.error("failed.txt contains unresolved failures")


def render_block(validation: Validation, strict: bool) -> str:
    failed = bool(validation.errors) or (strict and bool(validation.warnings))
    lines = [
        START_MARKER,
        "## 结构校验",
        "",
        "状态：%s" % ("FAIL" if failed else "PASS"),
        "",
        "- 错误：%d" % len(validation.errors),
        "- 警告：%d" % len(validation.warnings),
    ]
    if validation.errors:
        lines.extend(["", "### 错误"])
        lines.extend("- %s" % item for item in validation.errors)
    if validation.warnings:
        lines.extend(["", "### 警告"])
        lines.extend("- %s" % item for item in validation.warnings)
    lines.extend([END_MARKER, ""])
    return "\n".join(lines)


def update_report(path: Path, block: str) -> None:
    existing = read_text(path) if path.exists() else None
    if existing is None:
        existing = "# Product Video QC Report\n\n"
    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(existing):
        updated = pattern.sub(block, existing, count=1)
    else:
        updated = existing.rstrip() + "\n\n" + block
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(updated, encoding="utf-8")
    temporary.replace(path)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a product-video material package.")
    parser.add_argument("--package", required=True, type=Path, help="Package directory.")
    parser.add_argument(
        "--expected-shots", type=int, default=5, help="Expected shot count. Default: 5."
    )
    parser.add_argument(
        "--target-ratio",
        type=parse_ratio,
        default=(9, 16),
        help="Expected W:H ratio. Default: 9:16.",
    )
    parser.add_argument(
        "--ratio-tolerance",
        type=float,
        default=0.02,
        help="Allowed relative ratio error. Default: 0.02.",
    )
    parser.add_argument(
        "--report", type=Path, help="QC report path. Default: <package>/qc-report.md."
    )
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary.")
    return parser


def run(args: argparse.Namespace) -> int:
    package = args.package.expanduser().resolve()
    if not package.exists() or not package.is_dir():
        raise UserInputError("package must be an existing directory")
    if args.expected_shots <= 0:
        raise UserInputError("expected-shots must be greater than zero")
    if args.ratio_tolerance < 0:
        raise UserInputError("ratio-tolerance must not be negative")
    report = args.report.expanduser().resolve() if args.report else package / "qc-report.md"

    validation = Validation()
    validate_required_files(package, validation)
    validate_manifest(package, validation)
    validate_profile(package, validation)
    _, referenced = validate_storyboard(
        package,
        validation,
        args.expected_shots,
        args.target_ratio,
        args.ratio_tolerance,
    )
    validate_keyframe_inventory(package, validation, referenced)
    validate_markdown_prompts(package, validation, args.expected_shots)
    validate_universal(package, validation, args.expected_shots)
    validate_failed_file(package, validation)

    failed = bool(validation.errors) or (args.strict and bool(validation.warnings))
    update_report(report, render_block(validation, args.strict))
    summary: Dict[str, object] = {
        "status": "FAIL" if failed else "PASS",
        "errors": len(validation.errors),
        "warnings": len(validation.warnings),
        "report": str(report),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(
            "status=%s errors=%d warnings=%d report=%s"
            % (summary["status"], summary["errors"], summary["warnings"], report)
        )
        for item in validation.errors:
            print("ERROR: %s" % item)
        for item in validation.warnings:
            print("WARNING: %s" % item)
    return 1 if failed else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = create_parser()
    try:
        args = parser.parse_args(argv)
        return run(args)
    except UserInputError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except (OSError, PermissionError) as exc:
        print("error: filesystem failure: %s" % exc, file=sys.stderr)
        return 3
    except Exception as exc:  # pragma: no cover - final safety boundary
        print("error: unexpected failure: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
