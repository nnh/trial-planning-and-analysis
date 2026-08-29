/*****************************************************************************************
program name : tlf_ops.sas
description  : ARD から図表を描画する表示マクロ。図表の並びは TLF 本体が宣言する。
usage        : <試験ID>_TLF.sas から %include する。
comment      : 入力は ard.ard だけにする（data-first）。同じ結果値を複数の表示に使い回せる。
               図（Kaplan-Meier 曲線）のみ ads.adtte を直接使う。ARD は報告する統計量を
               持つが曲線の全点は持たないため。
               表示桁は SAP 3.3.2（割合は小数第1位、推定値は個別データの1桁下）。
*****************************************************************************************/

/*========================================================================================
  背景表の行ラベル。ARD は ADaM の変数名を持ち、日本語の表示名はここで与える。
========================================================================================*/

/*========================================================================================
  表示文言のカタログ。正本は docs/metadata/label-catalog.csv。
  &lang で出力言語を切り替える（en が既定。ja にすると日本語で出る）。
  ラベルをここに直書きしないこと。追加・修正はカタログ側で行う。
  設計は docs/spec/label-and-traceability-design.md。
========================================================================================*/

%global lang;

filename _labcsv "&repo_root/docs/metadata/label-catalog.csv" encoding='utf-8';
proc import out=_labcat datafile=_labcsv dbms=csv replace;
  getnames=yes;
  guessingrows=max;
run;
filename _labcsv clear;

%macro _mklabfmt;
  %if %length(&lang) = 0 %then %let lang = en;
data _labfmt;
  set _labcat;
  length fmtname $32 start $80 label $400 type $1;
  type  = 'C';
  start = strip(key);
  %if %upcase(&lang) = EN %then %do; label = strip(label_en); %end;
  %else %do;                        label = strip(label_ja); %end;
  /* 出力形式にできるのはキーが英数字のものだけ。表番号のキー（T-5.4.1 など）は
     ハイフンとドットを SAS が範囲指定と解釈するため、下でマクロ変数として持つ。 */
  select (strip(kind));
    when ('bgitem')   fmtname = '$bgitem';
    when ('fixed')    fmtname = '$lblfx';
    otherwise delete;
  end;
  if missing(label) then delete;
  keep fmtname start label type;
run;

/* cntlin は同じ FMTNAME の行が連続していることを前提にする。$bgitem と $lblfx が
   混ざっていると作り直しになり、後の方しか残らない（2026-08-20 に背景表の行ラベルが
   変数名のまま出ていたのを是正）*/
proc sort data=_labfmt; by fmtname; run;
proc format cntlin=_labfmt; run;

  /* 水準の識別子と表示名（kind=level）。ARD の VARLEVEL・GROUP1L を表示名へ写すのに使う。
     t(9;22) only のように記号を含む識別子があり出力形式にできないため、データセットにして
     join で引く。カタログに無い水準は識別子をそのまま表示する。 */
  data _lvcat;
    set _labcat(where=(strip(kind) = 'level'));
    length LVKEY $80 LVLBL $200;
    /* 水準の並び順（kind=level の order 列）。入れた水準はこの番号で、入れていない水準は
       識別子（ARD の VARLEVEL）で並べる。表示名で並べると符号化を変えたときに順序が
       変わり、日英でも並びが食い違う（2026-08-23。CP932 から UTF-8 への移行で12表が動いた）*/
    LVORD = input(strip(vvalue(order)), ?? best8.);
    if missing(LVORD) then LVORD = 9999;
    /* 来院番号（kind=level の visitnum 列）。SDTM の TV ドメインの VISITNUM を写したもので、
       治療相の識別子にだけ入る。図表の並びは来院計画の順を原則とするため、順序番号の次の
       キーに使う。入っていない水準は 99999 として後ろへ回す（2026-08-23）*/
    LVVISIT = input(strip(vvalue(visitnum)), ?? best8.);
    if missing(LVVISIT) then LVVISIT = 99999;
    LVKEY = strip(key);
    %if %upcase(&lang) = EN %then %do; LVLBL = strip(label_en); %end;
    %else %do;                        LVLBL = strip(label_ja); %end;
    if missing(LVLBL) then LVLBL = LVKEY;
    keep LVKEY LVLBL LVORD LVVISIT;
  run;
  proc sort data=_lvcat nodupkey; by LVKEY; run;

  /* 表番号をキーに持つ文言はマクロ変数へ。名前は L_<種別2文字>_<キーの記号を _ に置換>。 */
  data _null_;
    set _labcat;
    length _lab $2000 _nm $40;
    %if %upcase(&lang) = EN %then %do; _lab = strip(label_en); %end;
    %else %do;                        _lab = strip(label_ja); %end;
    if strip(kind) not in ('title', 'subtitle', 'rowlbl', 'footnote') then return;
    if missing(_lab) then return;
    _nm = cats('L_', substr(strip(kind), 1, 2), '_', strip(key));
    call symputx(_nm, _lab, 'G');
  run;
%mend _mklabfmt;
%_mklabfmt

/* カタログから1件引く。&lblid が未登録なら空が返るので、呼び出し側で気づける。
   %superq でマクロ変数の中身を「そのままの文字」として返す。表示文言には % が入る
   （「95%信頼区間」「95% confidence interval」）ため、素の &&L_… で展開すると % の次の
   語がマクロ呼び出しとして解決され「無効なSAS名です」で落ちる（2026-08-24 に表 5.4.9 の
   脚注で発生）。 */
%macro lbl(kind, key);
%superq(L_&kind._&key)
%mend lbl;

%macro lblfx(key);
%sysfunc(strip(%sysfunc(putc(&key, $lblfx.))))
%mend lblfx;


/*========================================================================================
  1.1 生存時間解析の表（時点別の生存割合と95%信頼区間）
========================================================================================*/

%macro tab_km(analysis_id=, lblid=);
  /* _ord は集約にして group by から外す。式のまま group by に置くと proc sql が
     要約統計量を元のデータへ再マージし、時点ごとに4行（統計量の数）出てしまう
     （2026-08-20 に KM 表と CIF 表で発生。セル台帳の突合で検出）*/
  %local _n _ev _cn nobs;
  proc sql;
    create table _t as
    select coalescec(c.LVLBL, a.VARLEVEL) as TIMEPT length=40,
           max(case when a.STATNAME='surv' then a.STAT else . end) as _s,
           max(case when a.STATNAME='se'   then a.STAT else . end) as _se,
           max(case when a.STATNAME='lcl'  then a.STAT else . end) as _l,
           max(case when a.STATNAME='ucl'  then a.STAT else . end) as _u,
           max(input(compress(a.VARLEVEL, 'Y年'), best8.)) as _ord
    from ard.ard as a left join _lvcat as c on strip(a.VARLEVEL) = c.LVKEY
    where a.ANALYSID = "&analysis_id" and a.CONTEXT = 'survival'
      and a.VARLEVEL not in ('中央値', 'MEDIAN') and a.VARLEVEL ne ' '
    group by coalescec(c.LVLBL, a.VARLEVEL)
    order by _ord;
  quit;

  /* proc sql が要約統計量を元のデータへ再マージするため、時点ごとに統計量の数だけ
     同じ行が出る。値は同一なので畳む（2026-08-20。セル台帳の突合で検出し、RTF の
     KM 表と CIF 表が各時点4行になっていたのを是正）*/
  proc sort data=_t nodupkey; by _ord TIMEPT; run;

  proc sql noprint; select count(*) into :nobs trimmed from _t; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &analysis_id に結果値がない。表を作らない;
    %return;
  %end;

  data _t2;
    set _t;
    /* 標準誤差も put で文字にする。format= を define 側に置くとセル台帳には生値が
       入り、表示と食い違う（2026-08-20）*/
    length SURVC $10 SEVC $10 CIC $30;
    SURVC = put(100 * _s, 6.1);
    SEVC  = put(100 * _se, 6.1);
    CIC   = catx(' - ', put(100 * _l, 6.1), put(100 * _u, 6.1));
    keep TIMEPT SURVC SEVC CIC;
  run;

  proc sql noprint;
    select STAT into :_n  trimmed from ard.ard where ANALYSID="&analysis_id" and STATNAME='N';
    select STAT into :_ev trimmed from ard.ard where ANALYSID="&analysis_id" and STATNAME='nevent';
    select STAT into :_cn trimmed from ard.ard where ANALYSID="&analysis_id" and STATNAME='ncensor';
  quit;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  title3 justify=left "%lblfx(note_km)";
  %_tlfcells(_t2, &lblid, tab_km, %str(TIMEPT SURVC SEVC CIC))

  proc report data=_t2 nowd;
    column TIMEPT SURVC SEVC CIC;
    define TIMEPT / display "%lblfx(timepoint)";
    define SURVC  / display "%lblfx(surv)";
    define SEVC   / display "%lblfx(se)";
    define CIC    / display "%lblfx(ci95)";
  run;
  title;
  %_tlfclose
%mend tab_km;

/*========================================================================================
  HTML 版の図表（1図表=1ファイル）。トレーサビリティ索引（output/deliver/r/traceability.html）
  から図表へ直接飛べるようにするためで、これが配布の正体である。tlfhtml=0 なら作らない。
  ファイル名は表番号（&lblid）にする。索引側は <base>/<表番号>.html を参照する。
  tlfhtml と tlfdir の既定は呼び出し側（<試験ID>_TLF.sas）が決める。ここでは
  未設定のときだけ作らない側へ倒す（このファイルを単独で include したときの保険）。
========================================================================================*/

