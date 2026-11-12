param(
  [int]$Seconds = 900,
  [string]$Tag = 'ab1',
  [string]$TargetFrame = '6600',
  [switch]$Fix,          # -Fix enables NX_KEEP_COLOUR_AREA; absent REMOVES it from the child environment
  [switch]$Window
)
# News-clip A/B arm. One run per invocation, archived immediately under its own tag.
#
# WHY THIS EXISTS AS A SEPARATE SCRIPT: the previous arm script baked NX_KEEP_COLOUR_AREA=1 into its own
# environment, so a "control" that merely cleared the variable before calling it was silently a second FIX-ON
# run. The switch is `getenv(...) != nullptr`, so ANY non-null value - including an empty string - enables it.
# Here the variable is explicitly REMOVED unless -Fix is passed, and the run PROVES what the child saw by
# counting the fix's own log line (`KEEPCOLOUR`) afterwards. A control is only a control if that count is 0.
#
# Route and timing are identical to the ab_a arm that first reproduced the rectangle, so the same window is
# reached on the same schedule.
$parts = @(
  '600:A','1000:A','1400:A',
  '2400:A','2500:Right','2600:A','2700:Right','2800:A','3100:A',
  '3400:A','3600:A','3800:A','4000:A','4200:A','4400:A',
  '4600:A','4800:A','5000:A','5200:A','5400:A','5600:A','5800:A',
  '6000:A','6300:A'
)
for ($f = 6400; $f -le 8500; $f += 60) { $parts += "${f}:A" }
for ($f = 6500; $f -le 8000; $f += 8) {
  $parts += "${f}:ZL"
  $parts += "${f}:ZR"
}
for ($i = 0; $i -lt 6; $i++) { $parts += "$(8700 + $i * 40):B" }
for ($f = 10000; $f -le 12400; $f += 30) { $parts += "${f}:RRight" }
for ($f = 13000; $f -le 14400; $f += 30) { $parts += "${f}:LUp" }
$script = $parts -join ','

$env:NX_TUT_AIM_SKIP = '180'
$env:NX_TUT_SHOT_SKIP = '240'
$env:NX_TUT_MOVE_SKIP = '180'
$env:NX_ZLZR_HOLD = '6000-8600'
$env:NX_INPUT = $script

# the instrument (always on, so the control is instrumented too)
$env:NX_CLEAR_AREA = '6a00ffea80'
# the pixel record
$env:NX_DUMP_AT = '6470:40'
$env:NX_DUMP_TEXTURES = '6a00ffea80,6a00ffe910'

# THE SWITCH: set only when -Fix is passed, otherwise removed outright.
if ($Fix) {
    $env:NX_KEEP_COLOUR_AREA = '1'
    Write-Output "ARM: FIX ON  (NX_KEEP_COLOUR_AREA=1)"
} else {
    Remove-Item Env:NX_KEEP_COLOUR_AREA -ErrorAction SilentlyContinue
    Write-Output ("ARM: CONTROL (NX_KEEP_COLOUR_AREA removed; present in this shell? {0})" -f [bool](Test-Path Env:NX_KEEP_COLOUR_AREA))
}

# nothing else may perturb the run
foreach ($v in 'NX_TEXTURE_RACE_OLD','NX_TRACE_PASSES','NX_TRACE_PASSES_FROM_FRAME','NX_STUDIO_SIG','NX_CULL_TRACE','NX_SNAP_PASSES') {
    Remove-Item "Env:$v" -ErrorAction SilentlyContinue
}

# Clear the frame directory so this arm cannot inherit another arm's dumps.
$frames = Join-Path 'C:\Users\Hexa\Documents\nintendo\sp2win' 'private\frames'
Get-ChildItem (Join-Path $frames '*.ppm') -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem (Join-Path $frames '*.pgm') -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
$pre = (Get-ChildItem (Join-Path $frames '*.ppm') -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Output "frames/ cleared before run: $pre files remain"

$runner = Join-Path $PSScriptRoot 'run-tutorial.ps1'
& $runner -Seconds $Seconds -Tag $Tag -DumpEvery 0 -Script $script -TargetFrame $TargetFrame -Attempts 1 -PipeCap 512 -Window:$Window

# ---- ARCHIVE IMMEDIATELY, under this arm's own directory, before anything else can touch frames/ -------------
$dir = 'C:\Users\Hexa\Documents\nintendo\sp2win'
$keep = Join-Path $dir ("private\frames\keep_$Tag")
New-Item -ItemType Directory -Force -Path $keep | Out-Null
$n = 0
Get-ChildItem (Join-Path $frames '*') -Include *.ppm,*.pgm -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $keep $_.Name) -Force
    $n++
}
Copy-Item (Join-Path $dir "$Tag.log") $keep -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $dir "progress_$Tag.txt") $keep -Force -ErrorAction SilentlyContinue

# ---- PROVE WHAT THE CHILD SAW: the fix's own log line, not this wrapper's environment ------------------------
$log = Join-Path $dir "$Tag.log"
$keepcolour = 0
$fires = 0
if (Test-Path $log) {
    $keepcolour = (Select-String -Path $log -Pattern 'KEEPCOLOUR' -AllMatches | Measure-Object).Count
    $fires = (Select-String -Path $log -Pattern 'CLEARAREA f=' -AllMatches | Measure-Object).Count
}
Write-Output ""
Write-Output ("ARM RESULT tag={0} files_archived={1}" -f $Tag, $n)
Write-Output ("  KEEPCOLOUR lines in log : {0}   <- 0 means the fix was genuinely OFF" -f $keepcolour)
Write-Output ("  CLEARAREA fires         : {0}   <- instrument liveness" -f $fires)
if ($Fix -and $keepcolour -eq 0) { Write-Output "  WARNING: -Fix was requested but the fix never fired; treat as fix-off." }
if (-not $Fix -and $keepcolour -gt 0) { Write-Output "  WARNING: CONTROL IS VOID - the fix fired despite being unset." }
