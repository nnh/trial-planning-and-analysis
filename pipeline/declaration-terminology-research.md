# 「宣言」という用語の検討

作成日：2026-08-22
改訂日：2026-08-22

`analysis-pipeline-plan.md`「図表を宣言で駆動する」で使う「宣言」という用語が、生物統計家にとって馴染みにくいのではないかという指摘を受け、代替語の有無を調査した。

## 対象の概念

1つの図表について「どの表示型で、どの解析の結果値を、どの並びで描くか」を1行にまとめた CSV（`docs/tlf-index.csv`）の行を指す。プログラミングの「宣言的（declarative）」という考え方（手続きを書かず、結果だけを書く）から名付けている。

## 調査した範囲

- CDISC ARS（Analysis Results Standard）標準の用語
- PHUSE・pharmaverse（R の `{cards}`/`{gtsummary}` コミュニティ）を含む英語圏の実務用語
- 日本語の生物統計・臨床試験統計解析の実務で使われる用語
- 「宣言」「宣言的」という言葉が日本語の IT・データ分析の文脈でどう受け止められているか

## 分かったこと

### CDISC ARS 標準

この概念に相当する単一のクラスは無い。`Analysis`（解析単位）・`Output`／`OutputDisplay`（結果の報告・表示単位）・`ReportingEvent`（報告要件全体）という複数クラスの組み合わせで表現される。ARS は「解析メタデータの層」を規定する標準であり、CSV 1行という物理的な実装単位までは規定していない。

### 英語圏の実務

最も普及している言葉は "table shell" / "mock shell" である。ただしこれは統計解析計画書の段階で作る「値の無いレイアウト雛形」を指す言葉で、本枠組みでは既に別の層（`review/planning-review/checklist-tlf-shells.md` の「シェル」）に割り当てている。CSV 1行という機械可読な最小単位を指す確立した用語は見当たらず、"output specification" 程度の言い回しが使われる。

### 日本語の生物統計実務

「解析仕様書」という言葉は、統計解析計画書・図表レイアウト・解析用データセット仕様書と並ぶ文書種別として実際に使われている。「表示定義」「出力仕様」に相当する実例は今回の調査では確認できなかった。

### 「宣言」という言葉自体

Infrastructure as Code（Terraform 等）の文脈で IT 業界では確立した用語だが、これは一般的な IT エンジニア向けの説明であり、生物統計家コミュニティでの使用例は見当たらなかった。

## 結論

CSV 1行という機械可読な最小単位を指す、こなれた日本語の生物統計用語は見つからなかった。最も近いのは「解析仕様」（実務で使われる「解析仕様書」の単位）だが、これも文書レベルの「仕様書」を想起させ、CSV 1行という粒度感は伝わりにくい。決定的に良い置換先が無いという調査結果を踏まえ、「宣言」という語は残し、`analysis-pipeline-plan.md` の初出箇所で「宣言とは何か（表示型・解析ID・並びを1行にまとめた CSV の行）」を先に明示する方針にした。

## ソース

- [Class: Output - Analysis Results Standard (ARS)](https://cdisc-org.github.io/analysis-results-standard/Output/)
- [Analysis Results Standard | CDISC](https://www.cdisc.org/standards/foundational/analysis-results-standard)
- [Creating Table Shells Consistently and Efficiently](https://www.lexjansen.com/pharmasug/2023/MM/PharmaSUG-2023-MM-118.pdf)
- [Lean TLF Mock Shells: A Programmer's Boon](https://www.acldigital.com/blogs/lean-tlf-mock-shells-programmers-boon)
- [SAP and TLF Shells – Being a Clinical Biostatistician](https://beingabiostatistician.wordpress.com/during-trial-activities/sap-and-tlf-shells/)
- [生物統計解析の求人一覧](https://directscout.recruit.co.jp/job_search/occ_lv3_31d1f)
- [IaC（Infrastructure as Code）とは？](https://www.trendmicro.com/ja_jp/what-is/cloud-security/infrastructure-as-code.html)
