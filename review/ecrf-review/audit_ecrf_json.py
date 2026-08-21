#!/usr/bin/env python3
"""eCRF 構造定義 JSON の機械検査。

Ptosh からエクスポートした eCRF 構造定義 JSON を読み、設計時点で検出できる
欠陥を規則ベースで洗い出す。CDISC 担当者が返していた指摘表と同じ型の出力を
自前で得ることが目的。

    python audit_ecrf_json.py <構造定義JSON> [--format text|tsv] [--severity error|warning|info]

標準ライブラリのみで動く。実データ（SDTM）は見ない。実データ側の確認項目は
checklist.md の「実データでの裏打ち」を参照。
"""

import argparse
import collections
import json
import sys

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

# SDTM/SAS XPT の制約
MAX_TESTCD_LEN = 8
MAX_TEST_LEN = 40
MAX_LABEL_LEN = 40


class Finding:
    def __init__(self, rule_id, rule, severity, sheet, field, label, detail):
        self.rule_id = rule_id
        self.rule = rule
        self.severity = severity
        self.sheet = sheet
        self.field = field
        self.label = label
        self.detail = detail


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_index(spec):
    """シート・フィールド・選択肢・SDTM マッピングの索引を作る。"""
    options = {o["name"]: o for o in spec.get("options", [])}

    sheets = []
    for sh in spec.get("sheets", []):
        alias = sh.get("alias_name") or sh.get("name")
        fields = {f["name"]: f for f in sh.get("field_items", [])}

        # field名 -> [(ドメイン, SDTM変数, レコードlabel), ...]
        mapping = collections.defaultdict(list)
        for cfg in sh.get("cdisc_sheet_configs", []) or []:
            prefix = cfg.get("prefix", "")
            for fname, var in (cfg.get("table") or {}).items():
                mapping[fname].append((prefix, var, cfg.get("label", "")))

        sheets.append({
            "alias": alias,
            "name": sh.get("name"),
            "raw": sh,
            "fields": fields,
            "mapping": mapping,
        })
    return sheets, options


def field_values(field, options):
    """そのフィールドが取りうる (コード, 表示ラベル) の一覧。"""
    out = []
    opt = options.get(field.get("option_name"))
    if opt:
        for v in opt.get("values", []):
            if v.get("is_usable", True):
                out.append((v.get("code", ""), v.get("name", "")))
    dv = field.get("default_value")
    if dv and not out:
        out.append((dv, dv))
    elif dv and not any(c == dv for c, _ in out):
        out.append((dv, dv))
    return out


def is_input_field(field):
    """入力または固定値として値を持つフィールドか（見出し・注記を除く）。"""
    return field.get("type") in ("FieldItem::Article", "FieldItem::Assigned",
                                 "FieldItem::Reference")


# --------------------------------------------------------------------------
# 規則
# --------------------------------------------------------------------------

def rule_sheet_group_unassigned(spec, sheets, options):
    """R01 どのシートグループにも割り当てられていないシート。

    ある試験で5年時点の最終転帰報告が該当した。設定漏れなら、そのシートの
    項目が特定の症例群で収集できない。
    """
    assigned = set()
    for g in spec.get("sheet_groups", []):
        for s in g.get("sheets", []) or []:
            assigned.add(s.get("alias_name"))
        if g.get("allocation_sheet"):
            assigned.add(g["allocation_sheet"].get("alias_name"))

    ordered = [o.get("sheet") for o in spec.get("sheet_orders", [])]
    for alias in ordered:
        if alias and alias not in assigned:
            yield Finding(
                "R01", "シートグループ未割り当て", "error", alias, "", "",
                "表示順（sheet_orders）には存在するが、どのシートグループの sheets "
                "にも含まれない。仕様か設定漏れかをデータセンターに確認する")


def rule_reference_cross_sheet(spec, sheets, options):
    """R02 参照フィールドが自シート以外を参照している。

    ある試験で、参照フィールドを持つシートを複製した際に参照先シート名が
    置き換わらず、60例全例の採取日・実施機関等が別シートの値になった。
    """
    for sh in sheets:
        for f in sh["raw"].get("field_items", []):
            ref = f.get("reference_field")
            if not ref:
                continue
            target_sheet = ref.split(".")[0] if "." in ref else ""
            if target_sheet and target_sheet != sh["alias"]:
                yield Finding(
                    "R02", "参照フィールドが他シートを参照", "error",
                    sh["alias"], f["name"], f.get("label", ""),
                    "参照先 '%s' が自シート '%s' ではない。シート複製時の置換漏れの疑い"
                    % (ref, sh["alias"]))


