/*****************************************************************************************
program name : ard_ops.sas
description  : ARD を作る Operation（統計手法）のマクロ。図表の定義からは独立させる。
usage        : <試験ID>_ARD.sas から %include する。
comment      : 図表ごとにプログラムを分けず、手法（本ファイル）と図表の宣言（ARD本体）の
               2層に分ける。集団の絞り込み・丸め・信頼区間の求め方が1か所に閉じるため、
               図表が増えても定義がずれない。ARD の列構成は cdisc-ars.md の R 実装
               （cards）に合わせてあり、ANALYSID・VARIABLE・VARLEVEL・GROUP1・GROUP1L・
               STATNAME をキーに両系統の ARD を突合できる。
*****************************************************************************************/

/*========================================================================================
  ARD の器と追加
========================================================================================*/

%macro ard_init;
  data _ard_base;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $20
           GROUP1 $20 GROUP1L $40 VARIABLE $80 VARLEVEL $60
           METHODID $20 OPERATID $40 STATNAME $20 STATLBL $60
           STATTYPE $4 STATC $60 CONTEXT $20 SRCDATA $300 SRCVAR $80;
    call missing(of _all_);
    STAT = .;
    delete;
  run;
%mend ard_init;

/* 結果値の1行ごとに ARS の Operation を紐づけ、数値・文字の別を明示する。
   OPERATID は ars-spec-index.md の AnalysisMethod と対応し、R系ARDとの突合キーになる。 */
/* 由来（SRCDATA・SRCVAR）は各マクロが %_ardsrc で書いたマクロ変数から写す。
   マクロ引数で渡さないのは、data= が "&sp" のような二重引用符と 'TOTDOSE' のような
   単一引用符を同時に含み、引数の引用が壊れるため。symget で読めば引用を経由しない。 */
%macro ard_stamp(ds, methodid);
  data &ds;
    length METHODID $20 OPERATID $40 STATTYPE $4 SRCDATA $300 SRCVAR $80;
    set &ds;
    METHODID = "&methodid";
    OPERATID = catx('.', METHODID, STATNAME);
    STATTYPE = ifc(not missing(STATC), 'char', 'num');
    SRCDATA = symget('_srcdata');
    SRCVAR  = symget('_srcvar');
  run;
%mend ard_stamp;

/* 由来の記録。結果値がどの入力データセットのどの絞り込みのどの変数から来たかを ARD 自身に
   持たせる（label-and-traceability-design.md 段階5）。%superq で受けるので & と % は
   再解決されない。data= が作業データセット（_hsct・_mol 等）のときは、そこから ADaM へ
   遡る1段は索引側で別に持つ必要がある。 */
%macro _ardsrc(d, v);
  %global _srcdata _srcvar;
  %let _srcdata = %superq(d);
  %let _srcvar  = %superq(v);
%mend _ardsrc;

%macro ardappend(ds);
  data _ard_base;
    set _ard_base &ds;
  run;
%mend ardappend;

/*========================================================================================
  Mth-N 例数
========================================================================================*/

%macro ard_n(data=, analysid=, outputid=, analset=, subset=, variable=, varlevel=);
  %_ardsrc(%superq(data), %superq(variable))
  proc sql noprint;
    create table _t_n as
    select "&analysid" as ANALYSID length=40,
           "&outputid" as OUTPUTID length=20,
           "&analset"  as ANALSET  length=10,
           "&subset"   as SUBSET   length=20,
           ' '         as GROUP1   length=20,
           ' '         as GROUP1L  length=40,
           "&variable" as VARIABLE length=40,
           "&varlevel" as VARLEVEL length=60,
           'n'         as STATNAME length=20,
           'Number of observations'      as STATLBL  length=60,
           count(*)    as STAT,
           ' '         as STATC    length=60,
           'count'     as CONTEXT  length=20
    from &data;
  quit;
  %ard_stamp(_t_n, Mth-N)
  %ardappend(_t_n)
%mend ard_n;

/*========================================================================================
  Mth-FREQ カテゴリの頻度と二項95%信頼区間（Clopper-Pearson。ars-spec-index A-1）
========================================================================================*/

