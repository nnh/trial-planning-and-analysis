#!/usr/bin/env python3
"""機械可読な宣言と、統計解析計画書との対応を検査する。

固定前に決め切った事項は、統計解析計画書の本文と機械可読な宣言の2か所に置かれる。
文書の構造検査（audit_sap_structure.py）は本文しか見ず、実装の検査は宣言しか見ない。
その間に落ちるのが、宣言がそろっていない・宣言に「未定」が残っている・宣言どうしの
識別子が食い違う・宣言が根拠として挙げる節が統計解析計画書に無い、という型である。
分母を変えて宣言を旧版に残しても、どちらの検査にも掛からない。

    python audit_declarations.py --metadata <docs/metadata> \
        --acceptance <docs/validation/acceptance> [--sap <統計解析計画書>]

終了コード

    0  error の指摘なし
    1  error の指摘あり。区間1の出口条件を満たさない
    2  検査が走らなかった（入力が無い等）。件数を0と読まない

規則

    D01  必須の宣言が無い                            error
    D02  宣言に未定が残っている                      error
    D03  図表の宣言の表番号が表示文言のカタログに無い error
    D04  受入基準の表番号が図表の宣言に無い          error
    D05  受入基準が指す集団の識別子が宣言に無い      error
    D06  図表の宣言が指す群・水準の識別子が宣言に無い warning
    D07  根拠として挙げた節が統計解析計画書に無い    error

文書の内容が正しいかは判定しない。識別子の対応と、根拠の節が実在するかだけを見る。
"""

import argparse
import csv
import os
import re
import sys

SEVERITIES = ("info", "warning", "error")

# 区間1の出口でそろっている宣言。置き場ごとに分ける
NEED_METADATA = ("tlf-index.csv", "label-catalog.csv", "analysis-grouping.csv",
                 "analysis-purpose.csv", "variable-map.csv")
NEED_ACCEPTANCE = ("analysis-set-condition.csv", "primary-endpoint.csv",
                   "display-contract.csv")

# 未定を表す書き方。決まっていないことを宣言に残したまま固定すると、実装は
# その文字列を値として読む
UNDECIDED = ("未定", "未確定", "要確認", "TBD", "tbd", "???", "FIXME", "検討中")

# 根拠の節番号の書き方。1.2.3 のような数字の連なりを拾う
RE_SECTION = re.compile(r"\d+(?:\.\d+)+")


class Finding:
    def __init__(self, rule, severity, where, message):
        self.rule = rule
        self.severity = severity
        self.where = where
        self.message = message


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def col(rows, name):
    return {(r.get(name) or "").strip() for r in rows if (r.get(name) or "").strip()}


def split_ids(value):
    """区切り文字の順序が意味を持つ列から、識別子だけを取り出す。"""
    return [x for x in re.split(r"[;,|/\s]+", value or "") if x]


