<#
  Packs Orbit.exe into an MSIX for the Microsoft Store.

  .\build_msix.ps1 -Exe ..\..\host\dist\Orbit.exe -Version 1.1.0 -Out Orbit-Windows-Store.msix

  Identity values come from Partner Center > your app > Product identity. Pass them as
  parameters or set MSIX_IDENTITY_NAME, MSIX_PUBLISHER and MSIX_PUBLISHER_DISPLAY_NAME.
  The Store signs the package itself, so the output is left unsigned.
#>
param(
  [Parameter(Mandatory = $true)] [string] $Exe,
  [Parameter(Mandatory = $true)] [string] $Version,
  [Parameter(Mandatory = $true)] [string] $Out,
  [string] $IdentityName = $(if ($env:MSIX_IDENTITY_NAME) { $env:MSIX_IDENTITY_NAME } else { 'OrbitRemote.Orbit' }),
  [string] $Publisher = $(if ($env:MSIX_PUBLISHER) { $env:MSIX_PUBLISHER } else { 'CN=Orbit Remote' }),
  [string] $PublisherDisplayName = $(if ($env:MSIX_PUBLISHER_DISPLAY_NAME) { $env:MSIX_PUBLISHER_DISPLAY_NAME } else { 'Orbit Remote' })
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# The Store wants a four-part version with the last part 0.
$parts = (($Version -replace '^v', '') -split '[-+]')[0].Split('.') + @('0', '0', '0')
$msixVersion = '{0}.{1}.{2}.0' -f [int]$parts[0], [int]$parts[1], [int]$parts[2]

$layout = Join-Path ([IO.Path]::GetTempPath()) ('orbit-msix-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path (Join-Path $layout 'Assets') | Out-Null
Copy-Item -LiteralPath $Exe -Destination (Join-Path $layout 'Orbit.exe')
Copy-Item -Path (Join-Path $here 'Assets\*.png') -Destination (Join-Path $layout 'Assets')

$esc = { param($v) [Security.SecurityElement]::Escape($v) }
$manifest = Get-Content -LiteralPath (Join-Path $here 'AppxManifest.xml') -Raw
$manifest = $manifest.Replace('$IDENTITY_NAME$', (& $esc $IdentityName))
$manifest = $manifest.Replace('$PUBLISHER_DISPLAY_NAME$', (& $esc $PublisherDisplayName))
$manifest = $manifest.Replace('$PUBLISHER$', (& $esc $Publisher))
$manifest = $manifest.Replace('$VERSION$', $msixVersion)
[IO.File]::WriteAllText((Join-Path $layout 'AppxManifest.xml'), $manifest, (New-Object Text.UTF8Encoding $false))

$makeappx = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" -ErrorAction SilentlyContinue |
  Sort-Object FullName | Select-Object -Last 1
if (-not $makeappx) { throw 'makeappx.exe not found. Install the Windows 10/11 SDK.' }

$outDir = Split-Path -Parent ([IO.Path]::GetFullPath($Out))
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
& $makeappx.FullName pack /d $layout /p $Out /o
if ($LASTEXITCODE -ne 0) { throw "makeappx failed with exit code $LASTEXITCODE" }
Remove-Item -Recurse -Force $layout
Write-Host "Packed $Out ($IdentityName $msixVersion, $Publisher)"
