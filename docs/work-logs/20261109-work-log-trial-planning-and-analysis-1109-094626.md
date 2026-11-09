# 作業ログ

作成日：2026-11-09
改訂日：2026-11-09

この worktree では、構造定義の機械検査へ寄せられた提案を判断し、反映した。

## 概要

試験I の EDC 構築レビューを `review/ecrf-review` の手順で回した利用者から、提案が3点届いた。欠陥事例の追記、R04 から IETEST を外すこと、同じシート内の参照先違いを拾う規則の追加である。SDTMIG と規則の設計に照らし、3点とも方向は妥当と判断して反映した（`4a0157b`）。うち2点は形を変えた。

## 決定事項

- 欠陥事例は別の見出しを立てず、既存の見出しを「参照フィールドの参照先違い」に広げ、他シート（R02）と同じシート内（R13）の2つの現れ方として書いた。[findings/README.md](../../findings/README.md) が見出しを原因の型で立てると決めているため
- IETEST は R04 から外さず、IE だけ上限を200文字にした。SDTMIG 3.2・3.3・3.4 の IE は、どれも IETEST を200文字までと定める（CDISC Library で確認）。外すと200文字を超える基準文を見落とす。試験I に203文字の除外基準が1件実在する
- 同じシート内の参照先違いは R13 にした。試験A に続く2試験目の同じ型なので、昇格の判定に合う。構造定義には欄の区切りが無いため、同じシートでラベル・SDTM 変数・型が同じ項目を欄の繰り返しと見て判定する
- [checklist.md](../../review/ecrf-review/checklist.md) の R01〜R12 の一覧は、スクリプトの各規則の説明の写しだったので、参照1行に替えた
- 提案者からの次回以降の変更は、プルリクエストで受ける。今回はこちらで反映し、従来の履歴と同じく master へ直接入れた

## 実測

- 試験I（11/6 版）：変更前は R04 の error が34件。変更後は R04 が1件（203文字）、R13 が8件（標的病変2〜5の検査方法・検査日）
- 他の13試験の構造定義：減った R04 は IE だけだった。R13 が出たのは1試験の2件だけで、併存症のシートで MHDECOD の参照が別の病名の MHTERM を指していた。この2件は提案者へ参考情報として伝えた。同じシート内の参照を277件持つ構造定義でも0件だった
- 回帰確認は、規則をわざと壊すと落ちることを確かめた。その過程で、結果を変えない冗長な条件を1つ外した

## 成果物

- [audit_ecrf_json.py](../../review/ecrf-review/audit_ecrf_json.py) — R04 の上限を IE だけ200文字にし、R13 を足した
- [audit_ecrf_json_test.py](../../review/ecrf-review/audit_ecrf_json_test.py) — 新規。R04 と R13 の回帰確認
- [findings-log.md](../../review/ecrf-review/findings-log.md) — 見出しを広げて試験I の事例を足し、IETEST の上限と「レビュー側の誤り」の1件を足した
- [checklist.md](../../review/ecrf-review/checklist.md)・[README.md](../../review/ecrf-review/README.md)・[CLAUDE.md](../../CLAUDE.md)・[SKILL.md](../../skills/trial-planning-review/SKILL.md)・[run-planning-review.py](../../skills/trial-planning-review/scripts/run-planning-review.py) — テストの追記と、規則の範囲を R01-R13 にする変更
- 本ログ

## 次回アクション

なし。試験側に残るもの（203文字の基準の短縮、もう1試験の2件）は提案者へ伝えた。
