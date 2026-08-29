## ---------------------------------------------------------------------------------
## program name : tlf_ops.R
## description  : 図表の表示型と描画（R系の汎用の部品）。<試験ID>_TLF.R が読み込む。
## comment      : SAS の program/sas/macro/tlf_ops.sas に対応する。表示の作法（列の組み立て・
##                並べ方・セル台帳への記録・HTML と Excel の書き出し）と、固有の語を持たない
##                表示型をここに置く。疾患・試験の知識を含む表示型は tlf_ops_trial.R が持つ。
##                判定の基準は nnh/trial-planning-and-analysis の examples/README.md
##                「表示型の判定」。
##
##                駆動は表示型を名前で引く（d_<表示型>）。登録表を持たないので、汎用と
##                試験固有のどちらに定義してあっても同じように呼べる。
##
##                R には名前空間が無いので、呼び出し側が用意した LANG・IDX・LC・ARD・P・
##                XLSX などをそのまま見る。読み込む順序は <試験ID>_TLF.R が決める。
## ---------------------------------------------------------------------------------

## 試験の識別子。成果物のファイル名とページ表題に使う。試験固有の値は
## docs/metadata/trial.json だけが持つ
TRIAL <- ap_trial_config()$trial_id

## 一覧の元データを表番号で引き当てる口。試験側が差し替える（既定は該当なし）
tlf_listdata <- function(lblid) NULL

## ---------------------------------------------------------------------------------
## 表示文言（label-catalog）。日本語版は label_ja、英語版は label_en を使う。
## カタログに無いキーは識別子をそのまま出す（SAS系と同じ振る舞い）。
## ---------------------------------------------------------------------------------
lab <- function(kind, key) {
  h <- LC[LC$kind == kind & LC$key == key, ]
  if (!nrow(h)) return("")
  v <- if (LANG == "ja") h$label_ja[1] else h$label_en[1]
  if (is.na(v)) "" else v
}
fx <- function(key) {
  v <- lab("fixed", key)
  if (nzchar(v)) v else key
}
lvl <- function(id) {                        # 水準・背景表の行項目の表示名
  if (is.na(id) || !nzchar(id)) return("")
  for (k in c("level", "bgitem")) {
    v <- lab(k, id)
    if (nzchar(v)) return(v)
  }
  id
}
## 水準の並び順（label-catalog.csv の kind=level の order 列。SAS の _lvcat.LVORD と同じ）。
## 番号を入れていない水準は 9999 を返し、呼び出し側が識別子で並べる。表示名で並べると
## 符号化を変えたときに順序が変わり、日英でも並びが食い違う（2026-08-23）
lvord <- function(id) {
  if (is.na(id) || !nzchar(id)) return(9999L)
  h <- LC[LC$kind == "level" & LC$key == id, ]
  if (!nrow(h) || is.na(h$order[1]) || !nzchar(as.character(h$order[1]))) return(9999L)
  v <- suppressWarnings(as.integer(h$order[1]))
  if (is.na(v)) 9999L else v
}
## 来院番号（label-catalog.csv の kind=level の visitnum 列。SAS の _lvcat.LVVISIT と同じ）。
## SDTM の TV ドメインの VISITNUM を写したもので、治療相の識別子にだけ入る。図表の並びは
## 来院計画の順を原則とするため、順序番号の次のキーに使う。入っていない水準は 99999 を
## 返し、呼び出し側が識別子で並べる（2026-08-23）
lvvisit <- function(id) {
  if (is.na(id) || !nzchar(id)) return(99999L)
  h <- LC[LC$kind == "level" & LC$key == id, ]
  if (!nrow(h) || is.na(h$visitnum[1]) || !nzchar(as.character(h$visitnum[1]))) return(99999L)
  v <- suppressWarnings(as.integer(h$visitnum[1]))
  if (is.na(v)) 99999L else v
}

## ---------------------------------------------------------------------------------
## 数値の書式。SAS の put(x, 6.1) 等に合わせる。欠測は空にする
## （TLF.sas が options missing="" で走っているため）。
## ---------------------------------------------------------------------------------
## SAS の w.d は 0.5 を絶対値の大きい側へ丸める（put(4.45, 12.1) は 4.5）。R の
## formatC・sprintf は C ライブラリの丸めで二進表現に従うため 4.4 になる。表の桁を
## SAS へ合わせるので、書式へ渡す前にこちらで丸める（2026-08-20）
sasround <- function(x, d) {
  m <- 10 ^ d
  sign(x) * floor(abs(x) * m + 0.5) / m
}
f1 <- function(x) ifelse(is.na(x), "", formatC(sasround(x, 1), format = "f", digits = 1))
f0 <- function(x) ifelse(is.na(x), "", formatC(sasround(x, 0), format = "f", digits = 0))
## 文字の並びを SAS の proc sort へ合わせる。SAS は UTF-8 セッションで動かすので
## （scripts/sas-common.ps1）UTF-8 のバイト列で並び、R の method="radix" も同じ
## UTF-8 バイト順なので、そのまま渡せば一致する。R の既定（LC_COLLATE に従う並び）は
## 記号と大小文字を無視して SAS と違うため使わない。
## 2026-08-21 まで SAS が CP932 セッションだったため、CP932 のバイト列へ直してから
## 並べる bytekey() を挟んでいた。UTF-8 へ統一したので不要になった。
## label-catalog の表題が持つ SAS のマクロ変数（&ph・&tk）を実際の値へ置き換える。表を
## 治療相 × TKI区分で分ける T_5_4_7_3 の表題がこの形で、SAS は title 文の二重引用符の中で
## 解決する。値を渡さないときは印を落として表番号だけの表題にする（節の見出しに使う）
ttl_sub <- function(ti, ph = NULL, tk = NULL) {
  if (is.null(ph) || is.null(tk)) return(trimws(gsub("\\s*&(ph|tk)\\b", "", ti)))
  ti <- sub("&ph", ph, ti, fixed = TRUE)
  sub("&tk", tk, ti, fixed = TRUE)
}
ordc <- function(...) {
  do.call(order, c(list(...), list(method = "radix")))
}
catx <- function(sep, ...) {                 # SAS の catx（欠測を落として連結）
  v <- c(...)
  paste(v[nzchar(v) & !is.na(v)], collapse = sep)
}
## ARD の該当行から統計量を1つ取る（SAS の max(case when ...) と同じ）
## 行はあるが値が全欠測のとき（n=1 の標準偏差など）は欠測を返す。max(v, na.rm=TRUE) は
## この場合 -Inf を返し、書式へ渡すと「SD -Inf」になる（SAS は欠測なので空。2026-08-20 是正）
stat_of <- function(d, name) {
  v <- d$stat_num[d$stat_name == name]
  v <- v[!is.na(v)]
  if (!length(v)) NA_real_ else max(v)
}
## tlf-index の filter（GROUP1L='INDUCTION' の形）を ARD の列名へ写して絞る
COLMAP <- c(GROUP1L = "group1_level", GROUP1 = "group1", SUBSET = "data_subset",
            VARIABLE = "variable", VARLEVEL = "variable_level",
            ANALSET = "analysis_set", CONTEXT = "context")
