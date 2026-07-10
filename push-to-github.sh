#!/usr/bin/env bash
set -euo pipefail

repository_url="https://github.com/naveedeme/reader-dictionaries.git"

command -v git >/dev/null 2>&1 || { echo "Git is required." >&2; exit 1; }

if [[ ! -d .git ]]; then
  git init
fi

git add .
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git commit -m "Initial offline dictionary builder"
elif ! git diff --cached --quiet; then
  git commit -m "Update offline dictionary builder"
fi

git branch -M main
if git remote get-url origin >/dev/null 2>&1; then
  current_origin="$(git remote get-url origin)"
  if [[ "$current_origin" != "$repository_url" ]]; then
    echo "Existing origin is $current_origin; expected $repository_url" >&2
    exit 1
  fi
else
  git remote add origin "$repository_url"
fi

git push -u origin main
