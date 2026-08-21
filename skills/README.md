# スキル

作成日：2026-08-22
改訂日：2026-08-22

Claude Code の Skill 形式で書かれた、実行できる資産。試験リポジトリから `~/.claude/skills/` へコピーして使う。

- [trial-planning-review/](trial-planning-review/SKILL.md) — 立案時レビュー（PRT・SAP・図表案・eCRF 構造定義）を1本のコマンドで回す。規則は写さず [../review/](../review/README.md) を呼ぶ
- [sdtm-trial-design/](sdtm-trial-design/SKILL.md) — Trial Design ドメイン（TS・TA・TE・TI・TV）をプロトコルから作る
- [cdisc-charset-check/](cdisc-charset-check/SKILL.md) — SDTM・ADaM に残る非ASCII文字の検出と、層ごとの対処
- [sdtm-conformance-triage/](sdtm-conformance-triage/SKILL.md) — CDISC CORE の指摘を直すものと既知に仕分ける
- [cdisc-define-xml/](cdisc-define-xml/SKILL.md) — SDTM・ADaM の define.xml を作る・整える
- [sas-utf8-migration/](sas-utf8-migration/SKILL.md) — SAS を CP932 セッションから UTF-8 セッションへ移す

## 使い方

各スキルのディレクトリを `~/.claude/skills/` へコピーする。

```bash
cp -r skills/trial-planning-review ~/.claude/skills/
```

Claude Code がスキル一覧に表示し、SKILL.md の説明文がトリガーする発言（「PRTをレビューして」等）で自動的に呼び出す。手動で呼ぶ場合は `/trial-planning-review` のようにスラッシュコマンドとして呼べる。

## 育つ仕組みとの関係

新しい規則・手順が[蓄積の3つの型](../findings/README.md)を通じて磨かれ、3試験で同じ手順を踏んだらスキルへ格上げする。ここにあるスキルは、その格上げを経た資産である。
