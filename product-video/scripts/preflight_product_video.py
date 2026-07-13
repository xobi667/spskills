#!/usr/bin/env python3
"""Build a deterministic source manifest for the product-video Codex Skill.

This script never decides what an image depicts. It records objective file/image
metadata and filename-based role hints so Codex can perform the visual review.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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
SKIP_DIR_NAMES = {".git", "__pycache__", ".next", "node_modules"}
STYLE_HINTS = (
    "参考",
    "风格",
    "场景",
    "reference",
    "style",
    "moodboard",
    "mood",
    "inspiration",
)
PRODUCT_HINTS = (
    "商品",
    "产品",
    "主图",
    "细节",
    "包装",
    "product",
    "hero",
    "detail",
    "packaging",
    "sku",
)
DEFAULT_PURPOSES = ("hook", "hero", "use", "detail", "ending")
REQUIRED_OUTPUTS = (
    "product-profile.json",
    "creative-brief.md",
    "storyboard.json",
    "storyboard.md",
    "prompts/flow.md",
    "prompts/capcut.md",
    "prompts/universal.json",
)


class UserInputError(Exception):
    """Raised for invalid CLI input."""


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def should_skip_directory(path: Path, package_dir: Path) -> bool:
    if path.name in SKIP_DIR_NAMES or path.name.endswith("-视频素材包"):
        return True
    try:
        return path.resolve() == package_dir.resolve()
    except OSError:
        return False


def walk_input(input_path: Path, package_dir: Path) -> Tuple[List[Path], List[str]]:
    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise UserInputError("input file is not a supported image")
        if input_path.is_symlink():
            raise UserInputError("symbolic-link inputs are not supported")
        return [input_path], []

    images: List[Path] = []
    ignored: List[str] = []
    for root, dirs, files in os.walk(str(input_path), followlinks=False):
        root_path = Path(root)
        dirs[:] = [
            name
            for name in dirs
            if not should_skip_directory(root_path / name, package_dir)
            and not (root_path / name).is_symlink()
        ]
        for name in files:
            path = root_path / name
            if path.is_symlink():
                ignored.append(path.relative_to(input_path).as_posix())
            elif path.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(path)
            else:
                ignored.append(path.relative_to(input_path).as_posix())
    images.sort(key=lambda item: item.relative_to(input_path).as_posix().casefold())
    ignored.sort(key=str.casefold)
    return images, ignored


def role_hint(relative_path: str) -> str:
    lowered = relative_path.casefold()
    style = any(token.casefold() in lowered for token in STYLE_HINTS)
    product = any(token.casefold() in lowered for token in PRODUCT_HINTS)
    if style and not product:
        return "style_reference_candidate"
    if product and not style:
        return "product_candidate"
    return "unknown"


def inspect_image(path: Path, relative_path: str, source_id: str) -> Dict[str, object]:
    base: Dict[str, object] = {
        "id": source_id,
        "source_path": path.resolve().as_posix(),
        "relative_path": relative_path,
        "sha256": "",
        "bytes": None,
        "width": None,
        "height": None,
        "format": None,
        "mode": None,
        "has_alpha": None,
        "aspect_ratio": None,
        "role": "unclassified",
        "role_source": "pending",
        "role_hint": role_hint(relative_path),
        "needs_visual_review": True,
        "error": None,
        "notes": "",
    }
    try:
        base["bytes"] = path.stat().st_size
        base["sha256"] = sha256_file(path)
        with Image.open(path) as opened:
            image_format = opened.format
            transposed = ImageOps.exif_transpose(opened)
            transposed.load()
            width, height = transposed.size
            base.update(
                {
                    "width": width,
                    "height": height,
                    "format": image_format,
                    "mode": transposed.mode,
                    "has_alpha": "A" in transposed.getbands(),
                    "aspect_ratio": round(width / height, 6) if height else None,
                }
            )
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        base["error"] = "%s: %s" % (type(exc).__name__, str(exc))
    return base


def load_json_object(path: Path) -> Optional[Dict[str, object]]:
    if not path.exists() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def merge_existing_classification(
    sources: List[Dict[str, object]],
    old_manifest: Optional[Dict[str, object]],
    reset: bool,
) -> None:
    if reset or not old_manifest:
        return
    old_sources = old_manifest.get("sources")
    if not isinstance(old_sources, list):
        return
    old_by_key: Dict[Tuple[str, str], Dict[str, object]] = {}
    for item in old_sources:
        if not isinstance(item, dict):
            continue
        relative = item.get("relative_path")
        digest = item.get("sha256")
        if isinstance(relative, str) and isinstance(digest, str):
            old_by_key[(relative, digest)] = item
    for source in sources:
        key = (str(source.get("relative_path", "")), str(source.get("sha256", "")))
        old = old_by_key.get(key)
        if not old:
            continue
        for field in ("role", "role_source", "notes"):
            value = old.get(field)
            if isinstance(value, str):
                source[field] = value


def path_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "present_unvalidated"
    try:
        return "present_nonempty" if path.stat().st_size > 0 else "present_empty"
    except OSError:
        return "present_unvalidated"


def standard_keyframes(shots: int) -> List[str]:
    values = []
    for index in range(1, shots + 1):
        purpose = DEFAULT_PURPOSES[index - 1] if index <= len(DEFAULT_PURPOSES) else "shot"
        values.append("keyframes/shot-%02d-%s.png" % (index, purpose))
    return values


def storyboard_keyframes(package_dir: Path, shots: int) -> List[str]:
    board = load_json_object(package_dir / "storyboard.json")
    if board and isinstance(board.get("shots"), list):
        found: List[str] = []
        for shot in board["shots"]:
            if isinstance(shot, dict) and isinstance(shot.get("keyframe"), str):
                found.append(shot["keyframe"])
        if found:
            return found
    return standard_keyframes(shots)


def collect_existing_outputs(package_dir: Path, shots: int) -> Dict[str, str]:
    outputs = {item: path_status(package_dir / item) for item in REQUIRED_OUTPUTS}
    for item in storyboard_keyframes(package_dir, shots):
        candidate = Path(item)
        if candidate.is_absolute() or ".." in candidate.parts:
            outputs[item] = "present_unvalidated"
        else:
            outputs[item] = path_status(package_dir / candidate)
    return outputs


def task_status(paths: Sequence[str], existing: Dict[str, str]) -> str:
    return (
        "review_existing"
        if any(existing.get(path, "missing") != "missing" for path in paths)
        else "pending"
    )


def build_tasks(shots: int, existing: Dict[str, str]) -> List[Dict[str, str]]:
    tasks = [
        {"id": "visual-classification", "status": "pending"},
        {
            "id": "product-profile",
            "status": task_status(["product-profile.json"], existing),
        },
        {
            "id": "storyboard",
            "status": task_status(["storyboard.json", "storyboard.md"], existing),
        },
    ]
    keyframes = standard_keyframes(shots)
    for index, keyframe in enumerate(keyframes, 1):
        tasks.append(
            {
                "id": "generate-shot-%02d" % index,
                "status": task_status([keyframe], existing),
            }
        )
    tasks.extend(
        [
            {
                "id": "platform-prompts",
                "status": task_status(
                    ["prompts/flow.md", "prompts/capcut.md", "prompts/universal.json"],
                    existing,
                ),
            },
            {"id": "visual-qc", "status": "pending"},
            {"id": "structural-validation", "status": "pending"},
        ]
    )
    return tasks


def atomic_write_json(path: Path, value: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def default_package_dir(input_path: Path) -> Path:
    name = input_path.stem if input_path.is_file() else input_path.name
    return input_path.parent / (name + "-视频素材包")


def parse_platforms(value: str) -> List[str]:
    platforms = []
    for item in value.split(","):
        normalized = item.strip().lower()
        if normalized and normalized not in platforms:
            platforms.append(normalized)
    if not platforms:
        raise argparse.ArgumentTypeError("platforms must not be empty")
    return platforms


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preflight scanner for Codex product-video projects."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input image or directory.")
    parser.add_argument(
        "--package-dir",
        type=Path,
        help="Output package directory. Default: sibling <name>-视频素材包.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Manifest path. Default: <package-dir>/source-manifest.json.",
    )
    parser.add_argument(
        "--target-ratio",
        type=parse_ratio,
        default=(9, 16),
        help="Target W:H ratio. Default: 9:16.",
    )
    parser.add_argument("--shots", type=int, default=5, help="Expected shot count. Default: 5.")
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Target edited duration in seconds. Default: 10.",
    )
    parser.add_argument(
        "--platforms",
        type=parse_platforms,
        default=["flow", "capcut"],
        help="Comma-separated platform names. Default: flow,capcut.",
    )
    parser.add_argument(
        "--reset-classification",
        action="store_true",
        help="Discard roles and notes preserved from an existing manifest.",
    )
    parser.add_argument(
        "--show-limit",
        type=int,
        default=20,
        help="Number of scanned items to print. Default: 20.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        raise UserInputError("input path does not exist: %s" % input_path)
    if not input_path.is_file() and not input_path.is_dir():
        raise UserInputError("input must be an image file or directory")
    if args.shots <= 0:
        raise UserInputError("shots must be greater than zero")
    if args.duration <= 0:
        raise UserInputError("duration must be greater than zero")
    if args.show_limit < 0:
        raise UserInputError("show-limit must be zero or greater")

    package_dir = (
        args.package_dir.expanduser().resolve()
        if args.package_dir
        else default_package_dir(input_path).resolve()
    )
    manifest_path = (
        args.manifest.expanduser().resolve()
        if args.manifest
        else package_dir / "source-manifest.json"
    )
    if input_path.is_file() and package_dir == input_path:
        raise UserInputError("package directory cannot be the input file")

    old_manifest = load_json_object(manifest_path)
    image_paths, ignored = walk_input(input_path, package_dir)
    sources: List[Dict[str, object]] = []
    for index, path in enumerate(image_paths, 1):
        relative = path.name if input_path.is_file() else path.relative_to(input_path).as_posix()
        sources.append(inspect_image(path, relative, "src-%03d" % index))
    merge_existing_classification(sources, old_manifest, args.reset_classification)

    invalid = sum(1 for item in sources if item.get("error"))
    valid = len(sources) - invalid
    existing = collect_existing_outputs(package_dir, args.shots)
    warnings: List[str] = []
    if invalid:
        warnings.append("%d image(s) could not be opened; inspect their error fields." % invalid)
    if valid == 0:
        warnings.append("No valid input images were found.")

    project_name = input_path.stem if input_path.is_file() else input_path.name
    manifest: Dict[str, object] = {
        "schema_version": "1.0",
        "project": {
            "name": project_name,
            "input": input_path.as_posix(),
            "package_dir": package_dir.as_posix(),
            "target_ratio": ratio_text(args.target_ratio),
            "expected_shots": args.shots,
            "target_duration_seconds": args.duration,
            "platforms": args.platforms,
        },
        "sources": sources,
        "ignored_files": ignored,
        "existing_outputs": existing,
        "tasks": build_tasks(args.shots, existing),
        "warnings": warnings,
    }
    atomic_write_json(manifest_path, manifest)

    for item in sources[: args.show_limit]:
        print(
            "%s role_hint=%s size=%sx%s path=%s%s"
            % (
                item["id"],
                item["role_hint"],
                item["width"],
                item["height"],
                item["relative_path"],
                " error=" + str(item["error"]) if item.get("error") else "",
            )
        )
    print(
        "status=%s images=%d invalid=%d ignored=%d manifest=%s"
        % (
            "ok" if valid > 0 and invalid == 0 else "warning",
            valid,
            invalid,
            len(ignored),
            manifest_path,
        )
    )
    return 0 if valid > 0 and invalid == 0 else 1


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