apply_filter <- function(d, f) {
  if (is.na(f) || !nzchar(f)) return(d)
  for (part in strsplit(f, "\\s+and\\s+")[[1]]) {
    m <- regmatches(part, regexec("^\\s*([A-Z0-9_]+)\\s*=\\s*['\"]([^'\"]*)['\"]\\s*$", part))[[1]]
    ## ワイルドカード（SUBSET=*）は「値ごとに表を分ける」印で絞り込みではない。
    ## 解析IDの集合を求めるとき（an_of）は分ける前の全体を見るので、ここは素通りさせる
    if (grepl("*", part, fixed = TRUE)) next
    if (length(m) != 3) stop("filter を解釈できません: ", f)
    col <- COLMAP[[m[2]]]
    if (is.null(col)) stop("filter の列を知りません: ", m[2])
    d <- d[d[[col]] == m[3], ]
  }
  d
}

## ---------------------------------------------------------------------------------
## トレーサビリティ索引への相互リンク（メタデータの単位）
## 図表 → その図表を作っている解析 → 解析対象の ADaM 変数、の順にリンクを並べる。
## 索引側のノードの住所（#n=out:T_5_4_1・#n=an:An-5.4.1-01・#n=adam:ADTTE.AVAL）を使う。
## ---------------------------------------------------------------------------------
VM <- read_csv(ap_spec("variable-map.csv"), col_types = cols(.default = "c"),
               progress = FALSE, na = character())
IX <- "../../deliver/r/traceability.html"  # output/tlf/r-<言語>/ から見たトレーサビリティ索引
adam_of <- function(item) {              # 解析項目 → ADaM の <データセット>.<変数>
  h <- VM[VM$layer == "adam" & VM$variable == item, ]
  if (nrow(h)) return(unique(paste0(h$dataset, ".", h$variable)))
  ## 変数名で一致しない項目（EFS・OS のように行を識別する値）は PARAMCD の実値で探す。
  ## 見つかったらその行の解析値（AVAL）を指す。トレーサビリティ索引と同じ考え方。
  ds <- paramcd_ds(item)
  if (length(ds)) paste0(ds, ".AVAL") else character(0)
}
## ADaM の Dataset-JSON から PARAMCD の実値を集める（初回だけ読む）
.pcd <- NULL
paramcd_ds <- function(v) {
  if (is.null(.pcd)) {
    m <- list()
    for (f in list.files(P$ads_r_json, pattern = "\\.json$", full.names = TRUE)) {
      j <- try(jsonlite::fromJSON(f, simplifyVector = FALSE), silent = TRUE)
      if (inherits(j, "try-error")) next
      nm <- vapply(j$columns, function(c) c$name, "")
      i <- match("PARAMCD", nm)
      if (is.na(i)) next
      ds <- toupper(sub("\\.json$", "", basename(f)))
      vals <- unique(vapply(j$rows, function(r)
        if (is.null(r[[i]])) NA_character_ else as.character(r[[i]]), ""))
      for (x in vals[!is.na(vals)]) m[[x]] <- unique(c(m[[x]], ds))
    }
    .pcd <<- m
  }
  .pcd[[v]]
}
an_of <- function(r) {                   # その図表を作っている解析
  if (!is.na(r$analysis_id) && nzchar(r$analysis_id)) return(r$analysis_id)
  ## KM の図は解析IDを持たず ADTTE から曲線を描く。表番号が指す解析グループ
  ## （F_5_4_1 なら Out-5.4.1）で同じ PARAMCD を扱う解析を、同じ推定値として指す
  if ((is.na(r$output_id) || !nzchar(r$output_id)) &&
      !is.na(r$paramcd) && nzchar(r$paramcd)) {
    oid <- paste0("Out-", gsub("_", ".", sub("^[TF]_", "", r$lblid)))
    x <- unique(ARD$analysis_id[ARD$output_id == oid & ARD$variable == r$paramcd])
    return(x[!is.na(x) & nzchar(x)])
  }
  if (is.na(r$output_id) || !nzchar(r$output_id)) return(character(0))
  d <- apply_filter(ARD[ARD$output_id == r$output_id, ], r$filter)
  x <- unique(d$analysis_id)
  x[!is.na(x) & nzchar(x)]
}
a_link <- function(href, text) paste0("<a href=\"", href, "\">", esc_html(text), "</a>")
nav_html <- function(r) {
  ids <- an_of(r)
  items <- unique(ARD$variable[ARD$analysis_id %in% ids & nzchar(ARD$variable)])
  ## 図（KM）は解析IDを持たずに PARAMCD で描く。その PARAMCD の実値から ADaM を指す
  if (!is.na(r$paramcd) && nzchar(r$paramcd)) items <- unique(c(items, r$paramcd))
  advar <- unique(unlist(lapply(items, adam_of)))
  other <- if (LANG == "ja") "en" else "ja"
  ## 見出しの後ろの記号と区切りは言語で替える。英語版に全角のコロンと全角の空白を
  ## 出すと組版が乱れるため（2026-08-20）
  cln <- if (LANG == "ja") "：" else ": "
  sep <- if (LANG == "ja") "　" else " "
  more <- function(n) if (LANG == "ja") paste0(" ほか ", n) else paste0(" and ", n, " more")
  ## 図は ARD の結果値ではなく ADTTE から曲線を描く。指している解析は同じ推定値を出したもの
  ## なので、そう断る（断らないと ARD から描いたように読める）。表は ARD の結果値そのもの
  km <- length(ids) > 0 && (is.na(r$analysis_id) || !nzchar(r$analysis_id)) &&
        (is.na(r$output_id) || !nzchar(r$output_id))
  anlab <- if (LANG == "ja") "解析結果(ARD)" else "ARD (Analysis Result Data)"
  annote <- if (!km) "" else if (LANG == "ja") "（同じ推定値。この図は ADaM から直接描く）"
            else " (same estimates; this figure is drawn from ADaM)"
  paste0(
    "\n<div class=\"nav\">\n<p>",
    a_link(paste0(IX, "#n=out:", r$lblid), if (LANG == "ja") "トレーサビリティ索引でこの図表を辿る"
                                           else "Trace this output in the index"),
    "</p>\n<p>", a_link(paste0("../r-", other, "/", r$lblid, ".html"),
                 if (LANG == "ja") "英語版" else "Japanese Version"), "</p>\n",
    if (length(ids)) paste0("<p>", anlab, cln,
      paste(vapply(head(sort(ids), 12), function(i)
        a_link(paste0(IX, "#n=an:", i), i), ""), collapse = sep),
      if (length(ids) > 12) more(length(ids) - 12) else "", annote, "</p>\n") else "",
    if (length(advar)) paste0("<p>", if (LANG == "ja") "ADaM 変数" else "ADaM variables",
      cln, paste(vapply(head(sort(advar), 12), function(v)
        a_link(paste0(IX, "#n=adam:", v), v), ""), collapse = sep),
      if (length(advar) > 12) more(length(advar) - 12) else "", "</p>\n") else "",
    "</div>")
}

## ---------------------------------------------------------------------------------
## 表示型ごとの表の組み立て
## 戻りは list(cols = 見出しの文字列ベクトル, rows = 行のリスト（文字列ベクトル）,
##            note = 表の下に置く注記, keycol = 行キーに使う列番号)
## ---------------------------------------------------------------------------------
d_tab_prop <- function(r) {
  d <- ARD[ARD$analysis_id == r$analysis_id & ARD$context == "categorical", ]
  if (!nrow(d)) return(NULL)
  g <- split(d, d$variable_level)
  rows <- lapply(names(g), function(k) {
    x <- g[[k]]
    n <- stat_of(x, "n"); N <- stat_of(x, "N"); p <- stat_of(x, "p")
    lo <- stat_of(x, "lcl"); hi <- stat_of(x, "ucl")
    list(sort = -ifelse(is.na(n), -Inf, n),
         cells = c(lvl(k), catx("/", f0(n), f0(N)), f1(p), catx(" - ", f1(lo), f1(hi))))
  })
  rows <- rows[order(vapply(rows, function(x) x$sort, 0))]
  list(cols = c(lab("rowlbl", r$lblid), fx("nden"), fx("prop"), fx("ci95")),
       rows = lapply(rows, function(x) x$cells), note = "")
}

