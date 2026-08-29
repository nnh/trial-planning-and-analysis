## ---------------------------------------------------------------------------------
## program name : ap_xlsx.R
## description  : 図表の Excel 出力（R系）。<試験ID>_TLF.R が読み込んで使う。
## comment      : 配布の正は HTML だが、あわせて Excel を出す。研究者が数値をそのまま扱え、
##                論文の図を自分で調整できるようにするため。方針の正本は nnh/trial-planning-
##                and-analysis の pipeline/analysis-pipeline-plan.md「図表の出力形式」。
##                言語ごとに1ブック、図表ごとに1シートにする。
##
##                このファイルは表示文言を持たない。日本語・英語の別は呼び出し側
##                （TLF.R が label-catalog.csv から引いた文字列）が tx で渡す。
##
##                生存時間曲線はブック内のデータ範囲を参照する Excel のネイティブな
##                チャートにする（{openxlsx2} と {mschart}）。画像を貼るのではないので、
##                研究者が点を足す・軸を変える・色を替えるといった調節を Excel の中で
##                行える。曲線・95%信頼区間・打ち切りの目印を1つの散布図の系列として
##                置き、リスク集合数はチャートの機能ではないのでシート上の別の表にする。
##
##                信頼区間を積み上げ面（帯）で描く案は採らない。面グラフの横軸は分類軸で、
##                イベント時点が等間隔でない曲線と軸を共有できないため、同じ図に置くと
##                帯と曲線の位置がずれる。破線2本で上限・下限を示す。
##
##                書き込みは R6 のメソッド（wb$add_data 等）で行う。同名の関数版
##                （openxlsx2::wb_add_data 等）はブックを深く複製してから書き足すので、
##                88シートのブックへ1セルずつ足す用途では複製の費用が積み上がり、
##                戻り値を受け取り損ねると変更が黙って消える。
## ---------------------------------------------------------------------------------

## 依存は openxlsx2 と mschart の2つ。図表層の他の処理はこの2つを要求しないので、
## 入っていない環境では Excel だけを飛ばして HTML を出し切る（PI へ渡す R 一式は
## renv.lock が両方を固定するが、単独で TLF.R を回す場合に落ちないようにする）
ap_xlsx_ok <- function() {
  requireNamespace("openxlsx2", quietly = TRUE) &&
    requireNamespace("mschart", quietly = TRUE)
}

## シート名。Excel が禁じる文字（: \ / ? * [ ]）と31文字の上限を守る。表番号は
## T_5_4_13_2 の形なのでそのまま通るが、宣言が変わっても壊れないようにする
ap_xlsx_sheet <- function(lblid) {
  substr(gsub("[:\\/?*\\[\\]]", "_", lblid), 1, 31)
}

## 曲線の色。SVG の図が使う R の既定パレット（1=黒、2=赤）と同じ並びにする。
## 群が増えても図と Excel で群と色の対応が変わらない
AP_XL_COL <- c("#000000", "#DF536B", "#61D04F", "#2297E6", "#28E2E5", "#CD0BBC")
AP_XL_GREY <- "#555555"

xl_col <- function(hex) openxlsx2::wb_color(hex = hex)
xl_ref <- function(j) openxlsx2::int2col(j)
xl_nz <- function(x) if (is.null(x) || length(x) == 0 || is.na(x[1])) "" else as.character(x[1])

## ---------------------------------------------------------------------------------
## セルの型。表のセルは HTML と同じ文字列（セル台帳と同じ値）を書くのが原則だが、
## 列の全体が同じ桁数の数値だけなら数値として書く。研究者がそのまま計算に使えるように
## するためで、表示は書式（0・0.0 …）で元の文字列と同じに保つ。
##
## 桁数が混じる列は文字のままにする。列に一括で書式を当てると 12 が 12.0 になり、
## 印字が HTML と食い違うため。先頭が 0 の値（症例番号など）と16桁以上の値も、
## 数値にすると表記が変わるので文字のままにする。
## ---------------------------------------------------------------------------------
ap_xlsx_numcol <- function(v) {
  s <- trimws(as.character(v))
  s <- s[nzchar(s) & !is.na(s)]
  if (!length(s)) return(NULL)
  if (!all(grepl("^-?[0-9]+([.][0-9]+)?$", s))) return(NULL)
  if (any(grepl("^-?0[0-9]", s))) return(NULL)              # 先頭の 0 は意味を持つ
  if (any(nchar(gsub("[^0-9]", "", s)) > 15)) return(NULL)  # 倍精度で表せない桁数
  d <- ifelse(grepl("[.]", s), nchar(sub("^[^.]*[.]", "", s)), 0L)
  if (length(unique(d)) != 1L) return(NULL)
  list(dec = d[1], fmt = if (d[1] == 0L) "0" else paste0("0.", strrep("0", d[1])))
}