%macro ard_prop(data=, var=, analysid=, outputid=, analset=, subset=, group1=, group1l=,
                levels=, varname=);
  /* varname= を与えると VARIABLE にその値を入れる。同じ変数名（GRBAND 等）で
     多数の項目を回すとき、ARD だけで何を解析したかが分かるようにするため。 */
  %if not %length(&varname) %then %let varname = &var;
  %_ardsrc(%superq(data), %superq(var))
  %local _den _nlv i;
  proc sql noprint;
    select count(*) into :_den trimmed from &data;
  quit;

  proc sql;
    create table _lv0 as
    select &var as _lvl length=60, count(*) as _num
    from &data where not missing(&var) group by &var;
  quit;

  /* levels= を与えた水準は該当0でも行を残す。0例であることが結果である行
     （早期死亡・その他TKI使用例など）が表から消えないようにするため。 */
  %if %length(&levels) %then %do;
    data _lvall;
      length _lvl $60;
      %do i = 1 %to %sysfunc(countw(&levels, |));
        _lvl = "%scan(&levels, &i, |)"; output;
      %end;
    run;
    proc sort data=_lvall; by _lvl; run;
    proc sort data=_lv0;   by _lvl; run;
    data _lv;
      merge _lvall(in=a) _lv0(in=b);
      by _lvl;
      if a;
      if not b then _num = 0;
    run;
  %end;
  %else %do;
    data _lv; set _lv0; run;
  %end;

  proc sql noprint; select count(*) into :_nlv trimmed from _lv; quit;
  %if &_nlv = 0 or &_den = 0 %then %do;
    %put WARNING: [ARD] &analysid. / &var. は水準または分母が0のため出力しない;
    %return;
  %end;

  /* Clopper-Pearson（正確法）。x=0 のとき下限0、x=n のとき上限1 */
  data _t_p;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $20 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    set _lv;
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&varname"; VARLEVEL = _lvl; CONTEXT = 'categorical'; STATC = ' ';
    _den = &_den;
    _lcl = ifn(_num = 0,    0, betainv(0.025, _num,     _den - _num + 1));
    _ucl = ifn(_num = _den, 1, betainv(0.975, _num + 1, _den - _num));
    STATNAME = 'n';   STATLBL = 'Count';           STAT = _num;  output;
    STATNAME = 'N';   STATLBL = 'Denominator';               STAT = _den;  output;
    STATNAME = 'p';   STATLBL = 'Percentage';   STAT = 100 * _num / _den; output;
    STATNAME = 'lcl'; STATLBL = '95% CI lower limit'; STAT = 100 * _lcl; output;
    STATNAME = 'ucl'; STATLBL = '95% CI upper limit'; STAT = 100 * _ucl; output;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_p, Mth-FREQ)
  %ardappend(_t_p)
%mend ard_prop;

/*========================================================================================
  Mth-CONT 連続量の要約（SAP 4.3 (1) の全統計量。未決事項 B-1、2026-08-15 確定）
========================================================================================*/

%macro ard_cont(data=, var=, analysid=, outputid=, analset=, subset=, group1=, group1l=,
                varname=);
  %if not %length(&varname) %then %let varname = &var;
  %_ardsrc(%superq(data), %superq(var))
  proc means data=&data noprint;
    var &var;
    output out=_c_out n=_n nmiss=_nmiss mean=_mean std=_sd median=_med
                      q1=_q1 q3=_q3 min=_min max=_max;
  run;

  data _t_c;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $20 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    set _c_out;
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&varname"; VARLEVEL = ' '; CONTEXT = 'continuous'; STATC = ' ';
    STATNAME = 'n';      STATLBL = 'Number of observations';             STAT = _n;     output;
    STATNAME = 'nmiss';  STATLBL = 'Number of missing values';         STAT = _nmiss; output;
    STATNAME = 'mean';   STATLBL = 'Mean';           STAT = _mean;  output;
    STATNAME = 'sd';     STATLBL = 'Standard deviation';         STAT = _sd;    output;
    STATNAME = 'median'; STATLBL = 'Median';           STAT = _med;   output;
    STATNAME = 'q1';     STATLBL = '25th percentile';   STAT = _q1;    output;
    STATNAME = 'q3';     STATLBL = '75th percentile';   STAT = _q3;    output;
    STATNAME = 'min';    STATLBL = 'Minimum';           STAT = _min;   output;
    STATNAME = 'max';    STATLBL = 'Maximum';           STAT = _max;   output;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_c, Mth-CONT)
  %ardappend(_t_c)
%mend ard_cont;

/*========================================================================================
  Mth-KM Kaplan-Meier（時点CIは Greenwood 線形形式、中央値CIは Brookmeyer-Crowley）
========================================================================================*/

