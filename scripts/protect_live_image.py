"""Move storage-retention protection to images actually serving Cloud Run.

Run only after a successful deployment. A failed read or unresolved image aborts
before any protection is removed. With --cleanup, obsolete versions older than
three days are removed immediately; registry policy also cleans them periodically.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import subprocess


def read(*args):
    return json.loads(subprocess.check_output(["gcloud", *args, "--format=json"], text=True))


def canonical_image(image, project):
    if image.startswith(f"gcr.io/{project}/"):
        image = image.replace(f"gcr.io/{project}/", f"us-docker.pkg.dev/{project}/gcr.io/", 1)
    if not image.startswith((f"us-docker.pkg.dev/{project}/", f"us-central1-docker.pkg.dev/{project}/")) or "@sha256:" not in image:
        raise ValueError("Cannot protect an unresolved or foreign image")
    return image


def protect(project, region, service, cleanup=False):
    data = read("run", "services", "describe", service, f"--project={project}", f"--region={region}")
    status = data["status"]
    revisions = sorted({item.get("revisionName") or status["latestReadyRevisionName"]
                        for item in status["traffic"] if item.get("percent", 0) > 0 or item.get("tag")})
    if not revisions:
        raise ValueError("No serving revision resolved; protection left unchanged")
    images = []
    for revision in revisions:
        row = read("run", "revisions", "describe", revision, f"--project={project}", f"--region={region}")
        images.append(canonical_image(row["status"]["imageDigest"], project))
    prefix = f"planner-live-{service}"
    desired = {}
    for index, image in enumerate(dict.fromkeys(images)):
        tag = prefix if index == 0 else f"{prefix}-{index}"
        target = image.split("@", 1)[0] + ":" + tag
        subprocess.run(["gcloud", "artifacts", "docker", "tags", "add", image, target, f"--project={project}", "--quiet"], check=True)
        desired[target] = image
    # Only now remove obsolete protection slots, leaving all ordinary build
    # tags alone. The main stable protection tag moves atomically above.
    for base in {image.split("@", 1)[0] for image in images}:
        tags = read("artifacts", "docker", "tags", "list", base, f"--project={project}")
        for row in tags:
            name = row.get("tag", "").rsplit("/tags/", 1)[-1]
            if not (name == prefix or name.startswith(prefix + "-")):
                continue
            target = base + ":" + name
            if target not in desired:
                subprocess.run(["gcloud", "artifacts", "docker", "tags", "delete", target, f"--project={project}", "--quiet"], check=True)
    print(f"Protected {len(desired)} serving image(s); obsolete versions expire after three days.")
    if cleanup:
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        for repository in (f"us-docker.pkg.dev/{project}/gcr.io", f"us-central1-docker.pkg.dev/{project}/cloud-run-source-deploy"):
            versions = read("artifacts", "docker", "images", "list", repository, "--include-tags", f"--project={project}")
            for row in versions:
                if row.get("package") != repository + "/" + service:
                    continue
                image = row["package"] + "@" + row["version"]
                created = datetime.fromisoformat(row["createTime"][:19]).replace(tzinfo=timezone.utc)
                if image in images or created >= cutoff:
                    continue
                subprocess.run(["gcloud", "artifacts", "docker", "images", "delete", image,
                                f"--project={project}", "--delete-tags", "--quiet"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--service", default="planner-os-api")
    parser.add_argument("--cleanup", action="store_true", help="Remove non-serving images older than three days after protecting live images")
    args = parser.parse_args()
    protect(args.project, args.region, args.service, args.cleanup)
