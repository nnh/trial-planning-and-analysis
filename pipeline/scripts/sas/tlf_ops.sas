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
  設計は docs/reporting/traceability-design.md。
========================================================================================*/

%global lang;

filename _labcsv "&repo_root/docs/metadata/label-catalog.csv" encoding='utf-8';
proc import out=_labcat datafile=_labcsv dbms=csv replace;
  getnames=yes;
  guessingrows=max;
run;
filename _labcsv clear;

/*========================================================================================
  事前規定の水準集合。正本は docs/metadata/level-sets.csv（C3-002。2026-09-03）。宣言表の
  levels 列と表示型の既定値が同じ集合を書き写していたのをやめ、集合IDで指す形にした。
  ここで作る _lvsetd は表示の順（display_order。空の集合は impl_order）に並べたもので、
  ARD 側が使う実装の列挙順とは別に持つ。2つを1つにすると図表の行順が変わる。
  CSV は1度だけ読む。並びの列は proc import が全て空だと文字型で読むので、型に依らず
  vvalue で数値へ直す（_lvcat の order・visitnum と同じ作法）。
========================================================================================*/

filename _lscsv "&repo_root/docs/metadata/level-sets.csv" encoding='utf-8';
proc import out=_lvsets0 datafile=_lscsv dbms=csv replace;
  getnames=yes;
  guessingrows=max;
run;
filename _lscsv clear;

data _lvsetd0;
  set _lvsets0;
  length SETID $40 LEVEL $80;
  SETID = strip(set_id);
  LEVEL = strip(level);
  _IO = input(strip(vvalue(impl_order)), ?? best12.);
  _DO = input(strip(vvalue(display_order)), ?? best12.);
  if missing(_DO) then _DO = _IO;
  keep SETID LEVEL _IO _DO;
run;
proc sort data=_lvsetd0; by SETID _DO _IO; run;

data _lvsetd;
  set _lvsetd0;
  by SETID;
  length LVSTR $400;
  retain LVSTR;
  if first.SETID then LVSTR = strip(LEVEL);
  else                LVSTR = catx('|', LVSTR, strip(LEVEL));
  if last.SETID;
  keep SETID LVSTR;
run;

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

  /* 表番号をキーに持つ文言はマクロ変数へ。名前は L_<種別2文字>_<キーの記号を _ に置換>。
     共通注記（kind=fixed のうちキーが note_ で始まるもの）も同じ形で持つ。注記は印を
     含むので、出力形式（$lblfx）が返す素の文字列ではなく %superq で渡せる形が要る */
  data _null_;
    set _labcat;
    length _lab $2000 _nm $40;
    %if %upcase(&lang) = EN %then %do; _lab = strip(label_en); %end;
    %else %do;                        _lab = strip(label_ja); %end;
    if missing(_lab) then return;
    if not (strip(kind) in ('title', 'subtitle', 'rowlbl', 'footnote')
            or (strip(kind) = 'fixed' and index(strip(key), 'note_') = 1)) then return;
    _nm = cats('L_', substr(strip(kind), 1, 2), '_', strip(key));
    call symputx(_nm, _lab, 'G');
  run;

  /* 注記の印（&_n・&_dec など）の宣言。正本は label-catalog.csv の kind=notemark で、
     印の名前（key）と値の出どころ（value_source）だけを持つ。印の一覧をソースへ書かない
     ので、印を1つ足せば宣言を読む両系統へ同時に届く（C3-202。R 系は note_marks が同じ
     宣言を読む）。並びは名前の長さの降順にする。&_n を先に置き換えると &_nc が "87c" に
     なるためで、順序は名前の長さから機械的に決める（並びを人が列挙しない。C3-203）*/
  data _nmdcl;
    set _labcat(where=(strip(kind) = 'notemark'));
    length MK $40 SRC $60 LN 8;
    MK = strip(key);
    SRC = strip(value_source);
    LN = length(MK);
    keep MK SRC LN;
  run;
  proc sort data=_nmdcl; by descending LN MK; run;
  %global _nmn _peaid;
  %let _nmn = 0;
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

/* 注記の印の値を作る。どの印にどの値を入れるかは宣言（_nmdcl）が持ち、ここは宣言の行を
   なぞるだけで印の名前を持たない（C3-202）。値の出どころは2種類ある。ard:<統計量名> は
   その図表の解析の ARD 行からその統計量を引き（同じ統計量の行が複数あるときは最大。
   R 系の stat_of と同じ）、pe:<名前> は %_pemake が作るマクロ変数 _pe<名前> から引く。
   判定は %_pemake がその解析を描いているときにだけ作るので、別の解析を描いている間は
   古い値を使わない（R 系の prim_values は解析が違えば NULL を返す）*/
%macro _nvset(aid);
proc sql noprint;
  create table _nmard as
    select strip(STATNAME) as SN length=40, max(STAT) as SV
      from ard.ard where ANALYSID = "&aid" and not missing(STAT)
      group by strip(STATNAME);
quit;
data _null_;
  length SN $40 SV 8 PV $60;
  if _n_ = 1 then do;
    declare hash a(dataset: '_nmard');
    a.definekey('SN');
    a.definedata('SV');
    a.definedone();
  end;
  set _nmdcl end=_last;
  /* 置き換えの順（名前の長さの降順）に番号を振る。%_fosub はこの番号でなぞる。
     値の出どころも番号で控える。注記を落としたときの記録に、どこから引けなかったかを
     書くため（C3-206）*/
  call symputx(cats('_nmk', _n_), MK, 'G');
  call symputx(cats('_nms', _n_), SRC, 'G');
  call symputx(MK, '', 'G');
  if scan(SRC, 1, ':') = 'ard' then do;
    SN = scan(SRC, 2, ':');
    if a.find() = 0 then call symputx(MK, SV, 'G');
  end;
  else if scan(SRC, 1, ':') = 'pe' then do;
    PV = cats('_pe', scan(SRC, 2, ':'));
    if symexist(PV) and symget('_peaid') = "&aid" then call symputx(MK, symget(PV), 'G');
  end;
  if _last then call symputx('_nmn', _n_, 'G');
run;
%mend _nvset;

/* 注記が持つ印を実際の値へ置き換える。%lbl は %superq で文字をそのまま返すため、
   title・footnote の二重引用符へ置いてもマクロ変数として解決されない（%ttlsub と同じ
   事情）。1つでも置き換えられない印があれば注記ごと落とす。印が残ったまま印字すると
   読み手に意味の無い文字列が見えるためで、共通注記・図表別脚注のどちらも、どの表示型でも
   この置き換えを通る（C3-204。R 系は tlf_ops.R の subst_note が同じ契約を持つ）。
   落ちた注記は成果物からは見えない。脚注の無い普通の表と区別が付かないので、図表番号・
   注記のキー・落ちた印とその出どころ・理由の記号を行頭 ERROR で残す。ERROR の数は
   scripts/run-all-sas.py が数えて非0で終えるため、注記の消えた図表は納品へ進まない
   （C3-206。R 系は subst_note が同じ4項目を tlf_miss へ残し、STRICT で非0になる）。
   その場では止めずに続けるのも R 系と同じで、1回の実行で落ちた注記をすべて挙げる */
%macro _fosub(txt, lblid=, key=);
%local _fs _fi _fk;
%let _fs = %superq(txt);
%do _fi = 1 %to &_nmn;
  %let _fk = &&_nmk&_fi;
  %if %index(%superq(_fs), %str(&)&_fk) %then %do;
    /* 置き換えの結果は %qsysfunc でクォートする。表示文言には % が入る（「95%信頼区間」
       「&_est%」）ため、素の %sysfunc の返り値を %let で受けると % の次の語がマクロ
       呼び出しとして解決され「無効なSAS名です」で落ちる（2026-08-30 に実測） */
    %if %length(%superq(&_fk)) %then
      %let _fs = %qsysfunc(tranwrd(%superq(_fs), %str(&)&_fk, %superq(&_fk)));
    %else %do;
      /* マクロ変数の参照はピリオドで閉じる。全角の括弧を続けると、その1文字目までを
         変数名と読んで「シンボリック変数名に英文字、数字、下線以外の文字が含まれて
         います」で落ちる（2026-08-31 に実測）*/
      %put ERROR: [TLF] NOTE-VAL: [&lblid] 注記 &key を落とす。印 %str(&)&_fk.（出どころ &&_nms&_fi..）の値を作れない: %superq(_fs);
      %let _fs = ;
    %end;
  %end;
%end;
/* 宣言に無い印が残っていれば、正本が実装の知らない印を使っている。落として記録する
   （検査 scripts/check-tlf-index.py が正本の側で先に捕まえる）*/
%if %index(%superq(_fs), %str(&)_) %then %do;
  %put ERROR: [TLF] NOTE-DECL: [&lblid] 注記 &key を落とす。宣言の無い印が残る: %superq(_fs);
  %let _fs = ;
%end;
%superq(_fs)
%mend _fosub;

/* 注記は二層で、共通注記（kind=fixed の note_ で始まるキー。表示型ごとの読み方）を
   title3 へ、図表別脚注（kind=footnote。キーは図表番号）を footnote1 へ出す。層ごとに
   置き換えるので、片方が組めなくてももう片方は残る（C3-216・C3-217）。
   %_nvset は proc sql を含むので、注記が印を持つときだけ呼ぶ */

/* 共通注記。表示型が自分の読み方のキーと図表番号を渡す。図表番号を渡すのは、注記が
   落ちたときにどの図表から消えたかを記録に残すためである（C3-206）*/
%macro tlfnote(key, aid=, lblid=);
%local _ntx;
%if %symexist(L_fi_&key) %then %do;
  %if %index(%superq(L_fi_&key), %str(&)_) %then %do; %_nvset(&aid) %end;
  %let _ntx = %_fosub(%superq(L_fi_&key), lblid=&lblid, key=fixed/&key);
  %if %length(%superq(_ntx)) %then %do;
    title3 justify=left "%superq(_ntx)";
  %end;
%end;
%mend tlfnote;

/* 図表別脚注。カタログに登録がある図表だけに付ける。未登録のまま参照するとマクロ変数が
   解決できず WARNING になる。R 側は lab("footnote", ...) が空を返すので口が常に開いており、
   SAS だけ表示型ごとに口の有無が分かれていた（2026-08-30 に C2-212 として検出。R 側は
   逆に tab_prop_grp_multi・tab_prop_tp が脚注を落としており、納品する R 系の4表で
   脚注が1文字も出ていなかった）。空の footnote 文を出さないのは、SAS が
   「FOOTNOTEステートメントが不明確です」を出すため */
%macro tlffoot(lblid, aid=);
%local _ftx;
/* 先に消す。footnote は title と違って次の図表まで残るため、脚注を持つ図表の脚注が、
   そのあとに描く脚注を持たない図表へ流れ込む。2026-09-01 に表 4.4.10 の脚注が
   表 4.4.11 から表 5.3.3 までの34表（表 5.2.1 患者背景を含む）へ出ていた。
   display マクロの終わりの title; footnote; だけでは、それを持たないマクロで漏れる */
footnote;
%if %symexist(L_fo_&lblid) %then %do;
  %if %index(%superq(L_fo_&lblid), %str(&)_) %then %do; %_nvset(&aid) %end;
  %let _ftx = %_fosub(%superq(L_fo_&lblid), lblid=&lblid, key=footnote/&lblid);
  %if %length(%superq(_ftx)) %then %do;
    footnote1 justify=left "%superq(_ftx)";
  %end;
%end;
%mend tlffoot;

/* 主要評価項目の判定を組む。判定の規則の正本は docs/validation/acceptance/primary-endpoint.csv
   で、閾値と時点のほかに、信頼区間の方式（ci_method）・比較の式（comparison）・推定統計量の
   名前（estimate_operation）も同じ表が持つ。統計量の名前も比較の向きもここへ写さず読む
   （C3-213。2026-08-31 まで lcl・surv・> をマクロが持っており、正本を変えても判定の規則へ
   届かなかった）。宣言の解析がその解析でないときは何も作らない。それ以外の不足は理由の
   記号で扱いを分け、受入基準そのものが読めない PE-CSV・PE-CMP・PE-CI は止め、結果値が
   足りない PE-VAL は脚注を落として続ける（2026-09-03 の運用5。C3-207・C3-213・C3-214。
   同じ記号と同じ扱いを R の prim_values も持つ）*/
%macro _pemake(analysis_id);
/* %symdel はグローバル宣言ごと消すので、そのあとの %let はマクロのローカル変数に
   なり、呼び出し元から見えなくなる。空にするだけにして宣言は残す */
%global _petp _peest _pelcl _pethr _pedec _peaid;
%let _petp = ; %let _peest = ; %let _pelcl = ; %let _pethr = ; %let _pedec = ;
/* 判定を組めた解析を控える。別の解析を描いている間に古い判定を印へ入れないためで、
   R 系の prim_values が解析の一致しないとき NULL を返すのと同じ扱いにする */