%global tlfhtml tlfdir;
%macro _deftlfhtml;
  %if %length(&tlfhtml) = 0 %then %let tlfhtml = 0;
%mend _deftlfhtml;
%_deftlfhtml

%macro _tlfopen(lblid);
  %if &tlfhtml = 1 %then %do;
    ods html5(id=h) path="&tlfdir" file="&lblid..html"
        options(svg_mode="inline") style=journal;
  %end;
%mend _tlfopen;

%macro _tlfclose;
  %if &tlfhtml = 1 %then %do;
    ods html5(id=h) close;
  %end;
%mend _tlfclose;
/*========================================================================================
  図表のセル台帳。表示した1セルを1行にして貯め、最後に CSV へ出す。R系の図表（同じ
  docs/metadata/tlf-index.csv を読んで描く）と突き合わせるための材料で、突合は
  program/r/<試験ID>_CompareTLF.R が行う。tlfcells=0 なら貯めない。
  列の並び（col_seq）は proc report の column 文の並びと同じにする。
========================================================================================*/

%global tlfcells;
%macro _deftlfcells;
  %if %length(&tlfcells) = 0 %then %let tlfcells = 1;
%mend _deftlfcells;
%_deftlfcells

%macro _cellsinit;
  %if &tlfcells = 1 %then %do;
    data _tlfcells;
      length lblid $20 display $20 row_key $200 col_label $60 value $200;
      row_seq = .; col_seq = .;
      call missing(of _all_);
      delete;
    run;
  %end;
%mend _cellsinit;

/* ds= 表示に使ったデータセット、vars= 表示した列（並び順）、lblid=・display= は宣言のもの */
%macro _tlfcells(ds, lblid, display, vars);
  %if &tlfcells = 1 %then %do;
    /* 同じ表番号を複数回呼ぶ表示（%tab_ae73_by_course の18表）があるので、row_seq は
       表番号ごとの通し番号にする。呼び出しごとに 1 から振ると台帳のキー
       （lblid・row_seq・col_seq）が重なり、突合の対象から落ちる（2026-08-20）*/
    %local _off;
    proc sql noprint;
      select coalesce(max(row_seq), 0) into :_off trimmed
      from _tlfcells where lblid = "&lblid";
    quit;
    data _cells1;
      /* 出力する列名が表示に使ったデータセットの列と衝突しうる（tab_bg の _bg2 は
         VALUE を持ち、SAS は大文字小文字を区別しないので同じ変数になる）。作業中は
         _c を付けた名前で持ち、最後に rename する（2026-08-20）*/
      length _clblid $20 _cdisp $20 _crowk $200 _ccoll $60 _cval $200;
      set &ds;
      _clblid = "&lblid"; _cdisp = "&display";
      row_seq = _n_ + &_off;
      %local i v n;
      %let n = %sysfunc(countw(&vars));
      _crowk = vvaluex("%scan(&vars, 1)");
      %do i = 1 %to &n;
        %let v = %scan(&vars, &i);
        col_seq = &i; _ccoll = "&v"; _cval = strip(vvaluex("&v")); output;
      %end;
      keep _clblid _cdisp row_seq _crowk col_seq _ccoll _cval;
      rename _clblid=lblid _cdisp=display _crowk=row_key _ccoll=col_label _cval=value;
    run;
    data _tlfcells; set _tlfcells _cells1; run;
    proc datasets library=work nolist; delete _cells1; quit;
  %end;
%mend _tlfcells;

%macro _cellswrite(path);
  %if &tlfcells = 1 %then %do;
    /* proc export はセッションの符号化（CP932）で書くため R 側が UTF-8 として
       読めない。データステップで UTF-8 を明示して書く。dsd でカンマと引用符を
       含む値も正しく囲む（2026-08-20）*/
    data _null_;
      set _tlfcells;
      length _rs _cs $12;
      file "&path" encoding='utf-8' lrecl=32767 dsd dlm=',';
      if _n_ = 1 then put 'lblid,display,row_seq,row_key,col_seq,col_label,value';
      _rs = strip(put(row_seq, best12.));
      _cs = strip(put(col_seq, best12.));
      put lblid display _rs row_key _cs col_label value;
    run;
    %put NOTE: [TLF] セル台帳を書いた: &path;
  %end;
%mend _cellswrite;



/*========================================================================================
  1.2 割合の表（頻度・割合・二項95%信頼区間）
========================================================================================*/

%macro tab_prop(analysis_id=, lblid=);
  %local nobs;
  proc sql;
    create table _p as
    select coalescec(c.LVLBL, a.VARLEVEL) as CATEG length=200,
           max(case when a.STATNAME='n'   then a.STAT else . end) as _n,
           max(case when a.STATNAME='N'   then a.STAT else . end) as _den,
           max(case when a.STATNAME='p'   then a.STAT else . end) as _p,
           max(case when a.STATNAME='lcl' then a.STAT else . end) as _l,
           max(case when a.STATNAME='ucl' then a.STAT else . end) as _u
    from ard.ard as a left join _lvcat as c on strip(a.VARLEVEL) = c.LVKEY
    where a.ANALYSID = "&analysis_id" and a.CONTEXT = 'categorical'
    group by coalescec(c.LVLBL, a.VARLEVEL);
  quit;

  /* proc sql の再マージで同じ水準が統計量の数（n・N・p・lcl・ucl の5つ）だけ出る。値は
     同一なので畳む。並びは件数の多い順（もとは order by _n descending で、集計列の別名を
     order by に置くこと自体が再マージの引き金になっていた）。%tab_bg・%tab_km と同じ手当て
     （2026-08-20。31表すべてが5行ずつ印字されていたのを是正）*/
  proc sort data=_p nodupkey; by descending _n CATEG; run;

  proc sql noprint; select count(*) into :nobs trimmed from _p; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &analysis_id に結果値がない。表を作らない;
    %return;
  %end;

  data _p2;
    set _p;
    length NFRAC $20 PCTC $10 CIC $30;
    NFRAC = catx('/', put(_n, best8.), put(_den, best8.));
    PCTC  = put(_p, 6.1);
    CIC   = catx(' - ', put(_l, 6.1), put(_u, 6.1));
    keep CATEG NFRAC PCTC CIC;
  run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %_tlfcells(_p2, &lblid, tab_prop, %str(CATEG NFRAC PCTC CIC))

  proc report data=_p2 nowd;
    column CATEG NFRAC PCTC CIC;
    define CATEG / display "%lbl(ro, &lblid)" width=40;
    define NFRAC / display "%lblfx(nden)";
    define PCTC  / display "%lblfx(prop)";
    define CIC   / display "%lblfx(ci95)";
  run;
  title;
  %_tlfclose
%mend tab_prop;

/*========================================================================================
  1.2b 群を列に持つカテゴリ表（1解析で群が複数あるもの。SAP 5.4.3 の3列表）
  行と列の並びは ARD が順序を持たないため、呼び出し側の levels= と groups= で決める
  （段階2で ARD 側へ移す。docs/spec/label-and-traceability-design.md）。
========================================================================================*/

%macro tab_prop_grp(analysis_id=, lblid=, groups=, levels=);
  %local nobs i ng;
  %let ng = %sysfunc(countw(&groups, |));
  proc sql;
    create table _gp as
    select GROUP1L, VARLEVEL,
           max(case when STATNAME='n' then STAT end) as _n,
           max(case when STATNAME='N' then STAT end) as _den,
           max(case when STATNAME='p' then STAT end) as _p
    from ard.ard
    where ANALYSID = "&analysis_id" and CONTEXT = 'categorical'
    group by GROUP1L, VARLEVEL;
  quit;

  proc sql noprint; select count(*) into :nobs trimmed from _gp; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &analysis_id に結果値がない。表を作らない;
    %return;
  %end;

  data _grord;
    length VARLEVEL $60;
    %do i = 1 %to %sysfunc(countw(&levels, |));
      VARLEVEL = "%scan(&levels, &i, |)"; _ro = &i; output;
    %end;
    keep VARLEVEL _ro;
  run;

  data _gcord;
    length GROUP1L $40;
    %do i = 1 %to &ng;
      GROUP1L = "%scan(&groups, &i, |)"; _co = &i; output;
    %end;
    keep GROUP1L _co;
  run;

  proc sql;
    /* 先頭に対象症例数の行を置く（SAP 5.4.3 の表の第1行） */
    create table _gp2 as
    select c._co, 0 as _ro, "%lblfx(nsubj)" as ROWLBL length=200,
           strip(put(max(a._den), 8.0)) as VALUE length=30
    from _gp as a inner join _gcord as c on strip(a.GROUP1L) = strip(c.GROUP1L)
    group by c._co
    union all
    select c._co, b._ro, coalescec(d.LVLBL, a.VARLEVEL) as ROWLBL length=200,
           catx(' ', strip(put(a._n, 8.0)),
                     cats('(', strip(put(a._p, 8.1)), ')')) as VALUE length=30
    from _gp as a
         inner join _grord as b on strip(a.VARLEVEL) = strip(b.VARLEVEL)
         inner join _gcord as c on strip(a.GROUP1L)  = strip(c.GROUP1L)
         left  join _lvcat as d on strip(a.VARLEVEL) = d.LVKEY;
  quit;

  /* proc report の across はその下に統計量しか置けない（文字を置くと
     「VALUEに統計量を割り当てた変数はありません」で止まる）ので、群は横持ちにしてから並べる */
  /* 列見出しは識別子ではなく表示名を出す。カタログに無ければ識別子のまま */
  data _null_;
    length k $80;
    %do i = 1 %to &ng;
      k = "%scan(&groups, &i, |)";
      call symputx("_gl&i", k, 'G');
    %end;
  run;
  data _null_;
    set _lvcat;
    %do i = 1 %to &ng;
      if LVKEY = "%scan(&groups, &i, |)" then call symputx("_gl&i", LVLBL, 'G');
    %end;
  run;

  proc sort data=_gp2; by _ro ROWLBL _co; run;
  proc transpose data=_gp2 out=_gpt(drop=_NAME_) prefix=C;
    by _ro ROWLBL;
    id _co;
    var VALUE;
  run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %local _vl;
  %let _vl = ROWLBL;
  %do i = 1 %to &ng; %let _vl = &_vl C&i; %end;
  %_tlfcells(_gpt, &lblid, tab_prop_grp, %str(&_vl))

  proc report data=_gpt nowd;
    column _ro ROWLBL %do i = 1 %to &ng; C&i %end;;
    define _ro    / order noprint;
    define ROWLBL / display "%lbl(ro, &lblid)" width=32;
    %do i = 1 %to &ng;
      define C&i / display "&&_gl&i" width=18;
    %end;
  run;
  title;
  %_tlfclose
