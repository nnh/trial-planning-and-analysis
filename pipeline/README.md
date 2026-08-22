# 解析パイプライン

作成日：2026-08-22
改訂日：2026-08-22

データロック後に「固定データ → SDTM → ADaM → ARD → 図表 → 納品物」までを回すための汎用フローと、その各段階を支える調査資料。

- [analysis-pipeline-plan.md](analysis-pipeline-plan.md) — 全体のフローチャート、6つの層、設計の4原則、人の介入ポイント。ここが正本
- [ptosh-sdtm-preparation.md](ptosh-sdtm-preparation.md) — Ptosh から受領した SDTM 風 CSV を CDISC CORE で検証できる状態にするまでの手順
- [sdtm-conformance-validation.md](sdtm-conformance-validation.md) — CDISC CORE（cdisc-rules-engine）の導入・実行・実行時の落とし穴
- [cdisc-ars.md](cdisc-ars.md) — CDISC ARS（Analysis Results Standard）と ARD の調査。二重コーディングの突合を ARD レベルで行う根拠

雛形の CSV は [../templates/](../templates/README.md)、機械検査は [../skills/](../skills/README.md) に置く該当スキルが持つ。解析の段階で見つかった欠陥の型は [../findings/analysis-findings-log.md](../findings/analysis-findings-log.md)。

## scripts/

層をまたぐ生成・検査スクリプト本体。試験リポジトリの `program/macro/`・`scripts/` へそのままコピーして使う。

- `scripts/sas/` — 表示型マクロ（`tlf_ops.sas`）・ARD 生成マクロ（`ard_ops.sas`）・受領データ読み込み（`load_rawdata.sas`）・ソースのタイムスタンプ記録（`srcstamp.sas`）・SDTM 変数メタデータの書き出し（`export-sdtm-metadata.sas`）
- `scripts/python/` — 追跡索引・仕様書 HTML・PI パッケージの生成と検査、変数マップ・CRF フィールドマップの生成と検査、Box パス解決（`boxpath.py`）
- `scripts/powershell/` — SAS バッチ実行の共通処理（`sas-common.ps1`）、12段階を一続きで回す実行（`run-all-sas.ps1`）、Dataset-JSON 生成、SDTM 適合性検証、define.xml 更新の一連の実行

いずれも試験固有の値は `docs/trial.json`（[../templates/trial.json](../templates/trial.json)）だけから引く。試験ごとに変わる値（受領データのフォルダ名、QC プログラムの段階名など）はコード中にコメントで明示してある。

試験固有の実装（受領CSVからSDTM・ADaM・ARD・図表を作る本体、疾患固有のエンドポイント計算ロジック）は、複数試験を通して共通部分が見えてくるまで公開対象に含めない。この抽出は将来の課題として残す。