d_tab_prop_grp <- function(r) {
  d <- ARD[ARD$analysis_id == r$analysis_id & ARD$context == "categorical", ]
  if (!nrow(d)) return(NULL)
  gs <- strsplit(r$groups, "\\|")[[1]]
  ls <- strsplit(r$levels, "\\|")[[1]]
  cell <- function(gr, lv) {
    x <- d[d$group1_level == gr & d$variable_level == lv, ]
    if (!nrow(x)) return("")
    paste0(f0(stat_of(x, "n")), " (", f1(stat_of(x, "p")), ")")
  }
  head_row <- c(fx("nsubj"), vapply(gs, function(gr) {
    x <- d[d$group1_level == gr, ]
    if (!nrow(x)) "" else f0(stat_of(x, "N"))
  }, ""))
  rows <- c(list(head_row),
            lapply(ls, function(lv) c(lvl(lv), vapply(gs, cell, "", lv = lv))))
  list(cols = c(lab("rowlbl", r$lblid), vapply(gs, lvl, "")), rows = rows, note = "")
}

## 時点の並びは SAS と同じく VARLEVEL から数字を取り出して昇順にする（1年・2年・3年…）
timept_order <- function(v) suppressWarnings(as.numeric(gsub("[^0-9.]", "", v)))

## 注記の文言（label-catalog の note_km・note_cif）は SAS のマクロ変数を含む。
## 例: "N=&_n, events=&_ev, censored=&_cn"。同じ値を ARD から入れて置き換える。
subst_note <- function(txt, d) {
  ## 長いキーから置き換える（&_ne を先に処理しないと &_n が食って "87e" になる）
  v <- list("&_ev" = "nevent", "&_cn" = "ncensor", "&_ne" = "nevent",
            "&_nc" = "ncompet", "&_n" = "N")
  for (k in names(v)) {
    if (grepl(k, txt, fixed = TRUE)) {
      txt <- gsub(k, f0(stat_of(d, v[[k]])), txt, fixed = TRUE)
    }
  }
  txt
}

## 指定時点（Y1〜Y5）の行だけを取る。除外ではなく採用で書くのは、Mth-KM が指定時点の
## ほかに生存曲線の全イベント時点（T<年>）と中央値（MEDIAN）と例数（水準なし）を持つため。
## 除外の列挙で書いていたときに曲線の行が表へ入り、表 5.4.1 が5行のところ89行出ていた
## （2026-08-29 に検出。ars-migration-plan.md 第3段が「時点で絞る形に変える」としていた
## 積み残し）。両系統が同じように出るので、系統間の突合では捕まらない
d_surv <- function(r, ctx, est, esthdr, note) {
  d <- ARD[ARD$analysis_id == r$analysis_id & ARD$context == ctx &
             grepl("^Y[0-9]", nz(ARD$variable_level)), ]
  if (!nrow(d)) return(NULL)
  g <- split(d, d$variable_level)
  ord <- ordc(timept_order(names(g)), names(g))
  rows <- lapply(names(g)[ord], function(k) {
    x <- g[[k]]
    c(lvl(k), f1(100 * stat_of(x, est)), f1(100 * stat_of(x, "se")),
      catx(" - ", f1(100 * stat_of(x, "lcl")), f1(100 * stat_of(x, "ucl"))))
  })
  all <- ARD[ARD$analysis_id == r$analysis_id, ]
  list(cols = c(fx("timepoint"), esthdr, fx("se"), fx("ci95")), rows = rows,
       note = subst_note(fx(note), all))
}
d_tab_km  <- function(r) d_surv(r, "survival", "surv", fx("surv"), "note_km")
d_tab_cif <- function(r) d_surv(r, "cuminc",   "cif",  fx("cif"),  "note_cif")

d_tab_bg <- function(r) {
  d <- apply_filter(ARD[ARD$output_id == r$output_id, ], r$filter)
  if (!nrow(d)) return(NULL)
  itemvar <- if (is.na(r$item_var) || !nzchar(r$item_var)) "VARIABLE" else r$item_var
  ## item_var は | 区切りで2つまで受ける（SAS の %tab_bg と同じ）。2つ渡すと行項目を
  ## 「1つ目 / 2つ目」と連結する。ARD が行を区別する軸を2つ持つ表のため（2026-08-23）
  icols <- vapply(strsplit(itemvar, "|", fixed = TRUE)[[1]], function(v) COLMAP[[v]], "")
  ## 宣言の levels= があればその順を最優先にする（SAS の %tab_bg と同じ）。来院と無関係な
  ## 区分（到達までの時間の区分など）を表ごとに指定するための口で、指定に無い水準は
  ## 後ろへ回す（2026-08-23）
  lvseq <- if (is.na(r$levels) || !nzchar(r$levels)) character(0) else
             strsplit(r$levels, "|", fixed = TRUE)[[1]]
  seqof <- function(id) { i <- match(nz(id), lvseq); if (is.na(i)) 99999L else i }
  key <- paste(d$analysis_id, d$variable, d$group1_level, d$variable_level, sep = "\u0001")
  g <- split(d, key)
  rows <- lapply(names(g), function(k) {
    x <- g[[k]]
    ctx <- max(x$context)
    item <- paste(vapply(icols, function(cc) lvl(x[[cc]][1]), ""), collapse = " / ")
    if (ctx == "continuous") {
      med <- f1(stat_of(x, "median")); mn <- f1(stat_of(x, "min"))
      mx <- f1(stat_of(x, "max")); me <- f1(stat_of(x, "mean"))
      sd <- f1(stat_of(x, "sd")); nm <- stat_of(x, "nmiss")
      val <- paste0(med, " [", mn, ", ", mx, "] ", fx("mean"), " ", me, " SD ", sd)
      ## 欠測数を足す前に trimws する。SD が定義できない（n=1 など）と val が "… SD " で
      ## 終わり、そのまま足すと空白が2つ並ぶ。SAS 側は catx が欠測を落とすため1つになり、
      ## セル台帳の突合で値ではなく空白の差として出る（issues.md 24。表 5.2.5 の CyA）
      if (!is.na(nm) && nm > 0) val <- paste0(trimws(val), " ", fx("missing"), f0(nm))
      list(sort = c(x$analysis_id[1], "99999", "9999", "99999", ""),
           cells = c(item, "", val))
    } else {
      list(sort = c(x$analysis_id[1],
                    sprintf("%05d", seqof(x$variable_level[1])),
                    sprintf("%04d", lvord(x$variable_level[1])),
                    sprintf("%05d", lvvisit(x$variable_level[1])),
                    nz(x$variable_level[1])),
           cells = c(item, lvl(x$variable_level[1]),
                     paste0(f0(stat_of(x, "n")), " (", f1(stat_of(x, "p")), ")")))
    }
  })
  o <- ordc(vapply(rows, function(x) x$sort[1], ""),
            vapply(rows, function(x) x$sort[2], ""),
            vapply(rows, function(x) x$sort[3], ""),
            vapply(rows, function(x) x$sort[4], ""),
            vapply(rows, function(x) x$sort[5], ""))
  list(cols = c(fx(if (is.na(r$item_label) || !nzchar(r$item_label)) "item" else r$item_label),
                fx("categ"), fx("summary")),
       rows = lapply(rows[o], function(x) x$cells), note = fx("note_bg"))
}