## ---------------------------------------------------------------------------------
## ブックを作る。目次を先頭のシートにするため、中身は空のまま最初に作っておき、
## すべての図表を並べ終えてから ap_xlsx_finish が書き込む
## ---------------------------------------------------------------------------------
ap_xlsx_new <- function(tx) {
  wb <- openxlsx2::wb_workbook()
  wb$add_worksheet(tx$toc_sheet, grid_lines = FALSE)
  wb
}

## 表題・副題・目次へのリンクを置き、次に書き始める行番号を返す
xl_head <- function(wb, sh, title, subtitle, tx) {
  wb$add_data(sheet = sh, x = xl_nz(title), dims = "A1")
  wb$add_font(sheet = sh, dims = "A1", bold = "1", size = "12")
  r <- 2L
  if (nzchar(xl_nz(subtitle))) {
    wb$add_data(sheet = sh, x = xl_nz(subtitle), dims = paste0("A", r))
    wb$add_font(sheet = sh, dims = paste0("A", r), color = xl_col(AP_XL_GREY))
    r <- r + 1L
  }
  ## 目次へ戻る（図表が88件あるので、シートを行き来する手がかりを各シートに置く）
  wb$add_formula(sheet = sh, dims = paste0("A", r),
                 x = openxlsx2::create_hyperlink(sheet = tx$toc_sheet, row = 1, col = 1,
                                                 text = tx$toc_back))
  wb$add_font(sheet = sh, dims = paste0("A", r), color = xl_col("#0563C1"),
              underline = "single")
  r + 2L
}

## 見出しの重複を外す。wb_data とチャートは列名で系列を選ぶため一意にする。表でも、
## 同じ見出しが並ぶ列（群が同名のとき）で読み手が迷わないようにする
xl_uniq <- function(v) {
  v <- ifelse(is.na(v) | !nzchar(v), " ", v)
  make.unique(v, sep = " ")
}

## 見出し行と本体の体裁。見出しは太字・薄い塗り・下の罫線、本体は上寄せ
xl_style_table <- function(wb, sh, hdr, nrow_d, nc, fmt = NULL, freeze = TRUE) {
  last <- xl_ref(nc)
  hd <- paste0("A", hdr, ":", last, hdr)
  wb$add_font(sheet = sh, dims = hd, bold = "1")
  wb$add_fill(sheet = sh, dims = hd, color = xl_col("#F2F4F6"))
  wb$add_border(sheet = sh, dims = hd, bottom_color = xl_col("#999999"),
                bottom_border = "thin", left_border = NULL, right_border = NULL,
                top_border = NULL, inner_hgrid = NULL, inner_vgrid = NULL)
  if (nrow_d > 0) {
    wb$add_cell_style(sheet = sh, dims = paste0("A", hdr + 1, ":", last, hdr + nrow_d),
                      vertical = "top")
    for (j in seq_len(nc)) {
      if (is.null(fmt) || is.na(fmt[j])) next
      cl <- xl_ref(j)
      wb$add_numfmt(sheet = sh, dims = paste0(cl, hdr + 1, ":", cl, hdr + nrow_d),
                    numfmt = fmt[j])
    }
  }
  ## 見出しを固定する。行数の多い表（症例別一覧は176行）で列が何かを見失わないため
  if (freeze) wb$freeze_pane(sheet = sh, first_active_row = hdr + 1)
  invisible(NULL)
}

## 文字の行列を data.frame にし、数値へ直せる列は数値にする。書式の並びを一緒に返す
xl_frame <- function(cols, rows) {
  nc <- length(cols)
  m <- do.call(rbind, lapply(rows, function(x) {
    length(x) <- nc                       # 行が短い表示型でも列数を揃える
    as.character(x)
  }))
  if (is.null(m)) m <- matrix(character(0), ncol = nc)
  m[is.na(m)] <- ""
  d <- as.data.frame(m, stringsAsFactors = FALSE)
  names(d) <- xl_uniq(cols)
  fmt <- rep(NA_character_, nc)
  for (j in seq_len(nc)) {
    k <- ap_xlsx_numcol(d[[j]])
    if (is.null(k)) next
    s <- trimws(d[[j]])
    d[[j]] <- suppressWarnings(as.numeric(ifelse(nzchar(s), s, NA)))
    fmt[j] <- k$fmt
  }
  list(d = d, fmt = fmt)
}

