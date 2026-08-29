# update-define-xml.ps1
#
# データセンターから受領した define.xml（Define-XML 2.0.0 / SDTM-IG 3.2）に、
# CSVtoSDTM.sas で追加した derived 変数と CO ドメインを反映した define.xml を作る。
#
# 入力  : 受領 define.xml（Box の固定データ内。読み取りのみ）
#         SDTM データセットの変数メタデータ CSV（scripts/export-sdtm-metadata.sas が出す）
# 出力  : Box datasets/sas/sdtm/define.xml、同 define2-0-0.xsl、変数ラベル CSV
#
# 役割分担：変数の型・長さ・順序は SAS データセットが正本、
#           ラベル・Origin・CodeList は define.xml が正本。
# 使い方  : pwsh -File scripts/update-define-xml.ps1

$ErrorActionPreference = 'Stop'

$box      = Join-Path $env:USERPROFILE 'Box\Stat\Trials\JALSG\<試験ID>'
$srcDir   = Join-Path $box 'input\rawdata\20260722 fixed data\PhALL219_define_260721_1002'
$outDir   = Join-Path $box 'datasets\sas\sdtm'
$metaCsv  = Join-Path $outDir 'sdtm_variables.csv'
$labelCsv = Join-Path $outDir 'sdtm_labels.csv'

if (-not (Test-Path $metaCsv)) { throw "変数メタデータがありません: $metaCsv （先に export-sdtm-metadata.sas を実行）" }

# ---- IG に無い変数のラベル -------------------------------------------------------------
# 変数ラベルの正本は SDTM IG（docs/metadata/external/sdtmig-3-2-variable-roles.csv）。ここに置くのは IG の
# 一覧に載らない変数だけにする。IG の値を写すと、ドメインで違うラベル（--STRESC など）を
# 取り違えるうえ、Library の版が変わったときにずれる。
# CO は本試験では作らない（AE 由来の全行を datasets/sas/pv へ出したため）が、他の試験で
# 使うことがあるので残す。
$lab = @{
  'RDOMAIN' = 'Related Domain Abbreviation'
  'COSEQ'   = 'Sequence Number'
  'COSPID'  = 'Sponsor-Defined Identifier'
  'IDVAR'   = 'Identifying Variable'
  'IDVARVAL' = 'Identifying Variable Value'
  'COVAL'   = 'Comment'
}

# 導出方法の説明（def:Origin Type="Derived" に添える）
$derivComment = @{
  'EPOCH'    = 'VISITNUM から割り付け、VISITNUM が無い場合は初回移植日と試験治療終了日を境に判定'
  'VISIT'    = 'VISITNUM に対応する来院名'
  'AGE'      = 'RFSTDTC と BRTHDTC から算出した満年齢'
  'RFXSTDTC' = 'EC の ECSTDTC の最小値'
  'RFXENDTC' = 'EC の ECENDTC（無い場合は ECSTDTC）の最大値'
  'RFPENDTC' = 'DS の withdrawal（無い場合は discon）の DSSTDTC'
  'DTHDTC'   = 'DS の EPOCH=FOLLOW-UP かつ DSTERM=DEATH の DSSTDTC'
  'DTHFL'    = 'DTHDTC が非欠測のとき Y'
  'ACTARMCD' = 'EC に投与記録が無い症例は SCRNFAIL、それ以外は ARMCD と同値'
  'ACTARM'   = 'EC に投与記録が無い症例は Screen Failure、それ以外は ARM と同値'
  'CESTDTC'  = 'CEDTC を移送'
  'CEDECOD'  = 'CETERM と同値'
  'DSDECOD'  = 'DSTERM と同値（試験固有の中止理由は標準用語へ丸めない）'
  'PRINDC'   = '外部データ engraftment.csv の RETXRSN（再移植の理由）'
  'RSBLFL'   = 'ベースラインの効果判定は存在しないため全件空'
  'LBSTNRLO' = 'LBORNRLO を移送（単位換算しないため同値）'
  'LBSTNRHI' = '受領データに上限が無いため全件欠測'
}

# ---- 元 define.xml を読む -------------------------------------------------------------
$srcXml = (Get-ChildItem $srcDir -Filter 'define-*.xml' | Select-Object -First 1).FullName
if (-not $srcXml) { throw "受領 define.xml が見つかりません: $srcDir" }
Write-Host "元ファイル: $srcXml"

[xml]$x = Get-Content $srcXml -Encoding UTF8
$ns  = 'http://www.cdisc.org/ns/odm/v1.3'
$nsd = 'http://www.cdisc.org/ns/def/v2.0'
$mdv = $x.ODM.Study.MetaDataVersion

# 既存 ItemDef を OID と 名前で引けるようにする
$defByOid  = @{}
foreach ($it in $mdv.ItemDef) { $defByOid[$it.OID] = $it }

# ---- SAS 側のメタデータ ---------------------------------------------------------------
$meta = Import-Csv $metaCsv
$byDom = $meta | Group-Object memname

# SAS の型と長さから Define-XML の DataType を決める
function Get-DataType($row) {
  if ($row.type -eq 'num') {
    if ($row.name -match 'STRESN$|^ECDOSE$|^CMDOSE$') { return 'float' }
    return 'integer'
  }
  if ($row.name -match 'DTC$') { return 'date' }
  return 'text'
}