d_tab_aegr <- function(r) {
  flt <- r$filter
  ## ワイルドカードを含む宣言（SUBSET=* and GROUP1L=*）は、ARD が持つ TKI区分 × 治療相の
  ## 組合せで表を分ける。SAS 側も %tab_aegr が同じ印を見て同じ並び（TKI区分 → 治療相）で
  ## 分ける。宣言を18行へ展開しないのは、組合せの正本を ARD に置いたままにするため
  if (!is.na(flt) && nzchar(flt) && grepl("*", flt, fixed = TRUE)) {
    d0 <- ARD[ARD$output_id == r$output_id, ]
    if (!nrow(d0)) return(NULL)
    cmb <- unique(data.frame(ph = d0$group1_level, tk = d0$data_subset,
                             stringsAsFactors = FALSE))
    cmb <- cmb[ordc(cmb$tk, cmb$ph), , drop = FALSE]
    out <- lapply(seq_len(nrow(cmb)), function(i) {
      rr <- r
      rr$filter <- sprintf("GROUP1L='%s' and SUBSET='%s'", cmb$ph[i], cmb$tk[i])
      tb <- d_tab_aegr(rr)
      if (is.null(tb) || !length(tb$rows)) return(NULL)
      ## 表題は label-catalog の「Adverse Events &ph &tk」を SAS と同じ値で置き換える
      list(tab = tb, ph = cmb$ph[i], tk = cmb$tk[i])
    })
    out <- out[!vapply(out, is.null, TRUE)]
    if (!length(out)) return(NULL)
    return(list(multi = out))
  }
  d <- apply_filter(ARD[ARD$output_id == r$output_id, ], flt)
  if (!nrow(d)) return(NULL)
  ## グレードの区切りは宣言の levels= が持つ。空なら CTCAE の4区分を既定にする。
  ## 区切り方は表示の選択なので表示型に直書きしない（2026-08-29。SAS の %tab_aegr と同じ）
  glv <- if (is.na(r$levels) || !nzchar(r$levels)) c("Grade 1-2", "Grade 3", "Grade 4", "Grade 5")
         else strsplit(r$levels, "|", fixed = TRUE)[[1]]
  key <- paste(d$group1_level, d$data_subset, d$variable, sep = "\u0001")
  g <- split(d, key)
  gr <- function(x, lv) {
    v <- x$stat_num[x$stat_name == "n" & x$variable_level == lv]
    if (!length(v)) "" else f0(max(v, na.rm = TRUE))
  }
  rows <- lapply(names(g), function(k) {
    x <- g[[k]]
    list(sort = c(x$group1_level[1], x$data_subset[1], x$variable[1]),
         cells = c(x$variable[1], f0(stat_of(x, "N")),
                   vapply(glv, function(g) gr(x, g), "", USE.NAMES = FALSE)))
  })
  o <- ordc(vapply(rows, function(x) x$sort[1], ""),
            vapply(rows, function(x) x$sort[2], ""),
            vapply(rows, function(x) x$sort[3], ""))
  list(cols = c(fx("ae"), fx("denom"), glv),
       rows = lapply(rows[o], function(x) x$cells), note = "")
}

## ---------------------------------------------------------------------------------
## 図（Kaplan-Meier 曲線）。ADTTE から曲線を引き、SVG を HTML へ埋め込む。
## ---------------------------------------------------------------------------------
adtte <- NULL
load_adtte <- function() {
  if (!is.null(adtte)) return(adtte)
  f <- file.path(P$ads_r_json, "adtte.json")
  if (file.exists(f)) {
    j <- jsonlite::fromJSON(f, simplifyVector = FALSE)
    nm <- vapply(j$columns, function(c) c$name, "")
    m <- do.call(rbind, lapply(j$rows, function(r)
      vapply(r, function(v) if (is.null(v)) NA_character_ else as.character(v), "")))
    d <- as.data.frame(m, stringsAsFactors = FALSE)
    names(d) <- nm
  } else {
    f2 <- file.path(P$ads_r_csv, "adtte.csv")
    if (!file.exists(f2)) return(NULL)
    d <- read_csv(f2, col_types = cols(.default = "c"), progress = FALSE, na = character())
  }
  d$AVAL <- suppressWarnings(as.numeric(d$AVAL))
  d$CNSR <- suppressWarnings(as.numeric(d$CNSR))
  adtte <<- d
  d
}

## 95%信頼区間の帯（群ごと）。survfit は時点ごとの下限・上限を持つので、生存曲線と
## 同じ階段の形に直して多角形で塗る。plot(conf.int=TRUE) の破線より、群が2つあるときに
## どちらの区間か見分けやすい。
step_xy <- function(x, y, xmax) {
  keep <- x <= xmax
  x <- c(0, x[keep], xmax)
  y <- c(1, y[keep], if (any(keep)) y[keep][sum(keep)] else 1)
  n <- length(x)
  list(x = rep(x, each = 2)[-1], y = rep(y, each = 2)[-(2 * n)])
}
km_band <- function(fit, cols, xmax) {
  ## 上限・下限は生存確率が0に達すると NA になる。直前の値を引き継ぐ
  ffill <- function(v) { v[1] <- if (is.na(v[1])) 1 else v[1]
    for (i in seq_along(v)[-1]) if (is.na(v[i])) v[i] <- v[i - 1]
    v }
  ix <- if (is.null(fit$strata)) list(seq_along(fit$time)) else
    split(seq_along(fit$time), rep(seq_along(fit$strata), fit$strata))
  for (g in seq_along(ix)) {
    j <- ix[[g]]
    if (is.null(fit$lower) || !length(j)) next
    lo <- step_xy(fit$time[j], ffill(fit$lower[j]), xmax)
    up <- step_xy(fit$time[j], ffill(fit$upper[j]), xmax)
    graphics::polygon(c(lo$x, rev(up$x)), c(lo$y, rev(up$y)), border = NA,
                      col = grDevices::adjustcolor(cols[g], alpha.f = 0.15))
  }
}

## 曲線の当てはめ。デバイスを開く前に済ませ、描くものが無ければ NULL を返す。
## 信頼区間は線形形式（Greenwood の分散をそのまま用いる）にする。SAP A-2 が定める方式で、
## SAS の PROC LIFETEST は CONFTYPE=LINEAR、ARD の %ard_km・ard_km も同じ。survfit の
## 既定は conf.type="log" で、同じデータでも信頼限界が 0.6〜0.7 ポイント違う。表と図で
## 別の方式の区間を並べないため、ここで揃える（2026-08-29）。この当てはめは Excel の
## チャートの元にもなるので、Excel のシートに載る値も ARD と同じ方式の値になる
km_fit <- function(r) {
  d <- load_adtte()
  if (is.null(d)) return(NULL)
  x <- d[d$PARAMCD == r$paramcd, ]
  if (!is.na(r$where) && nzchar(r$where)) x <- apply_filter_adtte(x, r$where)
  if (!nrow(x)) return(NULL)
  x$Y <- x$AVAL / 365.25
  x$EV <- as.integer(x$CNSR == 0)              # ADaM 準拠：0=イベント・1=打ち切り
  fm <- if (!is.na(r$group) && nzchar(r$group)) {
    stats::as.formula(paste0("survival::Surv(Y, EV) ~ ", r$group))
  } else {
    stats::as.formula("survival::Surv(Y, EV) ~ 1")
  }
  survival::survfit(fm, data = x, conf.type = "plain")
}