%let _peaid = ;
%local _aid _tp _thr _ci _cmp _eop _cstat _cop _cref _lcl _est _pepath _pemsg;
%let _pepath = &repo_root/docs/validation/acceptance/primary-endpoint.csv;
/* 受入基準が無いと以降の select が空を返し、解析IDの照合を素通りして脚注だけが
   黙って消える。読めないときはその場で止める（2026-08-31 に置き場を移したときに塞いだ）*/
%if %sysfunc(fileexist(&_pepath)) = 0 %then %do;
  %put ERROR: [TLF] PE-CSV: 受入基準が無い: &_pepath;
  %abort cancel;
%end;
filename _pecsv "&_pepath" encoding='utf-8';
proc import out=_pe datafile=_pecsv dbms=csv replace; getnames=yes; guessingrows=max; run;
filename _pecsv clear;
proc sql noprint;
  select value into :_aid trimmed from _pe where strip(item) = 'analysis_id';
  select value into :_tp  trimmed from _pe where strip(item) = 'timepoint';
  select value into :_ci  trimmed from _pe where strip(item) = 'ci_method';
  select value into :_cmp trimmed from _pe where strip(item) = 'comparison';
  select value into :_eop trimmed from _pe where strip(item) = 'estimate_operation';
quit;
/* 判定の規則を組むのに要る項目。1つでも欠けていれば正本として成立していない */
%if %length(%superq(_aid)) = 0 or %length(%superq(_tp)) = 0 or %length(%superq(_ci)) = 0
    or %length(%superq(_cmp)) = 0 or %length(%superq(_eop)) = 0 %then %do;
  %put ERROR: [TLF] PE-CSV: 受入基準に判定の規則が揃っていない: &_pepath;
  %abort cancel;
%end;
%if %superq(_aid) ne %superq(analysis_id) %then %return;
/* 信頼区間の方式は、この実装が計算しているものと照合する。ARD の下限は proc lifetest の
   conftype=loglog（R 系は survfit の conf.type="log-log"）で作った区間で、正本が別の方式を
   宣言しているならその下限は宣言どおりの量ではない */
%if %superq(_ci) ne loglog %then %do;
  %put ERROR: [TLF] PE-CI: 信頼区間の方式が実装と違う: 正本 &_ci / 実装 loglog;
  %abort cancel;
%end;
/* 比較の式は「<ARD の統計量> <演算子> <正本の項目>」の形だけを解釈する。読めない式を
   既定の向きで黙って判定すると、正本を変えても判定が変わらない（R の prim_subst も
   同じ形だけを受ける）*/
data _null_;
  length s $200;
  s = symget('_cmp');
  rx = prxparse('/^\s*(\w+)\s*(>=|<=|>|<)\s*(\w+)\s*$/');
  if prxmatch(rx, s) then do;
    call symputx('_cstat', prxposn(rx, 1, s), 'L');
    call symputx('_cop',   prxposn(rx, 2, s), 'L');
    call symputx('_cref',  prxposn(rx, 3, s), 'L');
  end;
run;
%if %length(&_cstat) = 0 %then %do;
  %put ERROR: [TLF] PE-CMP: comparison を解釈できない: %superq(_cmp);
  %abort cancel;
%end;
proc sql noprint;
  select value into :_thr trimmed from _pe where strip(item) = "&_cref";
quit;
%if %length(%superq(_thr)) = 0 %then %do;
  %put ERROR: [TLF] PE-CMP: comparison の右辺 &_cref が正本の項目に無い: %superq(_cmp);
  %abort cancel;
%end;
proc sql noprint;
  select STAT into :_lcl trimmed from ard.ard
   where ANALYSID = "&analysis_id" and STATNAME = "&_cstat" and strip(VARLEVEL) = "&_tp";
  select STAT into :_est trimmed from ard.ard
   where ANALYSID = "&analysis_id" and STATNAME = "&_eop" and strip(VARLEVEL) = "&_tp";
quit;
/* 推定値・比較の左辺・閾値のどれかが数値として取れないときは、脚注を落として続ける。
   欠けたまま組むと欠測を含む脚注や、閾値を数値と解せないままの判定が刷り上がるので出さない
   が（C3-214）、これは表 5.4.1 の結果値が ARD に無いという1表の話であり、原因を調べるには
   他の表も含めて1回走り切ったほうが分かる（2026-09-03 の運用5。C3-214 の対応として
   2026-08-31 に入れた %abort cancel を、受入基準そのものが読めない PE-CSV・PE-CMP・PE-CI と
   分けた）。落としたことは行頭 ERROR で残し、その数を scripts/run-all-sas.py が数えて非0で
   終えるため、脚注の消えた図表は納品へ進まない（C3-206。R 系は tlf_miss と STRICT が同じ
   働きをする）。記号は PE-VAL のまま置く。NOTE-VAL へ寄せると、印の値を作れない他の原因と
   区別が付かない。%return のあとは _peaid が空のままなので、%_nvset は pe: の印に値を入れず、
   %_fosub が注記を落として NOTE-VAL を続けて残す（脚注を持たない図表と同じ姿で刷り上がる）。
   ARD 側も同じ条件を %put WARNING: [ARD] PE-VAL で通すので、段階による扱いの差はこれで
   無くなる */
data _null_;
  if nmiss(input(symget('_est'), ?? best32.), input(symget('_lcl'), ?? best32.),
           input(symget('_thr'), ?? best32.))
    then call symputx('_pemsg', 'x', 'L');
    else call symputx('_pemsg', '',  'L');
run;
%if %length(&_pemsg) %then %do;
  %put ERROR: [TLF] PE-VAL: 主要評価項目の脚注を落とす。結果値が足りない: 解析 &analysis_id 時点 &_tp (&_eop=&_est / &_cstat=&_lcl / &_cref=&_thr);
  %return;
%end;
/* 時点は表示名で書く（R 側は lvl() を通して「3年」と出す）。$lblfx は kind=fixed しか
   持たないので、水準の表示名は _lvcat から引く。無ければ識別子のまま */
%let _petp = &_tp;
proc sql noprint;
  select LVLBL into :_petp trimmed from _lvcat where LVKEY = "&_tp";
quit;
%let _peest = %sysfunc(putn(%sysevalf(&_est * 100), 8.1));
%let _pelcl = %sysfunc(putn(%sysevalf(&_lcl * 100), 8.1));
%let _pethr = %sysfunc(putn(%sysevalf(&_thr * 100), 8.1));
/* 向きは正本の comparison が持つ。PRT 9.4 の「上回る」は厳密な > で、ちょうど等しい
   ときは超えていない */
%if %sysevalf(&_lcl &_cop &_thr) %then %let _pedec = MET;
%else                                  %let _pedec = NOT MET;
%let _peaid = &analysis_id;
%mend _pemake;

%macro lblfx(key);
%sysfunc(strip(%sysfunc(putc(&key, $lblfx.))))
%mend lblfx;

/* 図ごとに違う文言を引く。<key>_<図表ID> が登録されていればそれを、無ければ <key> を使う。
   生存曲線の横軸がこれにあたる。起算日が図によって違う（EFS・OS は登録日、RFS は LFS 到達日）
   のに、既定の「登録からの期間」を全図で使っていた（C2-064。2026-08-30 に図を見て判明）*/
%macro lblfx_for(key, lblid);
%local _v;
%let _v = %lblfx(&key._&lblid);
%if %superq(_v) = &key._&lblid %then %let _v = %lblfx(&key);
%superq(_v)
%mend lblfx_for;

/* 表題が持つ &ph・&tk を実際の値へ置き換える。%lbl は %superq で文字をそのまま返すので、
   title 文の二重引用符へ置いてもマクロ変数として解決されない。2026-08-24 に表示文言の
   % 対策で %superq を入れて以降こうなっており、表 5.4.7.3 の18ブロックが「有害事象
   &ph &tk」のまま印字されていた（2026-08-30 に独立レビューで判明。R 系の ttl_sub は
   同じことを明示的にやっていたため、R 系だけ正しく出ていた）。値を渡さないときは印を
   落として表番号だけの表題にする（目次と節の見出しに使う） */
%macro ttlsub(txt, ph=, tk=);
%local _t;
%let _t = %superq(txt);
%if %length(&ph) %then %let _t = %sysfunc(tranwrd(%superq(_t), %str(&)ph, &ph));
%else                 %let _t = %sysfunc(tranwrd(%superq(_t), %str( &)ph, %str()));
%if %length(&tk) %then %let _t = %sysfunc(tranwrd(%superq(_t), %str(&)tk, &tk));
%else                 %let _t = %sysfunc(tranwrd(%superq(_t), %str( &)tk, %str()));
%superq(_t)
%mend ttlsub;

/*========================================================================================
  1.1 生存時間解析の表（時点別の生存割合と95%信頼区間）
========================================================================================*/

%macro tab_km(analysis_id=, lblid=);
  /* _ord は集約にして group by から外す。式のまま group by に置くと proc sql が
     要約統計量を元のデータへ再マージし、時点ごとに4行（統計量の数）出てしまう
     （2026-08-20 に KM 表と CIF 表で発生。セル台帳の突合で検出）*/
  %local nobs;
  proc sql;
    create table _t as
    select coalescec(c.LVLBL, a.VARLEVEL) as TIMEPT length=40,
           /* 鍵に使う生の水準と群。group by に足しても粒度は変わらない（水準が表示名を
              決めるので1対1）。C2-068 */
           a.VARLEVEL as _vl length=200,
           a.GROUP1L  as _g1 length=60,
           max(case when a.STATNAME='surv' then a.STAT else . end) as _s,
           max(case when a.STATNAME='se'   then a.STAT else . end) as _se,
           max(case when a.STATNAME='lcl'  then a.STAT else . end) as _l,
           max(case when a.STATNAME='ucl'  then a.STAT else . end) as _u,
           max(input(compress(a.VARLEVEL, 'Y年'), best8.)) as _ord
    from ard.ard as a left join _lvcat as c on strip(a.VARLEVEL) = c.LVKEY
    /* 指定時点（Y1〜Y5）の行だけを取る。除外ではなく採用で書くのは、Mth-KM が指定時点の
       ほかに生存曲線の全イベント時点（T<年>）と中央値（MEDIAN）と例数（水準なし）を
       持つため。除外の列挙で書いていたときに曲線の行が表へ入り、表 5.4.1 が5行のところ
       89行出ていた（2026-08-29 に検出。R系の d_surv も同じ形に直した）*/
    where a.ANALYSID = "&analysis_id" and a.CONTEXT = 'survival'
      and prxmatch('/^Y[0-9]/', strip(a.VARLEVEL))
    group by coalescec(c.LVLBL, a.VARLEVEL), a.VARLEVEL, a.GROUP1L
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
    length SURVC $10 SEVC $10 CIC $30 K2 K3 K4 $410 _sci $60;
    SURVC = put(100 * _s, 6.1);
    SEVC  = put(100 * _se, 6.1);
    CIC   = catx(' - ', put(100 * _l, 6.1), put(100 * _u, 6.1));
    /* 信頼区間のセルは下限と上限を1つにまとめたもの。鍵の統計量は先に出る下限のままにし、
       セルに出た統計量を stats で数え上げる（C3-103。R 系の d_surv も同じ）*/
    _sci = catx('+', ifc(missing(_l), ' ', 'lcl'), ifc(missing(_u), ' ', 'ucl'));
    K2 = %_ky("&analysis_id", _vl, _g1, 'surv');
    K3 = %_ky("&analysis_id", _vl, _g1, 'se');
    K4 = %_ky("&analysis_id", _vl, _g1, 'lcl', stats=_sci);
    keep TIMEPT SURVC SEVC CIC K2 K3 K4;
  run;

  %_pemake(&analysis_id)
  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlfnote(note_km, aid=&analysis_id, lblid=&lblid)
  %tlffoot(&lblid, aid=&analysis_id)
  %_tlfcells(_t2, &lblid, tab_km, %str(TIMEPT SURVC SEVC CIC), keys=%str(. K2 K3 K4))

  proc report data=_t2 nowd;
    column TIMEPT SURVC SEVC CIC;
    define TIMEPT / display "%lblfx(timepoint)";
    define SURVC  / display "%lblfx(surv)";
    define SEVC   / display "%lblfx(se)";
    define CIC    / display "%lblfx(ci95)";
  run;
  title;
%mend tab_km;

