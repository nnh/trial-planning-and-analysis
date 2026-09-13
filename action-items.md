# trial-planning-and-analysis Action Items

作成日：2026-09-13
改訂日：2026-09-13

## 直近

- [ ] 試験側の `trial.json` に `define` と `sap_pdf` の2鍵を足す。枠組みの `build-adam-define.py`・`build-pi-package.py` はこの2鍵を読むが、試験側は `trial_id`・`box_path`・`received_define` の3鍵しか持たない。試験側は `--originator` の直書きと `SAP_PDF_SRC` の定数で動いているので、枠組み側を戻すとそこで止まる。鍵の形は `templates/trial.json`
- [ ] `review/README.md` に固定の工程を入れる。入口の3点セットの説明が立案の3つだけを挙げていて、固定の工程が揃ったことを反映していない。固定は手順と機械検査が `review/sap-review/`、蓄積が `findings/` と2つのディレクトリにまたがる点も書く
- [ ] 実行機に何が要るかを `starting-a-new-trial.md` へ書く。2026-09-14 に試験Aをリモートで回したとき、実行の入口を Python へ移してから16日のあいだ実行機の側が追随しておらず、Python 本体・R・R のビルド道具・検査に要る外部パッケージ（`playwright`・`jsonschema`）・生成が呼ぶスキルの5つが足りなかった。手順の「用意するもの」に、解析を回す端末が持つべきものを列挙する。型は `findings/analysis-findings-log.md`「実行の入口を移したとき、実行機の側が追随しない」
- [ ] 汎用の表示型が読むファイル名から疾患名を外す。`tlf_ops.R`・`tlf_ops.sas` が `mr-timepoint.csv` を直接読んでいる。雛形側の名前は `templates/timepoint-map.csv` で列は同じ。名前を変えるか、設定から引く形にするかを決める

## 判断が要るもの

- [!] `pipeline/scripts/sas/export-sdtm-metadata.sas` を落とすかどうか。現行の経路では誰も読まない（define.xml の生成を実装系統から外した時点で、生成が読むのは受領 define.xml と `docs/metadata/` の宣言だけになった）。試験側は既に落としてある。落とすなら削除し、`pipeline/README.md` の該当行も消す
- [!] `templates/timepoint-map.csv` に5列（`denom`・`ecphase`・`adslvar`・`subset`・`note`）を足すかどうか。試験側の実ファイルは雛形の7列に加えてこれらを持つ。足すなら `templates/README.md` に列の定義も書く
- [!] 水準の表示名の正本を `label-catalog.csv` に一本化するかどうか。`analysis-grouping.csv` の `label` 列が同じ表示名を二重に持ち、`build-ars-json.py` は `label` 列を読んで空なら識別子へ落ちるので `label-catalog.csv` を引かない。一本化するなら `build-ars-json.py` の参照先を変える
