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

/* 列の格納長。ここが ARD の各列の幅の正本で、超えた分は SAS が黙って捨てる。切れた値は
   R 系の値と食い違い、突合が落ちるまで気づけない。2026-09-06 に SUBSET を $20 から $40
   へ広げた。2つの治療相をまとめた部分集団の識別子が22文字になり、20文字へ切れて
   analysis-set-condition.csv の宣言と食い違ったためである（識別子そのものも短くした。
   docs/records/decisions-needed-20260901.md の C3-416）。幅は他の識別子の列（ANALYSID・
   OPERATID・GROUP1L の $40）に揃えた。固定データでの実測の最大長は ANALYSID 25・
   OUTPUTID 11・ANALSET 3・GROUP1 7・GROUP1L 26・VARIABLE 49・VARLEVEL 45・LEVELSET 10・
   METHODID 8・OPERATID 15・STATNAME 7・STATLBL 28・CONTEXT 11・SRCVAR 18 である。
   SRCDATA だけは実測267に対し $300 で余裕が33文字しかなく、絞り込みの条件が1つ増えれば
   足りなくなるので同じ日に $400 へ広げた。
   宣言済みの識別子がこの幅に収まることは scripts/check-identifier-length.py が見る。
   同じ列の length 宣言は本ファイルに何度も現れる。1つでも古い幅が残ると、そのマクロを
   通った行だけが切れるので、幅を変えるときは全部を揃える。 */
%macro ard_init;
  data _ard_base;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $40
           GROUP1 $20 GROUP1L $40 VARIABLE $80 VARLEVEL $60 LEVELSET $20
           METHODID $20 OPERATID $40 STATNAME $20 STATLBL $60
           STATTYPE $4 STATC $60 CONTEXT $20 SRCDATA $400 SRCVAR $80;
    call missing(of _all_);
    STAT = .;
    delete;
  run;
%mend ard_init;

/* 結果値の1行ごとに ARS の Operation を紐づけ、数値・文字の別を明示する。
   OPERATID は ard-spec.md の AnalysisMethod と対応し、R系ARDとの突合キーになる。 */
/* 由来（SRCDATA・SRCVAR）は各マクロが %_ardsrc で書いたマクロ変数から写す。
   マクロ引数で渡さないのは、data= が "&sp" のような二重引用符と 'TOTDOSE' のような
   単一引用符を同時に含み、引数の引用が壊れるため。symget で読めば引用を経由しない。 */
%macro ard_stamp(ds, methodid);
  data &ds;
    length METHODID $20 OPERATID $40 STATTYPE $4 SRCDATA $400 SRCVAR $80;
    set &ds;
    METHODID = "&methodid";
    OPERATID = catx('.', METHODID, STATNAME);
    STATTYPE = ifc(not missing(STATC), 'char', 'num');
    SRCDATA = symget('_srcdata');
    SRCVAR  = symget('_srcvar');
  run;
%mend ard_stamp;

/* 由来の記録。結果値がどの入力データセットのどの絞り込みのどの変数から来たかを ARD 自身に
   持たせる（label-and-traceability-stages.md 段階5）。%superq で受けるので & と % は
   再解決されない。data= が作業データセット（_hsct・_mol 等）のときは、呼ぶ側が srcdata=
   で解析の主たる出所を名指しする。中間データの名前から引く対応表は持たない。表はコードが
   既に持つ事実の写しになり、写しは編集のたびにズレる（2026-08-20 の決定。ズレた実例は
   C2-211 の _MNTDS・_FIRST_CMR）。
   名指しの無いまま作業データセットが由来に残ったらその場で止める。黙って通すと、主たる
   出所の分からない解析が ReportingEvent へ混ざる。 */
%macro _ardsrc(d, v);
  %global _srcdata _srcvar;
  %if %length(%superq(d)) = 0 %then %do;
    %put ERROR: [ARD] 解析の由来が空です。;
    %abort cancel;
  %end;
  %else %if %qsubstr(%superq(d), 1, 1) = %str(_) %then %do;
    %put ERROR: [ARD] 解析の主たる出所が作業データセットのままです: %superq(d);
    %put ERROR: [ARD] 呼ぶ側で srcdata= に ADaM・SDTM のデータセットを渡してください。;
    %abort cancel;
  %end;
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

