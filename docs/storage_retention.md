# Deployment storage retention

The user requested a three-day retention period on 2026-11-25. This covers
obsolete deployment images and build-source archives, not planner data, files,
credentials or database backups. A currently serving image is protected even
when its creation date is older than three days.

## Live cleanup completed

In `planner-os-502107`, 258 obsolete container versions and 60 old source
archives were deleted. The only remaining image is the one serving
`planner-os-api-00300-tb4`, digest
`sha256:40b2b1f1fb6942ddcbf3f24cb6e3b0e181c5d1c35503ce851595562349e1d91f`.
Both build-source buckets have zero active objects. The health endpoint still
reports ready, revision `24d46e4`; cleanup did not redeploy the backend.

Repository byte totals can lag image deletion and shared-layer reclamation.
Deleted build archives retain the buckets' existing seven-day soft-delete
recovery. Automatic approval review rejected disabling that recovery protection;
it was left enabled. Those archives total about 15 MB, not the multi-GB image
storage that drove the recurring cost.

## Automatic retention

The active registry policy is recorded in `config/artifact-retention.json`:
delete `planner-os-api` versions older than three days, except protected live
and latest image tags. Both deployment repositories have this policy enabled.
Registry policy runs periodically, rather than at an exact 72-hour deadline.

The build-source buckets have age-three-day deletion rules restricted to their
build prefixes: `source/` and `services/planner-os-api/` respectively.

`scripts/protect_live_image.py` resolves all serving or explicitly tagged Cloud
Run revisions, protects their exact image digests, and only then retires stale
protection slots. Failed reads leave protection intact. With `--cleanup`, it
also immediately removes non-serving images older than three days in these two
repositories. It leaves other image packages alone.

`cloudbuild.yaml` invokes this hook after a successful deployment. That source
change must be pushed before future Cloud Builds use it; the registry and bucket
policies above are already active. No push was performed for this cleanup.

Tests in `tests/test_image_retention.py` check foreign/unresolved-image refusal,
multiple traffic targets, read-failure safety and protection of old live images
during immediate cleanup.