/*========================================================================================
  HTML 版の図表（1図表=1ファイル）。トレーサビリティ索引（output/tlf/traceability.html）
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

/* Excel（id=x）は呼び出し側が1言語につき1ブックを開いたままにする。ここは表番号ごとに
   シートを切り替えるだけ。_xllast に直前の表番号を持ち、変わったときだけ新しいシートを
   起こす。1つの表番号で表示型を何度も呼ぶもの（%tab_aegr の TKI区分 × 治療相で18表）が
   あり、呼び出しごとにシートを起こすと同じ表番号のシートが18枚できてしまう。
   sheet_interval='now' は新しいシートを1枚起こす一度きりの指定で、そのあとは開いた
   ときの設定（'none'）に戻るため、こちらで戻さない。戻す ods excel options 文を
   表のたびに置くと、その文自体がシートを分ける。

   表 5.4.7.3（18表）だけは、こちらがシートを起こすのは1回でも（NOTE の数で88回＝
   宣言の数と一致することを確認した）、ODS EXCEL が途中で1枚増やして
   「T_5_4_7_3」と「T_5_4_7_3 2」の2枚になる。同じシートの中で表題（&ph &tk を含む）が
   変わることによる ODS 側の改シートで、こちらからは抑えられない。SAS系の Excel は
   証跡であって配布物ではないので、この1枚のずれは許容する。R系は18表を1シートへ積む
   （2026-08-29）。 */
%global tlfxlsx _lastlbl;
%macro _deftlfxlsx;
  %if %length(&tlfxlsx) = 0 %then %let tlfxlsx = 0;
%mend _deftlfxlsx;
%_deftlfxlsx

/* 表番号が変わったときだけ、個別 HTML と通し読みの錨（目次のリンク先）と Excel のシートを
   起こす。同じ表番号で表示型を何度も呼ぶもの（%tab_aegr の18表）があり、呼び出しごとに
   起こすと錨の名前が重複し、シートも表番号ごとに何枚も割れる。

   個別 HTML も同じ扱いにする。以前は呼び出しのたびに同じファイル名で開き直しており、
   1つの表番号を18回呼ぶ表 5.4.7.3 は最後の1ブロック（42行）だけが残って、前の17ブロックが
   消えていた（通し読み HTML には18表とも入っていた。2026-09-01）。開いたままにして
   18ブロックを1つのファイルへ積む。R系（TLF.R）も同じく1ファイルに18表を積む。
   1図表=1ファイルの約束は変えない。納品パッケージとトレーサビリティ索引が表番号で引く。 */
%macro _tlfopen(lblid);
  %if "&_lastlbl" ne "&lblid" %then %do;
    %if &tlfhtml = 1 %then %do;
      /* 直前の表番号の個別 HTML はここで閉じる。表示型の終わりで閉じると、同じ表番号の
         2回目の呼び出しがまた開き直すことになり、上書きが戻る */
      %if %length(&_lastlbl) %then %do;
        ods html5(id=h) close;
      %end;
      ods html5(id=h) path="&tlfdir" file="&lblid..html"
          options(svg_mode="inline") style=journal;
      ods html5(id=all) anchor="&lblid";
    %end;
    %if &tlfxlsx = 1 %then %do;
      ods excel(id=x) options(sheet_interval='now' sheet_name="&lblid");
    %end;
    %let _lastlbl = &lblid;
  %end;
%mend _tlfopen;

/*========================================================================================
  通し読み HTML の先頭に置く表題と目次。図表が88件あるので、目次が無いページは実質的に
  読めない。R系（TLF.R）は同じものを nav.toc として出す。

  目次は宣言（docs/metadata/tlf-index.csv）の順、すなわち章番号順に並べる。表示名は
  label-catalog の表題で、データセットのまま扱ってマクロ変数へ入れない（表題には
  % と & が入る。表 5.4.7.3 の「&ph &tk」は表を分ける印なので、目次では落とす）。
  リンク先は %_tlfopen が仕込む錨（表番号）。

  R系は実際に描けた図表だけを目次に載せるが、こちらは宣言をそのまま載せる。描けなかった
  宣言があるとリンクが空振りするので、そのときは駆動のログ（WARNING）で気づく。
========================================================================================*/
%macro _tlftoc(idx=work._tlfidx);
  %if &tlfhtml ne 1 %then %return;
  proc sql noprint;
    create table _toc as
    select i.seq as SEQ, i.lblid as LBLID length=20,
           case when missing(c.LBL) then i.lblid else c.LBL end as TITLE length=400
    from &idx as i
         left join (select strip(key) as KEY length=80,
                           %if %upcase(&lang) = EN %then strip(label_en);
                           %else strip(label_ja); as LBL length=400
                    from _labcat where strip(kind) = 'title') as c
              on strip(i.lblid) = c.KEY
    order by SEQ;
  quit;
  data _toc;
    set _toc;
    /* 表を分ける印（&ph・&tk）は目次では落とす。R系の ttl_sub と同じ扱い */
    TITLE = strip(prxchange('s/\s*&(ph|tk)\b//i', -1, strip(TITLE)));
  run;

  /* 目次は出力先ごとに作り分ける。HTML は同一ページ内の錨（#表番号）へ飛ばし、
     Excel はシートへの参照で飛ばす。1つの url= では両方を満たせない。ODS は url= を
     外部リンク（TargetMode="External"）として書くため、Excel では `#表番号` が
     開けない URL になり、押しても何も起きない（2026-08-29 に実測して判明）。
     Excel 側は HYPERLINK 関数をセルの数式として書き、同じブックのシートへ飛ばす。 */
  %if &tlfxlsx = 1 %then %do;
    ods html5(id=all) exclude all;
    ods excel(id=x) options(sheet_name="%lblfx(toc)");
    title1 justify=left "&tlfttl";
    title2 justify=left "%lblfx(toc)";
    ods listing close;
    proc report data=_toc nowd noheader
        style(report)={frame=void rules=none cellspacing=0}
        style(column)={fontsize=9pt borderwidth=0};
      column LBLID TITLE;
      define LBLID / display noprint;
      define TITLE / display;
      compute TITLE;
        length _f $400;
        _f = cats('formula:=HYPERLINK(',
                  quote(cats('#', strip(LBLID), '!A1')), ',',
                  quote(strip(TITLE)), ')');
        call define(_col_, 'style', cats('style={tagattr=', quote(strip(_f)), '}'));
      endcomp;
    run;
    ods listing;
    title;
    ods html5(id=all) select all;
    ods excel(id=x) exclude all;
  %end;
  title1 justify=left "&tlfttl";
  title2 justify=left "%lblfx(toc)";
  /* LISTING を閉じてから出す。目次は HTML と Excel のためのもので、表題の列（400バイト）は
     LISTING の列幅の上限（127）を超えて ERROR になる（2026-08-29）。%fig_km と同じ扱い */
  ods listing close;
  proc report data=_toc nowd noheader
      style(report)={frame=void rules=none cellspacing=0}
      style(column)={fontsize=9pt borderwidth=0};
    column LBLID TITLE;
    define LBLID / display noprint;
    define TITLE / display;
    compute TITLE;
      call define(_col_, 'style', 'style={url="#' || strip(LBLID) || '"}');
    endcomp;
  run;
  ods listing;
  title;
  %if &tlfxlsx = 1 %then %do;
    ods excel(id=x) select all;
  %end;
%mend _tlftoc;

/* 最後の表番号の個別 HTML を閉じる。途中の表番号は %_tlfopen が次を開くときに閉じるので、
   閉じ残るのは最後の1つだけ。%tlf_run が描き終わりに1度だけ呼ぶ。_lastlbl も戻して、
   同じセッションで駆動を2度回しても1つ目の表が開いたままにならないようにする */
%macro _tlfclose;
  %if &tlfhtml = 1 and %length(&_lastlbl) %then %do;
    ods html5(id=h) close;
  %end;
  %let _lastlbl = ;
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
      /* analysis_id から stat_name までの4つは、そのセルを作った ARD の行を指す（C2-068）。
         表番号までしか辿れないと、1つの表番号に多くの解析がぶら下がる表（5.4.7.3 は18ブロック
         756解析）で、どのセルがどの解析かを読み手が特定できない。
         cell_stats と key_kind は、その1行だけではセルの値を説明できないときに読み手が
         代表を単一の由来と読み違えないようにするもので、意味は %_ky の頭書き
         （C3-103・C3-104）。R 系（tlf_ops.R）と同じ名前・同じ並びにする */
      length lblid $20 display $20 row_key $200 col_label $60 value $200
             analysis_id $40 variable_level $200 group1_level $60 stat_name $20
             cell_stats $60 key_kind $8;
      row_seq = .; col_seq = .;
      call missing(of _all_);
      delete;
    run;
  %end;
%mend _cellsinit;

/* セルを作った ARD の行を指す鍵。解析ID・行の水準・列の群・統計量・セルに出た統計量の
   並び・鍵の読み方を | でつなぐ（R 系の tlf_ops.R の ky() と同じ形）。catx は空白の引数を
   落とすが区切りの '|' は残るので、欠けた要素は空のまま6つの位置が保たれる。表示型はこれで
   組んだ文字変数を %_tlfcells の keys= に渡す。C2-068

   前の4つは ARD の1行を一意に指す結合キーで、突合と索引が使う形を変えない。後ろの2つは
   その1行だけではセルの値を説明できないときに、読み手が代表を単一の由来と読み違えない
   ようにする（C3-103・C3-104）。
     stats= … セルに実際に出た統計量の名前を + でつないだ文字式。渡さないと st と同じに
              なる。「19/20」なら n+N、「7.0 - 21.4」なら lcl+ucl のように、解析ID・水準・群を
              固定したうえで由来の ARD 行をすべて数え上げられる形にする。値の無い統計量は
              表示から落ちるので、catx('+', ifc(missing(_p), ' ', 'p'), ...) の形で組む
     kind=  … 前の4つと stats で由来を数え上げられるなら渡さない。数え上げられないときだけ
              印を置く。repr は同じ値を持つ複数行のうちバイト順で最小のものを代表に選んだ
              場合（分母 N）、part は解析・部分集合が違う行も値に入っていて鍵では名指し
              できない場合。式ではなく文字定数（'repr' の形）を渡す */
/* stats= と kind= を %superq で受けてはいけない。マスクした引用符がそのまま生成テキストへ
   出て、kind='repr' が strip(' + 改行 + repr')) に割れる（2026-08-31 に単体で再現）。
   どちらの引数も & と % を含まないので、そのまま解決させる */
%macro _ky(aid, vl, g1, st, stats=, kind=);
%local _s _k;
%let _s = &stats;
%if %length(&_s) = 0 %then %let _s = &st;
%let _k = &kind;
%if %length(&_k) = 0 %then %let _k = ' ';
catx('', strip(&aid), '|', strip(&vl), '|', strip(&g1), '|', strip(&st), '|',
     strip(&_s), '|', strip(&_k))
%mend _ky;

/* ds= 表示に使ったデータセット、vars= 表示した列（並び順）、lblid=・display= は宣言のもの。
   labels= は列見出しの表示名（| 区切り。vars と同じ数・同じ順）。渡すと台帳の col_label に
   変数名ではなくこちらを記録する。列の数が宣言で変わる表示型では、変数名が位置の番号に
   なってしまい（G1・G2…）、読み手が意味を取り違える。台帳は人が読むものなので、
   何の列かが分かる文字列を残す（2026-08-29）。
   keys= は列ごとの鍵を持つ変数（空白区切り。vars= と同じ数・同じ順）。%_ky で組んだ
   「解析ID|水準|群|統計量|出た統計量|鍵の読み方」を入れると、台帳の6列へ分けて記録する。
   ARD の行を指さない列（行ラベル・文献値・一覧の症例識別子）は . を置く。keys= を渡さない
   表示型では6列すべてが空になる（C2-068・C3-103・C3-104） */
%macro _tlfcells(ds, lblid, display, vars, labels=, keys=);
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
      length _clblid $20 _cdisp $20 _crowk $200 _ccoll $60 _cval $200
             _ckey $410 _caid $40 _cvl $200 _cg1 $60 _cst $20
             _cstats $60 _ckind $8;
      set &ds;
      _clblid = "&lblid"; _cdisp = "&display";
      row_seq = _n_ + &_off;
      %local i v n k;
      %let n = %sysfunc(countw(&vars));
      _crowk = vvaluex("%scan(&vars, 1)");
      %do i = 1 %to &n;
        %let v = %scan(&vars, &i);
        col_seq = &i;
        %if %length(%superq(labels)) %then %do;
          _ccoll = "%qscan(%superq(labels), &i, |)";
        %end;
        %else %do;
          _ccoll = "&v";
        %end;
        _cval = strip(vvaluex("&v"));
        _ckey = '';
        %if %length(%superq(keys)) %then %do;
          %let k = %scan(%superq(keys), &i, %str( ));
          %if %length(%superq(k)) and %superq(k) ne . %then %do;
            _ckey = strip(vvaluex("&k"));
          %end;
        %end;
        /* 'm' は区切りが続いたときに空の要素を返させる印。これが無いと
           「解析ID||群|統計量」の空の水準が詰められて位置がずれる */
        _caid   = scan(_ckey, 1, '|', 'm');
        _cvl    = scan(_ckey, 2, '|', 'm');
        _cg1    = scan(_ckey, 3, '|', 'm');
        _cst    = scan(_ckey, 4, '|', 'm');
        _cstats = scan(_ckey, 5, '|', 'm');
        _ckind  = scan(_ckey, 6, '|', 'm');
        output;
      %end;
      keep _clblid _cdisp row_seq _crowk col_seq _ccoll _cval _caid _cvl _cg1 _cst
           _cstats _ckind;
      rename _clblid=lblid _cdisp=display _crowk=row_key _ccoll=col_label _cval=value
             _caid=analysis_id _cvl=variable_level _cg1=group1_level _cst=stat_name
             _cstats=cell_stats _ckind=key_kind;
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
      /* dlm=',' は put の項目の間に区切りを入れる。見出しは1つの文字列で書く
         （2つに分けると項目の間の区切りが増えてカンマが2つ並ぶ）*/
      if _n_ = 1 then put 'lblid,display,row_seq,row_key,col_seq,col_label,value,analysis_id,variable_level,group1_level,stat_name,cell_stats,key_kind';
      _rs = strip(put(row_seq, best12.));
      _cs = strip(put(col_seq, best12.));
      put lblid display _rs row_key _cs col_label value
          analysis_id variable_level group1_level stat_name cell_stats key_kind;
    run;
    %put NOTE: [TLF] セル台帳を書いた: &path;
  %end;
