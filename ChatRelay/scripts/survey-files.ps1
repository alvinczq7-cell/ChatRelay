# Read-only survey: where WeChat 4.x keeps received files, and which ones are plain
# (readable as-is) vs. encrypted (.dat). Lists names/extensions/counts only; does not
# open any database or message store.
$ErrorActionPreference = 'Continue'
$candidates = @(
    (Join-Path $env:USERPROFILE 'Documents\xwechat_files'),
    (Join-Path $env:USERPROFILE 'Documents\WeChat Files')
)
try {
    $cfg = Get-ChildItem (Join-Path $env:APPDATA 'Tencent\xwechat\config') -Filter '*.ini' -ErrorAction Stop |
        ForEach-Object { Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue }
    $candidates += ($cfg | Where-Object { $_ -and (Test-Path $_.Trim()) } | ForEach-Object { Join-Path $_.Trim() 'xwechat_files' })
} catch {}
foreach ($root in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path $root)) { continue }
    "== root: $root"
    Get-ChildItem $root -Directory | ForEach-Object {
        $acct = $_.FullName
        "-- account dir: $($_.Name)"
        foreach ($sub in 'msg\file', 'msg\attach', 'msg\video', 'cache', 'db_storage') {
            $p = Join-Path $acct $sub
            if (Test-Path $p) {
                $files = Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue
                $byExt = $files | Group-Object { $_.Extension.ToLower() } | Sort-Object Count -Descending | Select-Object -First 8 |
                    ForEach-Object { "$($_.Name)x$($_.Count)" }
                "   {0,-12} files={1,6}  ext: {2}" -f $sub, $files.Count, ($byExt -join ' ')
            }
        }
        $fileDir = Join-Path $acct 'msg\file'
        if (Test-Path $fileDir) {
            "   recent documents in msg\file:"
            Get-ChildItem $fileDir -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending |
                Select-Object -First 5 | ForEach-Object { "     {0:yyyy-MM-dd HH:mm}  {1}" -f $_.LastWriteTime, $_.FullName.Substring($acct.Length) }
        }
    }
}