## ---------------------------------------------------------------------------------
## 表のシート。blocks は list(list(subtitle=, cols=, rows=, note=), ...)。
## 1つの宣言が表を複数生む表示型（治療相 × TKI区分で分ける有害事象の表）は
## 同じシートへ小見出しを付けて積む。HTML が1ファイルへ並べるのと同じ扱い。
## ---------------------------------------------------------------------------------
ap_xlsx_table <- function(wb, lblid, title, subtitle, blocks, tx) {
  sh <- ap_xlsx_sheet(lblid)
  wb$add_worksheet(sh, grid_lines = FALSE)
  r <- xl_head(wb, sh, title, subtitle, tx)
  ncol_max <- 1L
  first_hdr <- NA_integer_
  for (b in blocks) {
    if (nzchar(xl_nz(b$subtitle))) {
      wb$add_data(sheet = sh, x = xl_nz(b$subtitle), dims = paste0("A", r))
      wb$add_font(sheet = sh, dims = paste0("A", r), bold = "1")
      r <- r + 1L
    }
    f <- xl_frame(b$cols, b$rows)
    nc <- ncol(f$d)
    ncol_max <- max(ncol_max, nc)
    hdr <- r
    if (is.na(first_hdr)) first_hdr <- hdr
    wb$add_data(sheet = sh, x = f$d, dims = paste0("A", hdr), na.strings = "")
    ## 見出しの固定は先頭の表にだけ効かせる（2つ目以降で呼ぶと固定位置が下がる）
    xl_style_table(wb, sh, hdr, nrow(f$d), nc, f$fmt, freeze = (hdr == first_hdr))
    r <- hdr + nrow(f$d) + 1L
    if (nzchar(xl_nz(b$note))) {
      wb$add_data(sheet = sh, x = xl_nz(b$note), dims = paste0("A", r))
      wb$add_font(sheet = sh, dims = paste0("A", r), color = xl_col(AP_XL_GREY),
                  size = "9")
      r <- r + 1L
    }
    r <- r + 1L
  }
  wb$set_col_widths(sheet = sh, cols = seq_len(ncol_max), widths = "auto")
  invisible(NULL)
}

