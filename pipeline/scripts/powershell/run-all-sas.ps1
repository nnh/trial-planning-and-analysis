# run-all-sas.ps1
#
# SAS 側の解析を受領CSVから図表まで一続きで回す。実行の順序はここが正本。
#
#   pwsh -File scripts/run-all-sas.ps1                    ... UTF-8 セッション（既定）
#   pwsh -File scripts/run-all-sas.ps1 -Encoding sjis     ... 従来の shift-jis セッション
#   pwsh -File scripts/run-all-sas.ps1 -Only ARD,TLF      ... 一部だけ回す
#   pwsh -File scripts/run-all-sas.ps1 -LogDir <dir>      ... ログの置き場を変える
#   pwsh -File scripts/run-all-sas.ps1 -Root <dir>        ... 入出力を別の試験フォルダへ振り替える
#   pwsh -File scripts/run-all-sas.ps1 -NoGate            ... 品質検査の停止条件を外して通す
#
# Dataset-JSON の後処理（BOM 除去・JSON として読めることの確認）と define.xml の更新・
# CORE 検証は含まない。それぞれ run-adam-json.ps1・run-sdtm-validation.ps1 が持つ。
#
# 前提：受領CSVが Box の input/rawdata 直下に展開されていること。

param(
  [ValidateSet('utf8', 'sjis')][string]$Encoding = 'utf8',
  [string]$Root,
  [string]$LogDir,
  [string[]]$Only,
  [switch]$NoGate
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'sas-common.ps1')

# 試験 ID は docs/metadata/trial.json だけが持つ。プログラム名の組み立てに使う。
$trialId = (Get-TrialConfig).trial_id

# -Root を渡すと、入力・出力・ログの置き場をまとめてその下へ振り替える。本番の試験
# フォルダを読み書きせずに検証するための口で、autoexec.sas・sas-common.ps1・R 側の
# 試験フォルダ解決の3つが同じ場所を指すように環境変数を1つ立てる。SAS は Start-Process
# の子プロセスとして環境変数を継承するので、これで autoexec に届く。
# 2026-08-29 まで試験ごとの名前（<試験ID>_ROOT）も併せて立てていた。名前の組み立て方が
# 枠組みと試験側で食い違っており、2試験目で黙って空振りする形だったのでやめた。
# 環境変数の名前は試験に依存させない。試験IDから名前を作ると、作り方を共有する必要が
# 生じ、その共有が破れても誰も気づかない（見つかったときの症状は「-Root が効かない」）。
if ($Root) {
  if (-not (Test-Path -LiteralPath $Root)) { throw "-Root が指す場所がありません: $Root" }
  $env:AKIKO_TRIAL_ROOT = (Resolve-Path -LiteralPath $Root).Path
  Write-Host "出力先の差し替え（検証用）: $env:AKIKO_TRIAL_ROOT"
}

$repo = Split-Path $PSScriptRoot -Parent
$box  = Get-TrialRoot

