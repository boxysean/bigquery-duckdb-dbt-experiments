#!/usr/bin/env bash
#
# Download the two jars Spark needs to use the shared Iceberg REST catalog on S3, into
# stack/spark/jars/ (git-ignored), and verify their sha256. Idempotent.
#
#   iceberg-spark-runtime-4.0_2.13-1.10.0.jar   Iceberg for Spark 4.0 / Scala 2.13
#   iceberg-aws-bundle-1.10.0.jar               S3FileIO (the AWS SDK, shaded)
#
# Downloaded on the host and mounted, rather than `--packages` at job start, so every
# Spark job starts without network access and with exactly these bytes. Tries Maven
# Central first, then Google's Maven Central mirror (Maven Central rate-limits shared
# egress IPs with HTTP 429).
set -euo pipefail

dest="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/stack/spark/jars"
mkdir -p "$dest"

jars=(
  "iceberg-spark-runtime-4.0_2.13 0480f1248e0a8b50ae2a730d7ad3e1a727351c362ca63f4a0c35182087a49323"
  "iceberg-aws-bundle 172370cfc32a5f1ae5399b210e86fc04a366dc29a112d97ac8ffc74df7525596"
)
mirrors=(
  "https://repo1.maven.org/maven2"
  "https://maven-central.storage-download.googleapis.com/maven2"
)
version=1.10.0

for entry in "${jars[@]}"; do
    read -r artifact sha <<<"$entry"
    file="$artifact-$version.jar"
    if [ -f "$dest/$file" ] && echo "$sha  $dest/$file" | sha256sum -c --status; then
        echo "ok    $file (already present, sha256 verified)"
        continue
    fi
    got=0
    for m in "${mirrors[@]}"; do
        url="$m/org/apache/iceberg/$artifact/$version/$file"
        if curl -sSfL --retry 3 -o "$dest/$file.part" "$url"; then
            got=1
            break
        fi
        echo "      $url failed, trying the next mirror" >&2
    done
    if [ "$got" -ne 1 ]; then
        echo "FAIL  could not download $file from any mirror" >&2
        exit 1
    fi
    if ! echo "$sha  $dest/$file.part" | sha256sum -c --status; then
        echo "FAIL  $file: sha256 mismatch (expected $sha)" >&2
        rm -f "$dest/$file.part"
        exit 1
    fi
    mv "$dest/$file.part" "$dest/$file"
    echo "ok    $file (downloaded, sha256 verified)"
done
