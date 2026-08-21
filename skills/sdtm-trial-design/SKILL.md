---
name: sdtm-trial-design
description: SDTM の Trial Design ドメイン（TS・TA・TE・TI・TV）をプロトコルから作るスキル。データ共有プラットフォーム（Vivli等）への登録前、CDISC CORE の SKIPPED を減らしたいとき、「SDTM だけを見て試験の概要が分かるようにしたい」「試験の計画を機械可読にしたい」と言われたときに使う。TSPARMCD の必須リストと CT の値を CDISC の定義から引くスクリプトを同梱する。
---

# Trial Design ドメインの作成

`TS`・`TA`・`TE`・`TI`・`TV` は試験の計画を表すドメインで、受領データからは作れない。
プロトコルから起こす。作らないと CDISC CORE のルールが大量に SKIPPED になる（実測で44）。

以下 `$SKILL` は**このSKILL.mdが置かれているディレクトリの絶対パス**。symlink 経由で
読み込まれていても実体のディレクトリを解決して使う。

## 1. 材料を集める

まず CDISC の定義を引く。**手で調べない。** `TSPARMCD` は CT に129種あり、そのうち何が
必須かはルールが決めている。版が変わると内容も変わる。

```bash
python "$SKILL/scripts/export-ts-parameters.py"              # 必須・CTの値・IGの変数
python "$SKILL/scripts/export-ts-parameters.py" --skeleton    # ts.csv の骨組み
```

CDISC CORE のキャッシュ（`%USERPROFILE%\opt\cdisc-core\core\resources\cache`）から読む。
CORE が別の場所にあるときは `--cache` で指定する。オプションは `--help` が正本。

次にプロトコルから読む。節の番号は試験ごとに違うので**目次を出してから当たりを付ける**。

- 試験の要旨（正式名称・依頼者・登録番号・目標例数・研究期間・デザインの概要）
- 目的と評価項目（主要・副次的）
- 選択基準・除外基準の条文
- 治療の流れ（相の順序、分岐の条件、各相の期間）
- 来院スケジュール
- 試験の中止規定（**被験者単位の中止と試験全体の中止は別の節にあることが多い**）

実データからも取る。`SSTDTC` は `DM.RFICDTC` の最小値（CTの定義が「最初の同意日」）、
`ACTSUB` は `DM` の被験者数、`ARMCD`・`ARM` は `DM` の値、`FCNTRY` は `DM.COUNTRY`。

## 2. TS（Trial Summary）

必須は27種（`CORE-000740` / CDISC CG0287）。`STYPE=INTERVENTIONAL` のときは
`INTMODEL`・`INTTYPE`・`PCLASS` の3つが揃っている必要がある（`CORE-000741` / FDA FB1111）。

- `TSPARM` は `TSPARMCD` に対応する CT の用語をそのまま使う。自分で書かない
- 値に CT があるパラメータは CT の submission value を使う（スクリプトの `--values`）。
  `PCLASS` は CT に無いので自由文（NCI の Established Pharmacologic Class を書く）
- 同じ `TSPARMCD` に複数の値があるときは `TSSEQ` で分ける（`TRT` に2剤、`OBJSEC` に2文、
  `STOPRULE` に6項目など）
- **`TSVAL` を空にして `TSVALNF` だけ置くと、日付のパラメータで適合性エラーになる**
  （`CORE-000506`）。`SENDTC` は必須なので削除もできない。試験が継続中なら、データカット
  時点の最終観察日を入れて、継続中である旨を出典の欄に書く

判断が要るもの。**プロトコルに書かれていないことを推測で埋めない。**

- `LENGTH` は「1症例あたりの観察期間」（試験全体の期間ではない）
- `DCUTDTC`・`DCUTDESC` はデータの受領記録から取る。解析担当に確認する
- `STOPRULE` は試験全体の中止規則。被験者単位の中止理由（`DS` の値になるもの）とは別。
  プロトコルの「試験の終了」「統計」の節にあることが多く、「中止基準」の節には被験者単位
  しか書かれていないことがある。**見つからないと判断する前に節を網羅的に探す**

## 3. TA（Trial Arms）・TE（Trial Elements）

- **`TA.ARMCD` は `DM.ARMCD` と一致していなければならない**（CORE の照合ルール）。
  単群試験で `DM.ARMCD` が1値なら `TA` も1腕にする。治療方針で経路が分かれても腕は増やさない
- 経路の分岐は `TABRANCH` に条件を書く。要素を一本の順序（`TAETORD`）に並べたうえで、
  分岐点の行に「どちらへ進むか」を書く。近似になるが `TA` の表現力の範囲
- `ELEMENT` は `TE` が正本。`TA` では `ETCD` で引く（同じ文字列を2箇所に書かない）
- `TE.TESTRL`・`TEENRL` は要素の開始・終了の規則。`TEDUR` は固定長の要素だけ入れる
  （ISO 8601 の期間。可変なら空）

## 4. TI（Trial Inclusion/Exclusion Criteria）

