---
name: cdisc-define-xml
description: SDTM と ADaM の define.xml を CDISC の定義に合わせて作る・整えるスキル。SDTM は受領 define.xml の編集、ADaM は変数マップからの新規生成という2つの型を持つ。受領 define.xml に Role が無い・CodeList が実データと食い違う・値水準メタデータが古い・CodeList に Decode が無いといった不備を検出して直す。CDISC CORE の指摘（CORE-001081 の Role 照合、CORE-000355 の必須変数、CORE-000334 の Expected 変数、CORE-000929 の DOMAIN コード照合など）の意味が分からないとき、define.xml を作り直すとき、Define-XML 2.0 で CORE が落ちるとき、CORE の指摘が多くて仕分けたいときに使う。CDISC Library と CT の写しを CSV に落とすスクリプト（IG の Role・Core・ラベル、ADaM IG の Core、CT のコードリスト）を同梱する。 ADaM の define.xml を変数マップ・Dataset-JSON・CodeList の CSV から生成するスクリプトも同梱する（試験の情報は引数、CodeList と試験固有のデータセットは CSV で渡す）。
---

# define.xml の作成と整備

EDC やデータセンターから受領する define.xml は、SDTM 層で変数を足したり値を書き換えたりした
あとの実データと食い違う。CDISC CORE はその食い違いを指摘するが、**メッセージだけでは何を
どう直すか分からないことが多い**。ここでは検出と修正の型をまとめる。

以下 `$SKILL` は**このSKILL.mdが置かれているディレクトリの絶対パス**。symlink 経由で
読み込まれていても実体のディレクトリを解決して使う。

## 1. 材料を引く

SDTM IG の Role・Core（Req/Exp/Perm）・ラベルを CSV に落とす。**手で調べない。**

```bash
python "$SKILL/scripts/export-sdtm-metadata.py" --out docs/sdtmig-3-2-variable-roles.csv \
       --domains-from <変数メタデータCSV>
```

`--domains-from` には `memname` / `dataset` / `domain` 列を持つ CSV を渡す（SAS の
`dictionary.columns` を書き出したものなど）。CDISC CORE のキャッシュから読むので、
CORE の場所が違うときは `--cache` で指定する。

**Role の出どころは2つある。** IG のドメイン変数リストと、SDTM モデルのクラス共通変数
（`EPOCH`・`VISIT`・`--DY`・`--SEQ`・`--LNKGRP` など）。前者だけでは足りず、後者は `--` を
ドメインのプレフィックスに展開して重ねる。Trial Design と Relationship は被験者の観測では
ないので `General Observations` を継承しない。

コントロールドタームは別のスクリプトで引く。CodeList に載せる NCI の C コード（`Alias`）と
`Decode` の表示名（`preferredTerm`）の正本である。

```bash
python "$SKILL/scripts/export-ct-codelist.py" --out docs/ct-domain-ccode.csv --codelist C66734
python "$SKILL/scripts/export-ct-codelist.py" --list     # 何があるかを見る
```

`--codelist` は C コードでも提出値（`DOMAIN`）でも名前の一部でも指せる。

### CDISC Library のラベルには誤記がある

Library の写しをそのまま使うと、誤ったラベルが define.xml と Dataset-JSON に流れる。
SDTMIG 3-2 で実測した例。

- `TI.IETESTCD` … `Incl/Excl Criterion Short Name e`（末尾の `e` が余分）
- `QS.QSSTRESC` … `Character Result/Finding in Standard Format`（43文字。SDTM は変数ラベルを
  40文字以内と定める。他の6ドメインの `--STRESC` はすべて 38文字の `... in Std Format`）

`export-sdtm-metadata.py` の `LABEL_FIXES` が補正する。**補正すると `CORE-000594`（title case
でない）や `CORE-000019`（40文字超）の代わりに `CORE-000398`（ラベルが IG と一致しない）が
同数だけ立つ。** どちらを選んでも件数は変わらないので、ラベルの正しさを取る。逸脱の理由は
記録に残す。

**誤りと判断できるかを確かめてから直す。** `QSSTRESC` は他の6ドメインが同じ表記だから
誤りと言えた。40文字を超えるラベルは他に `FA.FALAT`（43文字）と `MH.MHREASND`（47文字）も
あるが、短縮後の表記の根拠が無いので直していない。

