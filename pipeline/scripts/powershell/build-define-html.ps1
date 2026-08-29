# build-define-html.ps1
#
# define.xml を CDISC 標準の XSL（define2-0-0.xsl）で HTML へ変換する。
# ブラウザで define.xml を直接開いても XSL は効くが、配布用に静的な HTML も置く。
#
# 使い方
#   pwsh -File scripts/build-define-html.ps1            # ADaM と SDTM の両方
#   pwsh -File scripts/build-define-html.ps1 -Layer ads # ADaM だけ
param([ValidateSet('all', 'ads', 'sdtm')] [string]$Layer = 'all')

$ErrorActionPreference = 'Stop'
# 試験フォルダの探索は sas-common.ps1 の Get-TrialRoot が持つ（docs/metadata/trial.json の
# box_path を読む）。ここで組み立てると、Box の位置や試験フォルダ名を2箇所に書くことになる。
. (Join-Path $PSScriptRoot 'sas-common.ps1')
$base = Join-Path (Get-TrialRoot) 'input'

$targets = switch ($Layer) {
  'ads'  { @('ads') }
  'sdtm' { @('sdtm') }
  default { @('ads', 'sdtm') }
}

foreach ($t in $targets) {
  $dir = Join-Path $base $t
  $xml = Join-Path $dir 'define.xml'
  $xslPath = Join-Path $dir 'define2-0-0.xsl'
  $html = Join-Path $dir 'define.html'
  if (-not (Test-Path $xml)) { Write-Host "$t : define.xml が無いので飛ばす"; continue }
  if (-not (Test-Path $xslPath)) { Write-Host "$t : define2-0-0.xsl が無いので飛ばす"; continue }

  # XSL は document() を使うので EnableDocumentFunction と URL リゾルバを渡す
  $xsl = New-Object System.Xml.Xsl.XslCompiledTransform
  $set = New-Object System.Xml.Xsl.XsltSettings($true, $true)
  $res = New-Object System.Xml.XmlUrlResolver
  $xsl.Load($xslPath, $set, $res)
  $xsl.Transform($xml, $html)
  $len = (Get-Item $html).Length
  Write-Host ("{0} : define.html を作った（{1:N0} バイト）" -f $t, $len)
}