## 当てはめを Excel が読める形へ開く。群ごとに時点・生存確率・信頼限界・打ち切り数を持つ。
## 群が1つ（層別しない図）のときは群名を空にして、系列名に群名を付けない
km_curves <- function(fit) {
  ix <- if (is.null(fit$strata)) list(seq_along(fit$time)) else
    split(seq_along(fit$time), rep(seq_along(fit$strata), fit$strata))
  gl <- if (is.null(fit$strata)) "" else sub("^[^=]*=", "", names(fit$strata))
  lapply(seq_along(ix), function(g) {
    j <- ix[[g]]
    list(label = gl[g], time = fit$time[j], surv = fit$surv[j],
         lcl = if (is.null(fit$lower)) rep(NA_real_, length(j)) else fit$lower[j],
         ucl = if (is.null(fit$upper)) rep(NA_real_, length(j)) else fit$upper[j],
         ncensor = fit$n.censor[j])
  })
}

## リスク集合数。年ごとの値は曲線の点からは決まらない（イベントの無い年でも打ち切りで
## 減る）ので、当てはめから直接取る。extend=TRUE は最終観察より後の時点も返させる
km_atrisk <- function(fit, times = 0:5) {
  s <- summary(fit, times = times, extend = TRUE)
  gl <- if (is.null(fit$strata)) "" else sub("^[^=]*=", "", names(fit$strata))
  st <- if (is.null(s$strata)) rep("", length(s$time)) else sub("^[^=]*=", "", as.character(s$strata))
  list(times = times,
       n = lapply(gl, function(g) {
         v <- s$n.risk[st == g]
         length(v) <- length(times)
         ifelse(is.na(v), 0, v)
       }))
}

## 下描き。開いているデバイスへ描く（SVG を HTML へ埋める）
km_paint <- function(fit) {
  ng <- max(1, length(fit$strata))
  cols <- seq_len(ng)
  op <- graphics::par(mar = c(4.2, 4.2, 0.6, 0.6))
  # 枠と軸だけ先に描き、信頼区間の帯を敷いてから曲線を重ねる。帯を後から描くと
  # 曲線と打ち切りの目印が帯の下に隠れる
  plot(fit, xlab = fx("xaxis_km"), ylab = fx("yaxis_km"), ylim = c(0, 1),
       xlim = c(0, 5), conf.int = FALSE, mark.time = FALSE, col = NA)
  km_band(fit, cols, xmax = 5)
  graphics::lines(fit, conf.int = FALSE, mark.time = TRUE, col = cols, lwd = 2)
  if (!is.null(fit$strata)) {
    graphics::legend("bottomleft", legend = sub("^[^=]*=", "", names(fit$strata)),
                     col = seq_along(fit$strata), lwd = 2, bty = "n")
  }
  graphics::par(op)
  invisible(NULL)
}

## 当てはめは呼び出し側が作る（Excel のチャートも同じ当てはめから作るため、2度当てない）
d_fig_km <- function(r, fit) {
  if (is.null(fit)) return(NULL)
  tmp <- tempfile(fileext = ".svg")
  grDevices::svg(tmp, width = 6.3, height = 4.3, pointsize = 10, family = SVGFONT)
  on.exit(if (!is.null(grDevices::dev.list())) grDevices::dev.off(), add = TRUE)
  km_paint(fit)
  grDevices::dev.off()
  on.exit()
  svg <- paste(readLines(tmp, warn = FALSE), collapse = "\n")
  unlink(tmp)
  svg_localize(sub("^<\\?xml[^>]*\\?>\\s*(<!DOCTYPE[^>]*>)?\\s*", "", svg), r$lblid)
}

## ---------------------------------------------------------------------------------
## SVG の書体と識別子
##
## cairo の SVG は文字を字形の輪郭に変換して埋め込むため、指定した書体に日本語の字形が
## 無いと軸ラベルが豆腐（□）になる。既定の書体（sans）は端末によって欧文だけの書体に
## 解決されるので、日本語の字形を持つ書体を明示する。端末ごとに入っている書体が違うため、
## fontconfig（fc-list）で実在を確かめてから使い、見つからなければ既定に任せる。
## 環境変数 AP_SVG_FONT で上書きできる。
## ---------------------------------------------------------------------------------
svg_font <- function() {
  e <- Sys.getenv("AP_SVG_FONT")
  if (nzchar(e)) return(e)
  cand <- switch(Sys.info()[["sysname"]],
    Darwin  = c("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic", "Osaka"),
    Windows = c("Yu Gothic", "Meiryo", "MS Gothic"),
    c("Noto Sans CJK JP", "IPAexGothic", "VL PGothic", "TakaoPGothic"))
  installed <- function(f) {
    o <- suppressWarnings(try(system2("fc-list", shQuote(f), stdout = TRUE,
                                      stderr = FALSE), silent = TRUE))
    !inherits(o, "try-error") && length(o) > 0
  }
  has_fc <- nzchar(unname(Sys.which("fc-list")))
  for (f in cand) if (!has_fc || installed(f)) return(f)
  ""                                  # 見つからない（軸ラベルが豆腐になる可能性を記録する）
}
SVGFONT <- svg_font()
if (nzchar(SVGFONT)) ap_note("図の書体: %s", SVGFONT) else
  ap_note("図の書体: 見つからないため既定（日本語の軸ラベルが崩れる可能性）")

## cairo は SVG ごとに glyph-0-0 のような同じ識別子を振る。1ページに複数の図を並べると
## 後の図の <use> が先の図の字形を拾い、別の文字や豆腐が出る。図ごとに接頭辞を付けて分ける。
svg_localize <- function(s, tag) {
  tag <- gsub("[^A-Za-z0-9_]", "_", tag)
  s <- gsub('id="([^"]+)"', paste0('id="', tag, '-\\1"'), s)
  s <- gsub('(xlink:)?href="#([^"]+)"', paste0('\\1href="#', tag, '-\\2"'), s)
  gsub("url\\(#([^)]+)\\)", paste0("url(#", tag, "-\\1)"), s)
}
## ADTTE の絞り込み（FASFL='Y' の形）。列名はそのまま使う
apply_filter_adtte <- function(d, f) {
  for (part in strsplit(f, "\\s+and\\s+")[[1]]) {
    m <- regmatches(part, regexec("^\\s*([A-Za-z0-9_]+)\\s*=\\s*'([^']*)'\\s*$", part))[[1]]
    if (length(m) != 3) stop("where を解釈できません: ", f)
    d <- d[d[[m[2]]] == m[3], ]
  }
  d
}

