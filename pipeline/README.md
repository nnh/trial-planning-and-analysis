# 解析パイプライン

作成日：2026-08-22
改訂日：2026-09-13

データロック後に「固定データ → SDTM → ADaM → ARD → 図表 → 納品物」までを回すための汎用フローと、その各段階を支える調査資料。

- [analysis-pipeline-plan.md](analysis-pipeline-plan.md) — 全体のフローチャート、6つの層、設計の原則、人の介入ポイント。ここが正本
- [ptosh-sdtm-preparation.md](ptosh-sdtm-preparation.md) — Ptosh から受領した、SDTM のドメイン名・変数名は使うが派生変数を持たない CSV を、CDISC CORE で検証できる状態にするまでの手順
- [sdtm-conformance-validation.md](sdtm-conformance-validation.md) — CDISC CORE（cdisc-rules-engine）の導入・実行・実行時の落とし穴
- [cdisc-ars.md](cdisc-ars.md) — CDISC ARS（Analysis Results Standard）と ARD の調査。二重コーディングの突合を ARD レベルで行う根拠

雛形の CSV は [../templates/](../templates/README.md)。層をまたぐ実行・生成・検査は下の [scripts/](#scripts)、CDISC の標準そのものを相手にする検査は [../skills/](../skills/README.md) の該当スキルが持つ。解析の段階で見つかった欠陥の型は [../findings/analysis-findings-log.md](../findings/analysis-findings-log.md)。

## scripts/

層をまたぐ実行・生成・検査のスクリプト本体。試験リポジトリへそのままコピーして使う。Python は `scripts/`、SAS のマクロは `program/sas/macro/`、R は共通基盤を `program/r/`、`build-define-html.R` だけを `scripts/` へ置く。

下に書くのは「どれが何をするか」までで、中身は各ファイルの先頭のコメントが持つ。段階の順序・停止条件・引数はスクリプトが正本なので、ここへ写さない。

### 実行の入口

- `python/run-release.py` — 固定データの検証から納品パッケージまで、区間2の全段を一続きで回し、どこかで検査が落ちたらそこで止める。飛ばした段は通ったものとして数えない
- `python/run-all-sas.py` — SAS 系の本流を受領CSVから図表まで回す
- `python/run-adam-json.py` — ADaM の Dataset-JSON の後処理
- `python/run-adam-validation.py` — ADaM の宣言の照合と define 一式の作り直し
- `python/run-sdtm-validation.py` — SDTM の宣言の照合、define.xml の更新、CDISC CORE による適合性検証
- `python/runcommon.py` — 上が共通で使う起動の作法。SAS のバッチ起動と成否の判定、試験フォルダの解決、Rscript の在処、画面の符号化

### 生成

- `python/boxpath.py` — 試験の設定の読み出しと Box のパス解決。試験IDと試験フォルダを引く口をここだけが持つ
- `python/update-define-xml.py` — 受領 define.xml に SDTM 層で足した変数とドメインを反映する
- `python/build-adam-define.py` — ADaM の define.xml を変数マップと Dataset-JSON から新規生成する。生成の本体は [skills/cdisc-define-xml/](../skills/cdisc-define-xml/SKILL.md) が持ち、ここは材料の在処と試験の情報を渡す配線だけ
- `r/build-define-html.R` — define.xml を CDISC 標準の XSL で表示用の HTML へ変換する。XSLT の変換器は Python の標準ライブラリに無いので R が持つ
- `python/build-ars-json.py` — ARS の ReportingEvent
- `python/build-spec-html.py` — 仕様書 HTML
- `python/build-traceability.py` と `python/traceability_template.html` — トレーサビリティ索引の組み立てと画面
- `python/build-crf-field-map.py` — 症例報告書の項目と SDTM 変数の対応
- `python/build-pi-package.py` — 納品パッケージ。組み立ての途中で `build-flow-diagram.py`（登録から解析対象集団までの症例の流れ図）と `build-reviewers-guide.py`（解析データの案内・受領データの案内・総括報告書の逸脱の原稿）を呼び、パッケージの中には索引と ARS を作り直す包み（`rebuild-traceability.py`・`rebuild-ars.py`）を同梱する
- `python/init-variable-map.py` — 変数マップの初回版
- `python/read_xlsx.py` — 受領資料の xlsx の読み取り（回帰確認は `read_xlsx_test.py`）
- `python/trim-old-versions.py` — 旧版と実行ログの世代の片付け

### 検査

- `python/check-environment.py` — この端末で何が回せるか（処理系・SAS・CDISC CORE・スキル・枠組みの置き場）。試験のリポジトリが無くても動く。立ち上げの最初に回す
- `python/check-decisions.py` — 決定の正本が1つに保たれているか、判断票（区分が未決の行）が状態を持つか（[analysis-pipeline-plan.md](analysis-pipeline-plan.md)「検査で守る」）。`--gate` は未決が残っていれば落とす
- `python/check-review-ledger.py` — 独立レビューの台帳で、状態欄と各項の記録が食い違っていないか
- `python/check-ars-tlf.py` — ReportingEvent と、実際に配る図表・ARD が同じものを指しているか
- `python/check-tlf-index.py` — 図表の宣言
- `python/check-variable-map.py` — 変数マップと実データ
- `python/check-sdtm-declarations.py` — SDTM の宣言（値水準と CodeList）と実データ
- `python/check-datatype-rule.py` — 交換形式の型宣言の規則が R・SAS・Python の3実装で揃っているか
- `python/check-identifier-length.py` — 宣言済みの識別子が SAS 系の ARD の格納長に収まるか
- `python/check-ars-json.py` — ReportingEvent を ARS の標準スキーマで検証する
- `python/compare-ars-json.py` — 両系統の ReportingEvent の突合
- `python/check-crf-field-map.py` — 症例報告書の項目と SDTM 変数の対応
- `python/check-traceability.py` — 索引をブラウザで開いて、リンクと JS の例外を見る
- `python/check-visual-regression.py` — 図表を実際に描画して、前回合意した見た目と突き合わせる
- `python/check-pi-package.py` — 納品パッケージ

### 層の部品

- `sas/` — 表示型マクロ（`tlf_ops.sas`）・ARD 生成マクロ（`ard_ops.sas`）・受領データ読み込み（`load_rawdata.sas`）・ソースのタイムスタンプ記録（`srcstamp.sas`）。`export-sdtm-metadata.sas` は現行の経路では使わない。define.xml の生成を実装系統から切り離した時点で、生成が読むものが受領 define.xml と `docs/metadata/` の宣言だけになったためで、試験側では既に落としてある
- `r/` — R 系の共通基盤。パス解決・Dataset-JSON の読み書き・SDTM 標準ラベルの辞書・ログ・突合の道具（`ap_common.R`）、図表の Excel 出力（`ap_xlsx.R`）、図表の表示型と描画（`tlf_ops.R`。試験にしかない表示型は試験側の `tlf_ops_trial.R`）。接頭辞 `ap_` は試験に依存しない。試験名を関数名に入れると、その R 一式はその試験の外へ出せなくなる

いずれも試験固有の値は `docs/metadata/trial.json`（形は [../templates/trial.json](../templates/trial.json)）だけから引く。

### 試験ごとに書き換えるもの

汎用層が持つのは置き場と形までで、中身が疾患や研究計画書で変わるものは試験側が書く。次のものは試験A の値を見本として残してある。新しい試験ではそのまま使わず、自分の一次文書から起こし直す。

- ADaM の論理検証。何を検算するか（生存時間の検算表との全例突合、疾患固有の判定規則、症例報告書の入力規則が成り立つか）は疾患で変わるので、SAS 側の QC プログラムが試験ごとに持つ。汎用層が持つのは、その段を ADaM の後・ARD より前に置くことと、停止条件の印の形（`WARNING: [QCnn] 停止条件`）だけで、いずれも `run-all-sas.py` が持つ
- `update-define-xml.py` の導出方法の説明。def:Origin に添える文言は導出仕様そのものなので移せない
- `build-spec-html.py` の変換対象の一覧。どの仕様を納品物へ入れるかは、外部データで何を補ったか・どの導出に独立した仕様書を立てたかで変わる
- `run-all-sas.py` の QC の並び。番号と名前ごと差し替える
- `build-reviewers-guide.py` の本文。節立て（PHUSE の様式）は汎用だが、時間イベントのパラメータ名や正本として指す仕様書の名前は試験固有

受領CSVから SDTM・ADaM・ARD・図表を作る本体と、疾患固有のエンドポイントの計算も試験側にある。複数試験を通して共通部分が見えてくるまで公開対象に含めない。この抽出は将来の課題として残す。

### 実行できる形

実行できる形で置くのは Python と R に限る。納品先の研究者が別の系統の端末を使うことは多く、納品パッケージを受け取った側が完全に再現できる状態にするには、実行できる形をその2つに限る必要がある。処理系を1つ足すたびに、それが入っていない端末では回せないだけでなく、コードを読むこともできない経路が生まれる。理由と、どちらへ寄せるかの決め方は [analysis-pipeline-plan.md](analysis-pipeline-plan.md)「実行できる形を Python と R に限る」が持つ。

処理系を移すときに、移植の前後で振る舞いが変わっていないことをどう確かめるかは同[「別の処理系へ移すときの確かめ方」](analysis-pipeline-plan.md)が持つ。入口の処理系がここへ至るまでの経緯は [../history.md](../history.md) が持つ。

Python は生成と実行の経路を標準ライブラリだけで動かす。外部パッケージが要るのは検査の3本で、`check-ars-json.py` の JSON-Schema による検証に `jsonschema`、`check-traceability.py` のページの取得と `check-visual-regression.py` の描画に `playwright` が要る。いずれも関数の中で読み込み、入っていない環境では合否と区別できる終了コードで「検証できなかった」と返し、黙って通さない。飛ばす口（`--allow-skip`）は付けてよいが、既定は落ちる側にする。この境目を処理系の選択で崩さない。標準ライブラリで足りない処理を Python へ足すと、外部パッケージが要る場所が検査から生成の側へ移る。受領資料の xlsx を読むために openpyxl のような外部パッケージを足さない。対象の端末は Windows と macOS にまたがり、企業ネットワークの制約で pip が通らないものがあるため、依存を1つ足すたびに「入っている端末と入っていない端末」が生まれる。xlsx は ZIP と XML なので、読むだけなら標準ライブラリで足りる（`read_xlsx.py`）。図表の xlsx を書き出すのは R 側（`{openxlsx2}`・`{mschart}`）が持つので、Python 側は読み取りに限る。