%macro ard_km(data=, where=1, paramcd=, analysid=, outputid=, analset=, subset=,
              timelist=1 2 3 4 5, group1=, group1l=);
  /* PARAMCD= を位置引数に入れると keyword parameter と解釈されるため %let で組む */
  %global _srcdata _srcvar;
  %let _srcdata = %superq(data)(where=(%superq(where) and PARAMCD=%str(%')&paramcd%str(%')));
  %let _srcvar  = AVAL CNSR;
  data _km;
    set &data;
    if (&where) and PARAMCD = "&paramcd";
    AVALY = AVAL / 365.25;   /* SAP 3.3.3 6)：365.25日を1年とする */
  run;

  /* 時点の生存割合と95%信頼区間は outsurv から取る（ProductLimitEstimates は
     信頼限界を持たない）。CONFTYPE=LINEAR により Greenwood の分散をそのまま用いる
     線形形式になる。ars-spec-index.md 未決事項 A-2 の確定に従う。                     */
  ods select none;
  ods output Quartiles             = _qt
             CensoredSummary       = _cs
             ProductLimitEstimates = _ple;
  proc lifetest data=_km method=km conftype=linear alpha=0.05
                timelist=&timelist reduceout plots=none outsurv=_os;
    time AVALY * CNSR(1);
  run;
  ods select all;

  /* 信頼限界は outsurv、標準誤差は ProductLimitEstimates が持つため時点で結合する */
  proc sort data=_os(where=(not missing(TIMELIST))) out=_os2; by TIMELIST; run;
  proc sort data=_ple(keep=Timelist StdErr rename=(Timelist=TIMELIST)) out=_ple2; by TIMELIST; run;

  data _osx;
    merge _os2(in=a) _ple2;
    by TIMELIST;
    if a;
  run;

  data _t_km1;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $20 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    set _osx;
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&paramcd"; CONTEXT = 'survival'; STATC = ' ';
    VARLEVEL = cats('Y', put(TIMELIST, best8.));
    STATNAME = 'surv'; STATLBL = 'Survival probability';              STAT = SURVIVAL; output;
    STATNAME = 'se';   STATLBL = 'Standard error';              STAT = STDERR;   output;
    STATNAME = 'lcl';  STATLBL = '95% CI lower limit';    STAT = SDF_LCL;  output;
    STATNAME = 'ucl';  STATLBL = '95% CI upper limit';    STAT = SDF_UCL;  output;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_km1, Mth-KM)
  %ardappend(_t_km1)

  /* 中央値（Brookmeyer and Crowley 法の95%CI） */
  data _t_km2;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $20 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    set _qt(where=(Percent = 50));
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&paramcd"; VARLEVEL = 'MEDIAN'; CONTEXT = 'survival'; STATC = ' ';
    STATNAME = 'median'; STATLBL = 'Median survival time (years)';   STAT = Estimate;   output;
    STATNAME = 'lcl';    STATLBL = '95% CI lower limit';   STAT = LowerLimit; output;
    STATNAME = 'ucl';    STATLBL = '95% CI upper limit';   STAT = UpperLimit; output;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_km2, Mth-KM)
  %ardappend(_t_km2)

  /* 例数・イベント数・打ち切り数 */
  data _t_km3;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $20 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    set _cs;   /* 層別していないため1行のみ */
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&paramcd"; VARLEVEL = ' '; CONTEXT = 'survival'; STATC = ' ';
    STATNAME = 'N';       STATLBL = 'Number of subjects';   STAT = Total;    output;
    STATNAME = 'nevent';  STATLBL = 'Number of events'; STAT = Failed;   output;
    STATNAME = 'ncensor'; STATLBL = 'Number censored'; STAT = Censored; output;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_km3, Mth-KM)
  %ardappend(_t_km3)
%mend ard_km;

/*========================================================================================
  Mth-CIF 競合リスクの累積発生率（SAP 4.4.10）
  イベントを 1、競合事象を 2、打ち切りを 0 として PROC LIFETEST の EVENTCODE= で求める。
  Aalen-Johansen 推定（Gray 法と同じ推定量）。信頼区間は log-log 変換で求める。
========================================================================================*/