# 受領 define.xml に ItemGroupDef が無いドメインを新規に作るときの属性。
# Class は SDTM IG 3.2 のクラス、Structure は IG の記述に合わせる。
# SDTM IG 3.2 の Role と Label。ItemRef の Role と、受領 define.xml に無い変数の
# ラベルに使う。ラベルの正本はこの CSV で、スキル cdisc-define-xml の
# export-sdtm-metadata.py が CDISC CORE のキャッシュ（元は CDISC Library）から作る。
$roleCsv = Join-Path (Split-Path $PSScriptRoot -Parent) 'docs\metadata\external\sdtmig-3-2-variable-roles.csv'
if (-not (Test-Path $roleCsv)) {
  throw "変数の Role 一覧がありません: $roleCsv （先に scripts/export-sdtmig-roles.py を実行）"
}
$roleOf = @{}; $igLabelOf = @{}
foreach ($r in (Import-Csv $roleCsv)) {
  if ($r.role)  { $roleOf["$($r.domain).$($r.variable)"] = $r.role }
  if ($r.label) { $igLabelOf["$($r.domain).$($r.variable)"] = $r.label }
}

$newDomMeta = @{
  CO = @{ class = 'RELATIONSHIP'; refdata = 'No';
          structure = 'One record per comment per subject'; label = 'Comments' }
  TS = @{ class = 'TRIAL DESIGN'; refdata = 'Yes';
          structure = 'One record per trial summary parameter value';
          label = 'Trial Summary' }
  TA = @{ class = 'TRIAL DESIGN'; refdata = 'Yes';
          structure = 'One record per planned element per arm';
          label = 'Trial Arms' }
  TE = @{ class = 'TRIAL DESIGN'; refdata = 'Yes';
          structure = 'One record per planned element';
          label = 'Trial Elements' }
  TI = @{ class = 'TRIAL DESIGN'; refdata = 'Yes';
          structure = 'One record per inclusion or exclusion criterion';
          label = 'Trial Inclusion/Exclusion Criteria' }
  TV = @{ class = 'TRIAL DESIGN'; refdata = 'Yes';
          structure = 'One record per planned visit per arm';
          label = 'Trial Visits' }
}

$added = 0; $updated = 0; $newGroups = 0
$labelRows = @()

foreach ($g in $byDom) {
  $dom  = $g.Name
  $vars = $g.Group | Sort-Object { [int]$_.varnum }

  $ig = $mdv.ItemGroupDef | Where-Object { $_.Name -eq $dom }

  # --- ItemGroupDef が無いドメインは新規に作る ---
  # 受領 define.xml に無いのは、SDTM 層で作ったドメイン（Trial Design）と、
  # 受領時に define へ載っていなかったドメイン。Class・Structure は SDTM IG 3.2 に従う。
  # Trial Design は被験者データではないので IsReferenceData を Yes にする。
  if (-not $ig) {
    if (-not $newDomMeta.ContainsKey($dom)) {
      throw "ItemGroupDef が無いドメイン $dom の定義がありません（スクリプトの `$newDomMeta に追記してください）"
    }
    $m = $newDomMeta[$dom]
    $ig = $x.CreateElement('ItemGroupDef', $ns)
    $ig.SetAttribute('OID', "IG.$dom")
    $ig.SetAttribute('Name', $dom)
    $ig.SetAttribute('Domain', $dom)
    $ig.SetAttribute('SASDatasetName', $dom)
    $ig.SetAttribute('Repeating', 'Yes')
    $ig.SetAttribute('IsReferenceData', $m.refdata)
    $ig.SetAttribute('Purpose', 'Tabulation')
    $ig.SetAttribute('Class', $nsd, $m.class) | Out-Null
    $ig.SetAttribute('Structure', $nsd, $m.structure)
    $ig.SetAttribute('ArchiveLocationID', $nsd, "LF.$dom")
    $desc = $x.CreateElement('Description', $ns)
    $tt   = $x.CreateElement('TranslatedText', $ns)
    $tt.SetAttribute('lang', 'http://www.w3.org/XML/1998/namespace', 'en') | Out-Null
    $tt.InnerText = $m.label
    $desc.AppendChild($tt) | Out-Null
    $ig.AppendChild($desc) | Out-Null
    # 既存 ItemGroupDef 群の最後に挿入する
    $lastIg = ($mdv.ItemGroupDef | Select-Object -Last 1)
    $mdv.InsertAfter($ig, $lastIg) | Out-Null
    $newGroups++
    Write-Host "ItemGroupDef を新規作成: $dom"
  }

  # 既存 ItemRef を変数名で引けるようにする
  $refByName = @{}
  foreach ($ir in @($ig.ItemRef | Where-Object { $_ -ne $null })) {
    $d = $defByOid[$ir.ItemOID]
    if ($d) { $refByName[$d.Name] = @{ ref = $ir; def = $d } }
  }

  foreach ($v in $vars) {
    $name  = $v.name
    $order = [int]$v.varnum
    $dtype = Get-DataType $v
    $len   = if ($v.type -eq 'char') { [int]$v.length } else { $null }

    if ($refByName.ContainsKey($name)) {
      # --- 既存変数：順序と長さを SAS 側に合わせる（ラベル・Origin は元のまま） ---
      $refByName[$name].ref.SetAttribute('OrderNumber', "$order")
      $d = $refByName[$name].def
      if ($len) { $d.SetAttribute('Length', "$len") }
      if ($d.DataType -ne $dtype -and $dtype -in @('integer','float')) { $d.SetAttribute('DataType', $dtype) }
      $updated++
      $lbl = ''
      if ($d.Description -and $d.Description.TranslatedText) { $lbl = ($d.Description.TranslatedText.'#text').Trim() }
      $labelRows += [pscustomobject]@{ dataset = $dom; variable = $name; label = $lbl; itemOID = $d.OID }
      continue
    }

    # --- 追加変数：ItemDef と ItemRef を作る ---
    # ラベルは IG が正本。ドメインで違う変数（--STRESC など）があるので $dom.$name で引く。
    # IG の一覧に無い変数（CO の RDOMAIN など）だけ $lab から補う。
    $vlab = $igLabelOf["$dom.$name"]
    if (-not $vlab) { $vlab = $lab[$name] }
    if (-not $vlab) {
      throw "ラベル未定義の変数があります: $dom.$name（docs/metadata/external/sdtmig-3-2-variable-roles.csv を確認するか、スクリプトの `$lab に追記）"
    }
    $oid = "IT.$dom.$name"
    $id  = $x.CreateElement('ItemDef', $ns)
    $id.SetAttribute('OID', $oid)
    $id.SetAttribute('Name', $name)
    $id.SetAttribute('SASFieldName', $name)
    $id.SetAttribute('DataType', $dtype)
    if ($len) { $id.SetAttribute('Length', "$len") }
    $desc = $x.CreateElement('Description', $ns)
    $tt   = $x.CreateElement('TranslatedText', $ns)
    $tt.SetAttribute('lang', 'http://www.w3.org/XML/1998/namespace', 'en') | Out-Null
    $tt.InnerText = $vlab
    $desc.AppendChild($tt) | Out-Null
    $id.AppendChild($desc) | Out-Null
    $org = $x.CreateElement('def', 'Origin', $nsd)
    $org.SetAttribute('Type', 'Derived')
    if ($derivComment.ContainsKey($name)) {
      $od  = $x.CreateElement('Description', $ns)
      $ott = $x.CreateElement('TranslatedText', $ns)
      $ott.SetAttribute('lang', 'http://www.w3.org/XML/1998/namespace', 'en') | Out-Null
      $ott.InnerText = $derivComment[$name]
      $od.AppendChild($ott) | Out-Null
      $org.AppendChild($od) | Out-Null
    }
    $id.AppendChild($org) | Out-Null

    $lastDef = ($mdv.ItemDef | Select-Object -Last 1)
    $mdv.InsertAfter($id, $lastDef) | Out-Null
    $defByOid[$oid] = $id

    $ir = $x.CreateElement('ItemRef', $ns)
    $ir.SetAttribute('ItemOID', $oid)
    $ir.SetAttribute('OrderNumber', "$order")
    $ir.SetAttribute('Mandatory', 'No')
    $ig.AppendChild($ir) | Out-Null
    $added++
    $labelRows += [pscustomobject]@{ dataset = $dom; variable = $name; label = $vlab; itemOID = $oid }
  }

  # ArchiveLocation を Dataset-JSON のファイル名へ。
  # 受領 define.xml は xlink:href も def:title も空で、空の def:title は
  # CORE が "Missing required keyword argument _content in title" で落ちる。
  $fname = $dom.ToLower() + '.json'
  $leaf  = $ig.SelectSingleNode("*[local-name()='leaf']")
  if (-not $leaf) {
    $leaf = $x.CreateElement('def', 'leaf', $nsd)
    $leaf.SetAttribute('ID', "LF.$dom")
    $ig.AppendChild($leaf) | Out-Null
  }
  $leaf.SetAttribute('href', 'http://www.w3.org/1999/xlink', $fname) | Out-Null
  $title = $leaf.SelectSingleNode("*[local-name()='title']")
  if (-not $title) {
    $title = $x.CreateElement('def', 'title', $nsd)
    $leaf.AppendChild($title) | Out-Null
  }
  $title.InnerText = $fname
}

