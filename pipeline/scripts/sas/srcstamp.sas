/*****************************************************************************************
program name : srcstamp.sas
description  : 入力データの版をログへ残す共通マクロ。
usage        : %include "&repo_root/program/sas/macro/srcstamp.sas";
               %srcstamp(sdtm)                ... ライブラリのデータセットの更新時刻と件数
               %filestamp(<パス>, <表示名>)   ... 外部ファイルの更新日時とサイズ
comment      : Box Drive は同期の都合でファイルを掴んだまま更新することがあり、直前の
               プログラムが書いた版ではなく前回の内容を読む事故が起きうる。読んだ版を
               ログへ残しておけば、突合の食い違いがこれに由来するかを後から切り分けられる。
               読み取り側の対策は program/sas/macro/load_rawdata.sas の %sasds が持つ。
*****************************************************************************************/

%macro srcstamp(libs);
  %local i lb;
  %do i = 1 %to %sysfunc(countw(&libs));
    %let lb = %upcase(%scan(&libs, &i));
    %if %sysfunc(libref(&lb)) ne 0 %then %do;
      %put WARNING: [srcstamp] libname &lb が未定義のため版を記録できません。;
    %end;
    %else %do;
      proc sql noprint;
        create table _srcstamp as
        select memname, nobs, modate from dictionary.tables
        where libname = "&lb" order by memname;
      quit;
      data _null_;
        set _srcstamp;
        length _ds $60;
        _ds = cats("&lb", '.', memname);
        put 'NOTE: [srcstamp] ' _ds ' obs=' nobs ' 更新=' modate datetime20.;
      run;
      proc datasets library=work nolist; delete _srcstamp; quit;
    %end;
  %end;
%mend srcstamp;

%macro filestamp(path, tag);
  filename _fstmp "&path";
  data _null_;
    length nm $60 v $80 sz $40 md $80;
    fid = fopen('_fstmp');
    if fid <= 0 then do;
      put "ERROR: [filestamp] 開けません: &path";
      return;
    end;
    do i = 1 to foptnum(fid);
      nm = foptname(fid, i);
      v  = finfo(fid, nm);
      /* 情報項目名は SAS のロケールで変わる（日本語版は「更新日時」「ファイルサイズ (バイト)」）*/
      if      index(nm, '更新')   or index(upcase(nm), 'MODIF') then md = v;
      else if index(nm, 'サイズ') or index(upcase(nm), 'SIZE')  then sz = v;
    end;
    rc = fclose(fid);
    put "NOTE: [filestamp] &tag 更新=" md +(-1) ' サイズ=' sz;
  run;
  filename _fstmp clear;
%mend filestamp;