%mend _cellswrite;

/*========================================================================================
  1.2 割合の表（頻度・割合・二項95%信頼区間）

  grpcnt_id= を与えると、その解析の群ごとの件数（n）を列として右へ足す。列の並びは
  groups=（| 区切りの群の識別子）、列見出しは labels=（| 区切りの kind=fixed のキー。
  %tab_list と同じ作法）で、3つとも宣言（docs/metadata/tlf-index.csv）が持つ。群の名前も
  見出しの文言も実装は持たない。表 5.4.8 が An-5.4.8-04（事象別の件数を試験治療との
  因果関係で分けたもの）をこの口で足す。宣言を持たない表は 事象／該当件数・分母／割合／
  95%信頼区間 の4列のままで、足す側の分岐へ入らない。R 系は d_tab_prop が同じ宣言を読む。
========================================================================================*/

%macro tab_prop(analysis_id=, lblid=, grpcnt_id=, groups=, labels=);
  %local nobs _gn _gi _gcol _kcol _clab;
  %let _gn = 0;
  %if %length(%superq(grpcnt_id)) %then %let _gn = %sysfunc(countw(%superq(groups), |));
  proc sql;
    create table _p as
    select coalescec(c.LVLBL, a.VARLEVEL) as CATEG length=200,
           /* 鍵に使う生の水準と群。1解析でも GROUP1L は空とは限らない
              （An-4.4.11-CHR-major は SUBTYPE='MAJOR' を持つ）。C2-068 */
           a.VARLEVEL as _vl length=200,
           a.GROUP1L  as _g1 length=60,
           /* 宣言された定義順。カタログに order を持たない水準（結合に当たらない水準を
              含む）は 9999 にして、番号を持つ水準の後ろへ回す。R 側の lvord() と同じ */
           coalesce(c.LVORD, 9999) as _lvord,
           max(case when a.STATNAME='n'   then a.STAT else . end) as _n,
           max(case when a.STATNAME='N'   then a.STAT else . end) as _den,
           max(case when a.STATNAME='p'   then a.STAT else . end) as _p,
           max(case when a.STATNAME='lcl' then a.STAT else . end) as _l,
           max(case when a.STATNAME='ucl' then a.STAT else . end) as _u
    from ard.ard as a left join _lvcat as c on strip(a.VARLEVEL) = c.LVKEY
    where a.ANALYSID = "&analysis_id" and a.CONTEXT = 'categorical'
    group by coalescec(c.LVLBL, a.VARLEVEL), a.VARLEVEL, a.GROUP1L, c.LVORD;
  quit;

  /* proc sql の再マージで同じ水準が統計量の数（n・N・p・lcl・ucl の5つ）だけ出る。値は
     同一なので畳む。%tab_bg・%tab_km と同じ手当て（2026-08-20。31表すべてが5行ずつ
     印字されていたのを是正）*/
  /* 並びは 宣言された定義順（_lvord）→ 件数の多い順 → 識別子。定義順を先に見るのは、
     判定の水準のように読み手が決まった並びを期待する表があるためで、番号を持つ水準は
     件数に関わらずその番号順に出る（C2-049。2026-09-10）。番号を持たない水準は _lvord が
     9999 で揃うので、これまでどおり件数の多い順に落ちる。
     同点の行は表示名ではなく識別子（VARLEVEL）で並べる。表示名で並べると日本語版と
     英語版で順序が入れ替わり、同じ表の日英を並べたときに行が対応しない。突合は英語版
     どうしで行うため見えていなかった（C2-213。2026-08-30 にセル台帳の鍵で可視化）。
     R 側の d_tab_prop も同じ3つの鍵で並べるので、両系統・両言語が揃う */
  proc sort data=_p nodupkey; by _lvord descending _n _vl; run;

  /* 群別の件数を横持ちにして行（VARLEVEL）へ結ぶ。引くのは件数（n）だけにする。割合と
     信頼区間はその群の中での値で、行の列（分母は重篤な有害事象の件数）とは分母が違う。
     結果値の無い組合せは欠測のままにし、セルも鍵も空にする（ARD に無い行を指さない。
     %tab_prop_grp・%tab_aegr と同じ扱い）。R 系は d_tab_prop が同じ引き方をする */
  %if &_gn > 0 %then %do;
    proc sql;
      create table _pg as
      select VARLEVEL as _vl length=200
             %do _gi = 1 %to &_gn;
               , max(case when GROUP1L = "%scan(%superq(groups), &_gi, |)"
                           and STATNAME = 'n' then STAT else . end) as _gc&_gi
             %end;
      from ard.ard
      where ANALYSID = "&grpcnt_id" and CONTEXT = 'categorical'
      group by VARLEVEL;
    quit;
    proc sql;
      create table _pj as
      select a.* %do _gi = 1 %to &_gn; , b._gc&_gi %end;
      from _p as a left join _pg as b on strip(a._vl) = strip(b._vl);
    quit;
    /* proc sql は並びを保証しないので、結合のあとに上と同じ鍵で並べ直す */
    proc sort data=_pj out=_p; by _lvord descending _n _vl; run;
  %end;

  proc sql noprint; select count(*) into :nobs trimmed from _p; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &analysis_id に結果値がない。表を作らない;
    %return;
  %end;

  /* 足した列とその鍵の変数名。宣言の群の数だけ並ぶ */
  %let _gcol = ;
  %let _kcol = ;
  %do _gi = 1 %to &_gn;
    %let _gcol = &_gcol GC&_gi;
    %let _kcol = &_kcol KG&_gi;
  %end;

  data _p2;
    set _p;
    length NFRAC $20 PCTC $10 CIC $30 K2 K3 K4 $410 _snf _sci $60;
    %if &_gn > 0 %then %do;
      length %do _gi = 1 %to &_gn; GC&_gi $20 KG&_gi $410 %end;;
    %end;
    NFRAC = catx('/', put(_n, best8.), put(_den, best8.));
    PCTC  = put(_p, 6.1);
    CIC   = catx(' - ', put(_l, 6.1), put(_u, 6.1));
    /* 件数と分母、下限と上限を1つにまとめたセルは、先に出る方を鍵の統計量にしたまま、
       セルに出た統計量を stats で数え上げる（C3-103。R 系の d_tab_prop も同じ）*/
    _snf = catx('+', ifc(missing(_n), ' ', 'n'), ifc(missing(_den), ' ', 'N'));
    _sci = catx('+', ifc(missing(_l), ' ', 'lcl'), ifc(missing(_u), ' ', 'ucl'));
    K2 = %_ky("&analysis_id", _vl, _g1, 'n', stats=_snf);
    K3 = %_ky("&analysis_id", _vl, _g1, 'p');
    K4 = %_ky("&analysis_id", _vl, _g1, 'lcl', stats=_sci);
    %do _gi = 1 %to &_gn;
      GC&_gi = ''; KG&_gi = '';
      if not missing(_gc&_gi) then do;
        GC&_gi = strip(put(_gc&_gi, best8.));
        KG&_gi = %_ky("&grpcnt_id", _vl, "%scan(%superq(groups), &_gi, |)", 'n');
      end;
    %end;
    keep CATEG NFRAC PCTC CIC K2 K3 K4 &_gcol &_kcol;
  run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlffoot(&lblid, aid=&analysis_id)
  %if &_gn = 0 %then %do;
    %_tlfcells(_p2, &lblid, tab_prop, %str(CATEG NFRAC PCTC CIC), keys=%str(. K2 K3 K4))
  %end;
  %else %do;
    /* 足した列の変数名（GC1・GC2…）は位置の番号なので、台帳には宣言が持つ見出しの
       キー（labels= の値）を残す。4列のままの表は変数名を残す形を変えない（2026-08-29 の
       %_tlfcells の頭書き。見出しの文言そのものを入れないのは、英語の「Proportion (%)」の
       ような % を含む文言をマクロ変数へ入れないため）*/
    %let _clab = CATEG|NFRAC|PCTC|CIC;
    %do _gi = 1 %to &_gn;
      %let _clab = &_clab|%scan(%superq(labels), &_gi, |);
    %end;
    %_tlfcells(_p2, &lblid, tab_prop, %str(CATEG NFRAC PCTC CIC &_gcol),
               labels=%superq(_clab), keys=%str(. K2 K3 K4 &_kcol))
  %end;

  proc report data=_p2 nowd;
    column CATEG NFRAC PCTC CIC &_gcol;
    define CATEG / display "%lbl(ro, &lblid)" width=40;
    /* 分母の単位が表によって違う。表 5.4.8・5.4.8.1 は重篤な有害事象の件数を分母に
       するので、列名も件数と書く（C2-057。%lblfx_for が <key>_<図表ID> を先に引く） */
    define NFRAC / display "%lblfx_for(nden, &lblid)";
    define PCTC  / display "%lblfx(prop)";
    define CIC   / display "%lblfx(ci95)";
    %do _gi = 1 %to &_gn;
      define GC&_gi / display "%lblfx(%scan(%superq(labels), &_gi, |))";
    %end;
  run;
  title;
%mend tab_prop;

/*========================================================================================
  1.2b 群を列に持つカテゴリ表（1解析で群が複数あるもの。SAP 5.4.3 の3列表）
  行と列の並びは ARD が順序を持たないため、呼び出し側の levels= と groups= で決める
  （段階2で ARD 側へ移す。docs/reporting/traceability-design.md）。
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

  /* 対象症例数の行は、その群のすべての水準が持つ N の最大を出す。どの水準の行から
     来たかは決まらないので、水準はバイト順で最小のものを代表にする（R 系の
     d_tab_prop_grp の nkey() と同じ。C2-068）。代表であることは %_ky の kind= に
     repr を置いて台帳へ残す（C3-104）*/
  proc sql;
    create table _gpn as
    select GROUP1L, min(VARLEVEL) as _nlv length=200
    from _gp where _den is not null
    group by GROUP1L;
  quit;

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
           strip(put(max(a._den), 8.0)) as VALUE length=30,
           %_ky("&analysis_id", n._nlv, c.GROUP1L, 'N', kind='repr') as KEY length=410
    from _gp as a inner join _gcord as c on strip(a.GROUP1L) = strip(c.GROUP1L)
                  left  join _gpn   as n on strip(a.GROUP1L) = strip(n.GROUP1L)
    group by c._co, c.GROUP1L, n._nlv
    union all
    select c._co, b._ro, coalescec(d.LVLBL, a.VARLEVEL) as ROWLBL length=200,
           /* 割合が欠測なら括弧ごと落とす。「60 ()」のように空の括弧が残ると、
              割合が0なのか算出していないのかが読み手に分からない（C2-050。R 系は
              tlf_ops.R の np() が同じことをする） */
           catx(' ', strip(put(a._n, 8.0)),
                     ifc(missing(a._p), '', cats('(', strip(put(a._p, 8.1)), ')'))) as VALUE length=30,
           /* 「n (p)」は2つの統計量を並べたセルなので、出た方を stats で数え上げる（C3-103）*/
           %_ky("&analysis_id", a.VARLEVEL, a.GROUP1L, 'n',
                stats=catx('+', ifc(missing(a._n), ' ', 'n'),
                                ifc(missing(a._p), ' ', 'p'))) as KEY length=410
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
  /* 鍵も同じ形へ横持ちにする。結果値の無い組合せは行そのものが無いので、値と同じく
     鍵も空になる（ARD に無い行を指さない）*/
  proc transpose data=_gp2 out=_gpk(drop=_NAME_) prefix=K;
    by _ro ROWLBL;
    id _co;
    var KEY;
  run;
  data _gpt; merge _gpt _gpk; by _ro ROWLBL; run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlffoot(&lblid, aid=&analysis_id)
  %local _vl _kl;
  %let _vl = ROWLBL;
  %let _kl = .;
  %do i = 1 %to &ng; %let _vl = &_vl C&i; %let _kl = &_kl K&i; %end;
  %_tlfcells(_gpt, &lblid, tab_prop_grp, %str(&_vl), keys=%str(&_kl))

  proc report data=_gpt nowd;
    column _ro ROWLBL %do i = 1 %to &ng; C&i %end;;
    define _ro    / order noprint;
    define ROWLBL / display "%lbl(ro, &lblid)" width=32;
    %do i = 1 %to &ng;
      define C&i / display "&&_gl&i" width=18;
    %end;
  run;
  title;
