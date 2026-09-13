# 新しい試験の立ち上げ

作成日：2026-09-13
改訂日：2026-09-13

## 1. 目的

新しい試験の解析リポジトリを起こし、固定データを受け取れる状態に立つまでの作業と、その順序を定める。

## 2. 適用範囲

この枠組みを使って解析と納品を行う試験の、解析側リポジトリを新規に作るとき。既にあるリポジトリへ枠組みの更新を取り込む作業は範囲外で、[pipeline/analysis-pipeline-plan.md](pipeline/analysis-pipeline-plan.md)「試験側との同期」が持つ。

着手できるのは、研究計画書と統計解析計画書の草案があり、試験の識別子とデータの置き場が決まった時点である。図表案・電子症例報告書の構造定義・受領 define.xml は 4.5. までにそろえばよい。

この手順を終えた状態が、[pipeline/analysis-pipeline-plan.md](pipeline/analysis-pipeline-plan.md)「区間1 開始前の確定」の出口にあたる。区間2 以降はそこが持つ。

## 3. 役割と責任

- 統計解析責任者 — この手順の全段を実施し、固定前に決め切る事項を決める。
- 研究責任医師 — 医学的判断が要る照会に答え、決定の医学的な妥当性を確認する。
- データセンター — 電子症例報告書の構造定義と受領物を渡し、項目の意味・収集の有無・外部データの出所についての照会に答える。

## 4. 手順

4.1. から 4.4. は機械的な作業で、人の判断が入らない。4.5. と 4.6. が判断の段で、ここで出した照会の回答が届くまでに日数がかかるため、4.1. から 4.4. を待たずに 4.5. の資料集めを始めてよい。

以下の手順では、この枠組みの作業コピーを `$FRAMEWORK`、新しい試験のリポジトリを `$TRIAL` とする。

```bash
FRAMEWORK=<この枠組みのパス>
TRIAL=<新しい試験のリポジトリのパス>
```

### 4.1. リポジトリの骨格

最初に、この端末で何が回せるかを見る。依存の不足はデータを作り始める前にまとめて出す。回せない工程があることは、後の段で1つずつ突き当たるより、着手の前に分かっている方がよい。

```bash
python3 "$FRAMEWORK"/pipeline/scripts/python/check-environment.py
```

必須（python3・git・R・スキル2つ・枠組みの `review/`）が欠けていれば終了コード1で、そろっていれば0を返す。SAS と CDISC CORE は端末によって無いことがあり、その場合は回せない工程を挙げる。回せない工程を別端末で回すなら、どちらの端末で何を回すかを試験側の `CLAUDE.md` に書く。置き場が既定と違うものは環境変数で指す（`SAS_HOME`・`CDISC_CORE_EXE`・`CDISC_DEFINE_XML_SKILL`・`TRIAL_REVIEW_DIR`）。

統計解析責任者が、試験ごとに1つのリポジトリを作る。ディレクトリの形と、そう分ける理由は [pipeline/analysis-pipeline-plan.md](pipeline/analysis-pipeline-plan.md)「リポジトリ側の構成」が持つ。下のコマンドはその形を作るだけで、意図はそこを読む。

```bash
mkdir -p "$TRIAL"/program/sas/macro "$TRIAL"/program/sas/qc "$TRIAL"/program/r
mkdir -p "$TRIAL"/scripts
mkdir -p "$TRIAL"/docs/spec "$TRIAL"/docs/decisions "$TRIAL"/docs/reporting "$TRIAL"/docs/input
mkdir -p "$TRIAL"/docs/metadata/external "$TRIAL"/docs/metadata/trial-design
mkdir -p "$TRIAL"/docs/validation/acceptance "$TRIAL"/docs/validation/records
mkdir -p "$TRIAL"/docs/records "$TRIAL"/docs/correspondence "$TRIAL"/docs/work-logs "$TRIAL"/docs/tmf
git -C "$TRIAL" init
```

`docs/` の区分のうち、層の仕様・決定と規約・報告と成果物の設計・受領物の仕様の4つは、何をどこへ置くかを[同「spec から出したものの置き場」](pipeline/analysis-pipeline-plan.md)が持つ。決定の台帳を1つにする理由は[同「決定の正本を1つにする」](pipeline/analysis-pipeline-plan.md)。

`program/sas/` と `program/r/` を同じ深さに置く。片方を直下、他方をサブフォルダにしない。二重コーディングの2系統は対等な本解析であり、構成でそれを示す。突合の検出力が独立性に由来することと、独立性が崩れる条件は[同「独立性の担保」](pipeline/analysis-pipeline-plan.md)が持つ。

リポジトリは非公開にする。生データを置かない規則であっても、決定記録・対外文書の文案・症例の件数を含む記録が入る。

続いて、処理系がその場所で読む設定と、セッションの初めに読む生きた文書をルートへ置く。生成物はルートへ置かない。