## 複数の解析を行ブロックとして1つの表へ積む（SAS の %tab_prop_grp_multi）。
## blocks は「解析ID:水準1|水準2|…」を ~ で区切ったもの。行の並びは指定した順。
d_tab_prop_grp_multi <- function(r) {
  gs <- strsplit(r$groups, "\\|")[[1]]
  spec <- lapply(strsplit(r$blocks, "~", fixed = TRUE)[[1]], function(b) {
    p <- strsplit(b, ":", fixed = TRUE)[[1]]
    list(aid = p[1], lvs = strsplit(p[2], "\\|")[[1]])
  })
  aids <- unique(vapply(spec, function(s) s$aid, ""))
  d <- ARD[ARD$analysis_id %in% aids & ARD$context == "categorical", ]
  if (!nrow(d)) return(NULL)
  cell <- function(gr, aid, lv) {
    x <- d[d$analysis_id == aid & d$group1_level == gr & d$variable_level == lv, ]
    if (!nrow(x)) return("")
    paste0(f0(stat_of(x, "n")), " (", f1(stat_of(x, "p")), ")")
  }
  ## 先頭に対象症例数の行を置く（SAS の _gp2 の第1行と同じ）
  rows <- list(c(fx("nsubj"), vapply(gs, function(gr) {
    x <- d[d$group1_level == gr, ]
    if (!nrow(x)) "" else f0(stat_of(x, "N"))
  }, "")))
  for (s in spec) {
    for (lv in s$lvs) {
      rows[[length(rows) + 1L]] <- c(lvl(lv), vapply(gs, cell, "", aid = s$aid, lv = lv))
    }
  }
  list(cols = c(lab("rowlbl", r$lblid), vapply(gs, lvl, "")), rows = rows, note = "")
}

## 評価時点を行に持つ表（SAS の %tab_prop_tp）。行の並びと表示名は docs/metadata/mr-timepoint.csv。
## SAS 側も %_tdmr_load が同じ CSV を読む（宣言はデータセット名を持たない）。
## 宣言の subset= で渡した部分集合の解析がある水準は、割合ではなくその件数をカッコに入れる。
d_tab_prop_tp <- function(r) {
  d <- ARD[ARD$output_id == r$output_id & ARD$context == "categorical", ]
  if (!nrow(d)) return(NULL)
  ls <- strsplit(r$levels, "\\|")[[1]]
  tp <- read_csv(ap_spec("mr-timepoint.csv"), col_types = cols(.default = "c"),
                 progress = FALSE, na = character())
  tp <- tp[order(suppressWarnings(as.numeric(tp$order))), ]
  ## 件数をカッコに入れる部分集合の名前は宣言の subset= が持つ。試験ごとに違うので
  ## 表示型に直書きしない（2026-08-29。SAS の %tab_prop_tp と同じ）
  sbs  <- nz(r$subset)
  main <- if (nzchar(sbs)) d[!(d$data_subset %in% sbs), ] else d
  nsd  <- if (nzchar(sbs)) d[d$data_subset %in% sbs, ] else d[0, ]
  cell <- function(lv, gr) {
    x <- main[main$group1_level == gr & main$variable_level == lv, ]
    if (!nrow(x)) return("")
    y <- nsd[nsd$group1_level == gr & nsd$variable_level == lv, ]
    if (nrow(y)) paste0(f0(stat_of(x, "n")), " (", f0(stat_of(y, "n")), ")")
    else         paste0(f0(stat_of(x, "n")), " (", f1(stat_of(x, "p")), ")")
  }
  rows <- lapply(seq_len(nrow(tp)), function(i)
    c(tp$label[i], vapply(ls, cell, "", gr = tp$glabel[i])))
  list(cols = c(lab("rowlbl", r$lblid), vapply(ls, lvl, "")), rows = rows, note = "")
}

## 欠測を空文字にする。ARD・ADaM を CSV/JSON から読むと空欄が NA になるため、
## SAS の空白（' '）と同じ扱いへ揃える
nz <- function(x) ifelse(is.na(x), "", trimws(as.character(x)))

## 例数の表（SAS の %tab_count）。1つの output_id の CONTEXT='count' の解析を
## 解析IDの順に1行ずつ並べる。行ラベルは水準の識別子をカタログで引く。
d_tab_count <- function(r) {
  d <- ARD[ARD$output_id == r$output_id & ARD$context == "count" &
             ARD$stat_name == "n", ]
  if (!nrow(d)) return(NULL)
  d <- d[ordc(d$analysis_id), ]
  rows <- lapply(seq_len(nrow(d)), function(i)
    c(lvl(nz(d$variable_level[i])), f0(d$stat_num[i])))
  list(cols = c(fx("categ"), fx("ncnt")), rows = rows, note = "")
}

## コース別の実施状況表（SAS の %tab_crs）。SAP 5.3.4〜5.3.6 の図表案は1節=1表で、
## コースを行ブロックとして積む。コースの並びは ARD が持たないので宣言の levels= が
## 決める（M1-3・M10-12・M4-6 の文字順では SAP の並びにならない）。
## 薬剤・区分の列に GROUP1L を出すのは GROUP1 が変数名を持つときだけで、TKI区分の
## 例数（GROUP1 が空で GROUP1L='TKIGROUP'）は項目の列で表せる。
## 行の並びは コース順 → 解析ID → 水準の識別子。水準は表示名ではなく識別子で並べるので
## 日本語版と英語版で行の並びが変わらない。
d_tab_crs <- function(r) {
  cs <- strsplit(nz(r$levels), "\\|")[[1]]
  d <- ARD[ARD$output_id == r$output_id & ARD$data_subset %in% cs, ]
  if (!nrow(d)) return(NULL)
  co  <- match(d$data_subset, cs)
  key <- paste(co, d$analysis_id, nz(d$group1_level), nz(d$variable),
               nz(d$variable_level), sep = "\u0001")
  ix  <- split(seq_len(nrow(d)), key)
  rows <- lapply(ix, function(j) {
    x   <- d[j, ]
    ctx <- max(x$context)
    grp <- if (nzchar(nz(x$group1[1]))) lvl(nz(x$group1_level[1])) else ""
    if (ctx == "count") {
      cell <- c(lvl(nz(x$variable_level[1])), "", f0(stat_of(x, "n")))
    } else if (ctx == "continuous") {
      med <- f1(stat_of(x, "median")); mn <- f1(stat_of(x, "min"))
      mx  <- f1(stat_of(x, "max"));    me <- f1(stat_of(x, "mean"))
      sd  <- f1(stat_of(x, "sd"));     nm <- stat_of(x, "nmiss")
      val <- paste0(med, " [", mn, ", ", mx, "] ", fx("mean"), " ", me, " SD ", sd)
      if (!is.na(nm) && nm > 0) val <- paste0(trimws(val), " ", fx("missing"), f0(nm))
      cell <- c(lvl(nz(x$variable[1])), "", val)
    } else {
      cell <- c(lvl(nz(x$variable[1])), lvl(nz(x$variable_level[1])),
                paste0(f0(stat_of(x, "n")), " (", f1(stat_of(x, "p")), ")"))
    }
    list(co = co[j][1], aid = x$analysis_id[1], lv = nz(x$variable_level[1]),
         cells = c(lvl(nz(x$data_subset[1])), grp, cell))
  })
  o <- ordc(vapply(rows, function(z) z$co, 0),
            vapply(rows, function(z) z$aid, ""),
            vapply(rows, function(z) z$lv, ""))
  note <- fx("note_bg")
  fo <- lab("footnote", r$lblid)
  if (nzchar(fo)) note <- paste(note, fo)
  list(cols = c(fx("course"), fx("drug_grp"), fx("item"), fx("categ"), fx("summary")),
       rows = lapply(rows[o], function(z) unname(z$cells)), note = note)
}

