param([switch]$Launch)

$ErrorActionPreference='Stop'

$taskRoot=[IO.Path]::GetFullPath($PSScriptRoot)

$taskLog=Join-Path $taskRoot 'logs'

[IO.Directory]::CreateDirectory($taskLog) | Out-Null

$taskMarker=Join-Path $taskLog '실행콘솔.json'

$taskOutput=Join-Path $taskLog '실행상태_최근.log'
function Test-ConsoleReset {
    try {
        $taskReset=Get-Content -LiteralPath (Join-Path $taskLog 'full_reset_latest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        return $taskReset.phase -eq 'stopping' -and @($taskReset.old_status_ids) -contains $PID -and
            ([datetime]$taskReset.time) -ge $taskSelf.CreationDate.ToUniversalTime()
    } catch { return $false }
}

$taskLockName='Local\DINO_STATUS_'+([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($taskRoot))).Replace('/','_').Replace('+','_').TrimEnd('=')

$taskMutex=New-Object Threading.Mutex($false,$taskLockName)

if(-not $taskMutex.WaitOne(0)){exit 0}

$taskExit=0

$taskApp=$null

try {

    $taskSelf=Get-CimInstance Win32_Process -Filter "ProcessId=$PID"

    $taskParent=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskSelf.ParentProcessId)"

    $taskCmdId=if($taskParent.Name -eq 'cmd.exe'){$taskParent.ProcessId}else{0}

    $taskDesired='v10'

    try {$taskSaved=Get-Content -LiteralPath (Join-Path $taskRoot '사용버전.json') -Raw -Encoding UTF8 | ConvertFrom-Json;if($taskSaved.family -eq 'api'){$taskDesired='api'}}catch{}

    $taskFamily=if($taskDesired -eq 'api'){'API'}else{'드롭샷'}

    $taskBuild='13.2 몰입형 사용자버전 · 몰입감'
    try {
        $taskBuildMeta=Get-Content -LiteralPath (Join-Path $taskRoot '배포정보.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if($taskBuildMeta.build_label){$taskBuild=[string]$taskBuildMeta.build_label -replace '^DINO\s*',''}
    } catch {}
    $Host.UI.RawUI.WindowTitle="DINO $taskBuild · $taskFamily 실행 상태"

    Write-Host "DINO $taskBuild · $taskFamily 버전 · 빠른 편집" -ForegroundColor Cyan

    if($Launch){

        $taskRuntime=$env:_PYI_APPLICATION_HOME_DIR

        Get-ChildItem Env: | Where-Object {$_.Name -like '_PYI_*' -or $_.Name -in '_MEIPASS2','PYTHONHOME','PYTHONPATH','TCL_LIBRARY','TK_LIBRARY','DINO_COMPONENT_DIR','DINO_PORT','DINO_NO_BROWSER','DINO_EXCLUSIVE_API','DINO_MANAGER_ROOT','DINO_MANAGER_PID'} | ForEach-Object {Remove-Item -LiteralPath ('Env:'+$_.Name)}

        if($taskRuntime){$env:PATH=($env:PATH -split ';' | Where-Object {-not $_.StartsWith($taskRuntime,[StringComparison]::OrdinalIgnoreCase)}) -join ';'}

        $env:PYINSTALLER_RESET_ENVIRONMENT='1'

        $env:DINO_CONSOLE_HOSTED='1'

        $taskApp=Start-Process -FilePath (Join-Path $taskRoot 'DINO.exe') -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru

        Write-Host '프로그램을 시작하고 있습니다. 준비가 완료되면 화면이 열립니다.'

    }else{Write-Host '프로그램 연결과 실제 작업 진행을 표시합니다.'}

    $taskRecord=@{pid=$PID;cmd_pid=$taskCmdId;root=$taskRoot;family=$taskDesired;created=$taskSelf.CreationDate.ToUniversalTime().ToString('o')}

    if($taskApp){$taskRecord.app_pid=$taskApp.Id}

    [IO.File]::WriteAllText($taskMarker,($taskRecord | ConvertTo-Json),[Text.UTF8Encoding]::new($false))

    $taskLast='';$taskLastPrinted=Get-Date;$taskLastSeen=Get-Date;$taskEverSeen=$false

    while($true){
        if(Test-ConsoleReset){$taskExit=0;break}

        if($taskApp){

            $taskApp.Refresh()

            if($taskApp.HasExited){

                $taskExit=if(Test-ConsoleReset){0}else{$taskApp.ExitCode}

                if($taskExit -ne 0){Write-Host "프로그램이 시작되지 않았습니다. 종료 코드: $taskExit" -ForegroundColor Red}

                break

            }

        }

        try {

            $taskSelection=Invoke-RestMethod -Uri 'http://127.0.0.1:5910/api/v10/selection' -TimeoutSec 2

            $taskHub=Invoke-RestMethod -Uri 'http://127.0.0.1:5910/api/v75/hub-version' -TimeoutSec 2

            $taskExpected=if($taskSelection.family -eq 'api'){Join-Path $taskRoot '연결보조\R5_API'}else{$taskRoot}

            if($taskHub.installation -and [IO.Path]::GetFullPath($taskHub.installation).TrimEnd('\') -ne $taskExpected.TrimEnd('\')){break}

            $taskHealth=Invoke-RestMethod -Uri 'http://127.0.0.1:5910/api/health' -TimeoutSec 2

            if(-not $taskHealth.longform -or -not $taskHealth.shorts){throw 'starting'}

            $taskPort=if($taskSelection.mode -eq 'shorts'){5912}else{5911}

            $taskBase="http://127.0.0.1:$taskPort"

            $taskMode=if($taskSelection.mode -eq 'shorts'){'쇼츠'}else{'롱폼'}

            $taskFamily=if($taskSelection.family -eq 'api'){'API'}else{'드롭샷'}

            $Host.UI.RawUI.WindowTitle="DINO $taskBuild · $taskFamily 실행 상태"

            if($taskSelection.family -eq 'api'){

                $taskBoot=Invoke-RestMethod -Uri "$taskBase/api/r5/bootstrap" -TimeoutSec 2

                if($taskBoot.active_id){

                    $taskJob=(Invoke-RestMethod -Uri "$taskBase/api/r5/job/$($taskBoot.active_id)" -TimeoutSec 2).job

                    $taskText="$taskFamily $taskMode | $($taskJob.message) | 이미지 $($taskJob.complete)/$($taskJob.prompt_count)"

                }else{$taskText="$taskFamily $taskMode | 연결 완료 · 새 작업 입력 대기"}

            }else{

                $taskNative=Invoke-RestMethod -Uri "$taskBase/api/status" -TimeoutSec 2

                $taskWriter=Invoke-RestMethod -Uri "$taskBase/api/v10/writer" -TimeoutSec 2

                $taskWriting=$taskWriter.jobs | Where-Object {$_.status -in @('running','stopping')} | Select-Object -First 1

                if($taskWriting){

                    $taskJob=(Invoke-RestMethod -Uri "$taskBase/api/v10/writer/job/$($taskWriting.id)" -TimeoutSec 2).job

                    $taskText="$taskFamily $taskMode | $($taskJob.message) | 대본 $($taskJob.char_count)자 | 프롬프트 $($taskJob.prompt_count)개"

                }else{$taskText="$taskFamily $taskMode | 연결 완료 · $($taskNative.message)"}

            }

            $taskLastSeen=Get-Date;$taskEverSeen=$true

        }catch{$taskText="$taskFamily 버전 시작 중 · 프로그램 연결 확인 중"}

        if($taskText -ne $taskLast -or ((Get-Date)-$taskLastPrinted).TotalSeconds -ge 15){

            $taskLine='['+(Get-Date -Format 'HH:mm:ss')+'] '+$taskText

            Write-Host $taskLine

            [IO.File]::AppendAllText($taskOutput,$taskLine+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))

            $taskLast=$taskText;$taskLastPrinted=Get-Date

        }

        if(((Get-Date)-$taskLastSeen).TotalSeconds -gt $(if($taskEverSeen){15}else{75})){

            if(-not $taskEverSeen){$taskExit=1;Write-Host '프로그램 연결을 확인하지 못했습니다. 오류확인_실행.cmd로 실행 상태를 확인해 주세요.' -ForegroundColor Red}

            break

        }

        Start-Sleep -Seconds 2

    }

}finally{

    try{$taskSaved=Get-Content -LiteralPath $taskMarker -Raw -Encoding UTF8 | ConvertFrom-Json;if($taskSaved.pid -eq $PID){Remove-Item -LiteralPath $taskMarker -ErrorAction SilentlyContinue}}catch{}

    $taskMutex.ReleaseMutex();$taskMutex.Dispose()

}

exit $taskExit

