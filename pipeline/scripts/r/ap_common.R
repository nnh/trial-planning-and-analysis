## ---------------------------------------------------------------------------------
## program name : ap_common.R
## description  : R系パイプライン（CSVtoSDTM・SDTMtoADaM・Compare・ARD）の共通基盤。
##                パス解決、Dataset-JSON v1.1 の読み書き、レビュー用CSVの書き出し、
##                SDTM標準ラベルの辞書、ログを持つ。
## usage        : source(file.path(dirname(sys.frame(1)$ofile), "ap_common.R"))
##                または Rscript から source("program/r/ap_common.R")
## comment      : PI が SAS を持たずに検証・再現できることを目的とする層。
##                Box を前提にせず、単独フォルダへ展開しても相対パスで解決する。
##                仕様の正本は docs/spec/r-pipeline-spec.md。
## ---------------------------------------------------------------------------------

suppressPackageStartupMessages({
  library(jsonlite)
})

## ---------------------------------------------------------------------------------
## パス解決
## ---------------------------------------------------------------------------------

## 実行中のスクリプトが置かれたディレクトリ。Rscript・source のどちらでも解決する。
ap_script_dir <- function() {
  a <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", a[grep("^--file=", a)])
  if (length(f)) return(normalizePath(dirname(f[1]), winslash = "/", mustWork = FALSE))
  for (i in rev(seq_len(sys.nframe()))) {
    of <- sys.frames()[[i]]$ofile
    if (!is.null(of)) return(normalizePath(dirname(of), winslash = "/", mustWork = FALSE))
  }
  normalizePath(getwd(), winslash = "/", mustWork = FALSE)
}

## 試験固有の値。docs/metadata/trial.json だけが持つ（試験IDと Box の中の置き場）。
## リポジトリで実行するときと、単独フォルダへ展開した配布形態の両方から探す。
.ap_cfg <- NULL
ap_trial_config <- function() {
  if (!is.null(.ap_cfg)) return(.ap_cfg)
  d <- ap_script_dir()
  cand <- c(file.path(d, "..", "..", "docs", "metadata", "trial.json"),
            file.path(d, "..", "docs", "metadata", "trial.json"),
            file.path(d, "docs", "metadata", "trial.json"),
            ## 単独フォルダへ展開した配布形態。R は平置きで、仕様は input/spec/ にある
            file.path(d, "input", "spec", "trial.json"),
            file.path(d, "..", "..", "input", "spec", "trial.json"),
            file.path(d, "trial.json"))
  for (p in cand) if (file.exists(p)) {
    .ap_cfg <<- jsonlite::fromJSON(p, simplifyVector = TRUE)
    return(.ap_cfg)
  }
  stop("trial.json が見つかりません（探した場所: ",
       paste(normalizePath(cand, winslash = "/", mustWork = FALSE), collapse = "、"), "）")
}

## データルート。次の順で探し、最初に見つかったものを使う。
##   1. 環境変数 AKIKO_TRIAL_ROOT
##   2. スクリプト位置から上へ3階層（単独フォルダへ展開した配布形態）
##   3. Box（AKIKO_BOX_ROOT、macOS の Box Drive、~/Box、<USERPROFILE>/Box のいずれか配下の、
##      docs/metadata/trial.json の box_path が指す場所）
## 判定は input/rawdata/DM.csv の存在で行う。データが無い場所を黙って使わないため。
ap_root <- function(quiet = FALSE) {
  has_data <- function(p) file.exists(file.path(p, "input", "rawdata", "DM.csv"))
  norm <- function(p) normalizePath(p, winslash = "/", mustWork = FALSE)

  ## 出力先を本番から隔離する口。SAS の autoexec.sas と PowerShell が見るのと
  ## 同じ名前にしてある。試験IDから名前を組み立てる形にすると、組み立て方が
  ## 系統ごとに食い違ったときに黙って空振りする（2026-08-29 に一本化）
  e <- Sys.getenv("AKIKO_TRIAL_ROOT")
  if (nzchar(e)) {
    if (has_data(e)) return(norm(e))
    stop("AKIKO_TRIAL_ROOT が指す場所に input/rawdata/DM.csv がありません: ", e)
  }

  d <- ap_script_dir()
  for (up in c(".", "..", "../..", "../../..")) {
    cand <- norm(file.path(d, up))
    if (has_data(cand)) return(cand)
  }

  ## Box の置き場所は端末で違う（Windows は %USERPROFILE%\\Box、macOS の Box Drive は
  ## ~/Library/CloudStorage/Box-Box）。順に見て、データがある方を採る。
  boxes <- c(Sys.getenv("AKIKO_BOX_ROOT"),
             file.path(path.expand("~"), "Library", "CloudStorage", "Box-Box"),
             file.path(path.expand("~"), "Box"),
             file.path(Sys.getenv("USERPROFILE"), "Box"))
  ## Box の中のどこに試験フォルダがあるかは試験ごとに違う。試験固有の値は
  ## docs/metadata/trial.json だけが持ち、ここはそれを読む（Python の boxpath.py と同じ）
  rel <- ap_trial_config()$box_path
  for (box in boxes[nzchar(boxes)]) {
    cand <- norm(do.call(file.path, c(list(box), as.list(rel))))
    if (has_data(cand)) return(cand)
  }

  stop("データルートが見つかりません。環境変数 AKIKO_TRIAL_ROOT に ",
       "input/rawdata/DM.csv を含むフォルダを指定してください。")
}

