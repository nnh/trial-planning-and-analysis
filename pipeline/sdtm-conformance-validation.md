# SDTM 適合性検証

作成日：2026-08-15
改訂日：2026-08-22

## 目的

作成した SDTM データセットと define.xml を、Claude Code から適合性検証にかけ、指摘を読んで修正まで一連で回すための方法論。特定の試験に紐づかない汎用手順として置く。

導入の実績は複数端末（Windows・Mac）で確認済みで、いずれも CORE の展開と自己診断（`test-validate` の json・xpt）まで通っている。実データでの検証は試験A の SDTM 16ドメインに対して実施済み（430ルール中 SUCCESS 161・SKIPPED 194・ISSUE REPORTED 31・EXECUTION ERROR 6、所要 約60秒）。

## 選定

エンジンは CDISC CORE（cdisc-rules-engine）だけを使う。統計解析責任者の判断で「CORE のみで十分、Pinnacle 21 の併用は不要」と確定したので、Java 8 と P21 Community の導入は行わない。以下の P21 に関する記述は、判断を覆すべき事情（提出先が P21 レポートを名指しで要求する等）が出たときのための材料として残す。

CORE を主にする理由は4つある。

1. インストールを伴わない。Windows・Mac とも実行ファイルが配布されており、zip を展開して置くだけで動く。Python も Java も要らない。管理者権限も要らない。非管理者アカウントの端末でも入る。
2. ルールキャッシュが実行ファイルに同梱されている。CDISC Library API キーを取らなくても、そのまま検証が走る。
3. 出力を JSON で受け取れる。Claude がレポートを直接読んで、指摘の要約・原因の切り分け・修正方針の提示まで行える。P21 の出力は xlsx のみで、読ませるには変換が挟まる。
4. CDISC 本体が公開する Conformance Rules の正本実装で、ルール定義が YAML で読める。指摘が出たときに、その根拠まで遡れる。

P21 Community を副に置く理由。

- CLI は存在するが Java 8 必須で、より新しい Java では動かない。Java 8 を入れる判断が別に要る。
- CLI の実体は GUI アプリに同梱される jar なので、まず GUI アプリのインストールが要る。管理者権限の要否は端末による。
- 出力が xlsx のみ。
- 一方で、FDA/PMDA が用いるバリデータエンジンのバージョン（FDA 1903.1 等）を指定して検証できる。提出直前の確認としては依然として意味がある。実際の提出フローで P21 レポートを求められるなら、CORE で日常的に潰してから P21 で最終確認する二段構えになる。

補足として、CORE と P21 は指摘が完全には一致しない。ルールの実装元が違うため、CORE で通っても P21 で出る指摘、その逆もある。CORE を通したことは P21 で通ることを保証しない。

## CORE の確認済み事実

2026-08-15 に確認。出所は GitHub リポジトリ cdisc-org/cdisc-rules-engine の docs/quick-start.md・docs/cli-reference.md・docs/development.md、GitHub Releases API、PyPI API。

配布とバージョン：

- 最新リリースは v0.16.0（2026-05-01）
- 配布物は core-windows.zip（150MB）、core-mac-apple-silicon.zip（189MB）、core-mac-intel.zip（201MB）、Linux 版2種
- PyPI 版 `cdisc-rules-engine` 0.16.0 もある。requires_python は `>=3.12,<3.13` で、Python 3.12 以外では動かない
- Docker イメージ cdiscdocker/cdisc-rules-engine もある

入出力：

- 入力形式は XPT（SAS Transport v5）、Dataset-JSON v1.1 以上、NDJSON、XLSX、CSV。SAS から出した XPT がそのまま入る
- define.xml はデータセットのフォルダに置いても読まれない。`-dxp` で明示的に渡す
- 出力形式は JSON、XLSX、CSV。`-o` は拡張子なしで指定し、拡張子は形式から自動で付く
- 出力の Rules Report タブに、ルールごとの実行結果が SUCCESS / SKIPPED / ISSUE REPORTED / EXECUTION ERROR で入る

