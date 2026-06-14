# Security policy

## Reporting a vulnerability

Email **founder@memoryai.vn** with the subject prefix `[aimem-reference
security]`. Encrypt with our PGP key if the issue concerns
authentication, RLS, or signature verification:

```
PGP fingerprint: (to be published before v0.2.0)
```

We aim to acknowledge within 72 hours and produce a fix or workaround
within 14 days for confirmed high-severity issues.

## In scope

- Authentication bypass on `/v1/admin/provision` or `/v1/brain/*`.
- Tenant-isolation bypass (RLS evasion).
- Bundle parser vulnerabilities: stack overflow on deep nesting,
  algorithmic complexity (e.g. checksum-of-large-input DoS), unicode
  normalization mismatches.
- Signature forgery for the COSE_Sign1 detached signature path.
- Any leak of `app.bypass_rls` to a request handler.

## Out of scope

- Denial of service through legitimate-looking but expensive requests
  (mitigation is operational — rate limit, quota — not a code defect).
- Vulnerabilities in upstream dependencies that are fixed in a newer
  version we have not yet bumped to. File a regular PR/issue instead.
- The intentional absence of a recall engine. The reference is wire
  layer only by design (see README).

## Disclosure

We follow coordinated disclosure: a fix lands first, then a CHANGELOG
entry with a CVE if applicable. Reporters are credited unless they
request anonymity.
