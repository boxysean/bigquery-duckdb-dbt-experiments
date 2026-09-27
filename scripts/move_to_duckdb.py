#!/usr/bin/env python3
"""Move this BigQuery-targeted dbt project to a DuckDB-only one.

The project is one dbt project with two targets and a transcoding seam in
macros/polyglot/ (entry macro -> adapter.dispatch -> default__ = DuckDB,
bigquery__ = BigQuery). Moving it to DuckDB only is three steps:

  1. Absorb. Every seam call in models/, tests/ and analyses/polyglot_showcase.sql
     is replaced, textually, by its DuckDB rendering. The macros are loaded into a
     jinja2 Environment in which adapter.dispatch always picks the default__ branch;
     each `{{ ... }}` block that calls the seam is rendered there, and every other
     Jinja block ({{ ref() }}, {{ source() }}, {{ config() }}, {{ var() }},
     {{ env_var() }}, {{ this }}, comments, {% %} tags) is kept byte for byte.
     Inside a seam block, ref/source/config/var/env_var/this are stubs that print
     their own Jinja text back, so lineage survives there too.
  2. Rewrite. The three things no macro can hide are rewritten and diffed: the
     source `database:` line, profiles.yml (one DuckDB output) and dbt_project.yml
     (no macro-paths).
  3. Report. <out>/MOVE-REPORT.md (also printed): what was absorbed, what was
     edited, what cannot move (a detector for BigQuery-only constructs), the
     verification run, and an inventory of every file.

    .venv/bin/python scripts/move_to_duckdb.py --out DIR [--verify] [--force] [--report FILE]
    .venv/bin/python scripts/move_to_duckdb.py --out DIR --manual a,b,c
    .venv/bin/python scripts/move_to_duckdb.py --demo

Exit codes: 0 moved (and built green with --verify); 1 the moved project failed to
build, or --demo showed the detector missed a construct; 2 could not start;
3 moved as far as it goes, hand-move files are outstanding.

Stdlib plus jinja2 (the dev dependency group: `uv sync`). No network.
"""

import argparse
import difflib
import os
import re
import shutil
import signal
import subprocess
import sys
from collections import Counter
from pathlib import Path

try:
    import jinja2
except ImportError:  # reported by main() as an exit-2 "could not start"
    jinja2 = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_portability import strip_sql_comments  # noqa: E402  (same comment rules as the guardrail)

EXIT_MOVED, EXIT_BUILD_FAILED, EXIT_CANNOT_START, EXIT_HAND_MOVE = 0, 1, 2, 3

SEAM_DIR = Path("macros") / "polyglot"
SHOWCASE = Path("analyses") / "polyglot_showcase.sql"
TRANSPORT_REASON = ("not part of the warehouse: raw transport measurement scenarios, logs and "
                    "results (BigQuery community extension, GCS, Google credentials)")
SOURCES_YML = Path("models") / "staging" / "_thelook__sources.yml"
DEMO_FILE = Path("models") / "intermediate" / "_move_demo.sql"
MARKER = ".moved-by-move_to_duckdb"
LINEAGE = ("ref", "source", "config", "var", "env_var")
BLOCK_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)


class MoveError(Exception):
    """Something the procedure cannot do automatically; the message says what."""


def rel(path, base):
    return Path(path).resolve().relative_to(base).as_posix()


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


# --------------------------------------------------------------------------- 1
# The seam, loaded into jinja2 with adapter.dispatch pinned to default__.

class _DbtReturn(Exception):
    """dbt's `{{ return(x) }}` ends the macro with value x; so does this."""

    def __init__(self, value):
        super().__init__()
        self.value = value


def _jinja_literal(value):
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "none"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_jinja_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_jinja_literal(k)}: {_jinja_literal(v)}" for k, v in value.items()) + "}"
    return str(value)


def _lineage_stub(name):
    """ref('x') -> the literal text `{{ ref('x') }}`: dbt resolves it later."""
    def stub(*args, **kwargs):
        parts = [_jinja_literal(a) for a in args] + [f"{k}={_jinja_literal(v)}" for k, v in kwargs.items()]
        return "{{ %s(%s) }}" % (name, ", ".join(parts))
    return stub


class _ThisStub:
    def __init__(self, expr="this"):
        self._expr = expr

    def __str__(self):
        return "{{ %s }}" % self._expr

    def __getattr__(self, attr):
        return _ThisStub(f"{self._expr}.{attr}")