- `CLAUDE.md` — 運用ルール。答えるのは5つに限る。git に置かないもの（生データ・実行ログ・出力）と、それをディレクトリ単位の除外で担保していること。フォルダ構成がどの方針に従うか（この枠組みの該当節を指し、規則を写さない）。一次文書の正本がどこにあるか（統計解析計画書の編集中の正本と、固定版の所在を別に書く）。実行の入口はどのスクリプトか。セッションの開始時と終了時に何をするか。端末ごとに違う環境の事柄（処理系の導入・符号化の切替・リモート実行）はここに書かず、環境側の文書を指す。
- `README.md`・`overview.md`・`issues.md`・`action-items.md` — 入口、現状、既知の問題と制約、積み残し。役割は「リポジトリ側の構成」の一覧が持つ。
- `autoexec.sas` — SAS がルートで読む設定。データの置き場を環境変数と実行端末から解決し、[同「フォルダ構成と命名規則」](pipeline/analysis-pipeline-plan.md)の層ごとにライブラリを割り当てる。置き場をプログラム本体へ書かないためのもので、試験の識別子とグループ名以外は試験をまたいで同じにする。
- `.Rprofile` と `renv/`・`renv.lock` — R がルートで読む設定と、パッケージの版の固定。R はリポジトリのルートをカレントにして起動する。別の場所から起動すると版の固定も共通基盤の探索も効かない。
- `.gitignore` — 受領物・実行ログ・出力・突合結果をディレクトリ単位で除外する。拡張子だけの除外に頼らない。被験者単位のデータを持つファイルをその外へ置くときは個別に足す。git に置かないものの一覧は[同「着手前チェック」](pipeline/analysis-pipeline-plan.md)の禁止・制約事項が持つ。
- `.gitattributes` — 改行を LF に揃える。揃えない場合に何が起きるかは[同「命名の規約と既定」](pipeline/analysis-pipeline-plan.md)が持つ。
- `docs/README.md` — `docs/` の見取り図。区分の意味は上記の節を指し、この試験で実際に置いたファイルの1行説明だけを書く。

### 4.2. 雛形の配置

統計解析責任者が、雛形を `$TRIAL/docs/` へ写す。受入基準の3本だけが `docs/validation/acceptance/` で、残りは `docs/metadata/` である。どの雛形が何を持つか、どの順で埋めるか、どれが出す試験だけのものかは [templates/README.md](templates/README.md) が持つ。

```bash
cp "$FRAMEWORK"/templates/*.csv "$FRAMEWORK"/templates/trial.json "$TRIAL"/docs/metadata/
mv "$TRIAL"/docs/metadata/primary-endpoint.csv "$TRIAL"/docs/metadata/analysis-set-condition.csv "$TRIAL"/docs/metadata/display-contract.csv "$TRIAL"/docs/validation/acceptance/
```

この段で行うのは配置だけで、中身は埋めない。埋める順序は一次文書が固まる順に決まり、[templates/README.md](templates/README.md)「使い方」がその順を持つ。受入基準の3本だけは 4.6. で埋め切る。

`docs/metadata/external/` と `docs/metadata/trial-design/` は雛形から作らない。外部標準の写しは [skills/cdisc-define-xml/](skills/cdisc-define-xml/SKILL.md) の取得スクリプトが、Trial Design の入力は [skills/sdtm-trial-design/](skills/sdtm-trial-design/SKILL.md) が作る。

雛形に他の試験の中身を残さない。表題や水準の表示名を流用すると、その試験の語彙が紛れ込む。

### 4.3. スクリプトの配置

統計解析責任者が、層をまたぐ実行・生成・検査のスクリプトを写す。どれが何をするかと、どの系統をどこへ置くかは [pipeline/README.md](pipeline/README.md)「scripts/」が持つ。

```bash
cp "$FRAMEWORK"/pipeline/scripts/python/* "$TRIAL"/scripts/
cp "$FRAMEWORK"/pipeline/scripts/r/build-define-html.R "$TRIAL"/scripts/
cp "$FRAMEWORK"/pipeline/scripts/r/ap_common.R "$FRAMEWORK"/pipeline/scripts/r/ap_xlsx.R "$FRAMEWORK"/pipeline/scripts/r/tlf_ops.R "$TRIAL"/program/r/
cp "$FRAMEWORK"/pipeline/scripts/sas/* "$TRIAL"/program/sas/macro/
```

置いた階層を動かさない。`scripts/boxpath.py` は自分の1つ上をリポジトリの根と見て `docs/metadata/trial.json` を探すので、`scripts/` の下にフォルダを掘って入れると設定が見つからない。`scripts/` をフォルダで分けず接頭辞で並べる理由は [pipeline/analysis-pipeline-plan.md](pipeline/analysis-pipeline-plan.md)「リポジトリ側の構成」が持つ。

写した時点では試験Aの値が見本として残っている箇所がある。そのままでは回らないので、[pipeline/README.md](pipeline/README.md)「試験ごとに書き換えるもの」の挙げるものを自分の一次文書から起こし直す。