# def:Class を Define-XML 2.0 のコントロールドターム（大文字）に揃える。
# 受領 define.xml は小文字（events・findings 等）で、CORE が読み込み時に
# "Unknown value Class in ValueSet" で落ちる。
foreach ($ig in $mdv.ItemGroupDef) {
  $cls = $ig.GetAttribute('Class', $nsd)
  if ($cls -and $cls -cne $cls.ToUpper()) { $ig.SetAttribute('Class', $nsd, $cls.ToUpper()) | Out-Null }
}

# FINDINGS ABOUT は Define-XML 2.1 で追加された値で、2.0 の値セットには無い。2.0 では
# FINDINGS を使う（docs/records/sdtm-conformance-findings-20260815.md D-1）。
foreach ($ig in $mdv.ItemGroupDef) {
  if ($ig.GetAttribute('Class', $nsd) -eq 'FINDINGS ABOUT') {
    $ig.SetAttribute('Class', $nsd, 'FINDINGS') | Out-Null
    Write-Host "def:Class を FINDINGS に直した: $($ig.Name)"
  }
}

# ---- 値水準メタデータを SDTM の実データに合わせる ------------------------------------
# 受領 define.xml は --ORRES の値水準 ItemDef の Name と SASFieldName の両方へ --TESTCD の
# 値を入れており、Description が空になっている。SASFieldName は SAS の変数名の規則
# （空白不可・8文字以内）に従う必要があり、Description は値の意味を持つべきである
# （同 D-1）。FA は SDTM 層で FATESTCD を是正しているので、受領時の値のままの ItemDef を
# 落とし、実データにあって define に無い値を足す（docs/spec/sdtm-spec.md 3.6）。
$vlmCsv = Join-Path $outDir 'sdtm_valuelevel.csv'
if (-not (Test-Path $vlmCsv)) {
  throw "値水準メタデータの対応表がありません: $vlmCsv （先に scripts/export-sdtm-metadata.sas を実行）"
}
$vlmRows = Import-Csv $vlmCsv
$testOf = @{}
foreach ($r in $vlmRows) { $testOf["$($r.domain).$($r.testcd)"] = $r.test }

$oidToDef = @{}
foreach ($d in $mdv.ItemDef) { $oidToDef[$d.OID] = $d }
$oidToWc = @{}
foreach ($w in @($mdv.SelectNodes('*[local-name()="WhereClauseDef"]'))) { $oidToWc[$w.OID] = $w }

$vlSfn = 0; $vlDesc = 0; $vlDropped = 0; $vlAdded = 0; $vlOrigin = 0

