# trial-planning-and-analysis Action Items

作成日：2026-09-13
改訂日：2026-09-14

## 直近

- [ ] `review/README.md` に固定の工程を入れる。入口の3点セットの説明が立案の3つだけを挙げていて、固定の工程が揃ったことを反映していない。固定は手順と機械検査が `review/sap-review/`、蓄積が `findings/` と2つのディレクトリにまたがる点も書く
- [ ] `runcommon.find_rscript()` が選ぶ版と `renv.lock` の固定を突き合わせる。版のハードコードは外したが、複数の版が入っている端末では新しい方を採るので、固定した版と違う R で回り得る。食い違いに気づくのは renv が復元で止まるときで、実行の手前ではない
- [ ] この枠組み自身に `.gitattributes` を置くか決める。`templates/gitattributes` を試験リポジトリへ配る規約を持ちながら、枠組み自身は改行を強制していない。Windows のクローン（`core.autocrlf=true`）では CRLF で展開され、同じコミットから取った同じファイルの SHA が端末ごとに違う。現状 `.sh` が無いので実行の実害は出ていない（2026-09-14 に実行機で確認）

## 判断が要るもの

- [!] `pipeline/scripts/sas/export-sdtm-metadata.sas` を落とすかどうか。現行の経路では誰も読まない（define.xml の生成を実装系統から外した時点で、生成が読むのは受領 define.xml と `docs/metadata/` の宣言だけになった）。試験側は既に落としてある。落とすなら削除し、`pipeline/README.md` の該当行も消す
- [!] `templates/timepoint-map.csv` に5列（`denom`・`ecphase`・`adslvar`・`subset`・`note`）を足すかどうか。試験側の実ファイルは雛形の7列に加えてこれらを持つ。足すなら `templates/README.md` に列の定義も書く
