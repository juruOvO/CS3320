# ============================================================
#  京剧可视化系统 一键启动
#  - 自动创建 .env.local（让前端连真后端）
#  - 自动检查/安装依赖
#  - 启动后端 (FastAPI, 8000) 和 前端 (Vite, 5180)
#  - 服务就绪后自动打开浏览器
#  - 可重复双击：已在运行的服务会自动跳过
# ============================================================
$ProgressPreference = 'SilentlyContinue'
$root = $PSScriptRoot
Set-Location $root

Write-Host ""
Write-Host "==== 京剧可视化系统 一键启动 ====" -ForegroundColor Cyan
Write-Host ""

function Test-Up($url) {
    try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 1 | Out-Null; return $true }
    catch { return $false }
}

# --- [0/4] 确保 .env.local 存在（前端连真后端的开关）---
$envFile = Join-Path $root '.env.local'
if (-not (Test-Path $envFile)) {
    Write-Host "[0/4] 创建 .env.local（连接真后端）..."
    "VITE_USE_MOCK=false`r`nVITE_API_BASE_URL=http://127.0.0.1:8000/api" | Set-Content -Path $envFile -Encoding ascii
}

# --- [1/4] 后端依赖 ---
Write-Host "[1/4] 检查后端依赖 (fastapi, uvicorn) ..."
python -c "import fastapi, uvicorn" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "      未安装，正在 pip install ..." -ForegroundColor Yellow
    pip install fastapi uvicorn
}

# --- [2/4] 前端依赖 ---
Write-Host "[2/4] 检查前端依赖 (node_modules) ..."
if (-not (Test-Path (Join-Path $root 'node_modules'))) {
    Write-Host "      首次运行，正在 npm install（较慢，请耐心等待）..." -ForegroundColor Yellow
    npm install
}

# --- [3/4] 启动后端 + 前端（已在运行则跳过）---
Write-Host "[3/4] 启动后端(8000) 与 前端(5180) ..."
if (Test-Up "http://127.0.0.1:8000/health") {
    Write-Host "      后端已在运行，跳过。" -ForegroundColor DarkGray
} else {
    Write-Host "      启动后端，会弹出一个窗口。"
    Start-Process powershell -ArgumentList '-NoExit','-Command',"Set-Location '$root'; python -m uvicorn server.main:app --host 127.0.0.1 --port 8000"
}
if (Test-Up "http://localhost:5180/") {
    Write-Host "      前端已在运行，跳过。" -ForegroundColor DarkGray
} else {
    Write-Host "      启动前端，会弹出一个窗口。"
    Start-Process powershell -ArgumentList '-NoExit','-Command',"Set-Location '$root'; npm run dev"
}

# --- [4/4] 等待就绪后开浏览器 ---
Write-Host "[4/4] 等待服务就绪 ..."
function Wait-Ready($url, $name, $timeoutSec = 60) {
    for ($i = 0; $i -lt $timeoutSec; $i++) {
        if (Test-Up $url) {
            Write-Host "      [OK] $name 已就绪" -ForegroundColor Green
            return $true
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "      [!] $name 等待 $timeoutSec 秒仍未就绪" -ForegroundColor Yellow
    return $false
}
$okBackend  = Wait-Ready "http://127.0.0.1:8000/health" "后端"
$okFrontend = Wait-Ready "http://localhost:5180/" "前端"

Write-Host ""
if ($okFrontend) {
    Start-Process "http://localhost:5180"
    Write-Host "已在浏览器打开：http://localhost:5180" -ForegroundColor Cyan
} else {
    Write-Host "前端未就绪，请查看弹出的「前端」窗口里的报错信息。" -ForegroundColor Red
}
Write-Host ""
Write-Host "提示：要停止服务，关闭弹出的「后端」和「前端」两个窗口即可。"
Write-Host "本窗口 4 秒后自动关闭。"
Start-Sleep -Seconds 4
