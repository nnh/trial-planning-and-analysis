## ---------------------------------------------------------------------------------
## program name : build-define-html.R
## description  : define.xml を CDISC 標準の XSL（define2-0-0.xsl）で HTML へ変換する。
##                ブラウザで define.xml を直接開いても XSL は効くが、配布用に静的な
##                HTML も置く。
## usage        : Rscript scripts/build-define-html.R              # ADaM と SDTM の両方
##                Rscript scripts/build-define-html.R --layer=adam # ADaM だけ
##                Rscript scripts/build-define-html.R --layer=sdtm # SDTM だけ
## input        : Box datasets/define/<層>/define.xml と同 define2-0-0.xsl
## output       : Box datasets/define/<層>/define.html
## comment      : 変換を持つのはこのスクリプトだけにする。2026-09-05 まで、SDTM の
##                define.html は run-sdtm-validation が同じ処理を自前で書いて作っており、
##                このスクリプトは 2026-08-25 のフォルダ整理で取り残された
##                input/ads・input/sdtm を見ていたため毎回「define.xml が無いので飛ばす」
##                で終わっていた。同じ生成を2箇所が持つと、片方だけが直った状態に
##                気づけない（ADaM の define.html は 2026-08-20 の define.xml より
##                古いまま納品パッケージへ入っていた）。
##
##                実装系統は R である。2026-09-05 に PowerShell（.NET の
##                XslCompiledTransform）から移した。XSLT 1.0 の変換器が Python の
##                標準ライブラリに無く、Python は生成の経路を標準ライブラリだけで
##                動かしているのに対し、R は renv.lock がパッケージの版を固定して
##                renv::restore() で再現する仕組みを既に持つためである。役割としても、
##                機械が読む define.xml を作るのが Python（update-define-xml.py・
##                build-adam-define.py）、人が読む HTML にするのが R という分担になる。
##                判断の経緯は pipeline/analysis-pipeline-plan.md
##                「実行できる形を Python と R に限る」。
##
##                終了コード 0 対象を全て作れた / 1 どれかを作れなかった
## ---------------------------------------------------------------------------------

.here <- (function() {
  a <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", a[grep("^--file=", a)])
  if (length(f)) return(dirname(f[1]))
  "scripts"
})()
source(file.path(.here, "..", "program", "r", "ap_common.R"))

.args <- commandArgs(trailingOnly = TRUE)
argv <- function(name, default) {
  h <- grep(paste0("^--", name, "="), .args, value = TRUE)
  if (length(h)) sub(paste0("^--", name, "="), "", h[1]) else default
}
layer <- argv("layer", "all")
if (!layer %in% c("all", "adam", "sdtm")) {
  ap_stop("[define.html] --layer は all・adam・sdtm のいずれか（指定: %s）", layer)
}

## define.xml の在処。SDTM は update-define-xml.py、ADaM は build-adam-define.py が
## ここへ書く。define は試験に1組で実装系統を持たないので、系統別の datasets/sas・
## datasets/r ではなく datasets/define/<層> に置く（2026-09-05、段E。
## docs/reporting/traceability-design.md「define の置き場」）。
base <- file.path(ap_root(), "datasets", "define")
targets <- if (layer == "all") c("adam", "sdtm") else layer

ng <- 0
for (t in targets) {
  dir <- file.path(base, t)
  xml <- file.path(dir, "define.xml")
  xsl <- file.path(dir, "define2-0-0.xsl")
  html <- file.path(dir, "define.html")
  ## 「無いので飛ばす」で終わると、作れていないことが成功と区別できない。止める。
  if (!file.exists(xml)) {
    cat(sprintf("%s : define.xml がありません: %s\n", t, xml)); ng <- ng + 1; next
  }
  if (!file.exists(xsl)) {
    cat(sprintf("%s : define2-0-0.xsl がありません: %s\n", t, xsl)); ng <- ng + 1; next
  }

  ## xsl:output は method="html" と doctype-system を持つ。write_html は HTML の作法で
  ## 直列化するので DOCTYPE が付き、meta・br のような空要素も自己終了させない
  ## （write_xml に通すと XML の書き方になり、DOCTYPE も落ちる）。
  out <- xslt::xml_xslt(xml2::read_xml(xml), xml2::read_xml(xsl))
  xml2::write_html(out, html)

  ## define.xml より古い HTML が残っていないことを、作った直後に確かめられるようにする
  cat(sprintf("%s : define.html を作った（%s バイト。元 define.xml %s）\n", t,
              format(file.info(html)$size, big.mark = ","),
              format(file.info(xml)$mtime, "%Y-%m-%d %H:%M")))
}

if (ng) quit(status = 1)
