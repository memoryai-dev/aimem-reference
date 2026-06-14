---
title: "Memory Interchange Bundle Format for AI Agents"
abbrev: "AIMEM Bundle"
docname: draft-vu-aimem-bundle-01
category: info
stream: independent
ipr: trust200902
area: Applications
workgroup: Independent Submission
keyword:
  - ai
  - memory
  - interchange
  - portability
  - agents

stand_alone: yes
pi:
  toc: yes
  sortrefs: yes
  symrefs: yes

author:
 -
    fullname: Vu Duc Minh
    organization: MemoryAI
    email: minh@memoryai.dev
    country: Vietnam

normative:
  RFC2119:
  RFC4648:
  RFC8259:
  RFC8141:
  RFC8174:
  RFC8785:
  RFC9052:
  RFC9110:

informative:
  RFC7807:
  RFC8615:
  W3C-DID:
    target: https://www.w3.org/TR/did-core/
    title: Decentralized Identifiers (DIDs) v1.0
    author:
     -
        fullname: W3C DID Working Group
    date: 2022-07
  GDPR-A17:
    target: https://eur-lex.europa.eu/eli/reg/2016/679/oj
    title: "Regulation (EU) 2016/679 (GDPR), Article 17 — Right to erasure"
    date: 2016-04
  AIMEM-REF:
    target: https://github.com/aimem-protocol/aimem-reference
    title: "AIMEM Bundle Reference Implementation (Apache-2.0)"
    author:
     -
        fullname: Vu Duc Minh
    date: 2026-06

--- abstract

This document specifies a vendor-neutral interchange format for the
persistent memory of AI agents — preferences, decisions, identity claims,
pitfalls, and procedures that an agent accumulates across sessions.

The format is a self-contained JSON Bundle with explicit conformance
levels (Producer, Consumer, Bidirectional). Implementations MAY accompany
the Bundle with an HTTP Profile that exposes export and import endpoints.

The goal is to allow a user's "agent brain" to move between cloud
services, on-premise installations, and third-party implementations
without lock-in, in a manner that interoperates with existing
right-to-erasure obligations such as {{GDPR-A17}}.

This document is self-contained: all schema fields normatively required
by Producers and Consumers are defined inline. An informative reference
implementation is cited in {{AIMEM-REF}}.

--- middle

# Introduction

In 2026, multiple commercial LLM platforms ship memory features that
persist user identity, preferences, and prior decisions across sessions.
Each platform serializes that memory in a vendor-specific schema,
producing lock-in for the user and friction for downstream tooling such
as audit, compliance, and migration.

This document defines the **AIMEM Bundle Format**, an interchange
container that decouples three concerns:

| Layer      | Concern                                            |
| ---------- | -------------------------------------------------- |
| Encoding   | What agent memory looks like on disk               |
| Transport  | How memory bundles move between systems            |
| Reasoning  | How an LLM uses recalled memory                    |

This specification standardises only the encoding and transport layers.
The reasoning layer is left to each implementation, in keeping with the
HTTP precedent of standardising the wire while leaving rendering to
browsers.

## Requirements Language

{::boilerplate bcp14-tagged}

## Terminology {#terminology}

Bundle:
: A self-contained JSON document representing the complete or partial
  agent memory of one Tenant.

Tenant:
: The principal who owns a Bundle's contents, identified by an
  implementation-defined identifier (URI, UUID, or DID per {{W3C-DID}}).

Producer:
: An implementation that serialises agent memory into a Bundle.

Consumer:
: An implementation that ingests a Bundle and reconstructs the agent
  memory in its own storage.

Bidirectional:
: An implementation that is both Producer and Consumer for the same
  Bundle scope.

Chunk:
: An atomic memory record. A Bundle contains zero or more Chunks.

DNA-class memory:
: A Chunk whose `memory_type` is one of `preference`, `decision`,
  `identity`, `pitfall`, or `procedure`. DNA-class memory MUST NOT be
  silently decayed or deleted by any implementation; see {{security}}.

Producer Namespace:
: An opaque, lower-case ASCII identifier (1-63 chars, `[a-z0-9-]`) that
  uniquely identifies the originating Producer instance. See
  {{chunk-id}}.

# Bundle Format {#bundle-format}

A Bundle is a UTF-8 JSON document conforming to {{RFC8259}}.

## Required Envelope

A Bundle MUST contain the following top-level fields:

~~~ json
{
  "format": "aimem-bundle",
  "version": "1",
  "producer": "memoryai-prod",
  "tenant_id": "11111111-1111-1111-1111-111111111111",
  "exported_at": "2026-06-12T10:00:00Z",
  "scope": "FULL",
  "checksum": "sha256:...",
  "chunks": [],
  "edges": [],
  "entities": [],
  "chunk_entities": []
}
~~~