## 日付を名前に持つ生成物の退避。直下には最新の1組だけを置き、以前の版は 旧版/ へ移す。
## 退避は生成プログラム自身が行う（人が片付ける運用にすると溜まる）。退避であって削除では
## ないので、過去の版を参照する必要が出ても失われない。世代を絞るのは別の作業で、
## scripts/trim-old-versions.py が行う（生成と片付けを混ぜない）。
ap_archive_old <- function(dir, pattern, tag = "") {
  old <- list.files(dir, pattern = pattern, full.names = TRUE)
  if (!length(old)) return(invisible(NULL))
  arc <- file.path(dir, "旧版")
  ap_mkdir(arc)
  ok <- file.rename(old, file.path(arc, basename(old)))
  ap_note("%s旧版へ退避: %d 件（%s）", if (nzchar(tag)) paste0("[", tag, "] ") else "",
          sum(ok), arc)
  invisible(NULL)
}

## よく使うディレクトリをまとめて返す。存在しない出力先はここでは作らない。
ap_paths <- function(root = ap_root()) {
  p <- list(
    root    = root,
    ## 受領物と一次データは input、解析が作ったデータセットは datasets（実装系統ごと）。
    ## 方針の正本は nnh/trial-planning-and-analysis の pipeline/analysis-pipeline-plan.md
    ## 「フォルダ構成と命名規則」（2026-08-25 の再編。第2段階）
    rawdata = file.path(root, "input", "rawdata"),
    ext     = file.path(root, "input", "ext"),
    interim = file.path(root, "input", "interim"),
    sdtm    = file.path(root, "datasets", "sas", "sdtm"),   # SAS系の出力（読み取り専用で参照）
    ads     = file.path(root, "datasets", "sas", "adam"),   # SAS系の出力（読み取り専用で参照）
    ard     = file.path(root, "datasets", "sas", "ard"),    # SAS系の ARD
    pv      = file.path(root, "datasets", "sas", "pv"),     # PV データ（SAS系。SDTM ではない）
    sdtm_r  = file.path(root, "datasets", "r", "sdtm"),     # R系の出力
    ads_r   = file.path(root, "datasets", "r", "adam"),     # R系の出力
    ard_r   = file.path(root, "datasets", "r", "ard"),      # R系の ARD
    pv_r    = file.path(root, "datasets", "r", "pv"),       # PV データ（R系）
    out       = file.path(root, "output"),             # 人が読むもの・納品物
    tlf       = file.path(root, "output", "tlf"),      # 図表。下に sas-ja/sas-en/r-ja/r-en
    compare   = file.path(root, "output", "compare"),  # 突合の結果とセル台帳
    qc        = file.path(root, "output", "qc"),       # 品質検査プログラムの出力
    spec      = file.path(root, "output", "spec"),     # 仕様書の HTML
    deliver_r = file.path(root, "output", "deliver", "r")  # 索引と納品パッケージ（R系）
  )
  p$sdtm_r_json <- file.path(p$sdtm_r, "json")
  p$sdtm_r_csv  <- file.path(p$sdtm_r, "csv")
  p$ads_r_json  <- file.path(p$ads_r,  "json")
  p$ads_r_csv   <- file.path(p$ads_r,  "csv")
  p
}

## 図表の置き場。実装系統（sas・r）と言語（ja・en）でディレクトリを分ける。
## ファイル名の接尾辞では分けない（層によって分け方が変わると規則を毎回思い出すことになる）。
## 並びは「系統 → 言語」。方針の正本は nnh/trial-planning-and-analysis の
## pipeline/analysis-pipeline-plan.md「フォルダ構成と命名規則」。
ap_tlf_dir <- function(system, lang, root = ap_root()) {
  if (!system %in% c("sas", "r")) stop("system は sas か r: ", system)
  if (!lang %in% c("ja", "en"))   stop("lang は ja か en: ", lang)
  file.path(root, "output", "tlf", paste0(system, "-", lang))
}

ap_mkdir <- function(...) {
  for (d in c(...)) if (!dir.exists(d)) dir.create(d, recursive = TRUE)
  invisible(NULL)
}

## 仕様ファイル（図表の宣言・表示文言のカタログ）の場所。
## リポジトリで実行するときは docs/、単独フォルダへ展開した配布形態では input/spec/ を見る。
## 配布時は docs/ の該当ファイルを input/spec/ へ写して同梱する。
ap_spec <- function(name, root = ap_root()) {
  d <- ap_script_dir()
  ## 機械が読む仕様は docs/metadata/ に置く（下に external/・trial-design/ がある）。
  ## 単独フォルダへ展開した配布形態では input/spec/ に平らに写すので、そちらを先に見る。
  ## リポジトリ側は program/r から見た相対と、リポジトリ直下から実行したときの両方を試す
  sub <- c(file.path("metadata", name), file.path("metadata", "external", name),
           file.path("metadata", "trial-design", name), name)
  base <- c(file.path(d, "..", ".."), d, file.path(d, ".."))
  cand <- c(file.path(root, "input", "spec", name),
            as.vector(t(outer(base, sub, function(b, s) file.path(b, "docs", s)))))
  for (p in cand) if (file.exists(p)) return(normalizePath(p, winslash = "/"))
  stop("仕様ファイルが見つかりません: ", name, "（探した場所: ",
       paste(cand, collapse = " / "), "）")
}