## 2. 不備を検出する

```bash
python "$SKILL/scripts/check-define-xml.py" --define <define.xml> \
       --roles docs/sdtmig-3-2-variable-roles.csv --data <Dataset-JSON か sas7bdat のディレクトリ>
```

10項目を見る。オプションは `--help` が正本。終了コードは検出があれば 1。

ADaM の define.xml も同じスクリプトで検査する。`--roles` は SDTM IG の CSV なので渡さない
（Role と Required/Expected の2項目が飛ぶ）。

```bash
python "$SKILL/scripts/check-define-xml.py" --define <ADaM の define.xml> --data <ADaM の JSON>
```

`def:Class` の値セットは `MetaDataVersion/@def:StandardName` を見て切り替わる。

**「CodeList にあって実データに無い値」は不備として数えない。** CRF の選択肢として定義され
ていて誰も選ばなかった値であり、落とすと情報が失われる。数えるのは逆（実データにあって
CodeList に無い値）。

**CodeList の共有は、値集合が同じなら正しい。** `--PRESP` と `--BLFL` の Y/N、`--DOSU` と
`--ORRESU` の単位、MedDRA や薬剤辞書は共有していてよい。`--TESTCD` を含む共有だけが明確な
誤りで、コード（`--TESTCD`）と名称（`--TEST`）は別の値集合であり、ドメインが違えば
`--TESTCD` の値集合も違う（`LBTESTCD` と `MBTESTCD` の共有は誤り）。

## 3. 何を正本にするか

受領 define.xml を編集する形と、変数マップから新規生成する形がある。**受領版が持つ情報の
量で決める。** 受領版が CodeList・Origin・Comment を持っているなら、それを捨てて新規生成
するのは情報の損失になる。編集を続けて、層ごとに正本を決める。

- 変数の型・長さ・順序 … 実データ（SAS データセット / Dataset-JSON）
- Role・Core・ラベル … SDTM IG（`export-sdtm-metadata.py` の CSV）
- CodeList・Origin・Comment … 受領 define.xml。ただし SDTM 層で値を扱った変数は実データ
- 値水準メタデータの `--TESTCD` … 実データ
- 言語 … 英語のみ。日本語のラベルは別のカタログが持つ

ADaM の define.xml は受領版が無いので新規生成になる。変数マップ（`origin`・`predecessor` を
手で維持する CSV）と Dataset-JSON から作る。

**IG の値をスクリプトの中に写さない。** 実測した失敗：ラベル表をスクリプトのハッシュに
59変数分ハードコードしていたところ、そのうち53が IG の CSV と同じ値の写しになっていた。
写しは変数名だけをキーにしていたためドメインの区別ができず、`--STRESC` のように IG が
ドメインごとに違うラベルを定める変数で取り違えが起きる。CSV を正本にして `$dom.$name` で
引く形に直し、ハッシュには IG の一覧に載らない変数だけを残した。

同じ理由で、CodeList の値・ドメインの C コード・Required の一覧もスクリプトに書かない。
CSV に落として引く。

## 4. 直し方

### Role が無い（CORE-001081）

受領 define.xml は `ItemRef/@Role` を持たないことが多い。IG の Role を付ける。
**`def:Class` が読めないと CORE はこのルールを EXECUTION ERROR にするので、指摘が
「無い」ように見える**。`def:Class` を直すと初めて全変数の Role 欠落が見える。

### def:Class

Define-XML 2.0 の値セットは `EVENTS`・`FINDINGS`・`INTERVENTIONS`・`RELATIONSHIP`・
`SPECIAL PURPOSE`・`TRIAL DESIGN` の6つ。**`FINDINGS ABOUT` は 2.1 で追加された値**で、
2.0 では `FINDINGS` を使う。受領版が小文字（`events`）になっていることもある。

### 空の TranslatedText

`Description` の中が空なら変数ラベルが無い。値水準メタデータの ItemDef で起きやすく、
`--TEST`（`--TESTCD` に対応する完全名）を入れると意味のある記述になる。実データから
`--TESTCD` → `--TEST` の対応を出して埋める。

