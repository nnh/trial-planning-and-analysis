# trial-planning-and-analysis Action Items

作成日：2026-09-13
改訂日：2026-09-13

## 直近

- [ ] 試験側の `trial.json` に `define` と `sap_pdf` の2鍵を足す。枠組みの `build-adam-define.py`・`build-pi-package.py` はこの2鍵を読むが、試験側は `trial_id`・`box_path`・`received_define` の3鍵しか持たない。試験側は `--originator` の直書きと `SAP_PDF_SRC` の定数で動いているので、枠組み側を戻すとそこで止まる。鍵の形は `templates/trial.json`
- [ ] `review/README.md` に固定の工程を入れる。入口の3点セットの説明が立案の3つだけを挙げていて、固定の工程が揃ったことを反映していない。固定は手順と機械検査が `review/sap-review/`、蓄積が `findings/` と2つのディレクトリにまたがる点も書く

- [ ] 区間2の必須宣言と仕様索引を立案時レビューの入口に加える。いまの実行器が受け取るのは統計解析計画書・研究計画書のテキストと電子症例報告書の JSON だけで、宣言 CSV も仕様索引も見ない。統計解析計画書の分母を変えて宣言を旧版に残しても、その差はこの検査に入らない（外部レビュー 指摘1の残り）
- [ ] 固定データ検査の対象を受領マニフェストで指定する。いまは走査範囲を直下に限って同名ドメインで止めるところまで。どのファイルが現行の入力かを宣言から引く形にはなっていない（外部レビュー 指摘10の残り）
- [ ] 突合のキーを試験ごとに事前宣言する。いまは判定を表す変数をキーから外し、一意に結べなければ未評価として止めるところまで。ドメインごとの正しいキーを宣言から引く形にはなっていない（外部レビュー 指摘5の残り）
- [ ] 通し実行の再開の記録に、各段の入出力のハッシュと宣言・環境の版を持たせる。いまは受領データの指紋と段階1・2の成果物だけで、段階3以降は実施記録しか持たない（外部レビュー 指摘9の残り）

- [ ] 試験側の `docs/metadata/mr-timepoint.csv` を `timepoint-map.csv` へ改名する。枠組みの読み手を雛形の名前に揃えたので、同期した試験側は名前を変えないと時点別の表示型が止まる。PhALL219 に該当ファイルがある

## 判断が要るもの

- [!] `pipeline/scripts/sas/export-sdtm-metadata.sas` を落とすかどうか。現行の経路では誰も読まない（define.xml の生成を実装系統から外した時点で、生成が読むのは受領 define.xml と `docs/metadata/` の宣言だけになった）。試験側は既に落としてある。落とすなら削除し、`pipeline/README.md` の該当行も消す
- [!] `templates/timepoint-map.csv` に5列（`denom`・`ecphase`・`adslvar`・`subset`・`note`）を足すかどうか。試験側の実ファイルは雛形の7列に加えてこれらを持つ。足すなら `templates/README.md` に列の定義も書く
- [!] 水準の表示名の正本を `label-catalog.csv` に一本化するかどうか。`analysis-grouping.csv` の `label` 列が同じ表示名を二重に持ち、`build-ars-json.py` は `label` 列を読んで空なら識別子へ落ちるので `label-catalog.csv` を引かない。一本化するなら `build-ars-json.py` の参照先を変える
