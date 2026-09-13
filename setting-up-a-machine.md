# 端末の用意

作成日：2026-09-14
改訂日：2026-09-14

この枠組みを回す端末を1台立てるための文書。macOS と Windows の両方を扱う。

何が要るかはここが決めるのではなく、[pipeline/scripts/python/check-environment.py](pipeline/scripts/python/check-environment.py) が決める。要るものの一覧をこの文書へ写さないのは、写すと検査と食い違うからである。ここが持つのは入れ方と、その端末でだけ起きることの理由である。立ち上げの手順のどこでこの検査を回すかは [starting-a-new-trial.md](starting-a-new-trial.md)「4.1. リポジトリの骨格」が持つ。

## 1. 端末の役割

立案の端末と、解析を回す実行機に分かれる。1台が兼ねてもよい。SAS を持つのは実行機だけのことが多く、二重コーディングの SAS 系はそちらでしか回らない。どちらの端末で何を回すかは、試験側の `CLAUDE.md` に書く。

どちらの役割でも、その端末に枠組みのクローンを置く。検査そのもの、検査が要求するスキル2つ、立案時レビューが読む `review/` の方法論は、いずれもクローンの中にある。検査のファイルだけを写して回す形にすると、その端末は自分に何が足りないかを自分で答えられず、欠落は本番の実行まで現れない。実行の入口を移した16日後に実行機で初めて回し、5つの不足に一度に突き当たった事例がこれである（[findings/analysis-findings-log.md](findings/analysis-findings-log.md)「実行の入口を移したとき、実行機の側が追随しない」）。

## 2. 両方の OS で共通のもの

枠組みのクローンを置く。

```bash
git clone https://github.com/nnh/trial-planning-and-analysis.git
```

スキル2つを配る。検査はこの2つを必須として見る。片方だけ写すと、不足が分かるのは解析に入ってからになる。

```bash
mkdir -p ~/.claude/skills
cp -r <枠組み>/skills/trial-planning-review <枠組み>/skills/cdisc-define-xml ~/.claude/skills/
```

検査の3本だけが外部パッケージを要る。生成と実行の経路は標準ライブラリで動く（[pipeline/README.md](pipeline/README.md)「実行できる形」）。

```bash
python3 -m pip install jsonschema playwright
python3 -m playwright install chromium
```

CDISC CORE は[リリース](https://github.com/cdisc-org/cdisc-rules-engine/releases)の書庫を `~/opt/cdisc-core` へ展開する（Windows は `%USERPROFILE%\opt\cdisc-core`）。展開すると `core/core.exe` の形になり、検査はその場所を既定として見る。別の場所へ置くなら `CDISC_CORE_EXE` で指す。最新を追わず版を固定して入れる。提出を検証した版をあとで入れ直せるようにするためである。

R の版は試験リポジトリの `renv.lock` が固定する。端末側にその数字を書き写さない。

## 3. macOS

git と make は Xcode のコマンドラインツールが持つ。

```bash
xcode-select --install
```

R は [CRAN の pkg](https://cran.r-project.org/bin/macosx/) で入れる。macOS では make が Xcode 側にあるので、Windows の Rtools にあたるものを別に入れる必要はない。

## 4. Windows

Windows でだけ起きることが3つある。いずれも、入っているのに無いと見える形で現れる。

### 4.1. python3 という名前

Windows は `%LOCALAPPDATA%\Microsoft\WindowsApps` に python.exe と python3.exe という0バイトのストアエイリアスを置く。呼んでも何も起きないまま終了コード0が返るので、`python3` を使う手順はここで黙って素通りする。処理系が名前だけ在って中身が無い端末では、検査自体が何も出さずに0を返す。

エイリアスを外すだけでは直らない。公式インストーラは python.exe しか置かず python3.exe を作らないので、エイリアスを外すと `python3` というコマンド自体が消える。エイリアスを退避し、あわせて実体の隣へ python.exe の複製を python3.exe として置く。エイリアスの退避は設定のアプリ実行エイリアスから戻せる。

### 4.2. R と Rtools

[rig](https://github.com/r-lib/rig) で入れる。

```
winget install --id Posit.rig --exact
rig add <renv.lock が固定する版>
rig default <同じ版>
```

winget から R と Rtools を別々に入れる形は採らない。winget の `RProject.Rtools` は 4.5 系で止まっており、R 4.6 に対応する Rtools を配っていない（2026-09-14 に `winget show --versions` で確認）。この形を採ると、Rtools のインストーラの URL と、R の版に対応する Rtools の版の対応表を自分で持つことになり、R が上がるたびに直す必要が出る。rig は版に対応する Rtools を R と一緒に入れるので、その対応表を持たずに済む。

rig にはもう1つ効き目がある。R の公式インストーラは PATH を通さないため、入っている端末でも `Rscript` が引けず、検査は R が無いと報告する。実際に rinken37 では、前日に入れた R 4.6.1 と Rtools45 が PATH に無く、未導入として記録されていた（2026-09-14 に判明）。rig は `%ProgramFiles%\R\bin` に shim を置いて PATH を通すので、この読み違いが起きない。

R 4.6.1 と Rtools45 の組み合わせでソースからのビルドが通ることは実測してある（bit64 4.8.4 を C のコンパイル込みでビルド）。

### 4.3. バッチの shim を Python から呼ぶとき

rig が PATH へ置く shim は `Rscript.BAT` である。Windows の CreateProcess はバッチファイルを起動できないので、Python の `subprocess` へそのまま渡すと `FileNotFoundError` になる。例外を握り潰す書き方をしていると、R が動く端末で「R が無い」「ビルド道具が無い」と報告される。

枠組みの側はこの作法で書いてある。`runcommon.find_rscript()` は PATH より先に導入先を見て実体の `Rscript.exe` を返し、`check-environment.py` は shim を cmd.exe 経由で起動する。R を呼ぶスクリプトを新しく書くときは `find_rscript()` を使う。

cmd.exe を挟む経路では、引数にダブルクォートを入れない。cmd が引用符を再解釈し、空白を含むパスが別のコマンドとして読まれる。R へ渡す文字列はシングルクォートで書く。

## 5. 端末が起動できる形かの確認

```bash
python3 pipeline/scripts/python/check-environment.py
```

終了コードは3値で、0 が必須充足、1 が必須欠落、2 が検査そのものが走らなかったことを表す。2 を 0 と読まない。`python3` で起動すること自体が 4.1. の回帰テストになる。

必須が欠けていなくても、回せない工程があればそれを挙げる。回せない工程を別の端末で回すなら、どちらの端末で何を回すかを試験側の `CLAUDE.md` に書く。

パッケージの復元まで確かめるなら、試験リポジトリで `renv::restore()` を空回しし、ソースからのビルドになる件数を見る。固定したまま時間が経つとこの件数は増える。Rtools を入れない端末では、Posit Package Manager の日付スナップショットを `repos` に指すと過去版のバイナリが配られる。

## 6. この文書に書かないもの

特定の端末の素性・接続方法・鍵・機器固有の事情は書かない。それは端末を持つ側の環境の文書が持つ。ここが持つのは、どの端末でも同じように要るものと、OS ごとに決まった入れ方だけである。
