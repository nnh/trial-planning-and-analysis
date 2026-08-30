# Ptosh 由来データの SDTM 整備

作成日：2026-08-15
改訂日：2026-08-22

Ptosh（データセンターの EDC）から受領した、SDTM のドメイン名・変数名は使うが派生変数を持たない CSV と define.xml を、CDISC CORE で検証できる状態にするまでの手順。試験A で 2026-08-15 に実施した内容を、他試験でも使える形に整理したもの。

CORE 自体の使い方・導入・実行時の落とし穴は [`sdtm-conformance-validation.md`](sdtm-conformance-validation.md) が正本。本書は「渡すデータを作る側」を扱う。

実装は試験リポジトリの次のファイルにある。試験名とパスを差し替えれば他試験でも動く。

- `program/<試験ID>_CSVtoSDTM.sas` — 受領CSV → SDTM データセット
- `program/<試験ID>_SDTMtoJSON.sas` — SDTM → Dataset-JSON v1.1
- `scripts/export-sdtm-metadata.sas` — 変数メタデータの書き出し
- `scripts/update-define-xml.ps1` — 受領 define.xml に derived 変数を反映
- `scripts/run-sdtm-validation.ps1` — 上記4本と CORE を一続きで実行

## 全体の流れ

1. 受領データの実値スキャン（何が入っていて何が無いかを機械的に確認する）
2. SDTM データセットの生成（required・expected の派生変数を埋める）
3. define.xml の更新（derived 変数と、define に無いドメインを足す）
4. Dataset-JSON の生成
5. CORE による検証
6. 指摘の切り分け

3〜5は `run-sdtm-validation.ps1` が一続きで回す。1と2は試験ごとに中身を作る。

## 1. 受領データの性質

Ptosh から受領する `input/rawdata/*.csv` に共通する性質。試験A で確認したもので、他試験でも同じ構造で来る可能性が高い。着手時に実値スキャン（`program/QC/*_QC01_RawDataScan.sas` 相当）で確かめる。

- SDTM のドメイン名・変数名を使っているが、派生変数が入っていない
- `proc import` で読むと全変数が文字型になる。値がクォートされているため
- 日付は `YYYY-MM-DD` の完全形式で、部分日付が無い。日付の補完規則を設ける必要がない
- CRF のシート名が `--SPID` に入る。解析の抽出条件はここに依存することが多い
- 随時提出の報告シート（再発報告・変更報告など）は `VISITNUM` を持たない
- `VISITNUM` は治療コースと評価時点を表す数値コードで、体系は試験ごとに異なる
- ベースラインの結果を1枚のシートで集める運用のため、そのシートのレコードには `--BLFL` の既定値として `Y` が入る。フラグを後から付ける手間を省く設計で、検査が行われなかったレコードにも `Y` が残る（2.10）
- 同じカテゴリの中でも項目の尋ね方が違う。有無を選択させる項目と、数量だけを入力させる項目が混在し、後者は `--OCCUR` が空で来る（2.11）
- 値が入力されなかった項目のレコードを出力しない機能がある。`--ORRES` などに値が無い、つまり投与や実施が無かった項目はレコードそのものが出ない。レコードの不在は「行われなかった」を意味し、入力漏れではない（2.11）

欠けている派生変数は概ね次のとおり。

- 相対日 `--DY` が全ドメインに無い
- `EPOCH` は DS 以外に無い
- `VISIT` は LB 以外に無い
- DM に `AGE`・`AGEU`・`ARMCD`・`ARM`・`ACTARMCD`・`ACTARM`・`RFXSTDTC`・`RFXENDTC`・`RFPENDTC`・`DTHDTC`・`DTHFL` が無い
- 標準化結果 `--STRESC`・`--STRESN`・`--STRESU` が無い
- CE に `CESTDTC` が無く `CEDTC` だけがある

## 2. CORE を通すために必要な導出

各項目に、なぜ必要かを添える。

### 2.1 --SEQ

受領値をそのまま数値化する。被験者内で一意であることを検証し、重複があるドメインだけ再採番する。CORE は一意性を見るルールを持つ。