%macro ard_n(data=, analysid=, outputid=, analset=, subset=, variable=, varlevel=,
             srcdata=);
  /* srcdata= を与えると由来をそちらで記録する。data= が作業データセットのときに使う */
  %if %length(%superq(srcdata)) %then %do;
    %_ardsrc(%superq(srcdata), %superq(variable))
  %end;
  %else %do;
    %_ardsrc(%superq(data), %superq(variable))
  %end;
  proc sql noprint;
    create table _t_n as
    select "&analysid" as ANALYSID length=40,
           "&outputid" as OUTPUTID length=20,
           "&analset"  as ANALSET  length=10,
           "&subset"   as SUBSET   length=40,
           ' '         as GROUP1   length=20,
           ' '         as GROUP1L  length=40,
           "&variable" as VARIABLE length=80,
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
  Mth-FREQ カテゴリの頻度と二項95%信頼区間（Clopper-Pearson。ard-spec A-1）
========================================================================================*/

%macro ard_prop(data=, var=, analysid=, outputid=, analset=, subset=, group1=, group1l=,
                levels=, varname=, srcdata=);
  /* varname= を与えると VARIABLE にその値を入れる。同じ変数名（GRBAND 等）で
     多数の項目を回すとき、ARD だけで何を解析したかが分かるようにするため。 */
  %if not %length(&varname) %then %let varname = &var;
  /* srcdata= を与えると由来をそちらで記録する。data= が作業データセットのとき、および
     1つの中間データの中で解析ごとに出所が分かれるとき（Out-5.4.3.1 の評価時点）に使う。
     省略すれば data= がそのまま由来になる */
  %if %length(%superq(srcdata)) %then %do;
    %_ardsrc(%superq(srcdata), %superq(var))
  %end;
  %else %do;
    %_ardsrc(%superq(data), %superq(var))
  %end;
  %local _den _nlv i _ls;
  proc sql noprint;
    select count(*) into :_den trimmed from &data;
  quit;

  /* 水準集合の識別子。levels= に来た並びから引き当てる（出力形式 $lvsetid は ARD.sas が
     level-sets.csv から作る）。事前規定の水準集合であることを ARD 自身に持たせ、ARS では
     GroupingFactor になる。宣言に無い並びは空が返り、その水準はデータ由来の
     VARIABLE-LEVEL として扱われる。位置パラメータで渡すと前後に空白が付くことがある
     ので strip して照合する（%bgfl の呼び出しがこの形）。 */
  %let _ls = ;
  %if %length(%superq(levels)) %then %do;
    %let _ls = %sysfunc(putc(%sysfunc(strip(%superq(levels))), $lvsetid.));
    /* 宣言に無い並び（データ由来の水準）では putc が空を返す。空のまま strip へ渡すと
       「STRIP にある引数は少なすぎます」で落ちる。2026-09-12 に Out-5.4.8 の事象名を
       水準として渡したときに露見した。引き当たったときだけ整える */
    %if %length(%superq(_ls)) %then %let _ls = %sysfunc(strip(%superq(_ls)));
  %end;

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
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $40 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 LEVELSET $20
           STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    set _lv;
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&varname"; VARLEVEL = _lvl; LEVELSET = "&_ls";
    CONTEXT = 'categorical'; STATC = ' ';
    _den = &_den;
    _lcl = ifn(_num = 0,    0, betainv(0.025, _num,     _den - _num + 1));
    _ucl = ifn(_num = _den, 1, betainv(0.975, _num + 1, _den - _num));
    STATNAME = 'n';   STATLBL = 'Count';           STAT = _num;  output;
    STATNAME = 'N';   STATLBL = 'Denominator';               STAT = _den;  output;
    STATNAME = 'p';   STATLBL = 'Percentage';   STAT = 100 * _num / _den; output;
    STATNAME = 'lcl'; STATLBL = '95% CI lower limit'; STAT = 100 * _lcl; output;
    STATNAME = 'ucl'; STATLBL = '95% CI upper limit'; STAT = 100 * _ucl; output;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL LEVELSET
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_p, Mth-FREQ)
  %ardappend(_t_p)
%mend ard_prop;

/*========================================================================================
  Mth-CONT 連続量の要約（SAP 4.3 (1) の全統計量。未決事項 B-1、2026-08-15 確定）
========================================================================================*/

%macro ard_cont(data=, var=, analysid=, outputid=, analset=, subset=, group1=, group1l=,
                varname=, srcdata=);
  %if not %length(&varname) %then %let varname = &var;
  /* srcdata= の意味は %ard_prop と同じ。省略すれば data= がそのまま由来になる */
  %if %length(%superq(srcdata)) %then %do;
    %_ardsrc(%superq(srcdata), %superq(var))
  %end;
  %else %do;
    %_ardsrc(%superq(data), %superq(var))
  %end;
  proc means data=&data noprint;
    var &var;
    output out=_c_out n=_n nmiss=_nmiss mean=_mean std=_sd median=_med
                      q1=_q1 q3=_q3 min=_min max=_max;
  run;

  data _t_c;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $40 GROUP1 $20 GROUP1L $40
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
  Mth-KM Kaplan-Meier（時点CIは Greenwood 分散の log-log 変換、中央値CIは Brookmeyer-Crowley）