## ---------------------------------------------------------------------------------
## ログ
## ---------------------------------------------------------------------------------

.ap_log_env <- new.env(parent = emptyenv())
.ap_log_env$lines <- character()
.ap_log_env$warn  <- 0L
.ap_log_env$err   <- 0L

ap_log_reset <- function() {
  .ap_log_env$lines <- character()
  .ap_log_env$warn  <- 0L
  .ap_log_env$err   <- 0L
  invisible(NULL)
}

ap_note <- function(fmt, ...) {
  m <- sprintf(fmt, ...)
  .ap_log_env$lines <- c(.ap_log_env$lines, paste("NOTE :", m))
  cat("NOTE :", m, "\n", sep = " ")
  invisible(NULL)
}

ap_warn <- function(fmt, ...) {
  m <- sprintf(fmt, ...)
  .ap_log_env$warn <- .ap_log_env$warn + 1L
  .ap_log_env$lines <- c(.ap_log_env$lines, paste("WARN :", m))
  cat("WARN :", m, "\n", sep = " ")
  invisible(NULL)
}

## 停止すべき異常。SAS 側の %abort cancel に相当する。
ap_stop <- function(fmt, ...) {
  m <- sprintf(fmt, ...)
  .ap_log_env$err <- .ap_log_env$err + 1L
  .ap_log_env$lines <- c(.ap_log_env$lines, paste("ERROR:", m))
  stop(m, call. = FALSE)
}

ap_log_write <- function(path) {
  ap_mkdir(dirname(path))
  writeLines(.ap_log_env$lines, path, useBytes = TRUE)
  invisible(path)
}

ap_log_summary <- function() {
  list(warn = .ap_log_env$warn, err = .ap_log_env$err)
}

## ---------------------------------------------------------------------------------
## 受領CSVの読み込み
## ---------------------------------------------------------------------------------

## 受領CSVは全列を文字型で読む。proc import が全変数を文字型で読むのに揃える
## （docs/spec/sdtm-spec.md §2.2）。型は SDTM 層で明示的に与える。
## 空文字と NA を区別せず、いずれも NA_character_ にする。
ap_read_raw <- function(path, encoding = "UTF-8") {
  if (!file.exists(path)) ap_stop("見つかりません: %s", path)
  d <- utils::read.csv(path, colClasses = "character", check.names = FALSE,
                       na.strings = character(0), fileEncoding = encoding,
                       stringsAsFactors = FALSE, quote = "\"", comment.char = "")
  names(d) <- sub("^﻿", "", trimws(names(d)))  # UTF-8 BOM を落とす
  ## 行末のカンマで生じる名前の無い列を落とす（input/ext の ABL1変異解析_*.csv）
  d <- d[, nzchar(names(d)), drop = FALSE]
  for (i in seq_along(d)) {
    x <- trimws(d[[i]])
    x[x == ""] <- NA_character_
    d[[i]] <- x
  }
  d
}

## ---------------------------------------------------------------------------------
## 文字列・日付のユーティリティ
## ---------------------------------------------------------------------------------

## NA を空文字にして返す（比較・連結用）。
ap_chr <- function(x) ifelse(is.na(x), "", trimws(as.character(x)))

## ISO 8601 の YYYY-MM-DD を Date へ。部分日付・空は NA。
ap_date <- function(x) {
  x <- ap_chr(x)
  out <- rep(as.Date(NA), length(x))
  ok <- grepl("^\\d{4}-\\d{2}-\\d{2}", x)
  out[ok] <- as.Date(substr(x[ok], 1, 10))
  out
}

## 数値として解釈できるときだけ数値を返す（--STRESN の規則。docs/spec/sdtm-spec.md §2.8）。
## 指数表記・符号・小数を許し、それ以外の文字を含む値は NA。
ap_num <- function(x) {
  x <- ap_chr(x)
  out <- rep(NA_real_, length(x))
  ok <- grepl("^[+-]?(\\d+\\.?\\d*|\\.\\d+)([eE][+-]?\\d+)?$", x)
  out[ok] <- as.numeric(x[ok])
  out
}

## 相対日 --DY。起算日当日を 1、起算日前は負、0 は作らない（docs/spec/sdtm-spec.md §2.5）。
ap_dy <- function(dtc, refdt) {
  d <- if (inherits(dtc, "Date")) dtc else ap_date(dtc)
  r <- if (inherits(refdt, "Date")) refdt else ap_date(refdt)
  diff <- as.numeric(d - r)
  ifelse(is.na(diff), NA_real_, ifelse(diff >= 0, diff + 1, diff))
}

## ---------------------------------------------------------------------------------
## SDTM 標準ラベル
## ---------------------------------------------------------------------------------
## ラベルの正本は SAS 系では define.xml だが、R 系は独立実装のため自前の辞書を持つ。
## 突合ではラベルを一致判定の対象にせず参考差分として報告する
## （docs/spec/r-pipeline-spec.md「突合の対象」）。

