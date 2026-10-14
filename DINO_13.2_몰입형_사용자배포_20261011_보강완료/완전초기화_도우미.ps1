param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][int]$WorkerId
)
$ErrorActionPreference = 'Stop'
$applicationFile = (Resolve-Path -LiteralPath $Executable).Path
$applicationDirectory = [System.IO.Path]::GetDirectoryName($applicationFile)
$launcherFile = Join-Path $applicationDirectory '00_실행.cmd'
if ([System.IO.Path]::GetFileName($applicationFile) -ne 'DINO.exe' -or -not (Test-Path -LiteralPath $launcherFile -PathType Leaf)) {
    throw 'DINO 실행파일과 실행 CMD를 확인하지 못했습니다.'
}
$logFile = Join-Path $applicationDirectory 'logs\full_reset_latest.json'
New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($logFile)) -Force | Out-Null
function Write-ResetLog([string]$Phase, [string]$Message, $Details = @{}) {
    $record = @{phase=$Phase; message=$Message; time=(Get-Date).ToUniversalTime().ToString('o'); worker_id=$WorkerId}
    foreach ($key in $Details.Keys) { $record[$key] = $Details[$key] }
    [System.IO.File]::WriteAllText($logFile, ($record | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
}
function Get-OriginalProcess($Record) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($Record.ProcessId)" -ErrorAction SilentlyContinue
    if ($current -and $current.CreationDate -eq $Record.CreationDate -and $current.ExecutablePath -eq $Record.ExecutablePath) {
        return $current
    }
}
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DinoResetConsole {
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint id);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr process, uint exitCode);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr process, uint timeout);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    public static void End(uint id) {
        IntPtr handle=OpenProcess(0x00100001, false, id);
        if(handle==IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try {
            if(!TerminateProcess(handle,0)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            if(WaitForSingleObject(handle,3000)!=0) throw new Exception("Console exit timed out.");
        }
        finally { CloseHandle(handle); }
    }
}
'@
function Stop-OriginalConsole($Record) {
    if (Get-OriginalProcess $Record) {
        # Windows Terminal keeps failed sessions open. End our own console with
        # exit code zero so its tab closes without touching other terminal tabs.
        try { [DinoResetConsole]::End([uint32]$Record.ProcessId) } catch {
            if (Get-OriginalProcess $Record) { throw '기존 실행 CMD를 종료하지 못했습니다.' }
        }
    }
}
function Close-DinoBrowserWindows {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class DinoResetWindows {
    public delegate bool Enumerate(IntPtr handle, IntPtr unused);
    [DllImport("user32.dll")] public static extern bool EnumWindows(Enumerate callback, IntPtr unused);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr handle, StringBuilder title, int length);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr handle, uint message, IntPtr first, IntPtr second);
}
'@
    $windows = [System.Collections.Generic.List[long]]::new()
    $callback = [DinoResetWindows+Enumerate] {
        param([IntPtr]$handle, [IntPtr]$unused)
        $windowTitle = [System.Text.StringBuilder]::new(512)
        [DinoResetWindows]::GetWindowText($handle, $windowTitle, $windowTitle.Capacity) | Out-Null
        if ($windowTitle.ToString() -match '^DINO (?:v\d+(?:\.\d+)*|8\.1\.1 Master(?: R3)?)(?:\s+API)?(?:\s*[-–·]|$)') {
            [uint32]$browserProcessId = 0
            [DinoResetWindows]::GetWindowThreadProcessId($handle, [ref]$browserProcessId) | Out-Null
            $browserProcess = Get-Process -Id $browserProcessId -ErrorAction SilentlyContinue
            if ($browserProcess.ProcessName -in 'whale','chrome','msedge','firefox') { $windows.Add($handle.ToInt64()) }
        }
        return $true
    }
    [DinoResetWindows]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    foreach ($window in $windows) { [DinoResetWindows]::PostMessage([IntPtr]$window, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null }
    return @($windows)
}
try {
    $processes = @(Get-CimInstance Win32_Process)
    $applicationProcesses = @($processes | Where-Object { $_.Name -eq 'DINO.exe' -and $_.ExecutablePath -eq $applicationFile })
    if ($applicationProcesses.Count -and -not ($applicationProcesses | Where-Object { $_.ProcessId -eq $WorkerId })) {
        throw '실행 세션이 이미 변경됐습니다. 현재 화면에서 다시 시도하세요.'
    }
    $applicationIds = @($applicationProcesses | ForEach-Object { $_.ProcessId })
    $apiApplicationFile = Join-Path $applicationDirectory '연결보조\R5_API\DINO_API.exe'
    do {
        $apiChildren = @($processes | Where-Object {
            $_.ExecutablePath -eq $apiApplicationFile -and
            $applicationIds -contains $_.ParentProcessId -and
            $applicationIds -notcontains $_.ProcessId
        })
        $applicationProcesses += $apiChildren
        $applicationIds = @($applicationProcesses | ForEach-Object { $_.ProcessId })
    } while ($apiChildren.Count)
    $connectedConsoles = @()
    $connectedHosts = @()
    foreach ($process in $applicationProcesses) {
        if ($applicationIds -contains $process.ParentProcessId) { continue }
        $parent = $processes | Where-Object { $_.ProcessId -eq $process.ParentProcessId } | Select-Object -First 1
        if ($parent -and $parent.Name -in 'powershell.exe','pwsh.exe' -and $parent.CommandLine.Contains((Join-Path $applicationDirectory 'DINO_실행상태.ps1'))) {
            $connectedHosts += $parent
            $parent = $processes | Where-Object { $_.ProcessId -eq $parent.ParentProcessId } | Select-Object -First 1
        }
        if ($parent -and $parent.Name -eq 'cmd.exe' -and $parent.CreationDate -le $process.CreationDate) {
            $connectedConsoles += $parent
        }
    }
    # EXE double-clicks use a separate status CMD. Close that reader as well.
    try {
        $statusMarker=Get-Content -LiteralPath (Join-Path $applicationDirectory 'logs\실행콘솔.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $statusHost=$processes | Where-Object {$_.ProcessId -eq $statusMarker.pid} | Select-Object -First 1
        if($statusMarker.root -eq $applicationDirectory -and $statusHost -and $statusHost.Name -in 'powershell.exe','pwsh.exe' -and $statusHost.CommandLine.Contains((Join-Path $applicationDirectory 'DINO_실행상태.ps1'))){
            $connectedHosts += $statusHost
            $statusCmd=$processes | Where-Object {$_.ProcessId -eq $statusHost.ParentProcessId -and $_.Name -eq 'cmd.exe'} | Select-Object -First 1
            if($statusCmd){$connectedConsoles += $statusCmd}
        }
        # A previous helper can have stopped the status reader while its CMD
        # remains. Match the recorded launch time as well as its PID and command.
        if($statusMarker.root -eq $applicationDirectory -and -not $statusHost){
            $statusCmd=$processes | Where-Object {$_.ProcessId -eq $statusMarker.cmd_pid -and $_.Name -eq 'cmd.exe'} | Select-Object -First 1
            if($statusCmd -and $statusCmd.CommandLine -match '(?:00_실행|DINO_실행상태)\.cmd' -and
                ([math]::Abs((([datetime]$statusMarker.created)-$statusCmd.CreationDate.ToUniversalTime()).TotalSeconds)) -lt 5){
                $connectedConsoles += $statusCmd
            }
        }
    }catch{}
    $connectedHosts=@($connectedHosts | Sort-Object ProcessId -Unique)
    $consoleRecoveryFile=Join-Path $applicationDirectory 'logs\full_reset_consoles.json'
    try {
        $consoleRecovery=Get-Content -LiteralPath $consoleRecoveryFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if($consoleRecovery.root -eq $applicationDirectory){
            foreach($record in $consoleRecovery.consoles){
                $remainingConsole=Get-OriginalProcess $record
                if($remainingConsole -and $remainingConsole.Name -eq 'cmd.exe' -and
                    $remainingConsole.CommandLine -match '(?:00_실행|DINO_실행상태)\.cmd'){$connectedConsoles += $remainingConsole}
            }
        }
    }catch{}
    $connectedConsoles=@($connectedConsoles | Sort-Object ProcessId -Unique)
    $consoleRecords=@($connectedConsoles | ForEach-Object {@{ProcessId=$_.ProcessId;CreationDate=$_.CreationDate.ToUniversalTime().ToString('o');ExecutablePath=$_.ExecutablePath}})
    [IO.File]::WriteAllText($consoleRecoveryFile,(@{root=$applicationDirectory;consoles=$consoleRecords} | ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
    $oldWindows = @(Close-DinoBrowserWindows)
    Write-ResetLog 'stopping' '현재 DINO 작업 창과 실행 CMD를 종료합니다.' @{old_process_ids=$applicationIds; old_cmd_ids=@($connectedConsoles | ForEach-Object { $_.ProcessId }); old_status_ids=@($connectedHosts | ForEach-Object { $_.ProcessId }); old_window_handles=$oldWindows}
    try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5910/api/shutdown' -TimeoutSec 4 | Out-Null } catch {}
    $deadline = (Get-Date).AddSeconds(8)
    do {
        $remaining = @($applicationProcesses | Where-Object { Get-OriginalProcess $_ })
        if (-not $remaining.Count) { break }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    foreach ($process in ($remaining | Sort-Object CreationDate -Descending)) {
        if (Get-OriginalProcess $process) { Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop }
    }
    foreach ($reader in $connectedHosts) {
        Stop-OriginalConsole $reader
    }
    foreach ($console in $connectedConsoles) {
        Stop-OriginalConsole $console
    }
    if (@($applicationProcesses | Where-Object { Get-OriginalProcess $_ }).Count) {
        throw 'DINO가 종료되지 않아 재시작을 중단했습니다.'
    }
    if (@($connectedConsoles | Where-Object { Get-OriginalProcess $_ }).Count -or @($connectedHosts | Where-Object { Get-OriginalProcess $_ }).Count) {
        throw '기존 실행 CMD가 종료되지 않아 재시작을 중단했습니다.'
    }
    $apiUpdateFile=Join-Path $applicationDirectory '연결보조\R5_API\DINO_API.update'
    if(Test-Path -LiteralPath $apiUpdateFile -PathType Leaf){
        Move-Item -LiteralPath $apiUpdateFile -Destination $apiApplicationFile -Force
        $apiInfoFile=Join-Path $applicationDirectory '연결보조\R5_API\연결정보.json'
        $apiInfo=Get-Content -LiteralPath $apiInfoFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $apiDigest=[Security.Cryptography.SHA256]::Create()
        $apiStream=[IO.File]::OpenRead($apiApplicationFile)
        try {$apiInfo.adapter_sha256=([BitConverter]::ToString($apiDigest.ComputeHash($apiStream))).Replace('-','').ToLowerInvariant()}
        finally {$apiStream.Dispose();$apiDigest.Dispose()}
        [IO.File]::WriteAllText($apiInfoFile,($apiInfo | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
    }
    Write-ResetLog 'starting' '빈 작업으로 DINO를 다시 실행합니다.'
    $runtimeDirectory=$env:_PYI_APPLICATION_HOME_DIR
    Get-ChildItem Env: | Where-Object { $_.Name -like '_PYI_*' -or $_.Name -in '_MEIPASS2','PYTHONHOME','PYTHONPATH','TCL_LIBRARY','TK_LIBRARY','DINO_COMPONENT_DIR','DINO_PORT','DINO_NO_BROWSER','DINO_EXCLUSIVE_API','DINO_MANAGER_ROOT','DINO_MANAGER_PID','DINO_CONSOLE_HOSTED' } | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
    if($runtimeDirectory){$env:PATH=($env:PATH -split ';' | Where-Object {-not $_.StartsWith($runtimeDirectory,[StringComparison]::OrdinalIgnoreCase)}) -join ';'}
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    $newLauncher = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c', '00_실행.cmd') -WorkingDirectory $applicationDirectory -WindowStyle Normal -PassThru
    $desiredFamily=(Get-Content -LiteralPath (Join-Path $applicationDirectory '사용버전.json') -Raw -Encoding UTF8 | ConvertFrom-Json).family
    $readyPath=if($desiredFamily -eq 'api'){'/api/r5/bootstrap'}else{'/api/r3/bootstrap'}
    $readyDeadline = (Get-Date).AddSeconds(75)
    do {
        $ready = $false
        try {$newSelection=Invoke-RestMethod -Uri 'http://127.0.0.1:5910/api/v10/selection' -TimeoutSec 2;$ready=$newSelection.ok -and $newSelection.family -eq $desiredFamily}catch{}
        foreach ($applicationPort in 5911,5912) {
            try {
                $bootstrap = Invoke-RestMethod -Uri "http://127.0.0.1:$applicationPort$readyPath" -TimeoutSec 2
                if (-not $bootstrap.ok -or $bootstrap.token -match ('_' + $WorkerId + '_')) { $ready = $false }
            } catch { $ready = $false }
        }
        if ($ready) { break }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $readyDeadline)
    if (-not $ready) { throw '프로그램 재실행을 확인하지 못했습니다. 새 CMD 창의 오류 메시지를 확인하세요.' }
    Write-ResetLog 'started' '기존 CMD를 닫고 선택한 버전의 새 프로그램과 CMD를 시작했습니다.' @{family=$desiredFamily;new_cmd_id=$newLauncher.Id;old_process_ids=$applicationIds;old_cmd_ids=@($connectedConsoles | ForEach-Object { $_.ProcessId });old_status_ids=@($connectedHosts | ForEach-Object { $_.ProcessId });old_window_handles=$oldWindows}
} catch {
    Write-ResetLog 'error' $_.Exception.Message
    exit 1
}
