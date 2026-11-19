from pathlib import Path
import re
import unicodedata

import pandas as pd


base_dir = Path(__file__).resolve().parent
sample = pd.read_csv(base_dir / "supreme_court_sample_1000.csv", dtype=str, keep_default_na=False)
verdicts = pd.read_excel(
    Path(r"C:\Users\Shreesh\Downloads\scraper_codex - Copy\supreme_court_all_judges_verdict.csv.xlsx"),
    dtype=str,
).fillna("")

keys = ["judge_name", "case_id", "title"]


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


for key in keys:
    sample[f"_key_{key}"] = sample[key].map(normalize)
    verdicts[f"_key_{key}"] = verdicts[key].map(normalize)

if verdicts.duplicated([f"_key_{key}" for key in keys]).any():
    raise RuntimeError("Verdict workbook has duplicate judge/case/title keys; refusing an ambiguous merge.")

merged = sample.merge(
    verdicts[[*(f"_key_{key}" for key in keys), "verdict"]],
    on=[f"_key_{key}" for key in keys],
    how="left",
    validate="one_to_one",
)
matched = int(merged["verdict"].ne("").sum())
print(f"sample_records={len(sample)}")
print(f"matched_real_verdicts={matched}")
print(f"distinct_verdict_labels={merged['verdict'].nunique()}")
print("verdict_counts:")
print(merged["verdict"].value_counts().to_string())

if matched != len(sample):
    missing = merged.loc[merged["verdict"].eq(""), keys].head(5).to_dict("records")
    print(f"unmatched_examples={missing}")
    raise RuntimeError("Not every sample record matched a verdict; no output was written.")

output = merged[[*keys, "verdict"]]
output_path = base_dir / "supreme_court_verdicts_1000.csv"
output.to_csv(output_path, index=False, encoding="utf-8-sig")
print(f"output_bytes={output_path.stat().st_size}")