.AP_LABEL_EXACT <- c(
  STUDYID = "Study Identifier",
  DOMAIN  = "Domain Abbreviation",
  USUBJID = "Unique Subject Identifier",
  SUBJID  = "Subject Identifier for the Study",
  SITEID  = "Study Site Identifier",
  RFSTDTC = "Subject Reference Start Date/Time",
  RFENDTC = "Subject Reference End Date/Time",
  RFXSTDTC = "Date/Time of First Study Treatment",
  RFXENDTC = "Date/Time of Last Study Treatment",
  RFICDTC = "Date/Time of Informed Consent",
  RFPENDTC = "Date/Time of End of Participation",
  DTHDTC  = "Date/Time of Death",
  DTHFL   = "Subject Death Flag",
  BRTHDTC = "Date/Time of Birth",
  AGE     = "Age",
  AGEU    = "Age Units",
  SEX     = "Sex",
  RACE    = "Race",
  ETHNIC  = "Ethnicity",
  COUNTRY = "Country",
  ARMCD   = "Planned Arm Code",
  ARM     = "Description of Planned Arm",
  ACTARMCD = "Actual Arm Code",
  ACTARM  = "Description of Actual Arm",
  EPOCH   = "Epoch",
  VISITNUM = "Visit Number",
  VISIT   = "Visit Name",
  VISITDY = "Planned Study Day of Visit",
  RDOMAIN = "Related Domain Abbreviation",
  IDVAR   = "Identifying Variable",
  IDVARVAL = "Identifying Variable Value",
  ITEMGROUPDATASEQ = "Record identifier"
)

## ドメイン接頭辞を剥がしたサフィックスに対するラベル。
.AP_LABEL_SUFFIX <- c(
  SEQ     = "Sequence Number",
  SPID    = "Sponsor-Defined Identifier",
  GRPID   = "Group ID",
  REFID   = "Reference ID",
  LNKID   = "Link ID",
  LNKGRP  = "Link Group ID",
  TESTCD  = "Short Name of Measurement, Test or Examination",
  TEST    = "Name of Measurement, Test or Examination",
  TERM    = "Reported Term for the Event",
  DECOD   = "Dictionary-Derived Term",
  TRT     = "Reported Name of Intervention",
  CAT     = "Category",
  SCAT    = "Subcategory",
  OBJ     = "Object of the Observation",
  ORRES   = "Result or Finding as Collected",
  ORRESU  = "Original Units",
  ORNRLO  = "Reference Range Lower Limit in Orig Unit",
  ORNRHI  = "Reference Range Upper Limit in Orig Unit",
  STRESC  = "Character Result/Finding in Std Format",
  STRESN  = "Numeric Result/Finding in Standard Units",
  STRESU  = "Standard Units",
  STNRLO  = "Reference Range Lower Limit-Std Units",
  STNRHI  = "Reference Range Upper Limit-Std Units",
  STAT    = "Completion Status",
  REASND  = "Reason Not Done",
  NAM     = "Vendor Name",
  SPEC    = "Specimen Type",
  METHOD  = "Method of Test or Examination",
  BLFL    = "Baseline Flag",
  LOC     = "Location of the Observation",
  EVAL    = "Evaluator",
  RESCAT  = "Result Category",
  OCCUR   = "Occurrence",
  PRESP   = "Pre-Specified",
  MOOD    = "Mood",
  DOSE    = "Dose",
  DOSU    = "Dose Units",
  DOSFRM  = "Dose Form",
  DOSFRQ  = "Dosing Frequency per Interval",
  ROUTE   = "Route of Administration",
  ADJ     = "Reason for Dose Adjustment",
  INDC    = "Indication",
  DUR     = "Duration",
  DTC     = "Date/Time of Collection",
  STDTC   = "Start Date/Time",
  ENDTC   = "End Date/Time",
  DY      = "Study Day of Visit/Collection/Exam",
  STDY    = "Study Day of Start",
  ENDY    = "Study Day of End",
  TPT     = "Planned Time Point Name",
  TPTNUM  = "Planned Time Point Number",
  ENRTPT  = "End Relative to Reference Time Point",
  ENTPT   = "End Reference Time Point",
  VAL     = "Comment",
  SER     = "Serious Event",
  ACN     = "Action Taken with Study Treatment",
  REL     = "Causality",
  OUT     = "Outcome of Adverse Event",
  TOXGR   = "Standard Toxicity Grade",
  SEV     = "Severity/Intensity",
  BODSYS  = "Body System or Organ Class",
  BDSYCD  = "Body System or Organ Class Code",
  LLT     = "Lowest Level Term",
  LLTCD   = "Lowest Level Term Code",
  PTCD    = "Preferred Term Code",
  HLT     = "High Level Term",
  HLTCD   = "High Level Term Code",
  HLGT    = "High Level Group Term",
  HLGTCD  = "High Level Group Term Code",
  SOC     = "Primary System Organ Class",
  SOCCD   = "Primary System Organ Class Code",
  SCONG   = "Congenital Anomaly or Birth Defect",
  SDISAB  = "Persist or Signif Disability/Incapacity",
  SDTH    = "Results in Death",
  SHOSP   = "Requires or Prolongs Hospitalization",
  SLIFE   = "Is Life Threatening",
  SOD     = "Occurred with Overdose",
  SMIE    = "Other Medically Important Serious Event"
)