foreach ($vl in @($mdv.SelectNodes('*[local-name()="ValueListDef"]'))) {
  # VL.FA.FAORRES から ドメインと親変数を取る
  $p = $vl.OID -split '\.'
  if ($p.Count -lt 3) { continue }
  $dom = $p[1]; $var = $p[2]
  $parentDef = $oidToDef["IT.$dom.$var"]
  $seen = @{}

  foreach ($ref in @($vl.SelectNodes('*[local-name()="ItemRef"]'))) {
    $it = $oidToDef[$ref.ItemOID]
    if (-not $it) { continue }
    $q = $it.OID -split '\.'
    if ($q.Count -lt 4) { continue }
    $testcd = $q[3]

    if (-not $testOf.ContainsKey("$dom.$testcd")) {
      # 実データに無い --TESTCD。ItemRef・WhereClauseDef・ItemDef を落とす
      $wr = $ref.SelectSingleNode('*[local-name()="WhereClauseRef"]')
      if ($wr) {
        $w = $oidToWc[$wr.WhereClauseOID]
        if ($w) { $w.ParentNode.RemoveChild($w) | Out-Null }
      }
      $vl.RemoveChild($ref) | Out-Null
      $it.ParentNode.RemoveChild($it) | Out-Null
      $vlDropped++
      continue
    }

    $seen[$testcd] = $true
    # SASFieldName は親変数名にする（--TESTCD の値は SAS の変数名になり得ない）
    if ($it.GetAttribute('SASFieldName') -ne $var) {
      $it.SetAttribute('SASFieldName', $var)
      $vlSfn++
    }
    # 空の Description に --TEST を入れる
    $tt = $it.SelectSingleNode('*[local-name()="Description"]/*[local-name()="TranslatedText"]')
    if ($tt -and -not $tt.InnerText.Trim()) {
      $tt.InnerText = $testOf["$dom.$testcd"]
      $vlDesc++
    }
  }

  # 実データにあって define に無い --TESTCD を足す
  $order = @($vl.SelectNodes('*[local-name()="ItemRef"]')).Count
  foreach ($r in ($vlmRows | Where-Object { $_.domain -eq $dom })) {
    if ($seen.ContainsKey($r.testcd)) { continue }
    $order++
    $itOid = "IT.$dom.$var.$($r.testcd)"
    $wcOid = "WC.$dom.$($dom)TESTCD.$($r.testcd)"

    $nd = $x.CreateElement('ItemDef', $ns)
    $nd.SetAttribute('OID', $itOid)
    $nd.SetAttribute('Name', $r.testcd)
    $nd.SetAttribute('SASFieldName', $var)
    $nd.SetAttribute('DataType', $(if ($parentDef) { $parentDef.DataType } else { 'text' }))
    if ($parentDef -and $parentDef.Length) { $nd.SetAttribute('Length', $parentDef.Length) }
    $de = $x.CreateElement('Description', $ns)
    $tt = $x.CreateElement('TranslatedText', $ns)
    $tt.SetAttribute('lang', 'http://www.w3.org/XML/1998/namespace', 'en') | Out-Null
    $tt.InnerText = $r.test
    $de.AppendChild($tt) | Out-Null
    $nd.AppendChild($de) | Out-Null
    # 親 ItemDef の def:Origin を丸ごと写す（2026-08-20 追記）。
    # ここで足していた値水準の ItemDef は Origin を持たず、Define-XML 2.0 が ItemDef に
    # 求める出どころの記述を欠いていた。値水準の項目は親変数と同じ出どころ（FAORRES なら
    # CRF）なので、def:DocumentRef・def:PDFPageRef ごと複製して既存の値水準 ItemDef と
    # 同じ形にする。親が Origin を持たないときは何も付けない。
    if ($parentDef) {
      $pOrg = $parentDef.SelectSingleNode('*[local-name()="Origin"]')
      if ($pOrg) {
        $nd.AppendChild($pOrg.CloneNode($true)) | Out-Null
        $vlOrigin++
      }
    }
    $lastDef = @($mdv.ItemDef)[-1]
    $mdv.InsertAfter($nd, $lastDef) | Out-Null
    $oidToDef[$itOid] = $nd

    $wd = $x.CreateElement('def', 'WhereClauseDef', $nsd)
    $wd.SetAttribute('OID', $wcOid)
    $rc = $x.CreateElement('RangeCheck', $ns)
    $rc.SetAttribute('Comparator', 'EQ')
    $rc.SetAttribute('SoftHard', 'Soft')
    $rc.SetAttribute('ItemOID', $nsd, "IT.$dom.$($dom)TESTCD") | Out-Null
    $cv = $x.CreateElement('CheckValue', $ns)
    $cv.InnerText = $r.testcd
    $rc.AppendChild($cv) | Out-Null
    $wd.AppendChild($rc) | Out-Null
    $wcNodes = @($mdv.SelectNodes('*[local-name()="WhereClauseDef"]'))
    if ($wcNodes.Count -gt 0) { $mdv.InsertAfter($wd, $wcNodes[-1]) | Out-Null }
    else { $mdv.AppendChild($wd) | Out-Null }

    $ref = $x.CreateElement('ItemRef', $ns)
    $ref.SetAttribute('ItemOID', $itOid)
    $ref.SetAttribute('Mandatory', 'No')
    $ref.SetAttribute('OrderNumber', "$order")
    $wr = $x.CreateElement('def', 'WhereClauseRef', $nsd)
    $wr.SetAttribute('WhereClauseOID', $wcOid)
    $ref.AppendChild($wr) | Out-Null
    $vl.AppendChild($ref) | Out-Null
    $vlAdded++
  }
}
Write-Host ("値水準メタデータ : SASFieldName {0} / Description {1} / 削除 {2} / 追加 {3} / Origin 複製 {4}" -f `
  $vlSfn, $vlDesc, $vlDropped, $vlAdded, $vlOrigin)

# ---- SDTM 層で値を扱った変数の CodeList を実データに合わせる --------------------------
# 受領 define.xml の CodeList は CRF の選択肢を写したものなので、SDTM 層で値を扱った変数では
# 実データと食い違う。扱いは CSV の mode 列が持つ。replace は実データの値だけにする（SDTM 層で
# 値体系を作り直した変数）。add は既存の値と実データの値の和にする（CRF の選択肢に SDTM 層で
# 値を足した変数。未使用の選択肢も CRF としては正しいので落とさない）。
# どちらも専用の CodeList を作って差し替えるので、受領 define.xml が複数の変数へ同じ CodeList を
# 割り当てている場合（FATESTCD と FATEST、LBTESTCD と MBTESTCD）の共有も断てる。
# 対象は sdtm_codelist_sync.csv に出てくる変数だけ。リストの正本は
# scripts/export-sdtm-metadata.sas の &cl_replace・&cl_add。
$clCsv = Join-Path $outDir 'sdtm_codelist_sync.csv'
if (-not (Test-Path $clCsv)) {
  throw "CodeList 同期用の値一覧がありません: $clCsv （先に scripts/export-sdtm-metadata.sas を実行）"
}
$clRows = Import-Csv $clCsv
$clByVar = $clRows | Group-Object { "$($_.domain).$($_.variable)" }

$clReplaced = 0; $clOrphan = 0

foreach ($g in $clByVar) {
  $dom, $var = $g.Name -split '\.', 2
  $it = $mdv.ItemDef | Where-Object { $_.OID -eq "IT.$dom.$var" } | Select-Object -First 1
  if (-not $it) { Write-Host "  CodeList 同期: ItemDef が無い IT.$dom.$var （読み飛ばす）"; continue }

  $mode = $g.Group[0].mode
  $vals = @($g.Group | ForEach-Object { $_.value } | Sort-Object -Unique)

  # add は既存 CodeList の値も残す（未使用の CRF 選択肢を落とさない）
  if ($mode -eq 'add' -and $it.CodeListRef) {
    $old = $mdv.CodeList | Where-Object { $_.OID -eq $it.CodeListRef.CodeListOID } | Select-Object -First 1
    if ($old) {
      $oldVals = @(@($old.EnumeratedItem) + @($old.CodeListItem) |
                   Where-Object { $_ } | ForEach-Object { $_.CodedValue })
      $vals = @(@($vals) + $oldVals | Where-Object { $_ } | Sort-Object -Unique)
    }
  }
  $newOid = "CL.$dom.$var"

  # 既に同名の CodeList があれば作り直す
  $ex = $mdv.CodeList | Where-Object { $_.OID -eq $newOid } | Select-Object -First 1
  if ($ex) { $ex.ParentNode.RemoveChild($ex) | Out-Null }

  $cl = $x.CreateElement('CodeList', $ns)
  $cl.SetAttribute('OID', $newOid)
  $cl.SetAttribute('Name', "$dom $var")
  $cl.SetAttribute('DataType', $(if ($it.DataType -eq 'text') { 'text' } else { $it.DataType }))
  $n = 0
  foreach ($v in $vals) {
    $n++
    $ei = $x.CreateElement('EnumeratedItem', $ns)
    $ei.SetAttribute('CodedValue', $v)
    $ei.SetAttribute('OrderNumber', "$n")
    $cl.AppendChild($ei) | Out-Null
  }
  $clNodes = @($mdv.CodeList)
  if ($clNodes.Count -gt 0) { $mdv.InsertAfter($cl, $clNodes[-1]) | Out-Null }
  else { $mdv.AppendChild($cl) | Out-Null }

  # ItemDef の参照を差し替える
  if ($it.CodeListRef) { $it.CodeListRef.SetAttribute('CodeListOID', $newOid) }
  else {
    $ref = $x.CreateElement('CodeListRef', $ns)
    $ref.SetAttribute('CodeListOID', $newOid)
    $it.AppendChild($ref) | Out-Null
  }
  $clReplaced++
  Write-Host ("  CodeList 同期[{0}]: {1}.{2} → {3}（{4} 値）" -f $mode, $dom, $var, $newOid, $vals.Count)
}

# 誰からも参照されていない CodeList を消す
# 2026-08-20 修正：以前は上の差し替えで置き換えた OID だけを見ていたため、値水準の
# --TESTCD を実データに合わせて落としたときに参照が切れた CodeList（CL.VL7765 など）と、
# 受領 define.xml の時点でどの ItemDef からも参照されていない CodeList（CL.VA7755 など）が
# 残っていた。CodeListRef をすべて集めてから、参照の無い CodeList を落とす形にする。
# 受領 define.xml 自体は読み取り専用なので、削除はこの出力側だけに効く。
$clUsed = @{}
foreach ($ref in @($mdv.SelectNodes(".//*[local-name()='CodeListRef']"))) {
  $refOid = $ref.GetAttribute('CodeListOID')
  if ($refOid) { $clUsed[$refOid] = $true }
}
$clOrphanOids = @()
foreach ($cl in @($mdv.CodeList)) {
  if ($clUsed.ContainsKey($cl.OID)) { continue }
  $clOrphanOids += $cl.OID
  $cl.ParentNode.RemoveChild($cl) | Out-Null
  $clOrphan++
  Write-Host "  参照されていない CodeList を削除: $($cl.OID)"
}
Write-Host ("CodeList : 差し替え {0} / 孤立を削除 {1}" -f $clReplaced, $clOrphan)
if ($clOrphan -gt 0) {
  Write-Host ("  削除した OID: {0}" -f (($clOrphanOids | Sort-Object) -join ', '))
}

# DSCAT のコードリストに OTHER EVENT を足す。CSVtoSDTM.sas が DSSPID='tki_change1'
# の21件を OTHER EVENT へ置き換えるが、受領 define.xml のコードリストは
# DISPOSITION EVENT の1値しか持たない（docs/records/sdtm-conformance-findings-20260815.md A-2）。
$dscatDef = $mdv.ItemDef | Where-Object { $_.Name -eq 'DSCAT' } | Select-Object -First 1
if ($dscatDef -and $dscatDef.CodeListRef) {
  $clOid = $dscatDef.CodeListRef.CodeListOID
  $cl    = $mdv.CodeList | Where-Object { $_.OID -eq $clOid } | Select-Object -First 1
  if ($cl) {
    $items = @($cl.EnumeratedItem)
    if (-not ($items | Where-Object { $_.CodedValue -eq 'OTHER EVENT' })) {
      $ei = $x.CreateElement('EnumeratedItem', $ns)
      $ei.SetAttribute('CodedValue', 'OTHER EVENT')
      $ei.SetAttribute('OrderNumber', "$($items.Count + 1)")
      $cl.AppendChild($ei) | Out-Null
      Write-Host "DSCAT のコードリスト $clOid に OTHER EVENT を追加しました"
    }
  } else { throw "DSCAT のコードリストが見つかりません: $clOid" }
}

# ---- CodeList に Decode を載せる ------------------------------------------------------
# 値が略号やコードで意味が別にある CodeList を CodeListItem + Decode にする。値そのものが
# 英語の名称になっている CodeList（FAOBJ 60値・Microorganism 1508値・--TEST など）は
# EnumeratedItem のままにする。Decode を付けても同じ文字列の重複になるため。
# Define-XML 2.0 は1つの CodeList に EnumeratedItem と CodeListItem を混在できないので、
# 対象の CodeList は全項目を CodeListItem に置き換える。
#
# 2026-08-20 変更：Decode の正本を docs/metadata/codelist-decode.csv に移した。それまでは Y/N/NA と
# SEX の対応をハッシュで、--TOXGR を "Grade $v" の規則で、VISITNUM を docs/metadata/trial-design/tv.csv
# の参照でこのスクリプトが持っていた。受領 define.xml が値・CodeListRef の割り当ての正本で
# ある一方、英語の Decode はどこにも無いので、その差分だけを CSV に持つ
# （docs/spec/label-and-traceability-design.md の決定事項）。スクリプトは処理だけを持つ。
# --TESTCD の Decode は CSV に写さない。対応する --TEST は実データ（sdtm_valuelevel.csv）から
# 来るため、データが変われば Decode も変わる。CSV に写すと二重持ちになってズレる。実データに
# 無い --TESTCD（LB の PATHOGEN）の1件だけ CSV が穴埋めする。
# 対応が無い値には Decode を作らない。値と同一の Decode（以前のフォールバック）は情報を
# 持たないため。ただし混在できない制約から、全値の Decode がそろわない CodeList は
# EnumeratedItem のまま残し、件数を報告する。
$decCsv = Join-Path (Split-Path $PSScriptRoot -Parent) 'docs\codelist-decode.csv'
if (-not (Test-Path $decCsv)) { throw "Decode の対応表がありません: $decCsv" }
$decByCl = @{}
$decRows = 0
# VISITNUM の Decode は docs/metadata/trial-design/tv.csv が正本（SDTM の TV ドメインの入力そのもの）。
# 対応表へ写すと二重持ちになり、tv.csv を直したときにズレる。ここで読んで対応表へ足す
# （2026-08-20。CodeList の OID は受領 define.xml 側の CL.VA7745）。
$tvCsv = Join-Path (Split-Path $PSScriptRoot -Parent) 'docs/metadata/trial-design/tv.csv'
if (Test-Path $tvCsv) {
  $decByCl['CL.VA7745'] = @{}
  foreach ($r in (Import-Csv $tvCsv)) {
    if ($r.visitnum -and $r.visit) { $decByCl['CL.VA7745'][$r.visitnum] = $r.visit; $decRows++ }
  }
  Write-Host ("VISITNUM の Decode : tv.csv から {0} 件" -f $decByCl['CL.VA7745'].Count)
}
else { Write-Host "WARNING: tv.csv がないため VISITNUM の Decode を作らない: $tvCsv" }
foreach ($r in (Import-Csv $decCsv)) {
  if (-not $r.codelist_oid) { continue }
  if (-not $decByCl.ContainsKey($r.codelist_oid)) { $decByCl[$r.codelist_oid] = @{} }
  $decByCl[$r.codelist_oid][$r.coded_value] = $r.decode
  $decRows++
}

# CSV と define.xml の食い違いを数えるため、define.xml 側の（CodeList OID, 値）を先に集める
$clValSet = @{}
foreach ($cl in @($mdv.CodeList)) {
  foreach ($e in @(@($cl.EnumeratedItem) + @($cl.CodeListItem) | Where-Object { $_ })) {
    $clValSet["$($cl.OID)|$($e.CodedValue)"] = $true
  }
}

$dcCl = 0; $dcItem = 0; $dcSame = 0; $dcSkipVals = 0
$dcSkip = @()
foreach ($cl in @($mdv.CodeList)) {
  $eis = @($cl.EnumeratedItem | Where-Object { $_ })
  if ($eis.Count -eq 0) { continue }

  # この CodeList を参照している変数
  $refVars = @($mdv.ItemDef |
    Where-Object { $_.CodeListRef -and $_.CodeListRef.CodeListOID -eq $cl.OID } |
    ForEach-Object { $_.Name })
  $vals = @($eis | ForEach-Object { $_.CodedValue })
  $map = @{}; $src = ''

  $tcVar = $refVars | Where-Object { $_ -match 'TESTCD$' } | Select-Object -First 1
  if ($tcVar) {
    $dom = $tcVar -replace 'TESTCD$', ''
    foreach ($r in ($vlmRows | Where-Object { $_.domain -eq $dom })) { $map[$r.testcd] = $r.test }
    $src = "$dom" + "TEST"
  }
  if ($decByCl.ContainsKey($cl.OID)) {
    foreach ($k in $decByCl[$cl.OID].Keys) {
      if (-not $map[$k]) { $map[$k] = $decByCl[$cl.OID][$k] }
    }
    $src = if ($src) { "$src + codelist-decode.csv" } else { 'codelist-decode.csv' }
  }
  if ($map.Count -eq 0) { continue }

  $miss = @($vals | Where-Object { -not $map[$_] })
  if ($miss.Count -gt 0) {
    $dcSkip += ("{0}[{1}]" -f $cl.OID, (($miss | Sort-Object) -join '/'))
    $dcSkipVals += $miss.Count
    continue
  }

  $n = 0
  foreach ($e in $eis) {
    $n++
    $dec = $map[$e.CodedValue]
    if ($dec -ceq $e.CodedValue) { $dcSame++ }
    $ci = $x.CreateElement('CodeListItem', $ns)
    $ci.SetAttribute('CodedValue', $e.CodedValue)
    $ci.SetAttribute('OrderNumber', "$n")
    $de = $x.CreateElement('Decode', $ns)
    $tt = $x.CreateElement('TranslatedText', $ns)
    $tt.SetAttribute('lang', 'http://www.w3.org/XML/1998/namespace', 'en') | Out-Null
    $tt.InnerText = $dec
    $de.AppendChild($tt) | Out-Null
    $ci.AppendChild($de) | Out-Null
    $cl.InsertBefore($ci, $e) | Out-Null
    $dcItem++
  }
  foreach ($e in $eis) { $cl.RemoveChild($e) | Out-Null }
  $dcCl++
  Write-Host ("  Decode: {0,-22} {1,4} 値  ({2}) ← {3}" -f `
    $cl.OID, $n, ($refVars -join ','), $src)
}

