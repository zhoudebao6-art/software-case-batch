$ErrorActionPreference = 'Stop'
$TaskConfigPath = Join-Path $PSScriptRoot 'local.config.json'
if (-not (Test-Path -LiteralPath $TaskConfigPath -PathType Leaf)) { throw 'local.config.json is required; configure existing Python, Node, Playwright and FFmpeg paths.' }
$TaskSettings = Get-Content -LiteralPath $TaskConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$env:TEMP = 'D:\codex+\temp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = 'D:\codex+\cache\pip'
$env:UV_CACHE_DIR = 'D:\codex+\cache\uv'
$env:PYTHONPYCACHEPREFIX = 'D:\codex+\cache\python-pycache'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:NPM_CONFIG_CACHE = 'D:\codex+\cache\npm'
$env:NODE_COMPILE_CACHE = 'D:\codex+\cache\node-compile-cache'
$env:YARN_CACHE_FOLDER = 'D:\codex+\cache\yarn'
$env:XDG_CACHE_HOME = 'D:\codex+\cache'
$env:MPLCONFIGDIR = 'D:\codex+\cache\matplotlib\software-case-batch-pro'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\codex+\cache\ms-playwright'
$env:SCB_PRO_PYTHON = $TaskSettings.python
$env:SCB_PRO_NODE = $TaskSettings.node
$env:SCB_PRO_PLAYWRIGHT = $TaskSettings.playwright_module
$env:SCB_PRO_FFMPEG = $TaskSettings.ffmpeg
$env:SCB_PRO_FFPROBE = $TaskSettings.ffprobe
$env:SCB_PRO_OUTPUT_ROOT = if ($TaskSettings.output_root) { [string]$TaskSettings.output_root } else { 'F:\研发图表' }
if (-not [IO.Path]::IsPathRooted($env:SCB_PRO_OUTPUT_ROOT)) { throw 'output_root must be an explicit absolute directory; no fallback delivery location is allowed.' }
$env:SCB_OUTPUT_ROOT = $env:SCB_PRO_OUTPUT_ROOT
foreach ($TaskDirectory in @($env:TEMP,$env:MPLCONFIGDIR,$env:NODE_COMPILE_CACHE)) { New-Item -ItemType Directory -Path $TaskDirectory -Force | Out-Null }