## ドメイン固有ラベル。標準サフィックスでは説明が足りないものだけを持つ。
.AP_LABEL_DOMAIN <- list(
  DD = c(DDTESTCD = "Death Detail Assessment Short Name",
         DDTEST   = "Death Detail Assessment Name"),
  DS = c(DSTERM   = "Reported Term for the Disposition Event",
         DSDECOD  = "Standardized Disposition Term",
         DSCAT    = "Category for Disposition Event",
         DSSTDTC  = "Start Date/Time of Disposition Event"),
  CE = c(CETERM   = "Reported Term for the Clinical Event",
         CEDECOD  = "Dictionary-Derived Clinical Event Term",
         CEOCCUR  = "Clinical Event Occurrence",
         CEPRESP  = "Clinical Event Pre-specified"),
  AE = c(AETERM   = "Reported Term for the Adverse Event",
         AEDECOD  = "Dictionary-Derived Term",
         AESTDTC  = "Start Date/Time of Adverse Event",
         AEENDTC  = "End Date/Time of Adverse Event"),
  MH = c(MHTERM   = "Reported Term for the Medical History",
         MHDECOD  = "Dictionary-Derived Term",
         MHOCCUR  = "Medical History Occurrence",
         MHPRESP  = "Medical History Event Pre-Specified"),
  CM = c(CMTRT    = "Reported Name of Drug, Med, or Therapy",
         CMDECOD  = "Standardized Medication Name",
         CMOCCUR  = "CM Occurrence",
         CMPRESP  = "CM Pre-specified",
         CMDUR    = "Duration of Treatment"),
  EC = c(ECTRT    = "Name of Treatment",
         ECMOOD   = "Mood",
         ECOCCUR  = "Occurrence",
         ECPRESP  = "Pre-Specified",
         ECDOSE   = "Dose per Administration",
         ECADJ    = "Reason for Dose Adjustment"),
  PR = c(PRTRT    = "Reported Name of Procedure",
         PROCCUR  = "Procedure Occurrence",
         PRPRESP  = "Procedure Pre-specified",
         PRINDC   = "Indication"),
  RS = c(RSTESTCD = "Response Assessment Short Name",
         RSTEST   = "Response Assessment Name",
         RSEVAL   = "Evaluator"),
  FA = c(FATESTCD = "Findings About Test Short Name",
         FATEST   = "Findings About Test Name",
         FAOBJ    = "Object of the Observation"),
  MB = c(MBTESTCD = "Microbiology Test or Finding Short Name",
         MBTEST   = "Microbiology Test or Finding Name",
         MBRESCAT = "Result Category"),
  QS = c(QSTESTCD = "Question Short Name",
         QSTEST    = "Question Name"),
  LB = c(LBTESTCD = "Lab Test or Examination Short Name",
         LBTEST   = "Lab Test or Examination Name"),
  VS = c(VSTESTCD = "Vital Signs Test Short Name",
         VSTEST   = "Vital Signs Test Name"),
  CO = c(COVAL    = "Comment",
         COSPID   = "Sponsor-Defined Identifier")
)

## 変数1つのラベルを返す。ドメイン固有 → 完全一致 → サフィックスの順で引く。
ap_label <- function(varname, domain = NULL) {
  vn <- toupper(varname)
  if (!is.null(domain)) {
    dl <- .AP_LABEL_DOMAIN[[toupper(domain)]]
    if (!is.null(dl) && vn %in% names(dl)) return(unname(dl[vn]))
  }
  if (vn %in% names(.AP_LABEL_EXACT)) return(unname(.AP_LABEL_EXACT[vn]))
  if (!is.null(domain)) {
    d <- toupper(domain)
    if (startsWith(vn, d) && nchar(vn) > nchar(d)) {
      sfx <- substring(vn, nchar(d) + 1)
      if (sfx %in% names(.AP_LABEL_SUFFIX)) return(unname(.AP_LABEL_SUFFIX[sfx]))
    }
  }
  vn
}

## ---------------------------------------------------------------------------------
## Dataset-JSON v1.1
## ---------------------------------------------------------------------------------
## 仕様は CDISC Dataset-JSON v1.1.0。SAS 系（program/sas/<試験ID>_SDTMtoJSON.sas）
## が出す構造と同じ形にして、JSON 段階で突合できるようにする。
## 先頭列 ITEMGROUPDATASEQ は必須（CDISC CORE が要求する。docs/spec/sdtm-spec.md §6.1）。

AP_DATASETJSON_VERSION <- "1.1.0"