========================================================================================*/

%macro ard_km(data=, where=1, paramcd=, analysid=, outputid=, analset=, subset=,
              tpset=LS_YR5, group1=, group1l=);
  /* 指定時点は事前規定の水準集合が持つ。年の値そのものはこのマクロに書かず、集合の水準
     （Y<年>）から %_yrlist が取り出す。ARD の LEVELSET には同じ集合の識別子を入れるので、
     ARS では時点が1つの GroupingFactor になり、宣言と実装のずれは build-ars-json.py が
     捕まえる（ard-spec.md「グルーピング因子」）。 */
  %local timelist;
  %let timelist = %_yrlist(&tpset);
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
     信頼限界を持たない）。CONFTYPE=LOGLOG により Greenwood の分散に log(-log(S)) を
     当てた区間になる。2026-09-12 に統計解析責任者の判断で線形形式から改めた
     （docs/decisions/data-handling-decisions.md「Kaplan-Meier の時点信頼区間の形式」）。 */
  ods select none;
  ods output Quartiles             = _qt
             CensoredSummary       = _cs
             ProductLimitEstimates = _ple;
  proc lifetest data=_km method=km conftype=loglog alpha=0.05
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
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $40 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 LEVELSET $20
           STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    set _osx;
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&paramcd"; CONTEXT = 'survival'; STATC = ' ';
    VARLEVEL = cats('Y', put(TIMELIST, best8.)); LEVELSET = "&tpset";
    STATNAME = 'surv'; STATLBL = 'Survival probability';              STAT = SURVIVAL; output;
    STATNAME = 'se';   STATLBL = 'Standard error';              STAT = STDERR;   output;
    STATNAME = 'lcl';  STATLBL = '95% CI lower limit';    STAT = SDF_LCL;  output;
    STATNAME = 'ucl';  STATLBL = '95% CI upper limit';    STAT = SDF_UCL;  output;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL LEVELSET
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_km1, Mth-KM)
  %ardappend(_t_km1)

  /* 生存曲線。Mth-KM の定義（ard-spec.md）は「生存曲線」を先頭に挙げており、
     指定時点の値だけでは定義を満たさない。全イベント時点の推定値・信頼限界・リスク集合数・
     打ち切り数を持たせる（2026-08-29。records/ars-migration-20260829.md の第3段）。図はこれを読んで
     描くので、図の値も突合の対象になる。

     材料は2つ要る。outsurv は信頼限界を持つが Left（リスク集合数）を持たず、
     ProductLimitEstimates は Left・Failed・Censor を持つが信頼限界を持たない。時点で結合する。
     timelist と reduceout を付けると指定時点だけに畳まれるため、曲線用は付けずに回す。

     VARLEVEL には時点を `T<年>` の形で入れる。指定時点は `Y<年>` なので混ざらない。 */
  ods select none;
  ods output ProductLimitEstimates = _plec;
  /* plots= を書くと ODS graphics が無効な状態で「有効にせよ」という WARNING が出る。
     図はここでは要らない（%fig_km が別に描く）ので plots= 自体を書かない。 */
  proc lifetest data=_km method=km conftype=loglog alpha=0.05 outsurv=_curve;
    time AVALY * CNSR(1);
  run;
  ods select all;

  /* 同一時点に複数の被験者がいると、どちらのデータセットも1時点に複数行を返す。
     outsurv は打ち切りと死亡で行が分かれ、ProductLimitEstimates は被験者ごとに行が出る。
     時点を突合キーにするので、時点ごとに1行へ畳む。畳み方は、リスク集合数はその時点に
     入った時点での人数（最大）、打ち切り数は合計、生存割合と信頼限界はその時点の最終値
     （階段の右端）を採る。 */
  proc sort data=_curve out=_curve1; by AVALY; run;
  data _curve2;
    set _curve1; by AVALY;
    /* SAS は打ち切りだけの時点で SURVIVAL・SDF_LCL・SDF_UCL を空にする。R の survfit は
       直前の推定値を保つ。KM は階段関数なので、イベントが無ければ推定値は変わらないという
       R の扱いが正しい。直前の値で埋めて定義を揃える（2026-08-29）。 */
    /* SURVIVAL と SDF_LCL は欠測になる条件が違う。打ち切りだけの時点は SURVIVAL も空だが、
       生存割合が1の区間などは SURVIVAL に値があって信頼限界だけが空になる。
       まとめて分岐すると後者で信頼限界が更新されず空のまま残るので、変数ごとに見る。 */
    retain _s _l _u;
    if not missing(SURVIVAL) then _s = SURVIVAL; else SURVIVAL = _s;
    if not missing(SDF_LCL)  then _l = SDF_LCL;  else SDF_LCL  = _l;
    if not missing(SDF_UCL)  then _u = SDF_UCL;  else SDF_UCL  = _u;
    if last.AVALY;              /* その時点の最終値が階段の右端 */
    drop _s _l _u;
  run;
  /* リスク集合数の定義を R の survfit$n.risk に揃える。PROC LIFETEST の Left は
     「その時点を処理した後の残り人数」だが、at risk table が示すのは「その時点で
     リスクに晒されている人数」＝処理前の人数である。時点ごとに畳んだうえで、
     その時点のイベント数と打ち切り数を戻して処理前の値にする（2026-08-29）。 */
  data _plecd;
    set _plec;
    by AVALY;
    retain _prevf 0;
    if _n_ = 1 then _prevf = 0;
    _fd = Failed - _prevf;          /* その時点のイベント数（Failed は累積） */
    _prevf = Failed;
    _cd = coalesce(Censor, 0);
    keep AVALY Left _fd _cd;
  run;

  proc sql;
    create table _plec2 as
    select AVALY,
           min(Left) + sum(_fd) + sum(_cd) as Left,   /* 処理前のリスク集合数 */
           sum(_cd) as Censor
    from _plecd group by AVALY;
  quit;

  data _t_km4;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $40 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    merge _curve2(in=a) _plec2;
    by AVALY;
    /* 時点0（起点）は outsurv が出すが R の survfit$time は最初のイベント時点から始まる。
       起点の生存割合が1であることは推定結果ではなく定義なので、曲線の結果値には含めない。
       描画で起点から線を引くのは表示側の仕事である（2026-08-29）。 */
    if a and AVALY > 0;
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&paramcd"; CONTEXT = 'survival'; STATC = ' ';
    /* 時点は突合キーになるので、両系統で同じ文字列になる書式に固定する。
       SAS の best12. と R の format は既定の桁が違い、同じ値でも別の文字列を作る。
       日単位の元データを 365.25 で割った値なので、小数第6位（約0.03秒）で足りる。 */
    VARLEVEL = cats('T', put(round(AVALY, 1e-6), 12.6));
    STATNAME = 'time';    STATLBL = 'Time (years)';         STAT = AVALY;    output;
    STATNAME = 'surv';    STATLBL = 'Survival probability'; STAT = SURVIVAL; output;
    /* 直前値で埋めてあるので欠測で分岐しない。分岐すると打ち切りだけの時点で
       lcl・ucl の行が落ち、R 側とキーの集合がずれる（2026-08-29）。 */
    STATNAME = 'lcl';     STATLBL = '95% CI lower limit';   STAT = SDF_LCL;  output;
    STATNAME = 'ucl';     STATLBL = '95% CI upper limit';   STAT = SDF_UCL;  output;
    STATNAME = 'atrisk';  STATLBL = 'Number at risk';       STAT = Left;     output;
    STATNAME = 'ncensor'; STATLBL = 'Number censored';      STAT = Censor;   output;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_km4, Mth-KM)
  %ardappend(_t_km4)

  /* 中央値（Brookmeyer and Crowley 法の95%CI） */
  data _t_km2;
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $40 GROUP1 $20 GROUP1L $40
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
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $40 GROUP1 $20 GROUP1L $40
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
               tpset=LS_YR5, group1=, group1l=);
  /* 指定時点の出どころは %ard_km と同じ（水準集合 &tpset）。年の値をここに書かない */
  %local timelist;
  %let timelist = %_yrlist(&tpset);
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
    length ANALYSID $40 OUTPUTID $20 ANALSET $10 SUBSET $40 GROUP1 $20 GROUP1L $40
           VARIABLE $80 VARLEVEL $60 LEVELSET $20
           STATNAME $20 STATLBL $60 STATC $60 CONTEXT $20;
    set _cifest end=_last;
    ANALYSID = "&analysid"; OUTPUTID = "&outputid"; ANALSET = "&analset";
    SUBSET = "&subset"; GROUP1 = "&group1"; GROUP1L = "&group1l";
    VARIABLE = "&paramcd"; CONTEXT = 'cuminc'; STATC = ' ';
    VARLEVEL = cats('Y', put(Timelist, best8.)); LEVELSET = "&tpset";
    STATNAME = 'cif'; STATLBL = 'Cumulative incidence';           STAT = CIF;         output;
    STATNAME = 'se';  STATLBL = 'Standard error';             STAT = StdErr;      output;
    STATNAME = 'lcl'; STATLBL = '95% CI lower limit';   STAT = CIF_LCL;     output;
    STATNAME = 'ucl'; STATLBL = '95% CI upper limit';   STAT = CIF_UCL;     output;
    if _last then do;
      /* 時点を持たない行は水準集合にも属さない。集合だけが残ると build-ars-json.py が
         「level_set があるのに variable_level が空」で止める */
      VARLEVEL = ' '; LEVELSET = ' ';
      STATNAME = 'N';       STATLBL = 'Number of subjects';   STAT = &_n;  output;
      STATNAME = 'nevent';  STATLBL = 'Number of events'; STAT = &_ne; output;
      STATNAME = 'ncompet'; STATLBL = 'Number of competing events'; STAT = &_nc; output;
    end;
    keep ANALYSID OUTPUTID ANALSET SUBSET GROUP1 GROUP1L VARIABLE VARLEVEL LEVELSET
         STATNAME STATLBL STAT STATC CONTEXT;
  run;
  %ard_stamp(_t_cif, Mth-CIF)
  %ardappend(_t_cif)