%mend tab_prop_grp;
/*========================================================================================
  1.2d 群を列に持つカテゴリ表（複数の解析を行ブロックとして積む。SAP 5.4.3 の3列表）
  blocks= は「解析ID:水準1|水準2|…」を ~ で区切って並べたもの。行の並びは指定した順。
  1.2b は1解析しか扱えないため、行が複数の指標にまたがる表のために分けた。
========================================================================================*/

%macro tab_prop_grp_multi(output_id=, lblid=, groups=, blocks=);
  %local i j ng nb an lv nobs _a1;
  %let ng = %sysfunc(countw(&groups, |));
  %let nb = %sysfunc(countw(&blocks, ~));
  /* 対象症例数は先頭の行ブロックの解析から採る（下の _gpn1・_gp2）*/
  %let _a1 = %scan(%scan(&blocks, 1, ~), 1, %str(:));

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

  /* 対象症例数の行は、先頭の行ブロックの解析が持つ N を出す。表の集団を表す行なので、
     分母の違う解析を同じ列に並べる表では別の分母を拾ってはいけない（表 5.4.12 は
     死因の内訳が死亡例10、治療関連死が FAS 全体88。すべての解析の最大を採っていた頃は
     88 が出ていた。2026-09-12）。どの水準の行から来たかは決まらないので、水準は
     バイト順で最小のものを代表にする（R 系の d_tab_prop_grp_multi の nkey() と同じ。
     C2-068）。代表であることは %_ky の kind= に repr を置いて台帳へ残す（C3-104）*/
  proc sql;
    create table _gpn1 as
    select GROUP1L, min(ANALYSID) as _naid length=40
    from _gp where _den is not null and strip(ANALYSID) = "&_a1"
    group by GROUP1L;
    create table _gpn as
    select b.GROUP1L, b._naid, min(a.VARLEVEL) as _nlv length=200
    from _gp as a inner join _gpn1 as b on strip(a.GROUP1L)  = strip(b.GROUP1L)
                                       and strip(a.ANALYSID) = strip(b._naid)
    where a._den is not null
    group by b.GROUP1L, b._naid;
    /* 群ごとの対象症例数そのもの。分母がこれと違う行はセルに分母を出す */
    create table _gpden as
    select GROUP1L, max(_den) as _tden
    from _gp where strip(ANALYSID) = "&_a1" and _den is not null
    group by GROUP1L;
  quit;

  proc sql;
    /* 先頭に対象症例数の行を置く（SAP 5.4.3 の表の第1行） */
    create table _gp2 as
    select c._co, 0 as _ro, "%lblfx(nsubj)" as ROWLBL length=200,
           strip(put(max(a._den), 8.0)) as VALUE length=30,
           %_ky(n._naid, n._nlv, c.GROUP1L, 'N', kind='repr') as KEY length=410
    from _gp as a inner join _gcord as c on strip(a.GROUP1L) = strip(c.GROUP1L)
                  left  join _gpn   as n on strip(a.GROUP1L) = strip(n.GROUP1L)
    where strip(a.ANALYSID) = "&_a1"
    group by c._co, c.GROUP1L, n._naid, n._nlv
    union all
    /* 行ラベルは <水準>_<図表ID> があればそれを先に使う。同じ水準でも表によって
       説明を変えたいときの口で、表5.4.3 の MTF・MolPD・MolR がこれにあたる。
       5.4.3 では全観察期間の状態とイベントを表す行だが、5.4.3.1 では評価時点ごとの
       列になるため、水準そのものの名前を変えるわけにいかない（C2-039。R 系は
       tlf_ops.R の lvl_for が同じことをする） */
    select c._co, b._ro, coalescec(e.LVLBL, d.LVLBL, a.VARLEVEL) as ROWLBL length=200,
           /* 割合が欠測なら括弧ごと落とす。「60 ()」のように空の括弧が残ると、
              割合が0なのか算出していないのかが読み手に分からない（C2-050。R 系は
              tlf_ops.R の np() が同じことをする） */
           /* 分母が表の対象症例数と違う行は「n/N (p)」にする。分母の違う解析を同じ列に
              並べる表があるため（表 5.4.12 は死因の内訳が死亡例10、治療関連死が FAS
              全体88）。表 4.5.2.3 の「2/21」と形式が揃う（2026-09-12。R 系は
              tlf_ops.R の d_tab_prop_grp_multi の cell() が同じことをする）*/
           catx(' ', ifc(not missing(a._den) and not missing(t._tden)
                            and a._den ne t._tden,
                         cats(strip(put(a._n, 8.0)), '/', strip(put(a._den, 8.0))),
                         strip(put(a._n, 8.0))),
                     ifc(missing(a._p), '', cats('(', strip(put(a._p, 8.1)), ')'))) as VALUE length=30,
           /* 「n (p)」は2つの統計量を並べたセルなので、出た方を stats で数え上げる（C3-103）*/
           %_ky(a.ANALYSID, a.VARLEVEL, a.GROUP1L, 'n',
                stats=catx('+', ifc(missing(a._n), ' ', 'n'),
                                ifc(missing(a._p), ' ', 'p'))) as KEY length=410
    from _gp as a
         inner join _grord as b on strip(a.ANALYSID) = strip(b.ANALYSID)
                               and strip(a.VARLEVEL) = strip(b.VARLEVEL)
         inner join _gcord as c on strip(a.GROUP1L)  = strip(c.GROUP1L)
         left  join _lvcat as d on strip(a.VARLEVEL) = d.LVKEY
         left  join _lvcat as e on cats(strip(a.VARLEVEL), '_', "&lblid") = e.LVKEY
         left  join _gpden as t on strip(a.GROUP1L)  = strip(t.GROUP1L);
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
  /* 鍵も同じ形へ横持ちにする（%tab_prop_grp と同じ）*/
  proc transpose data=_gp2 out=_gpk(drop=_NAME_) prefix=K;
    by _ro ROWLBL;
    id _co;
    var KEY;
  run;
  data _gpt; merge _gpt _gpk; by _ro ROWLBL; run;

  %local _cols _kl;
  %let _cols = ROWLBL;
  %let _kl = .;
  %do i = 1 %to &ng; %let _cols = &_cols C&i; %let _kl = &_kl K&i; %end;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlffoot(&lblid)
  %_tlfcells(_gpt, &lblid, tab_prop_grp_multi, %str(&_cols), keys=%str(&_kl))

  proc report data=_gpt nowd;
    column _ro ROWLBL %do i = 1 %to &ng; C&i %end;;
    define _ro    / order noprint;
    define ROWLBL / display "%lbl(ro, &lblid)" width=40;
    %do i = 1 %to &ng;
      define C&i / display "&&_gl&i" width=18;
    %end;
  run;
  title; footnote;
%mend tab_prop_grp_multi;

/*========================================================================================
  1.2c 評価時点を行に持つカテゴリ表（1つの OUTPUTID の解析を行として並べる。SAP 5.4.3.1）
  SAP の図表案は評価時点を列に置くが、23列は A4 縦の本文幅（11,185 twips）に入らない
  （n (%) のセルで約22,800 twips 必要）。行と列を入れ替えて1表にする。内容は同じ。
  行の並びと表示名は docs/metadata/mr-timepoint.csv（%_tdmr_load）が持ち、列の並びは levels= で決める。
  宣言の subset= で渡した部分集合の解析がある水準は、割合ではなくその件数をカッコに入れる。
  部分集合の名前は試験ごとに違うので、表示型に直書きせず宣言から受ける（2026-08-29）
  （molpd・molr は88例の排他区分ではなくイベントの件数なので割合を出さない）。
========================================================================================*/

%macro tab_prop_tp(output_id=, lblid=, levels=, subset=);
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

  data _tprow0;
    set work._tdmr;
    length ROWKEY $40 ROWLBL $200 _LK $80;
    ROWKEY = strip(glabel);
    ROWLBL = strip(label);
    /* 行の表示名は mr-timepoint.csv の label。日英の表示を与えたい時点だけ label-catalog に
       kind=level で <群の識別子>_<図表ID> を登録し、そちらを先に引く。SAP の列見出しが
       内部識別子のままだった adjuvant_cmr・molpd・molr・relapse が該当する
       （C2-217。R 側は d_tab_prop_tp の tplab() が同じ引き当てをする）*/
    _LK    = cats(strip(glabel), '_', "&lblid");
    _ro    = order;
    keep ROWKEY ROWLBL _LK _ro;
  run;

  proc sql;
    create table _tprow as
    select a.ROWKEY, coalescec(b.LVLBL, a.ROWLBL) as ROWLBL length=200, a._ro
    from _tprow0 as a left join _lvcat as b on a._LK = b.LVKEY;
  quit;

  proc sql;
    create table _tpv as
    /* 解析IDは宣言が持たない（1つの OUTPUTID に評価時点の数だけ解析がある）ので、
       鍵に入れる分をここで持ち上げる。時点・水準・部分集合で解析は1つに決まるので
       group by に足しても粒度は変わらない（C2-068）*/
    select ANALYSID, GROUP1L, VARLEVEL, SUBSET,
           max(case when STATNAME='n' then STAT end) as _n,
           max(case when STATNAME='p' then STAT end) as _p
    from ard.ard
    where OUTPUTID = "&output_id" and CONTEXT = 'categorical'
    group by ANALYSID, GROUP1L, VARLEVEL, SUBSET;
  quit;

  proc sql noprint; select count(*) into :nobs trimmed from _tpv; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &output_id に結果値がない。表を作らない;
    %return;
  %end;

  proc sql;
    create table _tpc as
    select r._ro, r.ROWLBL, c._co,
           /* 部分集合の件数は角括弧に入れる。丸括弧のままだと割合と外見上まったく
              区別が付かず、同じ表の中で「例数（割合）」と「例数（別の例数）」が
              混ざる（C2-053。R 系は tlf_ops.R の nb() が同じことをする） */
           case when b._n is not null
                  then catx(' ', strip(put(a._n, 8.0)),
                            ifc(missing(b._n), '', cats('[', strip(put(b._n, 8.0)), ']')))
                else catx(' ', strip(put(a._n, 8.0)),
                          ifc(missing(a._p), '', cats('(', strip(put(a._p, 8.1)), ')')))
           end as VALUE length=30,
           /* 鍵は括弧の中身（部分集合の件数）ではなく先に出る件数を指す。
              角括弧に部分集合の件数が入るセルは、その件数が別の解析（別の SUBSET）の行から
              来るため鍵の4つでは名指しできない。kind に part を置いて、鍵が値の一部しか
              説明していないことを台帳へ残す。丸括弧の割合は同じ行の p なので stats で
              数え上げる（C3-103。R 系の d_tab_prop_tp も同じ）*/
           case when b._n is not null then %_ky(a.ANALYSID, a.VARLEVEL, a.GROUP1L, 'n',
                                                kind='part')
                else %_ky(a.ANALYSID, a.VARLEVEL, a.GROUP1L, 'n',
                          stats=catx('+', ifc(missing(a._n), ' ', 'n'),
                                          ifc(missing(a._p), ' ', 'p')))
           end as KEY length=410
    from _tpv as a
         inner join _tprow as r on strip(a.GROUP1L)  = strip(r.ROWKEY)
         inner join _tplv  as c on strip(a.VARLEVEL) = strip(c.VARLEVEL)
         left  join _tpv   as b on strip(a.GROUP1L)  = strip(b.GROUP1L)
                               and strip(a.VARLEVEL) = strip(b.VARLEVEL)
                               and strip(b.SUBSET)   = "&subset"
    where strip(a.SUBSET) ne "&subset";
  quit;

  proc sort data=_tpc; by _ro ROWLBL _co; run;
  proc transpose data=_tpc out=_tpt(drop=_NAME_) prefix=C;
    by _ro ROWLBL;
    id _co;
    var VALUE;
  run;
  /* 鍵も同じ形へ横持ちにする（%tab_prop_grp と同じ）*/
  proc transpose data=_tpc out=_tpk(drop=_NAME_) prefix=K;
    by _ro ROWLBL;
    id _co;
    var KEY;
  run;
  data _tpt; merge _tpt _tpk; by _ro ROWLBL; run;

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

  %local _cols _kl;
  %let _cols = ROWLBL;
  %let _kl = .;
  %do i = 1 %to &nlv; %let _cols = &_cols C&i; %let _kl = &_kl K&i; %end;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlffoot(&lblid)
  %_tlfcells(_tpt, &lblid, tab_prop_tp, %str(&_cols), keys=%str(&_kl))

  proc report data=_tpt nowd;
    column _ro ROWLBL %do i = 1 %to &nlv; C&i %end;;
    define _ro    / order noprint;
    define ROWLBL / display "%lbl(ro, &lblid)" width=28;
    %do i = 1 %to &nlv;
      define C&i / display "&&_cl&i" width=12;
    %end;
  run;
  title; footnote;
