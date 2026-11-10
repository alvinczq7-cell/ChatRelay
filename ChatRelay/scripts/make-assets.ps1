# Generates the placeholder logos the package manifest references.
param([Parameter(Mandatory = $true)][string]$OutDir)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
foreach ($spec in @(@{ Name = 'Square44x44Logo.png'; Size = 44 }, @{ Name = 'Square150x150Logo.png'; Size = 150 })) {
    $s = $spec.Size
    $bmp = New-Object System.Drawing.Bitmap $s, $s
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.TextRenderingHint = 'AntiAliasGridFit'
    $g.Clear([System.Drawing.Color]::Transparent)
    $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 37, 99, 235))
    $pad = [int]($s * 0.06)
    $g.FillEllipse($brush, $pad, $pad, $s - 2 * $pad, $s - 2 * $pad)
    $font = New-Object System.Drawing.Font 'Segoe UI', ([float]($s * 0.36)), ([System.Drawing.FontStyle]::Bold), ([System.Drawing.GraphicsUnit]::Pixel)
    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment = 'Center'; $fmt.LineAlignment = 'Center'
    $g.DrawString('CR', $font, [System.Drawing.Brushes]::White, (New-Object System.Drawing.RectangleF 0, 0, $s, $s), $fmt)
    $g.Dispose()
    $bmp.Save((Join-Path $OutDir $spec.Name), [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
}