## ---------------------------------------------------------------------------------
## 生存時間曲線のシート。
##
## curves は群ごとの list(label=, time=, surv=, lcl=, ucl=, ncensor=)。すべての群の
## 時点を合わせた1本の時間の列に対して、群ごとに 生存確率・下限・上限・打ち切り の
## 4系列を置く。mschart は横軸に1列しか取らないため、時点を揃えてから書く。
##
## 階段の形にするため、各時点を2行に分ける。1行目がその時点の直前の値、2行目が
## その時点の値で、両者を結ぶと垂直の落ち込みになる。イベントの無い群はその時点で
## 2行が同じ値になるので、落ち込みが描かれない。
## ---------------------------------------------------------------------------------
ap_xlsx_km <- function(wb, lblid, title, subtitle, curves, atrisk, tx, xmax = 5) {
  sh <- ap_xlsx_sheet(lblid)
  wb$add_worksheet(sh, grid_lines = FALSE)
  r <- xl_head(wb, sh, title, subtitle, tx)

  ## 図の読み方。HTML の図は信頼区間を帯で塗るが Excel は破線2本なので文言が違う
  wb$add_data(sheet = sh, x = tx$note_figkm, dims = paste0("A", r))
  wb$add_font(sheet = sh, dims = paste0("A", r), color = xl_col(AP_XL_GREY), size = "9")
  chart_top <- r + 2L
  chart_bottom <- chart_top + 21L

  ## リスク集合数の表（チャートの機能ではないのでシート上の表として置く）
  ar <- chart_bottom + 2L
  wb$add_data(sheet = sh, x = tx$atrisk, dims = paste0("A", ar))
  wb$add_font(sheet = sh, dims = paste0("A", ar), bold = "1")
  arows <- lapply(seq_along(curves), function(g)
    c(if (nzchar(curves[[g]]$label)) curves[[g]]$label else tx$atrisk,
      format(atrisk$n[[g]], trim = TRUE)))
  af <- xl_frame(c(tx$xaxis, format(atrisk$times, trim = TRUE)), arows)
  wb$add_data(sheet = sh, x = af$d, dims = paste0("A", ar + 1), na.strings = "")
  xl_style_table(wb, sh, ar + 1, nrow(af$d), ncol(af$d), af$fmt, freeze = FALSE)

  ## 曲線のデータ。チャートが参照する範囲そのものなので、研究者が値を差し替えれば
  ## 図がその場で追随する
  dat <- xl_km_frame(curves, tx)
  dt <- ar + nrow(af$d) + 4L
  wb$add_data(sheet = sh, x = tx$curvedata, dims = paste0("A", dt))
  wb$add_font(sheet = sh, dims = paste0("A", dt), bold = "1")
  hdr <- dt + 1L
  ## 欠測は空セルにする。na.strings に "" を渡すと空文字列のセルになり、Excel は
  ## それを 0 と読む。打ち切りの系列が横軸に沿って 0% に並んだ（2026-08-29）
  wb$add_data(sheet = sh, x = dat, dims = paste0("A", hdr), na.strings = NULL)
  xl_style_table(wb, sh, hdr, nrow(dat), ncol(dat), NULL, freeze = FALSE)
  wb$add_numfmt(sheet = sh,
                dims = paste0("A", hdr + 1, ":", xl_ref(ncol(dat)), hdr + nrow(dat)),
                numfmt = "0.0000")
  wb$set_col_widths(sheet = sh, cols = seq_len(ncol(dat)), widths = "auto")

  ## チャート。ブック内のセル範囲を参照する（値を埋め込まない）
  rng <- paste0("A", hdr, ":", xl_ref(ncol(dat)), hdr + nrow(dat))
  wd <- openxlsx2::wb_data(wb, sheet = sh, dims = rng)
  sn <- names(dat)[-1]
  st <- xl_km_style(curves)
  ch <- mschart::ms_scatterchart(data = wd, x = names(dat)[1], y = sn)
  ## 引数名は style。scatterstyle という名前は無く、渡しても ... に落ちて黙って
  ## 無視される。既定は "marker" で、そのままだと系列の線が noFill になり
  ## 曲線が1本も描かれない（2026-08-29 に Excel の図を画像で見て判明）
  ch <- mschart::chart_settings(ch, style = "lineMarker")
  ch <- mschart::chart_data_symbol(ch, values = stats::setNames(st$symbol, sn))
  ch <- mschart::chart_data_line_style(ch, values = stats::setNames(st$line, sn))
  ch <- mschart::chart_data_stroke(ch, values = stats::setNames(st$color, sn))
  ch <- mschart::chart_data_fill(ch, values = stats::setNames(st$color, sn))
  ch <- mschart::chart_data_size(ch, values = stats::setNames(st$size, sn))
  ## 折れ線を滑らかにしない。階段の角が丸まると打ち切りの位置が読めなくなる
  ch <- mschart::chart_data_smooth(ch, values = stats::setNames(rep(0, length(sn)), sn))
  ## 目盛を1年ごとに固定する。major_unit を指定しないと 0.5 刻みになり、
  ## 整数の書式と組み合わさって 0・1・1・2・2 と重複した目盛に見える
  ch <- mschart::chart_ax_x(ch, limit_min = 0, limit_max = xmax, num_fmt = "0",
                            major_unit = 1)
  ch <- mschart::chart_ax_y(ch, limit_min = 0, limit_max = 1, num_fmt = "0%")
  ch <- mschart::chart_labels(ch, xlab = tx$xaxis, ylab = tx$yaxis)
  wb$add_mschart(sheet = sh, dims = paste0("A", chart_top, ":J", chart_bottom), graph = ch)
  invisible(NULL)
}