def mapped_fields(sheets, suffix):
    """--TESTCD / --TEST にマップされたフィールドを、その固定値とともに返す。

    Ptosh では TESTCD・TEST は Assigned フィールドの default_value としてレコード
    ごとに固定される。選択肢マスタ（CDISC 用語集の取り込み）を展開すると、実際には
    使わない値まで指摘になるため、固定値だけを見る。
    """
    for sh in sheets:
        for fname, maps in sh["mapping"].items():
            field = sh["fields"].get(fname)
            if not field:
                continue
            for prefix, var, rec in maps:
                # 変数名を持たないマッピングがある。ドメイン接頭辞だけを指定して
                # 変数を割り当てていない項目で、ある試験の構造定義に実在した。
                # ここで落ちると以降の規則が1つも走らないので、飛ばして続ける。
                if not var or not var.endswith(suffix):
                    continue
                if suffix == "TEST" and var.endswith("TESTCD"):
                    continue
                value = field.get("default_value")
                if not value:
                    continue
                yield sh, fname, field, prefix, var, rec, value


def rule_testcd_length(spec, sheets, options):
    """R03 --TESTCD の値が8文字を超える（CT 規約違反）。

    ある試験で染色体異常の記法による TESTCD が9文字だった。
    """
    for sh, fname, field, prefix, var, _rec, value in mapped_fields(sheets,
                                                                   "TESTCD"):
        if len(value) > MAX_TESTCD_LEN:
            yield Finding(
                "R03", "TESTCD が8文字超", "error",
                sh["alias"], fname, field.get("label", ""),
                "%s.%s の値 '%s' は %d 文字" % (prefix, var, value, len(value)))


def rule_test_length(spec, sheets, options):
    """R04 --TEST の値が40文字を超える。"""
    for sh, fname, field, prefix, var, _rec, value in mapped_fields(sheets,
                                                                    "TEST"):
        if len(value) > MAX_TEST_LEN:
            yield Finding(
                "R04", "TEST が40文字超", "error",
                sh["alias"], fname, field.get("label", ""),
                "%s.%s の値 '%s' は %d 文字" % (prefix, var, value, len(value)))


def rule_label_length(spec, sheets, options):
    """R05 SDTM 変数に紐づくフィールドのラベルが40文字を超える。

    SAS XPT の変数ラベル上限。日本語ラベルは超えやすく、意図的に残す判断も
    ありうる（ある試験では CDISC 担当者が修正不要と判断した）。
    """
    for sh in sheets:
        for fname, maps in sh["mapping"].items():
            field = sh["fields"].get(fname)
            if not field:
                continue
            label = field.get("label") or ""
            if len(label) > MAX_LABEL_LEN:
                var = "/".join("%s.%s" % (p, v) for p, v, _ in maps)
                yield Finding(
                    "R05", "変数ラベルが40文字超", "warning",
                    sh["alias"], fname, label,
                    "%s のラベルは %d 文字。残す判断なら判断の記録を残す"
                    % (var, len(label)))


def rule_duplicate_testcd(spec, sheets, options):
    """R06 同一シート・同一ドメイン内で TESTCD が重複（コピペミスの疑い）。

    ある試験で別の遺伝子変異の TESTCD が、複製元の遺伝子のままだった。
    """
    by_sheet = collections.defaultdict(lambda: collections.defaultdict(list))
    for sh, fname, field, prefix, var, rec, value in mapped_fields(sheets,
                                                                   "TESTCD"):
        by_sheet[sh["alias"]][(prefix, value)].append((fname, rec))

    for alias, seen in by_sheet.items():
        for (prefix, code), items in seen.items():
            recs = {rec for _f, rec in items}
            # 同じレコード label の中で重複していれば取り違え。レコードが違えば
            # 別行として出力されるため正常。
            if len(items) > len(recs):
                yield Finding(
                    "R06", "同一シート内で TESTCD が重複", "warning",
                    alias, ", ".join(f for f, _r in items), "",
                    "%s ドメインの同一レコードで TESTCD '%s' が重複。"
                    "検査項目の取り違え（コピペミス）の疑い" % (prefix, code))


