# action-items 完了分

## 次の試験に入る前に片づけるもの

- [x] 実行の形を `pipeline/scripts/` へ持ち込む。Python 19本と `r/build-define-html.R` を入れ、`pipeline/scripts/powershell/` の6本を落とした。入口と一覧は `pipeline/README.md`「scripts/」
- [x] 検査スクリプトを `pipeline/scripts/python/` へ足す。7本を持ち込んだ。8本目に数えていた ADaM の論理検証は SAS 側の QC プログラムにあり、判定条件が疾患と研究計画書で変わるため汎用層は段の置き場と停止条件の形だけを持つ（`pipeline/README.md`「試験ごとに書き換えるもの」）
- [x] 宣言の雛形を `templates/` へ足す。17件。18件としていたのは `codelist-decode.csv` を SDTM と ADaM で二重に数えていたため。列の定義は `templates/README.md`
- [x] 試験Aの通過記録を `trials/` へ起こす。`trials/trial-a-20260913.md`。決定は78件で、設計文書が持っていた71件は 2026-09-06 時点の値だった。`pipeline/analysis-pipeline-plan.md` の「試験実績」「適用例」からは、原則の根拠になっていない数値を落とした
- [x] 固定の工程の3点セットを揃える。手順は `review/sap-review/data-verification.md` の 4.7〜4.10、機械検査は同 `audit_fixed_data.py`、蓄積は `findings/data-verification-findings-log.md`（9件）
- [x] 納品より後の工程を1つ足す。`pipeline/analysis-pipeline-plan.md` に区間4と「納品より後の工程」。納品承認より後なので必須2点・条件付き3点には数えない
- [x] 新しい試験を始める手順を1本書く。`starting-a-new-trial.md`
- [x] 蓄積の追記トリガーを配布元へ入れ直す。配布元は `saito-la/claude-toolkit` の `guides/SESSION-END.md` で、akiko-office ではなかった。Step 4b として入れ、正本がどちらかを toolkit の README に明記した
- [x] 試験側との同期の遅れを取り戻す。Python 14本・R 2本・SAS 2本を置き換えた。`findings/README.md` の「固定・納品の欠陥事例はまだ無い」も直した