### 2.2 --DY

`DM.RFSTDTC` を Day 1 として算出する。当日を1、起算日前は負、0は作らない。

CORE は「`--DTC` があるのに `--DY` が無い」を指摘する。収集日（`--DTC`）と開始日（`--STDTC`）の両方を持つドメインでは、それぞれに対応する `--DY`・`--STDY` が要る。片方だけ作ると残りが指摘される。

日付が空のレコードでは `--DY` も欠測になる。これは正しい。

### 2.3 EPOCH

`VISITNUM` から割り付け、`VISITNUM` を持たないドメイン（AE・CE など）は日付で判定する。CORE は「被験者レベルの観察に EPOCH が無い」を指摘する。

日付判定に使う境界は試験の設計による。移植を伴う試験では、投与記録の最終日（`RFXENDTC`）ではなく、治療終了報告の日付や移植日を境にしたほうが解析と整合することがある。投与記録の最終日は、移植後の維持投与が記録されるかどうかで症例ごとにぶれるため。

`VISITNUM` も日付も持たない随時報告は EPOCH が欠測のまま残る。これは判定材料が無いためで、埋めない。

### 2.4 VISIT

`VISITNUM` に対応する文字ラベル。コード体系は試験ごとに `--SPID` との対応から読み取り、フォーマットとして定義する。

### 2.5 DM の派生変数

- `AGE`・`AGEU` — `BRTHDTC` と `RFSTDTC` から
- `RFXSTDTC`・`RFXENDTC` — EC の投与開始・終了の最小・最大
- `RFPENDTC` — 最終追跡日（DS の追跡終了報告）
- `DTHDTC`・`DTHFL` — DS の死亡レコードから
- `ARMCD`・`ARM`・`ACTARMCD`・`ACTARM` — 受領の `ARM` は空で来る

単群試験では群の割り付けが無いため、`ARMCD`・`ARM` に試験治療の識別子を固定で入れる。試験治療を1回も受けていない症例は `SCRNFAIL`・`Screen Failure` とし、計画群（`ARMCD`・`ARM`）と実際の群（`ACTARMCD`・`ACTARM`）を揃える。揃えないと CORE が4つのルールで指摘する。

SDTM は `ACTARM` が Screen Failure の症例で `RFSTDTC` を空にすると定めるが、Ptosh の `RFSTDTC` は登録日であり ADaM の相対日の起算に使う。空にすると当該症例が日数計算から外れるため、意図的に従わないという判断があり得る。その場合は逸脱として記録する。

### 2.6 --STRESC・--STRESN・--STRESU

Findings クラス（LB・VS・RS・FA・MB・QS・DD など）にだけ作る。Interventions クラス（EC・CM・PR）と Events クラス（AE・CE・DS・MH）には存在しない変数なので作らない。作ると「Model の許可変数リストに無い」と指摘される。

`--STRESC` は原値をトリムして格納し、単位換算はしない。`--STRESN` は数値として解釈できる場合のみ設定する。定量下限未満を表す文字（`ND`・`NQ` など）は `--STRESC` に文字のまま残す。

### 2.7 数値型にすべき変数

受領データは全変数が文字型で来るため、SDTM が数値と定める変数を数値化する。CORE はデータ型を IG と照合する。

- MedDRA のコード（`--LLTCD`・`--PTCD`・`--HLTCD`・`--HLGTCD`・`--BDSYCD`・`--SOCCD`）
- 基準範囲（`--STNRLO`・`--STNRHI`）
- `--SEQ`・`VISITNUM`・`--DY`・`AGE`・用量（`--DOSE`）

### 2.8 変数の並び

SDTM の標準順に並べる。CORE は変数順を IG と照合する。

標準順は CORE の検証結果に含まれる `column_order_from_library` から抽出できる。一度検証を回して抽出し、CSV に保存してプログラムが読む形にすると、以後は自動で揃う。ドメインごとに次の形で持つ。

```
dataset,variable,order
DM,STUDYID,1
DM,DOMAIN,2
...
```

抽出は PowerShell で次のようにする。

