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
## 描画で作れなかったものの控え。図・SVG・Excel の失敗を警告に変えて進むと、外部から見た
## 終了コードは 0 のままで、成果物が欠けたまま次の段階へ進む（C3-125）。ここに貯めて、
## 呼び出し側（<試験ID>_TLF.R）が最後に非0で終えられるようにする。
## 続ける形は残す。1件で止めると、残りに他の欠陥があっても1回の実行で1件しか分からない。
## ---------------------------------------------------------------------------------
.tlf_miss <- new.env(parent = emptyenv())
.tlf_miss$msg <- character(0)

tlf_miss <- function(fmt, ...) {
  m <- sprintf(fmt, ...)
  .tlf_miss$msg <- c(.tlf_miss$msg, m)
  ap_note("WARN %s", m)
  invisible(NULL)
}

tlf_miss_list <- function() .tlf_miss$msg

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

## 図ごとに違う文言を引く。<key>_<図表ID> が登録されていればそれを、無ければ <key> を使う。
## 生存曲線の横軸がこれにあたる。起算日が図によって違う（EFS・OS は登録日、RFS は LFS 到達日）
## のに、既定の「登録からの期間」を全図で使っていた（C2-064。2026-08-30 に図を見て判明）
fx_for <- function(key, lblid) {
  v <- lab("fixed", paste0(key, "_", lblid))
  if (nzchar(v)) v else fx(key)
}
lvl <- function(id) {                        # 水準・背景表の行項目の表示名
  if (is.na(id) || !nzchar(id)) return("")
  for (k in c("level", "bgitem")) {
    v <- lab(k, id)
    if (nzchar(v)) return(v)
  }
  id
}
## 表ごとに違う行ラベルを引く。<水準>_<図表ID> が登録されていればそれを、無ければ
## 水準そのものの表示名を使う（固定文言の fx_for と同じ考え方）。同じ水準でも表に
## よって説明を変えたいときの口で、表5.4.3 の MTF・MolPD・MolR がこれにあたる。
## 5.4.3 では全観察期間の状態とイベントを表す行だが、5.4.3.1 では評価時点ごとの列に
## なるため、水準そのものの名前を変えるわけにいかない（C2-039。2026-08-30）
lvl_for <- function(id, lblid) {
  if (is.na(id) || !nzchar(id)) return("")
  v <- lab("level", paste0(id, "_", lblid))
  if (nzchar(v)) v else lvl(id)
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

## 事前規定の水準集合。正本は docs/metadata/level-sets.csv（C3-002。2026-09-03）。宣言表の
## levels 列と表示型の既定値が同じ集合を書き写していたのをやめ、集合IDで指す形にした。
## ここで使うのは表示の順（display_order。空の集合は impl_order）で、ARD 側が使う実装の
## 列挙順とは別に持つ。2つを1つにすると図表の行順が変わる。CSV は1度だけ読む。
LVSETS <- read_csv(ap_spec("level-sets.csv"), col_types = cols(.default = "c"),
                   progress = FALSE, na = character())
## 集合IDから表示順の水準を引く。集合が無ければ止める。既定の水準へ黙って落とすと、
## 宣言が指した集合とは違う列が出たままになる
lvsetd <- function(id) {
  h <- LVSETS[LVSETS$set_id == id, ]
  if (!nrow(h)) ap_stop("水準集合が docs/metadata/level-sets.csv に無い: %s", id)
  io <- suppressWarnings(as.integer(h$impl_order))
  dp <- suppressWarnings(as.integer(h$display_order))
  dp[is.na(dp)] <- io[is.na(dp)]
  h$level[ordc(dp, io)]
}
## 宣言の levels 列を水準の並びへ直す。LS_ で始まる値は水準集合の識別子なので展開し、
## それ以外（%tab_crs のコース列のような部分集合の並び）は | で分ける
lvsplit <- function(v) {
  if (length(v) != 1 || is.na(v) || !nzchar(v)) return(character(0))
  if (startsWith(v, "LS_")) return(lvsetd(v))
  strsplit(v, "|", fixed = TRUE)[[1]]
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
f1 <- function(x) ifelse(is.na(x), "", formatC(sasround(x, 1), format = "f", digits = 1, big.mark = ","))
f0 <- function(x) ifelse(is.na(x), "", formatC(sasround(x, 0), format = "f", digits = 0, big.mark = ","))

## 例数と括弧の中身を組む。中身が空のときは括弧ごと落とす。「60 ()」のように空の括弧が
## 残ると、割合が0なのか算出していないのかが読み手に分からない（C2-050）。SAS 側は
## tlf_ops.sas の同じ箇所で ifc() を使って同じことをする
np <- function(n, p) ifelse(is.na(p) | p == "", n, paste0(n, " (", p, ")"))
## セルを作った ARD の行を指す鍵。解析ID・行の水準・列の群・統計量・セルに出た統計量の
## 並び・鍵の読み方を | でつなぐ。空の要素があってもよい（列が統計量でない表では stat が
## 空になる）。C2-068
##
## 前の4つは ARD の1行を一意に指す結合キーで、突合と索引が使う形を変えない。後ろの2つは
## その1行だけではセルの値を説明できないときに、読み手が代表を単一の由来と読み違えない
## ようにする（C3-103・C3-104）。
##   stats … セルに実際に出た統計量の名前を + でつないだもの。1つしか出ないセルでは st と
##           同じ。「19/20」なら n+N、「7.0 - 21.4」なら lcl+ucl のように、解析ID・水準・群を
##           固定したうえで由来の ARD 行をすべて数え上げられる形にする
##   kind  … 前の4つと stats で由来を数え上げられるなら空。数え上げられないときだけ印を置く。
##           repr は同じ値を持つ複数行のうちバイト順で最小のものを代表に選んだ場合（分母 N）、
##           part は解析・部分集合が違う行も値に入っていて鍵では名指しできない場合
ky <- function(aid = "", vl = "", g1 = "", st = "", stats = st, kind = "")
  paste(nz(aid), nz(vl), nz(g1), nz(st),
        paste(nz(stats), collapse = "+"), nz(kind), sep = "|")
## セルに実際に出た統計量の名前を並べる。引数の名前が ARD の stat_name、値が書式化した
## あとの文字列で、空のものは表示から落ちているので鍵にも入れない（割合の無いセルが
## 「60 ()」にならないのと同じ扱い）。C3-103
shown <- function(...) { v <- c(...); names(v)[nzchar(v)] }
## 鍵に入れる代表値を1つ選ぶ。分母（N）のように複数の水準にまたがって同じ値を持つ
## 統計量は、セルの値がどの ARD 行から来たかを1行に決められない。バイト順で最小の
## ものを代表にすると、両系統で同じ行を指す（SAS の min() も UTF-8 セッションでは
## バイト順で比べる）。C2-068。代表を選んだセルは ky() の kind に repr を置き、
## 台帳の読み手が単一の由来と読み違えないようにする（C3-104）
minc <- function(v) {
  v <- v[!is.na(v)]
  if (!length(v)) "" else sort(unique(v), method = "radix")[1]
}
## 割合ではない併記は角括弧に入れる。丸括弧は割合の印なので、同じ形にすると
## 読み手が区別できない（C2-053。SAS の %tab_prop_tp も同じ形にしてある）
nb <- function(n, x) ifelse(is.na(x) | x == "", n, paste0(n, " [", x, "]"))
## 文字の並びを SAS の proc sort へ合わせる。SAS は UTF-8 セッションで動かすので
## （scripts/runcommon.py）UTF-8 のバイト列で並び、R の method="radix" も同じ
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
## 名前は SAS 側の ARD の列名（ard.ard）に合わせる。宣言の filter 列は両系統が同じ文字列を
## 読むので、片方にしか無い名前を作らない。ANALYSID は1つの図表グループの一部だけを描く
## ための軸で、表 5.4.2.4（Out-5.4.2 の連続量）が使う
COLMAP <- c(GROUP1L = "group1_level", GROUP1 = "group1", SUBSET = "data_subset",
            VARIABLE = "variable", VARLEVEL = "variable_level",
            ANALSET = "analysis_set", CONTEXT = "context",
            ANALYSID = "analysis_id")
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
IX <- "../traceability.html"  # output/tlf/r-<言語>/ から見たトレーサビリティ索引
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
  ## 群別の件数を列として足した表は、その列の出どころも指す（2026-09-12。表 5.4.8 の
  ## 因果関係の列が An-5.4.8-04 由来なのに案内が An-5.4.8-01 だけを指していた）
  extra <- if (!is.null(r$grpcnt_id) && !is.na(r$grpcnt_id) && nzchar(r$grpcnt_id))
             r$grpcnt_id else character(0)
  if (!is.na(r$analysis_id) && nzchar(r$analysis_id))
    return(unique(c(r$analysis_id, extra)))
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
  ## 宣言の grpcnt_id が指す解析の群ごとの件数（n）を列として右へ足す。列の並びは groups
  ## （| 区切りの群の識別子）、見出しは labels（| 区切りの kind=fixed のキー）で、群の名前も
  ## 見出しの文言も実装は持たない。表 5.4.8 が An-5.4.8-04（事象別の件数を試験治療との
  ## 因果関係で分けたもの）をこの口で足す。SAS 側は %tab_prop の grpcnt_id= が同じ宣言を読む。
  ## 引くのは件数だけにする。割合と信頼区間はその群の中での値で、行の列とは分母が違う
  gid <- nz(r$grpcnt_id)
  gs <- if (nzchar(gid)) strsplit(nz(r$groups), "\\|")[[1]] else character(0)
  gl <- if (nzchar(gid)) strsplit(nz(r$labels), "\\|")[[1]] else character(0)
  dg <- if (nzchar(gid))
          ARD[ARD$analysis_id == gid & ARD$context == "categorical" &
              ARD$stat_name == "n", ] else NULL
  g <- split(d, d$variable_level)
  rows <- lapply(names(g), function(k) {
    x <- g[[k]]
    n <- stat_of(x, "n"); N <- stat_of(x, "N"); p <- stat_of(x, "p")
    lo <- stat_of(x, "lcl"); hi <- stat_of(x, "ucl")
    ## 群は宣言ではなく ARD の行が持つ（1解析1群だが GROUP1L は空とは限らない。
    ## An-4.4.11-CHR-major は SUBTYPE='MAJOR' を持つ）。空を入れると鍵が ARD の
    ## 行に当たらない（C2-068 の照合で判明）
    g1 <- nz(x$group1_level[1])
    ## 件数と分母、下限と上限は1つのセルに2つの統計量を並べたもの。鍵の統計量は先に出る
    ## 方を残したまま、セルに出た統計量を stats で数え上げる（C3-103）
    nc <- f0(n); Nc <- f0(N); pc <- f1(p); lc <- f1(lo); uc <- f1(hi)
    ## 結果値の無い組合せはセルを空にし、鍵も空にする（ARD に無い行を指さない。
    ## d_tab_prop_grp・d_tab_aegr と同じ扱いで、SAS の %tab_prop も同じ）
    gv <- vapply(gs, function(gr) {
      x2 <- dg[dg$variable_level == k & dg$group1_level == gr, ]
      if (!nrow(x2)) "" else f0(stat_of(x2, "n"))
    }, "", USE.NAMES = FALSE)
    gk <- vapply(seq_along(gs), function(i)
      if (nzchar(gv[i])) ky(gid, k, gs[i], "n") else "", "")
    list(ord = lvord(k), sort = -ifelse(is.na(n), -Inf, n), id = k,
         cells = c(lvl(k), catx("/", nc, Nc), pc, catx(" - ", lc, uc), gv),
         keys = c("", ky(r$analysis_id, k, g1, "n", shown(n = nc, N = Nc)),
                  ky(r$analysis_id, k, g1, "p"),
                  ky(r$analysis_id, k, g1, "lcl", shown(lcl = lc, ucl = uc)), gk))
  })
  ## 並びは 宣言された定義順（label-catalog の order。lvord() は番号を持たない水準へ
  ## 9999 を返すので、番号を持つ水準が先に来る）→ 件数の多い順 → 識別子。定義順を先に
  ## 見るのは、判定の水準のように読み手が決まった並びを期待する表があるためで、番号を
  ## 持つ水準は件数に関わらずその番号順に出る（C2-049。2026-09-10）。同点を識別子で割る
  ## のは、表示名で並べると日英で行が入れ替わるためである（C2-213）。SAS 側は
  ## tlf_ops.sas の %tab_prop が同じ3つの鍵（_lvord・descending _n・_vl）で並べる
  rows <- rows[ordc(vapply(rows, function(x) x$ord, 0),
                    vapply(rows, function(x) x$sort, 0),
                    vapply(rows, function(x) x$id, ""))]
  ## 分母の単位が表によって違う。表 5.4.8・5.4.8.1 は重篤な有害事象の件数を分母に
  ## するので、列名も件数と書く（C2-057。fx_for が <key>_<図表ID> を先に引く）
  list(cols = c(lab("rowlbl", r$lblid), fx_for("nden", r$lblid), fx("prop"), fx("ci95"),
                vapply(gl, fx, "", USE.NAMES = FALSE)),
       rows = lapply(rows, function(x) x$cells),
       keys = lapply(rows, function(x) x$keys), note = build_note("", r))
}

d_tab_prop_grp <- function(r) {
  d <- ARD[ARD$analysis_id == r$analysis_id & ARD$context == "categorical", ]
  if (!nrow(d)) return(NULL)
  gs <- strsplit(r$groups, "\\|")[[1]]
  ls <- lvsplit(r$levels)
  cell <- function(gr, lv) {
    x <- d[d$group1_level == gr & d$variable_level == lv, ]
    if (!nrow(x)) return("")
    np(f0(stat_of(x, "n")), f1(stat_of(x, "p")))
  }
  head_row <- c(fx("nsubj"), vapply(gs, function(gr) {
    x <- d[d$group1_level == gr, ]
    if (!nrow(x)) "" else f0(stat_of(x, "N"))
  }, ""))
  ## 対象症例数の行は、その群のすべての水準が持つ N の最大を出す。どの水準の行から
  ## 来たかは決まらないので、水準はバイト順で最小のものを代表にする（C2-068）。
  ## 代表であることは kind に repr を置いて台帳へ残す（C3-104）
  nkey <- function(gr) {
    v <- d[d$group1_level == gr & d$stat_name == "N" & !is.na(d$stat_num), ]
    if (!nrow(v)) return("")
    ky(r$analysis_id, minc(v$variable_level), gr, "N", kind = "repr")
  }
  ## 結果値の無い組合せはセルが空になる。鍵も空にする（ARD に無い行を指さない）。
  ## 「n (p)」の形は2つの統計量を並べたものなので、出た方を stats で数え上げる（C3-103）
  cellk <- function(gr, lv) {
    x <- d[d$group1_level == gr & d$variable_level == lv, ]
    if (!nrow(x)) return("")
    ky(r$analysis_id, lv, gr, "n",
       shown(n = f0(stat_of(x, "n")), p = f1(stat_of(x, "p"))))
  }
  rows <- c(list(head_row),
            lapply(ls, function(lv) c(lvl(lv), vapply(gs, cell, "", lv = lv))))
  keys <- c(list(c("", vapply(gs, nkey, ""))),
            lapply(ls, function(lv)
              c("", vapply(gs, cellk, "", lv = lv))))
  list(cols = c(lab("rowlbl", r$lblid), vapply(gs, lvl, "")), rows = rows, keys = keys,
       note = build_note("", r))
}

## 時点の並びは SAS と同じく VARLEVEL から数字を取り出して昇順にする（1年・2年・3年…）
timept_order <- function(v) suppressWarnings(as.numeric(gsub("[^0-9.]", "", v)))

## 注記の文言は印（&_n・&_dec など）を含む。例: "N=&_n, events=&_ev, censored=&_cn"。
## 印の正本は label-catalog.csv の kind=notemark で、印の名前（key）と値の出どころ
## （value_source）だけを持つ。印の一覧をここへ写さないので、印を1つ足せば宣言を読む
## 両系統へ同時に届く（C3-202。SAS 系は %_nvset・%_fosub が同じ宣言を読む）。
## 値の出どころは2種類。ard:<統計量名> はその図表の解析の ARD 行、pe:<名前> は主要評価
## 項目の判定が作る値（prim_values の petp・peest…、SAS のマクロ変数 _petp・_peest…）
note_marks <- function() {
  m <- LC[LC$kind == "notemark", ]
  if (!nrow(m)) return(character(0))
  v <- setNames(nz(m$value_source), paste0("&", nz(m$key)))
  ## 長い印から置き換える。&_n を先に処理すると &_nc が "87c" になるので、順序は
  ## 名前の長さから機械的に決める（並びを人が列挙しない。C3-203）
  v[order(nchar(names(v)), decreasing = TRUE)]
}

## 注記の印を実際の値へ置き換える。1つでも置き換えられない印があれば注記ごと落とす。
## 印が残ったまま印字すると、読み手には意味の無い文字列が見える（SAS の %_fosub も同じ
## 契約で、共通注記・図表別脚注のどちらも、どの表示型でもこの関数を通る。C3-204）。
## 落ちた注記は成果物からは見えない。脚注の無い普通の表と区別が付かないので、図表番号・
## 注記のキー・落ちた印とその出どころ・理由の記号を tlf_miss へ残す。控えは実行の最後に
## 数えられ、STRICT なら非0で終えるため、注記の消えた図表は納品へ進まない（C3-206。
## SAS 系は %_fosub が同じ4項目を行頭 ERROR で出し、run-all-sas.py の ERROR 数が
## 同じ働きをする）
subst_note <- function(txt, d, aid = "", lblid = "", key = "") {
  if (!nzchar(txt) || !grepl("&_", txt, fixed = TRUE)) return(txt)
  mk <- note_marks()
  pe <- NULL                                   # 判定は要るときに一度だけ組む
  pe_done <- FALSE
  for (k in names(mk)) {
    if (!grepl(k, txt, fixed = TRUE)) next
    src <- mk[[k]]
    val <- NA_character_
    if (startsWith(src, "ard:")) {
      x <- stat_of(d, sub("^ard:", "", src))
      if (is.finite(x)) val <- f0(x)
    } else if (startsWith(src, "pe:")) {
      if (!pe_done) { pe <- prim_values(d, aid); pe_done <- TRUE }
      nm <- paste0("pe", sub("^pe:", "", src))
      if (!is.null(pe) && nm %in% names(pe)) val <- pe[[nm]]
    }
    if (is.na(val) || !nzchar(val)) {
      tlf_miss("NOTE-VAL: [%s] 注記 %s を落とす。印 %s（%s）の値を作れない: %s",
               lblid, key, k, src, txt)
      return("")
    }
    txt <- gsub(k, val, txt, fixed = TRUE)
  }
  ## 宣言に無い印が残っていれば、正本が実装の知らない印を使っている。落として記録する
  ## （検査 scripts/check-tlf-index.py が正本の側で先に捕まえる）
  if (grepl("&_", txt, fixed = TRUE)) {
    tlf_miss("NOTE-DECL: [%s] 注記 %s を落とす。宣言の無い印が残る: %s", lblid, key, txt)
    return("")
  }
  txt
}

## 注記は二層で、共通注記（kind=fixed の note_ で始まるキー。表示型ごとの読み方）の
## うしろに、図表別脚注（kind=footnote。キーは図表番号）を置く。層ごとに置き換えるので、
## 片方が組めなくてももう片方は残る。全表示型がこの関数だけを通る（C3-204・C3-216・C3-217）
build_note <- function(fixed_key, r) {
  aid <- nz(r$analysis_id)
  ## 解析IDを持たない宣言（図表グループで描く表示型）では ARD から印を引けない。
  ## 空の解析IDが ARD の行に当たらないよう、行の無い枠を渡す
  d <- if (nzchar(aid)) ARD[ARD$analysis_id == aid, ] else ARD[0, ]
  parts <- c(if (nzchar(fixed_key)) fx(fixed_key) else "", lab("footnote", r$lblid))
  ## 層を引いたカタログのキーを文言と組にして持つ。落ちた層がどれかは、文言が消えた
  ## あとでは分からない（C3-206）
  keys <- c(paste0("fixed/", fixed_key), paste0("footnote/", r$lblid))
  parts <- vapply(seq_along(parts),
                  function(i) subst_note(parts[i], d, aid, r$lblid, keys[i]), "")
  paste(parts[nzchar(parts)], collapse = " ")
}

## 正本の ci_method が名乗る方式のうち、この実装が計算しているもの。時点の信頼区間は
## survfit の conf.type="log-log"（SAS 系は proc lifetest の conftype=loglog）で作った、
## Greenwood の分散に log(-log(S)) を当てた区間である。正本がこれ以外を宣言したら、ARD が
## 持つ下限は宣言どおりの量ではないので止める（C3-213）
PRIM_CI_METHOD <- "loglog"

## 主要評価項目の判定が作る値を返す。判定の規則の正本は primary-endpoint.csv で、閾値と
## 時点のほかに、信頼区間の方式（ci_method）・比較の式（comparison）・推定統計量の名前
## （estimate_operation）も同じ表が持つ。統計量の名前も比較の向きもここへ写さず読む
## （C3-213。2026-08-31 まで lcl・surv・> をコードが持っており、正本を変えても判定の規則へ
## 届かなかった）。宣言の解析が正本の指す解析でないときは NULL を返し、呼び出し側が
## 注記を落とす（他の表がこの脚注を持っても空振りするだけ）。それ以外の不足は理由の記号で
## 扱いを分け、受入基準そのものが読めない PE-CSV・PE-CMP・PE-CI は止め、結果値が足りない
## PE-VAL は脚注を落として続ける（2026-09-03 の運用5。C3-207・C3-213・C3-214。同じ記号と
## 同じ扱いを SAS の %_pemake も持つ）。
## 返す名前は印の宣言の pe:<名前> に pe を冠したもので、SAS のマクロ変数 _pe<名前> と揃う
prim_values <- function(d, aid) {
  ## 受入基準が読めないときは止める。握り潰すと、閾値と判定を持つ脚注が図表から
  ## 黙って消えたまま刷り上がる（2026-08-31 に置き場を移したときに塞いだ）
  pe <- read_csv(ap_spec("primary-endpoint.csv"),
                 col_types = cols(.default = "c"), progress = FALSE,
                 na = character())
  if (!all(c("item", "value") %in% names(pe)))
    ap_stop("PE-CSV: primary-endpoint.csv が item・value の列を持たない")
  v <- setNames(nz(pe$value), nz(pe$item))
  ## 判定の規則を組むのに要る項目。1つでも欠けていれば正本として成立していない
  need <- c("analysis_id", "timepoint", "threshold",
            "ci_method", "comparison", "estimate_operation")
  val <- setNames(nz(v[need]), need)
  if (any(!nzchar(val)))
    ap_stop("PE-CSV: primary-endpoint.csv に %s が無い",
            paste(need[!nzchar(val)], collapse = "・"))
  ## 判定を組めない表ではこの脚注を出さない。印が残ったまま印字すると、読み手に
  ## 意味の無い文字列が見える（SAS の %_nvset も、%_pemake が判定を組んだ解析と
  ## 描いている解析が違えば印の値を空にする）
  if (!nzchar(aid) || val[["analysis_id"]] != aid) return(NULL)
  if (val[["ci_method"]] != PRIM_CI_METHOD)
    ap_stop("PE-CI: 信頼区間の方式が実装と違う: 正本 %s / 実装 %s",
            val[["ci_method"]], PRIM_CI_METHOD)
  ## 比較の式は「<ARD の統計量> <演算子> <正本の項目>」の形だけを解釈する。読めない式を
  ## 既定の向きで黙って判定すると、正本を変えても判定が変わらない（SAS の %_pemake も
  ## 同じ形だけを受ける）
  cmp <- regmatches(val[["comparison"]],
                    regexec("^\\s*([A-Za-z0-9_]+)\\s*(>=|<=|>|<)\\s*([A-Za-z0-9_]+)\\s*$",
                            val[["comparison"]]))[[1]]
  if (length(cmp) != 4L)
    ap_stop("PE-CMP: comparison を解釈できない: %s", val[["comparison"]])
  if (!cmp[4] %in% names(v))
    ap_stop("PE-CMP: comparison の右辺 %s が正本の項目に無い: %s", cmp[4], val[["comparison"]])
  ops <- list(">" = `>`, ">=" = `>=`, "<" = `<`, "<=" = `<=`)
  tp <- val[["timepoint"]]
  thr <- suppressWarnings(as.numeric(nz(v[[cmp[4]]])))
  x <- d[d$variable_level == tp, ]
  cv <- stat_of(x, cmp[2])                        # 比較の左辺。現行の正本では下限
  est <- stat_of(x, val[["estimate_operation"]])  # 印字する推定値。現行の正本では生存割合
  ## 推定値・比較の左辺・閾値のどれかが数値として取れないときは、脚注を落として続ける。
  ## 欠けたまま組むと空欄の混じった脚注や、閾値を数値と解せないままの判定が刷り上がるので
  ## 出さないが（C3-214）、これは表 5.4.1 の結果値が ARD に無いという1表の話であり、原因を
  ## 調べるには他の表も含めて1回走り切ったほうが分かる（2026-09-03 の運用5。C3-214 の対応と
  ## して 2026-08-31 に入れた ap_stop を、受入基準そのものが読めない PE-CSV・PE-CMP・PE-CI と
  ## 分けた。ap_stop は tlf_miss を経ずに stop() を投げるので、駆動の tryCatch が表そのものを
  ## 作れなかったものとして捨て、脚注1つのために表 5.4.1 が丸ごと出なくなっていた）。
  ## 落としたことは NOTE-VAL と同じ形で tlf_miss へ残し、実行の最後に STRICT が非0で終える
  ## ため、脚注の消えた図表は納品へ進まない（C3-206）。記号は PE-VAL のまま置く。NOTE-VAL へ
  ## 寄せると、印の値を作れない他の原因と区別が付かない。NULL を返したあとは呼び出し側
  ## （subst_note）が注記を落とし、その層のキーを NOTE-VAL として続けて残す。ARD の段階も
  ## 同じ条件を WARNING PE-VAL で通すので（<試験ID>_ARD.R）、段階による扱いの差は
  ## これで無くなる。
  ## 時点の表示名は lvl() が引けなければ識別子を返すので、ここで空にはならない
  if (!is.finite(est) || !is.finite(cv) || !is.finite(thr)) {
    tlf_miss("PE-VAL: 主要評価項目の脚注を落とす。結果値が足りない: 解析 %s 時点 %s（%s=%s / %s=%s / %s=%s）",
             aid, tp, val[["estimate_operation"]], est, cmp[2], cv, cmp[4], nz(v[[cmp[4]]]))
    return(NULL)
  }
  ## 向きは正本の comparison が持つ。PRT 9.4 の「上回る」は厳密な > で、ちょうど等しい
  ## ときは超えていない
  dec <- if (ops[[cmp[3]]](cv, thr)) "MET" else "NOT MET"
  c(petp = lvl(tp), peest = f1(100 * est), pelcl = f1(100 * cv),
    pethr = f1(100 * thr), pedec = dec)
}

## 指定時点（Y1〜Y5）の行だけを取る。除外ではなく採用で書くのは、Mth-KM が指定時点の
## ほかに生存曲線の全イベント時点（T<年>）と中央値（MEDIAN）と例数（水準なし）を持つため。
## 除外の列挙で書いていたときに曲線の行が表へ入り、表 5.4.1 が5行のところ89行出ていた
## （2026-08-29 に検出。records/ars-migration-20260829.md 第3段が「時点で絞る形に変える」としていた
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
  ## 信頼区間のセルは下限と上限を1つにまとめたもの。鍵の統計量は先に出る下限のままにし、
  ## セルに出た統計量を stats で数え上げる（C3-103）
  keys <- lapply(names(g)[ord], function(k) {
    x <- g[[k]]
    g1 <- nz(x$group1_level[1])
    c("", ky(r$analysis_id, k, g1, est), ky(r$analysis_id, k, g1, "se"),
      ky(r$analysis_id, k, g1, "lcl",
         shown(lcl = f1(100 * stat_of(x, "lcl")), ucl = f1(100 * stat_of(x, "ucl")))))
  })
  list(cols = c(fx("timepoint"), esthdr, fx("se"), fx("ci95")), rows = rows,
       keys = keys, note = build_note(note, r))
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
  lvseq <- lvsplit(r$levels)
  seqof <- function(id) { i <- match(nz(id), lvseq); if (is.na(i)) 99999L else i }
  key <- paste(d$analysis_id, d$variable, d$group1_level, d$variable_level, sep = "\u0001")
  g <- split(d, key)
  rows <- lapply(names(g), function(k) {
    x <- g[[k]]
    ctx <- max(x$context)
    ## 行項目の表示名も図表ごとに差し替えられる（lvl_for）。プレフェーズの
    ## REDUCEFL は減量ではなく漸増の有無を表すので、表 5.3.1 だけ別の行ラベルを
    ## 当てる（SAS 側は %tab_bg が _lvcat へ <キー>_<図表ID> で二重 join する）
    item <- paste(vapply(icols, function(cc) lvl_for(x[[cc]][1], r$lblid), ""),
                  collapse = " / ")
    ## 行項目の順序番号。連続量の行は水準を持たないので、これが無いと並びが定まらない（SAS の %tab_bg の ITEMORD と同じ）
    iord <- sprintf("%04d", lvord(x[[icols[1]]][1]))
    if (ctx == "continuous") {
      med <- f1(stat_of(x, "median")); mn <- f1(stat_of(x, "min"))
      mx <- f1(stat_of(x, "max")); me <- f1(stat_of(x, "mean"))
      sd <- f1(stat_of(x, "sd")); nm <- stat_of(x, "nmiss")
      q1 <- f1(stat_of(x, "q1")); q3 <- f1(stat_of(x, "q3"))
      ## 値の無い統計量はラベルごと落とす。n=1 では SD が定義できず「… 平均 630.0 SD」と
      ## ラベルだけが残っていた（C2-217。2026-08-30 の目視確認）。四分位点は下限と上限を
      ## 1つのラベルで並べるので、片方でも欠ければ「Q1-Q3 2.0-」にならないよう両方の
      ## 有無で見る。SAS 側は tlf_ops.sas の %tab_bg が同じ組み立てをする
      val <- paste0(med, " [", mn, ", ", mx, "]")
      qq <- if (nzchar(q1) && nzchar(q3)) paste0(q1, "-", q3) else ""
      if (nzchar(qq)) val <- paste0(val, " ", fx("q1q3"), " ", qq)
      if (nzchar(me)) val <- paste0(val, " ", fx("mean"), " ", me)
      if (nzchar(sd)) val <- paste0(val, " SD ", sd)
      nmc <- if (!is.na(nm) && nm > 0) f0(nm) else ""
      if (nzchar(nmc)) val <- paste0(trimws(val), " ", fx("missing"), nmc)
      ## 解析例数は宣言の show_n=Y を持つ表だけがセルの先頭に出す（表5.4.7.2・5.4.7.5）。
      ## 行を増やさずコース別の分母を示すための口である。欠測数は出さない。両表とも欠測は
      ## 全組0だが、値の無い症例は入力の行として存在しないため、0 と書くと「欠測が無い」
      ## という別のことを述べてしまう（C2-045。SAS 側は %tab_bg の show_n= が同じ）
      nc <- if (nz(r$show_n) == "Y") f0(stat_of(x, "n")) else ""
      if (nzchar(nc)) val <- paste0("n=", nc, " ", trimws(val))
      list(sort = c(x$analysis_id[1], iord, "99999", "9999", "99999", ""),
           cells = c(item, "", val),
           ## 連続量の要約は例数・中央値・最小・最大・四分位点・平均・SD・欠測を1つの
           ## セルに並べたもの。鍵の統計量は先に出る中央値のままにし、出た統計量を
           ## セルに出る順に数え上げる（C3-103）
           keys = c("", "", ky(x$analysis_id[1], x$variable_level[1],
                               x$group1_level[1], "median",
                               shown(n = nc, median = med, min = mn, max = mx,
                                     q1 = qq, q3 = qq,
                                     mean = me, sd = sd, nmiss = nmc))))
    } else {
      list(sort = c(x$analysis_id[1], iord,
                    sprintf("%05d", seqof(x$variable_level[1])),
                    sprintf("%04d", lvord(x$variable_level[1])),
                    sprintf("%05d", lvvisit(x$variable_level[1])),
                    nz(x$variable_level[1])),
           cells = c(item, lvl(x$variable_level[1]),
                     np(f0(stat_of(x, "n")), f1(stat_of(x, "p")))),
           keys = c("", "", ky(x$analysis_id[1], x$variable_level[1],
                               x$group1_level[1], "n",
                               shown(n = f0(stat_of(x, "n")),
                                     p = f1(stat_of(x, "p"))))))
    }
  })
  ## 鍵は 解析ID → 行項目の順序番号 → 宣言の順 → 順序番号 → 来院番号 → 識別子。
  ## 行項目の順序番号は SAS の %tab_bg の ITEMORD と同じ位置に置く（2026-09-11）
  o <- ordc(vapply(rows, function(x) x$sort[1], ""),
            vapply(rows, function(x) x$sort[2], ""),
            vapply(rows, function(x) x$sort[3], ""),
            vapply(rows, function(x) x$sort[4], ""),
            vapply(rows, function(x) x$sort[5], ""),
            vapply(rows, function(x) x$sort[6], ""))
  note <- build_note("note_bg", r)
  list(cols = c(fx(if (is.na(r$item_label) || !nzchar(r$item_label)) "item" else r$item_label),
                fx("categ"), fx("summary")),
       rows = lapply(rows[o], function(x) x$cells),
       keys = lapply(rows[o], function(x) x$keys), note = note)
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
  ## グレードの区切りは宣言の levels= が持つ。空なら CTCAE の4区分（LS_AEGR4）を既定に
  ## する。区切り方は表示の選択なので表示型に直書きせず、集合の正本である
  ## docs/metadata/level-sets.csv から引く（C3-002。2026-09-03。SAS の %tab_aegr も同じ）
  glv <- lvsplit(r$levels)
  if (!length(glv)) glv <- lvsetd("LS_AEGR4")
  key <- paste(d$group1_level, d$data_subset, d$variable, sep = "\u0001")
  g <- split(d, key)
  gr <- function(x, lv) {
    v <- x$stat_num[x$stat_name == "n" & x$variable_level == lv]
    if (!length(v)) "" else f0(max(v, na.rm = TRUE))
  }
  rows <- lapply(names(g), function(k) {
    x <- g[[k]]
    ## 分母は全グレードの行が同じ N を持つので、どの行から来たかが1つに決まらない。
    ## 水準はバイト順で最小のものを代表にする（SAS の %tab_aegr も同じ。C2-068）。
    ## 代表であることは kind に repr を置いて台帳へ残す（C3-104）
    aid <- minc(x$analysis_id)
    nv <- x$variable_level[x$stat_name == "N" & !is.na(x$stat_num)]
    nk <- if (!length(nv)) "" else
            ky(aid, minc(nv), x$group1_level[1], "N", kind = "repr")
    ## 結果値の無いグレードはセルが空になる。鍵も空にする（ARD に無い行を指さない）
    gk <- function(lv) {
      if (!length(x$stat_num[x$stat_name == "n" & x$variable_level == lv])) ""
      else ky(aid, lv, x$group1_level[1], "n")
    }
    list(sort = c(x$group1_level[1], x$data_subset[1], x$variable[1]),
         cells = c(x$variable[1], f0(stat_of(x, "N")),
                   vapply(glv, function(g) gr(x, g), "", USE.NAMES = FALSE)),
         keys = c("", nk, vapply(glv, gk, "", USE.NAMES = FALSE)))
  })
  o <- ordc(vapply(rows, function(x) x$sort[1], ""),
            vapply(rows, function(x) x$sort[2], ""),
            vapply(rows, function(x) x$sort[3], ""))
  ## 列見出しは水準の表示名を引く。宣言の levels= は識別子で書くので、そのまま出すと
  ## NOTRECORDED のような内部の名前が表に出る（C2-056）
  list(cols = c(fx("ae"), fx("denom"), vapply(glv, lvl, "", USE.NAMES = FALSE)),
       rows = lapply(rows[o], function(x) x$cells),
       keys = lapply(rows[o], function(x) x$keys), note = build_note("", r))
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
## 信頼区間は log-log 変換（Greenwood の分散に log(-log(S)) を当てる）にする。SAS の
## PROC LIFETEST は CONFTYPE=LOGLOG、ARD の %ard_km・ard_km も同じ。survfit の既定は
## conf.type="log" で、同じデータでも信頼限界が違う。表と図で別の方式の区間を並べない
## ため、ここで揃える（2026-08-29 に揃え、2026-09-12 に線形形式から改めた）。この
## 当てはめは Excel のチャートの元にもなるので、Excel のシートに載る値も ARD と同じになる
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
  survival::survfit(fm, data = x, conf.type = "log-log")
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
km_paint <- function(fit, lblid = "") {
  ng <- max(1, length(fit$strata))
  cols <- seq_len(ng)
  op <- graphics::par(mar = c(4.2, 4.2, 0.6, 0.6))
  # 枠と軸だけ先に描き、信頼区間の帯を敷いてから曲線を重ねる。帯を後から描くと
  # 曲線と打ち切りの目印が帯の下に隠れる
  plot(fit, xlab = fx_for("xaxis_km", lblid), ylab = fx("yaxis_km"), ylim = c(0, 1),
       xlim = c(0, 5), conf.int = FALSE, mark.time = FALSE, col = NA)
  km_band(fit, cols, xmax = 5)
  graphics::lines(fit, conf.int = FALSE, mark.time = TRUE, col = cols, lwd = 2)
  if (!is.null(fit$strata)) {
    ## 凡例は survfit の層の名前（HSCTFL=N）から値を取り出したもので、そのままでは
    ## 識別子が図に出る。カタログに <変数>_<水準> があればそれを、無ければ水準そのものを
    ## 引く（C2-064。2026-08-30 に図を見て判明）
    nm <- names(fit$strata)
    gv <- sub("=.*$", "", nm[1])
    lv <- sub("^[^=]*=", "", nm)
    lg <- vapply(lv, function(v) {
      a <- lab("level", paste0(gv, "_", v))
      if (nzchar(a)) return(a)
      b <- lab("level", v)
      if (nzchar(b)) b else v
    }, "", USE.NAMES = FALSE)
    graphics::legend("bottomleft", legend = lg,
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
  km_paint(fit, r$lblid)
  grDevices::dev.off()
  on.exit()
  svg <- paste(readLines(tmp, warn = FALSE), collapse = "\n")
  unlink(tmp)
  svg_localize(sub("^<\\?xml[^>]*\\?>\\s*(<!DOCTYPE[^>]*>)?\\s*", "", svg), r$lblid)
}

## 図を独立したベクター形式のファイルとしても出す（C2-112）。論文へ図を出すとき、投稿先は
## ベクター形式（EPS・PDF・SVG）か高解像度のラスタを求めるが、HTML へ埋めた SVG は
## 単体で取り出せない。書くのは HTML へ埋めるのと同じ文字列で、図が2種類にならないようにする。
## 埋め込みでは省ける XML 宣言だけを先頭へ足す（xmlns は cairo が <svg> へ書いている）。
## 文字列は cairo が書いたバイトのままなので、端末の既定符号化を挟まないよう writeBin で出す。
write_fig_svg <- function(dir, lblid, svg) {
  if (is.null(svg) || !nzchar(svg)) return(invisible(FALSE))
  ap_mkdir(dir)
  s <- if (grepl("<svg[^>]*xmlns=", svg)) svg else
    sub("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', svg, fixed = TRUE)
  con <- file(file.path(dir, paste0(lblid, ".svg")), open = "wb")
  on.exit(close(con))
  writeBin(charToRaw(paste0('<?xml version="1.0" encoding="UTF-8"?>\n', s, "\n")), con)
  invisible(TRUE)
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
  ## 群ごとの対象症例数は先頭の行ブロックの解析が持つ（下の nkey・rows と同じ）
  a1 <- spec[[1]]$aid
  nden <- vapply(gs, function(gr) {
    x <- d[d$group1_level == gr & d$analysis_id == a1, ]
    if (!nrow(x)) NA_real_ else stat_of(x, "N")
  }, 0)
  names(nden) <- gs
  ## 分母が表の対象症例数と違う行は、セルに分母を出して「n/N (p)」にする。分母の
  ## 違う解析を同じ列に並べる表があるため（表 5.4.12 は死因の内訳が死亡例10、
  ## 治療関連死が FAS 全体88）。表 4.5.2.3 の「2/21」と形式が揃う（2026-09-12）
  cell <- function(gr, aid, lv) {
    x <- d[d$analysis_id == aid & d$group1_level == gr & d$variable_level == lv, ]
    if (!nrow(x)) return("")
    n <- f0(stat_of(x, "n"))
    den <- stat_of(x, "N")
    if (nzchar(n) && !is.na(den) && !is.na(nden[[gr]]) && den != nden[[gr]])
      n <- paste0(n, "/", f0(den))
    np(n, f1(stat_of(x, "p")))
  }
  ## 「n (p)」の形は2つの統計量を並べたものなので、出た方を stats で数え上げる（C3-103）
  cellk <- function(gr, aid, lv) {
    x <- d[d$analysis_id == aid & d$group1_level == gr & d$variable_level == lv, ]
    if (!nrow(x)) return("")
    ky(aid, lv, gr, "n", shown(n = f0(stat_of(x, "n")), p = f1(stat_of(x, "p"))))
  }
  ## 対象症例数の行は、先頭の行ブロックの解析が持つ N を出す。表の集団を表す行なので、
  ## 分母の違う解析を同じ列に並べる表では別の分母を拾ってはいけない（表 5.4.12 は
  ## 死因の内訳が死亡例10、治療関連死が FAS 全体88。群の全行から最大を採っていた頃は
  ## 88 が出ていた。2026-09-12）。どの水準の行から来たかは決まらないので、水準は
  ## バイト順で最小のものを代表にする（SAS の %tab_prop_grp_multi も同じ。C2-068）。
  ## 代表であることは kind に repr を置いて台帳へ残す（C3-104）
  nkey <- function(gr) {
    v <- d[d$group1_level == gr & d$analysis_id == a1 & d$stat_name == "N" &
           !is.na(d$stat_num), ]
    if (!nrow(v)) return("")
    ky(a1, minc(v$variable_level), gr, "N", kind = "repr")
  }
  ## 先頭に対象症例数の行を置く（SAS の _gp2 の第1行と同じ）
  rows <- list(c(fx("nsubj"), vapply(gs, function(gr) {
    x <- d[d$group1_level == gr & d$analysis_id == a1, ]
    if (!nrow(x)) "" else f0(stat_of(x, "N"))
  }, "")))
  keys <- list(c("", vapply(gs, nkey, "")))
  for (s in spec) {
    for (lv in s$lvs) {
      rows[[length(rows) + 1L]] <- c(lvl_for(lv, r$lblid),
                                     vapply(gs, cell, "", aid = s$aid, lv = lv))
      keys[[length(keys) + 1L]] <- c("", vapply(gs, cellk, "", aid = s$aid, lv = lv))
    }
  }
  list(cols = c(lab("rowlbl", r$lblid), vapply(gs, lvl, "")), rows = rows,
       keys = keys, note = build_note("", r))
}

## 評価時点を行に持つ表（SAS の %tab_prop_tp）。行の並びと表示名は docs/metadata/mr-timepoint.csv。
## SAS 側も %_tdmr_load が同じ CSV を読む（宣言はデータセット名を持たない）。
## 宣言の subset= で渡した部分集合の解析がある水準は、割合ではなくその件数をカッコに入れる。
d_tab_prop_tp <- function(r) {
  d <- ARD[ARD$output_id == r$output_id & ARD$context == "categorical", ]
  if (!nrow(d)) return(NULL)
  ls <- lvsplit(r$levels)
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
    ## 部分集合の件数は角括弧に入れる。丸括弧のままだと割合と外見上まったく区別が
    ## 付かず、同じ表の中で「例数（割合）」と「例数（別の例数）」が混ざる（C2-053）
    if (nrow(y)) nb(f0(stat_of(x, "n")), f0(stat_of(y, "n")))
    else         np(f0(stat_of(x, "n")), f1(stat_of(x, "p")))
  }
  ## 鍵は括弧の中身（部分集合の件数）ではなく先に出る件数（main の n）を指す。
  ## 解析IDは宣言が持たないので、当たった ARD の行から取る（C2-068）。
  ## 角括弧に部分集合の件数が入るセルは、その件数が別の解析（別の data_subset）の行から
  ## 来るため鍵の4つでは名指しできない。kind に part を置いて、鍵が値の一部しか説明して
  ## いないことを台帳へ残す。丸括弧の割合は同じ行の p なので stats で数え上げる（C3-103）
  cellk <- function(lv, gr) {
    x <- main[main$group1_level == gr & main$variable_level == lv, ]
    if (!nrow(x)) return("")
    y <- nsd[nsd$group1_level == gr & nsd$variable_level == lv, ]
    if (nrow(y)) ky(x$analysis_id[1], lv, gr, "n", kind = "part")
    else ky(x$analysis_id[1], lv, gr, "n",
            shown(n = f0(stat_of(x, "n")), p = f1(stat_of(x, "p"))))
  }
  ## 行の表示名は mr-timepoint.csv の label。日英の表示を与えたい時点だけ label-catalog に
  ## kind=level で <群の識別子>_<図表ID> を登録し、そちらを先に引く（lvl_for と同じ形）。
  ## SAP の列見出しが内部識別子のままだった adjuvant_cmr・molpd・molr・relapse が該当する
  ## （C2-217。SAS の %tab_prop_tp も同じ引き当てをする）
  tplab <- function(i) {
    v <- lab("level", paste0(tp$glabel[i], "_", r$lblid))
    if (nzchar(v)) v else tp$label[i]
  }
  rows <- lapply(seq_len(nrow(tp)), function(i)
    c(tplab(i), vapply(ls, cell, "", gr = tp$glabel[i])))
  keys <- lapply(seq_len(nrow(tp)), function(i)
    c("", vapply(ls, cellk, "", gr = tp$glabel[i])))
  list(cols = c(lab("rowlbl", r$lblid), vapply(ls, lvl, "")), rows = rows,
       keys = keys, note = build_note("", r))
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
  ## 1行が ARD の1行なので、鍵はその行の値をそのまま指す（C2-068）
  keys <- lapply(seq_len(nrow(d)), function(i)
    c("", ky(d$analysis_id[i], d$variable_level[i], d$group1_level[i], "n")))
  list(cols = c(fx("categ"), fx("ncnt")), rows = rows, keys = keys,
       note = build_note("", r))
}

## コース別の実施状況表（SAS の %tab_crs）。SAP 5.3.4〜5.3.6 の図表案は1節=1表で、
## コースを行ブロックとして積む。コースの並びは ARD が持たないので宣言の levels= が
## 決める（M1-3・M10-12・M4-6 の文字順では SAP の並びにならない）。
## 薬剤・区分の列に GROUP1L を出すのは GROUP1 が変数名を持つときだけで、TKI区分の
## 例数（GROUP1 が空で GROUP1L='TKIGROUP'）は項目の列で表せる。
## 行の並びは コース順 → 解析ID → 水準の識別子。水準は表示名ではなく識別子で並べるので
## 日本語版と英語版で行の並びが変わらない。
d_tab_crs <- function(r) {
  cs <- lvsplit(r$levels)
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
    ## 要約の列だけが ARD 由来。コース・薬剤区分・項目・区分は行ラベルなので鍵を持たない。
    ## 統計量は連続量が median、それ以外が n（セルの先に出る方。C2-068）。
    ## 要約のセルは統計量を複数並べるので、出たものを sts に数え上げる（C3-103）
    st <- if (ctx == "continuous") "median" else "n"
    sts <- st
    if (ctx == "count") {
      cell <- c(lvl(nz(x$variable_level[1])), "", f0(stat_of(x, "n")))
    } else if (ctx == "continuous") {
      med <- f1(stat_of(x, "median")); mn <- f1(stat_of(x, "min"))
      mx  <- f1(stat_of(x, "max"));    me <- f1(stat_of(x, "mean"))
      sd  <- f1(stat_of(x, "sd"));     nm <- stat_of(x, "nmiss")
      q1  <- f1(stat_of(x, "q1"));     q3 <- f1(stat_of(x, "q3"))
      ## 値の無い統計量はラベルごと落とす（d_tab_bg と同じ。C2-217）。四分位点は下限と
      ## 上限を1つのラベルで並べるので、片方でも欠ければラベルごと落とす
      val <- paste0(med, " [", mn, ", ", mx, "]")
      qq <- if (nzchar(q1) && nzchar(q3)) paste0(q1, "-", q3) else ""
      if (nzchar(qq)) val <- paste0(val, " ", fx("q1q3"), " ", qq)
      if (nzchar(me)) val <- paste0(val, " ", fx("mean"), " ", me)
      if (nzchar(sd)) val <- paste0(val, " SD ", sd)
      nmc <- if (!is.na(nm) && nm > 0) f0(nm) else ""
      if (nzchar(nmc)) val <- paste0(trimws(val), " ", fx("missing"), nmc)
      sts <- shown(median = med, min = mn, max = mx, q1 = qq, q3 = qq,
                   mean = me, sd = sd, nmiss = nmc)
      cell <- c(lvl(nz(x$variable[1])), "", val)
    } else {
      nc <- f0(stat_of(x, "n")); pc <- f1(stat_of(x, "p"))
      sts <- shown(n = nc, p = pc)
      cell <- c(lvl(nz(x$variable[1])), lvl(nz(x$variable_level[1])), np(nc, pc))
    }
    list(co = co[j][1], aid = x$analysis_id[1], lv = nz(x$variable_level[1]),
         cells = c(lvl(nz(x$data_subset[1])), grp, cell),
         keys = c("", "", "", "",
                  ky(x$analysis_id[1], x$variable_level[1],
                     x$group1_level[1], st, sts)))
  })
  o <- ordc(vapply(rows, function(z) z$co, 0),
            vapply(rows, function(z) z$aid, ""),
            vapply(rows, function(z) z$lv, ""))
  note <- build_note("note_bg", r)
  list(cols = c(fx("course"), fx("drug_grp"), fx("item"), fx("categ"), fx("summary")),
       rows = lapply(rows[o], function(z) unname(z$cells)),
       keys = lapply(rows[o], function(z) unname(z$keys)), note = note)
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
  ## 症例単位の一覧は結果値の集計ではなく ADaM から直接組む。どのセルも ARD の行を
  ## 指さないので鍵を返さない（セル台帳の4列は空のままになる。C2-068）
  list(cols = vapply(ks, fx, "", USE.NAMES = FALSE), rows = rows,
       note = build_note("", r))
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
## SAS 系の ARD から描くのは突合用のセル台帳を作るためで、図表そのものは要らない。
## 出力先は ARD の系統を含まないので、書くと納品する図表（R 系の ARD から描いたもの）が
## SAS 系由来のもので上書きされる。通し実行（run-release.py）の段階2は、--ard=r の後に
## --ard=sas を回す。実際に納品物の出所が入れ替わっていた（2026-08-31。C3-115）。
## 順序で避ける設計にしていたが、順序を間違えると黙って壊れるので書かない形にする
WRITE_OUT <- ARDSRC != "sas"
## 前回の実行が残した図表 HTML を消す。宣言から外れた図表のファイルが残ると
## PI パッケージの相互リンクが片側だけ生きた状態になり、check-pi-package が落ちる
## 消すのは図表ファイル（T_… / F_…）だけ。同じディレクトリに通し読み HTML も置く
if (WRITE_OUT && dir.exists(TLFDIR))
  unlink(list.files(TLFDIR, pattern = "^[TF]_.*[.]html$", full.names = TRUE))
ap_mkdir(TLFDIR)
## 図を独立したベクター形式のファイルとして出す先（C2-112）。図表 HTML と混ぜず下の階層へ
## 分けるのは、ここが読み物ではなく持ち出す素材だからで、索引・検査が見る直下の顔ぶれも変えない。
## 図表 HTML と同じく、宣言から外れた図の残りが混ざらないよう毎回消してから書く
FIGDIR <- file.path(TLFDIR, "figures")
if (WRITE_OUT) {
  if (dir.exists(FIGDIR))
    unlink(list.files(FIGDIR, pattern = "^F_.*[.]svg$", full.names = TRUE))
  ap_archive_old(TLFDIR, paste0("^", TRIAL, "_TLF_.*[.](html|rtf|xlsx)$"), LANG)
}
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
      tlf_miss("[%s] 当てはめができない: %s", r$lblid, conditionMessage(e)); NULL })
    svg <- if (is.null(fit)) NULL else tryCatch(d_fig_km(r, fit), error = function(e) {
      tlf_miss("[%s] 図を描けない: %s", r$lblid, conditionMessage(e)); NULL })
    if (is.null(svg)) { n_skip <- n_skip + 1L; next }
    ## 図の注記も表と同じ二層にする。共通注記（note_figkm。打ち切りの目印と信頼区間の帯
    ## という読み方）のうしろに、図別の脚注（kind=footnote のキー F_…）を置く。以前は
    ## R 系が共通注記だけ、SAS 系が図別脚注だけを出しており、層が系統間で逆転していた
    ## （C3-216。SAS 系は %fig_km が %tlfnote と %tlffoot を並べる）
    fnote <- build_note("note_figkm", r)
    body <- paste0(svg, if (nzchar(fnote))
                          paste0("\n<p class=\"note\">", esc_html(fnote), "</p>") else "")
    n_fig <- n_fig + 1L
    ## 同じ SVG を独立したファイルとしても書く。埋め込む側の文字列は変えない
    if (WRITE_OUT) tryCatch(write_fig_svg(FIGDIR, r$lblid, svg),
             error = function(e)
               tlf_miss("[%s] 図の SVG を書けない: %s", r$lblid, conditionMessage(e)))
    if (XLSX) {
      ## Excel は画像を貼らず、ブック内のデータ範囲を参照するチャートにする。SVG と同じ
      ## 当てはめから作るので、図と Excel で曲線も信頼限界も同じ値になる
      tryCatch(ap_xlsx_km(wb, r$lblid, ttl_sub(lab("title", r$lblid)),
                             lab("subtitle", r$lblid), km_curves(fit), km_atrisk(fit), TX),
               error = function(e)
                 tlf_miss("[%s] Excel の図を作れない: %s", r$lblid, conditionMessage(e)))
    }
  } else {
    ## 表示型は名前で引く。登録表を持たないので、汎用と試験固有のどちらに
    ## 定義してあっても駆動は同じ（SAS の %tlf_run が %<表示型>() を呼ぶのと同じ）
    fn <- get0(paste0("d_", r$display), mode = "function")
    if (is.null(fn)) {
      tlf_miss("[%s] 表示型 %s は未実装", r$lblid, r$display)
      n_skip <- n_skip + 1L; next
    }
    t <- tryCatch(fn(r), error = function(e) {
      tlf_miss("[%s] 表を作れない: %s", r$lblid, conditionMessage(e)); NULL })
    ## 1つの宣言が表を複数生む場合（tab_aegr の治療相 × TKI区分）は multi で返る。表番号は
    ## 1つなので HTML は1ファイルに並べ、台帳の row_seq は表をまたぐ通し番号にする（SAS の
    ## %_tlfcells も同じ lblid の2度目以降は続きから振る）
    tabs <- if (!is.null(t) && !is.null(t$multi)) t$multi else
            if (!is.null(t) && length(t$rows)) list(list(tab = t, sfx = "")) else list()
    if (!length(tabs)) {
      tlf_miss("[%s] 結果値がない。表を作らない", r$lblid)
      n_skip <- n_skip + 1L; next
    }
    body <- ""
    roff <- 0L
    xlb <- list()                    # Excel のシートへ積む表（HTML と同じ並び・同じ値）
    for (tt in tabs) {
      tb <- tt$tab
      ## ph は ADaM の APHASE の値（C1-1・MAINTENANCE）、tk は部分集団の識別子
      ## （SS-TKIGRP-DA・SS-TKIGRP-PN）なので、表題には表示名を引いて出す。カタログに
      ## 無ければ lvl() が識別子を返す（SAS の %tab_aegr も同じ）。治療相は集約区分の
      ## C1-x・C2-x と個別コースの C1-1 などが別の行としてカタログに並ぶので、キーの
      ## 等値で引く lvl() をそのまま使う（前方一致にすると取り違える）
      ti <- ttl_sub(lab("title", r$lblid),
                    if (is.null(tt$ph)) NULL else lvl(tt$ph),
                    if (is.null(tt$tk)) NULL else lvl(tt$tk))
      ## 注記の印（&_n・&_dec など）が置き換わらないまま印字されると、読み手には
      ## 意味の無い文字列が見える。表 5.4.1 の判定の脚注が実際にこうなっていた
      ## （2026-08-30 に目視で検出。表示型が脚注を subst_note へ通していなかった）。
      ## 置き換えられない印を持つ注記は build_note が落とすので、ここまで残っていたら
      ## 表示型が build_note を通していない。落とさずに止める（C3-204）
      if (grepl("&_", tb$note, fixed = TRUE))
        ap_stop(sprintf("%s の注記が置き換えを通っていない（build_note を経由すること）: %s",
                        r$lblid, tb$note))
      body <- paste0(body,
                     if (length(tabs) > 1L) paste0("<h3>", esc_html(ti), "</h3>\n") else "",
                     html_table(tb),
                     if (nzchar(tb$note)) paste0("\n<p class=\"note\">",
                                                 esc_html(tb$note), "</p>") else "", "\n")
      n_tab <- n_tab + 1L
      xlb[[length(xlb) + 1L]] <- list(subtitle = if (length(tabs) > 1L) ti else "",
                                      cols = tb$cols, rows = tb$rows, note = tb$note)
      ## セル台帳（SAS系との突合に使う）。1行が1セル。
      ## セルを作った ARD の行を指す4つ（解析ID・行の水準・列の群・統計量）を併せて持つ。
      ## 表番号までしか辿れないと、1つの表番号に多くの解析がぶら下がる表（5.4.7.3 は
      ## 18ブロック756解析）で、どのセルがどの解析かを読み手が特定できない（C2-068）。
      ## さらに cell_stats（セルに出た統計量の並び）と key_kind（鍵の読み方）を持つ。
      ## 複数の ARD 行から作ったセルを1行の由来と読み違えないためで、意味は ky() の頭書き
      ## （C3-103・C3-104）。表示型が tb$keys を返さないとき（文献値の表や図）は空のままにする
      for (ri in seq_along(tb$rows)) {
        rw <- tb$rows[[ri]]
        kk <- if (!is.null(tb$keys) && length(tb$keys) >= ri) tb$keys[[ri]] else character(0)
        for (ci in seq_along(rw)) {
          k <- if (length(kk) >= ci) kk[ci] else ""
          ## 区切りを6つ足してから割る。strsplit は末尾の空要素を落とすので、最後の要素が
          ## 空でも6つ揃わせるために鍵の要素数と同じ数を足す
          part <- strsplit(paste0(k, "||||||"), "|", fixed = TRUE)[[1]]
          cells[[length(cells) + 1L]] <- data.frame(
            lblid = r$lblid, display = r$display, row_seq = roff + ri, row_key = rw[1],
            col_seq = ci, col_label = tb$cols[ci], value = rw[ci],
            analysis_id = part[1], variable_level = part[2],
            group1_level = part[3], stat_name = part[4],
            cell_stats = part[5], key_kind = part[6],
            stringsAsFactors = FALSE)
        }
      }
      roff <- roff + length(tb$rows)
    }
    if (XLSX) {
      tryCatch(ap_xlsx_table(wb, r$lblid, ttl_sub(lab("title", r$lblid)),
                                lab("subtitle", r$lblid), xlb, TX),
               error = function(e)
                 tlf_miss("[%s] Excel の表を作れない: %s", r$lblid, conditionMessage(e)))
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
  if (WRITE_OUT)
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
if (WRITE_OUT)
  writeLines(html_page(whole_ttl, whole_html),
             file.path(TLFDIR, paste0(base, ".html")))
## Excel は通し読み HTML と同じ名前で同じディレクトリへ置く。日付を名前に持つので、
## 直下には最新の1組だけを残し、以前の版は 旧版/ へ退避してある
if (WRITE_OUT && XLSX) {
  TX$toc_title <- whole_ttl
  xf <- file.path(TLFDIR, paste0(base, ".xlsx"))
  ok <- tryCatch({ ap_xlsx_finish(wb, xl_entries, xf, TX); TRUE },
                 error = function(e) {
                   tlf_miss("[%s] Excel を保存できない: %s", LANG, conditionMessage(e))
                   FALSE })
  if (ok) ap_note("[%s] Excel: %s（%d シート）", LANG, xf, length(xl_entries))
}
cellsdf <- if (length(cells)) bind_rows(cells) else
  data.frame(lblid = character(), display = character(), row_seq = integer(),
             row_key = character(), col_seq = integer(), col_label = character(),
             value = character(), analysis_id = character(),
             variable_level = character(), group1_level = character(),
             stat_name = character(), cell_stats = character(),
             key_kind = character())
## 台帳の名前で「どの ARD から描いたか」を分ける。突合の相手を間違えないため。
##   tlf_cells_r_<言語>.csv     R系の描画 × R系の ARD（PI へ渡す系統そのもの）
##   tlf_cells_rsas_<言語>.csv  R系の描画 × SAS系の ARD（描画だけを SAS と比べるとき）
cf <- file.path(P$compare, paste0(if (ARDSRC == "sas") "tlf_cells_rsas_" else "tlf_cells_r_",
                               LANG, ".csv"))
write_csv(cellsdf, cf, na = "")

ap_note("[%s] 表 %d / 図 %d / 作らなかった宣言 %d", LANG, n_tab, n_fig, n_skip)
if (WRITE_OUT) {
  ap_note("[%s] 通し読み HTML: %s", LANG, file.path(TLFDIR, paste0(base, ".html")))
  ap_note("[%s] 図表ごとの HTML: %s（%d ファイル）", LANG, TLFDIR,
             length(list.files(TLFDIR, pattern = "^[TF]_.*[.]html$")))
  ap_note("[%s] 図の SVG: %s（%d ファイル）", LANG, FIGDIR,
             length(list.files(FIGDIR, pattern = "^F_.*[.]svg$")))
} else {
  ap_note("[%s] SAS 系の ARD から描いたので、図表そのものは書かずセル台帳だけを出す",
             LANG)
}
ap_note("[%s] セル台帳: %s（%d セル）", LANG, cf, nrow(cellsdf))
}