SKIPPED の意味に注意する。対象のカラムやドメインが無い、スキーマ検証が無効、適用範囲外といった理由で実行されなかったことを表す。合格ではない。想定したドメインが SKIPPED になっているなら、データ側かバージョン指定側に取り違えがある。

キャッシュと API キー：

- `update-cache` のうち rules の取得は API キー不要。metadata と Controlled Terminology の取得には CDISC Library API キーが要る
- 接続先は api.library.cdisc.org の 443 番
- リリース同梱のキャッシュはリリース時点のもの。リリース後に公開されたルールは、そのリリースのエンジンが対応していない場合があるため、無理に update-cache せず次のリリースを待つのが公式の推奨

したがって初回は `update-cache` を実行しない。同梱キャッシュで始める。

同梱キャッシュの中身（2026-08-15 に v0.16.0 の Mac Apple Silicon 版で実測。同日、別のWindows端末でも `list-rule-sets` が同じ標準・同じバージョンを返し、リリースが同じなら配布物によらず同じであることを確認した）：

- 標準は adamig 1-0/1-1/1-2/1-3、sdtmig 3-2/3-3/3-4、sendig 3-0/3-1/3-1-1、sendig-ar 1-0、sendig-dart 1-1/1-2、sendig-genetox 1-0、tig 1-0（SDTM・SEND）、usdm 3-0/4-0
- sdtmig 3-4 のルールは 430 件
- Controlled Terminology は sdtmct が 2026-03-27 版まで。adamct・cdashct・sendct・define-xmlct・qrsct 等も入っている
- 展開後の容量は 840MB・2036 ファイル

`list-rule-sets` の出力がこれと大きく違うなら、落とした配布物か展開先を疑う。

コマンド：

- `validate` 適合性検証の実行
- `update-cache` ルール・CT・メタデータの更新、カスタムルール・カスタム標準の登録
- `list-rules` / `list-rule-sets` / `list-ct` キャッシュ内容の確認
- `test-validate` 同梱テストデータでの自己診断

`validate` の主なオプション：

- `-s, --standard` 標準の識別子。SDTMIG なら `sdtmig`、TIG なら `tig`
- `-v, --version` 標準のバージョン。ハイフン区切りで `3-4` のように書く
- `-ss, --substandard` TIG のときのみ必須。`SDTM` / `SEND` / `ADaM` / `CDASH`
- `-d, --data` データセットを置いたフォルダ
- `-dp, --dataset-path` 単一ファイルの指定。複数回指定できる
- `-dxp, --define-xml-path` define.xml のパス
- `-ct, --controlled-terminology-package` CT パッケージ。define.xml 2.1 を渡した場合は define から読まれるので不要
- `-of, --output-format` `JSON` / `XLSX` / `CSV`
- `-o, --output` 出力先（拡張子なし）
- `-mr, --max-report-rows` Excel 出力の Issue Details 行数上限。既定 1000、0 で無制限
- `-me, --max-errors-per-rule` ルールあたりのエラー数上限。`-me 100 False` で全データセット通算、`-me 100 True` でデータセットごと
- `-r, --rules` / `-er, --exclude-rules` CORE ID による対象ルールの限定・除外
- `-lr, --local-rules` ローカルのルール YAML/JSON を使う
- `-ps, --pool-size` 並列プロセス数
- `-p, --progress` 進捗表示。Claude から回すときは `disabled` にする

主要オプションは環境変数でも渡せる（`PRODUCT`・`VERSION`・`SUBSTANDARD`・`DEFINE_XML`・`CT`・`CDISC_LIBRARY_API_KEY` 等）。実行ファイルと同じ場所の `.env` に置ける。

大きなデータ：

- 利用可能メモリの 1/4 を超えるデータセットでは pandas ではなく Dask が使われる。`DATASET_SIZE_THRESHOLD=0` で常時 Dask を強制できる

## 検証に要るファイル