class Seam:
    """macros/polyglot/*.sql, rendering every call as its DuckDB (default__) branch.

    Entry names are bound to the entry macros themselves, and their
    adapter.dispatch returns the default__ branch: the result is exactly the
    default__ rendering, but the entry macro's own validation and normalisation
    (timestamp_trunc_to's granularity check, generate_date_series's step parsing,
    decimal_type's ceiling) still run, as they do under dbt. default__ branches that
    call other entry names resolve through the same bindings. bigquery__ branches
    are never reachable.
    """

    def __init__(self, source_root):
        self.root = source_root
        self.files = sorted((source_root / SEAM_DIR).glob("*.sql"))
        texts = {f: f.read_text(encoding="utf-8") for f in self.files}
        self.defined = [n for f in self.files
                        for n in re.findall(r"\{%-?\s*macro\s+(\w+)\s*\(", texts[f])]
        public = [n for n in self.defined if not n.startswith(("default__", "bigquery__"))]
        self.dialect = [n for n in public if "default__" + n in self.defined]
        self.selftests = [n for n in public if n not in self.dialect]
        self.duckdb_branch = {n: "default__" + n for n in self.dialect}
        self.registry = {}
        self.counts = Counter()   # top-level call sites, by entry name
        self._depth = 0

        env = jinja2.Environment(extensions=["jinja2.ext.do"], undefined=jinja2.StrictUndefined,
                                 keep_trailing_newline=True)
        # Globals must exist before the macro modules are built (jinja2 copies the
        # globals into each module's context), so they are late-bound wrappers.
        for name in self.defined:
            env.globals[name] = self._bound(name)
        env.globals.update(
            adapter=type("Adapter", (), {"dispatch": staticmethod(self._dispatch)})(),
            exceptions=type("Exceptions", (), {"raise_compiler_error": staticmethod(self._raise)})(),
            modules=type("Modules", (), {"re": re})(),
            this=_ThisStub(),
            **{"return": self._return},
            **{name: _lineage_stub(name) for name in LINEAGE},
        )
        self.env = env
        # Each macro is compiled as raw__<name>: a macro defined in the same file
        # would otherwise shadow the global wrapper, and a sibling call (e.g.
        # default__month_start -> timestamp_trunc_to) would bypass the wrapper that
        # catches its `return`.
        for f in self.files:
            src = re.sub(r"(\{%-?\s*macro\s+)(\w+)(\s*\()", r"\1raw__\2\3", texts[f])
            module = env.from_string(src).module
            for name in re.findall(r"\{%-?\s*macro\s+(\w+)\s*\(", texts[f]):
                self.registry[name] = getattr(module, "raw__" + name)
        call_names = sorted(self.defined, key=len, reverse=True)
        self.call_re = re.compile(r"(?<![\w.])(" + "|".join(map(re.escape, call_names)) + r")\s*\(")
        self.entry_re = re.compile(r"(?<![\w.])(" + "|".join(map(re.escape, self.dialect)) + r")\s*\(")

    @staticmethod
    def _return(value):
        raise _DbtReturn(value)

    @staticmethod
    def _raise(msg):
        raise MoveError(f"compiler error from the seam: {msg}")

    def _dispatch(self, name, package=None):
        if name not in self.duckdb_branch:
            raise MoveError(f"adapter.dispatch('{name}'): no default__{name} in {SEAM_DIR}")
        return self.env.globals[self.duckdb_branch[name]]

    def _bound(self, name):
        def call(*args, **kwargs):
            if name.startswith("bigquery__"):
                raise MoveError(f"{name} is the BigQuery branch; a DuckDB-only project cannot call it")
            if self._depth == 0:
                self.counts[name] += 1
            self._depth += 1
            try:
                out = self.registry[name](*args, **kwargs)
            except _DbtReturn as r:
                out = r.value
            finally:
                self._depth -= 1
            return out
        call.__name__ = name
        return call

    def render_block(self, block):
        """Render one `{{ ... }}` block. Returns (DuckDB text, Counter of call sites)."""
        before = Counter(self.counts)
        body = block[2:-2]
        body = body[1:] if body.startswith("-") else body
        body = body[:-1] if body.endswith("-") else body
        out = self.env.from_string("{{" + body + "}}").render()
        return out, self.counts - before

    def transcode(self, text):
        """Inline every seam block of one file.

        Returns (new text, list of call sites). A site is
        (line, original block, DuckDB rendering, Counter of macros).
        Raises MoveError for anything the textual inliner cannot do.
        """
        out, sites, pos = [], [], 0
        for m in BLOCK_RE.finditer(text):
            block, line = m.group(0), line_of(text, m.start())
            chunk = text[pos:m.start()]
            pos = m.end()
            if block.startswith("{#") or not self.call_re.search(block) and "adapter.dispatch" not in block:
                out.append(chunk + block)
                continue
            if block.startswith("{%"):
                raise MoveError(f"line {line}: a seam macro inside a {{% %}} tag cannot be inlined "
                                f"textually: {block.strip()[:120]}")
            try:
                rendered, used = self.render_block(block)
            except MoveError as e:
                raise MoveError(f"line {line}: {e}") from None
            except jinja2.TemplateError as e:
                raise MoveError(f"line {line}: {type(e).__name__}: {e} in {block.strip()[:120]}") from None
            if block.startswith("{{-"):
                chunk = chunk.rstrip()
            out.append(chunk + rendered)
            if block.endswith("-}}"):
                rest = text[pos:]
                pos += len(rest) - len(rest.lstrip())
            sites.append((line, block, rendered, used))
        out.append(text[pos:])
        return "".join(out), sites

    def static_count(self, text):
        """Entry-macro names written inside seam `{{ }}` blocks (the cross-check)."""
        n = Counter()
        for m in BLOCK_RE.finditer(text):
            if m.group(0).startswith("{{"):
                n.update(self.entry_re.findall(m.group(0)))
        return n


# --------------------------------------------------------------------------- 3
# The detector: BigQuery-only constructs that no macro in the seam covers.

def _wide_decimal(m):
    return int(m.group(1)) > 38