# 実行の順序。ARD の後に ARDtoCards、ADaM の後に JSON という依存があるので並べ替えない。
# 品質検査（QC01・QC03・QC04）は ADaM の後、ARD より前に置く。ADaM に論理矛盾があるまま
# 図表まで作ってしまうと、出来上がった図表を見て初めて気づくことになる
# （docs/records/independent-review-codex-kimi-20260822.md の「停止条件化」）。GateOn を持つ段階は
# ログに該当パターンが出たらそこで止める（調べるだけなら -NoGate で外す）。パターンは行頭に
# 錨を打つ。SAS のログはソースをエコーするので、%put の書かれた行そのものが引っかかる
# （2026-08-24 に QC03 のゲートが不一致0でも止まった）。
$steps = @(
  @{ Tag = 'CSVtoSDTM';    Program = "program\sas\${trialId}_CSVtoSDTM.sas" }
  @{ Tag = 'SDTMtoADaM';   Program = "program\sas\${trialId}_SDTMtoADaM.sas" }
  @{ Tag = 'QC01';         Program = 'program\sas\qc\<試験ID>_QC01_RawDataScan.sas' }
  @{ Tag = 'QC03';         Program = 'program\sas\qc\<試験ID>_QC03_TTECheck.sas';
     GateOn = '^WARNING: \[QC03\] 検算表と不一致' }
  @{ Tag = 'QC04';         Program = 'program\sas\qc\<試験ID>_QC04_CMRCheck.sas' }
  @{ Tag = 'ARD';          Program = "program\sas\${trialId}_ARD.sas";
     WaitFor = 'datasets\sas\ard\ard.sas7bdat' }
  @{ Tag = 'ARDtoCards';   Program = "program\sas\${trialId}_ARDtoCards.sas" }
  # 図表は output/tlf/sas-<lang>/ に出る（TLF.sas の既定で tlfhtml=1）。R 側は
  # output/tlf/r-<lang>/ なので系統でディレクトリが分かれ、名前が衝突しない。
  # トレーサビリティ索引と PI パッケージが読むのは R 側である
  @{ Tag = 'TLF_ja';       Program = "program\sas\${trialId}_TLF.sas";  InitStmt = '%let lang=ja;' }
  @{ Tag = 'TLF_en';       Program = "program\sas\${trialId}_TLF.sas";  InitStmt = '%let lang=en;' }
  @{ Tag = 'ADaMtoMaster'; Program = "program\sas\${trialId}_ADaMtoMaster.sas" }
  @{ Tag = 'SDTMtoJSON';   Program = "program\sas\${trialId}_SDTMtoJSON.sas" }
  @{ Tag = 'ADaMtoJSON';   Program = "program\sas\${trialId}_ADaMtoJSON.sas" }
)

if ($Only) {
  # ssh 経由（run-remote-sas.sh 越し）で呼ぶと、PowerShell 自身のコンマ区切り配列展開が
  # 効かず "-Only ARD,TLF" が1本の文字列として届く。[string[]] の各要素をさらにコンマで
  # 割ることで、ローカル起動（配列に分かれる）とリモート起動（1本の文字列）の両方を
  # 同じ形で扱う（2026-08-23 に実測。リモートから -Only を渡すと該当0件で落ちていた）。
  $onlySet = $Only | ForEach-Object { $_ -split ',' } | Where-Object { $_ }
  $steps = $steps | Where-Object { $onlySet -contains $_.Tag }
  if (-not $steps) { throw "-Only に該当する段階がありません（指定: $($onlySet -join ', ')）" }
}

Write-Host "SAS セッションの符号化: $Encoding"
Write-Host "Box: $box"
$results = @()
$t0 = Get-Date

$enc = Resolve-SasEncoding $Encoding
foreach ($s in $steps) {
  $r = Invoke-Sas -Program (Join-Path $repo $s.Program) -Tag $s.Tag -LogDir $LogDir `
                  -InitStmt $s.InitStmt -Encoding $Encoding
  $results += $r
  if ($s.GateOn) {
    $lines = [IO.File]::ReadAllLines($r.Log, (Get-SasLogEncoding $enc))
    $hit = @($lines | Select-String -Pattern $s.GateOn)
    if ($hit.Count -gt 0) {
      $hit | Select-Object -First 3 | ForEach-Object { Write-Host "  $_" }
      if ($NoGate) {
        Write-Host "  （$($s.Tag): 停止条件に触れたが -NoGate のため続けます）"
      } else {
        throw "$($s.Tag) が停止条件に触れました。直してから通すこと（ログ $($r.Log)）。調べるだけなら -NoGate"
      }
    }
  }
  if ($s.WaitFor) { Wait-BoxFile (Join-Path $box $s.WaitFor) }
}

# ARS の ReportingEvent。パイプラインの部品ではなく末端から枝分かれする成果物なので、
# 段階の一覧には入れず最後に1度だけ作る。-Only で一部だけ回したときは ARD が古い可能性が
# あるので作らない（pipeline/cdisc-ars.md「ARS を採るかどうかの判断軸」）。
if (-not $Only) {
  Write-Host ""
  Write-Host "ARS の ReportingEvent"
  & python (Join-Path $repo 'scripts' 'build-ars-json.py') 2>&1 | ForEach-Object { "  $_" }
}

$min = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
$e = ($results | Measure-Object Error -Sum).Sum
$w = ($results | Measure-Object Warning -Sum).Sum
Write-Host ""
Write-Host "完了: $($results.Count) 段階  ERROR $e  WARNING $w  所要 $min 分"
