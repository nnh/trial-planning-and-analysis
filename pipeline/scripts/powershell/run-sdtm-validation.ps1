# run-sdtm-validation.ps1
#
# SDTM の適合性検証を一続きで回す。
#   1. 変数メタデータの書き出し（SAS）
#   2. define.xml の更新と HTML 化
#   3. Dataset-JSON の生成（SAS）と BOM 除去
#   4. CDISC CORE による検証
#
# 前提：SDTM データセットが Box の datasets/sas/sdtm に出来ていること
#       （program/sas/<試験ID>_CSVtoSDTM.sas を先に実行する）
#       CDISC CORE が %USERPROFILE%\opt\cdisc-core\core に入っていること
#       方法論の正本は akiko-office docs/methods/sdtm-conformance-validation.md
#
# 使い方：pwsh -File scripts/run-sdtm-validation.ps1
#         pwsh -File scripts/run-sdtm-validation.ps1 -LogDir <dir>  ... ログの置き場を変える

param(
  [ValidateSet('utf8', 'sjis')][string]$Encoding = 'utf8',
  [string]$LogDir
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'sas-common.ps1')

$repo = Split-Path $PSScriptRoot -Parent
$box  = Get-TrialRoot
# 試験 ID は docs/metadata/trial.json だけが持つ。SAS プログラム名の組み立てに使う
$trialId = (Get-TrialConfig).trial_id
$core = Join-Path $env:USERPROFILE 'opt\cdisc-core\core\core.exe'
$stamp  = Get-Date -Format 'yyyyMMdd'

# CORE の結果の置き場。既定は Invoke-Sas と同じ試験フォルダの log で、-Root で出力先を
# 隔離したときもログだけ本番へ落ちないように Get-TrialRoot を通す（sas-common.ps1）。
if (-not $LogDir) { $LogDir = Join-Path $box 'log' }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $core)) { throw "見つかりません: $core" }

Write-Host '1. 変数メタデータの書き出し'
Invoke-Sas -Program (Join-Path $repo 'scripts\export-sdtm-metadata.sas') `
           -Tag 'export-sdtm-metadata' -Encoding $Encoding | Out-Null

Write-Host '2. define.xml の更新'
# update-define-xml.ps1 は SDTM IG の Role とラベルの一覧を読む。ドメインが増えたときに
# 追随させるため毎回作り直す。引くのはスキル cdisc-define-xml のスクリプトで、
# 出どころは CDISC CORE のキャッシュ（元は CDISC Library）。
$igMeta = Join-Path $env:USERPROFILE '.claude\skills\cdisc-define-xml\scripts\export-sdtm-metadata.py'
if (-not (Test-Path $igMeta)) { throw "スキル cdisc-define-xml が見つかりません: $igMeta" }
& python $igMeta --out (Join-Path $repo 'docs\metadata\external\sdtmig-3-2-variable-roles.csv') `
         --domains-from (Join-Path $box 'datasets\sas\sdtm\sdtm_variables.csv') | Select-Object -Last 2 | Write-Host
# DOMAIN の CodeList に付ける NCI の C コードは CDISC CT が正本。同じスキルの
# export-ct-codelist.py で写しを作り直す（CORE-000929 が Alias を見る）。
$ctMeta = Join-Path $env:USERPROFILE '.claude\skills\cdisc-define-xml\scripts\export-ct-codelist.py'
if (-not (Test-Path $ctMeta)) { throw "スキル cdisc-define-xml が見つかりません: $ctMeta" }
& python $ctMeta --out (Join-Path $repo 'docs\metadata\external\ct-domain-ccode.csv') --codelist C66734 |
  Select-Object -Last 1 | Write-Host
& pwsh -File (Join-Path $repo 'scripts\update-define-xml.ps1') | Select-Object -Last 5 | Write-Host

Write-Host '   define.xml の HTML 化'
$xslt = New-Object System.Xml.Xsl.XslCompiledTransform
$xslt.Load((Join-Path $box 'datasets\sas\sdtm\define2-0-0.xsl'),
           (New-Object System.Xml.Xsl.XsltSettings($true, $true)),
           (New-Object System.Xml.XmlUrlResolver))
$xslt.Transform((Join-Path $box 'datasets\sas\sdtm\define.xml'), (Join-Path $box 'datasets\sas\sdtm\define.html'))
Write-Host "   $(Join-Path $box 'datasets\sas\sdtm\define.html')"