渡す実体は SDTM データセットと define.xml の2つだけでよい。ルール定義とコントロールドターミノロジーは実行ファイルに同梱されており、追加ファイルも API キーも要らない。

- データセット — フォルダごと `-d`、または `-dp` で個別に指定する
- define.xml — `-dxp` で明示的に渡す。データセットと同じフォルダに置いても読まれない

追加が要るのは2つの場合に限られる。

第1に、define.xml が 2.0 のときは CT パッケージを `-ct` で指定する。ファイルを用意するのではなく、キャッシュ内のパッケージ名を選ぶだけである（`list-ct -s sdtmct` で一覧）。2.1 なら define.xml から読まれる。

第2に、外部辞書を参照するルールを回すときはその辞書が要る。実在を確認したオプションは `--meddra`・`--whodrug`・`--unii`・`--medrt`・`--loinc`・`--snomed-edition`／`--snomed-url`／`--snomed-version`。**辞書ファイル自体は同梱されない。** 指定しなければ、その辞書を使うルールは SKIPPED になる。SKIPPED は合格ではないので、辞書を使うルールを回さなかったこと自体は記録に残す。

## Windows の落とし穴

**`--help` を叩かない。** 日本語ロケールの Windows では必ずクラッシュする。ヘルプに含まれる罫線文字 `█` が cp932 で表現できず `UnicodeEncodeError` になる。`PYTHONIOENCODING=utf-8`・`PYTHONUTF8=1`・ファイルへのリダイレクト・`chcp 65001` のいずれも効かない（2026-08-15 に全て試した）。凍結アプリの click がコンソールへ直接書くため、通常のエンコーディング指定が届かない。

検証の実行そのものには影響しない。`version`・`test-validate`・`list-rule-sets`・`validate` はいずれも通る。オプションの有無を知りたいときは、そのオプションを付けて `validate` を叩き、`No such option` が返るかどうかで判定する。

## 実行時の落とし穴

`--help` 以外にも、実データを流して初めて分かったものが5件ある。いずれも回避策がある。2026-08-15 に試験A の SDTM を流して実測した。

**カレントディレクトリを core.exe の場所にする。** CORE は `resources\schema\dataset.schema.json` を相対パスで開く。別のディレクトリから実行すると Dataset-JSON の読み込みが `Your data file could not be read` で失敗し、原因がデータ側に見える。フルパスで `core.exe` を呼ぶだけでは足りない。

**Dataset-JSON の `ITEMGROUPDATASEQ` は必須。** レコード識別子の列で、Dataset-JSON の仕様上は任意だが、外すと読み込みに失敗する。CORE はこれをSDTMの変数としても扱うため、変数名8文字超・Model の許可変数リスト外・変数順の乱れとして指摘が出る。これは形式上のもので、実データの欠陥ではない。

**SAS から出す JSON は BOM を落とす。** SAS の `file ... encoding='utf-8'` はBOMを書き出すが、CORE のJSONパーサはBOM付きを読めない。生成後に先頭3バイトを除く処理を挟む。

**CSV 入力にはメタデータファイルが要る。** フォルダに `_datasets.csv`（Filename・Label）が無いと `There is no _datasets.csv file in provided path.` で止まる。さらに変数の型・長さ・ラベルは `_variables.csv` で渡す必要があり、渡さないと変数メタデータを見るルール13本が EXECUTION ERROR になる。required/expected 変数の欠落を見るルールもここに含まれるため、CSV は実質的に使えない。

**Define-XML 2.0 は読めない。** CORE 同梱の odmlib は `ItemGroupDef/@def:Class` を属性として扱えず（Define-XML 2.1 では子要素）、`Unknown value Class in ValueSet` で落ちる。属性を消すと今度は `Missing required keyword argument Class in ItemGroupDef` になる。2.0 の define.xml を持っている試験では、define.xml を渡さずに検証することになる。渡せないことで実行できないのは define と IG の照合ルールだけで、変数メタデータは Dataset-JSON 側が持つ。