## 列の値と変数名から Dataset-JSON の dataType を決める。
## SDTM 層は日付を ISO 8601 の文字列のまま保持する（docs/spec/sdtm-spec.md §2.3）ため、
## --DTC 系は値の型ではなく変数名で date と判定する。
## 整数として扱う変数（--SEQ・--DY・VISITNUM・AGE・MedDRAコード・基準範囲）は integer、
## 残る数値は float、それ以外は string。
## mode="adam" では数値をすべて float とする。ADaM 層は define.xml を持たず、
## 整数か否かの区別が突合の役に立たないため。ただし ITEMGROUPDATASEQ は Dataset-JSON が
## レコード識別子として定める連番の列なので、層を問わず integer にする（SAS 側と同じ）。
ap_datatype <- function(x, varname = "", mode = "sdtm") {
  vn <- toupper(varname)
  if (inherits(x, "Date")) return("date")
  if (vn == "ITEMGROUPDATASEQ") return("integer")
  if (mode == "adam") return(if (is.numeric(x)) "float" else "string")
  if (grepl("DTC$", vn)) return("date")
  if (is.numeric(x)) {
    if (grepl("(SEQ|DY|STDY|ENDY|TPTNUM)$", vn)) return("integer")
    if (vn %in% c("VISITNUM", "AGE", "TAETORD")) return("integer")   # TAETORD は要素の順序で整数
    if (grepl("(LLTCD|PTCD|HLTCD|HLGTCD|BDSYCD|SOCCD|STNRLO|STNRHI)$", vn)) return("integer")
    return("float")
  }
  "string"
}

## 文字列列のバイト長の最大値。Dataset-JSON の length に入れる。
ap_maxlen <- function(x) {
  v <- ap_chr(x)
  if (!length(v)) return(1L)
  m <- max(nchar(v, type = "bytes"), 0L)
  as.integer(max(m, 1L))
}

