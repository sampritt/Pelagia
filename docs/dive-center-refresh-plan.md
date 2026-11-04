# Dive-center registry refresh plan

## Objective

Load the versioned PADI-plus-Overture CSV into the production `dive_centers`
table without changing the IDs used by logged dives, dive-center likes, or
comments.

Pushing the CSV alone is not sufficient: production uses its persistent SQLite
database, and application startup imports reference data only when the table is
empty.

## Stable identity

Every incoming record must have one durable key:

1. `padi:<padi_id>` when a PADI ID is present.
2. `overture:<overture_id>` for Overture-only records.

Add a nullable, unique `reference_key` column to `dive_centers`. New and
matched records retain their existing integer primary key; the refresh never
uses a CSV row number as a database ID.

## One-time legacy reconciliation

Existing rows have no stable source key. During the first refresh, match an
unkeyed record only when normalized name plus its address/location or website
matches exactly one incoming record. Assign that record's `reference_key` while
retaining its current `dive_centers.id`.

Ambiguous legacy records are not relinked automatically. Keep them for review
if referenced; delete them only when unreferenced.

## Transactional refresh

Run the migration in a single SQLite transaction:

1. Load the CSV into a temporary staging table with `reference_key`.
2. Reconcile unkeyed legacy records conservatively.
3. Update matched rows in place by `reference_key`.
4. Insert genuinely new records without supplying an `id`.
5. Delete obsolete rows only when they have no row in `dives`,
   `dive_center_likes`, or `dive_center_comments`.
6. Commit only after validating all expected source keys are represented;
   otherwise roll back.

Retained, referenced records absent from the incoming registry remain valid for
historic links and are reported as `retained_referenced` for operator review.

## Deployment sequence

1. Back up `/var/data/pelagia.sqlite3`.
2. Deploy the revision containing the CSV and refresh command.
3. Run a dry run against the production persistent disk and review counts for
   inserted, updated, legacy-matched, deleted-unreferenced, and
   retained-referenced records.
4. Run the same command without dry-run under a brief maintenance window.
5. Verify `/api/dive-centers?q=...` and global search against a known new
   Overture-only center, while confirming a pre-existing logged dive still
   resolves to the same dive-center ID.

## Rollback

Restore the SQLite backup and redeploy the prior revision. Because the refresh
is transactional, a failed run leaves the prior database unchanged.
