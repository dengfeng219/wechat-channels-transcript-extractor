# 直接下载 PyTorch wheel（绕过 pip 的下载器；.NET HttpClient + 断点续传 + 多镜像回退）
# 实测速度：上海交大 ~88 MB/s，官方源 ~40 MB/s，阿里云 ~0.5 MB/s（限速），故按此顺序尝试。
param([string]$Proj = (Split-Path -Parent $MyInvocation.MyCommand.Path))
Add-Type -AssemblyName System.Net.Http
$dir = Join-Path $Proj 'wheels'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
$sources = @(
  'https://mirror.sjtu.edu.cn/pytorch-wheels/cu124/',
  'https://download.pytorch.org/whl/cu124/',
  'https://mirrors.aliyun.com/pytorch-wheels/cu124/'
)
$wheels = @(
  @{ name='torch-2.6.0+cu124-cp313-cp313-win_amd64.whl';      size=2532308219 },
  @{ name='torchaudio-2.6.0+cu124-cp313-cp313-win_amd64.whl'; size=4157703 }
)

foreach ($w in $wheels) {
  $out = Join-Path $dir $w.name
  if ((Test-Path $out) -and (Get-Item $out).Length -eq $w.size) {
    Write-Host "[skip] $($w.name) already complete"; continue
  }
  foreach ($base in $sources) {
    $have = if (Test-Path $out) { (Get-Item $out).Length } else { 0 }
    if ($have -ge $w.size) { break }
    Write-Host "[source] $base  (resume at $([math]::Round($have/1MB)) MB)"
    $url = $base + [uri]::EscapeDataString($w.name)
    $fail = 0
    while ($fail -lt 4 -and $have -lt $w.size) {
      try {
        $client = New-Object System.Net.Http.HttpClient
        $client.Timeout = [TimeSpan]::FromMinutes(20)
        $req = New-Object System.Net.Http.HttpRequestMessage('Get', $url)
        # 阿里云镜像对无 User-Agent 的请求返回 403
        $req.Headers.TryAddWithoutValidation('User-Agent', $UA) | Out-Null
        if ($have -gt 0) { $req.Headers.Range = New-Object System.Net.Http.Headers.RangeHeaderValue($have, $null) }
        $resp = $client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).Result
        if ($resp.StatusCode -ne 'OK' -and $resp.StatusCode -ne 'PartialContent') { throw "HTTP $($resp.StatusCode)" }
        $stream = $resp.Content.ReadAsStreamAsync().Result
        $mode = if ($have -gt 0) { [System.IO.FileMode]::Append } else { [System.IO.FileMode]::Create }
        $fs = New-Object System.IO.FileStream($out, $mode, [System.IO.FileAccess]::Write)
        $buf = New-Object byte[] 8388608
        $sw = [Diagnostics.Stopwatch]::StartNew(); $last = 0.0; $mark = $have
        while ($true) {
          $n = $stream.Read($buf, 0, $buf.Length)
          if ($n -le 0) { break }
          $fs.Write($buf, 0, $n); $have += $n
          if ($sw.Elapsed.TotalSeconds - $last -gt 4) {
            $last = $sw.Elapsed.TotalSeconds
            Write-Host ("    {0:N0}/{1:N0} MB  {2:N1} MB/s" -f ($have/1MB), ($w.size/1MB), ((($have-$mark)/1MB)/$sw.Elapsed.TotalSeconds))
            $mark = $have; $sw.Restart()
          }
        }
        $fs.Flush(); $fs.Close(); $stream.Close(); $client.Dispose()
      } catch {
        $fail++
        Write-Host "    interrupted: $($_.Exception.Message)"
        Start-Sleep -Seconds 2
      }
    }
    if ((Test-Path $out) -and (Get-Item $out).Length -eq $w.size) { break }
  }
  $final = if (Test-Path $out) { (Get-Item $out).Length } else { 0 }
  $verdict = if ($final -eq $w.size) { 'OK' } else { 'INCOMPLETE' }
  Write-Host "[result] $($w.name) = $final / $($w.size) $verdict"
}
Write-Host "WHEELS_DONE"