# 対応表と define.xml の食い違いを報告する
$decNoVal = 0
foreach ($oid in $decByCl.Keys) {
  foreach ($v in $decByCl[$oid].Keys) {
    if (-not $clValSet.ContainsKey("$oid|$v")) { $decNoVal++; Write-Host "  対応表にあって define.xml に無い値: $oid の $v" }
  }
}
Write-Host ("CodeList の Decode : {0} CodeList / {1} 項目（対応表 {2} 行）" -f $dcCl, $dcItem, $decRows)
Write-Host ("  対応表にあって define.xml に無い値 {0} 件 / define.xml にあって Decode の無い値 {1} 件" -f `
  $decNoVal, $dcSkipVals)
if ($dcSkip.Count -gt 0) {
  Write-Host ("  Decode がそろわず EnumeratedItem のまま残した CodeList {0} 件: {1}" -f `
    $dcSkip.Count, ($dcSkip -join ', '))
}
if ($dcSame -gt 0) {
  Write-Host ("  値と同一の Decode {0} 件（--TEST の表記が --TESTCD と同じもの）" -f $dcSame)
}

# ---- DOMAIN の CodeList を CT に合わせる -----------------------------------------------
# CORE は DOMAIN の CodeList が持つ NCI の C コード（Alias）を CT の
# SDTM Domain Abbreviation（C66734）と照合する（CORE-000929）。受領 define.xml は EC の
# 項目だけ Alias が抜けており、SDTM 層で作ったドメイン（Trial Design）は CodeList を
# 持たない。CT の写し docs/metadata/external/ct-domain-ccode.csv から補う（スキル cdisc-define-xml の
# export-ct-codelist.py が作る）。Decode は ItemGroupDef のラベルに揃える。受領版が
# 'Demographics' のように CT の preferredTerm から Domain を落とした表記をとっているため。
$ctCsv = Join-Path (Split-Path $PSScriptRoot -Parent) 'docs\metadata\external\ct-domain-ccode.csv'
if (-not (Test-Path $ctCsv)) { throw "ドメインコードの CSV がありません: $ctCsv" }
$domCcode = @{}
foreach ($r in Import-Csv $ctCsv) { $domCcode[$r.submission_value] = $r.code }

