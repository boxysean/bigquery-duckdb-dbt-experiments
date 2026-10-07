#!/usr/bin/env python3
"""Can the materialised BigQuery build run here? A read-only diagnosis.

    python3 scripts/bq_preflight.py                 # diagnose; writes nothing
    python3 scripts/bq_preflight.py --create        # ... and create the target dataset if missing
    python3 scripts/bq_preflight.py --dataset experiments_x   # another dataset in the project

scripts/run_bq.sh runs it with --create before `dbt build --target bigquery`, so a target
that cannot be written ends in a sentence naming the permission to grant, not in a driver
error. Without --create it writes nothing; with it, the one thing it may write is the
target dataset (`datasets.insert`, location US, attempted once).

Checks, in order, printed in the scripts/check_env.sh style (`  ok    ...` / `  FAIL  ...`):
  1. an access token is obtained from the service-account key;
  2. `datasets.get` on <project>.<dataset> (location, creation time, OWNER);
  3. `jobs.query` of `SELECT 1`, which proves bigquery.jobs.create (0 bytes, bills nothing);
  4. `tables.list` on the dataset, when it exists, which proves it can be read.

Target, from the repository's convention (profiles.yml): project BQ_PROJECT (default
coreychimpbot), dataset experiments_<DBT_ENV> (DBT_ENV default dev). Key: BQ_KEYFILE, else
GOOGLE_APPLICATION_CREDENTIALS when that is a service-account JSON. Only the key's
client_email is ever printed. The token comes from scripts/parity.py's access_token(),
the one JWT exchange in this repository.

Exit status. Neither 1 nor 2 is a build failure: no build has been started.
  0  ready: the dataset exists, a job can be created, the dataset is readable.
  1  PREFLIGHT UNAVAILABLE: it could not run (no service-account key, no openssl, bad
     credentials, network, an unexpected HTTP status). Nothing is known about the target;
     the caller should fall through to dbt unchanged.
  2  NAMED BLOCKER: the dataset is missing and was not (or could not be) created, a job
     cannot be created, or the dataset cannot be read. The diagnosis, BigQuery's own
     message and a "what to grant" block have been printed.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://bigquery.googleapis.com/bigquery/v2/projects/{project}"
LOCATION = "US"  # profiles.yml > bigquery > location


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


def _access_token(key: str) -> str:
    # One implementation of the JWT exchange in this repository: parity.py's.
    spec = importlib.util.spec_from_file_location(
        "parity", Path(__file__).resolve().parent / "parity.py")
    parity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parity)
    return parity.access_token(key)


def _key_path() -> str | None:
    key = os.environ.get("BQ_KEYFILE")
    if key:
        return key
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac and Path(gac).is_file():
        try:
            with open(gac) as fh:
                if json.load(fh).get("type") == "service_account":
                    return gac
        except (OSError, ValueError):
            return None
    return None


def _call(token: str, url: str, body: dict | None = None):
    """(status, parsed JSON). HTTP errors are returned, not raised; network errors raise."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data)
    req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": {"message": raw[:400]}}


def _quote(status: int, payload: dict) -> str:
    err = payload.get("error", {}) if isinstance(payload, dict) else {}
    reasons = ",".join(x.get("reason", "") for x in err.get("errors", []) if x.get("reason"))
    reason = f" reason={reasons}" if reasons else ""
    return f'HTTP {status}{reason}: "{err.get("message", "")}"'


