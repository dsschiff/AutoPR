$src = "D:\Dropbox\Documents\Academics\Purdue\GitHub\AutoPR\papers"

# Get PDFs directly in $src (non-recursive), sorted by LastWriteTime (modified date), earliest first
$pdfs = Get-ChildItem -Path $src -Filter *.pdf -File | Sort-Object LastWriteTime

$i = 0
foreach ($f in $pdfs) {
    $folderName = "{0:D4}" -f $i
    $destDir = Join-Path $src $folderName

    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir | Out-Null
    }

    $destPath = Join-Path $destDir $f.Name

    # Avoid overwriting if same filename already exists in destination
    if (Test-Path $destPath) {
        $base = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
        $ext  = $f.Extension
        $k = 1
        do {
            $newName = "{0} ({1}){2}" -f $base, $k, $ext
            $destPath = Join-Path $destDir $newName
            $k++
        } while (Test-Path $destPath)
    }

    Move-Item -LiteralPath $f.FullName -Destination $destPath
    $i++

    if ($i -gt 9999) { throw "More than 10,000 PDFs found (exceeded 9999)." }
}

Write-Host "Moved $i PDF(s) into subfolders 0000..$('{0:D4}' -f ($i-1))"