$dcAlias = 0; $dcNewCl = 0
foreach ($ig in @($mdv.ItemGroupDef)) {
  $dom = $ig.Name
  $it  = $mdv.ItemDef | Where-Object { $_.OID -eq "IT.$dom.DOMAIN" } | Select-Object -First 1
  if (-not $it) { continue }
  $ccode = $domCcode[$dom]
  if (-not $ccode) { Write-Host "  CT に $dom のドメインコードが無い（読み飛ばす）"; continue }
  $lbl = "$($ig.Description.TranslatedText.'#text')".Trim()
  if (-not $lbl) { $lbl = $dom }

  $clOid = "CL.$dom.DOMAIN"
  $cl = $mdv.CodeList | Where-Object { $_.OID -eq $clOid } | Select-Object -First 1

  if ($cl) {
    # 既にある CodeList は、その値の項目に Alias があるかを見る
    foreach ($e in @(@($cl.CodeListItem) + @($cl.EnumeratedItem) | Where-Object { $_ })) {
      if ($e.CodedValue -ne $dom) { continue }
      if (@($e.Alias | Where-Object { $_ -and $_.Name }).Count -gt 0) { continue }
      $al = $x.CreateElement('Alias', $ns)
      $al.SetAttribute('Context', 'nci:ExtCodeID')
      $al.SetAttribute('Name', $ccode)
      $e.AppendChild($al) | Out-Null
      $dcAlias++
      Write-Host "  DOMAIN の Alias を追加: $clOid の $dom → $ccode"
    }
    continue
  }

  # CodeList が無いドメインは作る
  $cl = $x.CreateElement('CodeList', $ns)
  $cl.SetAttribute('OID', $clOid)
  $cl.SetAttribute('Name', "SDTM Domain Abbreviation ($dom)")
  $cl.SetAttribute('DataType', 'text')
  $cl.SetAttribute('SASFormatName', '$DOMAIN')
  $ci = $x.CreateElement('CodeListItem', $ns)
  $ci.SetAttribute('CodedValue', $dom)
  $de = $x.CreateElement('Decode', $ns)
  $tt = $x.CreateElement('TranslatedText', $ns)
  $tt.SetAttribute('lang', 'http://www.w3.org/XML/1998/namespace', 'en') | Out-Null
  $tt.InnerText = $lbl
  $de.AppendChild($tt) | Out-Null
  $ci.AppendChild($de) | Out-Null
  $al = $x.CreateElement('Alias', $ns)
  $al.SetAttribute('Context', 'nci:ExtCodeID')
  $al.SetAttribute('Name', $ccode)
  $ci.AppendChild($al) | Out-Null
  $cl.AppendChild($ci) | Out-Null
  $alc = $x.CreateElement('Alias', $ns)
  $alc.SetAttribute('Context', 'nci:ExtCodeID')
  $alc.SetAttribute('Name', 'C66734')
  $cl.AppendChild($alc) | Out-Null

  $clNodes = @($mdv.CodeList)
  if ($clNodes.Count -gt 0) { $mdv.InsertAfter($cl, $clNodes[-1]) | Out-Null }
  else { $mdv.AppendChild($cl) | Out-Null }

  if ($it.CodeListRef) { $it.CodeListRef.SetAttribute('CodeListOID', $clOid) }
  else {
    $ref = $x.CreateElement('CodeListRef', $ns)
    $ref.SetAttribute('CodeListOID', $clOid)
    $it.AppendChild($ref) | Out-Null
  }
  $dcNewCl++
  Write-Host "  DOMAIN の CodeList を作成: $clOid（$ccode / $lbl）"
}
Write-Host ("DOMAIN の CodeList : 作成 {0} / Alias 補完 {1}" -f $dcNewCl, $dcAlias)