## ADaM を1つ読む（Dataset-JSON が無ければレビュー用 CSV）。1度読んだら使い回す
.adsc <- new.env(parent = emptyenv())
load_ads <- function(nm) {
  if (exists(nm, envir = .adsc, inherits = FALSE)) return(get(nm, envir = .adsc))
  f <- file.path(P$ads_r_json, paste0(nm, ".json"))
  d <- if (file.exists(f)) ap_read_dataset_json(f) else {
    f2 <- file.path(P$ads_r_csv, paste0(nm, ".csv"))
    if (!file.exists(f2)) NULL
    else read_csv(f2, col_types = cols(.default = "c"), progress = FALSE)
  }
  assign(nm, d, envir = .adsc)
  d
}
load_adsl <- function() load_ads("adsl")
## Dataset-JSON の date 列は ISO の文字列で返る。空欄は NA にしてから Date にする
as_d <- function(s) as.Date(ifelse(nzchar(nz(s)), nz(s), NA_character_))
iso_d <- function(d) ifelse(is.na(d), "", format(d, "%Y-%m-%d"))

d_tab_list <- function(r) {
  vs <- strsplit(nz(r$vars), "[[:space:]]+")[[1]]
  ks <- strsplit(nz(r$labels), "\\|")[[1]]
  ## 元データの作り方は試験ごとに違うので、表番号で引き当てる口だけを持つ。
  ## 既定は該当なしで、試験側の tlf_ops_trial.R が tlf_listdata() を差し替える
  d <- tlf_listdata(r$lblid)
  if (is.null(d) || !nrow(d)) return(NULL)
  rows <- lapply(seq_len(nrow(d)), function(i)
    vapply(vs, function(v) nz(d[[v]][i]), "", USE.NAMES = FALSE))
  list(cols = vapply(ks, fx, "", USE.NAMES = FALSE), rows = rows, note = "")
}

## ---------------------------------------------------------------------------------
## 出力（HTML）
## ---------------------------------------------------------------------------------
esc_html <- function(x) {
  x <- gsub("&", "&amp;", x, fixed = TRUE)
  x <- gsub("<", "&lt;", x, fixed = TRUE)
  gsub(">", "&gt;", x, fixed = TRUE)
}
html_table <- function(t) {
  paste0("<table>\n<tr>",
         paste0("<th>", esc_html(t$cols), "</th>", collapse = ""), "</tr>\n",
         paste0(vapply(t$rows, function(rw)
           paste0("<tr>", paste0("<td>", esc_html(rw), "</td>", collapse = ""), "</tr>"),
           ""), collapse = "\n"),
         "\n</table>")
}
html_block <- function(r, body) {
  ti <- ttl_sub(lab("title", r$lblid))
  if (!nzchar(ti)) ti <- r$lblid
  paste0("<section id=\"", r$lblid, "\">\n<h2>", esc_html(ti), "</h2>\n",
         if (nzchar(lab("subtitle", r$lblid)))
           paste0("<p class=\"su\">", esc_html(lab("subtitle", r$lblid)), "</p>\n") else "",
         body, "\n</section>")
}
HTML_CSS <- paste(
  "body{font-family:\"Hiragino Sans\",\"Yu Gothic UI\",Meiryo,Arial,sans-serif;",
  "margin:24px auto;max-width:1000px;color:#1a1a1a;font-size:14px;line-height:1.6}",
  "h1{font-size:1.1rem}h2{font-size:.98rem;margin:26px 0 4px}",
  "p.su{margin:0 0 6px;color:#555;font-size:.86rem}",
  "p.note{color:#555;font-size:.8rem;margin:4px 0 0}",
  "table{border-collapse:collapse;font-size:.84rem;margin-top:4px}",
  "div.nav{margin-top:14px;padding-top:8px;border-top:1px solid #e2e2e2;font-size:.8rem}",
  ## 通し読み版の目次。図表が100件近くになるので2段組にして一望できるようにする
  "nav.toc{margin:18px 0 26px;padding:12px 16px;border:1px solid #e2e2e2;background:#fafafa}",
  "nav.toc .t{font-weight:600;margin-bottom:6px}",
  "nav.toc ol{margin:0;padding-left:1.6em;columns:2;column-gap:28px;font-size:.85rem}",
  "nav.toc li{margin:1px 0;break-inside:avoid}",
  "@media (max-width:800px){nav.toc ol{columns:1}}",
  "div.nav p{margin:2px 0}",
  "th,td{border:1px solid #ccc;padding:3px 8px;text-align:left;vertical-align:top}",
  "th{background:#f2f4f6;white-space:nowrap}svg{max-width:100%;height:auto}",
  sep = "")
html_page <- function(title, body) {
  paste0("<!DOCTYPE html>\n<html lang=\"", if (LANG == "ja") "ja" else "en",
         "\">\n<head>\n<meta charset=\"utf-8\">\n<title>", esc_html(title),
         "</title>\n<style>", HTML_CSS, "</style>\n</head>\n<body>\n", body,
         "\n</body>\n</html>\n")
}

