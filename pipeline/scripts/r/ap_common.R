## ---------------------------------------------------------------------------------
## program name : ap_common.R
## description  : R系パイプライン（CSVtoSDTM・SDTMtoADaM・Compare・ARD）の共通基盤。
##                パス解決、Dataset-JSON v1.1 の読み書き、レビュー用CSVの書き出し、
##                変数属性の正本（docs/metadata/variable-map.csv）の読み取り、ログを持つ。
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
## 納品パッケージも同じ相対位置に置く（reproduce/ がリポジトリと同じ並びになる）ので、
## 配布形態のための別の探し先は持たない（2026-08-31）。
.ap_cfg <- NULL
ap_trial_config <- function() {
  if (!is.null(.ap_cfg)) return(.ap_cfg)
  d <- ap_script_dir()
  cand <- c(file.path(d, "..", "..", "docs", "metadata", "trial.json"),
            file.path(d, "..", "docs", "metadata", "trial.json"),
            file.path(d, "docs", "metadata", "trial.json"))
  for (p in cand) if (file.exists(p)) {
    .ap_cfg <<- jsonlite::fromJSON(p, simplifyVector = TRUE)
    return(.ap_cfg)
  }
  stop("trial.json が見つかりません（探した場所: ",
       paste(normalizePath(cand, winslash = "/", mustWork = FALSE), collapse = "、"), "）")
}

