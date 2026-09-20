# ============================================================
#  AI 科研问答系统 —— 一键启动脚本
#  用法（在项目根目录 lsb-ai-agent/ 下执行）：
#      .\start-all.ps1
#
#  会依次启动：
#      1. MCP 学术检索服务   :8001
#      2. 后端 API           :8124
#      3. 前端 dev server    :3001
#
#  依赖：已按《部署说明.md》创建好 .venv 并安装依赖、配置好 .env
# ============================================================

param(
    [switch]$SkipFrontend,   # 只启动后端 + MCP
    [switch]$SkipMcp         # 不启动 MCP（Agent 会跳过论文检索工具）
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
    Write-Host "❌ 未找到 Python 虚拟环境: $Python" -ForegroundColor Red
    Write-Host "   请先按《部署说明.md》第三章创建 .venv 并安装依赖。" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path (Join-Path $Root 'backend\.env'))) {
    Write-Host "⚠️  未找到 .env，请先执行：" -ForegroundColor Yellow
    Write-Host "   Copy-Item backend\.env.example backend\.env" -ForegroundColor Yellow
}

# 统一控制台编码，避免中文与符号乱码
$env:PYTHONIOENCODING = 'utf-8'

function Test-PortBusy($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return [bool]$conn
}

function Wait-Port($port, $name, $timeoutSec = 60) {
    for ($i = 0; $i -lt $timeoutSec; $i++) {
        if (Test-PortBusy $port) {
            Write-Host "   ✅ $name 已就绪 (端口 $port)" -ForegroundColor Green
            return $true
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "   ⚠️  $name 在 ${timeoutSec}s 内未监听端口 $port，请查看其窗口输出。" -ForegroundColor Yellow
    return $false
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  AI 科研问答系统 · 启动中" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# ---------- 1. MCP 学术检索服务 ----------
if (-not $SkipMcp) {
    if (Test-PortBusy 8001) {
        Write-Host "ℹ️  端口 8001 已被占用，跳过 MCP 启动（可能已在运行）" -ForegroundColor Yellow
    } else {
        Write-Host "`n[1/3] 启动 MCP 学术检索服务 (:8001)..." -ForegroundColor White
        Start-Process -FilePath $Python `
            -ArgumentList 'server.py' `
            -WorkingDirectory (Join-Path $Root 'mcp_server') `
            -WindowStyle Minimized
        Wait-Port 8001 'MCP 服务' 45 | Out-Null
    }
}

# ---------- 2. 后端 API ----------
if (Test-PortBusy 8124) {
    Write-Host "ℹ️  端口 8124 已被占用，跳过后端启动（可能已在运行）" -ForegroundColor Yellow
} else {
    Write-Host "`n[2/3] 启动后端 API (:8124)..." -ForegroundColor White
    Start-Process -FilePath $Python `
        -ArgumentList 'run.py' `
        -WorkingDirectory (Join-Path $Root 'backend') `
        -WindowStyle Minimized
    Wait-Port 8124 '后端 API' 90 | Out-Null
}

# ---------- 3. 前端 ----------
if ($SkipFrontend) {
    Write-Host "`n[3/3] 按要求跳过前端启动" -ForegroundColor Yellow
} else {
    if (Test-PortBusy 3001) {
        Write-Host "ℹ️  端口 3001 已被占用，跳过前端启动（可能已在运行）" -ForegroundColor Yellow
    } else {
        $frontend = Join-Path $Root 'frontend'
        if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
            Write-Host "`n[3/3] 首次运行，安装前端依赖（可能耗时几分钟）..." -ForegroundColor White
            Start-Process -FilePath 'npm.cmd' -ArgumentList 'install' -WorkingDirectory $frontend -Wait
        }
        Write-Host "`n[3/3] 启动前端 dev server (:3001)..." -ForegroundColor White
        Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'dev' `
            -WorkingDirectory $frontend -WindowStyle Minimized
        Wait-Port 3001 '前端' 90 | Out-Null
    }
}

# ---------- 健康检查 ----------
Write-Host "`n----------------------------------------------------------------" -ForegroundColor Cyan
Write-Host "  健康检查" -ForegroundColor Cyan
Write-Host "----------------------------------------------------------------" -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod 'http://localhost:8124/api/health' -TimeoutSec 15
    Write-Host "  后端     : OK  ($($health.title) / $($health.mode))" -ForegroundColor Green
} catch {
    Write-Host "  后端     : 未就绪 — $($_.Exception.Message)" -ForegroundColor Red
}

if (-not $SkipMcp) {
    try {
        Invoke-WebRequest 'http://127.0.0.1:8001/mcp' -TimeoutSec 10 -UseBasicParsing | Out-Null
        Write-Host "  MCP 服务 : OK" -ForegroundColor Green
    } catch {
        # 该端点对 GET 返回 406/405 属正常，能建立连接即视为可用
        if ($_.Exception.Response) {
            Write-Host "  MCP 服务 : OK  (HTTP $([int]$_.Exception.Response.StatusCode))" -ForegroundColor Green
        } else {
            Write-Host "  MCP 服务 : 未就绪 — $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "  访问地址" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  前端界面 : http://localhost:3001" -ForegroundColor White
Write-Host "  后端 API : http://localhost:8124/api/health" -ForegroundColor White
Write-Host "  MCP 服务 : http://127.0.0.1:8001/mcp" -ForegroundColor White
Write-Host "`n  停止服务：关闭对应最小化的窗口，或执行" -ForegroundColor Gray
Write-Host "    Get-NetTCPConnection -LocalPort 8001,8124,3001 -State Listen | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }" -ForegroundColor Gray