- トップ項目とサブ項目をそれぞれ1レコードにする。`IETESTCD` は `INCL01`・`INCL06A`・
  `EXCL08D` の形で**8文字以内**
- `IETEST` は**200文字以内**。原文が長い条文は、意味を落とさずに縮める。括弧書きの例示や
  但し書きを削るのが定石
- `IECAT` は `INCLUSION` / `EXCLUSION`
- 原文が日本語なら英訳する。**条文には機種依存文字が混ざる**（ローマ数字の `Ⅷ`、単位の
  `㎎`）。ASCII に直す（→ スキル `cdisc-charset-check`）
- **英訳の医学的な妥当性は自分で担保しない。** 訳したうえで、確認が必要な項目を名指しして
  依頼する。とくに疾患名・検査項目名・既往歴の表現

## 5. TV（Trial Visits）

- `VISITNUM`・`VISIT` は SDTM の他ドメインと同じ対応表を使う。**対応表が SAS のフォーマットと
  R のベクトルと仕様書の3箇所にあるなら、この機会に CSV 1箇所へまとめる**。`TV` も同じ表から作る
- `TVSTRL`（来院の開始規則）は**必須**（`CORE-000355`）。各来院に1文書く
- `VISITDY` は試験の Day 1 からの計画日。**コース単位の相対日でスケジュールが書かれている
  試験では算出できない**（コースの長さが症例ごとに変わる）。その場合は空にして、理由を
  仕様書に書く
- `ARMCD`・`ARM` は `TA` から引く

## 6. 実装

CSV を正本にして、SAS と R がそれを読む形にする。

- **CSV は両系統で共有する。** プロトコルの内容を2箇所に書かないため。二重コーディングを
  している試験でも、変換の処理だけを独立に実装すれば転記の誤りは突合で検出できる
- CSV に出典の列（`source`）を持たせる。SDTM には出さない。**値も出典も ASCII にする**
- 突合のキーはドメインごとに違う。Trial Design は被験者に紐づかないので `USUBJID` +
  `--SEQ` が使えない。`TS` は `TSPARMCD`+`TSSEQ`、`TA` は `ARMCD`+`TAETORD`、`TE` は `ETCD`、
  `TI` は `IETESTCD`、`TV` は `ARMCD`+`VISITNUM`
- 忘れやすい追加箇所。Dataset-JSON の対象ドメイン、突合のドメイン一覧とキー、
  変数マップ（`origin` は `Protocol`。`STUDYID`・`DOMAIN` は `Assigned`）、仕様書の節

## 7. define.xml

受領 define.xml には Trial Design が無いことが多いので、`ItemGroupDef` を新規に作る。

- `def:Class='TRIAL DESIGN'`・`IsReferenceData='Yes'`（被験者データではない）・
  `Repeating='Yes'`・`Purpose='Tabulation'`
- `Structure` は IG の記述に合わせる（`One record per trial summary parameter value` など）
- **変数のラベルは IG から引く。** 既存の生成スクリプトが追加変数のラベル表を
  ハードコードで持っている場合、ドメインごと新しいと表に無くて止まる。IG のラベルで
  補うフォールバックを入れる
- Trial Design は `General Observations` クラスの共通変数（`EPOCH`・`VISIT`・`--SEQ`）を
  継承しない。IG の Role を引くときにクラスの継承チェーンから外す

## 8. CORE で確認する

Trial Design を入れると、それが無いために飛ばされていたルールが評価対象になる。**指摘が
増えたように見えても、SKIPPED が減って SUCCESS が増えているなら前進**である。ルールの
status（`SKIPPED` / `SUCCESS` / `ISSUE REPORTED` / `EXECUTION ERROR`）の推移で判断する。

`ITEMGROUPDATASEQ`（Dataset-JSON のレコード識別子）に対する形式上の指摘が、ドメインごとに
各1件ずつ増える（変数名8文字超・Model の許可変数外・ラベルが title case でない・変数の
順序・型の不一致）。これは実データの欠陥ではない。

**指摘の内容が分からないときは CORE のルール定義を読む。** `rules.pkl` の `conditions` に
期待する値の一覧が入っている（必須 `TSPARMCD` の27種はここから取れる）。メッセージだけでは
何が足りないか分からないことが多い。

## 9. SAS で当たる制約

- **`proc format` の `cntlout=` は `library=` を省くと出力が空になる。** `select` を併せても
  空になる。既存フォーマットの内容を取り出すには `library=work cntlout=` で全件出して
  `FMTNAME` で絞る
- **`proc import` は値が全行数値に見える列を数値型にする。** バージョン番号（`1.9`）が
  これに当たる。SAS は変数名の大文字小文字を区別しないので `length TIVERS $20` と衝突して
  「変数は文字と数値の両方に定義されています」で止まる。`rename` して `vvalue()` で受ける
- 1つの data step のエラーが後続の `proc sql` を連鎖的に壊す。最初のエラーだけを見て直す
