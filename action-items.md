# trial-planning-and-analysis Action Items

作成日：2026-09-13
改訂日：2026-09-22

## 直近

- [ ] `review/README.md` に固定の工程を入れる。入口の3点セットの説明が立案の3つだけを挙げていて、固定の工程が揃ったことを反映していない。固定は手順と機械検査が `review/sap-review/`、蓄積が `findings/` と2つのディレクトリにまたがる点も書く
- [ ] 決定の台帳の一覧を本文から作る仕組みを入れる。`check-decisions.py` は一覧と本文の一致を見るのに、一覧を作る側が無い。検査のコメントは「一覧は区分ブロックから作るもので、手で維持しない」と書いているのに、作る手段が無いため手作業が残る。試験側で `scripts/build-decision-index.py` を書いたので `pipeline/scripts/python/` へ持ち込む
- [ ] `check-decisions.py` の枠の節（`FRAME`）に「関連」を足す。台帳の末尾に他の文書と同じ `## 関連` を置くと、それがエントリとして拾われて区分が揃っていないと報告される。試験側では関連の節を置かずに回避したが、他の文書と書き方が揃わない
- [ ] `check-environment.py` が枠組みの位置を自分の3つ上と決め打ちしている点を直す。試験リポジトリへ写した版では枠組みの位置が `Projects` と表示され、`TRIAL_REVIEW_DIR` を設定していない端末ではその誤った位置の `review/` を探しにいく。欠落と報告されるので安全側には倒れるが、置き場を直す先が分からない

## 判断が要るもの

- [!] 匿名化した試験ラベルと実際の試験の対応表をどこに置くか。`findings/` の各ログが試験A から試験H まで複数のラベルを使っているのに、どのラベルがどの試験かを引ける場所が無い。2026-09-22 に試験側から型を返すとき、既存のラベルのどれに当たるかを判定できず、新しいラベル（試験E）を立てた。同じ試験に2つのラベルが付いている可能性がある。対応表は公開リポジトリに置けないため、各試験リポジトリの `CLAUDE.md` に自分のラベルを書く形か、組織側の非公開リポジトリに一覧を置く形かを決める

- [!] `pipeline/scripts/sas/export-sdtm-metadata.sas` を落とすかどうか。現行の経路では誰も読まない（define.xml の生成を実装系統から外した時点で、生成が読むのは受領 define.xml と `docs/metadata/` の宣言だけになった）。試験側は既に落としてある。落とすなら削除し、`pipeline/README.md` の該当行も消す
- [!] `templates/timepoint-map.csv` に残る4列（`denom`・`ecphase`・`adslvar`・`note`）を足すかどうか。`subset` は 2026-09-18 に足した。判断ではなく欠落で、`check-identifier-length.py` がこの列を読むのに雛形が持っておらず、雛形どおりに作った2試験目で検査が「列が無い」と報告して止まったため。残る4列のうち `note` は2試験に共通するので昇格の条件を満たす。`denom`・`ecphase`・`adslvar` は試験Aだけ、2試験目が独自に持つのは `visitnum`・`sheet_label_ja`・`epoch`・`spec_planned` の4列で、重なりが無い。3試験目まで試験側に置いて判断する。足すなら `templates/README.md` に列の定義も書く
- [ ] 受入基準の列ごとの必須を宣言する仕組みを入れる。`audit_declarations.py` の D08 は行数で空を判定するので、`primary-endpoint.csv` のように雛形が鍵の行を1行持つファイルは、値が空のままでも通る
- [ ] `timepoint-map.csv` の7列のうち `source` を誰が読むのかを `templates/README.md` に書く。汎用層（`tlf_ops.R`・`tlf_ops.sas`）が読むのは `order`・`label`・`glabel` の3列、`rsparamcd` は `examples/trial-displays.sas`、`subset` は `check-identifier-length.py` で、`source` と `spid` は読み手が見つからない。雛形が「実装が読む列の集合」を表していない状態になっている
