/* ---------------------------------------------------------------------------------
   background-table.sas — 背景表の行項目の並びの例

   これは見本であって、そのままでは動かない。自分の試験の変数名で書き換えて、
   試験リポジトリの <試験ID>_ARD.sas か、そこから %include する場所へ置く。

   部品（%bg_init・%bgc・%bgf・%bgfl）は pipeline/scripts/sas/ard_ops.sas が持つ。
   部品は触らずに使い、並びだけを試験ごとに書く。

   使い方
     %bg_init(ds=..., oid=5.2.1, aset=AS-FAS, subset=)   /* 表ごとに1度 */
     %bg_common                                          /* 行項目を並べる */

   %bgc  連続量。要約統計量（n・平均・標準偏差・中央値・最小・最大）を出す
   %bgf  カテゴリ。実データに現れた水準だけを出す
   %bgfl 水準を明示するカテゴリ。該当0の水準も行を残す（0例であることが結果の行）

   同じ行項目を複数の表で使う場合は、下のようにマクロへ括ると並びが1箇所で済む。
   解析IDは %bg_init からの通し番号で自動採番されるので、並べ替えると番号が変わる。
   表番号との対応は図表の宣言（tlf-index.csv）が持つので、ここでは順序だけを決める。
   --------------------------------------------------------------------------------- */

/* 複数の背景表で共通する行項目。下は血液腫瘍の試験を想定した例である。
   人口統計・血算・生化学・骨髄所見・免疫表現型・染色体・併存疾患の順に並べてある。 */
%macro bg_common;
  /* 人口統計と全身状態 */
  %bgc(AGE)      %bgf(AGEGR1)   %bgf(SEX)      %bgf(PSC)

  /* 血算と生化学。診断時（ベースライン）の値 */
  %bgc(WBCBL)    %bgf(WBCGR1)   %bgc(HGBBL)    %bgc(PLTBL)
  %bgc(LDHBL)    %bgc(CRPBL)

  /* 骨髄所見 */
  %bgc(NUCCEBL)  %bgf(CELLBL)   %bgc(MYBLBL)   %bgc(BLSTBL)

  /* 免疫表現型。陽性・陰性の2値 */
  %bgf(CD20BL)   %bgf(CD13BL)   %bgf(CD33BL)   %bgf(CD34BL)

  /* 染色体所見と付加異常 */
  %bgf(KARYO)    %bgf(ADDER22)  %bgf(ADMNS7)   %bgf(ADPLS8)

  /* 疾患固有のサブタイプと定量値。ここが試験ごとに最も変わる */
  %bgf(SUBTYPE)  %bgc(MRDBL)

  /* 病変の広がり */
  %bgf(CNSGR)    %bgf(EXTRAMED)

  /* 併存疾患・前治療の有無。フラグ変数 */
  %bgf(CMPHTNFL) %bgf(CMPDMFL)  %bgf(CMPDICFL) %bgf(CMPINFFL)
%mend bg_common;

/* 水準を明示する例。実データに1例も無い水準でも行を残したいときに使う。
   全身状態のように、規定された水準がすべて表に並ぶべきものが該当する。 */
%macro bg_ps_example;
  %bgfl(PSC, %str(0|1|2|3|4))
%mend bg_ps_example;