%mend ard_cif;

/*========================================================================================
  背景表の行を並べる補助（Out-5.2.1・5.2.2・5.2.4 が同じ行項目を共有する）
  ANALYSID の連番が表の行順になる。行の日本語ラベルは TLF 側の $bgitem が持つ。
========================================================================================*/

%macro bg_init(data=, oid=, aset=, subset=, srcdata=);
  %global _bgds _bgoid _bgaset _bgsub _bgk _bgsrc;
  %let _bgds   = &data;
  %let _bgoid  = &oid;
  %let _bgaset = &aset;
  %let _bgsub  = &subset;
  %let _bgk    = 0;
  /* 背景表の行はすべて同じ中間データを分母にするので、解析の主たる出所も表ごとに1つ。
     ここで名指しした値を %bgc・%bgf・%bgfl が srcdata= へ渡す */
  %let _bgsrc  = &srcdata;
%mend bg_init;

/* where= を渡すと、その行項目だけ分母を絞る。使わなかった薬剤の空レコードが欠測として
   数えられる項目があり、そこでは測定の欠落ではなく投与そのものが無い（C2-042） */
%macro bgc(v, where=);
  %let _bgk = %eval(&_bgk + 1);
  %ard_cont(data=&_bgds%if %length(&where) %then (where=(&where));, var=&v,
            analysid=An-&_bgoid-%sysfunc(putn(&_bgk, z2.)), outputid=Out-&_bgoid,
            analset=&_bgaset, subset=&_bgsub, group1=, group1l=, srcdata=&_bgsrc)
