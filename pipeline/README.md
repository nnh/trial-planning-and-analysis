# 解析パイプライン

作成日：2026-08-22
改訂日：2026-08-22

データロック後に「固定データ → SDTM → ADaM → ARD → 図表 → 納品物」までを回すための汎用フローと、その各段階を支える調査資料。

- [analysis-pipeline-plan.md](analysis-pipeline-plan.md) — 全体のフローチャート、6つの層、設計の4原則、人の介入ポイント。ここが正本
- [ptosh-sdtm-preparation.md](ptosh-sdtm-preparation.md) — Ptosh から受領した SDTM 風 CSV を CDISC CORE で検証できる状態にするまでの手順
- [sdtm-conformance-validation.md](sdtm-conformance-validation.md) — CDISC CORE（cdisc-rules-engine）の導入・実行・実行時の落とし穴
- [cdisc-ars.md](cdisc-ars.md) — CDISC ARS（Analysis Results Standard）と ARD の調査。二重コーディングの突合を ARD レベルで行う根拠

雛形の CSV は [../templates/](../templates/README.md)、機械検査は [../skills/](../skills/README.md) に置く該当スキルが持つ。解析の段階で見つかった欠陥の型は [../findings/analysis-findings-log.md](../findings/analysis-findings-log.md)。
