/*****************************************************************************************
program name : export-sdtm-metadata.sas
description  : input/sdtm の変数メタデータ（ドメイン・変数名・型・長さ・順序）を CSV へ出す。
               scripts/update-define-xml.ps1 が define.xml を更新するときの入力になる。
usage        : autoexec.sas を実行した状態で submit する。
output       : <Box>/input/sdtm/sdtm_variables.csv・sdtm_valuelevel.csv・sdtm_codelist_sync.csv
*****************************************************************************************/

title; footnote;
options nonumber notes nomprint nocenter;

proc sql;
  create table _meta as
    select memname, name, type, length, varnum
      from dictionary.columns
     where libname = 'SDTM'
     order by memname, varnum;
quit;

filename _o "&base/input/sdtm/sdtm_variables.csv" encoding='utf-8';
proc export data=_meta outfile=_o dbms=csv replace;
run;
filename _o clear;

/* 値水準メタデータ用の --TESTCD → --TEST の対応。update-define-xml.ps1 が
   ValueList の ItemDef を実データに合わせるのに使う。--ORRES の値水準を持つ
   ドメインだけを対象にする（docs/sdtm-conformance-findings-20260815.md D-1） */
%let vlm_dom = LB FA RS VS DD MB QS;
%macro testmap;
  %local i dom;
  data _tmap;
    length domain $2 testcd $40 test $200;
    stop;
  run;
  %do i = 1 %to %sysfunc(countw(&vlm_dom));
    %let dom = %scan(&vlm_dom, &i);
    proc sql;
      create table _t as
        select distinct "&dom" as domain length=2,
               &dom.TESTCD as testcd length=40,
               &dom.TEST   as test   length=200
          from sdtm.&dom
         where not missing(&dom.TESTCD);
    quit;
    proc append base=_tmap data=_t force; run;
  %end;
  proc sort data=_tmap; by domain testcd; run;
%mend testmap;
%testmap;

filename _v "&base/input/sdtm/sdtm_valuelevel.csv" encoding='utf-8';
proc export data=_tmap outfile=_v dbms=csv replace;
run;
filename _v clear;

%put NOTE: [export-sdtm-metadata] 出力しました: &base/input/sdtm/sdtm_valuelevel.csv;

/* CodeList を実データへ合わせる対象変数。受領 define.xml の CodeList は CRF の選択肢を
   写したものなので、SDTM 層で値を扱った変数では実データと食い違う。扱い方は2種類ある。

   replace … SDTM 層で値体系を作り直した変数。実データの値だけにする。受領 define.xml が
             複数の変数へ同じ CodeList を割り当てている場合（FATESTCD と FATEST、
             LBTESTCD と MBTESTCD）も、専用の CodeList を作ることで共有を断つ。
   add     … CRF の選択肢に SDTM 層で値を足した変数。既存の値と実データの値の和にする。
             未使用の選択肢も CRF としては正しいので落とさない。

   対象外の変数の CodeList は受領版のままにする。対象を増やすときはこのリストに足す
   （update-define-xml.ps1 はこの CSV に出てくる変数だけを対象にする）。
   docs/sdtm-spec.md 3.6（FATESTCD 是正）・4.1・4.2（外部データ由来の値）を参照。
   LB:VISIT は受領 define.xml が VISITNUM の数値 CodeList を割り当てているための是正。
   他のドメインの VISIT は受領版のまま CodeList を持たない。
   FA:FACAT は 2026-08-20 に add から replace へ移した。受領値 'TREATENT' を SDTM 層で
   治療の対象ごとに分けたため、受領値は実データに存在しなくなる（仕様書 §3.6） */
%let cl_replace = FA:FATESTCD FA:FATEST FA:FAOBJ FA:FACAT DM:ARM DM:ARMCD
                  MB:MBTESTCD MB:MBTEST LB:VISIT;
%let cl_add     = FA:FASCAT PR:PRCAT PR:PRTRT PR:PROCCUR;
%macro clvals;
  %local m i tok dom var lst;
  data _clv;
    length domain $2 variable $32 mode $8 value $200;
    stop;
  run;
  %do m = 1 %to 2;
    %if &m = 1 %then %let lst = &cl_replace;
    %else            %let lst = &cl_add;
    %do i = 1 %to %sysfunc(countw(&lst, %str( )));
      %let tok = %scan(&lst, &i, %str( ));
      %let dom = %scan(&tok, 1, :);
      %let var = %scan(&tok, 2, :);
      proc sql;
        create table _c as
          select distinct "&dom" as domain length=2,
                 "&var" as variable length=32,
                 %if &m = 1 %then %do; "replace" %end; %else %do; "add" %end; as mode length=8,
                 &var as value length=200
            from sdtm.&dom
           where not missing(&var);
      quit;
      proc append base=_clv data=_c force; run;
    %end;
  %end;
  proc sort data=_clv; by domain variable value; run;
%mend clvals;
%clvals;

filename _c "&base/input/sdtm/sdtm_codelist_sync.csv" encoding='utf-8';
proc export data=_clv outfile=_c dbms=csv replace;
run;
filename _c clear;

%put NOTE: [export-sdtm-metadata] 出力しました: &base/input/sdtm/sdtm_codelist_sync.csv;

%put NOTE: [export-sdtm-metadata] 出力しました: &base/input/sdtm/sdtm_variables.csv;