## 群ごとの曲線を1枚の表にする。列は 時間・（群ごとに）生存確率・下限・上限・打ち切り。
## 列の見出しがそのままチャートの凡例になるので、表示文言を呼び出し側から受け取る
xl_km_frame <- function(curves, tx) {
  tms <- sort(unique(unlist(lapply(curves, function(c) c$time))))
  tms <- tms[tms > 0]
  d <- data.frame(c(0, rep(tms, each = 2)), check.names = FALSE)
  names(d) <- tx$time
  ## 階段関数の値。t 以下で最後に記録された値を返す（記録が無ければ init）
  at <- function(tv, vv, t, init) {
    i <- sum(tv <= t + 1e-12)
    if (i == 0L) init else vv[i]
  }
  ## 信頼限界は生存確率が0に達すると欠測になる。直前の値を引き継ぐ（HTML の図と同じ扱い）
  ffill <- function(v, init) {
    if (!length(v)) return(v)
    if (is.na(v[1])) v[1] <- init
    for (i in seq_along(v)[-1]) if (is.na(v[i])) v[i] <- v[i - 1]
    v
  }
  for (g in seq_along(curves)) {
    c0 <- curves[[g]]
    step <- function(vv, init) {
      pre  <- vapply(seq_along(tms), function(j)
        at(c0$time, vv, if (j == 1L) -1 else tms[j - 1], init), 0)
      post <- vapply(tms, function(t) at(c0$time, vv, t, init), 0)
      c(init, as.vector(rbind(pre, post)))
    }
    sv <- step(c0$surv, 1)
    d[[xl_km_nm(tx$surv, c0$label)]] <- sv
    d[[xl_km_nm(tx$lcl,  c0$label)]] <- step(ffill(c0$lcl, 1), 1)
    d[[xl_km_nm(tx$ucl,  c0$label)]] <- step(ffill(c0$ucl, 1), 1)
    ## 打ち切りの目印は、打ち切りのあった時点の「その時点の値」の行にだけ置く
    hit <- match(round(c0$time[c0$ncensor > 0], 9), round(tms, 9))
    hit <- hit[!is.na(hit)]
    mk <- rep(NA_real_, nrow(d))
    if (length(hit)) mk[1 + 2 * hit] <- sv[1 + 2 * hit]
    d[[xl_km_nm(tx$cens, c0$label)]] <- mk
  }
  names(d) <- xl_uniq(names(d))
  d
}

## 系列の名前。群が1つ（層別しない図）なら群名を付けない
xl_km_nm <- function(base, label) if (nzchar(label)) paste0(base, "（", label, "）") else base

## 系列の見た目。曲線は実線で目印なし、信頼限界は同じ色の破線、打ち切りは線なしの目印
xl_km_style <- function(curves) {
  sym <- ln <- col <- character(0); sz <- numeric(0)
  for (g in seq_along(curves)) {
    cc <- AP_XL_COL[((g - 1) %% length(AP_XL_COL)) + 1]
    sym <- c(sym, "none", "none", "none", "plus")
    ln  <- c(ln, "solid", "dashed", "dashed", "none")
    col <- c(col, cc, cc, cc, cc)
    ## 打ち切りの目印は小さくする。大きいと点が連なって帯に見え、曲線が読めない
    sz  <- c(sz, 5, 5, 5, 4)
  }
  list(symbol = sym, line = ln, color = col, size = sz)
}

## ---------------------------------------------------------------------------------
## 目次を書いてブックを保存する。entries は list(lblid=, title=) の並びで、順序は
## 図表の宣言（tlf-index.csv の seq）のまま。章番号順に振ってあるので、通し読み HTML・
## トレーサビリティ索引・納品パッケージと並びが揃う
## ---------------------------------------------------------------------------------
ap_xlsx_finish <- function(wb, entries, path, tx) {
  sh <- tx$toc_sheet
  wb$add_data(sheet = sh, x = tx$toc_title, dims = "A1")
  wb$add_font(sheet = sh, dims = "A1", bold = "1", size = "14")
  hdr <- 3L
  d <- data.frame(a = vapply(entries, function(e) e$lblid, ""),
                  b = vapply(entries, function(e) e$title, ""),
                  stringsAsFactors = FALSE)
  names(d) <- c(tx$toc_no, tx$toc_name)
  wb$add_data(sheet = sh, x = d, dims = paste0("A", hdr), na.strings = "")
  xl_style_table(wb, sh, hdr, nrow(d), 2L)
  ## 表番号からシートへ飛ぶ。88件あるので、目次から直接開けないと使いものにならない
  for (i in seq_along(entries)) {
    wb$add_formula(sheet = sh, dims = paste0("A", hdr + i),
                   x = openxlsx2::create_hyperlink(
                     sheet = ap_xlsx_sheet(entries[[i]]$lblid), row = 1, col = 1,
                     text = entries[[i]]$lblid))
    wb$add_font(sheet = sh, dims = paste0("A", hdr + i), color = xl_col("#0563C1"),
                underline = "single")
  }
  wb$set_col_widths(sheet = sh, cols = 1:2, widths = c(14, 90))
  wb$save(path, overwrite = TRUE)
  invisible(path)
}
