# 本地一键爬取（双击或在终端运行 .\run_local.ps1）
# 参数请在 run_local.py 顶部的「参数区」修改
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "未找到虚拟环境 $python，请先创建 .venv 并安装依赖。" -ForegroundColor Red
    exit 1
}
& $python (Join-Path $PSScriptRoot "run_local.py") @args