# ---- ItemRef に Role を付ける ----------------------------------------------------------
# 受領 define.xml は Role を持たず、CORE が「define-xml の role が IG と一致しない」と
# 指摘する（CORE-001081）。SDTM IG 3.2 の Role を docs/metadata/external/sdtmig-3-2-variable-roles.csv から
# 引いて付ける。CSV は scripts/export-sdtmig-roles.py が CDISC CORE のキャッシュ（元は
# CDISC Library）から作る。IG に無い変数（SDTM の標準変数でないもの）には付けない。
# ItemDef は途中で足しているので、この時点で作り直す
$oidName = @{}
foreach ($d in $mdv.ItemDef) { $oidName[$d.OID] = $d.Name }

$roleSet = 0
$roleMiss = @()
foreach ($ig in $mdv.ItemGroupDef) {
  $dom = $ig.Name
  foreach ($ref in @($ig.ItemRef | Where-Object { $_ })) {
    $nm = $oidName[$ref.ItemOID]
    if (-not $nm) { continue }
    $role = $roleOf["$dom.$nm"]
    if (-not $role) { $roleMiss += "$dom.$nm"; continue }
    if ($ref.GetAttribute('Role') -ne $role) { $ref.SetAttribute('Role', $role); $roleSet++ }
  }
}
Write-Host ("ItemRef の Role : {0} 件に付けた / IG に無い変数 {1} 件" -f $roleSet, $roleMiss.Count)
if ($roleMiss.Count -gt 0) {
  Write-Host ("  IG に無い変数: {0}" -f (($roleMiss | Sort-Object -Unique) -join ', '))
}

