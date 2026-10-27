# AL-RIFA'I Cash Standalone — Read-only T5 Artifact

Status: assembled as a contract-only, non-executable staging artifact on
2026-10-17 (Asia/Dhaka).

This directory is not a production deployment, Git repository, package
release, database client or WhatsApp consumer. It contains only extraction
metadata and test planning. The existing AL-RIFA'I Cash Payment remains the
only live authority.

## Guarantees

- No payment post, movement write, cursor update, migration, backfill or
  replay was performed.
- No WhatsApp message was sent and no Bridge-1 store, socket or token was
  accessed.
- No production database, runtime flag, deployment, restart, credential or
  protected source file was changed.
- No secret, password, raw WhatsApp content, employee record or payment record
  is included here.
- The artifact has no executable entry point and cannot be used to create a
  second writer.

## Files

- `README.md` — scope and safety guarantees.
- `SOURCE_IMPORT_MANIFEST.md` — verified source boundary, import edges,
  environment-key names and excluded writer/secret inputs.
- `API_CONTRACT.md` — current Cash and related API contract to preserve.
- `TEST_PLAN.md` — safe checks, disposable setup and execution status.

The next step, if separately approved, is to assemble an executable
read-only projection from this manifest in a disposable environment. That is
not included in this T5 artifact.