%mend tab_prop_tp;

/*========================================================================================
  1.3 背景表（連続量とカテゴリを1つの表に並べる。行順は ANALYSID の連番）
========================================================================================*/

/* item_var は | 区切りで2つまで受ける。2つ渡すと行項目を「1つ目 / 2つ目」と連結する。
   ARD が行を区別する軸を2つ持つ表（Out-5.4.7.4・Out-5.4.7.5 は VARIABLE が感染症や
   併用薬、GROUP1L が治療相）で、片方しか出せず同じ行ラベルが並んでいた（2026-08-23）*/
/* filter= は同じ図表グループの一部だけを描くための絞り込み（%tab_aegr と同じ書き方で、
   宣言の filter 列がそのまま来る）。1つの Output が別々の表になる集計を持つときに要る。
   表 5.4.2.4（芽球の経過）は Out-5.4.2 の連続量だけを描くので ANALYSID で絞る。
   R 側は tlf_ops.R の d_tab_bg が apply_filter で同じことを既に行っている */
%macro tab_bg(output_id=, lblid=, filter=, item_var=VARIABLE, item_label=item, levels=,
              show_n=);
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
           /* 行項目の順序番号。連続量の行は LEVEL を持たないため、宣言が無いと
              並びが定まらない（2026-09-11 に表 5.4.2.4 で SAS だけ順が崩れた）*/
           i.LVORD as ITEMORD,
           /* 図表ごとに行項目の表示名を差し替える口。<キー>_<図表ID> が登録されて
              いればそちらを先に使う（R 側の lvl_for と同じ）。プレフェーズの REDUCEFL は
              減量ではなく漸増の有無を表すので、表 5.3.1 だけ別の行ラベルを当てる */
           i2.LVLBL as ITEMLBLF length=200,
%if %length(&iv2) %then %do;
           j.LVLBL as ITEMLBL2 length=200,
           j2.LVLBL as ITEMLBL2F length=200,
%end;
           max(a.CONTEXT) as CONTEXT length=20,
           max(case when a.STATNAME='n'      then a.STAT end) as _n,
           max(case when a.STATNAME='nmiss'  then a.STAT end) as _nm,
           max(case when a.STATNAME='mean'   then a.STAT end) as _mean,
           max(case when a.STATNAME='sd'     then a.STAT end) as _sd,
           max(case when a.STATNAME='median' then a.STAT end) as _med,
           max(case when a.STATNAME='q1'     then a.STAT end) as _q1,
           max(case when a.STATNAME='q3'     then a.STAT end) as _q3,
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
         left join _lvcat as i2 on cats(strip(a.&iv1), '_', "&lblid") = i2.LVKEY
%if %length(&iv2) %then %do;
         left join _lvcat as j on strip(a.&iv2) = j.LVKEY
         left join _lvcat as j2 on cats(strip(a.&iv2), '_', "&lblid") = j2.LVKEY
%end;
    where a.OUTPUTID = "&output_id" %if %length(&filter) %then and &filter;
    group by a.ANALYSID, a.VARIABLE, a.GROUP1L, coalescec(c.LVLBL, a.VARLEVEL),
             a.VARLEVEL, c.LVORD, c.LVVISIT, i.LVLBL, i.LVORD, i2.LVLBL
%if %length(&iv2) %then %do;
           , j.LVLBL, j2.LVLBL
%end;
    ;
  quit;

  /* proc sql の再マージで同じ行が統計量の数だけ出る。値は同一なので畳む（2026-08-20）*/
  proc sort data=_w nodupkey; by ANALYSID VARIABLE GROUP1L VARLEVEL LVKEYRAW LVORD LVVISIT ITEMORD ITEMLBL ITEMLBLF
%if %length(&iv2) %then %do; ITEMLBL2 ITEMLBL2F %end;
  ; run;

  proc sql noprint; select count(*) into :nobs trimmed from _w; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &output_id. / &filter. に結果値がない。表を作らない;
    %return;
  %end;

  data _bg2;
    set _w;
    length ITEM $200 LEVEL $200 VALUE $120 _i2 $100 KEY $410 _sts $60;
    /* <キー>_<図表ID> → kind=level → kind=bgitem → 識別子そのまま、の順で引く
       （R 側の lvl_for() と同じ）。$bgitem は未登録の値を入力のまま返すため、
       登録を見る方を先に置く */
    ITEM = coalescec(ITEMLBLF, ITEMLBL, put(&iv1, $bgitem.));
    if ITEM = ' ' then ITEM = &iv1;
%if %length(&iv2) %then %do;
    _i2 = coalescec(ITEMLBL2F, ITEMLBL2, put(&iv2, $bgitem.));
    if _i2 = ' ' then _i2 = &iv2;
    ITEM = catx(' / ', ITEM, _i2);
%end;
    if CONTEXT = 'continuous' then do;
      LEVEL = ' ';
      /* 値の無い統計量はラベルごと落とす。n=1 では SD が定義できず「… 平均 630.0 SD」と
         ラベルだけが残っていた（C2-217。2026-08-30 の目視確認）。四分位点は下限と上限を
         1つのラベルで並べるので、片方でも欠ければ「Q1-Q3 2.0-」にならないよう両方の
         有無で見る。R 側は tlf_ops.R の d_tab_bg・d_tab_crs が同じ組み立てをする */
      VALUE = strip(put(_med, comma12.1)) || ' [' || strip(put(_min, comma12.1)) || ', '
              || strip(put(_max, comma12.1)) || ']';
      if not missing(_q1) and not missing(_q3) then
        VALUE = catx(' ', VALUE, "%lblfx(q1q3)",
                     strip(put(_q1, comma12.1)) || '-' || strip(put(_q3, comma12.1)));
      if not missing(_mean) then
        VALUE = catx(' ', VALUE, "%lblfx(mean)", strip(put(_mean, comma12.1)));
      if not missing(_sd) then VALUE = catx(' ', VALUE, 'SD', strip(put(_sd, comma12.1)));
      if _nm > 0 then VALUE = strip(VALUE) || " %lblfx(missing)" || strip(put(_nm, 8.0));
      /* 解析例数は宣言の show_n=Y を持つ表だけがセルの先頭に出す（表5.4.7.2・5.4.7.5）。
         行を増やさずコース別の分母を示すための口である。欠測数は出さない。両表とも欠測は
         全組0だが、値の無い症例は入力の行として存在しないため、0 と書くと「欠測が無い」
         という別のことを述べてしまう（C2-045。R 側は tlf_ops.R の d_tab_bg が同じ）*/
      if "&show_n" = 'Y' and not missing(_n) then
        VALUE = 'n=' || strip(put(_n, 8.0)) || ' ' || strip(VALUE);
      /* 並びはセルに出る順（例数 → 中央値 → 最小 → 最大 → 四分位点 → 平均 → SD → 欠測）*/
      _sts = catx('+', ifc("&show_n" = 'Y' and not missing(_n), 'n', ' '),
                       ifc(missing(_med),  ' ', 'median'),
                       ifc(missing(_min),  ' ', 'min'),
                       ifc(missing(_max),  ' ', 'max'),
                       ifc(missing(_q1) or missing(_q3), ' ', 'q1'),
                       ifc(missing(_q1) or missing(_q3), ' ', 'q3'),
                       ifc(missing(_mean), ' ', 'mean'),
                       ifc(missing(_sd),   ' ', 'sd'),
                       ifc(_nm > 0, 'nmiss', ' '));
    end;
    else do;
      LEVEL = VARLEVEL;
      /* 割合が欠測なら括弧ごと落とす。「60 ()」のように空の括弧が残ると、割合が0なのか
         算出していないのかが読み手に分からない（C2-050。R 系は tlf_ops.R の np()） */
      if missing(_p) then VALUE = strip(put(_n, 8.0));
      else VALUE = strip(put(_n, 8.0)) || ' (' || strip(put(_p, 8.1)) || ')';
      _sts = catx('+', ifc(missing(_n), ' ', 'n'), ifc(missing(_p), ' ', 'p'));
    end;
    /* 要約の列だけが ARD 由来。項目と区分は行ラベルなので鍵を持たない。統計量は
       連続量が median、カテゴリが n（セルの先に出る方。C2-068）。要約のセルは統計量を
       複数並べたものなので、出たものを stats で数え上げる（C3-103）*/
    KEY = %_ky(ANALYSID, LVKEYRAW, GROUP1L,
               ifc(CONTEXT = 'continuous', 'median', 'n'), stats=_sts);
    if missing(LVORD) then LVORD = 9999;
    if missing(LVVISIT) then LVVISIT = 99999;
    if missing(ITEMORD) then ITEMORD = 9999;
    drop _i2 _sts;
    keep ANALYSID ITEM LEVEL VALUE KEY LVORD LVVISIT LVKEYRAW ITEMORD;
  run;

  /* 並びは 行項目の順序番号 → 宣言の levels= の順 → 順序番号 → 来院番号 → 識別子。
     表示名では並べない
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
  proc sort data=_bg2s out=_bg2; by ANALYSID ITEMORD _LVSEQ LVORD LVVISIT LVKEYRAW; run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlfnote(note_bg, lblid=&lblid)
  %tlffoot(&lblid)
  %_tlfcells(_bg2, &lblid, tab_bg, %str(ITEM LEVEL VALUE), keys=%str(. . KEY))

  proc report data=_bg2 nowd;
    column ANALYSID ITEM LEVEL VALUE;
    define ANALYSID / order noprint;
    define ITEM     / order order=data display "%lblfx(&item_label)" width=44;
    define LEVEL    / display "%lblfx(categ)"   width=26;
    define VALUE    / display "%lblfx(summary)"   width=46;
  run;
  title;
%mend tab_bg;

/*========================================================================================
  1.4 Kaplan-Meier 曲線（図のみ ADaM を直接使う）
========================================================================================*/