DETECTOR_RULES = [
    # (id, what it is, regex, optional predicate on the match)
    ("partition_by", "dbt partition_by config (BigQuery table partitioning)",
     re.compile(r"\+?\bpartition_by\b\s*[:=]", re.I), None),
    ("cluster_by", "dbt cluster_by config (BigQuery clustering)",
     re.compile(r"\+?\bcluster_by\b\s*[:=]", re.I), None),
    ("external_table", "external table (external_location / uris / format)",
     re.compile(r"\bexternal_location\b|\buris\b\s*[:=]|\bformat\b\s*[:=]\s*['\"]?"
                r"(parquet|csv|avro|orc|json|newline_delimited_json|google_sheets|datastore_backup)\b", re.I), None),
    ("table_options", "OPTIONS(...) table/column options",
     re.compile(r"\boptions\s*\(", re.I), None),
    ("bq_script", "BigQuery script (BEGIN ... END, CREATE PROCEDURE, DECLARE)",
     re.compile(r"^\s*begin\b|\bcreate\s+(or\s+replace\s+)?procedure\b|^\s*declare\s+\w+", re.I | re.M), None),
    ("storage_api", "BigQuery Storage Write/Read API",
     re.compile(r"storage[_ ]?(read|write)[_ ]?api|\bbigquery[_.]storage\b|BigQuery(Read|Write)Client", re.I), None),
    ("geography", "GEOGRAPHY type / ST_GEOG* constructors",
     re.compile(r"\bgeography\b|\bst_geog\w*\s*\(", re.I), None),
    ("bignumeric", "BIGNUMERIC, or a decimal wider than DuckDB's 38 digits",
     re.compile(r"\bbig(numeric|decimal)\b", re.I), None),
    ("bignumeric", "BIGNUMERIC, or a decimal wider than DuckDB's 38 digits",
     re.compile(r"\b(?:numeric|decimal|decimal_type)\s*\(\s*(\d+)", re.I), _wide_decimal),
    ("bqml", "BigQuery ML (ML.PREDICT and friends, CREATE MODEL)",
     re.compile(r"\bml\s*\.\s*\w+\s*\(|\bcreate\s+(or\s+replace\s+)?model\b", re.I), None),
    ("safe_offset", "SAFE_OFFSET / SAFE_ORDINAL (and OFFSET/ORDINAL) array subscripts",
     re.compile(r"\bsafe_(offset|ordinal)\s*\(|\[\s*(offset|ordinal)\s*\(", re.I), None),
    ("with_offset", "UNNEST ... WITH OFFSET",
     re.compile(r"\bwith\s+offset\b", re.I), None),
    ("target_branch", "a branch on the target ({% if target.type %}, target.name, adapter.type)",
     re.compile(r"\btarget\s*\.\s*(type|name)\b|\badapter\s*\.\s*type\b", re.I), None),
]
DETECTOR_IDS = list(dict.fromkeys(r[0] for r in DETECTOR_RULES))


def _strip_yaml_comments(text):
    out = []
    for line in text.splitlines():
        quote, cut = None, len(line)
        for i, ch in enumerate(line):
            if quote:
                quote = None if ch == quote else quote
            elif ch in "'\"":
                quote = ch
            elif ch == "#" and (i == 0 or line[i - 1].isspace()):
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def _strip_jinja_comments(text):
    return re.sub(r"\{#.*?#\}", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)


