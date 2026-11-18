# hughtcourtscraperfinaldb.py
# Streams the Hugging Face dataset into numbered CSV files,
# with 1,000,000 records per file. Completed files are kept if interrupted;
# run the script again to resume.

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

from datasets import load_dataset
from huggingface_hub import HfApi


DATASET_ID = "KanoonGPT/indian-case-laws"
SPLIT = "train"
OUTPUT_DIR = Path("high_court_hf_chunks")
FILE_PREFIX = "indian_case_laws"
ROWS_PER_FILE = 1_000_000
PROGRESS_EVERY = 9_000


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return value


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return max(0, sum(1 for _ in csv.reader(file)) - 1)


def find_completed_parts(output_dir: Path) -> list[tuple[int, Path, int]]:
    pattern = re.compile(rf"^{re.escape(FILE_PREFIX)}_part_(\d+)\.csv$")
    parts = []

    for path in output_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            part_number = int(match.group(1))
            parts.append((part_number, path, count_csv_rows(path)))

    parts.sort(key=lambda item: item[0])

    for expected, (part_number, path, row_count) in enumerate(parts, start=1):
        if part_number != expected:
            raise RuntimeError("CSV part numbers are not consecutive.")
        if row_count > ROWS_PER_FILE:
            raise RuntimeError(f"Too many rows in {path.name}.")
        if expected < len(parts) and row_count != ROWS_PER_FILE:
            raise RuntimeError("Only the last CSV part may contain fewer than one million rows.")

    return parts


def write_manifest(path: Path, data: dict[str, Any]) -> None:
    temp_path = path.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT_DIR / "manifest.json"
    parts = find_completed_parts(OUTPUT_DIR)

    # Older huggingface_hub versions don't accept repo_type here.
    revision = HfApi().dataset_info(DATASET_ID).sha

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("dataset") != DATASET_ID or manifest.get("revision") != revision:
            raise RuntimeError(
                "The Hugging Face dataset changed since the last run. "
                "Use a new output folder for the new dataset revision."
            )
        if manifest.get("complete"):
            print("This dataset revision has already been downloaded.")
            return
    elif parts:
        raise RuntimeError(
            "CSV part files exist without a manifest. Keep them safe and use a new output folder."
        )
    else:
        if list(OUTPUT_DIR.iterdir()):
            raise RuntimeError(f"{OUTPUT_DIR} is not empty. Choose a new output folder.")
        manifest = {
            "dataset": DATASET_ID,
            "split": SPLIT,
            "revision": revision,
            "rows_per_file": ROWS_PER_FILE,
            "complete": False,
        }
        write_manifest(manifest_path, manifest)

    completed_rows = sum(row_count for _, _, row_count in parts)
    if parts and parts[-1][2] < ROWS_PER_FILE:
        manifest["downloaded_rows"] = completed_rows
        manifest["complete"] = True
        write_manifest(manifest_path, manifest)
        print(f"Download already complete: {completed_rows:,} records.")
        return

    print(f"Dataset: {DATASET_ID}")
    print(f"Revision: {revision}")
    print(f"Resuming after {completed_rows:,} completed records.")

    dataset = load_dataset(
        DATASET_ID,
        split=SPLIT,
        streaming=True,
        revision=revision,
    )
    fieldnames = list(dataset.features.keys())

    part_number = len(parts) + 1
    rows_in_part = 0
    total_written = completed_rows
    output_file = None
    writer = None
    temp_path = None
    row_number = -1

    try:
        for row_number, row in enumerate(dataset):
            if row_number < completed_rows:
                if (row_number + 1) % PROGRESS_EVERY == 0:
                    print(f"Resume scan: {row_number + 1:,} rows", flush=True)
                continue

            if output_file is None:
                final_path = OUTPUT_DIR / f"{FILE_PREFIX}_part_{part_number:03d}.csv"
                temp_path = final_path.with_suffix(".csv.tmp")
                output_file = temp_path.open("w", encoding="utf-8-sig", newline="")
                writer = csv.DictWriter(
                    output_file,
                    fieldnames=fieldnames,
                    extrasaction="ignore",
                )
                writer.writeheader()

            writer.writerow({key: csv_value(value) for key, value in row.items()})
            rows_in_part += 1
            total_written += 1

            if rows_in_part % PROGRESS_EVERY == 0:
                output_file.flush()
                print(
                    f"Part {part_number:03d}: {rows_in_part:,}/{ROWS_PER_FILE:,} "
                    f"| total written: {total_written:,}",
                    flush=True,
                )

            if rows_in_part == ROWS_PER_FILE:
                output_file.flush()
                os.fsync(output_file.fileno())
                output_file.close()
                output_file = None

                os.replace(
                    temp_path,
                    OUTPUT_DIR / f"{FILE_PREFIX}_part_{part_number:03d}.csv",
                )
                temp_path = None

                manifest["downloaded_rows"] = total_written
                write_manifest(manifest_path, manifest)

                print(
                    f"Saved {FILE_PREFIX}_part_{part_number:03d}.csv "
                    f"({ROWS_PER_FILE:,} rows)",
                    flush=True,
                )
                part_number += 1
                rows_in_part = 0

        if row_number + 1 < completed_rows:
            raise RuntimeError(
                "The dataset ended before all previously completed rows were reached."
            )

        if output_file is not None:
            output_file.flush()
            os.fsync(output_file.fileno())
            output_file.close()
            output_file = None
            os.replace(
                temp_path,
                OUTPUT_DIR / f"{FILE_PREFIX}_part_{part_number:03d}.csv",
            )
            temp_path = None

        manifest["downloaded_rows"] = total_written
        manifest["complete"] = True
        write_manifest(manifest_path, manifest)
        print(f"Download complete: {total_written:,} records in {part_number - 1} files.")

    except BaseException:
        if output_file is not None:
            output_file.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
        raise


if __name__ == "__main__":
    main()