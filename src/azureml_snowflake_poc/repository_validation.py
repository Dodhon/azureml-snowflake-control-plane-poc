"""Static public-repository and documentation contract validation."""

from __future__ import annotations

import os
import re
from itertools import pairwise
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".validation",
    ".venv",
    "__pycache__",
}
_TEXT_SUFFIXES = {".bicep", ".gitignore", ".json", ".md", ".py", ".sql", ".toml", ".yaml", ".yml"}
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
_CHANGE_ME_RE = re.compile(r"\bCHANGE_ME_[A-Z0-9_]+\b")
_FORBIDDEN_PATTERNS = {
    "absolute local user path": re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    "private key material": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential assignment": re.compile(
        r"(?im)^\s*(?:password|token|secret|private_key)\s*[:=]\s*['\"][^<\n]{6,}"
    ),
}
_REQUIRED_FILES = {
    ".github/workflows/validate.yml",
    ".gitignore",
    "LICENSE",
    "README.md",
    "azureml/pipelines/lifecycle.pipeline.yml",
    "config/poc.yaml",
    "docs/architecture.md",
    "docs/configuration.md",
    "docs/maturity-roadmap.md",
    "docs/operations.md",
    "docs/sources.md",
    "infra/event-grid.bicep",
    "infra/main.bicep",
    "snowflake/001_prediction_contract.sql",
}


def _text_files() -> list[Path]:
    files: list[Path] = []
    for directory, names, filenames in os.walk(ROOT):
        names[:] = [name for name in names if name not in _SKIP_DIRS]
        parent = Path(directory)
        for name in filenames:
            path = parent / name
            if path.suffix in _TEXT_SUFFIXES or path.name == ".gitignore":
                files.append(path)
    return sorted(files)


def _validate_required_files(errors: list[str]) -> None:
    for relative in sorted(_REQUIRED_FILES):
        if not (ROOT / relative).is_file():
            errors.append(f"missing required file: {relative}")


def _validate_links(errors: list[str]) -> None:
    for path in _text_files():
        if path.suffix != ".md":
            continue
        for raw in _MARKDOWN_LINK_RE.findall(path.read_text(encoding="utf-8")):
            target = raw.strip().split(maxsplit=1)[0].strip("<>")
            parsed = urlparse(target)
            if parsed.scheme in {"http", "https", "mailto"} or target.startswith("#"):
                continue
            local = (path.parent / unquote(parsed.path)).resolve()
            try:
                local.relative_to(ROOT)
            except ValueError:
                errors.append(f"link escapes repository: {path.relative_to(ROOT)} -> {target}")
                continue
            if not local.exists():
                errors.append(f"broken local link: {path.relative_to(ROOT)} -> {target}")


def _validate_sensitive_context(errors: list[str]) -> None:
    for path in _text_files():
        if path.name == "repository_validation.py":
            continue
        content = path.read_text(encoding="utf-8")
        for label, pattern in _FORBIDDEN_PATTERNS.items():
            if pattern.search(content):
                errors.append(f"{label} found in {path.relative_to(ROOT)}")


def _validate_placeholders(errors: list[str]) -> None:
    documentation = ROOT / "docs/configuration.md"
    if not documentation.exists():
        return
    documented = set(_CHANGE_ME_RE.findall(documentation.read_text(encoding="utf-8")))
    for path in _text_files():
        if path == documentation:
            continue
        for token in sorted(set(_CHANGE_ME_RE.findall(path.read_text(encoding="utf-8")))):
            if token not in documented:
                errors.append(f"undocumented placeholder {token} in {path.relative_to(ROOT)}")


def _validate_markdown_structure(errors: list[str]) -> None:
    for path in _text_files():
        if path.suffix != ".md":
            continue
        headings: list[tuple[int, int]] = []
        in_fence = False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            match = re.match(r"^(#{1,6})\s+", line)
            if match:
                headings.append((number, len(match.group(1))))
        if sum(level == 1 for _, level in headings) != 1:
            errors.append(f"{path.relative_to(ROOT)} must contain exactly one H1")
        for previous, current in pairwise(headings):
            if current[1] > previous[1] + 1:
                errors.append(
                    f"heading-level jump in {path.relative_to(ROOT)}: {previous[0]} -> {current[0]}"
                )


def main() -> int:
    errors: list[str] = []
    _validate_required_files(errors)
    _validate_links(errors)
    _validate_sensitive_context(errors)
    _validate_placeholders(errors)
    _validate_markdown_structure(errors)
    if errors:
        print("Repository validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