def detect(path, base):
    """Findings for one file: list of (relpath, line, rule id, matched text, source line)."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix in (".yml", ".yaml"):
        scan = _strip_yaml_comments(raw)
    else:
        scan = strip_sql_comments(_strip_jinja_comments(raw))
    raw_lines = raw.splitlines()
    findings, seen = [], set()
    for rule_id, _, rx, pred in DETECTOR_RULES:
        for m in rx.finditer(scan):
            if pred and not pred(m):
                continue
            line = line_of(scan, m.start())
            key = (line, rule_id, m.start())
            if key in seen:
                continue
            seen.add(key)
            findings.append((rel(path, base), line, rule_id, m.group(0).strip(),
                             raw_lines[line - 1].strip() if line <= len(raw_lines) else ""))
    return sorted(findings, key=lambda f: (f[0], f[1]))


def fmt_finding(f):
    return f"{f[0]}:{f[1]}: [{f[2]}] `{f[3]}` -> {f[4]}"


# --------------------------------------------------------------------------- 2
# The rewrites.

def read_yaml_subset(text):
    """Just enough YAML for profiles.yml: nested mappings, `- scalar` lists, comments."""
    lines = [(len(l) - len(l.lstrip()), l.strip()) for l in _strip_yaml_comments(text).splitlines() if l.strip()]

    def scalar(v):
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            return v[1:-1]
        return int(v) if re.fullmatch(r"-?\d+", v) else v

    def parse(i, indent):
        if lines[i][1].startswith("- "):
            items = []
            while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                items.append(scalar(lines[i][1][2:]))
                i += 1
            return items, i
        mapping = {}
        while i < len(lines) and lines[i][0] == indent:
            key, _, val = lines[i][1].partition(":")
            i += 1
            if val.strip():
                mapping[key.strip()] = scalar(val)
            elif i < len(lines) and (lines[i][0] > indent or lines[i][1].startswith("- ")):
                mapping[key.strip()], i = parse(i, lines[i][0])
            else:
                mapping[key.strip()] = None
        return mapping, i

    return parse(0, lines[0][0])[0] if lines else {}


def duckdb_output(source_root):
    """(profile name, output name, output dict, absolute DuckDB file) from the source project."""
    project = (source_root / "dbt_project.yml").read_text(encoding="utf-8")
    m = re.search(r"^profile:\s*['\"]?([\w-]+)", project, re.M)
    if not m:
        raise MoveError("dbt_project.yml names no profile")
    profile_name = m.group(1)
    profiles = read_yaml_subset((source_root / "profiles.yml").read_text(encoding="utf-8"))
    outputs = (profiles.get(profile_name) or {}).get("outputs") or {}
    duck = [(n, o) for n, o in outputs.items() if isinstance(o, dict) and o.get("type") == "duckdb"]
    if not duck:
        raise MoveError(f"profiles.yml: profile {profile_name} has no type: duckdb output")
    name, out = sorted(duck, key=lambda d: d[0] != "duckdb")[0]
    path = Path(str(out.get("path", "")))
    path = path if path.is_absolute() else (source_root / path).resolve()
    return profile_name, name, out, path


def unified(before, after, name, context=2):
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        f"a/{name}", f"b/{name}", n=context))


def rewrite_sources(text, catalog):
    pattern = re.compile(r"^(\s*database:\s*).*\btarget\.(type|name)\b.*$", re.M)
    if not pattern.search(text):
        return text, 0
    return pattern.subn(lambda m: f'{m.group(1)}"{catalog}"', text)


def emit_profile(profile_name, output_name, out, db_path):
    threads = out.get("threads", 4)
    return (
        "# Machine-written by scripts/move_to_duckdb.py (the DuckDB-only move of\n"
        "# bq_duckdb_experiments). One target, DuckDB. Regenerate rather than edit.\n"
        "#\n"
        "# `path` is the SOURCE repository's DuckDB file, by absolute path, so this\n"
        "# project reads the same fixture and its test run is comparable. Point it at a\n"
        "# local file to make the moved project independent of the source checkout.\n"
        f"{profile_name}:\n"
        f"  target: {output_name}\n"
        "  outputs:\n"
        f"    {output_name}:\n"
        "      type: duckdb\n"
        f"      path: {db_path}\n"
        f"      schema: {out.get('schema', 'main')}\n"
        f"      threads: {threads}\n"
        "      extensions:\n"
        "        - httpfs\n"
        "        - iceberg\n"
    )


def rewrite_project(text):
    header = ("# Moved to DuckDB only by scripts/move_to_duckdb.py: the seam macros were\n"
              "# inlined into the models, so this project ships no macros (macro-paths dropped).\n")
    return header + re.sub(r"^macro-paths:.*\n", "", text, flags=re.M)


def emit_makefile(source_root, db_path):
    return f"""\
# Machine-written by scripts/move_to_duckdb.py. One project, one target (DuckDB):
# no guardrail, no parity, no bq target.
SHELL := /bin/bash
.DEFAULT_GOAL := build

DBT ?= {source_root / '.venv' / 'bin' / 'dbt'}
DUCKDB_DB ?= {db_path}
export DBT_PROFILES_DIR := $(CURDIR)

.PHONY: build fixtures

# (Re)load the thelook_ecommerce fixture into the DuckDB file the profile reads.
fixtures:
\tDUCKDB_DB=$(DUCKDB_DB) bash scripts/load_duckdb_sources.sh