%mend bgc;

%macro bgf(v);
  %let _bgk = %eval(&_bgk + 1);
  %ard_prop(data=&_bgds, var=&v,
            analysid=An-&_bgoid-%sysfunc(putn(&_bgk, z2.)), outputid=Out-&_bgoid,
            analset=&_bgaset, subset=&_bgsub, group1=, group1l=, srcdata=&_bgsrc)
%mend bgf;

/* 水準を明示する版。該当0の水準も行を残す（0例であることが結果の行） */
%macro bgfl(v, levels);
  %let _bgk = %eval(&_bgk + 1);
  %ard_prop(data=&_bgds, var=&v, levels=&levels,
            analysid=An-&_bgoid-%sysfunc(putn(&_bgk, z2.)), outputid=Out-&_bgoid,
            analset=&_bgaset, subset=&_bgsub, group1=, group1l=, srcdata=&_bgsrc)
%mend bgfl;

/* 背景表の行項目の並びは試験ごとに違うので、ここには置かない。
   試験リポジトリの <試験ID>_ARD.sas か、そこから %include する場所で
   %bgc・%bgf・%bgfl を並べてマクロに括る。書き方の見本は
   examples/background-table.sas。

   ここが持つのは部品（%bg_init・%bgc・%bgf・%bgfl）までである。
   並びを汎用層へ置くと、次の試験で枠組みを使う人が、どこを書き換えて
   よいのか分からなくなる（2026-08-22 の独立レビューの指摘）。 */
