# CDISC Analysis Results Standard

作成日：2026-07-21
改訂日：2026-08-29

CDISC ARS（Analysis Results Standard）と、その中核成果物であるARD（Analysis Results Dataset）の調査メモ。試験AでR納品・ARDレベルの内部検証を行うための土台として整理する。新しい知見が出たら本ファイルを更新する。

このプロジェクトでの適用方針は [analysis-pipeline-plan.md](analysis-pipeline-plan.md) を参照。

## ARSとは

ARSは、統計解析の「結果」を機械可読・構造化された形で定義・表現するためのCDISC基盤標準。目的は解析結果データの**自動化・再現性・再利用性・トレーサビリティ**の確保。従来は最終成果物であるTLF（Table/Listing/Figure、＝レイアウト済みの表・図）が事実上の到達点で、そこに至る「どの母集団に・どの統計手法を・どの変数へ適用したか」というメタデータが構造化されていなかった。ARSはこの解析メタデータと結果値を標準モデルとして定義する。

要点は「table-first から data-first へ」。まずレイアウトのない結果データ（ARD）を作り、そこから表・図を描画する。結果データと表示を分離することで、同じ結果を複数の表示に再利用でき、検証も結果データのレベルで機械的に行える。

## 背景と経緯

- ARSはDefine-XMLに含まれていたARM（Analysis Results Metadata）の後継・発展。ARMが「結果の説明メタデータ」だったのに対し、ARSは結果の生成・表現・表示までを1つの論理モデルで扱う。
- CDISCは2024年4月にARS v1をリリース。モデルURIは `https://www.cdisc.org/ars/1-0`。
- 論理モデルはLinkMLで記述され、そこからJSON-Schema・RDF・OWL・SQL DDL等の下流成果物が生成される。したがってモデルはJSON/YAML等にシリアライズでき、システム間交換・LLM連携に向く。

## 論理モデルの構造

中心は `ReportingEvent`。以下、主要クラスと関係。

### ReportingEvent

特定の報告要件（CSR、中間解析など）を満たすために作られる解析とアウトプットの集合を表す根クラス。配下に analyses・outputs・methods・groupings・listOfContents 等を持ち、全体を統括する。

### AnalysisSet と DataSubset

- `AnalysisSet`：主解析に含める被験者集団（プロトコル統計セクションで定義。FAS・ITT・SAF・PPS等）。
- `DataSubset`：集団をさらに絞る条件付き部分集合。
- いずれも `WhereClauseCondition` / `CompoundExpression` で選択ロジックを表現する。ADaMの変数・値域を参照する形になる。

### Analysis と AnalysisMethod と Operation

- `Analysis`：報告要件を満たす個々の解析単位。参照するdataset・variable・AnalysisSet・DataSubset・AnalysisMethod・グルーピングを属性に持つ。
- `AnalysisMethod`：統計操作（Operation）の集合＝手法。
- `Operation`：単一の結果値を生む個々の統計計算。`order` 属性（整数、順序）を持ち、`ReferencedOperationRelationship` で依存計算を連鎖させられる（例：分母→割合）。
- `GroupingFactor`：集団・データを群に分割する因子（治療群、サブグループ等）。

### 結果の表現

- `OperationResult`：結果値。raw値と表示用のformatted値の両方を持つ。
- `ResultGroup`：結果を特定の群の値に紐づける（どの治療群・どのサブグループの結果か）。

### Output と表示

- `Output`：計画された解析に基づく結果とその評価の報告。
- `OutputDisplay`：結果の表形式表現（レイアウト）。
- `ListOfContents`：解析・アウトプットの構造化された目次。
- `ReferenceDocument`：裏付け文書への参照。

関係の要約：ReportingEvent が analyses / outputs / methods / groupings を保持し、各 Analysis が AnalysisSet・DataSubset・AnalysisMethod を参照、AnalysisMethod 内の Operation が結果値を生み、Output/OutputDisplay がそれらを表示に落とす。

## Analysis Results Dataset

ARD（Analysis Results Dataset）は、統計結果を構造化テーブルに保存した実体。**生の統計量・書式化関数・メタデータは持つが、視覚的レイアウトは持たない**。1行が1つの結果値（1 Operation の1 ResultGroup 結果）に対応する縦持ち形式。

R実装（後述）での代表的な列構成：

- `variable` / `variable_level`：解析対象変数とそのカテゴリ
- `stat_name` / `stat_label`：統計量の種類と表示ラベル
- `stat`：結果値。**リストカラム**で数値と文字が同じ列に入る（`fmt_fun`・`warning`・`error` も同様）
- `fmt_fun`：表示用の書式化関数（0.8.x での名称。以前の版は `fmt_fn`。版で変わるので `renv` で固定する）
- `context`：解析文脈（continuous / categorical / missing 等）
- `warning` / `error`：計算時の警告・エラー