### SASFieldName が不正

値水準メタデータの ItemDef で、`Name` と `SASFieldName` の両方に `--TESTCD` の値を入れて
いることがある。`SASFieldName` は SAS の変数名（空白なし・8文字以内）でなければならず、
**親変数名（`FAORRES` など）を入れる**のが正しい。

### CodeList を実データに合わせる

扱いは2つに分ける。**全 CodeList を実データで置き換えてはいけない。**

- replace … SDTM 層で値体系を作り直した変数。実データの値だけにする
- add … CRF の選択肢に SDTM 層で値を足した変数。既存の値との和にする

どちらも専用の CodeList（`CL.<DOM>.<VAR>`）を作って差し替えると、共有していた誤りも同時に
解ける。参照されなくなった CodeList は落とす。対象変数のリストは生成側のスクリプトに置き、
CSV で受け渡す。

### CodeList に Decode を載せる

`EnumeratedItem`（値のみ）から `CodeListItem` + `Decode`（値と意味）へ変える。**Define-XML
2.0 は1つの CodeList に両方を混在できない**ので、対象の CodeList は全項目を変える。

Decode に意味があるのは、値が略号やコードのものだけ。

- `--TESTCD` … 対応する `--TEST` を Decode に（実データから引く）
- `Y` / `N` … `Yes` / `No`
- `--TOXGR` … `Grade N`

**値そのものが英語の名称になっている CodeList は `EnumeratedItem` のままにする**（`--TEST`
系、`FAOBJ`、微生物名など）。Decode を付けても同じ文字列の重複になる。

### 値水準メタデータを実データに合わせる

SDTM 層で `--TESTCD` を是正していると、受領版の値水準メタデータが古いままになる。
実データに無い `--TESTCD` の ItemDef・WhereClauseDef・ItemRef を落とし、実データにあって
define に無い値を3点セットで足す。`WhereClauseDef` は `RangeCheck`（`def:ItemOID` +
`CheckValue`）で条件を書く。

### DOMAIN の CodeList に C コードを付ける（CORE-000929）

CORE は `DOMAIN` 変数の CodeList が持つ NCI の C コード（`Alias/@Name`）を CT の
`SDTM Domain Abbreviation`（C66734）と照合する。`Alias` が欠けていると「CT に無いドメイン
コード」として指摘される。受領 define.xml は一部のドメインだけ `Alias` が抜けていることが
あり（実測では EC の1件）、自分で足したドメインは CodeList そのものを持たない。

```xml
<CodeList OID="CL.EC.DOMAIN" Name="SDTM Domain Abbreviation (EC)" DataType="text"
          SASFormatName="$DOMAIN">
  <CodeListItem CodedValue="EC">
    <Decode><TranslatedText xml:lang="en">Exposure as Collected</TranslatedText></Decode>
    <Alias Context="nci:ExtCodeID" Name="C117466"/>
  </CodeListItem>
  <Alias Context="nci:ExtCodeID" Name="C66734"/>
</CodeList>
```

CodeList 自体の `Alias` は C66734（コードリストの C コード）、項目の `Alias` はドメインの
C コード。`Decode` は ItemGroupDef のラベルに揃える（CT の `preferredTerm` は
`Exposure as Collected Domain` のように `Domain` が付くが、受領版は付けない流儀を
とっていることが多い）。C コードは `export-ct-codelist.py` の CSV から引く。

### 新しいドメインの ItemGroupDef

受領版に無いドメイン（SDTM 層で作ったもの、Trial Design）は新規に作る。**Class・Structure・
Label をドメインごとの表に持つ**。生成スクリプトが1ドメイン分をハードコードしていると、
次のドメインで止まる。ラベルは IG の CSV から補うフォールバックを入れる。

## 5. ADaM の define.xml

ADaM には受領版が無いので**新規生成**になる。入力は4つ。

- 変数マップ … `label_en` と `origin`（`Predecessor` / `Derived` / `Assigned` / `CRF` /
  `Protocol`）・`predecessor`（`DM.RFSTDTC` のような参照元）を手で維持する CSV。**これが正本**