The `format` field MUST be the string `"aimem-bundle"`. The legacy value
`"memoryai-bundle"` MAY be accepted by Consumers for backwards
compatibility with implementations published before this revision.

The `version` field MUST be `"1"` for this specification.

The `producer` field MUST be a Producer Namespace (see {{chunk-id}}).
It identifies the implementation that emitted the Bundle and is the
namespace under which `chunk.id` values are interpreted.

The `tenant_id` field MUST be either a UUID per RFC 4122 or a URI
(including a DID per {{W3C-DID}}).

The `exported_at` field MUST be an ISO-8601 timestamp in UTC.

The `scope` field MUST be one of `"FULL"`, `"DNA_ONLY"`, or `"SINCE"`.
When the scope is `"SINCE"`, the envelope MUST include a `since` field
(ISO-8601) marking the lower bound of the time window.

The `checksum` field MUST be computed per {{checksum}}.

If any Chunk in the Bundle includes an embedding, the envelope MUST
include `embedding_dim` (integer) and `embedding_model` (string). See
{{embedding}}.

## ChunkRecord {#chunk-record}

Each entry in `chunks` MUST be an object with the following normative
fields:

~~~ json
{
  "id": "urn:aimem:memoryai-prod:chunk-1",
  "content": "User prefers PostgreSQL over MongoDB.",
  "content_hash": "sha256:abcdef...",
  "memory_type": "preference",
  "zone": "important",
  "is_pinned": false,
  "created_at": "2026-04-01T09:30:00Z",
  "tags": ["db", "stack-choice"],
  "embedding": null
}
~~~

The `id` field MUST conform to {{chunk-id}}.

The `content` field MUST be a non-empty UTF-8 string. Implementations
MAY enforce a maximum length but MUST accept strings up to 65,536
codepoints.

The `content_hash` field, if present, MUST be a lowercase
`sha256:<hex>` over the UTF-8 bytes of `content`. Consumers MUST verify
the hash on import and reject the Chunk on mismatch (HTTP 422 or
equivalent error).

The `memory_type` field MUST be one of: `fact`, `preference`,
`decision`, `identity`, `pitfall`, `procedure`, `episodic`, `goal`.
The five DNA-class types — `preference`, `decision`, `identity`,
`pitfall`, `procedure` — carry the additional invariant defined in
{{security}}.

The `zone` field, if present, MUST be one of `critical`, `important`,
or `standard`.

The `is_pinned` field, if present, MUST be a boolean. Pinned Chunks
share the DNA-class invariant defined in {{security}}.

The `created_at` field MUST be an ISO-8601 UTC timestamp.

The `tags` field, if present, MUST be a JSON array of strings, each
1-64 codepoints, lowercase ASCII recommended.

The `embedding` field, if present, MUST be encoded per {{embedding}}.

## Chunk identifier {#chunk-id}

Chunk identifiers MUST be URNs of the form

`urn:aimem:<producer>:<local>`

per {{RFC8141}} where:

- `<producer>` is the Producer Namespace (lowercase ASCII,
  `[a-z0-9-]`, 1-63 chars), identical to the `producer` envelope
  field. Producer Namespace assignment is by self-declaration; conflicts
  are resolved by domain ownership convention (a Producer SHOULD use a
  prefix derived from a domain it controls, e.g. `memoryai-prod` from
  `memoryai.dev`).
- `<local>` is an opaque identifier unique within `<producer>`, of any
  printable ASCII (`[\x21-\x7E]`) up to 256 chars, excluding `:` and
  whitespace.

Consumers MUST treat `id` as opaque and MUST NOT parse semantics from
it beyond the namespace prefix. Re-importing a Bundle with the same
`(producer, local)` pair MUST be idempotent (see {{idempotency}}).

## Edges {#edge-record}

The `edges` field, if present, MUST be a JSON array of objects with
the following normative fields:

~~~ json
{
  "source_id": "urn:aimem:memoryai-prod:chunk-1",
  "target_id": "urn:aimem:memoryai-prod:chunk-7",
  "edge_type": "hebbian",
  "weight": 0.42,
  "created_at": "2026-04-15T08:00:00Z"
}
~~~

The `edge_type` field MUST be one of `hebbian`, `semantic`, `temporal`,
`causal`, or an implementation-defined value prefixed with `x-`.

The `weight` field MUST be a number in the closed interval `[0.0, 1.0]`.

Both `source_id` and `target_id` MUST reference `id` values present in
the same Bundle's `chunks` array, or the Consumer MUST reject the
Bundle with a 422.

## Entities {#entity-record}