%macro ard_cif(data=, where=1, paramcd=, evtdesc=, cmpdesc=,
               analysid=, outputid=, analset=, subset=,
               timelist=1 2 3 4 5, group1=, group1l=);
  %global _srcdata _srcvar;
  %let _srcdata = %superq(data)(where=(%superq(where) and PARAMCD=%str(%')&paramcd%str(%')));
  %let _srcvar  = AVAL CNSR EVNTDESC;
  data _ci;
    set &data;
    if (&where) and PARAMCD = "&paramcd";
    AVALY = AVAL / 365.25;                 /* SAP 3.3.3 6)：365.25日を1年とする */
         if EVNTDESC = "&evtdesc" then _evt = 1;   /* 対象イベント */
    else if EVNTDESC = "&cmpdesc" then _evt = 2;   /* 競合事象 */
    else                               _evt = 0;   /* 打ち切り */
  run;

  ods select none;
  ods output CIF = _cifest;
  proc lifetest data=_ci plots=none timelist=&timelist reduceout conftype=loglog alpha=0.05;
    time AVALY * _evt(0) / eventcode=1;
  run;
  ods select all;

  /* 例数・イベント数・競合数 */
  %local _n _ne _nc;
  proc sql noprint;
    select count(*)          into :_n  trimmed from _ci;
    select sum(_evt = 1)     into :_ne trimmed from _ci;
    select sum(_evt = 2)     into :_nc trimmed from _ci;
  quit;

  data _t_cif;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $20 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    set _cifest end=_last;
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&paramcd"; CONTEXT = 'cuminc'; STATC = ' ';
    VARLEVEL = cats('Y', put(Timelist, best8.));
    STATNAME = 'cif'; STATLBL = 'Cumulative incidence';           STAT = CIF;         output;
    STATNAME = 'se';  STATLBL = 'Standard error';             STAT = StdErr;      output;
    STATNAME = 'lcl'; STATLBL = '95% CI lower limit';   STAT = CIF_LCL;     output;
    STATNAME = 'ucl'; STATLBL = '95% CI upper limit';   STAT = CIF_UCL;     output;
    if _last then do;
      VARLEVEL = ' ';
      STATNAME = 'N';       STATLBL = 'Number of subjects';   STAT = &_n;  output;
      STATNAME = 'nevent';  STATLBL = 'Number of events'; STAT = &_ne; output;
      STATNAME = 'ncompet'; STATLBL = 'Number of competing events'; STAT = &_nc; output;
    end;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_cif, Mth-CIF)
  %ardappend(_t_cif)
%mend ard_cif;

/*========================================================================================
  背景表の行を並べる補助（Out-5.2.1・5.2.2・5.2.4 が同じ行項目を共有する）
  ANALYSID の連番が表の行順になる。行の日本語ラベルは TLF 側の $bgitem が持つ。
========================================================================================*/

%macro bg_init(data=, oid=, aset=, subset=);
  %global _bgds _bgoid _bgaset _bgsub _bgk;
  %let _bgds   = &data;
  %let _bgoid  = &oid;
  %let _bgaset = &aset;
  %let _bgsub  = &subset;
  %let _bgk    = 0;
%mend bg_init;

%macro bgc(v);
  %let _bgk = %eval(&_bgk + 1);
  %ard_cont(data=&_bgds, var=&v,
            analysid=An-&_bgoid-%sysfunc(putn(&_bgk, z2.)), outputid=Out-&_bgoid,
            analset=&_bgaset, subset=&_bgsub, group1=, group1l=)
%mend bgc;

%macro bgf(v);
  %let _bgk = %eval(&_bgk + 1);
  %ard_prop(data=&_bgds, var=&v,
            analysid=An-&_bgoid-%sysfunc(putn(&_bgk, z2.)), outputid=Out-&_bgoid,
            analset=&_bgaset, subset=&_bgsub, group1=, group1l=)
%mend bgf;

/* 水準を明示する版。該当0の水準も行を残す（0例であることが結果の行） */
%macro bgfl(v, levels);
  %let _bgk = %eval(&_bgk + 1);
  %ard_prop(data=&_bgds, var=&v, levels=&levels,
            analysid=An-&_bgoid-%sysfunc(putn(&_bgk, z2.)), outputid=Out-&_bgoid,
            analset=&_bgaset, subset=&_bgsub, group1=, group1l=)
%mend bgfl;

/* 背景表の行項目の並びは試験ごとに違うので、ここには置かない。
   試験リポジトリの <試験ID>_ARD.sas か、そこから %include する場所で
   %bgc・%bgf・%bgfl を並べてマクロに括る。書き方の見本は
   examples/background-table.sas。

   ここが持つのは部品（%bg_init・%bgc・%bgf・%bgfl）までである。
   並びを汎用層へ置くと、次の試験で枠組みを使う人が、どこを書き換えて
   よいのか分からなくなる（2026-08-22 の独立レビューの指摘）。 */