```powershell
$j = Get-Content <検証結果>.json -Raw -Encoding UTF8 | ConvertFrom-Json
$rows = @()
foreach ($d in ($j.Issue_Details | Where-Object core_id -eq 'CORE-000852')) {
  $names = [regex]::Matches($d.values[1], "'([^']+)'") | ForEach-Object { $_.Groups[1].Value }
  $i = 0
  foreach ($n in $names) { $i++; $rows += [pscustomobject]@{ dataset=$d.dataset; variable=$n; order=$i } }
}
$rows | Export-Csv <出力先>\sdtm_variable_order.csv -NoTypeInformation -Encoding UTF8
```

出力側では、データセットの全変数を「標準順にあるものはその順、無いものは末尾」で並べ替える。SAS では `retain` に並べた変数名を渡す。標準順に存在する変数だけを列挙すると期待どおりに並ばないため、全変数を対象にする。

### 2.9 変数ラベル

SDTMIG の文言に合わせる。CORE は「ラベルが IG と一致しない」を指摘し、そのメッセージに正しい文言（`library_variable_label`）が入っているので、それを見て直す。

同じ意味の変数でもドメインによって文言が違う。`--DY` は Findings では `Study Day of Visit/Collection/Exam`、Events では `Study Day of Event Collection`、RS では `Study Day of Response Assessment` のように分かれる。推測せず、指摘に出た文言を使う。

### 2.10 --BLFL の既定値を落とす

ベースラインの結果を1枚のシートで集める運用（1）のため、`--BLFL` には既定値の `Y` があらかじめ入っている。検査が行われなかったレコード（`--STAT='NOT DONE'`）にも `Y` が残る。

`--BLFL` は解析でベースラインとして用いる値の識別子であり、シートの所属を表すものではない。値を持たない行のフラグは SDTM 化の段階で落とす。判定は `--STRESC` の欠測で行う。`--STAT='NOT DONE'` の行と、値も理由も空のまま提出された行の両方が対象になる。

落とさないと CDISC CORE が `CORE-000643`（`BLFL is set to "Y", but no value for STRESC is provided`）を立てる。件数はベースラインで未実施の検査の数だけ出るので、実測では483件になった。

提供先が `--BLFL='Y'` でベースライン値を抽出したときに欠測が混ざる実務上のリスクもある。SDTM だけを受け取る側は `--SPID`（シート名）を知らないため `--BLFL` を使う。

処理は全ドメインに適用する。`--BLFL` を持つのは Findings クラスで、対象は `--BLFL` と `--STRESC` の両方を持つドメインに限る。データセットの出力の直前に置くと漏れがない。落とした件数はログに出して、後から追えるようにする。

試験A の実装は `%blfl_clean`（SAS）と `blfl_clean()`（R）で、どちらも出力マクロ・関数の先頭から呼ぶ。実測では LB の483件だけが対象になり、FA（445件）・QS（89件）・VS（178件）の `Y` はすべて値を持っていた。

### 2.11 --PRESP と --OCCUR を CRF の尋ね方に合わせる

`--PRESP='Y'` は CRF に薬剤名や事象名が印字されて答えを求めたことを示し、そのとき `--OCCUR` に `Y`/`N` が入る。自発報告は両方とも空になる。この2通り以外は SDTM として不整合で、CORE が `CORE-000014`・`CORE-000016`・`CORE-000118` で指摘する。

Ptosh の CRF は同じカテゴリの中でも項目の尋ね方が違うことがあり、そのまま変換すると不整合になる。実測した2つのパターン。

数量だけを尋ねる項目。CRF に薬剤名が印字されているので `--PRESP='Y'` は付くが、有無の選択肢が無いため `--OCCUR` が空で来る。数量が0なら発生なしを意味するので、そこから `--OCCUR` を導出する。実測では「G-CSF投与日数」（`CMDUR`、`P0D` が131件）と「血小板輸血投与量 (総単位)」（`CMDOSE`、`0` が196件）の772件が該当した。同じシートの「ラスブリカーゼ投与 あり／なし」は選択肢なので受領値が入っており、上書きしない。

