/*****************************************************************************************
実装例：試験にしかない表示型

  これは見本であって、そのまま実行するものではない。読んで、自分の試験に合わせて
  書き換えるための雛形である。

  汎用の表示型は pipeline/scripts/sas/tlf_ops.sas が持つ。ここに置くのは、疾患・試験の
  知識そのものを含む表示型である。どちらに当たるかの判定は README.md「表示型の判定」。

  試験側では、汎用の部品に続けてこのファイルに相当するものを %include する。

      %include "&repo_root/program/sas/macro/tlf_ops.sas";        * 汎用の部品 ;
      %include "&repo_root/program/sas/macro/tlf_ops_trial.sas";  * この試験の表示型 ;

  読む順序を逆にしない。試験側の表示型は、汎用の部品（%_tlfopen・%_tlfcells・%lbl・
  %lblfx など）を使う側だからである。

  図表の宣言（tlf-index.csv）の display 列には、汎用と試験固有のどちらの名前も書ける。
  駆動（%tlf_run）は名前でマクロを呼ぶだけなので、置き場を区別しない。宣言の健全性を
  見る検査は、両方のファイルから %macro を集めること（片方だけ見ると、切り出した
  表示型が「実装が無い」と誤って出る）。
*****************************************************************************************/

/*========================================================================================
  例：検査値の判定を症例ごとに並べる一覧

  結果値の集計ではなく症例単位の一覧なので、解析結果データからは作れず ADaM から直接
  組む。1症例が2行で、1行目は症例報告書の判定欄、2行目は測定値から導出した判定。

  この型が試験固有になる理由は3つある。どれか1つでも当てはまるなら、汎用層へ置かない。

  - 疾患固有の測定項目を名指しする（下の subtypemap で外へ出せる部分もあるが、
    どの ADaM のどの変数を見るかは残る）
  - 3つの ADaM をまたいで組み立てる。その対応関係は試験の設計そのものである
  - 判定の略号と、値が無いときの扱い（空欄にするか判定不能とするか）が試験の取り決め

  subtypemap … 症例の分類ごとに見る測定項目が違う試験で、その対応を宣言から渡す。
                `<分類の値>:<PARAMCD>` を `|` で並べる。空なら絞り込まない。
                この1つだけは宣言へ出せたので、実装から名前が消えている。
========================================================================================*/

%macro tab_xxlist(lblid=, subtypemap=);
  %local i ntp nobs _cols;

  /* 評価時点の並びと列見出しは、汎用の CSV（templates/timepoint-map.csv と同じ列）から
     読む。%_tdmr_load は tlf_ops.sas 側の部品 */
  %_tdmr_load

  /* 1行目：症例報告書の判定欄。判定欄を持つシートだけが該当する */
  proc sql;
    create table _crf as
    select t.order as _co, s.SUBJID, r.AVALC as _v length=40
    from _tp as t
         inner join ads.adrs as r on strip(r.PARAMCD) = strip(t.rsparamcd)
         inner join _subj as s    on s.SUBJID = r.SUBJID
    where strip(t.rsparamcd) ne ' ' and r.AVALC ne ' ';
  quit;

  /* 2行目：測定値から導出した判定。分類ごとに見る測定項目が違うなら subtypemap で絞る。
     この %do %while が、宣言の文字列を where 句へ組み立てる部分である */
  %local _smi _sm _smk _smv _smwh;
  %let _smwh = ;
  %if %length(&subtypemap) %then %do;
    %let _smi = 1;
    %do %while (%length(%scan(&subtypemap, &_smi, |)));
      %let _sm  = %scan(&subtypemap, &_smi, |);
      %let _smk = %scan(&_sm, 1, :);
      %let _smv = %scan(&_sm, 2, :);
      %if &_smi = 1 %then %let _smwh = (s.CLASS = "&_smk" and l.PARAMCD = "&_smv");
      %else %let _smwh = &_smwh or (s.CLASS = "&_smk" and l.PARAMCD = "&_smv");
      %let _smi = %eval(&_smi + 1);
    %end;
    %let _smwh = and (&_smwh);
  %end;

  proc sql;
    create table _lab as
    select t.order as _co, s.SUBJID, l.RESULTCAT as _v length=40
    from _tp as t
         inner join ads.adlb as l on strip(l.LBSPID) = strip(t.spid)
         inner join _subj as s    on s.SUBJID = l.SUBJID
    where index(strip(t.source), 'LB') > 0 and l.RESULTCAT ne ' '
      &_smwh;
  quit;

  /* 以降、2行を1症例へ組んで proc report で出す。表示の作法（%_tlfopen で開き、
     %_tlfcells でセル台帳へ貯め、%_tlfclose で閉じる）は汎用の部品に従う */
  %_tlfopen(&lblid)
  title1 justify=left "%lbl(ti, &lblid)";
  title2 justify=left "%lbl(su, &lblid)";
  %_tlfcells(_out, &lblid, tab_xxlist, %str(&_cols))
  proc report data=_out nowd;
    /* 列は評価時点の数だけ動的に並ぶ */
  run;
  title;
  %_tlfclose
%mend tab_xxlist;

/*========================================================================================
  例：一覧の元データを表番号で引き当てる

  汎用の %tab_list は、列と見出しを宣言（vars=・labels=）で受けるので表示型としては
  汎用である。ただし一覧の元データを作る前処理は試験ごとに違うため、表番号で引き当てる
  部分が残る。引き当ての口だけを汎用層に置き、前処理そのものはここに書く。
========================================================================================*/

%macro _listdata(lblid=);
  %if &lblid = T_X_X_X %then %do;
    /* この表番号の一覧の元データを作る。ADaM から直接組む */
    data _xxlist;
      set ads.adsl;
      where FASFL = 'Y';
    run;
    %let data = _xxlist;
  %end;
%mend _listdata;