def audit(meta_dir, acc_dir, sap_path):
    f = []
    tables = {}

    for d, names in ((meta_dir, NEED_METADATA), (acc_dir, NEED_ACCEPTANCE)):
        for n in names:
            p = os.path.join(d, n)
            if not os.path.isfile(p):
                f.append(Finding("D01", "error", n, "宣言が無い: %s" % p))
                continue
            tables[n] = read_csv(p)

    # D02 未定
    for n, rows in tables.items():
        for i, r in enumerate(rows, start=2):
            for k, v in r.items():
                if v and any(u in str(v) for u in UNDECIDED):
                    f.append(Finding("D02", "error", "%s %d行目" % (n, i),
                                     "%s に未定が残っている: %s" % (k, v)))

    idx = tables.get("tlf-index.csv")
    cat = tables.get("label-catalog.csv")
    dc = tables.get("display-contract.csv")
    asc = tables.get("analysis-set-condition.csv")
    grp = tables.get("analysis-grouping.csv")
    pe = tables.get("primary-endpoint.csv")

    # D03 図表の表番号が表示文言のカタログにあるか
    if idx is not None and cat is not None:
        keys = col(cat, "key")
        for r in idx:
            lbl = (r.get("lblid") or "").strip()
            if lbl and lbl not in keys:
                f.append(Finding("D03", "error", "tlf-index.csv",
                                 "表番号 %s が label-catalog.csv に無い" % lbl))

    # D04 受入基準の表番号が図表の宣言にあるか
    if idx is not None and dc is not None:
        lbls = col(idx, "lblid")
        for r in dc:
            lbl = (r.get("lblid") or "").strip()
            if lbl and lbl not in lbls:
                f.append(Finding("D04", "error", "display-contract.csv",
                                 "表番号 %s が tlf-index.csv に無い" % lbl))

    # D05 受入基準が指す集団の識別子
    if dc is not None and asc is not None:
        ids = col(asc, "id")
        for r in dc:
            for key in ("analysis_set", "data_subset"):
                v = (r.get(key) or "").strip()
                if v and v not in ids:
                    f.append(Finding("D05", "error", "display-contract.csv",
                                     "%s の %s が analysis-set-condition.csv に無い"
                                     % (key, v)))

    # D06 群・水準の識別子
    if idx is not None and grp is not None:
        known = col(grp, "grouping_id") | col(grp, "group_id")
        for r in idx:
            for key in ("groups", "levels"):
                for v in split_ids(r.get(key)):
                    if v not in known:
                        f.append(Finding("D06", "warning", "tlf-index.csv",
                                         "%s の %s が analysis-grouping.csv に無い"
                                         % (key, v)))

    # D07 根拠の節が統計解析計画書にあるか
    if sap_path:
        if not os.path.isfile(sap_path):
            raise SystemExit("統計解析計画書がありません: %s" % sap_path)
        text = open(sap_path, encoding="utf-8").read()
        present = set(RE_SECTION.findall(text))
        for name, rows, key in (("display-contract.csv", dc, "source"),
                                ("primary-endpoint.csv", pe, "source"),
                                ("analysis-set-condition.csv", asc, "note")):
            if not rows:
                continue
            for r in rows:
                for sec in RE_SECTION.findall(r.get(key) or ""):
                    if sec not in present:
                        f.append(Finding("D07", "error", name,
                                         "根拠の節 %s が統計解析計画書に無い" % sec))
    return f


def main():
    p = argparse.ArgumentParser(description="機械可読な宣言と統計解析計画書の対応を検査する")
    p.add_argument("--metadata", required=True, help="docs/metadata")
    p.add_argument("--acceptance", required=True, help="docs/validation/acceptance")
    p.add_argument("--sap", help="統計解析計画書（text/markdown）。渡すと根拠の節を照合する")
    p.add_argument("--severity", choices=SEVERITIES, default="info",
                   help="この深刻度以上だけ出す（既定 info＝全部）")
    a = p.parse_args()

    for d in (a.metadata, a.acceptance):
        if not os.path.isdir(d):
            print("ディレクトリがありません: %s" % d)
            return 2

    findings = audit(a.metadata, a.acceptance, a.sap)
    code = 1 if any(x.severity == "error" for x in findings) else 0

    floor = SEVERITIES.index(a.severity)
    shown = [x for x in findings if SEVERITIES.index(x.severity) >= floor]
    shown.sort(key=lambda x: (-SEVERITIES.index(x.severity), x.rule, x.where))

    print("宣言: %s / 受入基準: %s" % (a.metadata, a.acceptance))
    if a.sap:
        print("統計解析計画書: %s" % a.sap)
    print()
    if not shown:
        print("指摘はありません。識別子の対応と根拠の節の実在だけを見ています。")
    for x in shown:
        print("  [%s/%s] %s: %s" % (x.rule, x.severity, x.where, x.message))
    if code:
        print()
        print("error があるので終了コード 1 を返します。区間1の出口条件を満たしません。")
    return code


if __name__ == "__main__":
    sys.exit(main())