%mend tab_prop_grp;
/*========================================================================================
  1.2d 群を列に持つカテゴリ表（複数の解析を行ブロックとして積む。SAP 5.4.3 の3列表）
  blocks= は「解析ID:水準1|水準2|…」を ~ で区切って並べたもの。行の並びは指定した順。
  1.2b は1解析しか扱えないため、行が複数の指標にまたがる表のために分けた。
========================================================================================*/

%macro tab_prop_grp_multi(output_id=, lblid=, groups=, blocks=);
  %local i j ng nb an lv nobs;
  %let ng = %sysfunc(countw(&groups, |));
  %let nb = %sysfunc(countw(&blocks, ~));

  data _grord;
    length ANALYSID $40 VARLEVEL $60;
    retain _ro 0;
    %do i = 1 %to &nb;
      %let an = %scan(%scan(&blocks, &i, ~), 1, %str(:));
      %let lv = %scan(%scan(&blocks, &i, ~), 2, %str(:));
      %do j = 1 %to %sysfunc(countw(&lv, |));
        ANALYSID = "&an"; VARLEVEL = "%scan(&lv, &j, |)"; _ro + 1; output;
      %end;
    %end;
    keep ANALYSID VARLEVEL _ro;
  run;

  data _gcord;
    length GROUP1L $40;
    %do i = 1 %to &ng;
      GROUP1L = "%scan(&groups, &i, |)"; _co = &i; output;
    %end;
    keep GROUP1L _co;
  run;

  proc sql;
    create table _gp as
    select ANALYSID, GROUP1L, VARLEVEL,
           max(case when STATNAME='n' then STAT end) as _n,
           max(case when STATNAME='N' then STAT end) as _den,
           max(case when STATNAME='p' then STAT end) as _p
    from ard.ard
    where CONTEXT = 'categorical'
      and ANALYSID in (select distinct ANALYSID from _grord)
      %if %length(&output_id) %then and OUTPUTID = "&output_id";
    group by ANALYSID, GROUP1L, VARLEVEL;
  quit;

  proc sql noprint; select count(*) into :nobs trimmed from _gp; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &lblid に結果値がない。表を作らない;
    %return;
  %end;

  proc sql;
    /* 先頭に対象症例数の行を置く（SAP 5.4.3 の表の第1行） */
    create table _gp2 as
    select c._co, 0 as _ro, "%lblfx(nsubj)" as ROWLBL length=200,
           strip(put(max(a._den), 8.0)) as VALUE length=30
    from _gp as a inner join _gcord as c on strip(a.GROUP1L) = strip(c.GROUP1L)
    group by c._co
    union all
    select c._co, b._ro, coalescec(d.LVLBL, a.VARLEVEL) as ROWLBL length=200,
           catx(' ', strip(put(a._n, 8.0)),
                     cats('(', strip(put(a._p, 8.1)), ')')) as VALUE length=30
    from _gp as a
         inner join _grord as b on strip(a.ANALYSID) = strip(b.ANALYSID)
                               and strip(a.VARLEVEL) = strip(b.VARLEVEL)
         inner join _gcord as c on strip(a.GROUP1L)  = strip(c.GROUP1L)
         left  join _lvcat as d on strip(a.VARLEVEL) = d.LVKEY;
  quit;

  data _null_;
    length k $80;
    %do i = 1 %to &ng;
      k = "%scan(&groups, &i, |)";
      call symputx("_gl&i", k, 'G');
    %end;
  run;
  data _null_;
    set _lvcat;
    %do i = 1 %to &ng;
      if LVKEY = "%scan(&groups, &i, |)" then call symputx("_gl&i", LVLBL, 'G');
    %end;
  run;

  proc sort data=_gp2; by _ro ROWLBL _co; run;
  proc transpose data=_gp2 out=_gpt(drop=_NAME_) prefix=C;
    by _ro ROWLBL;
    id _co;
    var VALUE;
  run;

  %local _cols;
  %let _cols = ROWLBL;
  %do i = 1 %to &ng; %let _cols = &_cols C&i; %end;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  footnote1 justify=left "%lbl(fo, &lblid)";
  %_tlfcells(_gpt, &lblid, tab_prop_grp_multi, %str(&_cols))

  proc report data=_gpt nowd;
    column _ro ROWLBL %do i = 1 %to &ng; C&i %end;;
    define _ro    / order noprint;
    define ROWLBL / display "%lbl(ro, &lblid)" width=40;
    %do i = 1 %to &ng;
      define C&i / display "&&_gl&i" width=18;
    %end;
  run;
  title; footnote;
  %_tlfclose
%mend tab_prop_grp_multi;

/*========================================================================================
  1.2c 評価時点を行に持つカテゴリ表（1つの OUTPUTID の解析を行として並べる。SAP 5.4.3.1）
  SAP の図表案は評価時点を列に置くが、23列は A4 縦の本文幅（11,185 twips）に入らない
  （n (%) のセルで約22,800 twips 必要）。行と列を入れ替えて1表にする。内容は同じ。
  行の並びと表示名は docs/metadata/mr-timepoint.csv（%_tdmr_load）が持ち、列の並びは levels= で決める。
  SUBSET='NOSAMEDAY' の解析がある水準は、割合ではなくその件数をカッコに入れる
  （molpd・molr は88例の排他区分ではなくイベントの件数なので割合を出さない）。
========================================================================================*/

%macro tab_prop_tp(output_id=, lblid=, levels=);
  %local nobs i nlv;
  %_tdmr_load
  %let nlv = %sysfunc(countw(&levels, |));

  data _tplv;
    length VARLEVEL $60;
    %do i = 1 %to &nlv;
      VARLEVEL = "%scan(&levels, &i, |)"; _co = &i; output;
    %end;
    keep VARLEVEL _co;
  run;

  data _tprow;
    set work._tdmr;
    length ROWKEY $40 ROWLBL $200;
    ROWKEY = strip(glabel);
    ROWLBL = strip(label);
    _ro    = order;
    keep ROWKEY ROWLBL _ro;
  run;

  proc sql;
    create table _tpv as
    select GROUP1L, VARLEVEL, SUBSET,
           max(case when STATNAME='n' then STAT end) as _n,
           max(case when STATNAME='p' then STAT end) as _p
    from ard.ard
    where OUTPUTID = "&output_id" and CONTEXT = 'categorical'
    group by GROUP1L, VARLEVEL, SUBSET;
  quit;

  proc sql noprint; select count(*) into :nobs trimmed from _tpv; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &output_id に結果値がない。表を作らない;
    %return;
  %end;

  proc sql;
    create table _tpc as
    select r._ro, r.ROWLBL, c._co,
           case when b._n is not null
                  then catx(' ', strip(put(a._n, 8.0)),
                            cats('(', strip(put(b._n, 8.0)), ')'))
                else catx(' ', strip(put(a._n, 8.0)),
                          cats('(', strip(put(a._p, 8.1)), ')'))
           end as VALUE length=30
    from _tpv as a
         inner join _tprow as r on strip(a.GROUP1L)  = strip(r.ROWKEY)
         inner join _tplv  as c on strip(a.VARLEVEL) = strip(c.VARLEVEL)
         left  join _tpv   as b on strip(a.GROUP1L)  = strip(b.GROUP1L)
                               and strip(a.VARLEVEL) = strip(b.VARLEVEL)
                               and strip(b.SUBSET)   = 'NOSAMEDAY'
    where strip(a.SUBSET) ne 'NOSAMEDAY';
  quit;

  proc sort data=_tpc; by _ro ROWLBL _co; run;
  proc transpose data=_tpc out=_tpt(drop=_NAME_) prefix=C;
    by _ro ROWLBL;
    id _co;
    var VALUE;
  run;

  /* 列見出しは識別子ではなく表示名。カタログに無ければ識別子のまま */
  data _null_;
    length k $80;
    %do i = 1 %to &nlv;
      k = "%scan(&levels, &i, |)";
      call symputx("_cl&i", k, 'G');
    %end;
  run;
  data _null_;
    set _lvcat;
    %do i = 1 %to &nlv;
      if LVKEY = "%scan(&levels, &i, |)" then call symputx("_cl&i", LVLBL, 'G');
    %end;
  run;

  %local _cols;
  %let _cols = ROWLBL;
  %do i = 1 %to &nlv; %let _cols = &_cols C&i; %end;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  footnote1 justify=left "%lbl(fo, &lblid)";
  %_tlfcells(_tpt, &lblid, tab_prop_tp, %str(&_cols))

  proc report data=_tpt nowd;
    column _ro ROWLBL %do i = 1 %to &nlv; C&i %end;;
    define _ro    / order noprint;
    define ROWLBL / display "%lbl(ro, &lblid)" width=28;
    %do i = 1 %to &nlv;
      define C&i / display "&&_cl&i" width=12;
    %end;
  run;
  title; footnote;
  %_tlfclose