Write-Host '3. Dataset-JSON の生成'
Invoke-Sas -Program (Join-Path $repo "program\sas\${trialId}_SDTMtoJSON.sas") `
           -Tag 'SDTMtoJSON' -Encoding $Encoding | Out-Null

# SAS の encoding='utf-8' は BOM を書き出すが、CORE の JSON パーサは BOM 付きを読めない
$n = 0
foreach ($f in Get-ChildItem (Join-Path $box 'datasets\sas\sdtm\json') -Filter *.json) {
  $bytes = [IO.File]::ReadAllBytes($f.FullName)
  if ($bytes.Length -gt 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    [IO.File]::WriteAllBytes($f.FullName, $bytes[3..($bytes.Length - 1)])
    $n++
  }
}
Write-Host "   BOM を除去: $n ファイル"

# CORE の一部のルール（DOMAIN コードの照合、define と IG の role 照合）は
# -dxp とは別に、データセットと同じフォルダの define.xml を直接開く。
# 置かないと "No such file or directory" で 32 件のルールが EXECUTION ERROR になる。
Copy-Item (Join-Path $box 'datasets\sas\sdtm\define.xml') (Join-Path $box 'datasets\sas\sdtm\json\define.xml') -Force
Write-Host '   define.xml をデータフォルダへ配置'

# Box Drive は書き込み直後のファイルを別プロセスから読めないことがある
# （CORE が "Your data file could not be read" で落ちる）。読めるまで待つ。
$files = Get-ChildItem (Join-Path $box 'datasets\sas\sdtm\json') -Filter *.json
for ($try = 1; $try -le 10; $try++) {
  $ng = 0
  foreach ($f in $files) {
    try { [void](Get-Content $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { $ng++ }
  }
  if ($ng -eq 0) { Write-Host "   $($files.Count) ファイルの読み取りを確認"; break }
  Start-Sleep -Seconds 3
  if ($try -eq 10) { throw "Dataset-JSON を読み取れません（$ng ファイル）" }
}

Write-Host '4. CDISC CORE による検証'
# define.xml は渡さない。CORE 同梱の odmlib が Define-XML 2.0 の ItemGroupDef/@def:Class を
# 扱えず読み込み時に落ちるため（2.1 は Class が子要素）。変数メタデータは Dataset-JSON が持つ。
$out = Join-Path $LogDir "$stamp-sdtm-validation"
$sw  = [Diagnostics.Stopwatch]::StartNew()
# CORE は resources\schema\dataset.schema.json を相対パスで開くため、
# カレントディレクトリを core.exe の場所にしないと Dataset-JSON を読めない。
$cwd = Get-Location
Set-Location (Split-Path $core -Parent)
& $core validate -s sdtmig -v 3-2 -d (Join-Path $box 'datasets\sas\sdtm\json') `
        -ct sdtmct-2026-03-27 -of JSON -o $out -p disabled | Select-Object -Last 3 | Write-Host
Set-Location $cwd
$sw.Stop()
Write-Host "   所要時間 $([math]::Round($sw.Elapsed.TotalSeconds,1)) 秒"

$j = Get-Content "$out.json" -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ''
Write-Host 'ルール実行状況'
$j.Rules_Report | Group-Object status | Sort-Object Count -Descending |
  ForEach-Object { Write-Host ("  {0,-16} {1}" -f $_.Name, $_.Count) }
# 仕分けの正本は docs/metadata/core-issue-disposition.csv。既知として残すと決めたルールを別枠に
# 出し、未仕分けの指摘が件数の多い既知に埋もれないようにする。CORE 自体は素のまま回して
# 全件を JSON に残す。--exclude-rules で除外すると、何を外したかが JSON から見えなくなり、
# データの設計が変わって指摘の性質が変わっても気づけない。
# EXECUTION ERROR のルールも Issue_Summary に各1件として現れる（ルールが実行できな
# かった旨の報告。指摘ではない）。status で分けないと指摘の件数に混ざる。
$rmsg = @{}; $stat = @{}
foreach ($r in $j.Rules_Report) { $rmsg[$r.core_id] = $r.message; $stat[$r.core_id] = $r.status }
$disp = @{}
$dispPath = Join-Path $repo 'docs\metadata\core-issue-disposition.csv'
# 仕分け表が読めないまま進むと、既知の指摘が0件と表示されて未仕分けの山に埋もれる。
# 2026-08-25 の docs 階層化でパスが取り残され、2026-08-29 まで気づけなかったため止める。
if (-not (Test-Path $dispPath)) { throw "仕分け表が見つかりません: $dispPath" }
foreach ($r in Import-Csv $dispPath) { $disp[$r.core_id] = $r }

$grp = $j.Issue_Summary | Group-Object core_id | ForEach-Object {
  [pscustomobject]@{
    core_id = $_.Name
    issues  = ($_.Group | Measure-Object issues -Sum).Sum
    ds      = (($_.Group | ForEach-Object { $_.dataset } | Sort-Object -Unique) -join ',')
    disp    = $(if ($disp.ContainsKey($_.Name)) { $disp[$_.Name].disposition } else { 'open' })
    status  = $stat[$_.Name]
  }
}
$exec  = @($grp | Where-Object { $_.status -eq 'EXECUTION ERROR' })
$issue = @($grp | Where-Object { $_.status -ne 'EXECUTION ERROR' })
$known = @($issue | Where-Object { $_.disp -eq 'known' } | Sort-Object issues -Descending)
$rest  = @($issue | Where-Object { $_.disp -ne 'known' } | Sort-Object issues -Descending)

Write-Host ''
Write-Host ("既知として残すと決めた指摘 : {0} ルール / {1:n0} 件" -f `
            $known.Count, [int](($known | Measure-Object issues -Sum).Sum))
foreach ($k in $known) {
  Write-Host ("  {0,6} 件  {1}  {2}" -f $k.issues, $k.core_id, $disp[$k.core_id].note)
}
Write-Host ''
Write-Host ("仕分けの対象 : {0} ルール / {1:n0} 件（件数順に15まで）" -f `
            $rest.Count, [int](($rest | Measure-Object issues -Sum).Sum))
foreach ($r in ($rest | Select-Object -First 15)) {
  $mark = $(if ($r.disp -eq 'open') { ' ' } else { $r.disp.Substring(0, 1) })
  Write-Host ("  {0} {1,6} 件  {2}  [{3}]  {4}" -f $mark, $r.issues, $r.core_id, $r.ds, $rmsg[$r.core_id])
}
if ($exec.Count -gt 0) {
  Write-Host ''
  Write-Host ("ルールが実行できなかったもの : {0} ルール" -f $exec.Count)
  foreach ($e in $exec) {
    Write-Host ("  {0}  [{1}]  {2}" -f $e.core_id, $e.ds, $rmsg[$e.core_id])
  }
}
