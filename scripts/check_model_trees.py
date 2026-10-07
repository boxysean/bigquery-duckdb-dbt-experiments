#!/usr/bin/env python3
"""Keep the two peer projects building the SAME end models from the SAME source.

The repository compares 1_dbt_bigquery_duckdb (dbt v2) with 2_dbt_bigquery_trino_spark
(dbt v1). That comparison is only fair while both build the same models, so this check
fails (exit 1) on any drift:

  1. SQL, byte for byte. Every .sql file under models/ and tests/ must exist in both
     projects with identical content. Dialect differences belong in macros/polyglot,
     never in a model, so there is no allowlist.
  2. YAML, by structure. The .yml files may differ in prose (descriptions name each
     project's engine), but must declare the same sources, tables, models, columns and
     data tests (with the same arguments).
  3. The macro seam, by name. Every macro project 1 defines in macros/polyglot must
     exist in project 2 and vice versa, so a model that calls one compiles in both.

    python3 scripts/check_model_trees.py          # exit 0 in sync, 1 drift

Needs PyYAML, which both projects' tooling already installs (dbt depends on it).
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
P1 = REPO / "1_dbt_bigquery_duckdb"
P2 = REPO / "2_dbt_bigquery_trino_spark"
SQL_DIRS = ("models", "tests")
# Keys that are prose, not structure.
PROSE = {"description"}


def files(project: pathlib.Path, suffix: str) -> dict[str, pathlib.Path]:
    out = {}
    for d in SQL_DIRS:
        for p in sorted((project / d).rglob(f"*{suffix}")):
            out[p.relative_to(project).as_posix()] = p
    return out


def strip_prose(node):
    if isinstance(node, dict):
        return {k: strip_prose(v) for k, v in node.items() if k not in PROSE}
    if isinstance(node, list):
        return [strip_prose(v) for v in node]
    return node


def macro_names(project: pathlib.Path) -> set[str]:
    names = set()
    for p in (project / "macros" / "polyglot").glob("*.sql"):
        for m in re.finditer(r"\{%-?\s*macro\s+(\w+)\s*\(", p.read_text()):
            name = m.group(1)
            # adapter-specific implementations differ by design (default__/duckdb vs trino__)
            if "__" not in name:
                names.add(name)
    return names


def main() -> int:
    findings: list[str] = []

    s1, s2 = files(P1, ".sql"), files(P2, ".sql")
    for rel in sorted(set(s1) | set(s2)):
        if rel not in s2:
            findings.append(f"sql   {rel}: only in {P1.name}")
        elif rel not in s1:
            findings.append(f"sql   {rel}: only in {P2.name}")
        elif s1[rel].read_bytes() != s2[rel].read_bytes():
            findings.append(f"sql   {rel}: content differs (diff {P1.name}/{rel} {P2.name}/{rel})")

    y1, y2 = files(P1, ".yml"), files(P2, ".yml")
    for rel in sorted(set(y1) | set(y2)):
        if rel not in y2 or rel not in y1:
            findings.append(f"yml   {rel}: only in {P1.name if rel in y1 else P2.name}")
            continue
        a = strip_prose(yaml.safe_load(y1[rel].read_text()))
        b = strip_prose(yaml.safe_load(y2[rel].read_text()))
        if a != b:
            findings.append(f"yml   {rel}: declares different structure (names, columns, tests or arguments)")

    m1, m2 = macro_names(P1), macro_names(P2)
    for name in sorted(m1 - m2):
        findings.append(f"macro {name}: in {P1.name}/macros/polyglot only")
    for name in sorted(m2 - m1):
        findings.append(f"macro {name}: in {P2.name}/macros/polyglot only")

    for f in findings:
        print(f)
    print(f"\nsql files compared: {len(set(s1) & set(s2))}, yml files compared: {len(set(y1) & set(y2))}, "
          f"seam macros compared: {len(m1 & m2)}")
    if findings:
        print(f"DRIFT: {len(findings)} finding(s). The two projects no longer build the same models.")
        return 1
    print("IN SYNC: both projects build the same models from the same source, through the same macro seam.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
