# SPA Verifier Release Manifest

**Purpose.** Pin an *authentic* copy of the standalone proof verifier so a skeptical
reviewer can confirm the script they run is byte-for-byte the one SPA published — before
they trust a single verdict it prints. "Don't trust us, check us" only works if you can
also check the *checker*.

The verifier is `scripts/verify_spa.py`: a zero-dependency, no-network, no-`spa_core`
Python file that re-derives every published hash following only the public
[`docs/PROOF_CHAIN_SPEC.md`](./PROOF_CHAIN_SPEC.md) recipe. See [`/verify`](https://earn-defi.com/verify)
for the reviewer-facing walkthrough.

---

## Current release

| Field | Value |
|---|---|
| **Version tag** | `verifier-v1.0` |
| **File** | `scripts/verify_spa.py` |
| **SHA-256** | `0f8c270c8c1f0c59ffc7236b1e43c1cb2aa58329faf7839c1961ce83209f81da` |
| **Size** | 51817 bytes · 915 lines |
| **Spec version** | PROOF_CHAIN_SPEC `1.0` |
| **Scope** | decision chain (A) · exit-NAV proofs (B) · anchors (C) · equity track (D) |

### Verify the verifier (one command)

On macOS / Linux, after downloading `verify_spa.py`:

```bash
shasum -a 256 verify_spa.py
# must print:
# 0f8c270c8c1f0c59ffc7236b1e43c1cb2aa58329faf7839c1961ce83209f81da  verify_spa.py
```

or with the GNU coreutils tool:

```bash
sha256sum verify_spa.py
# 0f8c270c8c1f0c59ffc7236b1e43c1cb2aa58329faf7839c1961ce83209f81da  verify_spa.py
```

If the digest does not match this manifest **byte-for-byte**, you do not have the
authentic verifier — discard it and re-download from the pinned tag below.

### Then run it

```bash
python3 verify_spa.py data/rates_desk/
# exit 0 = every published hash reproduces; exit 1 = any mismatch.
```

---

## What this release pins (and what it does NOT)

- **A tag + a SHA-256 are owner-independent integrity:** anyone can recompute the digest
  on their own machine and compare it to this manifest. No trust in SPA is required for the
  digest comparison itself — that is the whole point.
- **A SHA-256 proves identity, not provenance.** It proves *"this is the file the manifest
  describes."* It does **not**, by itself, cryptographically prove *"SPA's owner authored
  this manifest."* That stronger guarantee needs a **signature**.

### Owner actions (flagged — not done here)

These are intentionally **owner-gated** and are NOT performed by this manifest:

1. **`git tag verifier-v1.0`** over the commit that contains this exact
   `scripts/verify_spa.py`, then push the tag. A pushed git tag gives reviewers an
   immutable, fetchable reference point (`git fetch --tags` → `git show verifier-v1.0`).
2. **GPG-sign** the tag (`git tag -s verifier-v1.0`) and/or publish a detached
   signature of the SHA-256 with the project's published GPG key. *Only this* upgrades the
   digest from "identity" to "authenticated provenance." It requires the owner's private
   key and is therefore out of scope for an automated change.

Until the owner signs, the honest claim is precisely: *this manifest pins an
owner-independent SHA-256 + version label; a reviewer can confirm file identity against it
today; cryptographic provenance (a signed tag) is the owner's next step.*

---

## Re-pinning on a verifier change

If `scripts/verify_spa.py` ever changes, this is **not** automatic — bump the version,
recompute, and record it here:

```bash
shasum -a 256 scripts/verify_spa.py     # new digest
wc -c -l scripts/verify_spa.py          # new size / line count
```

Then add a row to the changelog below, update **Current release**, and (owner) cut a new
`verifier-vN.M` tag. A new digest with the **same** version tag is a contradiction — every
distinct verifier byte-image gets its own version.

| Version | SHA-256 | Date | Note |
|---|---|---|---|
| `verifier-v1.0` | `0f8c270c8c1f0c59ffc7236b1e43c1cb2aa58329faf7839c1961ce83209f81da` | 2026-06-28 | Initial pinned release. Verifies decision chain + exit-NAV + anchors + equity track per PROOF_CHAIN_SPEC v1.0. |

---

*Referenced from `/verify`, `docs/DD_PACK.md`, and `/track-record`. Recipe:
`docs/PROOF_CHAIN_SPEC.md`. stdlib-only · deterministic · fail-CLOSED.*