%macro fig_km(paramcd=, lblid=, where=1, group=);
  %local _lcol _ghdr _nlv;
  %let _nlv = 0;

  /* 層別のときの凡例とリスク集合表の文言。PROC LIFETEST は凡例の見出しに層別の変数の
     ラベルを、凡例の各項目とリスク集合表の行見出しに層別の変数の値を、いずれもそのまま
     出す。ADaM が持つラベルは日本語なので（<試験ID>_SDTMtoADaM.sas の
     HSCTFL='全移植例'）英語版の図 5.4.10 にも「全移植例」が出ており、水準は生値（Y・N）が
     日英どちらにも出ていた（2026-09-02 の実測）。ODS が生成する文言ではないため、TLF 本体の
     %_matchlocale（options locale=）では直らない。
     表示文言の正本は docs/metadata/label-catalog.csv の kind=level で、見出しは層別の変数の
     名前（key=HSCTFL）、各水準は <変数名>_<水準>（key=HSCTFL_Y・HSCTFL_N）を鍵に持つ。
     層別の変数の名前から前向きに引く。表示文言そのものを鍵にして引き当てると、文言を直した
     日に黙って外れるので、文字列の突合はしない（2026-09-03 に置き換えた。C2-064）。R 系
     （tlf_ops.R の km_paint）が凡例に使う鍵と同じもので、両系統が同じ宣言を読む。カタログは
     %_mklabfmt が読んだ _labcat をそのまま引く（同じ CSV を2度読まない）。引き当てられなければ
     ADaM のラベル・生値のまま出し、見出しと水準のどちらが欠けたかをログへ残す */
  %if %length(&group) %then %do;
    %if %upcase(&lang) = EN %then %let _lcol = label_en;
    %else                        %let _lcol = label_ja;
    proc sql noprint;
      select strip(&_lcol) into :_ghdr trimmed
        from _labcat
       where strip(kind) = 'level' and strip(key) = "&group"
         and not missing(&_lcol);
    quit;
    %if %length(&_ghdr) = 0 %then
      %put WARNING: [TLF] [&lblid] 層別の変数 &group の見出しが label-catalog.csv に無い（kind=level, key=&group.）。凡例の見出しは ADaM のラベルのまま出る;
  %end;

  data _k;
    set ads.adtte;
    if (&where) and PARAMCD = "&paramcd";
    AVALY = AVAL / 365.25;
    /* 引いた見出しは入力データの変数ラベルとして与える。凡例の見出しは層別の変数のラベルから
       採られるので、proc lifetest の label 文（横軸に使っている）に頼らない */
    %if %length(&_ghdr) %then %do; label &group = "&_ghdr"; %end;
  run;

  %if %length(&group) %then %do;
    /* 水準の文言は出力形式で与え、データの値は書き換えない。表示文言を値にすると層の並びが
       文言の順に動き、日英で食い違いかねない（2026-08-23。CP932 から UTF-8 への移行で、
       表示名で並べていた12表が動いた）。start と end を同じ値で埋めるのは、ハイフン・ドットを
       含む水準を範囲の指定と読ませないため（2026-09-03。C2-064）*/
    data _kmglv;
      set _labcat(where=(strip(kind) = 'level' and index(strip(key), "&group._") = 1));
      length fmtname $32 start $80 end $80 label $400 type $1;
      fmtname = '$kmgrp';
      type  = 'C';
      start = substr(strip(key), length("&group") + 2);
      end   = start;
      label = strip(&_lcol);
      if missing(start) or missing(label) then delete;
      keep fmtname start end label type;
    run;
    data _null_;
      if 0 then set _kmglv nobs=_nlv;
      call symputx('_nlv', _nlv, 'L');
      stop;
    run;
    %if &_nlv > 0 %then %do;
      proc sort data=_kmglv; by start; run;
      proc format cntlin=_kmglv; run;
    %end;
    /* データに在る水準のうちカタログに無いもの。出力形式は当たらない値を生値のまま返すので
       図は出るが、識別子が読み手に見えるためログへ残す（2026-09-03。C2-064）*/
    proc sql noprint;
      create table _kmgmiss as
        select distinct strip(k.&group) as LV length=80
          from _k as k
         where not missing(k.&group)
           and strip(k.&group) not in (select strip(c.start) from _kmglv as c);
    quit;
    data _null_;
      set _kmgmiss;
      length _msg $400;
      /* cats は引数の前後の空白を落とすので語の間が詰まる。|| と strip で組む */
      _msg = "WARNING: [TLF] [&lblid] 層別の変数 &group の水準 " || strip(LV)
             || " の文言が label-catalog.csv に無い（kind=level, key=&group._" || strip(LV)
             || "）。凡例とリスク集合表には生値が出る";
      put _msg;
    run;
  %end;

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
  /* 図の注記も表と同じ二層にする。共通注記（note_figkm。打ち切りの目印と信頼区間の帯
     という読み方）のうしろに、図別の脚注を置く。以前は SAS 系が図別脚注だけ、R 系が
     共通注記だけを出しており、層が系統間で逆転していた（C3-216）*/
  %tlfnote(note_figkm, lblid=&lblid)
  %tlffoot(&lblid)
  /* 図だけを出す。生存率の表は %tab_km が ARD から出しており、proc lifetest の既定の表を
     重ねると同じ数字が2度出るうえ、SAS のロケールが生成する日本語の見出し（積極限法による
     生存推定・生存率・打ち切り など）が英語版の rtf にも入る（2026-08-20） */
  ods select survivalplot;
  /* 打ち切りの目印（既定で出る）と95%信頼限界を出す。R系の図と読み方を揃えるため
     （2026-08-20）。cl は層別のときも層ごとに描かれる。

     conftype=loglog を明示する。表・ARD（%ard_km）・R系（survfit の conf.type='log-log'）と
     同じ方式で、2026-09-12 に線形形式から改めた。明示を省くと処理系の既定に落ちるため、
     方式を変えるときは4か所を同時に動かす。書かずにいた間は図の帯だけが別の方式で描かれ、
     主要評価項目の3年EFS割合の下限が図で 60.3%、表で 61.6% と食い違っていた
     （2026-08-29 に是正）。差は指定時点で 1.3〜2.0 ポイント、全イベント時点の最大で
     4.4 ポイントある（生存割合が1に近いほど離れる）。 */
  proc lifetest data=_k method=km conftype=loglog plots=survival(atrisk=0 to 5 by 1 cl);
    time AVALY * CNSR(1);
    %if %length(&group) %then %do;
      strata &group;
      /* 水準の表示名。凡例の各項目とリスク集合表の行見出しの両方がこの出力形式を通る */
      %if &_nlv > 0 %then %do; format &group $kmgrp.; %end;
    %end;
    label AVALY = "%lblfx_for(xaxis_km, &lblid)";
  run;
  ods select all;
  title;
  ods graphics off;
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
  %tlffoot(&lblid)
  /* 症例単位の一覧は結果値の集計ではなく ADaM から直接組む。どのセルも ARD の行を
     指さないので keys= を渡さない（台帳の4列は空のままになる。C2-068）*/
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
%mend tab_list;

/*========================================================================================
  1.6 累積発生率の表（競合リスク。SAP 4.4.10）
========================================================================================*/

%macro tab_cif(analysis_id=, lblid=);
  %local nobs;
  proc sql;
    create table _cf as
    select coalescec(c.LVLBL, a.VARLEVEL) as TIMEPT length=40,
           /* 鍵に使う生の水準と群（%tab_km と同じ。C2-068）*/
           a.VARLEVEL as _vl length=200,
           a.GROUP1L  as _g1 length=60,
           max(case when a.STATNAME='cif' then a.STAT else . end) as _c,
           max(case when a.STATNAME='se'  then a.STAT else . end) as _se,
           max(case when a.STATNAME='lcl' then a.STAT else . end) as _l,
           max(case when a.STATNAME='ucl' then a.STAT else . end) as _u,
           max(input(compress(a.VARLEVEL, 'Y年'), best8.)) as _ord
    from ard.ard as a left join _lvcat as c on strip(a.VARLEVEL) = c.LVKEY
    /* 指定時点（Y1〜Y5）の行だけを取る。%tab_km と同じ形にしておく（Mth-CIF は今のところ
       曲線の全時点を持たないが、持たせたときに黙って表へ入らないようにする）*/
    where a.ANALYSID = "&analysis_id" and a.CONTEXT = 'cuminc'
      and prxmatch('/^Y[0-9]/', strip(a.VARLEVEL))
    group by coalescec(c.LVLBL, a.VARLEVEL), a.VARLEVEL, a.GROUP1L
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
    length CIFC $10 SEVC $10 CIC $30 K2 K3 K4 $410 _sci $60;
    CIFC = put(100 * _c, 6.1);
    SEVC = put(100 * _se, 6.1);
    CIC  = catx(' - ', put(100 * _l, 6.1), put(100 * _u, 6.1));
    /* 信頼区間のセルは下限と上限を1つにまとめたもの（%tab_km と同じ。C3-103）*/
    _sci = catx('+', ifc(missing(_l), ' ', 'lcl'), ifc(missing(_u), ' ', 'ucl'));
    K2 = %_ky("&analysis_id", _vl, _g1, 'cif');
    K3 = %_ky("&analysis_id", _vl, _g1, 'se');
    K4 = %_ky("&analysis_id", _vl, _g1, 'lcl', stats=_sci);
    keep TIMEPT CIFC SEVC CIC K2 K3 K4;
  run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlfnote(note_cif, aid=&analysis_id, lblid=&lblid)
  %tlffoot(&lblid, aid=&analysis_id)
  %_tlfcells(_cf2, &lblid, tab_cif, %str(TIMEPT CIFC SEVC CIC), keys=%str(. K2 K3 K4))

  proc report data=_cf2 nowd;
    column TIMEPT CIFC SEVC CIC;
    define TIMEPT / display "%lblfx(timepoint)";
    define CIFC   / display "%lblfx(cif)";
    define SEVC   / display "%lblfx(se)";
    define CIC    / display "%lblfx(ci95)";
  run;
  title;
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
           /* 鍵に使う生の水準と群（C2-068）*/
           a.VARLEVEL as _vl length=200,
           a.GROUP1L  as _g1 length=60,
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
    length NCNT $12 KEY $410;
    NCNT = strip(put(_n, 8.0));
    /* 1行が ARD の1行なので、鍵はその行の値をそのまま指す（C2-068）*/
    KEY = %_ky(ANALYSID, _vl, _g1, 'n');
    keep ANALYSID CATEG NCNT KEY;
  run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlffoot(&lblid)
  %_tlfcells(_cn2, &lblid, tab_count, %str(CATEG NCNT), keys=%str(. KEY))

  proc report data=_cn2 nowd;
    column ANALYSID CATEG NCNT;
    define ANALYSID / order noprint;
    define CATEG    / display "%lblfx(categ)" width=40;
    define NCNT     / display "%lblfx(ncnt)"  width=10;
  run;
  title;
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
           max(case when a.STATNAME='q1'     then a.STAT end) as _q1,
           max(case when a.STATNAME='q3'     then a.STAT end) as _q3,
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
    length COURSE $60 GRP $200 ITEM $200 LEVEL $200 VALUE $120 KEY $410 _sts $60;
    COURSE = COURSEL;
    GRP    = ifc(GROUP1 = ' ', ' ', GRPL);
    if CONTEXT = 'count' then do;
      /* 例数の行は VARLEVEL（COURSEDONE・TKIDOSED）が何を数えたかを持つ */
      ITEM  = LEVELL;
      LEVEL = ' ';
      VALUE = strip(put(_n, 8.0));
      _sts  = 'n';
    end;
    else if CONTEXT = 'continuous' then do;
      ITEM  = ITEML;
      LEVEL = ' ';
      /* 値の無い統計量はラベルごと落とす。n=1 では SD が定義できず「… 平均 630.0 SD」と
         ラベルだけが残っていた（C2-217。2026-08-30 の目視確認）。四分位点は下限と上限を
         1つのラベルで並べるので、片方でも欠ければ「Q1-Q3 2.0-」にならないよう両方の
         有無で見る。R 側は tlf_ops.R の d_tab_bg・d_tab_crs が同じ組み立てをする */
      VALUE = strip(put(_med, comma12.1)) || ' [' || strip(put(_min, comma12.1)) || ', '
              || strip(put(_max, comma12.1)) || ']';
      if not missing(_q1) and not missing(_q3) then
        VALUE = catx(' ', VALUE, "%lblfx(q1q3)",
                     strip(put(_q1, comma12.1)) || '-' || strip(put(_q3, comma12.1)));
      if not missing(_mean) then
        VALUE = catx(' ', VALUE, "%lblfx(mean)", strip(put(_mean, comma12.1)));
      if not missing(_sd) then VALUE = catx(' ', VALUE, 'SD', strip(put(_sd, comma12.1)));
      if _nm > 0 then VALUE = strip(VALUE) || " %lblfx(missing)" || strip(put(_nm, 8.0));
      /* 並びはセルに出る順（中央値 → 最小 → 最大 → 四分位点 → 平均 → SD → 欠測）*/
      _sts = catx('+', ifc(missing(_med),  ' ', 'median'),
                       ifc(missing(_min),  ' ', 'min'),
                       ifc(missing(_max),  ' ', 'max'),
                       ifc(missing(_q1) or missing(_q3), ' ', 'q1'),
                       ifc(missing(_q1) or missing(_q3), ' ', 'q3'),
                       ifc(missing(_mean), ' ', 'mean'),
                       ifc(missing(_sd),   ' ', 'sd'),
                       ifc(_nm > 0, 'nmiss', ' '));
    end;
    else do;
      ITEM  = ITEML;
      LEVEL = LEVELL;
      VALUE = strip(put(_n, 8.0)) || ' (' || strip(put(_p, 8.1)) || ')';
      _sts  = catx('+', ifc(missing(_n), ' ', 'n'), ifc(missing(_p), ' ', 'p'));
    end;
    /* 要約の列だけが ARD 由来。コース・薬剤区分・項目・区分は行ラベルなので鍵を持たない。
       統計量は連続量が median、それ以外が n（セルの先に出る方。C2-068）。要約のセルは
       統計量を複数並べたものなので、出たものを stats で数え上げる（C3-103）*/
    KEY = %_ky(ANALYSID, VARLEVEL, GROUP1L,
               ifc(CONTEXT = 'continuous', 'median', 'n'), stats=_sts);
    keep _co ANALYSID VARLEVEL COURSE GRP ITEM LEVEL VALUE KEY;
  run;

  proc sort data=_cs2; by _co ANALYSID VARLEVEL; run;

  %_tlfopen(&lblid)

  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlfnote(note_bg, lblid=&lblid)
  %tlffoot(&lblid)
  %_tlfcells(_cs2, &lblid, tab_crs, %str(COURSE GRP ITEM LEVEL VALUE),
             keys=%str(. . . . KEY))

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
%mend tab_crs;

/*========================================================================================
  1.9 有害事象の最悪グレード表（SAP 5.4.7.1・5.4.7.3・5.4.7.6）
  ARD の VARIABLE が有害事象の項目名を持つので、そこから直接組む。
========================================================================================*/

