# caseproof

**Certify differential-test case counts by content, not by loop iterations.**
`caseproof` hashes every case, reports how many samples are actually distinct,
and refuses to certify a claim whose declared count is inflated by duplicates.

Upstream: none

A differential test that says *"2000 random documents, 0 mismatches"* can be
entirely vacuous: if the generator resets its seed inside the function, all
2000 iterations produce the same document. `caseproof` turns "N cases" into a
falsifiable claim with a sha256 ledger, a worst-key witness, and per-input-class
floors. It is a small, dependency-free library plus a CLI.

## Why this exists

On 2026-11-01 a published lab claimed *"2000 random grouped documents, 0
mismatch"*. Independent review found the document constructor reseeded
`random.Random(4321)` on every call: 2000 iterations produced **one** 557-byte
document, and only ~10 effective combinations were exercised — a nominal 200x
overstatement. The same audit found a second repo whose 2206 cases really were
2206 unique samples, and that one held up.

Counting loop iterations cannot tell those two repos apart. Counting content
hashes can. The demo in `examples/seed_reset.py` reproduces the first failure
mode exactly and shows the fixed generator reaching 2000/2000 unique.

## Install

No third-party runtime dependencies (Python >= 3.8).

```bash
python3 -m venv .venv --system-site-packages
. .venv/bin/activate
python3 -m pip install -e . --no-build-isolation
python3 -m unittest discover -s tests -v
```

`--system-site-packages` keeps setuptools available in the venv, so the
editable install works offline (no build-isolation download). On a machine with
internet, `python3 -m pip install -e .` is enough. If you prefer not to install,
run everything from the repository root; `caseproof/` is importable in place.

## Three commands

```bash
python3 examples/seed_reset.py
python3 -m caseproof /tmp/cases.jsonl --min-unique 4 --require-label ascii=2
python3 -m unittest discover -s tests -v
```

Real output of the demo on this machine (CPython 3.12.3):

```
buggy generator (seed reset inside):
  declared 2000  unique 1  ratio 0.0500%
  worst key repeated 2000x
fixed generator (seed created once):
  declared 2000  unique 2000  ratio 100.0000%
certification: REJECTED
  - unique 1 < required 1000 (declared 2000, 0.050% distinct)
  - worst key sha256:044682d6e5379870 repeated 2000x (644 bytes): {'title': 'ttttt', ...}
```

CLI on four JSON lines where `{"a":1}` appears twice:

```
declared cases : 4
unique cases   : 3 (75.000%)
duplicate events: 1
most repeated keys:
  sha256:6eb2fa289851c341       2x  {'a': 1}
verdict        : REJECTED
  - unique 3 < required 4 (declared 4, 75.000% distinct)
  - worst key sha256:6eb2fa289851c341 repeated 2x (9 bytes): {'a': 1}
  - label 'ascii': unique 0 < required 2
```

## API

```python
from caseproof import CaseLedger

ledger = CaseLedger()
for doc in documents:
    ledger.add(doc, label="wide-table")      # label is optional

ledger.total          # declared cases
ledger.unique         # distinct sha256 keys
ledger.duplicate_events
ledger.duplicates()   # worst-first, each with digest/count/key size/sample

report = ledger.certify(min_unique=1000, per_label={"wide-table": 250})
report["certified"]   # bool
report["failures"]    # human-readable reasons, including the worst key

ledger.require(min_unique=1000)   # raises CaseCountError when short
```

One-shot helper: `certify_cases(cases, min_unique=1000)`.

Use `key=` when your objects are not canonically JSON/pickle serialisable:

```python
ledger = CaseLedger(key=lambda case: case.canonical_bytes())
```

### What counts as distinct

The default key is content-addressed and type-tagged:

| input | key prefix | notes |
|---|---|---|
| `bytes` / `bytearray` | `b:` | raw bytes |
| `str` | `s:` | UTF-8 (surrogatepass) |
| JSON-able value | `j:` | `sort_keys=True`, compact separators |
| other pickle-able value | `p:` | protocol 4 fallback |

`1`, `1.0`, `True`, `"1"` and `b"1"` are five different keys. Dict insertion
order does not create a new key; `0.0` and `-0.0` do. `NaN` is stable.

## CLI

```
python3 -m caseproof FILE.jsonl [--wrapped] [--min-unique N]
                        [--require-label LABEL=N ...] [--top K]
                        [--json-out PATH] [--quiet]
```

* Each line is one JSON case; `--wrapped` expects `{"case": ..., "label": ...}`.
* Exit code `0` = every floor met, `1` = rejected (with reasons on stdout),
  `2` = unreadable/invalid input.
* `--json-out` writes the full report (including `top_duplicates`,
  `requirements`, `certified`, `failures`) for CI artifacts.

## What the report proves, and what it does not

It proves: the declared count, the number of distinct content keys, the
multiplicity of the worst repeated key, and (optionally) distinct counts per
label. Those are exact integers from a sha256 ledger, not estimates.

It does **not** prove semantic coverage. A thousand distinct inputs can still
miss a branch, and a single input can exercise many branches. `caseproof`
answers the narrower question that published claims usually get wrong: *were
there really N independent samples?* Pair it with branch coverage or mutation
tests when coverage is the claim.

`pickle` is only a fallback. For objects whose pickle is not canonical (sets,
custom `__reduce__`), pass an explicit `key=` function, otherwise two logically
equal cases may count as distinct.

## Tests

```bash
python3 -m unittest discover -s tests -v
# Ran 21 tests in 0.397s
# OK
```

The suite covers type-tag separation, dict-order canonicalisation, `-0.0`
vs `0.0`, non-ASCII strings, byte payloads, per-label floors, custom keys,
error messages, empty ledgers, the seed-reset reproduction (1/2000), the fixed
generator (2000/2000), and four CLI paths including invalid JSON and JSON output.

## 本轮创新

**首次把「差分用例数」当作可证伪声明来认证**：对每个样本做内容寻址 sha256
去重，保留 worst-key 见证，并支持按输入类设下限；在 seed-reset 场景把宣称
2000 组实测揭穿为 1 组（2000× 虚高），而同一工具对真正 2000 组独立的生成器
给出 2000/2000。与「逐 hunk 消融」（归因补丁收益）不同，这一层管的是样本
独立性本身，台账此前没有该判据。

Not a re-run of another upstream: `caseproof` has no upstream and is not a
benchmark wrapper. It is the check that several earlier labs needed and did not
have.

## License

MIT. See `LICENSE`.
