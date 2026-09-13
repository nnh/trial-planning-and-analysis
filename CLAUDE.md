# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

作成日：2026-09-14
改訂日：2026-09-14

## リポジトリの性格

臨床試験の解析を回す枠組みそのものを置く公開リポジトリ（github.com/nnh/trial-planning-and-analysis、MIT）。解析の実装本体もデータも持たない。中身の大半は文書で、コードは試験リポジトリへコピーして使う部品である。個別の試験の解析はここでは行わない。

何を持ち何を持たないかは `README.md`「持たないもの」、汎用層と試験側の境界の判定は `examples/README.md` が持つ。

## 正本の地図

この枠組みで最も強い規則は、同じ事実を2箇所に書かないことである。このファイルも規則を写さず参照だけを持つ。書き足す前に正本を探し、あれば参照させる。

- `pipeline/analysis-pipeline-plan.md` — 中心。層の定義、フォルダ構成、工程の入口・出口条件、人の介入点、設計の原則、内部検証、文書の階層と決定の正本。文書の書き方の規約（日付・見出し・識別子・改行）も「命名の規約と既定」が持つ
- `starting-a-new-trial.md` — 新しい試験のリポジトリを起こし、固定データを受け取れる状態に立つまで
- `setting-up-a-machine.md` — 枠組みを回す端末を1台立てる。macOS と Windows の入れ方、Windows でだけ起きること（ストアエイリアス・rig・バッチの shim）の理由。要るものの一覧は持たず、`check-environment.py` が正本
- `pipeline/README.md` — スクリプトの一覧と役割、実行できる形を Python と R に限る規則、外部パッケージを足さない境界
- `templates/README.md` — 機械可読な宣言の列の定義と、埋める順序
- `review/README.md` — 立案時レビューと最終レビュー、3点セットの考え方
- `findings/README.md` — 欠陥事例の書き方、匿名化、機械へ寄せる昇格の判定
- `trials/` — 試験を1本通すごとの通過記録
- `history.md` — 経緯と過去の判断。現在の規則をここへ混ぜない
- `action-items.md` — 積み残し。片づいたら `action-items-archive.md` へ移す
- `docs/work-logs/YYYYMMDD-work-log.md` — 日ごとの作業記録
- `_review/` — 枠組み自体を外部モデルにレビューさせた記録

## スクリプトの実行

`pipeline/scripts/` のものは試験リポジトリへコピーして使う前提で書かれている。ファイル冒頭の「使い方」が `python scripts/xxx.py` と書くのは試験リポジトリでの姿で、この枠組みで動かすときのパスは `pipeline/scripts/python/xxx.py` である。

`boxpath.py` は自分の1つ上をリポジトリの根と見て `docs/metadata/trial.json` を読む。この枠組みにその設定は無いので、`run-*.py` と `build-*.py` の大半、Box を読む検査はここでは動かない。動かして確かめたいときは試験リポジトリで回す。

この枠組みの中で単独に回るもの。

```bash
python3 pipeline/scripts/python/check-environment.py      # 端末で何が回せるか。試験リポジトリが無くても動く
python3 pipeline/scripts/python/read_xlsx_test.py         # read_xlsx.py の回帰確認。このリポジトリで唯一のテスト
python3 review/planning-review/audit_sap_structure.py <文書>
python3 review/planning-review/audit_declarations.py --metadata <dir> --acceptance <dir> [--sap <文書>]
python3 review/ecrf-review/audit_ecrf_json.py <構造定義JSON>
python3 review/sap-review/audit_fixed_data.py inventory|audit|diff <dir>
TRIAL_REVIEW_DIR=$PWD/review python3 skills/trial-planning-review/scripts/run-planning-review.py --sap <文書> --prt <文書> --ecrf <JSON>
```

検査の終了コードは3値で、2 を 0 と読まない。3値の定義と規則の一覧は各スクリプト冒頭のコメントが持つ。新しい検査を足すときも同じ作法に従う。

## 作業の流れ

- 欠陥を見つけたら、工程ごとの蓄積へ型として返す。置き場と書き方は `findings/README.md`
- 規則を新設したら正本を1つ決め、他は参照させる。スキル（`skills/`）は `review/` の規則を写さない
- 試験側との同期は一方向のコピーではない。手順は `pipeline/analysis-pipeline-plan.md`「試験側との同期」
- 試験固有の値をスクリプトへ書かない。`docs/metadata/trial.json` だけが持つ

## コミット

メッセージは日本語。1行目に何をしたかを書き、本文に理由と、その判断の根拠になった事実を書く。末尾に `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` を置く。
