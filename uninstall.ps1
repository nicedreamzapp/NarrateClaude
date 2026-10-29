# NarrateClaude uninstaller for Windows.
#
#   irm https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.ps1 | iex
#   $env:NARRATE_PURGE = "1"; irm .../uninstall.ps1 | iex       (also delete models and the clone)
#   powershell -ExecutionPolicy Bypass -File $HOME\NarrateClaude\uninstall.ps1 [-Purge]
#
# Stops a running whisper-server this install started (by its pid file), removes
# narrate-claude.cmd and the speak / speak.cmd wrappers (only the ones the
# installer wrote), whisper.cpp and the venv. Downloaded models are kept unless
# you purge; purge also deletes the clone in NARRATE_DIR. Never touches ~\.claude.
# Same environment variables as install.ps1.

# No param() block, so the same text also runs through irm | iex.
$ErrorActionPreference = "Stop"
$narratePurge = [bool](@($args) -contains "-Purge")

& {
  param([bool]$purge)
  $SpeakMarker = "speak wrapper installed by NarrateClaude install.ps1"
  function Say([string]$m) { Write-Host "NarrateClaude: $m" }
  function EnvOr([string]$name, [string]$default) {
    $v = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($v)) { return $default } else { return $v }
  }
  if ((EnvOr "NARRATE_PURGE" "0") -eq "1") { $purge = $true }

  $dir    = EnvOr "NARRATE_DIR" (Join-Path $HOME "NarrateClaude")
  $data   = EnvOr "NARRATE_DATA" (Join-Path (EnvOr "LOCALAPPDATA" (Join-Path $HOME "AppData\Local")) "narrateclaude")
  $bindir = EnvOr "KIT_BIN_DIR" (Join-Path $HOME ".local\bin")

  # 1. A whisper-server left behind by a crashed session (pid file in the clone's state).
  $pidFile = Join-Path $dir "dictation\state\whisper-server.pid"
  if (Test-Path $pidFile) {
    $procId = [int]((Get-Content $pidFile -Raw).Trim())
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -eq "whisper-server") { Stop-Process -Id $procId -Force; Say "stopped whisper-server" }
    Remove-Item $pidFile -Force
  }

  # 2. Commands, only the ones this installer wrote.
  $launcher = Join-Path $bindir "narrate-claude.cmd"
  if ((Test-Path $launcher) -and (Select-String -Path $launcher -SimpleMatch "NarrateClaude install.ps1" -Quiet)) {
    Remove-Item $launcher -Force; Say "removed $launcher"
  }
  foreach ($f in @("speak", "speak.cmd")) {
    $p = Join-Path $bindir $f
    if ((Test-Path $p) -and (Select-String -Path $p -SimpleMatch $SpeakMarker -Quiet)) { Remove-Item $p -Force; Say "removed $p" }
  }

  # 3. whisper.cpp and the venv; models only on purge.
  if (Test-Path $data) {
    foreach ($part in @("whisper", "venv")) {
      $p = Join-Path $data $part
      if (Test-Path $p) { Remove-Item $p -Recurse -Force; Say "removed $p" }
    }
    $models = Join-Path $data "models"
    if ($purge) {
      if (Test-Path $models) { Remove-Item $models -Recurse -Force; Say "removed $models" }
      if (-not (Get-ChildItem $data -Force | Select-Object -First 1)) { Remove-Item $data -Force }
    } elseif (Test-Path $models) {
      Say "kept the models in $models (purge deletes them)"
    }
  }

  # 4. Purge: the clone.
  if ($purge -and (Test-Path (Join-Path $dir "dictation\voice\session.py"))) {
    if ($PSScriptRoot -and ((Resolve-Path $PSScriptRoot).Path -eq (Resolve-Path $dir).Path)) {
      Say "left the checkout you ran this from: $dir"
    } else {
      Remove-Item $dir -Recurse -Force; Say "removed $dir"
    }
  }
  Say "uninstalled"
} $narratePurge
