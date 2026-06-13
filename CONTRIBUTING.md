# Contributing

Thanks for considering a contribution. This repository is the **reference
implementation** of the AIMEM Bundle Format
([draft-vu-aimem-bundle-01](spec/draft-vu-aimem-bundle-01.md)). Its
purpose is twofold:

1. Show implementers what conformance looks like in code.
2. Provide a black-box test corpus that any AIMEM-Bundle-claiming
   implementation can run against itself.

## Independent implementations are explicitly welcome

The single most useful contribution right now is **a second implementation
from a vendor or research group not affiliated with MemoryAI**. The IETF
draft cannot advance from Independent Submission to Working Group track
without ≥2 independent Consumer/Producer pairs.

If you ship one — even a partial Consumer — please:

1. Open a `2nd-implementer` issue with the URL.
2. Run the conformance corpus and post results.
3. Note any spec gaps you found while implementing.

Co-authorship of the next draft revision (`-02`) is on the table for any
implementer who lands a working independent Consumer.

## Scope

This repo accepts:

- Bug fixes in the bundle parser, exporter, importer, or HTTP layer.
- Conformance corpus additions (more `valid/`, `invalid/`, `edge/`
  bundles that exercise spec corners).
- Documentation improvements to the spec or README.
- Adapter examples (e.g. `examples/letta_bridge.py`,
  `examples/mem0_bridge.py`) that show how to wrap an existing memory
  system in the Bundle interface.

This repo does **not** accept:

- Recall ranking, reasoning, or "smart" retrieval logic. Those are
  intentionally out of scope per spec §1. If you want a production
  recall engine, run [MemoryAI](https://memoryai.dev/) or another
  AIMEM-Bundle-compatible implementation.
- Vendor-specific extensions to the wire format. New record types or
  fields must go through the spec's `x-` extension prefix or wait for a
  draft revision.

## Filing a bug

Use the `bug` issue template. Include:

- Reproducer (small bundle JSON, curl command, or pytest snippet).
- Expected vs actual behaviour.
- Spec section number that you believe codifies the expected behaviour.

## Filing a spec gap

Use the `spec-gap` issue template. Spec gaps drive the next draft
revision. Be specific: "section 3.2 doesn't constrain X" rather than
"unclear".

## Pull requests

- One concern per PR. Bundle parser fixes, conformance additions, and
  HTTP route changes go in separate PRs.
- All PRs must pass `pytest` and the conformance suite.
- Use `Signed-off-by` per the [Developer Certificate of Origin](https://developercertificate.org/) on every commit.
- Squash merge into `main`.

## Development setup

```bash
git clone https://github.com/memoryai-dev/aimem-reference
cd aimem-reference
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run the unit tests (no DB needed)
PYTHONPATH=. pytest tests/test_bundle.py -v

# Run conformance corpus against the reference server
docker compose up -d
python tests/conformance/conformance.py run http://localhost:9420 <api-key>
```

## License of contributions

By submitting a contribution, you agree that it will be released under
the [Apache License 2.0](LICENSE), the same license as the rest of the
project.
