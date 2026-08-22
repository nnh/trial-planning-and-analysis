# sas-common.ps1
#
# SAS をバッチで回すときの共通処理。実行する側から dot-source して使う。
#
#   . (Join-Path $PSScriptRoot 'sas-common.ps1')
#   Invoke-Sas -Program (Join-Path $repo 'program\<試験ID>_ARD.sas') -Tag 'ARD'
#
# セッションの符号化は UTF-8 を既定にする。SAS 9.4 の日本語版は既定の
# config が shift-jis のため、Unicode サーバーの config（nls\u8\sasv9.cfg）を -config で
# 明示して起動する。この config は導入済みで、追加のインストールは要らない。
# 従来の shift-jis で回すときだけ -Encoding sjis を渡す（符号化の前後比較に使う）。
#
# sas.exe は GUI サブシステムのため呼び出し演算子では待たずに戻る。Start-Process -Wait で
# 完了を待つ。引数は1本の文字列で渡す。配列で渡すと -initstmt "%let lang=ja;" が空白で
# 分割されて SAS が異常終了する（終了コード116）。

$SasHome   = 'C:\Program Files\SASHome\SASFoundation\9.4'
$SasExe    = Join-Path $SasHome 'sas.exe'
$SasConfig = @{
  utf8 = Join-Path $SasHome 'nls\u8\sasv9.cfg'
  sjis = Join-Path $SasHome 'nls\ja\sasv9.cfg'
}
$SasRepo = Split-Path $PSScriptRoot -Parent


function Resolve-SasEncoding([string]$Encoding) {
  if (-not $Encoding) { $Encoding = $env:SAS_SESSION_ENCODING }
  if (-not $Encoding) { $Encoding = 'utf8' }
  $Encoding = $Encoding.ToLower()
  if (-not $SasConfig.ContainsKey($Encoding)) {
    throw "符号化の指定が不正です: $Encoding（utf8 か sjis）"
  }
  if (-not (Test-Path $SasConfig[$Encoding])) {
    throw "SAS の config が見つかりません: $($SasConfig[$Encoding])"
  }
  $Encoding
}


function Get-TrialConfig {
  # 試験固有の値は docs/trial.json だけが持つ（scripts/boxpath.py と同じ設定）
  $cfg = Join-Path (Split-Path $PSScriptRoot -Parent) 'docs/trial.json'
  if (-not (Test-Path -LiteralPath $cfg)) { throw "試験の設定が無い: $cfg" }
  return (Get-Content -LiteralPath $cfg -Raw -Encoding UTF8 | ConvertFrom-Json)
}


function Get-TrialRoot {
  # Box の試験フォルダ。端末ごとに Box の位置が違うので探す（scripts/boxpath.py と同じ順）
  $rel = (Get-TrialConfig).box_path -join [IO.Path]::DirectorySeparatorChar
  $cands = @()
  if ($env:TRIAL_BOX_ROOT) { $cands += $env:TRIAL_BOX_ROOT }
  $cands += (Join-Path $env:USERPROFILE 'Box')
  foreach ($c in $cands) {
    $p = Join-Path $c $rel
    if (Test-Path $p) { return $p }
  }
  throw "Box の試験フォルダが見つかりません（探した先: $($cands -join ', ')）"
}


function Get-SasLogEncoding([string]$Encoding) {
  # SAS はセッションの符号化でログを書く。読む側を合わせないと ERROR の検出が効かない
  if ($Encoding -eq 'utf8') { return New-Object System.Text.UTF8Encoding($false) }
  return [Text.Encoding]::GetEncoding(932)
}


function Invoke-Sas {
  <#
    .SYNOPSIS
      SAS プログラムを1本実行し、ログの ERROR を数えて報告する。
    .PARAMETER InitStmt
      -initstmt へ渡す文（例 '%let lang=ja;'）。図表の言語切り替えに使う。
    .PARAMETER Encoding
      utf8（既定）か sjis。省略時は環境変数 SAS_SESSION_ENCODING、それも無ければ utf8。
  #>
  param(
    [Parameter(Mandatory)][string]$Program,
    [Parameter(Mandatory)][string]$Tag,
    [string]$LogDir,
    [string]$InitStmt,
    [string]$Encoding,
    [switch]$AllowError
  )

  $enc = Resolve-SasEncoding $Encoding
  $cfg = $SasConfig[$enc]
  if (-not (Test-Path $SasExe)) { throw "SAS が見つかりません: $SasExe" }
  if (-not (Test-Path $Program)) { throw "プログラムが見つかりません: $Program" }
  if (-not $LogDir) { $LogDir = Join-Path (Get-TrialRoot) 'log' }
  New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

  $stamp = Get-Date -Format 'yyyyMMdd'
  $log   = Join-Path $LogDir "$Tag`_$stamp.log"
  $lst   = Join-Path $env:TEMP "$Tag.lst"

  $argv = "-config `"$cfg`" -sysin `"$Program`" -autoexec `"$(Join-Path $SasRepo 'autoexec.sas')`"" +
          " -sasinitialfolder `"$SasRepo`" -log `"$log`" -print `"$lst`" -nosplash -noterminal"
  if ($InitStmt) { $argv += " -initstmt `"$InitStmt`"" }

  $sw = [Diagnostics.Stopwatch]::StartNew()
  Start-Process -FilePath $SasExe -ArgumentList $argv -Wait -NoNewWindow
  $sw.Stop()

  $lines = [IO.File]::ReadAllLines($log, (Get-SasLogEncoding $enc))
  $err   = ($lines | Select-String '^ERROR').Count
  $warn  = ($lines | Select-String '^WARNING').Count
  $sec   = [math]::Round($sw.Elapsed.TotalSeconds, 1)
  Write-Host ("  {0,-22} ERROR {1}  WARNING {2}  {3}秒  [{4}]" -f $Tag, $err, $warn, $sec, $enc)
  if ($err -gt 0) {
    ($lines | Select-String '^ERROR' | Select-Object -First 5) -join "`n" | Write-Host
    if (-not $AllowError) { throw "$Tag で ERROR が出ました（ログ $log）" }
  }
  [pscustomobject]@{ Tag = $Tag; Error = $err; Warning = $warn; Seconds = $sec; Log = $log }
}


function Wait-BoxFile {
  # Box Drive は書き込み直後に別プロセスから読むと古い版を返すことがある。
  # 更新時刻とサイズが落ち着くまで待つ。
  param([Parameter(Mandatory)][string]$Path, [int]$TimeoutSec = 60)
  $t0 = Get-Date
  $prev = $null
  while (((Get-Date) - $t0).TotalSeconds -lt $TimeoutSec) {
    if (Test-Path $Path) {
      $i = Get-Item $Path
      $cur = "$($i.Length)/$($i.LastWriteTimeUtc.Ticks)"
      if ($cur -eq $prev) { return }
      $prev = $cur
    }
    Start-Sleep -Milliseconds 800
  }
  Write-Host "  （$([IO.Path]::GetFileName($Path)) の同期待ちが $TimeoutSec 秒を超えました）"
}