## データルート。次の順で探し、最初に見つかったものを使う。
##   1. 環境変数 AKIKO_TRIAL_ROOT
##   2. スクリプト位置から上へ辿る（納品パッケージ。program/r から ../.. が reproduce/）
##   3. Box（AKIKO_BOX_ROOT、macOS の Box Drive、~/Box、<USERPROFILE>/Box のいずれか配下の、
##      docs/metadata/trial.json の box_path が指す場所）
## 判定は input/rawdata/DM.csv の存在で行う。データが無い場所を黙って使わないため。
ap_root <- function(quiet = FALSE) {
  has_data <- function(p) file.exists(file.path(p, "input", "rawdata", "DM.csv"))
  norm <- function(p) normalizePath(p, winslash = "/", mustWork = FALSE)

  ## 出力先を本番から隔離する口。SAS の autoexec.sas と runcommon.py が見るのと
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

## 仕様ファイル（図表の宣言・表示文言のカタログ・受入基準）の場所。
## 納品パッケージは docs/ の該当ファイルを同じ相対位置へ写して同梱するので、リポジトリで
## 実行するときと配った先とで探し先が同じになる（2026-08-31。それまでは input/spec/ へ
## 平らに写しており、読む側が2つの並びを知っている必要があった）。
ap_spec <- function(name) {
  d <- ap_script_dir()
  ## 機械が読む仕様は docs/metadata/ に置く（下に external/・trial-design/ がある）。
  ## 機械が読む受入基準は docs/validation/acceptance/ に置く（2026-08-31 に metadata から移した）。
  ## 納品パッケージも同じ相対位置に置くので、配布形態のための別の探し先は持たない。
  ## program/r から見た相対（../..）が本筋で、リポジトリ直下や docs の隣から source した
  ## ときのために d と d/.. も試す。データルートは見ない（仕様を読むだけなら要らない）
  sub <- c(file.path("metadata", name), file.path("metadata", "external", name),
           file.path("metadata", "trial-design", name),
           file.path("validation", "acceptance", name), name)
  base <- c(file.path(d, "..", ".."), d, file.path(d, ".."))
  cand <- as.vector(t(outer(base, sub, function(b, s) file.path(b, "docs", s))))
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
## 変数属性の正本
## ---------------------------------------------------------------------------------
## ラベル・宣言長と ADaM の変数の並びは docs/metadata/variable-map.csv が正本である。
## 規則は docs/spec/sdtm-spec.md §2.2.2・§2.2.3 と docs/spec/adam-spec.md §11 が持つ。
## 2026-09-05 まで R 系はここに標準ラベルの辞書を持ち、宣言長を実データの最大バイト長で
## 代用していた。属性を実装が持つかぎり、その実装を持たない側（R だけの端末、PI の手元）で
## 値を再現できない。正本を読むのはこの節だけにして、呼び出し側に値を書かせない。

## 名前付きベクトルを作る（stats::setNames に依らない）。
.ap_named <- function(x, nm) { names(x) <- nm; x }

.ap_varmap <- NULL
ap_var_map <- function() {
  if (!is.null(.ap_varmap)) return(.ap_varmap)
  d <- utils::read.csv(ap_spec("variable-map.csv"), colClasses = "character",
                       check.names = FALSE, stringsAsFactors = FALSE)
  names(d) <- trimws(names(d))
  need <- c("layer", "dataset", "variable", "label_en", "length", "order")
  if (!all(need %in% names(d)))
    ap_stop("variable-map.csv に列がありません: %s",
            paste(setdiff(need, names(d)), collapse = "・"))
  .ap_varmap <<- d
  d
}

## 1データセット分の属性。変数名を名前に持つベクトル3本で返す。
ap_var_attr <- function(layer, dataset) {
  d <- ap_var_map()
  d <- d[d$layer == tolower(layer) & toupper(d$dataset) == toupper(dataset), , drop = FALSE]
  if (!nrow(d))
    ap_stop("variable-map.csv に %s/%s の行がありません（属性の正本）。",
            tolower(layer), toupper(dataset))
  v <- toupper(trimws(d$variable))
  list(label  = .ap_named(trimws(d$label_en), v),
       length = .ap_named(suppressWarnings(as.integer(d$length)), v),
       order  = .ap_named(suppressWarnings(as.integer(d$order)), v))
}

## ADaM の列を variable-map.csv の order で並べる（docs/spec/adam-spec.md §11）。
## SDTM は標準が並びを定めるので ap_load_var_order() を使う。
## order に無い列を黙って末尾へ置くと宣言の抜けが出力から見えないので警告を出す。
ap_order_vars <- function(df, layer, dataset) {
  o <- ap_var_attr(layer, dataset)$order
  o <- o[!is.na(o)]
  if (!length(o))
    ap_stop("variable-map.csv の %s/%s に order がありません。",
            tolower(layer), toupper(dataset))
  head <- names(sort(o))
  head <- head[head %in% names(df)]
  tail <- setdiff(names(df), head)
  if (length(tail))
    ap_warn("[%s] order が宣言されていない列を末尾へ置いた（%d 件）: %s",
            toupper(dataset), length(tail), paste(tail, collapse = ", "))
  df[, c(head, tail), drop = FALSE]
}

## データセットのラベルと OID の正本は docs/metadata/sdtm_datasets.csv（受領 define.xml
## 由来。docs/spec/sdtm-spec.md §2.1）。ドメインのラベルは SDTMIG の版で文言が変わるので
## 実装へ書かない。
.ap_dsmeta <- NULL
ap_dataset_meta <- function(dataset = NULL) {
  if (is.null(.ap_dsmeta)) {
    d <- utils::read.csv(ap_spec("sdtm_datasets.csv"), colClasses = "character",
                         check.names = FALSE, stringsAsFactors = FALSE)
    names(d) <- trimws(names(d))
    d$dataset <- toupper(trimws(d$dataset))
    .ap_dsmeta <<- d
  }
  if (is.null(dataset)) return(.ap_dsmeta)
  r <- .ap_dsmeta[.ap_dsmeta$dataset == toupper(dataset), , drop = FALSE]
  if (nrow(r) != 1L)
    ap_stop("sdtm_datasets.csv に %s の行が %d 件あります。", toupper(dataset), nrow(r))
  as.list(r[1, ])
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
## integer にするのは、定義の上で整数しか取らない変数（--SEQ・--DY・VISITNUM・AGE・
## MedDRA コード）だけとし、残る数値は float、それ以外は string とする。
## 基準範囲（--STNRLO・--STNRHI）は検査値と同じ尺度を持つので小数を取り得る。
## 2026-09-06 まで名前だけで integer としていたため、Dataset-JSON から読み戻す側が
## 定量域の下限 0.01 を 0 に丸め、分子遺伝学的効果の判定が1件 NQ から DT へ動いた。
## 名前の規則を「float と言い切れるものだけ float」から「integer と言い切れるものだけ
## integer」へ反転させた。同じ規則を SAS 側（<試験ID>_SDTMtoJSON.sas）と
## define.xml（scripts/update-define-xml.py）が持つ。3実装の一致は
## scripts/check-datatype-rule.py が見る。
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
    if (grepl("(SEQ|DY|TPTNUM|LLTCD|PTCD|HLTCD|HLGTCD|BDSYCD|SOCCD)$", vn)) return("integer")
    if (vn %in% c("VISITNUM", "AGE", "TAETORD")) return("integer")   # TAETORD は要素の順序で整数
    return("float")
  }
  "string"
}

## Dataset-JSON を1本書き出す。
##   df       : data.frame。ITEMGROUPDATASEQ は含めない（ここで先頭に付ける）
##   path     : 出力パス
##   domain   : ドメイン名／データセット名（大文字）
##   ds_label : データセットのラベル
##   mode     : 層（"sdtm" / "adam"）。dataType の決め方と、属性の正本
##     （variable-map.csv の layer）の引き先を兼ねる
##   itemgrp  : itemGroupOID の接頭辞（SDTM は "IG."、ADaM も同じ）
##   study_oid・mdv_oid・file_oid_prefix : 試験の OID。既定値を持たせない。
##     試験の値を汎用の部品に埋めると、次の試験が黙って別の試験の OID を出す
## ラベル・宣言長は引数で受けない。呼び出し側から流し込めるようにすると、正本を読む
## 場所が呼び出しの数だけ増える（2026-09-05 に labels 引数を外した）。
ap_write_dataset_json <- function(df, path, domain, ds_label,
                                     originator = "R", mode = "sdtm",
                                     study_oid, mdv_oid, file_oid_prefix) {
  domain <- toupper(domain)
  ap_mkdir(dirname(path))

  n <- nrow(df)
  seqcol <- data.frame(ITEMGROUPDATASEQ = seq_len(max(n, 0L)))
  if (n == 0L) seqcol <- data.frame(ITEMGROUPDATASEQ = integer(0))
  d <- cbind(seqcol, df)

  ## ラベルと宣言長は variable-map.csv から引く。itemOID は必ずデータセットで修飾する
  ## （docs/spec/sdtm-spec.md §2.2.2・§2.2.3）。宣言が無い列は黙って通さない。
  va <- ap_var_attr(mode, domain)
  cols <- lapply(names(d), function(v) {
    x  <- d[[v]]
    dt <- ap_datatype(x, v, mode)
    if (v == "ITEMGROUPDATASEQ")
      return(list(itemOID = unbox("ITEMGROUPDATASEQ"), name = unbox(v),
                  label = unbox("Record identifier"), dataType = unbox(dt)))
    vu <- toupper(v)
    if (!vu %in% names(va$label))
      ap_stop("variable-map.csv に %s/%s.%s の行がありません（属性の正本）。",
              tolower(mode), domain, vu)
    out <- list(itemOID = unbox(paste0("IT.", domain, ".", vu)), name = unbox(v),
                label = unbox(va$label[[vu]]), dataType = unbox(dt))
    if (dt %in% c("string", "date")) {
      L <- va$length[[vu]]
      if (is.na(L))
        ap_stop("variable-map.csv の %s/%s.%s に length がありません（%s 型）。",
                tolower(mode), domain, vu, dt)
      out$length <- unbox(as.integer(L))
    }
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
## SDTM の標準変数順は docs/metadata/external/sdtm_variable_order.csv が持つ
## （docs/spec/sdtm-spec.md §2.2.1）。CDISC ライブラリからの抽出物で、2026-09-05 に
## Box の input/ext から外部標準の写しの置き場へ移した（git 管理外だったため、R だけの
## 端末では正本が手元に無かった）。プログラムと同じリポジトリに入ったので、無い場合に
## 受領CSVの順で出す逃げ道は持たない。

ap_load_var_order <- function() {
  d <- utils::read.csv(ap_spec("sdtm_variable_order.csv"), colClasses = "character",
                       check.names = FALSE, stringsAsFactors = FALSE)
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
