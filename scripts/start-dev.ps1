# AI Edu 一键启动：后端（8000）+ 前端（3001）
# 用法：
#   本机使用  —— 双击仓库根目录的「启动 AI Edu.cmd」
#   手机使用  —— PowerShell 执行 scripts\start-dev.ps1 -Mobile
#                （或「启动 AI Edu.cmd -Mobile」）：前后端都监听 0.0.0.0，
#                并打印手机浏览器 / Obsidian 插件要填的局域网地址。
param(
    [switch]$Mobile
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "services\api"
$frontendDir = Join-Path $root "apps\web"
$py = Join-Path $backendDir ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== AI Edu 启动器 ===" -ForegroundColor Cyan
if ($Mobile) { Write-Host "手机模式：前后端监听 0.0.0.0，可用局域网地址访问" -ForegroundColor Green }
Write-Host "仓库：$root"
Write-Host ""

if (-not (Test-Path $py)) {
    Write-Host "[错误] 未找到后端虚拟环境：$py" -ForegroundColor Red
    Write-Host "      请先按 README 初始化：cd services/api; python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "[错误] 前端依赖未安装：$frontendDir\node_modules" -ForegroundColor Red
    Write-Host "      请先在 apps/web 下执行：pnpm install（本仓库前端用 pnpm，勿与 npm 混用）"
    exit 1
}

# -Mobile：探测本机局域网 IPv4（排除回环与虚拟网卡），用于打印手机要访问的地址。
# 取所有候选是因为多网卡机器（Wi-Fi + 有线 + 虚拟交换机）上「正确的」IP 不一定是第一个。
$lanIps = @()
if ($Mobile) {
    try {
        $lanIps = @(
            Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -ne "127.0.0.1" -and
                $_.PrefixOrigin -ne "WellKnown" -and
                $_.InterfaceAlias -notmatch "Loopback|vEthernet|VMware|VirtualBox|WSL|Docker"
            } |
            Select-Object -ExpandProperty IPAddress
        )
    } catch { $lanIps = @() }
    if (-not $lanIps) {
        Write-Host "[警告] 未能探测到局域网 IPv4；手机可能连不上。请手动用 ipconfig 查看。" -ForegroundColor Yellow
    }
}

# 如果 8000 已被占用，提示而不是重复启动
$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "[提示] 端口 8000 已有进程在监听（可能是已启动的后端）。" -ForegroundColor Yellow
} else {
    $backendHost = if ($Mobile) { "0.0.0.0" } else { "127.0.0.1" }
    Write-Host "启动后端（新窗口“AI Edu 后端”，端口 8000，监听 $backendHost）..." -ForegroundColor Cyan
    # 端点并发上限：DeepSeek 等云端 API 可开多路（9）；自建单卡端点请改回 "1"
    $env:AIEDU_LLM_CONCURRENCY = "9"
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/k", "title AI Edu 后端 && .venv\Scripts\python.exe -m uvicorn app.main:app --host $backendHost --port 8000" `
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
    if ($Mobile) {
        # next.config.ts 读 AIEDU_DEV_ORIGINS 放开手机访问 dev 资源的 origin 白名单
        $env:AIEDU_DEV_ORIGINS = ($lanIps -join ",")
        Write-Host "启动前端（新窗口“AI Edu 前端”，端口 3001，允许来源：$($env:AIEDU_DEV_ORIGINS)）..." -ForegroundColor Cyan
    } else {
        Write-Host "启动前端（新窗口“AI Edu 前端”，端口 3001）..." -ForegroundColor Cyan
    }
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

if ($Mobile -and $lanIps.Count -gt 0) {
    $primary = $lanIps[0]
    Write-Host ""
    Write-Host "=== 手机端访问（电脑与手机需在同一 Wi-Fi）===" -ForegroundColor Green
    Write-Host ("  · 手机浏览器打开网页端：  http://" + $primary + ":3001") -ForegroundColor White
    Write-Host ("  · Obsidian 插件 API 地址： http://" + $primary + ":8000") -ForegroundColor White
    Write-Host "    （插件设置里把 API base URL 从 127.0.0.1 改成上面这个地址）" -ForegroundColor Gray
    if ($lanIps.Count -gt 1) {
        Write-Host "  · 其它候选 IP（多网卡时按实际 Wi-Fi 选）：" -ForegroundColor Gray
        $lanIps | Select-Object -Skip 1 | ForEach-Object { Write-Host ("      http://" + $_ + ":3001 / http://" + $_ + ":8000") -ForegroundColor Gray }
    }
    Write-Host "  · 若手机连不上：在电脑防火墙放行 TCP 8000 与 3001 端口（首次启动时系统弹窗选「允许」）。" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "使用方式：" -ForegroundColor Gray
Write-Host "  · 关闭「AI Edu 前端」「AI Edu 后端」两个黑窗口即可停止。"
Write-Host "  · 数据保存在 services\api\data\aiedu.db，可定期在「偏好设置」导出 JSON 备份。"