落ちる原因は1つではない。2026-08-16 に別の端末で試験A の define.xml を1つずつ直して確かめたところ、3段階で別の例外が出た。`def:Class="FINDINGS ABOUT"` を `FINDINGS` に書き換えると `Missing required keyword argument _content in TranslatedText` になり（中身が空の `TranslatedText` が 455 件中 72 件）、それを埋めると `SASFieldName has an invalid sasName of COMPTBL SEROTYPES` になる（空白を含む値が4件。いずれも FA の値水準メタデータ）。**個別に潰しても次が出るので、2.0 のまま通そうとする試みは打ち切ってよい。** なお `FINDINGS ABOUT` は Define-XML 2.1 で追加された値で、2.0 の許容値には無い。**この3件は CORE を通す通さないに関わらず define.xml 側の不備**なので、生成元（試験の SDTM 生成プログラム）を直す判断は試験側で要る。

## データ形式の選択

CORE は XPT・Dataset-JSON・NDJSON・XLSX・CSV を受け付けるが、実際に使えるのは Dataset-JSON である。

**XPT（SAS Transport v5）は制限が強すぎる。** 文字変数200バイト・変数名8文字・ラベル40文字の上限があり、コメントドメインの `COVAL`（自由記述）が入らない。SDTM は超過分を `COVAL1`〜`COVALn` に分けると定めるが、日本語の記述ではバイト境界の処理が要る。SAS の `libname xport` は `outencoding` を実装していないため、日本語を含むデータのエンコーディングも制御できない。

**CSV はメタデータを二重に持つことになる。** 上記のとおり `_variables.csv` に型・長さ・ラベルを書き写す必要があり、SASデータセットの実体と別に持つ状態になる。ズレの検証という将来の作業が生まれる。

**Dataset-JSON はデータとメタデータが1ファイルに収まる。** 型の表現も細かく（string / integer / decimal / float / double / boolean）、`keySequence`（キー変数）やデータセットラベルも持てる。CDISC の正式な交換標準で、XPT の後継として規制当局が受け入れを進めている。SAS からの生成は `proc export` 相当が無いため data step で組み立てることになるが（100行程度）、実装は一度きりで、二重管理は残らない。

参考として試験A（16ドメイン・約27000レコード）での実測サイズは XPT 18.5MB、CSV 4.2MB、Dataset-JSON 6.1MB。

## 実データでの実績

試験A（16ドメイン・約27000レコード・被験者90例）を SDTMIG 3.2 で検証した結果。

- 430ルールに対し SUCCESS 161・SKIPPED 194・ISSUE REPORTED 31・EXECUTION ERROR 6
- 所要時間は約60秒（Windows）。別のMac端末（Apple Silicon）で再現したときは32秒で、ルールの内訳・指摘件数とも完全に一致した（OS とデータの入手経路が変わっても結果は同じ）
- 指摘は31ルール・約19000件だが、件数の大半は1ルールに集中する。ルール単位で読めば人手で捌ける
- 偽陽性は FA の1ルール（`FAOBJ` と親ドメインの用語の一致を求めるもの）に集中した。試験の設計上 FA が独立している場合に出る
- 実装の欠陥を実際に検出した。相対日の欠落、MedDRAコードと基準値の型、Interventions クラスに Findings の標準化結果変数を作っていたこと、Arm 変数の不整合、変数順、ラベルの文言
- 受領データ側の問題も検出した。同意日が試験治療開始日より後（61例）、`--STAT='NOT DONE'` に理由が無い、`--TEST` が40文字超など
- SKIPPED 194 の主因は作っていないドメイン（Trial Design・SV・SE・EX・SUPP）と、渡していない外部辞書

