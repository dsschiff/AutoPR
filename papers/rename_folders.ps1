param(
  [string]$PapersDir = "D:\Dropbox\Documents\Academics\Purdue\GitHub\AutoPR\papers",
  [switch]$KeepNumericPrefix = $true,
  [int]$MaxTokens = 4,
  [switch]$DryRun
)

function Slug-FirstTokens([string]$pdfStem, [int]$MaxTokensLocal = 4) {
  if ($null -eq $pdfStem) { return "" }

  $s = $pdfStem.Trim()

  # Normalize common separators to underscores
  $s = [regex]::Replace($s, "[\s\-]+", "_")

  # Replace anything not safe for filenames with underscore
  $s = [regex]::Replace($s, "[^A-Za-z0-9_]+", "_")

  # Collapse multiple underscores and trim
  $s = [regex]::Replace($s, "_+", "_").Trim("_")

  if ([string]::IsNullOrWhiteSpace($s)) { return "" }

  $parts = $s.Split("_") | Where-Object { $_ -ne "" }

  if ($parts.Count -le $MaxTokensLocal) {
    return ($parts -join "_")
  }

  return (($parts[0..($MaxTokensLocal-1)]) -join "_")
}

if (-not (Test-Path -LiteralPath $PapersDir)) {
  throw "PapersDir not found: $PapersDir"
}

$folders = Get-ChildItem -LiteralPath $PapersDir -Directory | Sort-Object Name

foreach ($folder in $folders) {

  # If you want to ONLY rename numeric folders like 0000, 0001, ... uncomment:
  # if ($folder.Name -notmatch '^\d{4}$') { continue }

  $pdf = Get-ChildItem -LiteralPath $folder.FullName -File -Filter *.pdf |
         Sort-Object LastWriteTime |
         Select-Object -First 1

  if (-not $pdf) {
    Write-Host ("[skip] No PDF in {0}" -f $folder.Name)
    continue
  }

  $pdfStem = [System.IO.Path]::GetFileNameWithoutExtension($pdf.Name)
  $slug = Slug-FirstTokens $pdfStem $MaxTokens

  if ([string]::IsNullOrWhiteSpace($slug)) {
    Write-Host ("[skip] Could not make slug for {0} (pdf: {1})" -f $folder.Name, $pdf.Name)
    continue
  }

  # Preserve a leading 4-digit prefix from the existing folder name (e.g., 0007)
  $prefix = ""
  $m = [regex]::Match($folder.Name, "^\d{4}")
  if ($KeepNumericPrefix -and $m.Success) { $prefix = $m.Value }

  if ($prefix -ne "") {
    $newBase = "{0}__{1}" -f $prefix, $slug
  } else {
    $newBase = $slug
  }

  $newName = $newBase

  # Avoid collisions by adding __2, __3, ...
  $n = 2
  while ((Test-Path -LiteralPath (Join-Path $PapersDir $newName)) -and ($newName -ne $folder.Name)) {
    $newName = "{0}__{1}" -f $newBase, $n
    $n++
  }

  if ($newName -eq $folder.Name) {
    Write-Host ("[ok]  {0}" -f $folder.Name)
    continue
  }

  Write-Host ("[ren] {0} -> {1}" -f $folder.Name, $newName)

  if (-not $DryRun) {
    Rename-Item -LiteralPath $folder.FullName -NewName $newName
  }
}

Write-Host "Done."
