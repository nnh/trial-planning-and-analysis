# run-all-sas.ps1
#
# SAS 側の解析を受領CSVから図表まで一続きで回す。実行の順序はここが正本。
#
#   pwsh -File scripts/run-all-sas.ps1                    ... UTF-8 セッション（既定）
#   pwsh -File scripts/run-all-sas.ps1 -Encoding sjis     ... 従来の shift-jis セッション
#   pwsh -File scripts/run-all-sas.ps1 -Only ARD,TLF      ... 一部だけ回す
#   pwsh -File scripts/run-all-sas.ps1 -LogDir <dir>      ... ログの置き場を変える
#
# Dataset-JSON の後処理（BOM 除去・JSON として読めることの確認）と define.xml の更新・
# CORE 検証は含まない。それぞれ run-adam-json.ps1・run-sdtm-validation.ps1 が持つ。
#
# 前提：受領CSVが Box の input/rawdata 直下に展開されていること。

param(
  [ValidateSet('utf8', 'sjis')][string]$Encoding = 'utf8',
  [string]$LogDir,
  [string[]]$Only
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'sas-common.ps1')

$repo = Split-Path $PSScriptRoot -Parent
$box  = Get-TrialRoot
$trialId = (Get-TrialConfig).trial_id

# 実行の順序。ARD の後に ARDtoCards、ADaM の後に JSON という依存があるので並べ替えない。
# プログラム名は <試験ID>_<段階名>.sas の形に揃える。QC の段階名（TTECheck・CMRCheck 等）
# は試験の主要エンドポイントに応じて試験ごとに変わるので、ここは例として置く。
$steps = @(
  @{ Tag = 'CSVtoSDTM';    Program = "program\${trialId}_CSVtoSDTM.sas" }
  @{ Tag = 'SDTMtoADaM';   Program = "program\${trialId}_SDTMtoADaM.sas" }
  @{ Tag = 'ARD';          Program = "program\${trialId}_ARD.sas";
     WaitFor = 'input\ads\ard.sas7bdat' }
  @{ Tag = 'ARDtoCards';   Program = "program\${trialId}_ARDtoCards.sas" }
  @{ Tag = 'TLF_ja';       Program = "program\${trialId}_TLF.sas";  InitStmt = '%let lang=ja;' }
  @{ Tag = 'TLF_en';       Program = "program\${trialId}_TLF.sas";  InitStmt = '%let lang=en;' }
  @{ Tag = 'ADaMtoMaster'; Program = "program\${trialId}_ADaMtoMaster.sas" }
  @{ Tag = 'SDTMtoJSON';   Program = "program\${trialId}_SDTMtoJSON.sas" }
  @{ Tag = 'ADaMtoJSON';   Program = "program\${trialId}_ADaMtoJSON.sas" }
  @{ Tag = 'QC01';         Program = "program\QC\${trialId}_QC01_RawDataScan.sas" }
  @{ Tag = 'QC03';         Program = "program\QC\${trialId}_QC03_TTECheck.sas" }
  @{ Tag = 'QC04';         Program = "program\QC\${trialId}_QC04_CMRCheck.sas" }
)

if ($Only) {
  $steps = $steps | Where-Object { $Only -contains $_.Tag }
  if (-not $steps) { throw "-Only に該当する段階がありません（指定: $($Only -join ', ')）" }
}

Write-Host "SAS セッションの符号化: $Encoding"
Write-Host "Box: $box"
$results = @()
$t0 = Get-Date

foreach ($s in $steps) {
  $r = Invoke-Sas -Program (Join-Path $repo $s.Program) -Tag $s.Tag -LogDir $LogDir `
                  -InitStmt $s.InitStmt -Encoding $Encoding
  $results += $r
  if ($s.WaitFor) { Wait-BoxFile (Join-Path $box $s.WaitFor) }
}

$min = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
$e = ($results | Measure-Object Error -Sum).Sum
$w = ($results | Measure-Object Warning -Sum).Sum
Write-Host ""
Write-Host "完了: $($results.Count) 段階  ERROR $e  WARNING $w  所要 $min 分"
