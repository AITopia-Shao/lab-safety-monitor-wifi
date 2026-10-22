param([switch]$Live)
$ErrorActionPreference='Stop'
$source=Join-Path $PSScriptRoot 'labguard'
$python=Join-Path $source '.runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '比赛版独立环境缺失。' }
$runtime=Join-Path $source 'runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$argsList=@('-u','run_app.py')
if (-not $Live) { $argsList += '--samples' }
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$process=Start-Process -FilePath $python -ArgumentList $argsList -WorkingDirectory $source -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime "$stamp-out.log") -RedirectStandardError (Join-Path $runtime "$stamp-error.log") -PassThru
Set-Content -LiteralPath (Join-Path $runtime 'process-id.txt') -Value $process.Id -Encoding ascii
