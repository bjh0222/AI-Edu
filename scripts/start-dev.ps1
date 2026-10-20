# AI Edu 一键启动：后端（8000）+ 前端（3001）
# 用法：双击仓库根目录的「启动 AI Edu.cmd」，或在 PowerShell 执行本脚本。

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "services\api"
$frontendDir = Join-Path $root "apps\web"
$py = Join-Path $backendDir ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== AI Edu 启动器 ===" -ForegroundColor Cyan
Write-Host "仓库：$root"
Write-Host ""

if (-not (Test-Path $py)) {
    Write-Host "[错误] 未找到后端虚拟环境：$py" -ForegroundColor Red
    Write-Host "      请先按 README 初始化：cd services/api; python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "[错误] 前端依赖未安装：$frontendDir\node_modules" -ForegroundColor Red
    Write-Host "      请先在 apps/web 下执行：npm install"
    exit 1
}

# 如果 8000 已被占用，提示而不是重复启动
$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "[提示] 端口 8000 已有进程在监听（可能是已启动的后端）。" -ForegroundColor Yellow
} else {
    Write-Host "启动后端（新窗口“AI Edu 后端”，端口 8000）..." -ForegroundColor Cyan
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/k", "title AI Edu 后端 && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000" `
        -WorkingDirectory $backendDir
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { break }
        } catch { }
    }
    Write-Host "后端已就绪：http://127.0.0.1:8000/docs" -ForegroundColor Green
}

# 前端：3001 空闲则用 3001；被占用则 Next 自动顺延，实际端口看“AI Edu 前端”窗口输出
if (-not (Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue)) {
    Write-Host "启动前端（新窗口“AI Edu 前端”，端口 3001）..." -ForegroundColor Cyan
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/k", "title AI Edu 前端 && npm run dev" `
        -WorkingDirectory $frontendDir
} else {
    Write-Host "[提示] 端口 3001 已被占用，前端可能已在运行；若未运行请查看已有窗口。" -ForegroundColor Yellow
}

# 等待前端就绪并打开浏览器
$url = "http://127.0.0.1:3001"
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { break }
    } catch { }
}
Write-Host ""
Write-Host "打开浏览器：$url" -ForegroundColor Green
Start-Process $url
Write-Host ""
Write-Host "使用方式：" -ForegroundColor Gray
Write-Host "  · 关闭「AI Edu 前端」「AI Edu 后端」两个黑窗口即可停止。"
Write-Host "  · 数据保存在 services\api\data\aiedu.db，可定期在「偏好设置」导出 JSON 备份。"