- Dataset-JSON … 変数の型・長さ・ラベル・順序（ADaM を作るプログラムの出力）
- ADaM IG の変数一覧 … `ItemRef/@Mandatory` の判定に使う（`export-adam-metadata.py` の出力）
- CodeList の定義 … 値と Decode を持つ CSV（後述）

`Origin` は ADaM の define.xml でいちばん価値がある情報である。変数が SDTM のどこから
来たのか、導出なのか固定値なのかが機械可読になる。**`predecessor` が実在する SDTM 変数を
指しているかを検証する**（誤った参照は追跡索引まで壊す。実測で14件見つかった）。

### 生成スクリプト

```bash
python "$SKILL/scripts/build-adam-define.py" --json-dir <Dataset-JSON のディレクトリ> \
       --variable-map docs/variable-map.csv --adam-ig docs/adamig-1-1-variables.csv \
       --codelist docs/adam-codelist.csv --out <出力する define.xml> \
       --study-oid <試験の OID> --study-description "..." --protocol-name "..." \
       --originator "..." --xsl-from <SDTM 側の define2-0-0.xsl>
```

オプションは `--help` が正本。試験ごとに変わるものは引数と CSV が持ち、スクリプトが持つのは
Define-XML 2.0.0 の骨格・ItemRef の並べ方・`def:Origin` の付け方と、ADaM の標準に沿う
`def:Class` / `def:Structure` の表（`DS_META`。ADSL・ADTTE・ADRS・ADLB・ADVS・ADEC・ADAE・
ADCM・ADMH）だけ。試験固有のデータセットは `--dataset-meta` の CSV
（`dataset,class,structure,repeating`）で足す。同名を書けば標準の値を上書きする。

呼び出し側は試験のリポジトリに薄い起動スクリプトを1つ置き、試験の情報と生データの置き場の
パスだけを持たせる（実例は試験リポジトリの `scripts/build-adam-define.py`）。**この
スクリプトの引数に試験固有の既定値を入れない。**

`--creation-datetime` を渡さないと `ODM/@CreationDateTime` は実行日の `00:00:00` になる。
時刻まで入れると再実行のたびに差分が出るのでそうしている。版を固定したいときだけ渡す。

他の試験へ持っていくときに差し替えるもの。

- 引数 … `--study-oid`・`--study-name`・`--study-description`・`--protocol-name`・
  `--originator`、入出力のパス、`--standard-version`（ADaM IG の版）
- 変数マップ … 試験ごとに全面的に作る
- CodeList の CSV … 試験固有の値が多いので流用できない
- ADaM IG の変数一覧 … `export-adam-metadata.py` で作り直す（IG の版が同じなら流用できる）

### 変数のラベルと Core の出どころ

ADaM の変数は3種類に分かれる。**ラベルの出どころが違う。**

- ADaM IG の変数（`TRT01P`・`AVAL`・`PARAMCD`・`ANL01FL` など）… IG が持つ
- SDTM から転記した変数（`AETERM`・`AESPID`・`CMTRT` など）… SDTM IG が持つ
- 試験固有の派生変数（`SAEPFL`・`TKIGRP` のようなフラグ）… 試験が決める

実測では ADaM 312変数のうち IG から引けたのは125で、残り187は転記か試験固有だった。
**したがってラベルの正本は変数マップに置く。** IG は Required の判定と、IG からの逸脱を
見つけるために使う。

```bash
python "$SKILL/scripts/export-adam-metadata.py" --out docs/adamig-1-1-variables.csv
```

**ADaM IG は SDTM と構造が違う。** データセットごとではなく変数グループごとに定義されて
いて（`ADSL Identifier Variables`・`Timing Variables for BDS Datasets` など23グループ）、
どのグループがどのデータセットに当たるかは実装側が決める。CSV は「変数名 → Core・ラベル」の
辞書として使う。

**変数名にパターンが入る。** `TRTxxP`・`ANLzzFL`・`AGEGRy` のような形で、実データは
`TRT01P`・`ANL01FL`・`AGEGR1` になる。CSV の `regex` 列で照合する（完全一致を先に見る）。

### IG からの逸脱を見る