%mend tab_prop_tp;



/*========================================================================================
  1.3 背景表（連続量とカテゴリを1つの表に並べる。行順は ANALYSID の連番）
========================================================================================*/

/* item_var は | 区切りで2つまで受ける。2つ渡すと行項目を「1つ目 / 2つ目」と連結する。
   ARD が行を区別する軸を2つ持つ表（Out-5.4.7.4・Out-5.4.7.5 は VARIABLE が感染症や
   併用薬、GROUP1L が治療相）で、片方しか出せず同じ行ラベルが並んでいた（2026-08-23）*/
%macro tab_bg(output_id=, lblid=, item_var=VARIABLE, item_label=item, levels=);
  %local nobs iv1 iv2 _nlv _k;
  %let iv1 = %scan(&item_var, 1, %str(|));
  %let iv2 = %scan(&item_var, 2, %str(|));
  proc sql;
    create table _w as
    select a.ANALYSID, a.VARIABLE, a.GROUP1L,
           coalescec(c.LVLBL, a.VARLEVEL) as VARLEVEL length=200,
           a.VARLEVEL as LVKEYRAW length=200,
           c.LVORD as LVORD,
           c.LVVISIT as LVVISIT,
           i.LVLBL as ITEMLBL length=200,
%if %length(&iv2) %then %do;
           j.LVLBL as ITEMLBL2 length=200,
%end;
           max(a.CONTEXT) as CONTEXT length=20,
           max(case when a.STATNAME='n'      then a.STAT end) as _n,
           max(case when a.STATNAME='nmiss'  then a.STAT end) as _nm,
           max(case when a.STATNAME='mean'   then a.STAT end) as _mean,
           max(case when a.STATNAME='sd'     then a.STAT end) as _sd,
           max(case when a.STATNAME='median' then a.STAT end) as _med,
           max(case when a.STATNAME='min'    then a.STAT end) as _min,
           max(case when a.STATNAME='max'    then a.STAT end) as _max,
           max(case when a.STATNAME='N'      then a.STAT end) as _den,
           max(case when a.STATNAME='p'      then a.STAT end) as _p
    from ard.ard as a
         left join _lvcat as c on strip(a.VARLEVEL) = c.LVKEY
         /* 行項目（&item_var）の表示名も水準のカタログから引く。ENGRAFT・ITDOSE のように
            kind=level にだけ登録されているキーがあり、$bgitem だけを見ていた頃は識別子が
            そのまま印字されていた（2026-08-20）*/
         left join _lvcat as i on strip(a.&iv1) = i.LVKEY
%if %length(&iv2) %then %do;
         left join _lvcat as j on strip(a.&iv2) = j.LVKEY
%end;
    where a.OUTPUTID = "&output_id"
    group by a.ANALYSID, a.VARIABLE, a.GROUP1L, coalescec(c.LVLBL, a.VARLEVEL),
             a.VARLEVEL, c.LVORD, c.LVVISIT, i.LVLBL
%if %length(&iv2) %then %do;
           , j.LVLBL
%end;
    ;
  quit;

  /* proc sql の再マージで同じ行が統計量の数だけ出る。値は同一なので畳む（2026-08-20）*/
  proc sort data=_w nodupkey; by ANALYSID VARIABLE GROUP1L VARLEVEL LVKEYRAW LVORD LVVISIT ITEMLBL
%if %length(&iv2) %then %do; ITEMLBL2 %end;
  ; run;

  proc sql noprint; select count(*) into :nobs trimmed from _w; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &output_id に結果値がない。表を作らない;
    %return;
  %end;

  data _bg2;
    set _w;
    length ITEM $200 LEVEL $200 VALUE $60 _i2 $100;
    /* kind=level → kind=bgitem → 識別子そのまま、の順で引く（R 側の lvl() と同じ）。
       $bgitem は未登録の値を入力のまま返すため、level を先に見る */
    ITEM = coalescec(ITEMLBL, put(&iv1, $bgitem.));
    if ITEM = ' ' then ITEM = &iv1;
%if %length(&iv2) %then %do;
    _i2 = coalescec(ITEMLBL2, put(&iv2, $bgitem.));
    if _i2 = ' ' then _i2 = &iv2;
    ITEM = catx(' / ', ITEM, _i2);
%end;
    if CONTEXT = 'continuous' then do;
      LEVEL = ' ';
      VALUE = strip(put(_med, 12.1)) || ' [' || strip(put(_min, 12.1)) || ', '
              || strip(put(_max, 12.1)) || "] %lblfx(mean) " || strip(put(_mean, 12.1))
              || ' SD ' || strip(put(_sd, 12.1));
      if _nm > 0 then VALUE = strip(VALUE) || " %lblfx(missing)" || strip(put(_nm, 8.0));
    end;
    else do;
      LEVEL = VARLEVEL;
      VALUE = strip(put(_n, 8.0)) || ' (' || strip(put(_p, 8.1)) || ')';
    end;
    if missing(LVORD) then LVORD = 9999;
    if missing(LVVISIT) then LVVISIT = 99999;
    drop _i2;
    keep ANALYSID ITEM LEVEL VALUE LVORD LVVISIT LVKEYRAW;
  run;

  /* 並びは 宣言の levels= の順 → 順序番号 → 来院番号 → 識別子。表示名では並べない
     （符号化を変えると順序が変わり、日英でも食い違うため。2026-08-23）。
     levels= は来院と無関係な区分（到達までの時間の区分など）を表ごとに指定するための口で、
     指定に無い水準は後ろへ回す */
  %let _nlv = 0;
  %if %length(&levels) %then %let _nlv = %sysfunc(countw(&levels, %str(|)));
  data _lvseq;
    length LVKEYRAW $200 _LVSEQ 8;
    %do _k = 1 %to &_nlv;
      LVKEYRAW = "%scan(&levels, &_k, %str(|))"; _LVSEQ = &_k; output;
    %end;
    stop;
  run;

  proc sql;
    create table _bg2s as
    select a.*, coalesce(b._LVSEQ, 99999) as _LVSEQ
    from _bg2 as a left join _lvseq as b on strip(a.LVKEYRAW) = strip(b.LVKEYRAW);
  quit;
  proc sort data=_bg2s out=_bg2; by ANALYSID _LVSEQ LVORD LVVISIT LVKEYRAW; run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  title3 justify=left "%lblfx(note_bg)";
  %_tlfcells(_bg2, &lblid, tab_bg, %str(ITEM LEVEL VALUE))

  proc report data=_bg2 nowd;
    column ANALYSID ITEM LEVEL VALUE;
    define ANALYSID / order noprint;
    define ITEM     / order order=data display "%lblfx(&item_label)" width=44;
    define LEVEL    / display "%lblfx(categ)"   width=26;
    define VALUE    / display "%lblfx(summary)"   width=46;
  run;
  title;
  %_tlfclose
%mend tab_bg;

/*========================================================================================
  1.4 Kaplan-Meier 曲線（図のみ ADaM を直接使う）
========================================================================================*/

%macro fig_km(paramcd=, lblid=, where=1, group=);
  data _k;
    set ads.adtte;
    if (&where) and PARAMCD = "&paramcd";
    AVALY = AVAL / 365.25;
  run;

  /* LISTING を閉じてから描く。開いたままだと図が PNG としてカレント（リポジトリの
     ルート）へ落ちる（SurvivalPlot.png・SurvivalPlot1.png …。2026-08-25 に判明）。
     図は html5 の svg_mode="inline" で本文へ埋め込むので LISTING 宛の画像は要らない。
     ods graphics on の width= は LISTING の幅も変えるため、閉じている間は
     %tab_mrlist の列幅の計算が options ls= のままで済む */
  ods listing close;
  ods graphics on / width=16cm height=11cm;
  %_tlfopen(&lblid)
  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  /* 図だけを出す。生存率の表は %tab_km が ARD から出しており、proc lifetest の既定の表を
     重ねると同じ数字が2度出るうえ、SAS のロケールが生成する日本語の見出し（積極限法による
     生存推定・生存率・打ち切り など）が英語版の rtf にも入る（2026-08-20） */
  ods select survivalplot;
  /* 打ち切りの目印（既定で出る）と95%信頼限界を出す。R系の図と読み方を揃えるため
     （2026-08-20）。cl は層別のときも層ごとに描かれる */
  proc lifetest data=_k method=km plots=survival(atrisk=0 to 5 by 1 cl);
    time AVALY * CNSR(1);
    %if %length(&group) %then %do; strata &group; %end;
    label AVALY = "%lblfx(xaxis_km)";
  run;
  ods select all;
  title;
  ods graphics off;
  %_tlfclose
  ods listing;