def rule_option_duplicate_label(spec, sheets, options):
    """R07 選択肢マスタ内で表示ラベルが重複（排反違反の疑い）。

    別コードに同じ表示ラベルが付いていると、入力者は区別できず、格納値も割れる。
    """
    used = set()
    fixed = collections.Counter()
    for sh in sheets:
        for f in sh["raw"].get("field_items", []):
            if f.get("option_name"):
                used.add(f["option_name"])
            if f.get("default_value"):
                fixed[f["default_value"]] += 1

    for name in sorted(used):
        opt = options.get(name)
        if not opt:
            continue
        by_label = collections.defaultdict(list)
        for v in opt.get("values", []):
            if v.get("is_usable", True):
                by_label[v.get("name", "")].append(v.get("code", ""))
        for label, codes in by_label.items():
            if len(codes) < 2:
                continue
            # この試験で固定値として実際に使われているコードの数を添える。
            # 片方しか使っていなければ本試験のデータは割れない（マスタ側の問題）。
            live = [c for c in codes if fixed[c]]
            sev = "warning" if len(live) > 1 else "info"
            yield Finding(
                "R07", "選択肢の表示ラベルが重複", sev,
                "(選択肢マスタ)", name, label,
                "表示ラベル '%s' が %d 件（code: %s）。排反でない疑い。"
                "本試験で固定値として使用中: %s"
                % (label, len(codes), ", ".join(codes),
                   ", ".join(live) if live else "なし"))


def rule_duplicate_field_label(spec, sheets, options):
    """R08 同一シート内で入力フィールドのラベルが重複。

    設計上の意図がある場合もある（治療内容を2枠置く等）が、突合表を作る際に
    どちらの値かが判別できなくなるため、意図の記録を要求する。
    """
    for sh in sheets:
        by_label = collections.defaultdict(list)
        for f in sh["raw"].get("field_items", []):
            if f.get("type") != "FieldItem::Article":
                continue
            if f.get("is_invisible"):
                continue
            lb = (f.get("label") or "").strip()
            if lb:
                by_label[lb].append(f["name"])
        for lb, names in by_label.items():
            if len(names) > 1:
                yield Finding(
                    "R08", "シート内でラベルが重複", "info",
                    sh["alias"], ", ".join(names), lb,
                    "同一ラベルの入力フィールドが %d 件" % len(names))


def rule_date_validator(spec, sheets, options):
    """R09 日付フィールドに日付整合バリデータが無い。

    上限に Date.current を置かないと未来日が入る。
    """
    for sh in sheets:
        for f in sh["raw"].get("field_items", []):
            if f.get("field_type") != "date":
                continue
            v = (f.get("validators") or {}).get("date") or {}
            if not v:
                yield Finding(
                    "R09", "日付バリデータなし", "warning",
                    sh["alias"], f["name"], f.get("label", ""),
                    "日付の前後関係・範囲バリデータが設定されていない")


def rule_numeric_validator(spec, sheets, options):
    """R10 数値入力の範囲バリデータが無い、または片側しか無い。

    ある試験のテストデータで、下限0のはずの握力と使用薬総数が -1 だった。
    バリデータの有無だけでなく、実データでの裏打ちが要る。
    """
    for sh in sheets:
        for f in sh["raw"].get("field_items", []):
            if f.get("field_type") != "text":
                continue
            v = (f.get("validators") or {}).get("numericality")
            if v is None:
                yield Finding(
                    "R10", "数値範囲バリデータなし", "info",
                    sh["alias"], f["name"], f.get("label", ""),
                    "自由記述なら問題ない。数値項目なら上下限を設定する")
                continue
            has_min = "validate_numericality_greater_than_or_equal_to" in v \
                or "validate_numericality_greater_than" in v
            has_max = "validate_numericality_less_than_or_equal_to" in v \
                or "validate_numericality_less_than" in v
            if not (has_min and has_max):
                side = "上限" if has_min else "下限"
                yield Finding(
                    "R10", "数値範囲が片側のみ", "info",
                    sh["alias"], f["name"], f.get("label", ""),
                    "%sが未設定（%s）" % (side, json.dumps(v, ensure_ascii=False)))