Required の変数が揃っているかを照合すると、設計上の抜けが見つかる。実測では ADaM IG 1.1 が
ADSL に求める `ARM` が無かった（単群で `TRT01P` に群名を入れていたため）。**単群試験でも
`ARM` は Required** なので、持たない判断をするなら理由を仕様書に書く。

### CodeList

ADaM の CodeList は試験固有の値が多く、CDISC CT に無いものが混ざる（分子遺伝学的効果の
区分、TKI の使用パターンなど）。**値の意味を Decode に載せる価値が高い。** とくに向きが
試験で違う変数は必ず載せる（`CNSR` が 0=イベント / 1=打ち切りか、その逆か）。

CodeList の定義をスクリプトにハードコードしない。`--codelist` の CSV が持つ。列は
`codelist_oid,codelist_name,datatype,variables,coded_value,decode,source`。

- `codelist_name`・`datatype`・`variables`・`source` は CodeList ごとに1回書けばよい
  （2行目以降は空でよい）
- `variables` は空白区切りの変数名。データセットを問わず同名の変数は同じ CodeList を参照する。
  `*` を含む項目はパターンで、**文字型・長さ1の変数にだけ当たる**（ADaM のフラグ変数の
  約束）。完全一致が優先
- 出力の順序は CSV に現れた順。どの変数からも参照されない CodeList は出力しない
- `coded_value` に `include:<CSV>|<値の列>|<Decode の列>|<列>=<値>|<列>~<部分一致>` と書くと、
  項目を別の CSV から引く。値の正本が他にある CodeList（ラベルカタログが持つ水準など）を
  写さずに参照するために置いた

**SDTM 側と ADaM 側で CSV の役割が違う。** SDTM は受領 define.xml が値を持つので CSV は
Decode の差分だけを持つ（`codelist_oid,coded_value,decode,source`）。ADaM は受領物が無いので
値も CSV が持ち、`coded_value` が正本になる。ADaM の CSV から行を落とすと define.xml から
その値が消える。

`*FL` のパターンには長さ1の条件が付くので、**SDTM から転記した Y/N 変数は拾われない**。
`AESER`・`--OCCUR`・`--BLFL` は値が `Y` / `N` でも長さ3で定義されていることがある。
CodeList を付けるなら `variables` に変数名を並べて書く（完全一致は型と長さを見ない）。

### データセットのメタデータ

`def:Class` は ADaM の構造（`SUBJECT LEVEL ANALYSIS DATASET`・`BASIC DATA STRUCTURE`・
`OCCURRENCE DATA STRUCTURE`）、`def:Structure` は `One record per subject per parameter` の
ような記述。`Repeating` は ADSL だけ `No`。

**値セットの正本は CT の General Observation Class（C103329）で、SDTM の Observation Class と
ADaM の構造が同じコードリストに入っている。**

```bash
python "$SKILL/scripts/export-ct-codelist.py" --list --package define-xmlct-<日付>
python "$SKILL/scripts/export-ct-codelist.py" --out class.csv --codelist C103329 \
       --package define-xmlct-<日付>
```

ただし Define-XML 2.0 のスキーマが許すのは SDTM の6語（`EVENTS`・`FINDINGS`・
`INTERVENTIONS`・`RELATIONSHIP`・`SPECIAL PURPOSE`・`TRIAL DESIGN`）だけで、ADaM の構造名は
2.1 で使えるようになった値である。**ADaM の define.xml を CORE の検証対象に入れるなら
`def:Class` を外すか 2.1 で書く。** 検証に回さず読み手に渡すだけなら、構造が分かるほうが
有益なので載せる。どちらを選んだかは記録に残す。

### 言語

**英語のみにする。** 日本語のラベルを define.xml に入れると、共有先のツールで扱いにくく
なるうえ、ラベルの正本が2つになる。日本語はラベルカタログと PI 向けの HTML が持つ。


## 6. CORE との関係

**ルールの status で判断する。** 指摘の件数だけを見ると誤読する。

- `EXECUTION ERROR` … ルールが実行できていない。define.xml が読めないのが主因
- `SKIPPED` … 対象のドメインや外部辞書が無い。合格ではない
- `ISSUE REPORTED` … 実行できて指摘があった