%mend fig_km;

/*========================================================================================
  1.5 症例一覧（結果値ではないので ARD には持たせず、ADaM から直接描く）
========================================================================================*/

/* vars= は表示する列（空白区切り。並び順を持つ）、labels= は列見出しに使う固定文言の
   キー（| 区切り。label-catalog の kind=fixed。vars= と同じ数・同じ順）。
   R系（TLF.R の d_tab_list）が同じ vars=・labels= を読んで同じ列を出す。 */
%macro tab_list(vars=, labels=, lblid=);
  %local nobs i n v k data;
  /* 一覧の元データは表番号ごとに作る。結果値の集計ではないので ARD から引けず、宣言に
     データセット名を持たせると SAS 側の実装詳細が正本（docs/metadata/tlf-index.csv）に入る。
     R系（TLF.R の d_tab_list）も同じく表番号で前処理を引く */
  %if &lblid = T_5_4_13_2 %then %do;
    %_list_abl
    %let data = _abllist;
  %end;
  %else %do;
    %put WARNING: [TLF] &lblid の一覧の元データを知らない。一覧を作らない;
    %return;
  %end;
  proc sql noprint; select count(*) into :nobs trimmed from &data; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &data に該当例がない。一覧を作らない;
    %return;
  %end;
  %_tlfopen(&lblid)
  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %_tlfcells(&data, &lblid, tab_list, %str(&vars))

  %let n = %sysfunc(countw(&vars, %str( )));
  proc report data=&data nowd;
    column &vars;
    %do i = 1 %to &n;
      %let v = %scan(&vars, &i, %str( ));
      %let k = %scan(&labels, &i, |);
      define &v / display "%lblfx(&k)";
    %end;
  run;
  title;
  %_tlfclose
%mend tab_list;

/*========================================================================================
  1.5.1 分子遺伝学的効果の症例別一覧（SAP 5.4.3.2）

  症例あたり2行。1行目は CRF の判定欄（ads.adrs。判定欄があるシートのみ）、2行目は
  コピー数から導出した判定（ads.adlb の MRCAT。提出された全シート）。列は 表 5.4.3.1 と
  同じ23評価時点で、並びと列見出し（glabel）は docs/metadata/mr-timepoint.csv（%_tdmr_load）が持つ。
  結果値の集計ではなく症例単位の一覧なので ARD からは作れず、ADaM から直接組む
  （%tab_list と同じ作り方）。
  判定欄の値は紙幅の都合で略号にする（MOLECULAR CR → CR など。対応は脚注）。
  測定も判定も無い時点は空欄にする。判定不能とは書かない（表 5.4.3.1 の集計は未測定を
  判定不能に数えるが、一覧では実際に何が無いかが見えるようにする）。
========================================================================================*/

/* subtypemap … 症例のサブタイプごとに見る測定項目が違う試験で、その対応を渡す。
                 `<SUBTYPE の値>:<PARAMCD>` を `|` で並べる。空なら絞り込まない。 */
%macro tab_mrlist(lblid=, subtypemap=);
  %local i ntp nobs _cols _w1 _w2 _wt;
  %_tdmr_load
  /* RTF の列幅は cellwidth で決める。A4 縦の本文幅 11,185 twips（paperw 11905 から
     左右の余白 各360 を引いた幅）に収める。実際に出る幅は 760 + 910 + 23x410 =
     11,100 twips。単位を付けないと ODS RTF が別の単位で読んで桁違いに広い表を作り、
     1つの表が列ごとの表に分割される（2026-08-21）*/
  %let _w1 = 38pt;   /* 症例 */
  %let _w2 = 45pt;   /* 種別 */
  %let _wt = 20pt;   /* 評価時点（23列を等幅）*/

  /* 評価時点の並びと列見出し。正本は docs/metadata/mr-timepoint.csv */
  proc sort data=work._tdmr out=_mrtp; by order; run;
  proc sql noprint; select count(*) into :ntp trimmed from _mrtp; quit;
  %if &ntp = 0 %then %do;
    %put WARNING: [TLF] work._tdmr に評価時点がない。一覧を作らない;
    %return;
  %end;
  data _null_;
    set _mrtp;
    call symputx(cats('_mg', _n_), strip(glabel), 'G');
  run;

  /* 対象は FAS。症例の識別子は SUBJID（4桁）にする。USUBJID は試験名が表題と重なって
     冗長で、紙幅も食う。サブタイプは ADSL のものを正とし、ADLB の測定項目に対応づける */
  proc sort data=ads.adsl(where=(FASFL='Y') keep=SUBJID SUBTYPE FASFL) out=_mrsub;
    by SUBJID;
  run;

  /* 1行目：CRF の判定欄。rsparamcd を持つ時点だけが該当する。MOLRESP の3時点は AVISIT が
     rsavisit と一致する行、MOLPD・MOLR の2時点は AVISIT を見ない */
  proc sql;
    create table _mrrs as
    select t.order as _co, s.SUBJID, r.AVALC as _v length=40
    from _mrtp as t
         inner join ads.adrs as r on strip(r.PARAMCD) = strip(t.rsparamcd)
         inner join _mrsub as s   on s.SUBJID = r.SUBJID
    where strip(t.rsparamcd) ne ' ' and r.AVALC ne ' '
      and (strip(t.rsavisit) = ' ' or strip(r.AVISIT) = strip(t.rsavisit));
  quit;

  /* 2行目：測定値からの判定（MRCAT）。source に LB を含む時点が該当する。
     症例のサブタイプごとに見る測定項目が違う試験では、subtypemap で対応を渡す。
     書き方は `<SUBTYPE の値>:<PARAMCD>` を `|` で並べる（例 major:MJBCRABL|minor:MNBCRABL）。
     渡さなければ絞り込まず、該当時点の MRCAT をそのまま採る（サブタイプの区別が無い試験）。 */
  %local _smi _sm _smk _smv _smwh;
  %let _smwh = ;
  %if %length(&subtypemap) %then %do;
    %let _smi = 1;
    %do %while (%length(%scan(&subtypemap, &_smi, |)));
      %let _sm  = %scan(&subtypemap, &_smi, |);
      %let _smk = %scan(&_sm, 1, :);
      %let _smv = %scan(&_sm, 2, :);
      %if &_smi = 1 %then %let _smwh = (s.SUBTYPE = "&_smk" and l.PARAMCD = "&_smv");
      %else %let _smwh = &_smwh or (s.SUBTYPE = "&_smk" and l.PARAMCD = "&_smv");
      %let _smi = %eval(&_smi + 1);
    %end;
    %let _smwh = and (&_smwh);
  %end;
  proc sql;
    create table _mrlb as
    select t.order as _co, s.SUBJID, l.MRCAT as _v length=40
    from _mrtp as t
         inner join ads.adlb as l on strip(l.LBSPID) = strip(t.spid)
         inner join _mrsub as s   on s.SUBJID = l.SUBJID
    where index(strip(t.source), 'LB') > 0 and l.MRCAT ne ' '
      &_smwh;
  quit;

  data _mrv;
    set _mrrs(in=_a) _mrlb;
    length VALC $8;
    _ki = ifn(_a, 1, 2);
    /* 判定欄の値は紙幅の都合で略号にする。ND・NQ・DT・NE は記録のまま */
    select (strip(_v));
      when ('MOLECULAR CR') VALC = 'CR';
      when ('MOLECULAR PD') VALC = 'PD';
      when ('MOLECULAR R')  VALC = 'R';
      when ('MOLECULAR TF') VALC = 'TF';
      otherwise VALC = strip(_v);
    end;
    keep SUBJID _ki _co VALC;
  run;
  proc sort data=_mrv nodupkey; by SUBJID _ki _co; run;

  /* 症例 × 2行 × 23時点の枠を先に作る。proc transpose は値のある _co しか列にしないため、
     枠が無いと測定が1件も無い時点の列が落ちて列数が変わる */
  data _mrgrid;
    set _mrsub;
    do _ki = 1 to 2;
      do _co = 1 to &ntp;
        output;
      end;
    end;
    keep SUBJID _ki _co;
  run;
  proc sql;
    create table _mrcell as
    select g.SUBJID, g._ki, g._co, coalescec(v.VALC, ' ') as VALC length=8
    from _mrgrid as g left join _mrv as v
      on g.SUBJID = v.SUBJID and g._ki = v._ki and g._co = v._co;
  quit;
  proc sort data=_mrcell; by SUBJID _ki _co; run;

  proc transpose data=_mrcell out=_mrt(drop=_NAME_) prefix=T;
    by SUBJID _ki;
    id _co;
    var VALC;
  run;

  data _mrl;
    set _mrt;
    length KIND $40;
    KIND = ifc(_ki = 1, "%lblfx(mr_crf)", "%lblfx(mr_copy)");
  run;
  proc sort data=_mrl; by SUBJID _ki; run;

  proc sql noprint; select count(*) into :nobs trimmed from _mrl; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &lblid に対象例がない。一覧を作らない;
    %return;
  %end;

  %let _cols = SUBJID KIND;
  %do i = 1 %to &ntp; %let _cols = &_cols T&i; %end;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  footnote1 justify=left "%lbl(fo, &lblid)";
  %_tlfcells(_mrl, &lblid, tab_mrlist, %str(&_cols))

  /* width= は LISTING だけに効く。合計を 9 + 11 + 23x6 = 158 桁にする。LINESIZE を
     超えると proc report が表を列で分割し、その分割が ODS RTF にもそのまま出る
     （%fig_km の ods graphics が LISTING の幅を 171 桁まで下げている。2026-08-21）*/
  proc report data=_mrl nowd;
    column SUBJID _ki KIND %do i = 1 %to &ntp; T&i %end;;
    /* order 変数は欠測の行を既定で落とすので missing を付ける */
    define SUBJID / order order=internal missing "%lblfx(subject)" width=7
                    style(column)=[cellwidth=&_w1];
    define _ki    / order noprint missing;
    define KIND   / display "%lblfx(mr_kind)" width=9
                    style(column)=[cellwidth=&_w2];
    %do i = 1 %to &ntp;
      define T&i / display "&&_mg&i" width=4 style(column)=[cellwidth=&_wt];
    %end;
  run;
  title; footnote;
  %_tlfclose
