/*****************************************************************************************
program name : load_rawdata.sas
description  : Box の input/rawdata・input/ext から SDTM 相当 CSV を WORK へ取り込む共通マクロ。
               CSVtoSASDS と QC プログラムの双方から %include して使う（読み込み仕様の単一正本）。
usage        : %include "&repo_root/program/sas/macro/load_rawdata.sas";
               %require_base;
               %import_all;
comment      : 読み込むドメインを増減するときは &raw_dom / &ext_dom の2行だけを直す。
*****************************************************************************************/

/* 入力データの版をログへ残す共通マクロ（%filestamp・%srcstamp）*/
%include "&repo_root/program/sas/macro/srcstamp.sas";

%global cwd raw_dom ext_dom;

/* 読み込むドメイン。追加・削除はこの2行だけで済む */
%let raw_dom = AE CE CM CO DD DM DS EC FA LB MB MH PR QS RS VS;
%let ext_dom = facilities saihi diseases;

/* --- 前提チェック：autoexec.sas が張った &base のみを正とする -------------------------- */
%macro require_base;
  %if not %symexist(base) %then %do;
    %put ERROR: autoexec.sas が実行されていません。;
    %put ERROR- リポジトリルートをカレントにして SAS を起動するか、;
    %put ERROR- sas.exe -autoexec "<repo>\autoexec.sas" を指定してください。;
    %abort cancel;
  %end;
  %if %length(&base) = 0 %then %do;
    %put ERROR: マクロ変数 base が空です。autoexec.sas の設定を確認してください。;
    %abort cancel;
  %end;
  %if %sysfunc(fileexist(&base/input/rawdata/DM.csv)) = 0 %then %do;
    %put ERROR: &base/input/rawdata に DM.csv がありません。;
    %put ERROR- Box の同期状態、または rawdata 直下へのデータカット展開を確認してください。;
    %abort cancel;
  %end;
  %let cwd = &base;
  %put NOTE: [load_rawdata] base=&base;
%mend require_base;

/* --- CSV 1本を取り込む ----------------------------------------------------------------
   Box Drive は同期の都合でファイルを掴んだまま差し替えることがあり、proc import が読んで
   いる途中に中身が変わると取り込み結果が受領データと一致しない。WORK へ写してから読み、
   Box 上のファイルを掴む時間を複写の一瞬に限る（2026-08-19）。写す前の更新日時とサイズを
   ログへ出すので、どの版を読んだかは後から log で確認できる。                          */
%macro sasds(folder, dsnm);
  %local f w rc;
  %let f = &base/input/&folder/&dsnm..csv;
  %let w = %sysfunc(pathname(work))/&dsnm..csv;
  %if %sysfunc(fileexist(&f)) = 0 %then %do;
    %put ERROR: [sasds] がありません: &f;
    %abort cancel;
  %end;
  %filestamp(&f, &folder/&dsnm..csv)

  filename _cpsrc "&f" recfm=n;
  filename _cpdst "&w" recfm=n;
  data _null_;
    call symputx('rc', fcopy('_cpsrc', '_cpdst'), 'L');
  run;
  filename _cpsrc clear;
  filename _cpdst clear;
  %if &rc ne 0 %then %do;
    %put ERROR: [sasds] WORK への複写に失敗しました rc=&rc: &f;
    %put ERROR- Box Drive の同期中か、他のプロセスがファイルを掴んでいる可能性があります。;
    %abort cancel;
  %end;

  proc import out=&dsnm datafile="&w" dbms=csv replace;
    getnames=yes;
    datarow=2;
    guessingrows=max;
  run;
  %if &syserr > 4 %then %do;
    %put ERROR: [sasds] 取り込みに失敗しました: &f;
    %abort cancel;
  %end;
%mend sasds;

/* --- 全ドメインを取り込む -------------------------------------------------------------- */
%macro import_all;
  %local i;
  %do i=1 %to %sysfunc(countw(&raw_dom));
    %sasds(rawdata, %scan(&raw_dom, &i))
  %end;
  %do i=1 %to %sysfunc(countw(&ext_dom));
    %sasds(ext, %scan(&ext_dom, &i))
  %end;
  %put NOTE: [load_rawdata] 取り込み完了 rawdata=%sysfunc(countw(&raw_dom))件 ext=%sysfunc(countw(&ext_dom))件;
%mend import_all;