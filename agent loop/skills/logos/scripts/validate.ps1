$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$failures = New-Object System.Collections.Generic.List[string]

function Assert-FileExists {
    param(
        [string]$RelativePath
    )

    $path = Join-Path $root $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $failures.Add("Missing file: $RelativePath")
    }
}

function Assert-Contains {
    param(
        [string]$RelativePath,
        [string]$Pattern,
        [string]$Message
    )

    $path = Join-Path $root $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $failures.Add("Cannot inspect missing file: $RelativePath")
        return
    }

    if (-not (Select-String -Path $path -Pattern $Pattern -Encoding UTF8 -Quiet)) {
        $failures.Add($Message)
    }
}

Assert-FileExists "README.md"
Assert-FileExists "SKILL.md"
Assert-FileExists "references/template.md"
Assert-FileExists "examples/daily/2026-07-02.md"

$skillPath = Join-Path $root "SKILL.md"
if (Test-Path -LiteralPath $skillPath -PathType Leaf) {
    $skillLines = Get-Content -LiteralPath $skillPath -Encoding UTF8
    $frontmatterDelimiters = @($skillLines | Where-Object { $_ -eq "---" })
    if ($frontmatterDelimiters.Count -lt 2) {
        $failures.Add("SKILL.md frontmatter must have opening and closing --- delimiters")
    }
}

Assert-Contains "SKILL.md" "^name:\s+logos$" "SKILL.md must declare name: logos"
Assert-Contains "SKILL.md" "allowed-tools:" "SKILL.md must declare allowed-tools"
Assert-Contains "SKILL.md" "references/template\.md" "SKILL.md must reference references/template.md"
Assert-Contains "SKILL.md" "\[REDACTED\]" "SKILL.md must include redaction handling"
Assert-Contains "SKILL.md" "N" "SKILL.md must define daily conversation numbering"

Assert-Contains "references/template.md" "####" "template.md must include structured sections"
Assert-Contains "references/template.md" "- \[ \]" "template.md must include checkbox todo syntax"
Assert-Contains "references/template.md" "\[REDACTED\]" "template.md must mention redaction"

Assert-Contains "README.md" "git clone https://github.com/myyyyyyz/logos-aicoding.git skills/logos/" "README.md must include installation instructions"
Assert-Contains "README.md" "logos" "README.md must include usage instructions"
Assert-Contains "README.md" "API Key" "README.md must include privacy and security guidance"
Assert-Contains "README.md" "scripts/validate.ps1" "README.md must include validation instructions"
Assert-Contains "README.md" "CLI" "README.md must state current limitations"

Assert-Contains "examples/daily/2026-07-02.md" "scripts/validate.ps1" "example daily report must include verification results"
Assert-Contains "examples/daily/2026-07-02.md" "Skill" "example daily report must include lessons learned"

if ($failures.Count -gt 0) {
    Write-Host "Logos validation failed:" -ForegroundColor Red
    foreach ($failure in $failures) {
        Write-Host " - $failure" -ForegroundColor Red
    }
    exit 1
}

Write-Host "Logos validation passed." -ForegroundColor Green