投与量が入った薬剤だけレコードになる項目。CRF に3剤（CyA・FK506・PSL）が印字されて投与量を入力する形で、`--PRESP` が付かずに来る。組み合わせとしては自発報告に見えるので CORE は指摘しないが、事前規定の項目なので `Y` を補い、投与量から `--OCCUR='Y'` を導く。実測では11件。入力の無かった薬剤のレコードが作られないのは Ptosh の機能による。値が入力されなかった項目、すなわち投与や実施が無かった項目はレコードそのものを出力しない設計なので、レコードの不在は「行われなかった」を意味する。したがって `--OCCUR='N'` のレコードを作る根拠は無い。導出するのは `Y` の行だけで、発生なしのレコードを補って行数を揃えようとしない。

尋ね方はシートごとに違うので、CRF（Annotated CRF の PDF）で項目の作りを確かめてから決める。`pdftotext -layout` で読むと項目名と SDTM 変数の対応注記が並んで出るので、どの項目がどの変数に落ちるかが分かる。

導出後の件数はログに出し、`--PRESP='Y'` で `--OCCUR` が空の行が残ったら WARNING を出す。

### 2.12 DSCAT をシートごとに決める

`DSCAT` は DS のレコードを性格で仕分ける変数で、コントロールドタームは3値である。`DISPOSITION EVENT` は被験者がその試験（あるいは治療期・追跡期）をどう終えたかという転帰そのもので、`DSDECOD` には完了・中止理由のコントロールドターム（`COMPLETED`・`ADVERSE EVENT`・`DEATH`・`LOST TO FOLLOW-UP`・`PHYSICIAN DECISION`・`PROTOCOL DEVIATION`・`WITHDRAWAL BY SUBJECT`・`SCREEN FAILURE` など）が入ることが期待される。`PROTOCOL MILESTONE` は転帰ではなく計画書が定めた節目の到達点で、同意取得・ランダム化・登録が該当し、`DSDECOD` には `INFORMED CONSENT OBTAINED`・`RANDOMIZED` といった別のコードリストを使う。`OTHER EVENT` はそのどちらでもないが DS に残しておきたい事象である。

区分が3つに分かれているのは、DS が被験者の進捗を追う唯一のドメインであり、転帰・節目・その他を混ぜると機械的に追えなくなるためである。SDTMIG は1つの試験期（EPOCH）につき転帰レコードは1件という前提に立っており、検証ツールもその前提で重複を検出する。

受領データは DS の全レコードが `DISPOSITION EVENT` で来ることがある。CRF のシートが複数あっても区別されないため、転帰でないシートまで転帰として扱われる。試験A では治療内容の変更報告21件がこれに当たり、中止・完了報告と同じ EPOCH に並んで42件が重複した中止イベントとして検出された。

判断は「そのシートは被験者の転帰を記録するものか」で足りる。

- 転帰であれば `DISPOSITION EVENT` とし、`DSDECOD` が完了・中止理由のコントロールドタームに収まるかを確認する。収まらない試験固有の理由を使う場合は、`DSTERM` に原文を残したうえで `DSDECOD` をどう埋めるかを決めておく
- 同意取得・登録などの節目を DS に持つなら `PROTOCOL MILESTONE`
- 治療内容の変更報告のように、転帰でも節目でもないものは `OTHER EVENT`

`DSTERM` の値からも性格の違いが読み取れる。転帰レコードなら標準用語に収まるはずのものが収まらない、という形で区分の誤りが表に出る。試験固有の中止理由を標準用語へ丸めると中止理由の集計が壊れるので、`DSTERM` と `DSDECOD` は受領値のまま保持し、置き換えるのは `DSCAT` だけにする。

define.xml のコードリストは、実際に使う値をすべて含める。1値しか使わない見込みでも、後から値が増えると検証ツールがコードリスト外の値として指摘する。受領 define.xml が1値しか持たないなら、SDTM 変換で足した値をコードリストにも足す。

解析側が区分に依らず `--SPID` でシートを判別しているなら、この置き換えで解析結果は変わらない。受領データそのものを作り直す必要も無い。

