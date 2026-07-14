#!/usr/bin/env python3
"""Build a deterministic Azure Functions deployment ZIP."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def iter_files(root: Path, relative_root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            yield path, path.relative_to(relative_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/aml-event-function.zip"))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    entries: list[tuple[Path, Path]] = [
        (repo / "functions" / "function_app.py", Path("function_app.py")),
        (repo / "functions" / "host.json", Path("host.json")),
        (repo / "functions" / "requirements.txt", Path("requirements.txt")),
        (repo / "config" / "poc.yaml", Path("config/poc.yaml")),
    ]
    entries.extend(iter_files(repo / "src" / "azureml_snowflake_poc", repo / "src"))
    entries.extend(iter_files(repo / "azureml", repo))
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, destination in sorted(entries, key=lambda item: str(item[1])):
            info = zipfile.ZipInfo.from_file(source, arcname=str(destination))
            info.date_time = (2026, 1, 1, 0, 0, 0)
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