The `entities` field, if present, MUST be a JSON array of objects with
the following normative fields:

~~~ json
{
  "id": "urn:aimem:memoryai-prod:entity-7",
  "name": "PostgreSQL",
  "kind": "technology",
  "created_at": "2026-04-01T09:30:00Z"
}
~~~

The `kind` field MUST be one of `person`, `organization`, `place`,
`technology`, `concept`, or an implementation-defined value prefixed
with `x-`.

## Chunk-entity links {#chunk-entities}

The `chunk_entities` field, if present, MUST be a JSON array of objects
linking Chunks to Entities:

~~~ json
{
  "chunk_id": "urn:aimem:memoryai-prod:chunk-1",
  "entity_id": "urn:aimem:memoryai-prod:entity-7"
}
~~~

Both `chunk_id` and `entity_id` MUST reference URNs present in the
same Bundle.

## Embedding encoding {#embedding}

When a Chunk includes an embedding:

1. The Chunk's `embedding` field MUST be a base64-encoded {{RFC4648}}
   little-endian float32 array.
2. The envelope MUST declare `embedding_dim` (integer) — the array
   length.
3. The envelope MUST declare `embedding_model` (string) — the model
   identifier under which the vector was produced (e.g.
   `"text-embedding-3-small"`, `"bge-large-en-v1.5"`).

A Consumer that does not support `embedding_model` MAY drop the
embeddings (treating the Bundle as if `embedding` were null on every
Chunk) and MUST emit a structured warning identifying the unsupported
model. The Consumer MUST NOT silently re-embed Chunks under a different
model when ingesting; re-embedding is a separate, explicit operation
out of scope for this specification.

## Checksum {#checksum}

The `checksum` field MUST be computed as follows:

1. Remove the `checksum` field from the envelope.
2. Serialise the resulting object using JSON Canonicalization Scheme
   ({{RFC8785}}).
3. Compute SHA-256 over the UTF-8 bytes.
4. Encode as `"sha256:" + lowercase_hex(digest)`.

A Consumer MUST verify the checksum before importing. Verification
failure MUST result in HTTP 409 (Conflict) when the Bundle is delivered
over HTTP, or an equivalent application-level error otherwise.

## Idempotency rules {#idempotency}

Consumers MUST treat re-imports as idempotent on the URN
`(producer, local)` pair. On re-import:

1. If the Chunk already exists with identical `content_hash` and
   `created_at`, the Consumer MUST treat the import as a no-op.
2. If `content_hash` differs but `created_at` matches, the Consumer
   MUST reject the Chunk with a structured error citing the conflict.
3. If `created_at` is newer than the stored value, the Consumer MAY
   either reject or update at its discretion; the chosen behaviour MUST
   be documented.

# HTTP Profile

The following endpoints are RECOMMENDED for implementations that expose
Bundles over HTTP {{RFC9110}}.

## Export

`GET /v1/brain/export?scope={FULL|DNA_ONLY|SINCE}&since={ISO-8601}`

A 200 response MUST contain the Bundle JSON with the
`application/aimem-bundle+json` media type. A 401 response indicates
missing authentication. A 403 response indicates the caller has no
export scope on the Tenant.

For Bundles whose serialised body would exceed 16 MiB, Producers SHOULD
support a streaming variant returning newline-delimited JSON
(`application/x-ndjson`) at `GET /v1/brain/export/stream`. The first
line MUST be the envelope (without the `chunks`, `edges`, `entities`,
`chunk_entities` arrays); subsequent lines MUST be objects of one of
those record types each tagged with a `_kind` field
(`"chunk"`, `"edge"`, `"entity"`, `"chunk_entity"`).

## Import

`POST /v1/brain/import`

The request body MUST be a Bundle. A 200 response indicates a successful
ingest with a summary of inserted, updated, and skipped Chunks. A 409
response indicates checksum mismatch. A 422 response indicates a
malformed Bundle (envelope missing fields, invalid URN, edge references
unknown chunk, etc.).

Errors SHOULD use the format defined in {{RFC7807}}.

# Conformance Levels

A Producer (Level 1) MUST emit a Bundle that round-trips through itself
when re-imported, in conformance with {{idempotency}}.

A Consumer (Level 2) MUST ingest any Bundle that conforms to
{{bundle-format}}.

A Bidirectional implementation (Level 3) MUST satisfy both, AND a
Bundle exported from such an implementation MUST be importable into
the same implementation as a no-op (idempotent re-import).

A test corpus exercising each conformance level is included with the
informative reference implementation cited in {{AIMEM-REF}}.

# Security Considerations {#security}

## DNA-class invariant

