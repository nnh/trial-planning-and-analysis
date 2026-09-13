# 欠陥事例

作成日：2026-08-22
改訂日：2026-09-13

試験を1本通すたびに見つかった欠陥を、症状ではなく原因の型として残す蓄積。次の試験で同じ箇所を見るための実体であり、レビュー・解析のたびに追記する。

工程ごとに置き場が分かれる。

- 立案（研究計画書・図表案） — [../review/planning-review/findings-log.md](../review/planning-review/findings-log.md)
- 立案（電子症例報告書の構造定義） — [../review/ecrf-review/findings-log.md](../review/ecrf-review/findings-log.md)
- 固定（固定データの検証と再抽出） — [data-verification-findings-log.md](data-verification-findings-log.md)
- 解析と納品（固定データを受け取ってから納品まで） — [analysis-findings-log.md](analysis-findings-log.md)

立案の2つは3点セットがそれぞれのサブディレクトリで完結する（[../review/README.md](../review/README.md)）。固定は手順と機械検査が [../review/sap-review/](../review/sap-review/data-verification.md)、蓄積がここ、と2つのディレクトリにまたがる。手順は `data-verification.md`、機械検査は `audit_fixed_data.py` である。

納品は独立した工程として3点セットを持たない。手順は [../pipeline/analysis-pipeline-plan.md](../pipeline/analysis-pipeline-plan.md) が持ち、専用の機械検査は無く、欠陥事例は `analysis-findings-log.md` の「納品と再現で壊れるもの」が持つ。納品より後の工程（総括報告書概要・追加解析の受け方）は枠組みにまだ無い（[../action-items.md](../action-items.md)）。

## 書き方

- 見出しは型の名前にする。症状ではなく原因で書く
- 本文は、何が起きたか・どう見つけるか・出どころ（試験名は匿名化し、日付。機械検査で拾ったなら規則番号）の順
- 確認の結果、指摘でなかったものも消さずに残す
- レビュー・検証側の誤りも残す。次に同じ誤りをしないため
- 被験者単位の情報は書かない。症例番号・日付・検査値は型の説明に要らない。要るのは件数と構造である

## 昇格の判定

蓄積したものをどこまで機械に寄せるかの判定。

- 初出 — 欠陥事例に型として書く。この時点では機械化しない
- 2試験目で同じ型が出た — 機械で判定できるか見る。できれば規則にして番号を足す。判断が要るならチェックリストの項目にする
- 3試験で同じ手順を踏んだ — スキルにする
- 規則が3試験続けて0件 — 落とす候補にする。落とすときも消さず、落とした理由を残す
- 設計原則に組み込まれた — 原因が枠組みの設計そのもの（宣言駆動、表示文言のカタログ等）で構造的に排除され、その原則を守っている限り再発しない型は、対応する設計文書（[../pipeline/analysis-pipeline-plan.md](../pipeline/analysis-pipeline-plan.md) 等）の「なぜこの原則が要るか」の根拠として移す。ここには残さない。まだ人的ミス・外部要因・新規追加時の見落としで再発しうる型（テンプレートや既存実装で軽減されているだけのもの）とは区別する