%mend tab_mrlist;

/*========================================================================================
  1.6 累積発生率の表（競合リスク。SAP 4.4.10）
========================================================================================*/

%macro tab_cif(analysis_id=, lblid=);
  %local _n _ne _nc nobs;
  proc sql;
    create table _cf as
    select coalescec(c.LVLBL, a.VARLEVEL) as TIMEPT length=40,
           max(case when a.STATNAME='cif' then a.STAT else . end) as _c,
           max(case when a.STATNAME='se'  then a.STAT else . end) as _se,
           max(case when a.STATNAME='lcl' then a.STAT else . end) as _l,
           max(case when a.STATNAME='ucl' then a.STAT else . end) as _u,
           max(input(compress(a.VARLEVEL, 'Y年'), best8.)) as _ord
    from ard.ard as a left join _lvcat as c on strip(a.VARLEVEL) = c.LVKEY
    where a.ANALYSID = "&analysis_id" and a.CONTEXT = 'cuminc' and a.VARLEVEL ne ' '
    group by coalescec(c.LVLBL, a.VARLEVEL)
    order by _ord;
  quit;

  /* proc sql が要約統計量を元のデータへ再マージするため、時点ごとに統計量の数だけ
     同じ行が出る。値は同一なので畳む（2026-08-20。セル台帳の突合で検出し、RTF の
     KM 表と CIF 表が各時点4行になっていたのを是正）*/
  proc sort data=_cf nodupkey; by _ord TIMEPT; run;

  proc sql noprint; select count(*) into :nobs trimmed from _cf; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &analysis_id に結果値がない。表を作らない;
    %return;
  %end;

  data _cf2;
    set _cf;
    length CIFC $10 SEVC $10 CIC $30;
    CIFC = put(100 * _c, 6.1);
    SEVC = put(100 * _se, 6.1);
    CIC  = catx(' - ', put(100 * _l, 6.1), put(100 * _u, 6.1));
    keep TIMEPT CIFC SEVC CIC;
  run;

  proc sql noprint;
    select STAT into :_n  trimmed from ard.ard where ANALYSID="&analysis_id" and STATNAME='N';
    select STAT into :_ne trimmed from ard.ard where ANALYSID="&analysis_id" and STATNAME='nevent';
    select STAT into :_nc trimmed from ard.ard where ANALYSID="&analysis_id" and STATNAME='ncompet';
  quit;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  title3 justify=left "%lblfx(note_cif)";
  %_tlfcells(_cf2, &lblid, tab_cif, %str(TIMEPT CIFC SEVC CIC))

  proc report data=_cf2 nowd;
    column TIMEPT CIFC SEVC CIC;
    define TIMEPT / display "%lblfx(timepoint)";
    define CIFC   / display "%lblfx(cif)";
    define SEVC   / display "%lblfx(se)";
    define CIC    / display "%lblfx(ci95)";
  run;
  title;
  %_tlfclose
%mend tab_cif;

/*========================================================================================
  1.7 例数の表（Mth-N の結果値だけを並べる。SAP 5.1 対象患者）
  1つの OUTPUTID の CONTEXT='count' の解析を、解析IDの順に1行ずつ並べる。
  行ラベルは水準の識別子（ALLENR・FAS・SAF・PPS・ALLHSCT・PNINTRO）をカタログで引く。
  2026-08-20 に TLF.sas の直書きの proc report をここへ移した。マクロ呼び出しでないと
  docs/metadata/tlf-index.csv に載らず、R系が描かず、セル台帳にも載らないため。
========================================================================================*/

%macro tab_count(output_id=, lblid=);
  %local nobs;
  /* 1解析1行なので group by が要らない。集約を書かなければ proc sql の再マージも起きない */
  proc sql;
    create table _cn as
    select a.ANALYSID,
           coalescec(c.LVLBL, a.VARLEVEL) as CATEG length=200,
           a.STAT as _n
    from ard.ard as a left join _lvcat as c on strip(a.VARLEVEL) = c.LVKEY
    where a.OUTPUTID = "&output_id" and a.CONTEXT = 'count' and a.STATNAME = 'n'
    order by a.ANALYSID;
  quit;

  proc sql noprint; select count(*) into :nobs trimmed from _cn; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &output_id に例数の結果値がない。表を作らない;
    %return;
  %end;

  data _cn2;
    set _cn;
    /* 書式は put で文字にする。define 側の format= にするとセル台帳に生値が入る */
    length NCNT $12;
    NCNT = strip(put(_n, 8.0));
    keep ANALYSID CATEG NCNT;
  run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %_tlfcells(_cn2, &lblid, tab_count, %str(CATEG NCNT))

  proc report data=_cn2 nowd;
    column ANALYSID CATEG NCNT;
    define ANALYSID / order noprint;
    define CATEG    / display "%lblfx(categ)" width=40;
    define NCNT     / display "%lblfx(ncnt)"  width=10;
  run;
  title;
  %_tlfclose
%mend tab_count;

/*========================================================================================
  1.8 コース別の実施状況表（SAP 5.3.4～5.3.6）
  SAP の図表案は1節=1表で、コースを行ブロックとして積む形。%tab_bg は行項目と水準の
  2列しか持たず、薬剤ごとの減量とTKI区分ごとの投与量を1つの表へ並べられないため
  別の型にした。列は コース／薬剤・区分／項目／区分／要約 の5つ。
  コースの並びは ARD が持たないので levels= が決める（M1-3・M10-12・M4-6 の文字順では
  SAP の並びにならない）。GROUP1L を薬剤・区分の列に出すのは GROUP1 が変数名を持つ
  ときだけで、TKI区分の例数（GROUP1 が空で GROUP1L='TKIGROUP'）は項目の列で表せる。
  行の並びは コース順 → 解析ID → 水準の識別子。水準は表示名ではなく識別子で並べるので
  日本語版と英語版で行の並びが変わらない。
========================================================================================*/