build:
\t$(DBT) build --target duckdb
"""


# --------------------------------------------------------------------------- the move

def source_files(source_root):
    """Every file of the source project (git-tracked if possible)."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=source_root, check=True,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode()
        files = [f for f in out.split("\0") if f and (source_root / f).is_file()]
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", ".venv", "target", "logs", "dbt_packages", "dbt_internal_packages", "__pycache__"}
        files = []
        for dirpath, dirnames, filenames in os.walk(source_root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            files += [rel(Path(dirpath) / f, source_root) for f in filenames]
    return sorted(files)


def transport_dir(relpath):
    """`analyses/transport_<x>` for a file inside such a directory, else None.

    Every transport measurement (transport_a, transport_b, any later one) is skipped
    as one unit and rolled up to one inventory line.
    """
    parts = Path(relpath).parts
    if len(parts) > 2 and parts[0] == "analyses" and parts[1].startswith("transport_"):
        return f"{parts[0]}/{parts[1]}"
    return None


def classify(relpath):
    """(action, reason). action: transcode | copy | rewrite | skip."""
    p = Path(relpath)
    top = p.parts[0]
    if top in ("models", "tests"):
        if p.suffix == ".sql":
            return "transcode", "seam calls inlined as DuckDB SQL"
        if relpath == SOURCES_YML.as_posix():
            return "rewrite", "source database line: target branch -> DuckDB catalog"
        return "copy", "model/test config and docs, unchanged"
    if relpath == SHOWCASE.as_posix():
        return "transcode", "every seam macro once; kept as a readable DuckDB render"
    if transport_dir(relpath):
        return "skip", TRANSPORT_REASON
    if p.parts[:2] == SEAM_DIR.parts:
        return "skip", "absorbed: every call was inlined, the moved project ships no macros"
    if relpath == "scripts/load_duckdb_sources.sh" or relpath.startswith("scripts/fixtures/"):
        return "copy", "the DuckDB fixture loader and its data"
    if relpath == "dbt_project.yml":
        return "rewrite", "macro-paths dropped"
    if relpath == "profiles.yml":
        return "rewrite", "one DuckDB output; the bigquery output and extension removed"
    if relpath == "Makefile":
        return "skip", "two-target Makefile; a one-target Makefile is emitted instead"
    if relpath == "packages.yml":
        return "skip", "declares no packages"
    if top == "scripts":
        return "skip", "two-target tooling (BigQuery runner, parity, portability guardrail, setup)"
    if top == "macros":
        return "skip", "not a seam macro file"
    if top == "examples":
        return "skip", "the hand-moved worked example of this procedure, not part of the warehouse"
    if p.suffix == ".md":
        return "skip", "documentation of the two-target project"
    return "skip", "project tooling / editor config, not part of the warehouse"


def resolve_manual(names, source_root):
    """Bare model names or paths -> relative model paths. Unknown -> MoveError."""
    models = {Path(f).stem: rel(f, source_root) for f in (source_root / "models").rglob("*.sql")}
    out = []
    for name in (n.strip() for n in names.split(",") if n.strip()):
        if name.endswith(".sql"):
            path = (source_root / name).resolve()
            if not path.is_file():
                raise MoveError(f"--manual: no such file {name}")
            out.append(rel(path, source_root))
        elif name in models:
            out.append(models[name])
        else:
            raise MoveError(f"--manual: no model named {name}")
    return list(dict.fromkeys(out))


def hand_move_text(relpath, original, seam, reason):
    """The placeholder written for a file that is moved by hand."""
    sites = []
    try:
        _, sites = seam.transcode(original)
        render_note = None
    except MoveError as e:
        render_note = str(e)
    macros = Counter()
    for *_, used in sites:
        macros.update(used)
    lines = [f"{{# HAND-MOVE: {relpath} was not transcoded ({reason}).",
             "   Replace this file with DuckDB SQL; the original is kept below, commented out.",
             "   Seam macros in this file: "
             + (", ".join(f"{n} x{c}" for n, c in sorted(macros.items())) or "none"),
             "   The DuckDB rendering of each call site (what the transcoder would write):"]
    for line, block, rendered, _ in sites:
        lines.append(f"     line {line}: {' '.join(block.split())}")
        lines.append(f"       -> {' '.join(rendered.split())}")
    if render_note:
        lines.append(f"   The transcoder could not render it: {render_note}")
    lines.append("#}")
    body = original.replace("#}", "# }")
    return "\n".join(lines) + "\n{# ORIGINAL (verbatim):\n" + body + ("" if body.endswith("\n") else "\n") + "#}\n", sites


def prepare_out(out, force):
    if out.exists() and any(out.iterdir()):
        if not force:
            raise FileExistsError(f"{out} exists; pass --force to replace it")
        if out == ROOT or ROOT.is_relative_to(out) or not (out / MARKER).exists():
            raise FileExistsError(f"{out} is not a directory this script wrote (no {MARKER}); "
                                  "refusing to delete it even with --force")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("written by scripts/move_to_duckdb.py; --force may delete this directory\n")


def move(source_root, out, manual):
    """Do the move. Returns a dict the report is written from."""
    seam = Seam(source_root)
    profile_name, output_name, duck_out, db_path = duckdb_output(source_root)
    catalog = str(duck_out.get("database") or db_path.stem)

    files = source_files(source_root)
    plan = {f: classify(f) for f in files}
    moved_scope = [f for f, (action, _) in plan.items() if action != "skip"
                   and Path(f).suffix in (".sql", ".yml", ".yaml")]
    source_findings = [x for f in moved_scope for x in detect(source_root / f, source_root)]
    rewritten_lines = set()

    inventory, per_file, hand_moves, rewrites = [], {}, {}, []
    per_macro, static = Counter(), Counter()
    manual_set = set(manual)
    # A file with an unresolved BigQuery-only construct is not transcoded either.
    blocked = {}
    for f in source_findings:
        if f[0] == SOURCES_YML.as_posix() and f[2] == "target_branch" and f[4].startswith("database:"):
            rewritten_lines.add((f[0], f[1]))
            continue
        if plan[f[0]][0] == "transcode":
            blocked.setdefault(f[0], []).append(f)

    for f in files:
        action, reason = plan[f]
        src, dst = source_root / f, out / f
        if action == "skip":
            inventory.append((f, "skipped", reason))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8") if src.suffix in (".sql", ".yml", ".yaml", ".sh") else None
        if action == "transcode":
            why = None
            if f in manual_set:
                why = "--manual"
            elif f in blocked:
                why = "BigQuery-only construct: " + ", ".join(sorted({x[2] for x in blocked[f]}))
            if why is None:
                try:
                    new, sites = seam.transcode(text)
                except MoveError as e:
                    why = f"transcoder: {e}"
            if why is not None:
                placeholder, _ = hand_move_text(f, text, seam, why)
                dst.write_text(placeholder, encoding="utf-8")
                hand_moves[f] = why
                inventory.append((f, "HAND-MOVE", why))
                continue
            dst.write_text(new, encoding="utf-8")
            n = Counter()
            for *_, used in sites:
                n.update(used)
            per_macro.update(n)
            static.update(seam.static_count(text))
            per_file[f] = sum(n.values())
            inventory.append((f, "transcoded", f"{per_file[f]} call site(s) inlined" if per_file[f]
                              else "no seam calls; copied through the transcoder unchanged"))
        elif action == "copy":
            shutil.copy2(src, dst)
            inventory.append((f, "copied", reason))
        elif action == "rewrite":
            if f == SOURCES_YML.as_posix():
                new, n = rewrite_sources(text, catalog)
                note = (f"`database:` target branch replaced by the literal catalog \"{catalog}\" "
                        f"(the stem of the profile's DuckDB path {db_path})") if n else \
                    "no target-branching `database:` line found; copied unchanged"
            elif f == "profiles.yml":
                new = emit_profile(profile_name, output_name, duck_out, db_path)
                note = (f"one output `{output_name}` (type duckdb) of profile `{profile_name}`; path is the "
                        f"source repo's DuckDB file by absolute path; extensions httpfs, iceberg only")
            else:
                new = rewrite_project(text)
                note = "macro-paths dropped (no macros ship); model config and test-paths kept"
            dst.write_text(new, encoding="utf-8")
            rewrites.append((f, note, unified(text, new, f)))
            inventory.append((f, "rewritten", reason))

    (out / "Makefile").write_text(emit_makefile(source_root, db_path), encoding="utf-8")
    inventory.append(("Makefile", "generated", "one-target Makefile: build, fixtures"))

    moved_findings = [x for f in moved_scope if (out / f).exists() for x in detect(out / f, out)]
    return dict(seam=seam, per_macro=per_macro, static=static, per_file=per_file,
                rewrites=rewrites, hand_moves=hand_moves, inventory=inventory,
                source_findings=source_findings, rewritten_lines=rewritten_lines,
                blocked=blocked, moved_findings=moved_findings, db_path=db_path, catalog=catalog)


# --------------------------------------------------------------------------- 6

def verify(out, source_root, db_path):
    """Build the moved project. Returns (ok, command, summary lines, message)."""
    log = []
    if not db_path.exists():
        cmd = ["bash", str(out / "scripts" / "load_duckdb_sources.sh")]
        log.append(f"$ DUCKDB_DB={db_path} {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=out, env=dict(os.environ, DUCKDB_DB=str(db_path)),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log.append(proc.stdout.rstrip().splitlines()[-1] if proc.stdout.strip() else "")
        if proc.returncode != 0:
            return False, log, [], f"fixture load failed (exit {proc.returncode})"
    dbt = source_root / ".venv" / "bin" / "dbt"
    cmd = [str(dbt), "build", "--target", "duckdb"]
    log.append(f"$ cd {out} && DBT_PROFILES_DIR={out} {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=out, env=dict(os.environ, DBT_PROFILES_DIR=str(out)),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = proc.stdout
    (out / "logs").mkdir(exist_ok=True)
    (out / "logs" / "move-verify.log").write_text(output, encoding="utf-8")
    lines = output.rstrip().splitlines()
    summary = [l for l in lines if l.startswith(("Finished ", "Processed:", "Summary:"))] or lines[-4:]
    processed = re.search(r"^Processed: (\d+) models \| (\d+) tests", output, re.M)
    total = re.search(r"^Summary: (\d+) total \| (\d+) success(.*)$", output, re.M)
    fails = [l for l in lines if re.search(r"\bfail(ed|ure|ures)?\b|\berror\b", l, re.I)]
    n_models = len(list((out / "models").rglob("*.sql")))
    problems = []
    if proc.returncode != 0:
        problems.append(f"dbt exit {proc.returncode}")
    if not total or total.group(1) != total.group(2) or total.group(3).strip():
        problems.append("summary is not N total | N success")
    if fails:
        problems.append(f"{len(fails)} line(s) mention fail/error, first: {fails[0].strip()}")
    if processed and int(processed.group(1)) != n_models:
        problems.append(f"processed {processed.group(1)} models but {n_models} were moved")
    msg = "; ".join(problems) if problems else (
        f"exit 0, {total.group(1)} total | {total.group(2)} success, no fail/error line, "
        f"{processed.group(1) if processed else '?'} models processed = {n_models} moved")
    return not problems, log, summary, msg


# --------------------------------------------------------------------------- report

def build_report(result, out, verification):
    seam = result["seam"]
    per_macro, per_file = result["per_macro"], result["per_file"]
    total = sum(per_macro.values())
    static_total = sum(result["static"].values())
    L = ["# MOVE-REPORT: bq_duckdb_experiments -> DuckDB only", "",
         f"Written by `scripts/move_to_duckdb.py` into `{out}`.", ""]

    L += ["## Absorbed by the macro layer", "",
          f"- Seam: {len(seam.defined)} macro definitions in {len(seam.files)} files under `{SEAM_DIR}/`: "
          f"{len(seam.dialect)} dialect macros (entry + `default__` + `bigquery__`), "
          f"{len(seam.selftests)} run-operation self-tests ({', '.join(seam.selftests)}; never called "
          "by a model, not moved).",
          f"- Call sites inlined: **{total}** across {sum(1 for v in per_file.values() if v)} files "
          f"({len(per_file)} files went through the transcoder).",
          f"- Cross-check: entry-macro names written inside `{{{{ }}}}` blocks of the transcoded files: "
          f"{static_total} ({'matches' if static_total == total else 'DOES NOT match'} the rendered count).",
          f"- Dialect macros never called by a moved file: "
          + (", ".join(n for n in seam.dialect if not per_macro[n]) or "none"), "",
          "| macro | call sites |", "|---|---:|"]
    L += [f"| `{n}` | {c} |" for n, c in sorted(per_macro.items(), key=lambda kv: (-kv[1], kv[0]))]
    L += ["", "| file | call sites |", "|---|---:|"]
    L += [f"| `{f}` | {c} |" for f, c in sorted(per_file.items())]
    L += [""]

    L += ["## Edited by hand (done by the script, here is the diff)", ""]
    for i, (f, note, diff) in enumerate(result["rewrites"], 1):
        L += [f"### {i}. `{f}`", "", note, "", "```diff", diff.rstrip() or "(no change)", "```", ""]
    L += [f"The profile's `path` is the SOURCE repository's `{result['db_path'].name}` by absolute path "
          f"(`{result['db_path']}`): the moved project reads the same fixture, and its build writes its "
          "models into the same file's `main` schema, replacing the source project's build output with "
          "the moved project's. Point `path` elsewhere to decouple them.", ""]

    L += ["## Cannot move at all", "",
          "Detector scope: every moved `.sql`/`.yml` file (models, tests, the showcase analysis, "
          "dbt_project.yml, profiles.yml), SQL comments and `{# #}` stripped, YAML comments stripped.", ""]
    src = result["source_findings"]
    resolved = [f for f in src if (f[0], f[1]) in result["rewritten_lines"]]
    outstanding = [f for f in src if (f[0], f[1]) not in result["rewritten_lines"]]
    L += [f"Source project: {len(src)} finding(s); {len(resolved)} resolved by the rewrites above, "
          f"{len(outstanding)} outstanding."]
    L += [f"- {fmt_finding(f)}  (resolved: rewrite 1)" for f in resolved]
    L += [f"- {fmt_finding(f)}  (OUTSTANDING)" for f in outstanding]
    mf = result["moved_findings"]
    L += ["", f"Moved project, re-scanned after the move: {len(mf)} finding(s)."]
    L += [f"- {fmt_finding(f)}" for f in mf]
    L += ["", "What the detector looks for (BigQuery-only, nothing in the seam covers it):", ""]
    L += [f"- `{rid}`: {desc}" for rid, desc in dict((r[0], r[1]) for r in DETECTOR_RULES).items()]
    L += ["", "Hand-move files (written as a HAND-MOVE placeholder, not transcoded): "
          + (str(len(result["hand_moves"])) if result["hand_moves"] else "none")]
    L += [f"- `{f}`: {why}" for f, why in result["hand_moves"].items()]
    L += [""]

    L += ["## Verification", ""]
    if verification is None:
        L += ["Not run (pass `--verify`)." if not result["hand_moves"] else
              "Not run: hand-move files are outstanding, the moved project cannot build yet.", ""]
    else:
        ok, log, summary, msg = verification
        L += ["```"] + log + summary + ["```", "", f"Result: {'PASS' if ok else 'FAIL'}: {msg}",
                                         f"Full output: `{out / 'logs' / 'move-verify.log'}`", ""]

    inventory = result["inventory"]
    counts = Counter(a for _, a, _ in inventory)
    transport = Counter(transport_dir(f) for f, _, _ in inventory if transport_dir(f))
    rows = [row for row in inventory if not transport_dir(row[0])]
    rows += [(f"{d}/** ({n} files)", "skipped", TRANSPORT_REASON) for d, n in sorted(transport.items())]
    L += ["## Inventory", "", "Not moved, and why:", ""]
    by_reason = {}
    for f, a, r in rows:
        if a == "skipped":
            by_reason.setdefault(r, []).append(f)
    L += [f"- {r}: " + ", ".join(f"`{f}`" for f in fs) for r, fs in by_reason.items()]
    L += ["", "| file | action | reason |", "|---|---|---|"]
    L += [f"| `{f}` | {a} | {r} |" for f, a, r in rows]
    L += ["", "Totals (every file counted): " + ", ".join(f"{a} {n}" for a, n in sorted(counts.items())), ""]
    return "\n".join(L)


# --------------------------------------------------------------------------- 4

DEMO_SQL = """\
-- Written by `scripts/move_to_duckdb.py --demo` and deleted again by it. Every
-- construct below is BigQuery-only and outside the seam.
{{ config(materialized='table', partition_by={'field': 'order_date', 'data_type': 'date'},
          cluster_by=['user_id'], external_location='gs://bucket/orders/*', submission='storage_write_api') }}
select
    o.order_id,
    cast(o.total as bignumeric)             as total_big,
    cast(null as geography)                 as shipped_to,
    o.items[safe_offset(0)]                 as first_item,
    pos
from {{ ref('stg_thelook__orders') }} as o
cross join unnest(o.items) as item with offset as pos
{% if target.type == 'bigquery' %}where true{% endif %}
;
create or replace table demo options(description = 'demo') as
select * from ml.predict(model demo_model, (select 1 as x));
begin
    create procedure demo_proc() begin select 1; end;
end;
"""


def git_status(root):
    try:
        return subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
    except OSError:
        return None


def demo(source_root):
    demo_path = source_root / DEMO_FILE
    if demo_path.exists():
        print(f"move_to_duckdb --demo: {DEMO_FILE} already exists; remove it first (exit 2)")
        return EXIT_CANNOT_START
    status_before = git_status(source_root)
    found = set()
    try:
        demo_path.write_text(DEMO_SQL, encoding="utf-8")
        print(f"demo: wrote {DEMO_FILE} with {len(DETECTOR_IDS)} injected construct kinds\n")
        findings = detect(demo_path, source_root)
        for f in findings:
            print("  " + fmt_finding(f))
        found = {f[2] for f in findings}
    finally:
        demo_path.unlink(missing_ok=True)
        print(f"\ndemo: removed {DEMO_FILE}")
    missed = [r for r in DETECTOR_IDS if r not in found]
    print(f"demo: detector found {len(DETECTOR_IDS) - len(missed)}/{len(DETECTOR_IDS)} construct kinds"
          + (f"; MISSED: {', '.join(missed)}" if missed else ""))

    # Re-check: the file is gone, the real models carry no finding from it, the tree is as found.
    rescan = [x for f in (source_root / "models").rglob("*.sql") for x in detect(f, source_root)]
    leftover = [f for f in rescan if DEMO_FILE.name in f[0]]
    status_after = git_status(source_root)
    clean = not demo_path.exists() and not leftover and status_before == status_after
    print(f"demo: re-check: {DEMO_FILE} exists={demo_path.exists()}, models/ findings now {len(rescan)}, "
          f"git status {'unchanged' if status_before == status_after else 'CHANGED'}")
    if missed or not clean:
        print("move_to_duckdb --demo: FAIL - the detector missed an injected construct or the tree changed (exit 1)")
        return EXIT_BUILD_FAILED
    print("move_to_duckdb --demo: the detector found every injected construct; tree left as found (exit 0)")
    return EXIT_MOVED


# --------------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(
        description="Move this BigQuery-targeted dbt project to a DuckDB-only one "
                    "(absorb the seam, rewrite the rest, report).",
        epilog="exit codes: 0 moved (built green with --verify); 1 build failed / --demo missed; "
               "2 could not start; 3 hand-move files outstanding")
    parser.add_argument("--out", help="directory to write the DuckDB-only project into")
    parser.add_argument("--verify", action="store_true",
                        help="dbt build --target duckdb inside --out and assert it is all green")
    parser.add_argument("--force", action="store_true", help="replace --out if this script wrote it before")
    parser.add_argument("--manual", metavar="A,B,C",
                        help="models to leave for a hand move (bare names or models/... paths); exits 3")
    parser.add_argument("--report", metavar="FILE", help="write the report here instead of <out>/MOVE-REPORT.md")
    parser.add_argument("--demo", action="store_true",
                        help="inject a model full of BigQuery-only constructs, prove the detector finds them all")
    parser.add_argument("--source", default=str(ROOT), help=argparse.SUPPRESS)
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(EXIT_CANNOT_START))
    source_root = Path(args.source).resolve()
    if not (source_root / "dbt_project.yml").is_file() or not (source_root / SEAM_DIR).is_dir():
        print(f"move_to_duckdb: no dbt_project.yml / {SEAM_DIR} at {source_root}; nothing to move (exit 2)")
        return EXIT_CANNOT_START
    if args.demo:
        return demo(source_root)
    if not args.out:
        print("move_to_duckdb: --out DIR is required (or --demo); nothing done (exit 2)")
        return EXIT_CANNOT_START
    if jinja2 is None:
        print(f"move_to_duckdb: jinja2 is not importable by {sys.executable}; run with an interpreter "
              "that has it (`uv sync` installs it from the dev group); nothing done (exit 2)")
        return EXIT_CANNOT_START

    out = Path(args.out).resolve()
    try:
        manual = resolve_manual(args.manual, source_root) if args.manual else []
        prepare_out(out, args.force)
        result = move(source_root, out, manual)
    except (MoveError, FileExistsError) as e:
        print(f"move_to_duckdb: {e}; nothing moved (exit 2)")
        return EXIT_CANNOT_START

    verification = None
    if args.verify and not result["hand_moves"]:
        verification = verify(out, source_root, result["db_path"])
    report = build_report(result, out, verification)
    report_path = Path(args.report).resolve() if args.report else out / "MOVE-REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(report)

    n_calls = sum(result["per_macro"].values())
    where = f"{out} (report: {report_path})"
    if result["hand_moves"]:
        print("Outstanding hand-move files:")
        for f in result["hand_moves"]:
            print(f"  {out / f}")
        print(f"move_to_duckdb: moved into {where}; {len(result['hand_moves'])} hand-move file(s) "
              f"outstanding, {n_calls} call sites inlined elsewhere (exit 3)")
        return EXIT_HAND_MOVE
    if verification is not None:
        ok, _, _, msg = verification
        if not ok:
            print(f"move_to_duckdb: moved into {where}, but the build FAILED: {msg} (exit 1)")
            return EXIT_BUILD_FAILED
        print(f"move_to_duckdb: moved into {where}; {n_calls} call sites inlined; build green: {msg} (exit 0)")
        return EXIT_MOVED
    print(f"move_to_duckdb: moved into {where}; {n_calls} call sites inlined; not built (no --verify) (exit 0)")
    return EXIT_MOVED


if __name__ == "__main__":
    sys.exit(main())
