# 解析パイプライン

作成日：2026-08-22
改訂日：2026-08-22

データロック後に「固定データ → SDTM → ADaM → ARD → 図表 → 納品物」までを回すための汎用フローと、その各段階を支える調査資料。

- [analysis-pipeline-plan.md](analysis-pipeline-plan.md) — 全体のフローチャート、6つの層、設計の4原則、人の介入ポイント。ここが正本
- [ptosh-sdtm-preparation.md](ptosh-sdtm-preparation.md) — Ptosh から受領した、SDTM のドメイン名・変数名は使うが派生変数を持たない CSV を、CDISC CORE で検証できる状態にするまでの手順
- [sdtm-conformance-validation.md](sdtm-conformance-validation.md) — CDISC CORE（cdisc-rules-engine）の導入・実行・実行時の落とし穴
- [cdisc-ars.md](cdisc-ars.md) — CDISC ARS（Analysis Results Standard）と ARD の調査。二重コーディングの突合を ARD レベルで行う根拠

雛形の CSV は [../templates/](../templates/README.md)、機械検査は [../skills/](../skills/README.md) に置く該当スキルが持つ。解析の段階で見つかった欠陥の型は [../findings/analysis-findings-log.md](../findings/analysis-findings-log.md)。

## scripts/

層をまたぐ生成・検査スクリプト本体。試験リポジトリの `program/macro/`・`scripts/` へそのままコピーして使う。

- `scripts/sas/` — 表示型マクロ（`tlf_ops.sas`）・ARD 生成マクロ（`ard_ops.sas`）・受領データ読み込み（`load_rawdata.sas`）・ソースのタイムスタンプ記録（`srcstamp.sas`）・SDTM 変数メタデータの書き出し（`export-sdtm-metadata.sas`）
- `scripts/python/` — トレーサビリティ索引・仕様書 HTML・PI パッケージの生成と検査、変数マップ・CRF フィールドマップの生成と検査、ARS の ReportingEvent の生成（`build-ars-json.py`）・系統間の突合（`compare-ars-json.py`）・標準のスキーマによる検証（`check-ars-json.py`）、Box パス解決（`boxpath.py`）、xlsx の読み取り（`read_xlsx.py`、回帰確認は `read_xlsx_test.py`）
- `scripts/powershell/` — SAS バッチ実行の共通処理（`sas-common.ps1`）、12段階を一続きで回す実行（`run-all-sas.ps1`）、ADaM の Dataset-JSON 後処理、SDTM の define.xml 更新・Dataset-JSON 生成・適合性検証の一連の実行。ADaM 側の define.xml の生成は [skills/cdisc-define-xml/](../skills/cdisc-define-xml/SKILL.md) が別に持つ（受領 define.xml を更新するのではなく、変数マップと Dataset-JSON から新規生成する別の作り）

Python は標準ライブラリだけで動かす。例外は `check-ars-json.py` の1本だけで、JSON-Schema による検証に `jsonschema` が要る。入っていない環境では合否と区別できる終了コードで「検証できなかった」と返し、黙って通さない。受領資料の xlsx を読むために openpyxl のような外部パッケージを足さない。対象の端末は Windows と macOS にまたがり、企業ネットワークの制約で pip が通らないものがあるため、依存を1つ足すたびに「入っている端末と入っていない端末」が生まれる。xlsx は ZIP と XML なので、読むだけなら標準ライブラリで足りる（`read_xlsx.py`）。図表の xlsx を書き出すのは R 側（`{openxlsx2}`・`{mschart}`）が持つので、Python 側は読み取りに限る。

いずれも試験固有の値は `docs/trial.json`（[../templates/trial.json](../templates/trial.json)）だけから引く。試験ごとに変わる値（受領データのフォルダ名、QC プログラムの段階名など）はコード中にコメントで明示してある。

試験固有の実装（受領CSVからSDTM・ADaM・ARD・図表を作る本体、疾患固有のエンドポイント計算ロジック）は、複数試験を通して共通部分が見えてくるまで公開対象に含めない。この抽出は将来の課題として残す。