%macro tab_crs(output_id=, lblid=, levels=);
  %local nobs i nc;
  %let nc = %sysfunc(countw(&levels, |));

  data _crsord;
    length SUBSET $20;
    %do i = 1 %to &nc;
      SUBSET = "%scan(&levels, &i, |)"; _co = &i; output;
    %end;
    keep SUBSET _co;
  run;

  proc sql;
    create table _cs as
    select o._co, a.ANALYSID, a.GROUP1, a.GROUP1L, a.VARIABLE, a.VARLEVEL,
           coalescec(s.LVLBL, a.SUBSET)                  as COURSEL length=60,
           coalescec(g.LVLBL, put(a.GROUP1L,  $bgitem.)) as GRPL    length=200,
           coalescec(v.LVLBL, put(a.VARIABLE, $bgitem.)) as ITEML   length=200,
           coalescec(l.LVLBL, a.VARLEVEL)                as LEVELL  length=200,
           max(a.CONTEXT) as CONTEXT length=20,
           max(case when a.STATNAME='n'      then a.STAT end) as _n,
           max(case when a.STATNAME='nmiss'  then a.STAT end) as _nm,
           max(case when a.STATNAME='mean'   then a.STAT end) as _mean,
           max(case when a.STATNAME='sd'     then a.STAT end) as _sd,
           max(case when a.STATNAME='median' then a.STAT end) as _med,
           max(case when a.STATNAME='min'    then a.STAT end) as _min,
           max(case when a.STATNAME='max'    then a.STAT end) as _max,
           max(case when a.STATNAME='p'      then a.STAT end) as _p
    from ard.ard as a
         inner join _crsord as o on strip(a.SUBSET)   = strip(o.SUBSET)
         left  join _lvcat  as s on strip(a.SUBSET)   = s.LVKEY
         left  join _lvcat  as g on strip(a.GROUP1L)  = g.LVKEY
         left  join _lvcat  as v on strip(a.VARIABLE) = v.LVKEY
         left  join _lvcat  as l on strip(a.VARLEVEL) = l.LVKEY
    where a.OUTPUTID = "&output_id"
    group by o._co, a.ANALYSID, a.GROUP1, a.GROUP1L, a.VARIABLE, a.VARLEVEL,
             s.LVLBL, g.LVLBL, v.LVLBL, l.LVLBL, a.SUBSET;
  quit;

  /* proc sql の再マージで同じ行が統計量の数だけ出る。値は同一なので畳む（%tab_bg と同じ） */
  proc sort data=_cs nodupkey; by _co ANALYSID VARLEVEL GROUP1L VARIABLE; run;

  proc sql noprint; select count(*) into :nobs trimmed from _cs; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &output_id に結果値がない。表を作らない;
    %return;
  %end;

  data _cs2;
    set _cs;
    length COURSE $60 GRP $200 ITEM $200 LEVEL $200 VALUE $60;
    COURSE = COURSEL;
    GRP    = ifc(GROUP1 = ' ', ' ', GRPL);
    if CONTEXT = 'count' then do;
      /* 例数の行は VARLEVEL（COURSEDONE・TKIDOSED）が何を数えたかを持つ */
      ITEM  = LEVELL;
      LEVEL = ' ';
      VALUE = strip(put(_n, 8.0));
    end;
    else if CONTEXT = 'continuous' then do;
      ITEM  = ITEML;
      LEVEL = ' ';
      VALUE = strip(put(_med, 12.1)) || ' [' || strip(put(_min, 12.1)) || ', '
              || strip(put(_max, 12.1)) || "] %lblfx(mean) " || strip(put(_mean, 12.1))
              || ' SD ' || strip(put(_sd, 12.1));
      if _nm > 0 then VALUE = strip(VALUE) || " %lblfx(missing)" || strip(put(_nm, 8.0));
    end;
    else do;
      ITEM  = ITEML;
      LEVEL = LEVELL;
      VALUE = strip(put(_n, 8.0)) || ' (' || strip(put(_p, 8.1)) || ')';
    end;
    keep _co ANALYSID VARLEVEL COURSE GRP ITEM LEVEL VALUE;
  run;

  proc sort data=_cs2; by _co ANALYSID VARLEVEL; run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  title3 justify=left "%lblfx(note_bg)";
  /* 脚注はカタログに登録がある表だけに付ける。未登録のまま参照すると
     マクロ変数が解決できず WARNING になる */
  %if %symexist(L_fo_&lblid) %then %do;
    footnote1 justify=left "%lbl(fo, &lblid)";
  %end;
  %_tlfcells(_cs2, &lblid, tab_crs, %str(COURSE GRP ITEM LEVEL VALUE))

  /* missing は必須。ORDER 変数（ここでは VARLEVEL）が欠測の行を proc report は既定で
     落とすため、連続量の行（水準を持たない）が黙って印字されなくなる。台帳は表示前の
     データセットから貯めるので、突合では気づけない（2026-08-20 に33行の脱落を検出）*/
  proc report data=_cs2 nowd missing;
    column _co ANALYSID VARLEVEL COURSE GRP ITEM LEVEL VALUE;
    define _co      / order noprint;
    define ANALYSID / order noprint;
    define VARLEVEL / order noprint;
    define COURSE   / display "%lblfx(course)"    width=10;
    define GRP      / display "%lblfx(drug_grp)"  width=26;
    define ITEM     / display "%lblfx(item)"      width=32;
    define LEVEL    / display "%lblfx(categ)"     width=26;
    define VALUE    / display "%lblfx(summary)"   width=46;
  run;
  title; footnote;
  %_tlfclose
%mend tab_crs;


/*========================================================================================
  1.9 有害事象の最悪グレード表（SAP 5.4.7.1・5.4.7.3・5.4.7.6）
  ARD の VARIABLE が有害事象の項目名を持つので、そこから直接組む。
========================================================================================*/

%macro tab_aegr(output_id=, lblid=, filter=);
  %local nobs;
  /* filter に * を含む宣言（SUBSET=* and GROUP1L=*）は、ARD が持つ TKI区分 × 治療相の
     組合せで表を分ける（SAP 5.4.7.3 の図表案）。組合せの正本を ARD に置いたままにしたい
     ので、宣言を組合せの数だけ並べない。並びは TKI区分 → 治療相。表題は label-catalog の
     「Adverse Events &ph &tk」を title 文の二重引用符の中で SAS が解決する。R系
     （TLF.R の d_tab_aegr）も同じ印を見て同じ順に分ける */
  %if %index(&filter, *) %then %do;
    %local i n ph tk;
    proc sql noprint;
      create table _aesp as
      select distinct GROUP1L as PHASE length=20, SUBSET as TKIG length=20
      from ard.ard where OUTPUTID = "&output_id"
      order by TKIG, PHASE;
      select count(*) into :n trimmed from _aesp;
    quit;
    %do i = 1 %to &n;
      proc sql noprint;
        select PHASE, TKIG into :ph trimmed, :tk trimmed from _aesp(firstobs=&i obs=&i);
      quit;
      %tab_aegr(output_id=&output_id, lblid=&lblid,
                filter=%str(GROUP1L="&ph" and SUBSET="&tk"))
    %end;
    %return;
  %end;

  proc sql;
    create table _ag as
    select GROUP1L as PHASE length=20, SUBSET as TKIG length=20,
           VARIABLE as AETERM length=80,
           max(case when STATNAME='N'                                then STAT end) as DEN,
           max(case when STATNAME='n' and VARLEVEL='Grade 1-2'       then STAT end) as G12,
           max(case when STATNAME='n' and VARLEVEL='Grade 3'         then STAT end) as G3,
           max(case when STATNAME='n' and VARLEVEL='Grade 4'         then STAT end) as G4,
           max(case when STATNAME='n' and VARLEVEL='Grade 5'         then STAT end) as G5
    from ard.ard
    where OUTPUTID = "&output_id" %if %length(&filter) %then and &filter;
    group by GROUP1L, SUBSET, VARIABLE;
  quit;

  proc sql noprint; select count(*) into :nobs trimmed from _ag; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &output_id. / &filter. に結果値がない。表を作らない;
    %return;
  %end;

  proc sort data=_ag; by PHASE TKIG AETERM; run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %_tlfcells(_ag, &lblid, tab_aegr, %str(AETERM DEN G12 G3 G4 G5))

  /* missing は必須。ORDER 変数（PHASE・TKIG）が欠測の行を proc report は既定で落とすため、
     Out-5.4.7.1 と 5.4.7.6 のように TKIG が全行で欠測の表が本文に1行も出ていなかった
     （表題だけが出る。台帳は表示前のデータセットから貯めるので突合では気づけない。
     2026-08-20 に検出）*/
  proc report data=_ag nowd missing;
    column PHASE TKIG AETERM DEN G12 G3 G4 G5;
    define PHASE  / order noprint;
    define TKIG   / order noprint;
    define AETERM / display "%lblfx(ae)" width=48;
    define DEN    / display "%lblfx(denom)"      format=4.0;
    define G12    / display 'Grade 1-2' format=4.0;
    define G3     / display 'Grade 3'   format=4.0;
    define G4     / display 'Grade 4'   format=4.0;
    define G5     / display 'Grade 5'   format=4.0;
  run;
  title;
  %_tlfclose
%mend tab_aegr;


/*========================================================================================
  第2章 前処理

  結果値の集計ではない図表の元データを作る。宣言（docs/metadata/tlf-index.csv）にはデータセット名
  を持たせない。SAS のデータセット名は実装の詳細で、正本に混ぜると R系が読めない列に
  なるため。表示型が表番号から前処理を引く（R系の d_tab_list も同じ形）。
========================================================================================*/

/* 分子遺伝学的効果の23評価時点。正本は docs/metadata/mr-timepoint.csv（ARD.sas 第11章と同じ表）。
   表 5.4.3.1（%tab_prop_tp）が行の並びと表示名に、表 5.4.3.2（%tab_mrlist）が列の並びと
   列見出しに使う。2度目以降は読み直さない */
%macro _tdmr_load;
  %if not %sysfunc(exist(work._tdmr)) %then %do;
    filename _mrcsv "&repo_root/docs/metadata/mr-timepoint.csv" encoding='utf-8';
    proc import out=work._tdmr datafile=_mrcsv dbms=csv replace;
      getnames=yes;
      guessingrows=max;
    run;
    filename _mrcsv clear;
    %put NOTE: [TLF] 評価時点を読んだ: docs/metadata/mr-timepoint.csv;
  %end;
%mend _tdmr_load;

/* 表 5.4.13.2 ABL1変異解析の症例一覧（SAP 5.4.13）。結果値ではないので ARD には持たせず
   ADSL から直接組む。R系は list_abl() が同じものを作る */