def _grant_block(project: str, dataset: str, email: str) -> None:
    member = f"serviceAccount:{email}"
    print(f"""
what to grant (to {email}):
  # roles/bigquery.jobUser supplies bigquery.jobs.create
  gcloud projects add-iam-policy-binding {project} --member={member} --role=roles/bigquery.jobUser
  # roles/bigquery.dataEditor supplies bigquery.datasets.create, and inside the dataset
  # bigquery.tables.create / .updateData / .get and bigquery.datasets.get / .update
  gcloud projects add-iam-policy-binding {project} --member={member} --role=roles/bigquery.dataEditor
gcloud is not installed on this box; the console route is BigQuery -> Create dataset
(id {dataset}, location {LOCATION}), plus IAM -> grant the two roles above to {email}.""")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--create", action="store_true",
                    help="create the target dataset (location US) if it is missing")
    ap.add_argument("--project", default=os.environ.get("BQ_PROJECT", "coreychimpbot"))
    ap.add_argument("--dataset",
                    default="experiments_" + os.environ.get("DBT_ENV", "dev"))
    args = ap.parse_args(argv)
    project, dataset = args.project, args.dataset
    base = API.format(project=project)

    print(f"bigquery preflight: target {project}.{dataset} (location {LOCATION})")

    key = _key_path()
    if not key or not Path(key).is_file():
        fail("no service-account key: set BQ_KEYFILE (or GOOGLE_APPLICATION_CREDENTIALS to a "
             "service-account JSON). Preflight unavailable.")
        return 1
    if shutil.which("openssl") is None:
        fail("openssl not found on PATH; it signs the token request. Preflight unavailable.")
        return 1
    try:
        with open(key) as fh:
            email = json.load(fh)["client_email"]
    except (OSError, ValueError, KeyError) as e:
        fail(f"{key} is not a readable service-account key ({type(e).__name__}). "
             "Preflight unavailable.")
        return 1

    # 1. token ------------------------------------------------------------------
    try:
        token = _access_token(key)
    except Exception as e:  # noqa: BLE001
        fail(f"access token for {email}: {type(e).__name__}: {e}. Preflight unavailable.")
        return 1
    ok(f"access token obtained for {email}")

    blockers: list[str] = []
    try:
        # 2. datasets.get ---------------------------------------------------------
        status, ds = _call(token, f"{base}/datasets/{dataset}")
        exists = False
        if status == 200:
            exists = True
            created = datetime.datetime.fromtimestamp(
                int(ds.get("creationTime", 0)) / 1000, datetime.timezone.utc)
            owners = [a.get("userByEmail") or a.get("groupByEmail") or a.get("specialGroup")
                      or a.get("domain") or "?"
                      for a in ds.get("access", []) if a.get("role") == "OWNER"]
            ok(f"dataset {project}.{dataset} exists: location {ds.get('location')}, created "
               f"{created:%Y-%m-%d %H:%M:%SZ}, OWNER {', '.join(owners) or '(none listed)'}")
        elif status == 404:
            fail(f"dataset {project}.{dataset} not found ({_quote(status, ds)})")
            if not args.create:
                fail(f"creating it needs bigquery.datasets.create; not attempted. Re-run with "
                     f"--create, or create it in the console (id {dataset}, location {LOCATION})")
                blockers.append("bigquery.datasets.create (untested: --create was not passed)")
            else:
                st, ins = _call(token, f"{base}/datasets", {
                    "datasetReference": {"projectId": project, "datasetId": dataset},
                    "location": LOCATION})
                if st == 200:
                    exists = True
                    ok(f"dataset {project}.{dataset} created (location {ins.get('location')})")
                elif st == 403:
                    fail(f"datasets.insert refused, {_quote(st, ins)}; the missing permission is "
                         f"bigquery.datasets.create on project {project}")
                    blockers.append("bigquery.datasets.create (refused)")
                else:
                    fail(f"datasets.insert: {_quote(st, ins)}. Preflight unavailable.")
                    return 1
        elif status == 403:
            fail(f"datasets.get on {project}.{dataset} refused, {_quote(status, ds)}; "
                 "the missing permission is bigquery.datasets.get")
            blockers.append("bigquery.datasets.get (refused)")
        else:
            fail(f"datasets.get on {project}.{dataset}: {_quote(status, ds)}. "
                 "Preflight unavailable.")
            return 1

        # 3. jobs.query SELECT 1 ----------------------------------------------------
        status, job = _call(token, f"{base}/queries", {
            "query": "SELECT 1", "useLegacySql": False, "location": LOCATION})
        if status == 200:
            ok(f"jobs.query SELECT 1 ran (bigquery.jobs.create held; processed "
               f"{job.get('totalBytesProcessed', '?')} bytes, billed "
               f"{job.get('totalBytesBilled', '0')})")
        elif status == 403:
            fail(f"jobs.query refused, {_quote(status, job)}; the missing permission is "
                 f"bigquery.jobs.create on project {project}")
            blockers.append("bigquery.jobs.create (refused)")
        else:
            fail(f"jobs.query: {_quote(status, job)}. Preflight unavailable.")
            return 1

        # 4. tables.list ------------------------------------------------------------
        if exists:
            status, tl = _call(token, f"{base}/datasets/{dataset}/tables?maxResults=1000")
            if status == 200:
                ok(f"tables.list on {project}.{dataset}: {tl.get('totalItems', 0)} relation(s), "
                   "the dataset is readable")
            elif status == 403:
                fail(f"tables.list refused, {_quote(status, tl)}; the missing permission is "
                     "bigquery.tables.list")
                blockers.append("bigquery.tables.list (refused)")
            else:
                fail(f"tables.list: {_quote(status, tl)}. Preflight unavailable.")
                return 1
    except (urllib.error.URLError, OSError, ValueError) as e:
        fail(f"network: {type(e).__name__}: {e}. Preflight unavailable.")
        return 1

    if blockers:
        print(f"\nNAMED BLOCKER: {project}.{dataset} cannot be built by {email}; "
              f"needed: {', '.join(blockers)}. No build was started.")
        _grant_block(project, dataset, email)
        return 2
    print(f"ready: {project}.{dataset} exists, a job can be created and the dataset is readable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