実務で使えるという結論。指摘の量・偽陽性の少なさ・実行時間のいずれも許容範囲で、[「Claude から回す運用」](#claude-から回す運用)の段階2（整形のスクリプト化）へ進める。段階2の実装例は試験リポジトリの `scripts/run-sdtm-validation.ps1`。

## P21 Community の確認済み事実

出所は Pinnacle 21 ヘルプセンター（現 help.pinnacle21.certara.net）。Pinnacle 21 は Certara の傘下に入り、ドメインが移行している。

- CLI の実体は `p21-client-1.0.0.jar`。GUI アプリに同梱される
- Windows でのパスは `C:\Users\<ユーザー名>\AppData\Local\Programs\Pinnacle 21 Community\resources\app.asar.unpacked\components\lib`
- Mac でのパスは `/Applications/Pinnacle 21 Community/Contents/Resources/app.asar.unpacked/components/lib`
- Java 8 が必須。より新しい Java は非対応
- 書式は `java -jar p21-client-1.0.0.jar` に `--engine.version`・`--standard`・`--standard.version`・`--source.sdtm`・`--source.define`・`--report`・`--cdisc.ct.sdtm.version`・`--meddra.version` 等を渡す
- レポートは xlsx で出力される
- Community の最新は 4.2.0 だが Windows のみ。Mac 版は 4.1.0 が最新（2026-08-15 時点）
- jar と configs フォルダを別の場所へコピーしても動く

Windows 端末のほうが P21 は導入しやすい。Mac は 4.1.0 止まりのことがある。

導入する場合、既定の Java を 8 に落とすと他の用途に影響するため、Java 8 は個別に置いて jar を実行するときだけ `JAVA_HOME` を切り替える。

## 企業ネットワークでの制約

企業ネットワークに TLS インスペクション（プロキシによる通信内容の検査）が入っている環境では、CORE の実行に影響し得る箇所が2つある。

1. GitHub Releases からの実行ファイルのダウンロード（150〜200MB）。`Invoke-WebRequest` や `curl` が証明書検証で落ちる可能性がある。落ちたらブラウザで直接ダウンロードして展開する。ブラウザは OS の証明書ストアを使うので通ることが多い。
2. `update-cache` の api.library.cdisc.org への接続。CORE のドキュメント自体が「SSL certificate verification errors が出たら企業の CA バンドルを入手するか、このホスト名の許可を IT に依頼せよ」と書いている。

2 については、そもそも初回は `update-cache` を実行しない設計にしてあるので当面問題にならない。同梱キャッシュで検証が回る。これは CORE を選ぶ理由の1つでもある。

管理者権限については、CORE は zip を展開して置くだけなのでインストール操作が無く、非管理者アカウントでも入る。P21 は GUI アプリのインストールが要るので、そこで詰まる可能性がある。

## 検証の実行

SDTMIG 3.4 の例。標準とバージョン、パスは対象データに合わせる。

Windows（PowerShell）：

```powershell
cd $env:USERPROFILE\opt\cdisc-core\core
.\core.exe validate `
  -s sdtmig -v 3-4 `
  -d "$env:USERPROFILE\Box\Stat\Trials\<試験>\<SDTM のフォルダ>" `
  -dxp "$env:USERPROFILE\Box\Stat\Trials\<試験>\<define.xml のパス>" `
  -of JSON `
  -o "$env:USERPROFILE\Box\Stat\Trials\<試験>\log\20260815-validation" `
  -p disabled
```

Mac：

```bash
cd ~/opt/cdisc-core/core
./core validate \
  -s sdtmig -v 3-4 \
  -d ~/Box/Stat/Trials/<試験>/<SDTM のフォルダ> \
  -dxp ~/Box/Stat/Trials/<試験>/<define.xml のパス> \
  -of JSON \
  -o ~/Box/Stat/Trials/<試験>/log/20260815-validation \
  -p disabled
```

出力は `20260815-validation.json` になる。人が目視する版が要るときは `-of XLSX` で同じコマンドをもう一度回す。

端末固有の絶対パスは文書やプロンプトに書かず、Windows は `$env:USERPROFILE`、Mac は `$HOME` から書く。Box のマウントは永続しないので、実行前に Box のフォルダが存在することを確認する。

### Box Drive が無い端末

Box Drive の配布 pkg は `rootVolumeOnly="true"` で、インストールに管理者権限が要る。組織の管理者権限で `open Box.pkg` を実行し、GUI インストーラで入れる。

それでも Box Drive を使えない場面——組織のポリシーで入れられない、一時的に落ちている、その端末に入れる必要がない——では、Box CLI で作業領域へ落として検証し、レポートを Box へ戻す。

```bash
box folders:items <親フォルダID> --fields=type,name,id --csv   # フォルダIDを辿る
box folders:download <SDTM フォルダのID> --destination "$WORK"
cd ~/opt/cdisc-core/core
./core validate -s sdtmig -v 3-2 -d "$WORK/json" -ct sdtmct-<版> -of JSON -o "$WORK/<YYYYMMDD>-validation" -p disabled
box files:upload "$WORK/<YYYYMMDD>-validation.json" --parent-id <log フォルダのID>
```

守ること。`$WORK` はリポジトリの外に置く（被験者の個票データがローカルに降りるため）。**検証が終わったら消す**——Box Drive のキャッシュと違い、これは明示的に消さない限り残り続ける。レポートの置き場は Box のままで変わらない。

この経路の所要時間は試験A（16ドメイン・約27000レコード）で、ダウンロードを含めて1分程度。検証そのものは32秒だった。

CT の扱い：define.xml が 2.1 なら CT は define から読まれる。2.0 なら `-ct` でパッケージを明示する。利用できるパッケージは `list-ct -s sdtmct` で確認する。

キャッシュに入っている標準とバージョンは `list-rule-sets` で確認する。

## レポートの置き場

検証レポートは被験者の個票データを含み得る。Issue Details には違反したレコードの値がそのまま入るため、USUBJID や日付、検査値が載る。

したがって置き場は Box（IPD を含むもの）。git には入れない。判断の正本は組織内のデータ層に関する方針が持つ。

Claude に読ませること自体は、機密性1と仮名加工被験者データの範囲であれば問題ない。読ませてよいことと git へ出してよいことは別で、歯止めは置き場の構造が担う。

検証対象のデータセットと define.xml も同じ理由で Box に置いたまま検証する。リポジトリへコピーしない。

## Claude から回す運用

段階を踏む。最初からスキル化しない。

段階1。Claude に validate を実行させ、JSON レポートを読ませて、ルール単位に集約した指摘と修正方針を日本語で返させる。ここで実際の指摘の量と質を見る。

段階2。指摘が多いと JSON をそのまま読ませるのはコンテキストを圧迫する。ルール ID・重大度・件数・代表例に落としてから読ませる。この整形の形が決まったらスクリプト化する。

段階3。手順が固まったらスキル化する。スキルが備えるべきもの。

- 入力はデータセットのフォルダ、define.xml のパス、標準とバージョン
- 実行・出力・整形・日本語での指摘要約・修正案の提示までを一続きで行う
- SKIPPED になったルールを合格として扱わず、実行されなかった理由を併せて示す
- 出力を日付付きで残し、前回との差分（新しく出た指摘、解消した指摘）を出す

配置先は、CDISC 固有のツールとして組織内に置くか、他プロジェクトからも呼ぶ場面が出て汎用化できたら共通のツールキットへ移す。判断は実際に呼ぶ場面が2つ以上出てから行う。

## 未確定事項

- 検証対象の SDTM データセットと define.xml の所在。試験ごとに Box のどのフォルダにあるか
- データ形式が XPT か Dataset-JSON か
- SDTMIG のバージョン（3-3 か 3-4 か、TIG か）
- define.xml のバージョン（2.0 か 2.1 か）。CT の指定方法が変わる
- MedDRA・WHODrug の辞書を使う検証まで必要か。必要なら辞書ファイルの入手経路
- 提出先が P21 レポートを要求するか。要求されるなら Java 8 と P21 Community の導入まで進める
- 既に業務で P21 を使っている工程があるか。あるなら、その config をそのまま CLI 化できる
