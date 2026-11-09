# GitHub Actions freeze — November 2026

**Effective:** 9 November 2026 through 30 November 2026, 23:59:59 Asia/Karachi (Pakistan time).

The repository owner has exhausted GitHub Actions minutes. Until 1 December 2026, **do not run, queue, trigger, dispatch, rerun, enable, restore, or create GitHub Actions workflows**. This applies to push, pull request, schedule, release, manual dispatch, repository dispatch, workflow-call, and any other trigger. Do not use GitHub Actions to compile, test, package, deploy, publish, or verify work.

The repository's active workflow YAML files on the default branch have been preserved by renaming them from `.yml`/`.yaml` to `.yml.paused`/`.yaml.paused`. **Do not remove the `.paused` suffix or otherwise activate them before December 2026.** Workflow files already paused must remain paused.

This temporary restriction supersedes any CI, sprint, verification, deployment, or automation instruction elsewhere in the repository. Work requiring GitHub Actions must be deferred. Local/offline work is permitted if otherwise authorized, but avoid branch pushes, PR actions, tags, and releases that could activate workflows in other branches or connected systems.

**After the freeze:** Do not automatically restore or run workflows. On or after 1 December 2026, first confirm with the owner that Action minutes are available and resumption is authorized; then restore the original filenames in a controlled commit. Preserve the original workflow contents. Repository-level GitHub Actions settings and other branches are not changed by this file-based pause.