%macro _list_abl;
  data _abllist;
    set ads.adsl(where=(FASFL='Y' and not missing(ABLMUT)));
    length CTX $12 HSCTC $4 TRGDYC $8 RELC $40;
    CTX   = ifc(ABLMUTCT = "PN CHANGE", "%lblfx(ctx_pn)", ifc(ABLMUTCT = "RELAPSE", "%lblfx(ctx_relapse)", " "));
    HSCTC = ifc(HSCTFL = "Y", "%lblfx(yes)", "%lblfx(no)");
    if      ABLMUTCT = 'PN CHANGE' then TRGDT = TKICHGDT;
    else if ABLMUTCT = 'RELAPSE'   then TRGDT = RELDT;
    if not missing(ABLMUTDT) and not missing(TRGDT) then TRGDY = ABLMUTDT - TRGDT;
    /* 契機からの日数も文字にする。define 側の format= だとセル台帳に生値が入る */
    TRGDYC = strip(put(TRGDY, best8.));
    /* 検査後の血液学的再発（SAP 5.4.13 ※5・※6）。CE 由来の RELDT が検査日より後なら
       再発ありとし、検査の契機が再発である症例は「－」にする */
    if ABLMUTCT = 'RELAPSE' then RELC = "%lblfx(notapplic)";
    else if not missing(RELDT) and not missing(ABLMUTDT) and RELDT > ABLMUTDT
         then RELC = catx(' ', "%lblfx(yes)", cats('(', put(RELDT, yymmdd10.), ')'));
    else RELC = "%lblfx(no)";
    /* 日付の書式は明示する。R系が ISO 文字列を出すので合わせる */
    format ABLMUTDT TRGDT yymmdd10.;
    keep SUBJID CTX ABLMUTDT TRGDT TRGDYC ABLMUT HSCTC RELC;
  run;
  /* ADSL.ABLMUT は識別子（MUTNONE 等）なので表示名に引き当てる。SDTM を ASCII だけで
     構成したため和文は docs/metadata/label-catalog.csv の kind=level が持つ（2026-08-20）*/
  proc sql;
    create table _abllist2 as
    select a.*, coalescec(c.LVLBL, a.ABLMUT) as ABLMUTL length=40
    from _abllist as a left join _lvcat as c on strip(a.ABLMUT) = c.LVKEY;
  quit;
  proc sort data=_abllist2 out=_abllist; by CTX SUBJID; run;
%mend _list_abl;


/*========================================================================================
  第3章 宣言の駆動

  図表の宣言（どの表番号を、どの表示型で、どの解析から描くか）の正本は
  docs/metadata/tlf-index.csv で、SAS系・R系・トレーサビリティ索引の3つが同じものを読む。設計は
  docs/spec/tlf-declaration-design.md。
========================================================================================*/

/*========================================================================================
  1.13 参考併記の表（SAP 5.4.9）

  本試験と PhALL208・PhALL213 を3列で並べる。行の定義と他2試験の文献値は
  docs/metadata/reference-table-rows.csv が持ち、文献値は docs/metadata/reference-values.csv が持つ。
  文献値は解析の結果ではないので ARD には置かない
  （ARD は本試験のデータから作るもので、外から持ち込んだ値を混ぜない）。本試験の値は行ごとに
  違う解析から引くため、宣言に analysis_id を1つ書く形にしない。
  行ごとの引き方は仕様 CSV の stat 列が決める。
    n_total ... 例数（ARD の N）
    pct_n   ... 割合。<p>% (<n>/<N>)
    km_ci   ... KM の時点推定。<surv>% (95%CI: <lcl>-<ucl>%)。surv・lcl・ucl は 0-1 の比率
    空      ... 本試験でも値を出さない行（見出しの行、時点別の内訳に譲る行）
========================================================================================*/

%macro tab_ref(lblid=, rows=metadata/reference-table-rows.csv, vals=metadata/reference-values.csv);
  %local nobs;
  /* 行の定義（並び・引く解析・引き方）と文献値を別のファイルに持つ。文献値は試験ごとに
     行が増える縦持ち（docs/metadata/reference-values.csv。出典と注記は reference-values-source.md）、
     行の定義は表の構造（docs/metadata/reference-table-rows.csv）で、item で結合する。
     空欄の多い列を数値と判定されないよう infile で読む（tlf_read と同じ理由） */
  data _refrow;
    infile "&repo_root/docs/&rows" dsd dlm=',' truncover firstobs=2
           encoding='utf-8' lrecl=1024;
    length _ord 8 _item $40 _lab $40 _aid $40 _lv $40 _stat $12;
    input _ord _item $ _lab $ _aid $ _lv $ _stat $;
  run;
  data _refval;
    infile "&repo_root/docs/&vals" dsd dlm=',' truncover firstobs=2
           encoding='utf-8' lrecl=1024;
    length _trial $20 _item $40 _val $120 _note $200 _src $80;
    input _trial $ _item $ _val $ _note $ _src $;
  run;

  proc sql;
    create table _refj as
    select r._ord, r._lab, r._stat,
           max(case when v._trial = 'PhALL208' then v._val else '' end) as _t208 length=120,
           max(case when v._trial = 'PhALL213' then v._val else '' end) as _t213 length=120,
           max(case when a.STATNAME = 'n'    then a.STAT else . end) as _n,
           max(case when a.STATNAME = 'N'    then a.STAT else . end) as _bn,
           max(case when a.STATNAME = 'p'    then a.STAT else . end) as _p,
           max(case when a.STATNAME = 'surv' then a.STAT else . end) as _s,
           max(case when a.STATNAME = 'lcl'  then a.STAT else . end) as _l,
           max(case when a.STATNAME = 'ucl'  then a.STAT else . end) as _u
    from _refrow as r
         left join _refval as v on strip(r._item) = strip(v._item)
         left join ard.ard as a
           on strip(a.ANALYSID) = strip(r._aid) and strip(a.VARLEVEL) = strip(r._lv)
    group by r._ord, r._lab, r._stat
    order by r._ord;
  quit;

  proc sql noprint; select count(*) into :nobs trimmed from _refj; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &lblid の行の定義が読めない。表を作らない;
    %return;
  %end;

  data _ref;
    set _refj;
    length ITEM $200 OWN $60 T208 $120 T213 $120;
    ITEM = strip(put(_lab, $bgitem.));
    if missing(ITEM) then ITEM = strip(_lab);
         if missing(_stat)                          then OWN = '';
    else if _stat = 'n_total' and not missing(_bn)  then OWN = strip(put(_bn, 8.0));
    else if _stat = 'pct_n'   and not missing(_p)
         then OWN = catx(' ', cats(put(_p, 8.1), '%'),
                         cats('(', put(_n, 8.0), '/', put(_bn, 8.0), ')'));
    else if _stat = 'km_ci'   and not missing(_s)
         /* cats は引数の前後の空白を落とすので「(95%CI: 」の末尾の空白が消える。
            R 側と1文字ずれるため、空白は catx の区切りで入れる */
         then OWN = catx(' ', cats(put(100 * _s, 8.1), '%'), '(95%CI:',
                         cats(put(100 * _l, 8.1), '-',
                              put(100 * _u, 8.1), '%)'));
    else OWN = '-';
    T208 = _t208;
    T213 = _t213;
    keep _ord ITEM OWN T208 T213;
  run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  footnote1 justify=left "%lbl(fo, &lblid)";
  %_tlfcells(_ref, &lblid, tab_ref, %str(ITEM OWN T208 T213))

  proc report data=_ref nowd;
    column _ord ITEM OWN T208 T213;
    define _ord / order noprint;
    define ITEM / display "%lbl(ro, &lblid)"  width=34;
    define OWN  / display "%lblfx(ref_own)"   width=26;
    define T208 / display "%lblfx(ref_208)"   width=26;
    define T213 / display "%lblfx(ref_213)"   width=30;
  run;
  title; footnote;
  %_tlfclose
%mend tab_ref;


/* 宣言を読む。proc import は空欄の多い列を数値と判定して宣言を黙って落とすので使わない。
   列の並びは CSV のヘッダで固定し（並びの検査は scripts/check-tlf-index.py が持つ）、
   ヘッダ行は読み飛ばす。CSV は BOM 付き UTF-8（Excel で開くため）で、BOM はヘッダ行に
   だけ乗るので firstobs=2 で避けられる */
%macro tlf_read(path=, out=work._tlfidx);
  %if %length(&path) = 0 %then %let path = &repo_root/docs/metadata/tlf-index.csv;
  data &out;
    infile "&path" dsd dlm=',' truncover firstobs=2 encoding='utf-8' lrecl=32767;
    length seq 8 lblid $20 display $20 analysis_id $40 output_id $40 filter $200
           groups $200 levels $200 item_var $40 item_label $200 vars $200 labels $200
           paramcd $20 where $100 group $20 blocks $600;
    input seq lblid $ display $ analysis_id $ output_id $ filter $ groups $ levels $
          item_var $ item_label $ vars $ labels $ paramcd $ where $ group $ blocks $;
  run;
  proc sort data=&out; by seq; run;
%mend tlf_read;

/* 宣言を seq の順に描く。空でない列だけを「列名=値」で連ねて表示型へ渡す。列名がそのまま
   引数名なので、列名と引数名の対応表を持たない。call execute を使わないのは、積む文字列に
   % や & が混じるとキューへ入れる前にマクロ言語が解決してしまうため */
%macro tlf_run(idx=work._tlfidx);
  %local n i _disp _args;
  proc sql noprint; select count(*) into :n trimmed from &idx; quit;
  %put NOTE: [TLF] 宣言 &n 件を描く（正本 docs/metadata/tlf-index.csv）;
  %do i = 1 %to &n;
    data _null_;
      set &idx(firstobs=&i obs=&i);
      length _a $8000;
      _a = 'lblid=' || strip(lblid);
      array _v{*} analysis_id output_id filter groups levels item_var item_label
                  vars labels paramcd where group blocks;
      do _j = 1 to dim(_v);
        if not missing(_v[_j]) then
          _a = strip(_a) || ',' || strip(vname(_v[_j])) || '=' || strip(_v[_j]);
      end;
      call symputx('_disp', display, 'L');
      call symputx('_args', _a, 'L');
    run;
    %&_disp.(&_args)
  %end;
%mend tlf_run;
