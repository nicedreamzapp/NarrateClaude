# NarrateClaude installer for Windows (PowerShell 5.1 or 7).
#
#   irm https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/install.ps1 | iex
#   powershell -ExecutionPolicy Bypass -File $HOME\NarrateClaude\install.ps1      (from a checkout)
#
# Sets up the same local, open-source voice loop as install.sh:
#   - a Python venv with the mic library, Piper TTS and pywinpty (voice\requirements.txt)
#   - whisper.cpp's official Windows build at a pinned release, checked by sha256
#   - the f16 whisper model that fits this PC's memory, Silero VAD and a Piper voice
#     (voice\models.txt, every file pinned by URL + sha256)
#   - narrate-claude.cmd and speak / speak.cmd in %USERPROFILE%\.local\bin
# A speak you already have is never replaced. Never edits ~\.claude and never
# starts the microphone.
#
# irm | iex can't take parameters, so options are environment variables:
#   NARRATE_DIR           where to clone (default ~\NarrateClaude)
#   NARRATE_REPO          git URL or local path to clone
#   NARRATE_DATA          whisper.cpp, models, venv (default %LOCALAPPDATA%\narrateclaude)
#   NARRATE_WHISPER_MODEL large-v3-turbo | small.en | base.en | tiny.en (default: by RAM)
#   NARRATE_SKIP_MODEL    1 = download no models
#   NARRATE_PYTHON        Python 3.10+ to build the venv with
#   KIT_BIN_DIR           where the commands go (default ~\.local\bin)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