Implementations MUST NOT silently decay, delete, or supersede DNA-class
Chunks (see {{terminology}}) during background processing. Explicit
user-initiated deletion MUST be honoured (see {{erasure}}); implicit
decay MUST NOT.

The reasoning is operational: a user's identity claims and previously
recorded decisions are higher-cost-to-lose than incidental facts.
Implementations that decay them silently produce a privacy harm
(loss of user-stated history without consent) and a correctness harm
(divergent agent behaviour after decay).

## Right to erasure {#erasure}

When a Tenant exercises a right-to-erasure request such as
{{GDPR-A17}}, conforming implementations MUST:

1. Hard-delete every Chunk for that Tenant, cascading through any
   per-tenant derivative tables (edges, entity links, recall logs,
   audit logs that contain content rather than hashes).
2. Decrement reference counts on globally shared content pools and
   trigger orphan cleanup.
3. Filter the Tenant's data out of any subsequent Bundle export, even
   if the export request precedes the cascade by milliseconds (i.e.
   erasure is durable from the user's perspective).

Implementations SHOULD record the erasure event in a tamper-evident
audit log so an auditor can reconstruct *that* erasure occurred without
recovering *what* was erased.

## Bundle authenticity {#auth}

When a Bundle crosses a trust boundary (e.g. ingest from a third
party), Consumers SHOULD verify the Producer's signature over the
canonicalised Bundle bytes using a detached COSE_Sign1 signature
{{RFC9052}}.

The signature MUST be carried in the
`AIMEM-Signature` HTTP header for HTTP transports, or in a sibling
file `<bundle-name>.sig` for at-rest exchange. The signature payload
MUST be the canonical JSON form of the Bundle as produced for the
checksum (see {{checksum}}).

Producers MAY publish their public key under {{RFC8615}}
`/.well-known/aimem-pubkey`, in COSE_Key format, to facilitate
verification.

Consumers that elect to skip signature verification (e.g. inside a
trusted enclave) MUST log the decision in their audit trail.

## Replay and idempotency

Consumers MUST treat a re-imported Bundle as idempotent on chunk URN
(within the Producer Namespace) per {{idempotency}}, and reject any
field changes on a Chunk whose `created_at` matches a prior import.
Replay attacks across trust boundaries are addressed by the
Bundle-level signature defined in {{auth}}; duplicate ingest within a
trust boundary is addressed by URN idempotency.

## Embedding privacy

Embeddings can leak content under inversion attacks. Producers SHOULD
NOT include embeddings in Bundles delivered to untrusted Consumers
unless the Tenant has explicitly consented. Consumers receiving
embeddings MUST treat them with the same access controls as the
underlying `content`.

# IANA Considerations

This document requests the registration of the media type
`application/aimem-bundle+json` per {{RFC8259}}. The registration
template is provided in {{iana-template}}.

## Media type registration template {#iana-template}

~~~
Type name:        application
Subtype name:     aimem-bundle+json
Required parameters: none
Optional parameters: version (e.g. "1")
Encoding considerations: UTF-8 JSON
Security considerations: see Section 6 of this document
Interoperability considerations: see Section 5 of this document
Published specification: this document
Applications that use this media type: AI agent memory portability tools
Fragment identifier considerations: none
Restrictions on usage: none
Additional information:
  Magic number(s): N/A (UTF-8 JSON)
  File extension(s): .aimem.json
  Macintosh file type code: TEXT
Person & email address to contact:
  Vu Duc Minh <minh@memoryai.dev>
Intended usage: COMMON
Author: Vu Duc Minh
Change controller: IETF (after publication)
~~~

# Versioning

The `version` field is a string. Backwards-compatible additions MUST
keep the same major version. Breaking changes MUST increment the major
version and MUST NOT be silently accepted by Consumers — a v1 Consumer
MUST reject a v2 Bundle with a 422 response.

--- back

# Changes from draft-00

- Added `producer` envelope field and the `urn:aimem:` namespace
  scheme for chunk identifiers.
- Inlined edge, entity, and chunk-entity record schemas (previously
  delegated to an external CC-BY document, which is not a normative
  reference acceptable to IETF).
- Added `embedding_model` envelope field; clarified that Consumers
  MUST NOT silently re-embed under a different model.
- Replaced the "out-of-band v1" signature mechanism with detached
  COSE_Sign1 over the JSON-canonicalised body.
- Required JSON Canonicalization Scheme (RFC 8785) for checksum,
  replacing prose-defined "sorted keys" canonicalisation.
- Added `chunk_entities` link record.
- Added embedding privacy guidance in {{security}}.

# Acknowledgments

The author thanks the early implementers of `draft-00` for feedback on
the conformance level structure and the embedding interop gap that
motivated `embedding_model`.
