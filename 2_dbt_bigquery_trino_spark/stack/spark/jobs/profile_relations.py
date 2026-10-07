"""Spark, the DOWNSTREAM consumer: read what dbt built on Trino, and profile it.

Reads /data/interop/spec.json (written by scripts/spark_interop.py: every relation dbt
built, with each column's kind) and computes, in Spark SQL, the same per-column profile
the driver computes in Trino SQL. Writes /data/interop/spark.json. A relation Spark
cannot read (typically a Trino view whose SQL is not Spark SQL) is recorded with the
error instead of a profile; deciding whether that is a failure is the driver's job.

    docker compose run --rm spark profile_relations.py
"""
import json

from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("profile_relations").getOrCreate()
spark.sparkContext.setLogLevel("ERROR")


def q(name):
    return "`" + name.replace("`", "``") + "`"


def exprs(col, kind):
    c = q(col)
    if kind == "num":
        return [f"count({c})", f"cast(sum({c}) as string)"]
    if kind == "dbl":
        return [f"count({c})", f"sum({c})"]
    if kind == "str":
        return [f"count({c})", f"count(distinct {c})", f"sum(length({c}))"]
    if kind == "bool":
        return [f"count({c})", f"sum(case when {c} then 1 else 0 end)"]
    if kind == "date":
        return [f"count({c})", f"count(distinct {c})", f"cast(min({c}) as string)", f"cast(max({c}) as string)"]
    if kind == "ts":
        micros = f"unix_micros(cast({c} as timestamp))"
        return [f"count({c})", f"count(distinct {c})", f"min({micros})", f"max({micros})"]
    if kind == "array":
        return [f"count({c})", f"sum(case when {c} is not null then size({c}) end)"]
    return [f"count({c})"]  # row / other


spec = json.load(open("/data/interop/spec.json"))
out = {"spark_version": spark.version, "relations": {}}
for rel in spec["relations"]:
    name = f"lake.{spec['schema']}.{rel['name']}"
    select = ["count(*)"]
    for col in rel["columns"]:
        select += exprs(col["name"], col["kind"])
    try:
        row = spark.sql(f"select {', '.join(select)} from {name}").collect()[0]
        values = [None if v is None else (float(v) if isinstance(v, float) else str(v)) for v in row]
        out["relations"][rel["name"]] = {"ok": True, "values": values,
                                          "spark_schema": spark.table(name).schema.simpleString()}
    except Exception as e:  # noqa: BLE001 - every failure is data here
        first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        out["relations"][rel["name"]] = {"ok": False, "error": f"{type(e).__name__}: {first[:300]}"}
    print(f"  {'read' if out['relations'][rel['name']]['ok'] else 'FAIL':<4} {name}")

json.dump(out, open("/data/interop/spark.json", "w"), indent=1)