def rule_unmapped_input(spec, sheets, options):
    """R11 SDTM にマップされていない入力フィールド。

    分岐制御用なら出力しない設計で正しい。解析に使う値が紛れていないかを見る。
    """
    for sh in sheets:
        for f in sh["raw"].get("field_items", []):
            if f.get("type") != "FieldItem::Article":
                continue
            if f["name"] in sh["mapping"]:
                continue
            yield Finding(
                "R11", "SDTM 未マップの入力項目", "info",
                sh["alias"], f["name"], f.get("label", ""),
                "分岐制御用か、出力すべき項目かを判断する")


def rule_unusable_option_values(spec, sheets, options):
    """R12 使用不可（is_usable=false）の選択肢を含む選択肢マスタ。

    PRT・SAP が要求する値が無効化されていないかを目視で確かめる。
    """
    used = collections.defaultdict(set)
    for sh in sheets:
        for f in sh["raw"].get("field_items", []):
            if f.get("option_name"):
                used[f["option_name"]].add(sh["alias"])

    for name in sorted(used):
        opt = options.get(name)
        if not opt:
            continue
        dead = [v.get("name", "") for v in opt.get("values", [])
                if not v.get("is_usable", True)]
        if dead:
            yield Finding(
                "R12", "無効化された選択肢がある", "info",
                ", ".join(sorted(used[name])), name, "",
                "非表示 %d 件: %s" % (len(dead), " / ".join(dead[:8])
                                    + (" ..." if len(dead) > 8 else "")))


RULES = [
    rule_sheet_group_unassigned,
    rule_reference_cross_sheet,
    rule_testcd_length,
    rule_test_length,
    rule_label_length,
    rule_duplicate_testcd,
    rule_option_duplicate_label,
    rule_duplicate_field_label,
    rule_date_validator,
    rule_numeric_validator,
    rule_unmapped_input,
    rule_unusable_option_values,
]


def main():
    p = argparse.ArgumentParser(description="eCRF 構造定義 JSON の機械検査")
    p.add_argument("spec", help="Ptosh からエクスポートした構造定義 JSON")
    p.add_argument("--format", choices=["text", "tsv"], default="text")
    p.add_argument("--severity", choices=["error", "warning", "info"],
                   default="info", help="この重大度までを出力する")
    args = p.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    spec = load(args.spec)
    sheets, options = build_index(spec)

    limit = SEVERITY_ORDER[args.severity]
    findings = []
    for rule in RULES:
        for f in rule(spec, sheets, options):
            if SEVERITY_ORDER[f.severity] <= limit:
                findings.append(f)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id, f.sheet))

    if args.format == "tsv":
        print("\t".join(["重大度", "規則ID", "規則", "シート", "フィールド",
                         "ラベル", "指摘内容"]))
        for f in findings:
            print("\t".join([f.severity, f.rule_id, f.rule, f.sheet, f.field,
                             f.label.replace("\t", " "),
                             f.detail.replace("\t", " ")]))
        return

    total_fields = sum(len(s["fields"]) for s in sheets)
    print("試験: %s（%s）" % (spec.get("proper_name") or spec.get("name"),
                          spec.get("name")))
    print("SDTM 版: %s / 用語集: %s / CTCAE: %s"
          % (spec.get("sdtm_version"), spec.get("sdtm_terminology_version"),
             spec.get("ctcae_version")))
    print("シート %d 枚・フィールド %d 件・選択肢マスタ %d 件"
          % (len(sheets), total_fields, len(options)))
    print()

    counts = collections.Counter(f.severity for f in findings)
    print("検出: error %d / warning %d / info %d"
          % (counts["error"], counts["warning"], counts["info"]))
    print()

    current = None
    for f in findings:
        key = (f.severity, f.rule_id, f.rule)
        if key != current:
            current = key
            n = sum(1 for x in findings
                    if (x.severity, x.rule_id) == (f.severity, f.rule_id))
            print("## [%s] %s %s（%d件）" % (f.severity.upper(), f.rule_id,
                                          f.rule, n))
        loc = f.sheet + (" " + f.field if f.field else "")
        print("- %s%s\n  %s" % (loc, ("｜" + f.label if f.label else ""), f.detail))
    if not findings:
        print("指摘なし。")


if __name__ == "__main__":
    main()