この形式は「結果の粒度で機械的にQC・再利用できる」ことが最大の利点。表を作ってから目視で照合するのではなく、結果データフレーム同士を突合すればよい。

## R エコシステムでの実装

ARD中心のワークフローはRのpharmaverse系で実装が進んでおり、R納品と相性が良い。

- **`{cards}`**：ARD生成の中核。`ard_continuous()`（平均・SD・中央値・四分位）、`ard_categorical()`（件数・割合）、`ard_dichotomous()`、`ard_hierarchical()`（SOC内AE項目のような入れ子集計）、`ard_missing()`、`ard_complex()`。formulaインターフェースで任意のユーザー定義統計も適用可能。
- **`{cardx}`**：`{cards}` の拡張。40超の統計手法のARDラッパー（t検定、Cox比例ハザード、混合効果、GEE、生存解析、線形/一般化線形モデル等）。生存解析やハザード比もARD化できる＝EFS/OS/RFSに対応可能。
- **`{gtsummary}`**：ARDから表を描画。既存表からARDを取り出す `gather_ard()` と、ARDから表を組む `tbl_ard_summary()` の両方向。解析（ARD）と表示（表）を分離できる。
- 描画は `{gt}`（HTML/PDF）・`{flextable}`（Word/RTF）へ接続でき、RTF納品にも対応。
- 周辺：Roche系の `{crane}`、業界横断の cARDinal イニシアチブ（TLFのARD標準化）。
- ADaMをRで作る場合は pharmaverse の `{admiral}` 系が使える（SDTM→ADaM）。

## ARDレベルでのcompare

TLF（レイアウト済みの表）レベルの突合は、書式・結合順・セル位置の違いに埋もれて機械化しにくい。ARDは結果値の縦持ちなので、**結果データフレーム同士を直接照合できる**。標準的なQC手順：

1. 一方の系統でARDを生成（または完成表から `gather_ard()` で抽出）。
2. もう一方の系統で同一仕様のARDを独立に再生成。
3. 2つのデータフレームを `waldo::compare()` 等でプログラム的に突合。

これで全統計量・全書式を、表を目視せずに検証できる。ある試験では「R（納品）で作ったARD」と「独立実装（SAS等）で作ったARDに相当する結果値」をこのレベルで突合し、内部検証に用いた（PIには出さない）。突合の鍵は、両系統で `variable` / `stat_name` / `ResultGroup`（群）のキーをそろえること。

## バージョンと参照先

- ARS v1.0（2024-04-19 リリース）。モデルURI `https://www.cdisc.org/ars/1-0`。2026-08-16 時点で後続の改訂は出ていない。
- ARM（Analysis Results Metadata）v1.0 for Define-XML v2.0 は2015年公開。規制当局の扱いは非対称で、FDA は Data Standards Catalog に載せておらず任意、PMDA は主要な有効性・安全性解析について ADaM の定義文書に含めることを強く推奨（別PDFでの提出も可）。ARS はこの ARM の後継・発展。
- `cards` の版は 0.8.1（2026-08-16 確認）。ARD の標準列は `group1`/`group1_level`（複数可）・`variable`・`variable_level`・`context`・`stat_name`・`stat_label`・`stat`・`fmt_fun`・`warning`・`error`。うち `stat`・`fmt_fun`・`warning`・`error` はリストカラム。
- 標準トップ：https://www.cdisc.org/standards/foundational/analysis-results-standard
- モデルドキュメント（LinkML生成）：https://cdisc-org.github.io/analysis-results-standard/
- GitHub：https://github.com/cdisc-org/analysis-results-standard ／ API定義 https://github.com/cdisc-org/analysis-results-standard-api
- R実装解説（{cards}/{gtsummary}）：https://www.danieldsjoberg.com/CDISC-COSA-Spotlight-ARD-gtsummary-2025/slides/

## 一次情報の当たり方

モデルの正本は LinkML の記述であり、GitHub の `cdisc-org/analysis-results-standard` にある。そこから生成されたモデル文書（https://cdisc-org.github.io/analysis-results-standard/ ）がクラスとスロット、必須と任意の別、値の制約（列挙）を持つ。

実装の前に、使うクラスのスロットをここから写し取る。要約や記憶で書かない。本書の 2026-08-16 版が「ARS 準拠かは判定できる問いではない」と書いていたのは、一次情報に当たらずに書いたためである。同じ文書の「主要クラス」に `OperationResult` を挙げておきながら、判断軸の節では結果値の層は規定されていないとしていた。文書の中で矛盾していても、読み返すまで気づかない。

