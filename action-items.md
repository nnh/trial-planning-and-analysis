# trial-planning-and-analysis Action Items

作成日：2026-09-13
改訂日：2026-09-14

## 直近

- [ ] `review/README.md` に固定の工程を入れる。入口の3点セットの説明が立案の3つだけを挙げていて、固定の工程が揃ったことを反映していない。固定は手順と機械検査が `review/sap-review/`、蓄積が `findings/` と2つのディレクトリにまたがる点も書く

## 判断が要るもの

- [!] `pipeline/scripts/sas/export-sdtm-metadata.sas` を落とすかどうか。現行の経路では誰も読まない（define.xml の生成を実装系統から外した時点で、生成が読むのは受領 define.xml と `docs/metadata/` の宣言だけになった）。試験側は既に落としてある。落とすなら削除し、`pipeline/README.md` の該当行も消す
- [!] `templates/timepoint-map.csv` に5列（`denom`・`ecphase`・`adslvar`・`subset`・`note`）を足すかどうか。試験側の実ファイルは雛形の7列に加えてこれらを持つ。足すなら `templates/README.md` に列の定義も書く
