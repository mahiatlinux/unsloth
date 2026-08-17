"""Roll up the on-disk checkpoint inventory by model family."""

import csv
from pathlib import Path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def total_gib_by_family(rows: list[dict[str, str]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        family = row["family"].strip().lower()
        totals[family] = totals.get(family, 0.0) + float(row["gib"])
    return totals


def widest_family(totals: dict[str, float]) -> str:
    if not totals:
        raise ValueError("no rows to summarise")
    return max(totals, key=lambda family: totals[family])


if __name__ == "__main__":
    rows = read_rows(Path("checkpoints.csv"))
    totals = total_gib_by_family(rows)
    for family, gib in sorted(totals.items()):
        print(f"{family:24s} {gib:9.2f} GiB")
    print(f"largest: {widest_family(totals)}")