写し取る対象は3つある。クラスごとの必須スロット（`ReportingEvent` は `id`・`name`・`mainListOfContents`、`Analysis` は `id`・`name`・`reason`・`purpose`・`methodId`、`OperationResult` は `operationId`）、列挙の値（`AnalysisPurposeEnum` の3値、`AnalysisReasonEnum` の4値）、そして入れ子の構造である。列挙は綴りまで一致させる。

生成した JSON は、モデルから導かれた JSON-Schema で検証するのが本来である。試験Aでは必須スロットの検査を自前で書くにとどめた。自前の検査は書いた分しか見ないので、これは暫定である。2試験目でスキーマによる検証へ寄せるかを判断する。

版は着手時に確認する。v1.0（2024-04-19）以降の改訂が出ていれば、スロットと列挙を写し直す。API 定義は別リポジトリ（`cdisc-org/analysis-results-standard-api`）にある。

## ARS を採るかどうかの判断軸

2026-08-29 に改めた。それまでここには「標準が規定しているのはメタデータの層だけで、ARD の物理的な列名や型は規定していない。したがって ARS 準拠かは判定できる問いではない」と書いていた。誤りである。ARS v1.0 は `OperationResult` を規定しており、スロットは `operationId`（必須）・`resultGroups`・`rawValue`・`formattedValue` の4つである。上の「主要クラス」に `OperationResult` を挙げておきながら、判断軸の節がそれを無かったことにしていた。準拠かどうかは判定できる問いである。

判定できる問いだと気づかないと、準拠しない選択が既定になる。機械可読な ReportingEvent を「該当する試験だけが作るもの」に分類した時点で、モデルへの準拠は見送られる。判断軸は次のように置き直す。

ARS の考え方（table-first ではなく data-first、結果データと表示の分離、ARD レベルでの突合）は全試験で採る。これは出力形式ではなく設計の骨格であり、採らない理由が無い。

ARS v1.0 のモデルに準拠した機械可読な ReportingEvent を出すかどうかは、次で決める。

- 解析の由来を機械可読な形で受け取る側がいる（規制当局・共同研究者・データ再利用）
- ARS を入力とするツールを使う（ARD を含む JSON から図表を描くもの、メタデータから解析コードを生成するもの、ARD から要約表を作るもの）

出すと決めたときに要る作業は多くない。試験Aの実績では、識別子の体系（解析ID・図表ID・母集団・部分集団・手法ID・操作ID・群と水準・結果値）が既に対応しており、不足していたのは `Analysis` の必須スロットのうち `purpose`（3値から選ぶ）・`reason`（4値から選ぶ）・`name` の3つだけだった。`purpose` と `reason` は解析仕様インデックスの根拠の記述から機械的に決まり、判断が要るものだけを人へ回せばよい。これらは機械可読な CSV を正本にし、人間可読の仕様書からは参照する。

ReportingEvent はパイプラインの部品ではなく、末端から枝分かれする成果物である。

```
受領CSV → SDTM → ADaM → ARD → 図表
                          └→ ReportingEvent（JSON）
```

ARD はパイプラインの一部として残る。図表の材料であり、二重コーディングの突合の主軸でもある。ReportingEvent を読み返す必要は無い。ここを取り違えると「既存の ARD 形式を破棄して生成コードを置き換える」という不要な作業に進む。試験Aでは当初その計画になっていた。

生成は最も組みやすい言語1つで行う。二重コーディングで検証したいのは統計量の値であって直列化ではなく、値の一致は ARD の層で済んでいる。同じ ARD から JSON を組む処理を2つ書いても、新たに検証されるのは直列化のコードだけである。入れ子の深い JSON（ReportingEvent → analyses → results → resultGroups の4階層）を統計処理系の JSON 出力機能で組もうとしない。

ARM を作るかどうかは別の軸で決まる。承認申請に使わない試験では不要で、ARM が要求する情報は解析仕様インデックスが既に持っている。

## 更新履歴

- 2026-08-29：一次情報（GitHub の LinkML モデルと生成されたモデル文書）の当たり方を追記。「ARS 準拠かは判定できる問いではない」という誤りを正し、判断軸を置き直した。試験Aで ARS v1.0 準拠の ReportingEvent を両系統で定常的に作り、その形式で突合して納品へ同梱するところまで実施した実績を反映（解析1,428件・結果値29,259件・図表88件）。ReportingEvent の位置づけ（末端から枝分かれする成果物であってパイプラインの部品ではない）と、生成を1言語に閉じる理由を追記。
- 2026-08-16：ARS v1.0 のリリース日と後続改訂の有無、ARM の規制当局別の扱い、`cards` 0.8.1 の列構成（`fmt_fn` から `fmt_fun` への改称、リストカラム）を確認して更新。ARS・ARM を採るかどうかの判断軸を追記。
- 2026-07-21：初版。ARS v1の論理モデル・ARD・R実装（cards/cardx/gtsummary）・ARDレベルcompareを整理。