## Dataset-JSON を1本書き出す。
##   df       : data.frame。ITEMGROUPDATASEQ は含めない（ここで先頭に付ける）
##   path     : 出力パス
##   domain   : ドメイン名／データセット名（大文字）
##   ds_label : データセットのラベル
##   labels   : 名前付き文字ベクトル。列ラベルを明示するときに渡す
##   itemgrp  : itemGroupOID の接頭辞（SDTM は "IG."、ADaM も同じ）
##   study_oid・mdv_oid・file_oid_prefix : 試験の OID。既定値を持たせない。
##     試験の値を汎用の部品に埋めると、次の試験が黙って別の試験の OID を出す
ap_write_dataset_json <- function(df, path, domain, ds_label,
                                     labels = NULL, originator = "R", mode = "sdtm",
                                     study_oid, mdv_oid, file_oid_prefix) {
  domain <- toupper(domain)
  ap_mkdir(dirname(path))

  n <- nrow(df)
  seqcol <- data.frame(ITEMGROUPDATASEQ = seq_len(max(n, 0L)))
  if (n == 0L) seqcol <- data.frame(ITEMGROUPDATASEQ = integer(0))
  d <- cbind(seqcol, df)

  cols <- lapply(names(d), function(v) {
    x  <- d[[v]]
    dt <- ap_datatype(x, v, mode)
    lb <- if (!is.null(labels) && v %in% names(labels)) unname(labels[v]) else
          if (v == "ITEMGROUPDATASEQ") "Record identifier" else ap_label(v, domain)
    oid <- if (v == "ITEMGROUPDATASEQ") "ITEMGROUPDATASEQ"
           else if (v %in% c("STUDYID", "USUBJID")) paste0("IT.", v)
           else paste0("IT.", domain, ".", v)
    out <- list(itemOID = unbox(oid), name = unbox(v),
                label = unbox(lb), dataType = unbox(dt))
    if (dt %in% c("string", "date")) out$length <- unbox(ap_maxlen(x))
    out
  })

  ## 行は値の配列。Date は ISO 8601 の文字列で書く。
  dd <- d
  for (v in names(dd)) if (inherits(dd[[v]], "Date")) dd[[v]] <- format(dd[[v]], "%Y-%m-%d")

  obj <- list(
    datasetJSONCreationDateTime = unbox(format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")),
    datasetJSONVersion = unbox(AP_DATASETJSON_VERSION),
    fileOID = unbox(paste0(file_oid_prefix, ".", domain)),
    originator = unbox(originator),
    studyOID = unbox(study_oid),
    metaDataVersionOID = unbox(mdv_oid),
    itemGroupOID = unbox(paste0("IG.", domain)),
    name = unbox(domain),
    label = unbox(ds_label),
    records = unbox(as.integer(n)),
    columns = cols,
    rows = dd
  )

  json <- toJSON(obj, dataframe = "values", na = "null", null = "null",
                 digits = NA, pretty = 2, auto_unbox = FALSE)
  ## BOM を付けない（CDISC CORE の JSON パーサが読めないため。docs/spec/sdtm-spec.md §6.1）
  con <- file(path, open = "wb")
  on.exit(close(con))
  writeBin(charToRaw(as.character(json)), con)
  invisible(path)
}

## Dataset-JSON を data.frame として読む。列の型は columns の dataType に従う。
## 属性 dsmeta に name・label・records・columns（メタデータ）を持たせる。
ap_read_dataset_json <- function(path) {
  if (!file.exists(path)) ap_stop("見つかりません: %s", path)
  j <- fromJSON(path, simplifyVector = FALSE)
  cols <- j$columns
  nm   <- vapply(cols, function(c) c$name, character(1))
  dt   <- vapply(cols, function(c) c$dataType, character(1))

  nrows <- length(j$rows)
  out <- vector("list", length(nm))
  names(out) <- nm
  for (i in seq_along(nm)) {
    v <- vapply(j$rows, function(r) {
      x <- r[[i]]
      if (is.null(x)) NA_character_ else as.character(x)
    }, character(1))
    out[[i]] <- switch(dt[i],
      integer  = as.integer(v),
      float    = as.numeric(v),
      double   = as.numeric(v),
      decimal  = as.numeric(v),
      date     = v,
      v)
  }
  d <- as.data.frame(out, stringsAsFactors = FALSE, check.names = FALSE)
  if (nrows == 0L) d <- d[0, , drop = FALSE]

  meta <- data.frame(
    name     = nm,
    label    = vapply(cols, function(c) if (is.null(c$label)) "" else c$label, character(1)),
    dataType = dt,
    length   = vapply(cols, function(c) if (is.null(c$length)) NA_integer_ else as.integer(c$length),
                      integer(1)),
    stringsAsFactors = FALSE
  )
  attr(d, "dsmeta") <- list(name = j$name, label = j$label,
                            records = j$records, columns = meta)
  d
}

## ---------------------------------------------------------------------------------
## レビュー用CSV
## ---------------------------------------------------------------------------------
## PI が Excel で中身を確認するための出力。UTF-8 BOM 付きで書き、Excel が
## 日本語を文字化けせずに開けるようにする。突合には使わない（正は JSON）。

ap_write_review_csv <- function(df, path) {
  ap_mkdir(dirname(path))
  d <- df
  for (v in names(d)) {
    x <- d[[v]]
    if (inherits(x, "Date")) d[[v]] <- format(x, "%Y-%m-%d")
  }
  con <- file(path, open = "wb")
  on.exit(close(con))
  writeBin(charToRaw("﻿"), con)
  tf <- tempfile(fileext = ".csv")
  utils::write.csv(d, tf, row.names = FALSE, na = "", fileEncoding = "UTF-8")
  writeBin(readBin(tf, "raw", file.info(tf)$size), con)
  unlink(tf)
  invisible(path)
}

## ---------------------------------------------------------------------------------
## 変数順
## ---------------------------------------------------------------------------------
## SDTM の標準変数順は input/ext/sdtm_variable_order.csv が持つ
## （docs/spec/sdtm-spec.md §2.2.1）。無い場合は警告を出して現在の順のまま返す。

ap_load_var_order <- function(ext_dir) {
  f <- file.path(ext_dir, "sdtm_variable_order.csv")
  if (!file.exists(f)) {
    ap_warn("sdtm_variable_order.csv がありません。変数順は受領CSVの順のままにします。")
    return(NULL)
  }
  d <- utils::read.csv(f, colClasses = "character", check.names = FALSE,
                       stringsAsFactors = FALSE)
  names(d) <- toupper(trimws(names(d)))
  d
}

## ---------------------------------------------------------------------------------
## 検証ヘルパ
## ---------------------------------------------------------------------------------

## --SEQ の被験者内一意性（docs/spec/sdtm-spec.md §2.4）。
ap_check_seq_unique <- function(df, seqvar, domain) {
  if (!all(c("USUBJID", seqvar) %in% names(df))) return(invisible(FALSE))
  k <- paste(df$USUBJID, df[[seqvar]], sep = "|")
  dup <- sum(duplicated(k))
  if (dup > 0) {
    ap_warn("[%s] %s が被験者内で重複しています（%d 件）。再採番の要否を確認すること。",
               domain, seqvar, dup)
    return(invisible(FALSE))
  }
  invisible(TRUE)
}

## USUBJID が DM に含まれること。
ap_check_usubjid <- function(df, dm_usubjid, domain) {
  bad <- setdiff(unique(ap_chr(df$USUBJID)), c("", dm_usubjid))
  if (length(bad)) {
    ap_stop("[%s] DM に無い USUBJID があります: %s",
               domain, paste(head(bad, 5), collapse = ", "))
  }
  invisible(TRUE)
}

## ---------------------------------------------------------------------------------
## データセットの突合
## ---------------------------------------------------------------------------------
## SAS 系と R 系の同名データセットを Dataset-JSON の段階で突合する。
## 判定の対象はデータ値と変数の構成であり、ラベル・dataType・length は
## 参考差分として別に報告する（docs/spec/r-pipeline-spec.md「突合の対象」）。

## 値を比較用の文字列へ落とす。数値は有効数字15桁で丸め、NA と空文字を同一視する。
.ap_cmpval <- function(x) {
  if (is.numeric(x)) {
    v <- ifelse(is.na(x), "", formatC(x, format = "g", digits = 15))
  } else {
    v <- ap_chr(x)
  }
  v
}

## 数値として比較できるか
.ap_both_num <- function(x, y) is.numeric(x) && is.numeric(y)

## 1データセットを突合する。戻り値は報告行と不一致件数。
##   a, b   : data.frame（a を SAS 系、b を R 系とする）
##   keys   : 突合キーの変数名
##   name   : データセット名（報告に出す）
##   tol    : 実数の相対許容差
ap_compare <- function(a, b, keys, name, tol = 1e-8,
                          label_a = "SAS", label_b = "R") {
  L <- character(); ndiff <- 0L
  say <- function(fmt, ...) L <<- c(L, sprintf(fmt, ...))

  say("── %s ──", name)
  say("  行数        : %s %d / %s %d", label_a, nrow(a), label_b, nrow(b))
  if (nrow(a) != nrow(b)) ndiff <- ndiff + 1L

  ## 変数の過不足
  only_a <- setdiff(names(a), names(b))
  only_b <- setdiff(names(b), names(a))
  common <- intersect(names(a), names(b))
  say("  変数        : 共通 %d / %s のみ %d / %s のみ %d",
      length(common), label_a, length(only_a), label_b, length(only_b))
  if (length(only_a)) { say("    %s のみ : %s", label_a, paste(only_a, collapse = ", ")); ndiff <- ndiff + 1L }
  if (length(only_b)) { say("    %s のみ : %s", label_b, paste(only_b, collapse = ", ")); ndiff <- ndiff + 1L }

  ## 変数の並び（共通変数の相対順序）
  oa <- names(a)[names(a) %in% common]
  ob <- names(b)[names(b) %in% common]
  if (!identical(oa, ob)) {
    say("    変数の並びが違います（先頭の相違: %s / %s）",
        oa[which(oa != ob)[1]], ob[which(oa != ob)[1]])
  }

  ## キー
  k <- keys[keys %in% common]
  if (!length(k)) {
    say("    突合キーがありません。値の突合を行いません。")
    return(list(lines = L, ndiff = ndiff + 1L))
  }
  mk <- function(d) do.call(paste, c(lapply(k, function(v) .ap_cmpval(d[[v]])), sep = "|"))
  ka <- mk(a); kb <- mk(b)
  dup_a <- sum(duplicated(ka)); dup_b <- sum(duplicated(kb))
  if (dup_a || dup_b) {
    say("    キー重複    : %s %d / %s %d（キー: %s）",
        label_a, dup_a, label_b, dup_b, paste(k, collapse = "+"))
    ndiff <- ndiff + 1L
  }
  ea <- setdiff(ka, kb); eb <- setdiff(kb, ka)
  if (length(ea) || length(eb)) {
    say("    キーの過不足: %s のみ %d 行 / %s のみ %d 行", label_a, length(ea), label_b, length(eb))
    if (length(ea)) say("      例: %s", paste(utils::head(ea, 3), collapse = " / "))
    if (length(eb)) say("      例: %s", paste(utils::head(eb, 3), collapse = " / "))
    ndiff <- ndiff + 1L
  }

  ## 共通キーで値を突合
  both <- intersect(ka, kb)
  ia <- match(both, ka); ib <- match(both, kb)
  vars <- setdiff(common, character(0))
  bad <- list()
  for (v in vars) {
    xa <- a[[v]][ia]; xb <- b[[v]][ib]
    if (.ap_both_num(xa, xb)) {
      den <- pmax(abs(xa), abs(xb), 1, na.rm = TRUE)
      d <- ifelse(is.na(xa) & is.na(xb), 0,
           ifelse(is.na(xa) | is.na(xb), Inf, abs(xa - xb) / den))
      n <- sum(d > tol)
    } else {
      n <- sum(.ap_cmpval(xa) != .ap_cmpval(xb))
    }
    if (n > 0) bad[[v]] <- n
  }
  say("  値の突合    : 共通キー %d 行 × 共通変数 %d 個、不一致のある変数 %d 個",
      length(both), length(vars), length(bad))
  if (length(bad)) {
    ndiff <- ndiff + length(bad)
    ord <- order(-unlist(bad))
    for (v in names(bad)[ord]) {
      xa <- a[[v]][ia]; xb <- b[[v]][ib]
      sa <- .ap_cmpval(xa); sb <- .ap_cmpval(xb)
      i <- which(sa != sb)
      if (!length(i)) i <- which(!is.na(xa) | !is.na(xb))
      ex <- utils::head(i, 3)
      say("    %-12s 不一致 %d 行  例: %s",
          v, bad[[v]],
          paste(sprintf("[%s] %s→%s", both[ex], sa[ex], sb[ex]), collapse = " / "))
    }
  }
  list(lines = L, ndiff = ndiff)
}

## メタデータ（ラベル・型・長さ）の差分。判定には使わず参考として報告する。
ap_compare_meta <- function(ma, mb, name, label_a = "SAS", label_b = "R") {
  L <- character()
  say <- function(fmt, ...) L <<- c(L, sprintf(fmt, ...))
  common <- intersect(ma$name, mb$name)
  ia <- match(common, ma$name); ib <- match(common, mb$name)
  dl <- common[ap_chr(ma$label[ia])    != ap_chr(mb$label[ib])]
  dt <- common[ap_chr(ma$dataType[ia]) != ap_chr(mb$dataType[ib])]
  dn <- common[!is.na(ma$length[ia]) & !is.na(mb$length[ib]) & ma$length[ia] != mb$length[ib]]
  say("  参考差分    : ラベル %d / 型 %d / 長さ %d", length(dl), length(dt), length(dn))
  if (length(dt)) {
    say("    型の相違  : %s", paste(sprintf("%s(%s→%s)", dt,
        ma$dataType[match(dt, ma$name)], mb$dataType[match(dt, mb$name)]), collapse = ", "))
  }
  L
}