# 作成日時と由来を更新
$x.ODM.SetAttribute('CreationDateTime', (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
$x.ODM.SetAttribute('SourceSystem', '<試験ID>_CSVtoSDTM.sas')

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
$outXml = Join-Path $outDir 'define.xml'
$x.Save($outXml)

# .NET は xml 名前空間に独自の接頭辞（d6p1 等）を割り当てて宣言を書き出す。
# xml は予約接頭辞で再バインドできないため、Python の XML パーサ（CORE）が
# "prefix must not be bound to one of the reserved namespace names" で落ちる。
# 保存後に xml:lang へ書き戻す。
$raw = Get-Content $outXml -Raw -Encoding UTF8
$raw = [regex]::Replace($raw, '\s+xmlns:d\d+p\d+="http://www\.w3\.org/XML/1998/namespace"', '')
$raw = [regex]::Replace($raw, 'd\d+p\d+:lang=', 'xml:lang=')
[IO.File]::WriteAllText($outXml, $raw, (New-Object Text.UTF8Encoding($false)))
Copy-Item (Join-Path $srcDir 'define2-0-0.xsl') (Join-Path $outDir 'define2-0-0.xsl') -Force
$labelRows | Export-Csv $labelCsv -NoTypeInformation -Encoding UTF8

# Dataset-JSON 生成に要るデータセット単位の情報も出す（SDTMtoJSON.sas が読む）
$dsRows = foreach ($ig in $mdv.ItemGroupDef) {
  $lbl = ''
  if ($ig.Description -and $ig.Description.TranslatedText) { $lbl = ($ig.Description.TranslatedText.'#text').Trim() }
  [pscustomobject]@{
    dataset            = $ig.Name
    label              = $lbl
    itemGroupOID       = $ig.OID
    studyOID           = $x.ODM.Study.OID
    metaDataVersionOID = $mdv.OID
  }
}
$dsRows | Export-Csv (Join-Path $outDir 'sdtm_datasets.csv') -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "出力: $outXml"
Write-Host "ItemGroupDef 新規 $newGroups / ItemDef 追加 $added / 既存更新 $updated"
Write-Host "ラベル一覧: $labelCsv（$($labelRows.Count) 変数）"
