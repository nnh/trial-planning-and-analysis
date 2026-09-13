# action-items 完了分

## 次の試験に入る前に片づけるもの

- [x] `check-environment.py` が解析を回す端末の要件まで見るようにした。R のビルド道具・`jsonschema`・`playwright` の3項目を足し、SAS・CDISC CORE と同じ「回せない工程」として報告する。実行機でも回す段を `starting-a-new-trial.md` 4.1. へ書いた。5つのうち Python 本体がスタブの場合だけは、この検査自体がそのスタブで起動するため拾えないので、4.1. で人が確かめる項目として書いた
- [x] `starting-a-new-trial.md` の順序の食い違いを直した。4.1. の環境検査がスキル2つを必須として見るのに、配置は 4.5. だったため、手順どおり上から進めると 4.1. で必ず終了コード1になっていた。スキルの配置を 4.1. へ前出しし、修正後に手元の端末で通して終了コード0を確認した
- [x] 着手に要る情報を `starting-a-new-trial.md` の「適用範囲と着手の条件」に明示した。渡すのは試験の識別子・データの置き場・研究計画書の草案・統計解析計画書の草案の4つで、`trial.json` の残る鍵がどの段で埋まるかも併記した
- [x] 実行の形を `pipeline/scripts/` へ持ち込む。Python 19本と `r/build-define-html.R` を入れ、`pipeline/scripts/powershell/` の6本を落とした。入口と一覧は `pipeline/README.md`「scripts/」
- [x] 検査スクリプトを `pipeline/scripts/python/` へ足す。7本を持ち込んだ。8本目に数えていた ADaM の論理検証は SAS 側の QC プログラムにあり、判定条件が疾患と研究計画書で変わるため汎用層は段の置き場と停止条件の形だけを持つ（`pipeline/README.md`「試験ごとに書き換えるもの」）
- [x] 宣言の雛形を `templates/` へ足す。17件。18件としていたのは `codelist-decode.csv` を SDTM と ADaM で二重に数えていたため。列の定義は `templates/README.md`
- [x] 試験Aの通過記録を `trials/` へ起こす。`trials/trial-a-20260913.md`。決定は78件で、設計文書が持っていた71件は 2026-09-06 時点の値だった。`pipeline/analysis-pipeline-plan.md` の「試験実績」「適用例」からは、原則の根拠になっていない数値を落とした
- [x] 固定の工程の3点セットを揃える。手順は `review/sap-review/data-verification.md` の 4.7〜4.10、機械検査は同 `audit_fixed_data.py`、蓄積は `findings/data-verification-findings-log.md`（9件）
- [x] 納品より後の工程を1つ足す。`pipeline/analysis-pipeline-plan.md` に区間5と「納品より後の工程」。納品承認より後なので必須2点・条件付き3点には数えない
- [x] 新しい試験を始める手順を1本書く。`starting-a-new-trial.md`
- [x] 蓄積の追記トリガーを配布元へ入れ直す。配布元は `saito-la/claude-toolkit` の `guides/SESSION-END.md` で、akiko-office ではなかった。Step 4b として入れ、正本がどちらかを toolkit の README に明記した
- [x] 試験側との同期の遅れを取り戻す。Python 14本・R 2本・SAS 2本を置き換えた。`findings/README.md` の「固定・納品の欠陥事例はまだ無い」も直した
- [x] `runcommon.find_rscript()` が選ぶ版と `renv.lock` の固定を突き合わせる。固定した版が端末に在ればそれを使い、無ければ新しい方で回して画面に出す。黙って別の版で回ると、気づくのは renv が復元で止まるときになる。探す形は Windows の導入先のものだけで、macOS は PATH の Rscript を使う（版を1つだけ持つ運用のため。境界は docstring に書いた）
- [x] この枠組み自身に `.gitattributes` を置く。`* text=auto eol=lf` の1行のみ。枠組みの追跡ファイルはすべてテキスト（py・md・csv・sas・R・json・html）なので binary の指定は置かない。理由の正本は配る雛形 `templates/gitattributes` 側に残した。`git add --renormalize .` の差分は0件で、既存のファイルはもともと LF だった