## 3. Ptosh 由来で繰り返し出る問題

試験A で見つかったもののうち、EDC やデータ変換の仕組みに由来し、他試験でも同じ形で出る可能性が高いもの。着手時に確認する。

### 3.1 define.xml の def:Class が小文字

受領 define.xml の `ItemGroupDef/@def:Class` が `events`・`findings`・`special purpose` のような小文字で入っている。Define-XML のコントロールドタームは大文字。CORE は読み込み時に `Unknown value Class in ValueSet` で落ちる。

生成側で大文字化する。

### 3.2 define.xml の def:title が空

`def:leaf/def:title` が空要素になっており、`xlink:href` も空。CORE は空の `def:title` を読めず `Missing required keyword argument _content in title` で落ちる。

生成側でデータセットのファイル名を入れる。

### 3.3 Define-XML 2.0 は CORE が読めない

Ptosh が出すのは Define-XML 2.0.0。CORE 同梱の odmlib は `ItemGroupDef/@def:Class` を属性として扱えず（2.1 では子要素）、2.0 の define.xml を渡すと落ちる。属性を消すと今度は必須項目が無いと言われる。

当面は define.xml を渡さずに検証する。変数のメタデータは Dataset-JSON 側が持つため、実行できなくなるのは define と IG の照合ルールだけ。

### 3.4 受領データにあって define.xml に無いドメイン

試験A では CO（コメント）が受領CSVにあるのに define.xml の `ItemGroupDef` に無かった。define を更新するときに新規作成する。

### 3.5 コメントドメインの自由記述に改行が入る

CO の `COVAL`（重篤な有害事象報告の経過記述など）はフィールド内に改行を含む。`proc import` は引用符内の改行を跨げず、1レコードが複数行に割れる（24レコードが198行になった）。

引用符の数が偶数になるまで行を連結して論理レコードへ復元し、埋め込み改行を空白に置き換えてから `scan` の `q` 修飾子でカンマ区切りを解く。

```sas
data _co_rec;
  length _rec $32767;
  retain _rec '';
  infile "<CO.csv>" lrecl=32767 truncover firstobs=2;
  input;
  _rec = catx(' ', _rec, _infile_);
  if mod(countc(_rec, '"'), 2) = 0 then do;
    output;
    _rec = '';
  end;
  keep _rec;
run;
```

なお `COVAL` は XPT v5 の文字200バイト制限に収まらない。Dataset-JSON を使う理由の1つ。

### 3.6 FA の FATESTCD と FAOBJ が入れ替わる

事象名が `FATESTCD` に入り、`FAOBJ` が `OCCUR` になっているレコードがあった（生着・GVHD・輸血離脱など）。SDTM の意図は逆で、`FATESTCD='OCCUR'`・`FAOBJ='<事象名>'`。

あわせて `FATESTCD` に8文字を超える値（`COMPTBL SEROTYPES` など）が入ることがある。`--TESTCD` は8文字以内なので短縮し、完全名を `FATEST` に残す。

### 3.7 LB の VISITNUM と VISIT の取り違え

一部のシートで `VISITNUM` が空になり、`VISIT` 列に数値コードが入っていた。SDTM では `VISITNUM` が数値、`VISIT` が文字ラベル。統合してから使う。

### 3.8 外部CSVを proc import に任せない

手作りの外部データ（値がクォートされていない CSV）は `proc import` が日付列を数値型に推定する。受領CSVは文字型で来るため、突合すると型不一致でエラーになる。列構成が分かっている外部データは `infile` で型を明示して読む。

### 3.9 eCRF のシート複製に伴う参照漏れ

試験A では、あるシートを複製して別のシートを作った際に参照先のシート名の置換が漏れ、採取日・検体・実施機関・定量下限が別シートの値になっていた。eCRF の構造定義（JSON）を検査すれば機械的に見つかる。

これは1試験で起きた事象だが、原因が eCRF 構築の作業手順にあるため、他試験でも起こりうる。データ固定後に日付の整合を確認する価値がある。

