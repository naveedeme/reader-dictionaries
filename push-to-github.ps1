$ErrorActionPreference = "Stop"
$RepositoryUrl = "https://github.com/naveedeme/reader-dictionaries.git"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required. Install Git for Windows and reopen PowerShell."
}

if (-not (Test-Path ".git")) {
    git init
}

git add .
$HasCommit = $true
git rev-parse --verify HEAD 2>$null
if ($LASTEXITCODE -ne 0) {
    $HasCommit = $false
}

if (-not $HasCommit) {
    git commit -m "Initial offline dictionary builder"
} else {
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit -m "Update offline dictionary builder"
    }
}

git branch -M main
$Origin = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0) {
    if ($Origin.Trim() -ne $RepositoryUrl) {
        throw "Existing origin is '$($Origin.Trim())'; expected '$RepositoryUrl'."
    }
} else {
    git remote add origin $RepositoryUrl
}

git push -u origin main
