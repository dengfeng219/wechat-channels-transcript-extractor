# 视频号文案提取器 —— 环境安装脚本
# 网络说明：PyTorch 走多镜像直接下载（pip 自有下载器在国内易断流）；其余依赖走清华 PyPI。
$ErrorActionPreference = 'Continue'
$Proj   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv   = Join-Path $Proj '.venv'
$Py     = Join-Path $Venv 'Scripts\python.exe'
$MIRROR = 'https://pypi.tuna.tsinghua.edu.cn/simple'
$COMMON = @('--retries','10','--timeout','60','--disable-pip-version-check')

Write-Host "== [1/5] 创建虚拟环境 ==" -ForegroundColor Cyan
if (-not (Test-Path $Py)) {
    # 找一个可用的 Python：PATH 里的 python -> py 启动器 -> 常见安装位置
    # （不要写死路径，否则换台电脑就跑不了）
    $sysPy = $null
    $cand = @()
    $w = Get-Command python -ErrorAction SilentlyContinue
    if ($w) { $cand += $w.Source }
    $w2 = Get-Command py -ErrorAction SilentlyContinue
    if ($w2) { $cand += @('py', '-3') }
    $cand += (Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    $cand += @('C:\Python313\python.exe', 'C:\Python312\python.exe', 'C:\Python311\python.exe')
    foreach ($c in $cand) {
        try {
            if ($c -is [array]) { & $c[0] $c[1] --version *> $null } else { & $c --version *> $null }
            if ($LASTEXITCODE -eq 0) { $sysPy = $c; break }
        } catch { }
    }
    if (-not $sysPy) {
        Write-Host "[错误] 没找到 Python，请先安装 Python 3.10~3.13（勾选 Add to PATH）" -ForegroundColor Red
        Write-Host "       下载地址: https://www.python.org/downloads/" -ForegroundColor Yellow
        exit 1
    }
    Write-Host ("  使用 Python: " + ($sysPy -join ' ')) -ForegroundColor Gray
    if ($sysPy -is [array]) { & $sysPy[0] $sysPy[1] -m venv $Venv } else { & $sysPy -m venv $Venv }
}
& $Py -m pip install --upgrade pip -i $MIRROR @COMMON

Write-Host "== [2/5] 下载 PyTorch 2.6.0 + CUDA 12.4（约 2.5 GB，多镜像自动选快） ==" -ForegroundColor Cyan
& (Join-Path $Proj 'fetch_wheels.ps1') -Proj $Proj

Write-Host "== [3/5] 安装 PyTorch ==" -ForegroundColor Cyan
$wheels = Join-Path $Proj 'wheels'
& $Py -m pip install (Join-Path $wheels 'torch-2.6.0+cu124-cp313-cp313-win_amd64.whl') (Join-Path $wheels 'torchaudio-2.6.0+cu124-cp313-cp313-win_amd64.whl') @COMMON

Write-Host "== [4/5] 安装音频解码与中文识别依赖 ==" -ForegroundColor Cyan
& $Py -m pip install -i $MIRROR @COMMON av requests numpy modelscope faster-whisper funasr
# huggingface_hub 1.x 会让 faster-whisper 报 metadata_errors，钉回 0.x
& $Py -m pip install -i $MIRROR @COMMON "huggingface_hub<1.0"

Write-Host "== [5/5] 验证 ==" -ForegroundColor Cyan
& $Py -c "import torch;print('torch',torch.__version__,'| CUDA',torch.cuda.is_available(),'|',(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'))"
& $Py -c "import av;print('PyAV',av.__version__)"
& $Py -c "import faster_whisper;print('faster-whisper OK')"
& $Py -c "import funasr;print('FunASR',funasr.__version__)"
& $Py -c "import requests, numpy;print('requests/numpy OK')"
Write-Host "SETUP_DONE" -ForegroundColor Green