### 3.10 --ADJ は減量と増量の理由を同じ変数に持つ

`EC.ECADJ`（用量調整の理由）には、コース中の減量理由だけでなく、プレフェーズの増量理由のように別の性格の理由も同じ変数に入る。値の水準を治療相ごとに見ると、シートによって使われる水準の集合が分かれていることで判別できる。「減量理由が見当たらない」「増量理由の格納場所が無い」と判断する前に、`--SPID` 別の水準を確認する。

### 3.11 条件付きの報告シートは該当が無ければ1レコードも現れない

提出条件が付いたシート（特定の状況でのみ報告するもの）は、条件を満たす症例が無ければ SDTM のどのドメインにもレコードが現れない。集計項目としては図表案に残るため、「データが欠けている」のか「該当症例が無い」のかを、aCRF の提出条件から判断する必要がある。前者なら照会、後者なら0件として集計する。

### 3.12 MB の --REFID が親事象との紐づけを持つことがある

微生物検査（MB）の起因菌が、どの感染症事象に対応するかを `MBREFID` の接頭辞と番号で表している例がある。接頭辞が事象の種類、続く数字が報告シートの番号（`MBSPID` と一致）という構造で、親ドメイン（FA 等）の該当項目の Grade と突合すれば対応を検証できる。事象別の起因菌の内訳を求められたときは `--REFID` の構造を先に確認する。

### 3.13 同じ変数がシートによって別の意味の値を持つ

`EC.ECDOSE` が、あるシートでは1日投与量、別のシートではコース総投与量として入っていることがある。`ECCAT='TOTAL DOSE PER COURSE'` の有無で区別できる場合もあるが、区別が付かない設計もある。投与量を横断的に集計する前に、シート別に値の桁と単位を確認する。

## 4. 試験ごとに確認が要ること

一般化できないもの。

- VISITNUM のコード体系（何番が何のコースか）。`--SPID` との対応から読む
- ドメイン構成。どのドメインが来るか、EX を使うか EC だけか
- CRF 固有の設計。投与の有無をどの変数で判定するか、前処置と移植が同じドメインに混在するか
- EPOCH の日付判定に使う境界日
- 外部データの有無と受け皿ドメイン

## 5. 試験A に固有だったこと

他試験に持ち込まない。参考として残す。

- LB の `evaluation15` シートの参照フィールド補正（§3.9 の事象への対処）
- 移植の生着不全・再移植の外部データ（CRF に記録欄が無いため外部CSVで補った）
- ABL1 変異解析の外部データ（PI 提供のシートから3項目のみ読む）
- 移植期を表す EPOCH 値 `TRANSPLANT` の導入（移植を伴う試験でのみ必要）

## 6. Dataset-JSON の生成

CORE に渡す形式は Dataset-JSON v1.1。理由は [`sdtm-conformance-validation.md`](sdtm-conformance-validation.md)「データ形式の選択」。

SAS には `proc export` 相当が無いため data step で組み立てる。実装は `<試験ID>_SDTMtoJSON.sas`。要点は3つ。

- ラベルと `itemOID` は define.xml から引く（変数メタデータの正本を1つにする）
- 先頭列に `ITEMGROUPDATASEQ` を置く。CORE が必須とする
- 値は `put ... $varying` で書く。桁送りの指定（`+(-1)`）で書くと JSON が壊れる

生成後に BOM を除去する。SAS の `encoding='utf-8'` は BOM を書き出すが CORE は読めない。

## 7. 指摘の切り分け

CORE の指摘は次の4つに分けると扱いやすい。

1. 実装で直すもの — 派生変数の欠落、型、変数順、ラベル、クラスに合わない変数
2. 受領データ由来 — データセンターへ照会する。解析への影響の有無を添える
3. 形式上のもの — `ITEMGROUPDATASEQ` に関する指摘など。理由を書いて除外する
4. 未作成ドメイン由来 — EX や Trial Design を作らない判断の帰結。SKIPPED も同じ

SKIPPED は合格ではない。作っていないドメインと渡していない外部辞書が主因になるので、その内訳を記録に残す。
