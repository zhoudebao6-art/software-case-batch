$ErrorActionPreference = 'Stop'
$TaskConfigPath = Join-Path $PSScriptRoot 'local.config.json'
if (-not (Test-Path -LiteralPath $TaskConfigPath -PathType Leaf)) { throw 'local.config.json is required; configure existing Python, Node, Playwright and FFmpeg paths.' }
$TaskSettings = Get-Content -LiteralPath $TaskConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
# A caller may select the cache root before loading this entry. Otherwise use
# this installation's configuration. A junction path must not change defaults.
$TaskCacheRoot = if ($env:SCB_PRO_CACHE_ROOT) { [string]$env:SCB_PRO_CACHE_ROOT } elseif ($TaskSettings.cache_root) { [string]$TaskSettings.cache_root } else { 'E:\codex+' }
if ($TaskCacheRoot -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+)') { throw 'cache_root must be an explicit absolute directory.' }
$TaskCacheRoot = [IO.Path]::GetFullPath($TaskCacheRoot)
$env:SCB_PRO_CACHE_ROOT = $TaskCacheRoot
$env:TEMP = Join-Path $TaskCacheRoot 'temp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $TaskCacheRoot 'cache\pip'
$env:UV_CACHE_DIR = Join-Path $TaskCacheRoot 'cache\uv'
$env:PYTHONPYCACHEPREFIX = Join-Path $TaskCacheRoot 'cache\python-pycache'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:NPM_CONFIG_CACHE = Join-Path $TaskCacheRoot 'cache\npm'
$env:NODE_COMPILE_CACHE = Join-Path $TaskCacheRoot 'cache\node-compile-cache'
$env:YARN_CACHE_FOLDER = Join-Path $TaskCacheRoot 'cache\yarn'
$env:XDG_CACHE_HOME = Join-Path $TaskCacheRoot 'cache'
$env:MPLCONFIGDIR = Join-Path $TaskCacheRoot 'cache\matplotlib\software-case-batch-pro'
# Installed browser binaries are dependencies, not disposable cache. Moving
# TEMP must not silently redirect Playwright to a missing installation.
if ($TaskSettings.playwright_browsers_path) { $env:PLAYWRIGHT_BROWSERS_PATH = [string]$TaskSettings.playwright_browsers_path }
elseif (-not $env:PLAYWRIGHT_BROWSERS_PATH) { $env:PLAYWRIGHT_BROWSERS_PATH = 'D:\codex+\cache\ms-playwright' }
$env:SCB_PRO_PYTHON = $TaskSettings.python
$env:SCB_PRO_NODE = $TaskSettings.node
$env:SCB_PRO_PLAYWRIGHT = $TaskSettings.playwright_module
$env:SCB_PRO_FFMPEG = $TaskSettings.ffmpeg
$env:SCB_PRO_FFPROBE = $TaskSettings.ffprobe
$env:SCB_PRO_OUTPUT_ROOT = if ($TaskSettings.output_root) { [string]$TaskSettings.output_root } else { 'D:\研发图表' }
if (-not [IO.Path]::IsPathRooted($env:SCB_PRO_OUTPUT_ROOT)) { throw 'output_root must be an explicit absolute directory; no fallback delivery location is allowed.' }
$env:SCB_OUTPUT_ROOT = $env:SCB_PRO_OUTPUT_ROOT
foreach ($TaskDirectory in @($env:TEMP,$env:MPLCONFIGDIR,$env:NODE_COMPILE_CACHE)) { New-Item -ItemType Directory -Path $TaskDirectory -Force | Out-Null }
