# run-adam-json.ps1
#
# ADaM の Dataset-JSON を作る。
#   1. <試験ID>_ADaMtoJSON.sas を実行
#   2. BOM を除去（SAS の file encoding='utf-8' は BOM を書く）
#   3. 生成された全ファイルが JSON として読めることを確認
#
# 前提：ADaM データセットが Box の datasets/sas/adam に出来ていること
#       （program/sas/<試験ID>_SDTMtoADaM.sas を先に実行する）
#       SDTM 側の同じ処理は scripts/run-sdtm-validation.ps1 が持つ。
#
# 使い方：pwsh -File scripts/run-adam-json.ps1

param([ValidateSet('utf8', 'sjis')][string]$Encoding = 'utf8')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'sas-common.ps1')

$repo = Split-Path $PSScriptRoot -Parent
$box  = Get-TrialRoot
$trialId = (Get-TrialConfig).trial_id
$jsonDir = Join-Path $box 'datasets\sas\adam\json'

Write-Host '1. Dataset-JSON の生成'
Invoke-Sas -Program (Join-Path $repo "program\sas\${trialId}_ADaMtoJSON.sas") `
           -Tag "${trialId}_ADaMtoJSON" -Encoding $Encoding | Out-Null

# SAS の encoding='utf-8' は BOM を書き出すが、jsonlite は BOM 付きを警告する。
# SDTM 側（run-sdtm-validation.ps1）と同じく除去して揃える。
Write-Host '2. BOM の除去'
$n = 0
foreach ($f in Get-ChildItem $jsonDir -Filter *.json) {
  $bytes = [IO.File]::ReadAllBytes($f.FullName)
  if ($bytes.Length -gt 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    [IO.File]::WriteAllBytes($f.FullName, $bytes[3..($bytes.Length - 1)])
    $n++
  }
}
Write-Host "   $n ファイルから除去"

# 空ラベルを put の "&&vb&i" に埋めると SAS が引用符をエスケープと解釈して
# 不正な JSON になる（2026-08-19 に発覧）。ERROR が出ないので、読めることを必ず確かめる。
Write-Host '3. JSON として読めるかの確認'
$ng = @()
foreach ($f in Get-ChildItem $jsonDir -Filter *.json) {
  try {
    $d = Get-Content $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host ("   {0,-12} columns {1,3} / records {2,6}" -f $f.Name, $d.columns.Count, $d.records)
  } catch {
    $ng += $f.Name
    Write-Host "   $($f.Name) : 読めません — $($_.Exception.Message)"
  }
}
if ($ng.Count -gt 0) { throw "不正な JSON: $($ng -join ', ')" }
Write-Host "完了。$jsonDir"
