# Blast Radius precision candidate

This candidate narrows changed-source statements using AST structure and records
actual readers of existing literal uppercase class settings. Reflection through
literal strings, shared setup, import-time initialization, function and lambda
headers, and incomplete maps retain conservative handling. Unknown edits keep
all tests. It does not contain patch IDs, sample answers, or edit-answer tables.

This is an experimental improvement over the published 351.3-second entry. See
validation.json for measured public-sample results. Public-sample results are NOT
hidden leaderboard predictions; no under-150 hidden score has been demonstrated.

## Container

Build Dockerfile for linux/amd64. The runtime reads /data/tests.json and patches
from /data/commits, prints the specified JSONL, and needs no writable source tree
or network. Dependencies are precomputed from the pinned pristine SQLGlot commit.

## Map reproduction

Dockerfile.map installs pinned test dependencies and downloads the pinned source.
Run its default command to produce a baseline map. Then run the attribute pass:

    docker run --rm --platform linux/amd64 --network none \
      -v "$PWD/map-output:/out" --entrypoint python blast-map \
      /app/build_attributes.py /opt/sqlglot /out/attributes.json.gz
    python merge_maps.py map-output/dependencies.json.gz \
      map-output/attributes.json.gz dependencies.json.gz /path/to/pristine/sqlglot

Both map runs must pass. The attribute pass allows extra test time for tracing;
that offline timeout does not change the submission's runtime limits.

## Validation

    python -m unittest test_selector test_precision

Use the official sample and score.py for simulated cost. CPU seconds must also be
measured inside the restricted container. Dynamic coverage is not a proof of
correctness for arbitrary Python edits. Attribute narrowing is disabled unless
its complete baseline suite passed and covered the original collected tests.

## Measured results

The same public sample improved from 182.08334 to 172.066121 seconds including median CPU. All three restricted container runs had zero sample misses. Thirteen unit checks and seven independent mutation checks passed. No hidden score exists for this candidate. The known submitted score remains 351.3 seconds.