受領データから SDTM・ADaM・ARD・図表を作る実装本体と、疾患固有のエンドポイントの計算は枠組みが持たない。試験側が `program/sas/` と `program/r/` に書く。書き方の見本は [examples/](examples/README.md) にある。

### 4.4. 試験固有の値

統計解析責任者が `docs/metadata/trial.json` を埋める。鍵の意味は [templates/README.md](templates/README.md)「trial.json」が持つ。

```bash
cd "$TRIAL" && python3 -c "import sys; sys.path.insert(0, 'scripts'); import boxpath; print(boxpath.trial_id()); print(boxpath.trial_dir())"
```

識別子と試験フォルダが2行で表示されれば、以降のスクリプトが設定を引ける。止まったときは `boxpath.py` がどちらの理由かを示す。鍵が足りなければ要る形を示し、データの置き場が解決できなければ探した場所を並べる。前者は `trial.json` を直し、後者は置き場を用意するか環境変数で場所を指す。

試験の識別子をプログラム・文書・スクリプトへ直接書かない。プログラム名・納品パッケージ名・表題はこの値から組み立てる。組み立ての規則は [pipeline/analysis-pipeline-plan.md](pipeline/analysis-pipeline-plan.md)「命名の規約と既定」が持つ。

### 4.5. 立案時レビュー

統計解析責任者が、集めた資料に立案時レビューを当てる。回す順序・機械検査・指摘の形は [skills/trial-planning-review/](skills/trial-planning-review/SKILL.md) が持ち、判断が要る項目の規則は [review/](review/README.md) の各チェックリストが持つ。

```bash
mkdir -p ~/.claude/skills
cp -r "$FRAMEWORK"/skills/trial-planning-review ~/.claude/skills/
cp -r "$FRAMEWORK"/skills/cdisc-define-xml ~/.claude/skills/
export TRIAL_REVIEW_DIR="$FRAMEWORK/review"
```

写すスキルは2つある。`trial-planning-review` はこの段で使い、`cdisc-define-xml` は後の ADaM の define.xml の生成が読む。立案の段で片方だけ写すと、不足が分かるのは解析に入ってからになる。`TRIAL_REVIEW_DIR` は実行器が方法論を探す場所で、指定が無いときはホーム配下の決め打ちの候補を順に見る。枠組みをそこに置いていない端末では、この変数か `--methods-dir` が無いと検査が1件も回らない。

対象ごとの実施の時期は [review/README.md](review/README.md)「実施の時期」が持つ。研究計画書は倫理審査へ出す前、電子症例報告書は EDC 固定の前、統計解析計画書と図表案は固定の前である。この時期を逃すと以降は改訂手続きになるので、4.1. から 4.4. の完了を待たずに資料の依頼を出す。

資料の依頼はデータセンターへ出す。入手まで日数がかかるため、着手の2週間前には出す。集めた資料が同じ時点のものであることを最初に確かめる。版が食い違うとレビューが無効になる。

機械検査は件数が0でも走ったことを終了コードで確かめる。落ちた場合と0件は出力で区別が付かない。

レビューで見つかった欠陥のうち、この試験に固有でない型は、枠組み側の蓄積（[review/planning-review/findings-log.md](review/planning-review/findings-log.md)・[review/ecrf-review/findings-log.md](review/ecrf-review/findings-log.md)）へ足す。足さないと次の試験で同じ指摘を一から出すことになる。

### 4.6. 固定前の決定

統計解析責任者が、[review/sap-review/upfront-decisions.md](review/sap-review/upfront-decisions.md) の12事項を1つの塊として決め切る。事項の中身・決め方の原則・誰がいつ決めるかはそこが持つ。ここへ写さない。

研究責任医師への医学的判断の照会と、データセンターへの収集の照会は、この段で一括して出す。4.5. の指摘で照会が要るものも同じ便に載せる。

決めた結果の置き場は2つに分かれる。統計解析計画書の本文と、4.2. で配置した機械可読な宣言である。宣言のうち受入基準の3本は実装を見ずに一次文書から起こす。実装ができてから書くと基準が実装の写しになり、二重コーディングの両系統が同じ誤りを共有したときに突合が通る。

決めた事項が統計解析計画書の文言と食い違ったら、改訂するか逸脱として持つかをその場で決める。決めずに置くと、総括報告書の段で一次文書と実装の食い違いとして再浮上する。

### 4.7. 立ち上げの確認

統計解析責任者が、区間1の出口条件を満たしたことを確かめる。条件は [pipeline/analysis-pipeline-plan.md](pipeline/analysis-pipeline-plan.md)「区間1 開始前の確定」が持つ。

あわせて次を見る。

- リポジトリのルートに、設定と生きた文書以外のものが増えていないこと。増えていたら出力先を指定していない箇所を疑う。
- 各段の機械検査が終了コード0で終わったこと。
- 雛形に他の試験の中身が残っていないこと。

この手順で手が止まった箇所は、枠組みの [action-items.md](action-items.md) へ書く。次の試験で同じ場所で止まる。