& {
  $WhisperBuild = "b5454"   # the Windows binaries of whisper.cpp v1.9.5 (commit d1be6fd)
  $WhisperZips = @{
    AMD64 = @{ File = "whisper-bin-x64.zip";           Sha = "6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb" }
    ARM64 = @{ File = "whisper-bin-win-cpu-arm64.zip"; Sha = "28c37e7b598c3d9bbfef94f3bd67f2ee6f12b7c86f3da5edcf5e4308d615ff6d" }
  }
  $SpeakMarker = "speak wrapper installed by NarrateClaude install.ps1"

  function Say([string]$m) { Write-Host "NarrateClaude: $m" }
  function Die([string]$m) { Write-Host "NarrateClaude: ERROR: $m" -ForegroundColor Red; throw $m }
  function EnvOr([string]$name, [string]$default) {
    $v = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($v)) { return $default } else { return $v }
  }
  function Sha256([string]$p) { (Get-FileHash -Algorithm SHA256 -Path $p).Hash.ToLower() }
  function Is-Checkout([string]$d) {
    (Test-Path (Join-Path $d "narrative-claude.sh")) -and (Test-Path (Join-Path $d "dictation\voice\session.py"))
  }

  $repo   = EnvOr "NARRATE_REPO" "https://github.com/nicedreamzapp/NarrateClaude"
  $dir    = EnvOr "NARRATE_DIR" (Join-Path $HOME "NarrateClaude")
  $data   = EnvOr "NARRATE_DATA" (Join-Path (EnvOr "LOCALAPPDATA" (Join-Path $HOME "AppData\Local")) "narrateclaude")
  $bindir = EnvOr "KIT_BIN_DIR" (Join-Path $HOME ".local\bin")
  $skipModel = (EnvOr "NARRATE_SKIP_MODEL" "0") -eq "1"

  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git is required (winget install Git.Git)" }

  # 1. Checkout: the one this script sits in, else clone / update NARRATE_DIR.
  $src = $null
  if ($PSScriptRoot -and (Is-Checkout $PSScriptRoot)) { $src = $PSScriptRoot }
  if (-not $src) {
    if (Is-Checkout $dir) {
      $dirty = git -C $dir status --porcelain --untracked-files=no
      if ($dirty) { Say "local edits in $dir, skipping update" }
      else { git -C $dir pull --ff-only -q; if ($LASTEXITCODE -ne 0) { Say "warning: could not update $dir, using it as is" } }
    } elseif ((Test-Path $dir) -and (Get-ChildItem $dir -Force | Select-Object -First 1)) {
      Die "$dir exists and is not a NarrateClaude checkout; set NARRATE_DIR"
    } else {
      git clone -q $repo $dir
      if ($LASTEXITCODE -ne 0) { Die "git clone $repo failed" }
    }
    $src = (Resolve-Path $dir).Path
  }
  $voice = Join-Path $src "dictation\voice"
  New-Item -ItemType Directory -Force -Path (Join-Path $data "models") | Out-Null

  # 2. Python venv with the voice packages.
  $venvPy = Join-Path $data "venv\Scripts\python.exe"
  $req = Join-Path $voice "requirements.txt"
  $stamp = Join-Path $data "venv\.requirements"
  if ((Test-Path $venvPy) -and (Test-Path $stamp) -and ((Get-Content $req -Raw) -eq (Get-Content $stamp -Raw))) {
    Say "voice packages already installed"
  } else {
    if (-not (Test-Path $venvPy)) {
      $cands = @()
      $np = EnvOr "NARRATE_PYTHON" ""
      if ($np) { $cands += ,@($np) }
      if (Get-Command py -ErrorAction SilentlyContinue) { foreach ($v in "3.13", "3.12", "3.11", "3.10") { $cands += ,@("py", "-$v") } }
      $cands += ,@("python")
      $made = $false
      foreach ($c in $cands) {
        $exe = $c[0]; $rest = @($c | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        # Windows PowerShell turns a probe's stderr into an error, so catch it.
        $ok = $null
        try { $ok = & $exe @rest -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null } catch { $ok = $null }
        if ($ok -ne "1") { continue }
        Say "creating the voice venv with $($c -join ' ')"
        & $exe @rest -m venv (Join-Path $data "venv")
        if ($LASTEXITCODE -eq 0) { $made = $true; break }
      }
      if (-not $made) { Die "Python 3.10+ is required (winget install Python.Python.3.13)" }
    }
    Say "installing voice packages (Piper, mic, pty) ..."
    & $venvPy -m pip install -q --disable-pip-version-check -r $req
    if ($LASTEXITCODE -ne 0) { Die "pip install failed" }
    Copy-Item $req $stamp -Force
  }

  # 3. whisper.cpp: the official Windows build, pinned and checksummed.
  $arch = $env:PROCESSOR_ARCHITECTURE
  if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
  if (-not $WhisperZips.ContainsKey($arch)) { Die "no whisper.cpp Windows build for $arch" }
  $zipInfo = $WhisperZips[$arch]
  $wdir = Join-Path $data "whisper"
  $wstamp = Join-Path $wdir ".narrate-build"
  if ((Test-Path (Join-Path $wdir "Release\whisper-server.exe")) -and (Test-Path $wstamp) -and ((Get-Content $wstamp -Raw).Trim() -eq $zipInfo.Sha)) {
    Say "whisper.cpp v1.9.5 already installed"
  } else {
    $zip = Join-Path $data $zipInfo.File
    Say "downloading whisper.cpp v1.9.5 ($($zipInfo.File)) ..."
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/ggml-org/whisper.cpp/releases/download/$WhisperBuild/$($zipInfo.File)" -OutFile $zip
    if ((Sha256 $zip) -ne $zipInfo.Sha) { Remove-Item $zip -Force; Die "checksum mismatch for $($zipInfo.File)" }
    if (Test-Path $wdir) { Remove-Item $wdir -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $wdir -Force
    Remove-Item $zip -Force
    if (-not (Test-Path (Join-Path $wdir "Release\whisper-server.exe"))) { Die "whisper-server.exe missing from the zip" }
    Set-Content -Path $wstamp -Value $zipInfo.Sha
  }

  # 4. Models, pinned by URL + sha256 in voice\models.txt.
  function Fetch-Model([string]$want) {
    foreach ($line in Get-Content (Join-Path $voice "models.txt")) {
      if ($line -match '^\s*(#|$)') { continue }
      $f = -split $line
      if ($f[0] -ne $want) { continue }
      $dest = Join-Path (Join-Path $data "models") ($f[2] -replace '/', '\')
      if ((Test-Path $dest) -and ((Sha256 $dest) -eq $f[1])) { Say "have $($f[2])"; return }
      New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
      Say "downloading $($f[2]) ..."
      Invoke-WebRequest -UseBasicParsing -Uri $f[3] -OutFile "$dest.part"
      if ((Sha256 "$dest.part") -ne $f[1]) { Remove-Item "$dest.part" -Force; Die "checksum mismatch for $($f[2])" }
      Move-Item "$dest.part" $dest -Force
      return
    }
    Die "unknown model '$want' (see dictation\voice\models.txt)"
  }
  if ($skipModel) {
    Say "NARRATE_SKIP_MODEL=1: not downloading models"
  } else {
    $model = EnvOr "NARRATE_WHISPER_MODEL" ""
    if (-not $model) {
      $model = (& $venvPy -c "import sys; sys.path.insert(0, sys.argv[1]); import common; print(common.model_for_ram(common.total_ram_gib()))" $voice).Trim()
    }
    Say "speech model: $model (full precision f16)"
    foreach ($m in @($model, "silero-vad", "piper-voice-config", "piper-voice")) { Fetch-Model $m }
  }

  # 5. Commands: narrate-claude.cmd, and speak (Git Bash, where Claude Code runs
  #    its commands) + speak.cmd, only when you have no speak of your own.
  New-Item -ItemType Directory -Force -Path $bindir | Out-Null
  $session = Join-Path $voice "session.py"
  Set-Content -Path (Join-Path $bindir "narrate-claude.cmd") -Encoding Ascii -Value @(
    "@echo off",
    "rem launcher installed by NarrateClaude install.ps1",
    "set `"NARRATE_DATA=$data`"",
    "set `"CLAUDE_SESSION_LABEL=NarrativeClaude`"",
    "cd /d `"$src`"",
    "`"$venvPy`" `"$session`" %* -- claude"
  )
  $speakSh = Join-Path $bindir "speak"
  $speakCmd = Join-Path $bindir "speak.cmd"
  $mine = (Test-Path $speakSh) -and (Select-String -Path $speakSh -SimpleMatch $SpeakMarker -Quiet)
  if ((Test-Path $speakSh) -and -not $mine) {
    Say "keeping your existing $speakSh"
  } else {
    $pyFwd = $venvPy -replace '\\', '/'
    $spFwd = (Join-Path $voice "speak.py") -replace '\\', '/'
    $text = "#!/bin/bash`n# $SpeakMarker`n# The local Piper voice. Replace this file with your own TTS any time.`nexport NARRATE_DATA='$data'`nexec '$pyFwd' '$spFwd' `"`$@`"`n"
    [IO.File]::WriteAllText($speakSh, $text)
    Set-Content -Path $speakCmd -Encoding Ascii -Value @(
      "@echo off", "rem $SpeakMarker", "set `"NARRATE_DATA=$data`"",
      "`"$venvPy`" `"$(Join-Path $voice 'speak.py')`" %*")
    Say "created $speakSh and speak.cmd (Piper voice, local)"
  }

  Write-Host ""
  Write-Host "NarrateClaude installed in $src (voice loop in $data)"
  Write-Host "  Start it:  narrate-claude     (claude runs inside the voice loop, in this terminal)"
  Write-Host "Speech to text is whisper.cpp running on this PC; nothing leaves it."
  Write-Host "Windows asks for Microphone access the first time; allow it for your terminal."
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if (-not $userPath) { $userPath = "" }
  if (-not (($userPath -split ';') -contains $bindir)) {
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(';') + ";" + $bindir), "User")
    Say "added $bindir to your user PATH (open a new terminal)"
  }
  Say "done"
  Say "uninstall: irm https://raw.githubusercontent.com/nicedreamzapp/NarrateClaude/main/uninstall.ps1 | iex"
}