define.xml を直すと `EXECUTION ERROR` が `ISSUE REPORTED` に変わり、**指摘が急に増えたように
見える**。実際は検証が通るようになった前進である。

**指摘の内容が分からないときはルール定義を読む。** CORE のキャッシュの `rules.pkl` は
core_id をキーにした dict で、`conditions` に期待する値の一覧が入っている。

`ITEMGROUPDATASEQ`（Dataset-JSON のレコード識別子）に対する形式上の指摘は、ドメインごとに
各1件ずつ出る（変数名8文字超・Model の許可変数外・ラベルが title case でない・変数の順序・
型の不一致）。CORE のリーダーがこの列を必須とするため付けているもので、実データの欠陥では
ない。

Expected 変数の欠落（`CORE-000334`）は、置かない方針なら受け入れる。Required の欠落
（`CORE-000355`）は直す。

### 指摘の仕分けを CSV で持つ

同じ指摘を毎回読み直すのは無駄で、件数の多い既知の指摘に新規の指摘が埋もれる。仕分けの
状態を CSV（`core_id,disposition,note,ref`）に持ち、検証スクリプトの集計で既知と未仕分けを
分けて出す。`disposition` は `known`（判断が済んで対応しない）と `open`（決まっていない）の
2つで足りる。詳細は `ref` が指す文書に書き、CSV の `note` は1行にする。

**CORE の `--exclude-rules`（`-er`）でルールを除外する形にはしない。** 除外すると何を外した
かが検証結果の JSON に残らず、データの設計が変わって指摘の性質が変わっても気づけない。
外部の提供先が自分で CORE を回せば同じ指摘が出るので、こちらで消しても意味がない。検証は
素のまま回して全件を JSON に残し、集計の段で分ける。

**件数の内訳を必ず見る。** 1つのルールの指摘が複数の原因の混合であることがある。実測例：
FA のベースラインフラグの重複261件は、166行が CRF の構造（1つの `FAOBJ` に2種類の観測が
入っている）で、95行はルールのグルーピングキーに `FAOBJ` が入らないことによる偽陽性
だった。前者は直せるが後者は直せない。

`EXECUTION ERROR` のルールも `Issue_Summary` に各1件として現れる。指摘の件数に混ぜると
誤るので、`Rules_Report` の `status` で分ける。

## 7. 落とし穴

- **.NET の `XmlDocument` は `xml:lang` に独自の接頭辞（`d6p1` など）を割り当てて書き出す。**
  `xml` は予約接頭辞で再バインドできないため、Python の XML パーサ（CORE の odmlib）が
  「prefix must not be bound to one of the reserved namespace names」で落ちる。保存後に
  文字列置換で `xml:lang` へ戻す
- **`def:` の要素を作るときは接頭辞を明示する。** `CreateElement(name, ns)` だと
  `xmlns="..."` が付くことがある。`CreateElement('def', name, ns)` を使う
- MetaDataVersion の子要素には順序がある（`def:ValueListDef` → `def:WhereClauseDef` →
  `ItemGroupDef` → `ItemDef` → `CodeList` → `MethodDef` → `def:leaf`）。要素を足すときは
  同じ種類の最後の要素の後に挿入する
- CORE の一部のルールは `-dxp` とは別に、**データセットと同じフォルダの define.xml を直接
  開く**。検証の前にコピーを配置する。片方だけ更新すると古い方が読まれる
- **`core.exe validate --help` は日本語環境（cp932）で落ちる。** ヘルプ文に `█` が入って
  おり `UnicodeEncodeError` になる。`PYTHONIOENCODING` も `chcp 65001` も効かない
  （PyInstaller の onefile がロケールから決めるため）。オプションの有無を知りたいときは
  `core.exe validate <オプション> X -d nosuchdir` を試して `No such option` が出るかを見る。
  click が候補を出してくれるので正しい綴りも分かる
- **ラベルを put で JSON へ埋める処理は、空ラベルで不正な JSON を作る。** SAS が引用符を
  エスケープと解釈して `"label": """` のようになる。ERROR は出ないので、生成後に JSON として
  読めることを必ず確かめる（実測で20ファイル全滅を検出した）
