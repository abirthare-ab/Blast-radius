# Blast Radius entry

Select tests using dependencies measured on the competition's pinned SQLGlot
commit, then minimize the recorded worker cost using longest-job-first packing
for each worker count from one through eight.

## Design

`build_map.py` executes the pristine pinned test suite and records:

- test contexts for executed source lines;
- files read by each test, including class-wide fixture setup;
- concrete runtime classes and their bases, including inherited constructors.

The selector applies each incoming diff in memory. It selects consumers of changed
statements or class attributes. Uncertain edits fall back to all tests. Function
signature, default, decorator, encoding and module-initialization changes receive
conservative handling. Class-level edits receive an isolated import check before
class-consumer narrowing. AST-identical edits retain any source-reading tests.

No patch IDs, sample answers, mutation-answer tables, or competitor code are used.
The compressed dependency map is source-derived data committed as a normal Git
file. `sample/answers.json` is exclusively an offline evaluator input and is not
copied into the container.

## Reproduce

With the official starter's `sample/` directory alongside the Makefile, build and
run the public sample (Docker with Buildx):

```sh
make sample
python3 test_selector.py
```

The image's Python base is pinned by digest. Its only build-time download is the
permitted SQLGlot repository archive at
`eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. The runtime has no network and writes
no files. The optional import checks are child Python processes whose CPU time
counts toward the score.

The shipped map is generated on Linux amd64 with the same pinned Python image.
To reproduce it (allow several minutes for tracing):

```sh
mkdir -p map-output
docker buildx build --platform linux/amd64 --load -f Dockerfile.map -t blast-map .
docker run --rm --platform linux/amd64 --network none -v "$PWD/map-output:/out" blast-map
cp map-output/dependencies.json.gz .
```

Alternatively, install `requirements-map.txt` in Python 3.13 and run:

```sh
python build_map.py /path/to/pristine/sqlglot dependencies.json.gz
```

During instrumentation only, process-pool jobs run synchronously so their lines
retain the originating test context. Arguments and results still undergo pickle
round-trips, capturing serialization dependencies. This does not modify upstream
source. `SCORING.md` contains the official metric and runtime restrictions.

## Validation limits

The public sample and independent synthetic mutations are development checks,
not proof of correctness on hidden patches. Dynamic coverage cannot establish
complete dependency soundness for arbitrary Python edits. The final hidden score
must be measured by the competition.