## ---------------------------------------------------------------------------------
## 本体。言語ごとに図表ごとの HTML・通し読み HTML・セル台帳を出す。
## セル台帳は言語を含めた名前にする（表示文言が言語で変わるため、突合は同じ言語どうしで行う）。
## ---------------------------------------------------------------------------------
render_lang <- function(lang) {
LANG <<- lang
TLFDIR <- ap_tlf_dir("r", LANG)
## 前回の実行が残した図表 HTML を消す。宣言から外れた図表のファイルが残ると
## PI パッケージの相互リンクが片側だけ生きた状態になり、check-pi-package が落ちる
## 消すのは図表ファイル（T_… / F_…）だけ。同じディレクトリに通し読み HTML も置く
if (dir.exists(TLFDIR))
  unlink(list.files(TLFDIR, pattern = "^[TF]_.*[.]html$", full.names = TRUE))
ap_mkdir(TLFDIR)
ap_archive_old(TLFDIR, paste0("^", TRIAL, "_TLF_.*[.](html|rtf|xlsx)$"), LANG)
cells <- list()
html_parts <- character(0)
toc_parts <- character(0)          # 通し読み版の目次（表番号 → ページ内の錨）
n_tab <- n_fig <- n_skip <- 0L
## Excel（言語ごとに1ブック、図表ごとに1シート）。HTML と同じ走査で組む。表の中身を
## 2度作らないためで、シートの並びも宣言の順（章番号順）のまま揃う
TX <- list(toc_sheet = fx("toc"), toc_title = "", toc_no = fx("xl_toc_no"),
           toc_name = fx("xl_toc_name"), toc_back = fx("xl_toc_back"),
           time = fx("xl_time"), surv = fx("yaxis_km"), lcl = fx("xl_lcl"),
           ucl = fx("xl_ucl"), cens = fx("xl_cens"), atrisk = fx("xl_atrisk"),
           curvedata = fx("xl_curvedata"), note_figkm = fx("xl_note_figkm"),
           xaxis = fx("xaxis_km"), yaxis = fx("yaxis_km"))
wb <- if (XLSX) ap_xlsx_new(TX) else NULL
xl_entries <- list()

for (i in seq_len(nrow(IDX))) {
  r <- as.list(IDX[i, ])
  if (r$display == "fig_km") {
    fit <- tryCatch(km_fit(r), error = function(e) {
      ap_note("WARN [%s] 当てはめができない: %s", r$lblid, conditionMessage(e)); NULL })
    svg <- if (is.null(fit)) NULL else tryCatch(d_fig_km(r, fit), error = function(e) {
      ap_note("WARN [%s] 図を描けない: %s", r$lblid, conditionMessage(e)); NULL })
    if (is.null(svg)) { n_skip <- n_skip + 1L; next }
    # 図の読み方（打ち切りの目印と信頼区間の帯）を図の下に置く
    body <- paste0(svg, "\n<p class=\"note\">", esc_html(fx("note_figkm")), "</p>")
    n_fig <- n_fig + 1L
    if (XLSX) {
      ## Excel は画像を貼らず、ブック内のデータ範囲を参照するチャートにする。SVG と同じ
      ## 当てはめから作るので、図と Excel で曲線も信頼限界も同じ値になる
      tryCatch(ap_xlsx_km(wb, r$lblid, ttl_sub(lab("title", r$lblid)),
                             lab("subtitle", r$lblid), km_curves(fit), km_atrisk(fit), TX),
               error = function(e)
                 ap_note("WARN [%s] Excel の図を作れない: %s", r$lblid, conditionMessage(e)))
    }
  } else {
    ## 表示型は名前で引く。登録表を持たないので、汎用と試験固有のどちらに
    ## 定義してあっても駆動は同じ（SAS の %tlf_run が %<表示型>() を呼ぶのと同じ）
    fn <- get0(paste0("d_", r$display), mode = "function")
    if (is.null(fn)) {
      ap_note("WARN [%s] 表示型 %s は未実装", r$lblid, r$display)
      n_skip <- n_skip + 1L; next
    }
    t <- tryCatch(fn(r), error = function(e) {
      ap_note("WARN [%s] 表を作れない: %s", r$lblid, conditionMessage(e)); NULL })
    ## 1つの宣言が表を複数生む場合（tab_aegr の治療相 × TKI区分）は multi で返る。表番号は
    ## 1つなので HTML は1ファイルに並べ、台帳の row_seq は表をまたぐ通し番号にする（SAS の
    ## %_tlfcells も同じ lblid の2度目以降は続きから振る）
    tabs <- if (!is.null(t) && !is.null(t$multi)) t$multi else
            if (!is.null(t) && length(t$rows)) list(list(tab = t, sfx = "")) else list()
    if (!length(tabs)) {
      ap_note("WARN [%s] 結果値がない。表を作らない", r$lblid)
      n_skip <- n_skip + 1L; next
    }
    body <- ""
    roff <- 0L
    xlb <- list()                    # Excel のシートへ積む表（HTML と同じ並び・同じ値）
    for (tt in tabs) {
      tb <- tt$tab
      ti <- ttl_sub(lab("title", r$lblid), tt$ph, tt$tk)
      body <- paste0(body,
                     if (length(tabs) > 1L) paste0("<h3>", esc_html(ti), "</h3>\n") else "",
                     html_table(tb),
                     if (nzchar(tb$note)) paste0("\n<p class=\"note\">",
                                                 esc_html(tb$note), "</p>") else "", "\n")
      n_tab <- n_tab + 1L
      xlb[[length(xlb) + 1L]] <- list(subtitle = if (length(tabs) > 1L) ti else "",
                                      cols = tb$cols, rows = tb$rows, note = tb$note)
      ## セル台帳（SAS系との突合に使う）。1行が1セル
      for (ri in seq_along(tb$rows)) {
        rw <- tb$rows[[ri]]
        for (ci in seq_along(rw)) {
          cells[[length(cells) + 1L]] <- data.frame(
            lblid = r$lblid, display = r$display, row_seq = roff + ri, row_key = rw[1],
            col_seq = ci, col_label = tb$cols[ci], value = rw[ci],
            stringsAsFactors = FALSE)
        }
      }
      roff <- roff + length(tb$rows)
    }
    if (XLSX) {
      tryCatch(ap_xlsx_table(wb, r$lblid, ttl_sub(lab("title", r$lblid)),
                                lab("subtitle", r$lblid), xlb, TX),
               error = function(e)
                 ap_note("WARN [%s] Excel の表を作れない: %s", r$lblid, conditionMessage(e)))
    }
  }
  blk <- html_block(r, body)
  html_parts <- c(html_parts, blk)
  ## 目次の1行。錨は html_block が section へ付ける id（表番号）
  toc_parts <- c(toc_parts,
                 paste0("<li><a href=\"#", r$lblid, "\">",
                        esc_html(ttl_sub(lab("title", r$lblid))), "</a></li>"))
  xl_entries[[length(xl_entries) + 1L]] <- list(lblid = r$lblid,
                                                title = ttl_sub(lab("title", r$lblid)))
  writeLines(html_page(paste0(r$lblid, " ", ttl_sub(lab("title", r$lblid))),
                       paste0(blk, nav_html(r))),
             file.path(TLFDIR, paste0(r$lblid, ".html")))
}

today <- format(Sys.Date(), "%Y%m%d")
base <- paste0(TRIAL, "_TLF_", today, "_", LANG, "_r")
## 全図表を1ページに収めた版。表題は言語ごとに閉じる（英語版に日本語を混ぜない）
whole_ttl <- paste0(TRIAL, if (LANG == "ja") " 図表（R系）" else " Tables and Figures (R)")
## 通し読み版は図表が100件近くになるので、冒頭に目次を置いて同一ページ内の錨へ飛ばす。
## 並びは宣言の順（docs/metadata/tlf-index.csv の seq）で、seq は章番号順に振ってある
toc_ttl <- if (LANG == "ja") "目次" else "Contents"
whole_html <- paste0("<h1>", esc_html(whole_ttl), "</h1>\n",
                     "<nav class=\"toc\"><div class=\"t\">", esc_html(toc_ttl),
                     "</div>\n<ol>\n", paste(toc_parts, collapse = "\n"),
                     "\n</ol>\n</nav>\n",
                     paste(html_parts, collapse = "\n"))
writeLines(html_page(whole_ttl, whole_html),
           file.path(TLFDIR, paste0(base, ".html")))
## Excel は通し読み HTML と同じ名前で同じディレクトリへ置く。日付を名前に持つので、
## 直下には最新の1組だけを残し、以前の版は 旧版/ へ退避してある
if (XLSX) {
  TX$toc_title <- whole_ttl
  xf <- file.path(TLFDIR, paste0(base, ".xlsx"))
  ok <- tryCatch({ ap_xlsx_finish(wb, xl_entries, xf, TX); TRUE },
                 error = function(e) {
                   ap_note("WARN [%s] Excel を保存できない: %s", LANG, conditionMessage(e))
                   FALSE })
  if (ok) ap_note("[%s] Excel: %s（%d シート）", LANG, xf, length(xl_entries))
}
cellsdf <- if (length(cells)) bind_rows(cells) else
  data.frame(lblid = character(), display = character(), row_seq = integer(),
             row_key = character(), col_seq = integer(), col_label = character(),
             value = character())
## 台帳の名前で「どの ARD から描いたか」を分ける。突合の相手を間違えないため。
##   tlf_cells_r_<言語>.csv     R系の描画 × R系の ARD（PI へ渡す系統そのもの）
##   tlf_cells_rsas_<言語>.csv  R系の描画 × SAS系の ARD（描画だけを SAS と比べるとき）
cf <- file.path(P$compare, paste0(if (ARDSRC == "sas") "tlf_cells_rsas_" else "tlf_cells_r_",
                               LANG, ".csv"))
write_csv(cellsdf, cf, na = "")

ap_note("[%s] 表 %d / 図 %d / 作らなかった宣言 %d", LANG, n_tab, n_fig, n_skip)
ap_note("[%s] 通し読み HTML: %s", LANG, file.path(TLFDIR, paste0(base, ".html")))
ap_note("[%s] 図表ごとの HTML: %s（%d ファイル）", LANG, TLFDIR,
           length(list.files(TLFDIR, pattern = "^[TF]_.*[.]html$")))
ap_note("[%s] セル台帳: %s（%d セル）", LANG, cf, nrow(cellsdf))
}