%macro tab_aegr(output_id=, lblid=, filter=, levels=, ph=, tk=);
  %local nobs _gi _gn _glv _gcol;
  /* グレードの区切りは宣言の levels= が持つ。空なら CTCAE の4区分（LS_AEGR4）を既定に
     する。区切り方は表示の選択なので表示型に直書きせず、集合の正本である
     docs/metadata/level-sets.csv から引く（2026-08-29・C3-002。2026-09-03。
     R系の d_tab_aegr も同じ）*/
  %let _glv = &levels;
  %if %length(&_glv) = 0 %then %do;
    proc sql noprint;
      select LVSTR into :_glv trimmed from _lvsetd where SETID = 'LS_AEGR4';
    quit;
    %if %length(&_glv) = 0 %then %do;
      %put ERROR: [TLF] 水準集合 LS_AEGR4 が docs/metadata/level-sets.csv に無い;
      %abort cancel;
    %end;
  %end;
  %let _gn  = %sysfunc(countw(%superq(_glv), |));
  /* filter に * を含む宣言（SUBSET=* and GROUP1L=*）は、ARD が持つ TKI区分 × 治療相の
     組合せで表を分ける（SAP 5.4.7.3 の図表案）。組合せの正本を ARD に置いたままにしたい
     ので、宣言を組合せの数だけ並べない。並びは TKI区分 → 治療相。表題は label-catalog の
     「Adverse Events &ph &tk」の印を %ttlsub が値へ置き換える。R系
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
      %tab_aegr(output_id=&output_id, lblid=&lblid, ph=&ph, tk=&tk,
                filter=%str(GROUP1L="&ph" and SUBSET="&tk"))
    %end;
    %return;
  %end;

  proc sql;
    create table _ag as
    select GROUP1L as PHASE length=20, SUBSET as TKIG length=20,
           VARIABLE as AETERM length=80,
           /* 鍵に使う解析ID。1つの有害事象の項目に解析は1つだが、ここは集計なので
              バイト順で最小のものを取る（R 系の d_tab_aegr も同じ。C2-068）*/
           min(ANALYSID) as _aid length=40,
           max(case when STATNAME='N'                                then STAT end) as DEN,
           %do _gi = 1 %to &_gn;
             max(case when STATNAME='n' and VARLEVEL="%scan(&_glv, &_gi, |)"
                      then STAT end) as G&_gi %if &_gi < &_gn %then ,;
           %end;
    from ard.ard
    where OUTPUTID = "&output_id" %if %length(&filter) %then and &filter;
    group by GROUP1L, SUBSET, VARIABLE;
  quit;

  /* 分母は全グレードの行が同じ N を持つので、どの行から来たかが1つに決まらない。
     水準はバイト順で最小のものを代表にする（R 系の d_tab_aegr の nk と同じ）*/
  proc sql;
    create table _agn as
    select GROUP1L as PHASE length=20, SUBSET as TKIG length=20,
           VARIABLE as AETERM length=80, min(VARLEVEL) as _nlv length=200
    from ard.ard
    where OUTPUTID = "&output_id" and STATNAME = 'N'
          %if %length(&filter) %then and &filter;
    group by GROUP1L, SUBSET, VARIABLE;
  quit;

  proc sql noprint; select count(*) into :nobs trimmed from _ag; quit;
  %if &nobs = 0 %then %do;
    %put WARNING: [TLF] &output_id. / &filter. に結果値がない。表を作らない;
    %return;
  %end;

  proc sort data=_ag;  by PHASE TKIG AETERM; run;
  proc sort data=_agn; by PHASE TKIG AETERM; run;
  data _ag;
    merge _ag(in=_a) _agn;
    by PHASE TKIG AETERM;
    if _a;
    length KDEN $410 %do _gi = 1 %to &_gn; KG&_gi $410 %end;;
    KDEN = '';
    /* 分母は代表の行を指すので、kind に repr を置いて台帳へ残す（C3-104）*/
    if not missing(_nlv) then KDEN = %_ky(_aid, _nlv, PHASE, 'N', kind='repr');
    %do _gi = 1 %to &_gn;
      /* 結果値の無いグレードはセルが空になる。鍵も空にする（ARD に無い行を指さない）*/
      KG&_gi = '';
      if not missing(G&_gi) then
        KG&_gi = %_ky(_aid, "%scan(&_glv, &_gi, |)", PHASE, 'n');
    %end;
    drop _aid _nlv;
  run;

  %_tlfopen(&lblid)

  /* 表題に出す治療相と TKI区分は表示名を引く。&ph は ADaM の APHASE の値（C1-1・
     MAINTENANCE）、&tk は部分集団の識別子（SS-TKIGRP-DA・SS-TKIGRP-PN）なので、
     そのまま出すと内部の名前が読み手の目に入る。カタログに無ければ識別子のまま
     （%_pemake の時点・下の列見出しと同じ作法。R 系は d_tab_aegr の ph・tk を
     lvl() へ通す）。並び順と絞り込みは識別子のままで行う。治療相は集約区分の
     C1-x・C2-x と個別コースの C1-1 などが別の行としてカタログに並ぶので、
     LVKEY の等値で引く（前方一致にすると取り違える） */
  %local _phl _tkl;
  %let _phl = &ph;
  %if %length(&ph) %then %do;
    proc sql noprint;
      select LVLBL into :_phl trimmed from _lvcat where LVKEY = "&ph";
    quit;
  %end;
  %let _tkl = &tk;
  %if %length(&tk) %then %do;
    proc sql noprint;
      select LVLBL into :_tkl trimmed from _lvcat where LVKEY = "&tk";
    quit;
  %end;

  title1 justify=left "%ttlsub(%superq(L_ti_&lblid), ph=&_phl, tk=&_tkl)";
  title2 justify=left "%lbl(su, &lblid)";
  %tlffoot(&lblid)
    %let _gcol = ;
  %local _kcol;
  %let _kcol = . KDEN;
  %do _gi = 1 %to &_gn; %let _gcol = &_gcol G&_gi; %let _kcol = &_kcol KG&_gi; %end;
  /* 台帳には列の意味を残す。グレードの区切りは宣言で変わるので、変数名（G1・G2…）を
     書くと位置の番号になり、読み手が Grade 3 と取り違える */
  %local _glab;
  %let _glab = %lblfx(ae)|%lblfx(denom);
  %do _gi = 1 %to &_gn; %let _glab = &_glab|%scan(&_glv, &_gi, |); %end;
  %_tlfcells(_ag, &lblid, tab_aegr, %str(AETERM DEN &_gcol), labels=%superq(_glab),
             keys=%str(&_kcol))

  /* 列見出しの表示名を先に引く。define 文の中では SQL を呼べない。宣言の levels= は
     識別子で書くので、そのまま出すと NOTRECORDED のような内部の名前が表に出る
     （C2-056。R 系は d_tab_aegr が lvl() を通す） */
  %do _gi = 1 %to &_gn;
    %local _gcap&_gi;
    %let _gcap&_gi = %scan(&_glv, &_gi, |);
  %end;
  proc sql noprint;
    %do _gi = 1 %to &_gn;
      select LVLBL into :_gcap&_gi trimmed from _lvcat
       where LVKEY = "%scan(&_glv, &_gi, |)";
    %end;
  quit;

  /* missing は必須。ORDER 変数（PHASE・TKIG）が欠測の行を proc report は既定で落とすため、
     Out-5.4.7.1 と 5.4.7.6 のように TKIG が全行で欠測の表が本文に1行も出ていなかった
     （表題だけが出る。台帳は表示前のデータセットから貯めるので突合では気づけない。
     2026-08-20 に検出）*/
  proc report data=_ag nowd missing;
    column PHASE TKIG AETERM DEN &_gcol;
    define PHASE  / order noprint;
    define TKIG   / order noprint;
    define AETERM / display "%lblfx(ae)" width=48;
    define DEN    / display "%lblfx(denom)"      format=4.0;
    %do _gi = 1 %to &_gn;
      define G&_gi / display "&&_gcap&_gi" format=4.0;
    %end;
  run;
  title;
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
   ADSL から直接組む。R系は list_abl() が同じものを作る。
   対象は頻度表（Out-5.4.13）と同じ検査実施例にする。決定事項 B-17 が「検査実施例の一覧」
   と呼ぶ以上、一覧と頻度表の分母が違ってはならない（2026-09-05）。実施したのに結果が空の
   症例が来たときは ARD 層の %chk_ablres が先に止めるので、ここには到達しない */
%macro _list_abl;
  data _abllist;
    set ads.adsl(where=(FASFL='Y' and ABLMUTFL='Y'));
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
    keep SUBJID CTX ABLMUTCT ABLMUTDT TRGDT TRGDYC ABLMUT HSCTC RELC;
  run;
  /* ADSL.ABLMUT は識別子（MUTNONE 等）なので表示名に引き当てる。SDTM を ASCII だけで
     構成したため和文は docs/metadata/label-catalog.csv の kind=level が持つ（2026-08-20）*/
  proc sql;
    create table _abllist2 as
    select a.*, coalescec(c.LVLBL, a.ABLMUT) as ABLMUTL length=40
    from _abllist as a left join _lvcat as c on strip(a.ABLMUT) = c.LVKEY;
  quit;
  /* 並べ替えは表示文言（CTX）ではなく原記録の符号（ABLMUTCT）で行う。表示文言で
     並べると日本語版と英語版で行が入れ替わる（C2-213 と同じ型。この表は由来鍵を
     持たないので値の突合では見えず、C3-121 の言語間の突合が捕らえた）*/
  proc sort data=_abllist2 out=_abllist(drop=ABLMUTCT); by ABLMUTCT SUBJID; run;
%mend _list_abl;

/*========================================================================================
  第3章 宣言の駆動

  図表の宣言（どの表番号を、どの表示型で、どの解析から描くか）の正本は
  docs/metadata/tlf-index.csv で、SAS系・R系・トレーサビリティ索引の3つが同じものを読む。設計は
  docs/spec/tlf-spec.md。
========================================================================================*/

/*========================================================================================
  参考併記の表について

  自試験の値と文献値を列に並べる作りは汎用だが、実装が比較対象の他試験名を
  直書きするので、ここには置かない。試験リポジトリの tlf_ops_trial.sas が持つ
  （2026-08-29 の判定。examples/README.md「表示型の判定」）。何列並べるか、
  どの試験を並べるかが試験ごとに変わるためである。

  行の定義（どの解析からどう引くか）と文献値は CSV 2つ（reference-table-rows.csv・
  reference-values.csv）が持ち、その中身も試験固有なので試験側の docs/metadata/ に置く。
  文献値は解析の結果ではないので ARD には置かない。

  ここが持つのは部品（%_tlfopen・%_tlfcells・%lbl・%lblfx・%_ky）までである。
========================================================================================*/

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
           paramcd $20 where $100 group $20 blocks $600 subtypemap $200 subset $40
           visual $1 show_n $1 grpcnt_id $40;
    /* 列を足したら LENGTH と INPUT の両方へ書く。LENGTH にだけ足すと、その列は常に
       空のまま駆動へ渡り、宣言に書いた値が黙って効かない。subtypemap が 2026-08-29 まで
       この状態で、%tab_mrlist がサブタイプの対応を受け取れていなかった（値は
       docs/metadata/tlf-index.csv に入っていた）。列の並びは同 CSV が正本 */
    input seq lblid $ display $ analysis_id $ output_id $ filter $ groups $ levels $
          item_var $ item_label $ vars $ labels $ paramcd $ where $ group $ blocks $
          subtypemap $ subset $ visual $ show_n $ grpcnt_id $;
  run;

  /* levels 列が水準集合の識別子（LS_ で始まる値）なら level-sets.csv の表示順へ展開する。
     集合の並びを宣言へ書き写さないため（C3-002。2026-09-03）。SS- で始まる部分集合の並び
     （%tab_crs のコース列）は水準集合ではないのでそのまま渡す。指した集合が無ければ止める。
     既定へ黙って落とすと、宣言が指したのとは違う列が出たままになる */
  %local _lserr;
  %let _lserr = 0;
  proc sql;
    create table _tlfls as
    select a.*, b.LVSTR
    from &out as a left join _lvsetd as b on strip(a.levels) = strip(b.SETID);
  quit;
  data &out;
    set _tlfls;
    if levels =: 'LS_' then do;
      if missing(LVSTR) then do;
        put 'ERROR: [TLF] 宣言 ' lblid +(-1) ' が指す水準集合 ' levels
            +(-1) ' が docs/metadata/level-sets.csv に無い';
        call symputx('_lserr', '1', 'L');
      end;
      else levels = LVSTR;
    end;
    drop LVSTR;
  run;
  %if &_lserr = 1 %then %do;
    %put ERROR: [TLF] 宣言が指す水準集合を展開できない。docs/metadata/level-sets.csv を直すこと;
    %abort cancel;
  %end;
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
                  vars labels paramcd where group blocks subtypemap subset show_n
                  grpcnt_id;
      do _j = 1 to dim(_v);
        if not missing(_v[_j]) then
          _a = strip(_a) || ',' || strip(vname(_v[_j])) || '=' || strip(_v[_j]);
      end;
      call symputx('_disp', display, 'L');
      call symputx('_args', _a, 'L');
    run;
    %&_disp.(&_args)
  %end;
  /* 個別 HTML の閉じは表示型ではなくここが持つ。表示型の終わりで閉じると、同じ表番号を
     何度も呼ぶ表示型が2回目以降に開き直すことになり、前の分を上書きする */
  %_tlfclose
%mend tlf_run;
