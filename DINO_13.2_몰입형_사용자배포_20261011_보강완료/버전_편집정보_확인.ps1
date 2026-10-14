$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath($PSScriptRoot)
$taskMeta=Get-Content -LiteralPath (Join-Path $taskRoot '배포정보.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskEngineRows=@()
foreach($taskEntry in $taskMeta.current_engines.PSObject.Properties){
    $taskPath=Join-Path $taskRoot $taskEntry.Name
    $taskActual=(Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $taskEngineRows += [pscustomobject]@{file=$taskEntry.Name;sha256=$taskActual;matchesRelease=($taskActual -eq $taskEntry.Value.sha256);fpsIfMatches=$taskEntry.Value.rendering_fps}
}
$taskCpu=Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
$taskOs=Get-CimInstance Win32_OperatingSystem | Select-Object Caption,TotalVisibleMemorySize,FreePhysicalMemory
$taskGpu=Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion
$taskResult=[ordered]@{checkedAt=(Get-Date).ToString('o');version=$taskMeta.version;build=$taskMeta.build_label;engines=$taskEngineRows;cpu=$taskCpu;memoryKiB=$taskOs;graphics=$taskGpu;ffmpegProcesses=@(Get-Process ffmpeg -ErrorAction SilentlyContinue | Select-Object Id,CPU,WorkingSet64);containsApiKeys=$false}
$taskLog=Join-Path $taskRoot 'logs'
[IO.Directory]::CreateDirectory($taskLog) | Out-Null
$taskOutput=Join-Path $taskLog '버전_편집정보.json'
$taskResult | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $taskOutput -Encoding UTF8
Write-Host $taskMeta.build_label -ForegroundColor Cyan
if(@($taskEngineRows | Where-Object {-not $_.matchesRelease}).Count -eq 0){Write-Host '설치 파일 확인 완료 · 30fps 빠른 편집' -ForegroundColor Green}else{Write-Host '배포본과 다른 실행 파일이 있습니다. 확인 결과를 전달해 주세요.' -ForegroundColor Yellow}
Write-Host ('확인 파일: '+$taskOutput)
