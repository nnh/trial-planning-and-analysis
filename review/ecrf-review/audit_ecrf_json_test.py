# audit_ecrf_json_test.py
#
#   python audit_ecrf_json_test.py
#
# audit_ecrf_json.py の回帰確認。最小の構造定義をその場で組み立て、規則が拾うべきものを
# 拾い、拾うべきでないものを拾わないことを確かめる。標準ライブラリだけで動き、実際の
# 構造定義 JSON を要らない。
#
# 対象は、誤検出と見落としの実例から直した規則に限る。
#   R04  IE の IETEST に40文字を当てて、選択・除外基準が誤って error になった
#   R13  同じシート内の参照フィールドが、複製元の欄を指したままだった

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_ecrf_json import (build_index, rule_reference_same_sheet,  # noqa: E402
                             rule_test_length)


def field(name, seq, kind, label, default=None, ref=None):
    f = {"name": name, "seq": seq, "type": "FieldItem::" + kind, "label": label}
    if default is not None:
        f["default_value"] = default
    if ref is not None:
        f["reference_field"] = ref
    return f


def sheet(alias, items, configs):
    return {"alias_name": alias, "name": alias, "field_items": items,
            "cdisc_sheet_configs": [{"prefix": p, "label": rec, "table": t}
                                    for p, rec, t in configs]}


def run(rule, *sheets):
    spec = {"sheets": list(sheets), "options": []}
    built, options = build_index(spec)
    return list(rule(spec, built, options))


def test_length():
    ie = sheet("ie", [
        field("field1", 1, "Assigned", "Criterion", "x" * 150),
        field("field2", 2, "Assigned", "Criterion", "x" * 200),
        field("field3", 3, "Assigned", "Criterion", "x" * 201),
    ], [("IE", "001", {"field1": "TEST"}), ("IE", "002", {"field2": "TEST"}),
        ("IE", "003", {"field3": "TEST"})])
    lb = sheet("lb", [
        field("field1", 1, "Assigned", "Test", "y" * 40),
        field("field2", 2, "Assigned", "Test", "y" * 41),
    ], [("LB", "001", {"field1": "TEST"}), ("LB", "002", {"field2": "TEST"})])

    got = sorted((f.sheet, f.field) for f in run(rule_test_length, ie, lb))
    assert got == [("ie", "field3"), ("lb", "field2")], \
        "IETEST は200文字まで、他の --TEST は40文字まで: %s" % got


def lesions(targets):
    """標的病変を3つ持つシート。病変ごとに同定（TU）の入力と、計測（TR）が
    その入力を引く参照フィールドを持つ。targets は各病変の参照が指す病変の番号。"""
    items, configs = [], []
    for i, t in enumerate(targets, 1):
        base = i * 10
        items += [
            field("field%d" % base, base, "Heading", "標的病変%d" % i),
            field("field%d" % (base + 1), base + 1, "Article", "検査方法"),
            field("field%d" % (base + 2), base + 2, "Reference", "検査方法",
                  ref="base.field%d" % (t * 10 + 1)),
        ]
        configs += [("TU", "%03d" % (2 * i - 1), {"field%d" % (base + 1): "METHOD"}),
                    ("TR", "%03d" % (2 * i), {"field%d" % (base + 2): "METHOD"})]
    return sheet("base", items, configs)


def test_reference_same_sheet():
    # 病変2・3の参照が病変1を指したまま。並び順から本来の参照先を添える
    got = run(rule_reference_same_sheet, lesions([1, 1, 1]))
    assert [f.field for f in got] == ["field22", "field32"], \
        "置換漏れの2件: %s" % [f.field for f in got]
    assert "base.field21" in got[0].detail and "base.field31" in got[1].detail, \
        "本来の参照先: %s" % [f.detail for f in got]
    assert all(f.severity == "error" for f in got)

    # 正しい設計
    assert run(rule_reference_same_sheet, lesions([1, 2, 3])) == [], "正しい設計を拾った"

    # 参照フィールドが繰り返しより少ない。どれが正しいか決められないので、共有している
    # ものをすべて挙げ、参照されていない繰り返しを添える
    sh = lesions([1, 1, 1])
    sh["field_items"] = [f for f in sh["field_items"] if f["name"] != "field32"]
    got = run(rule_reference_same_sheet, sh)
    assert [f.field for f in got] == ["field12", "field22"], \
        "件数が合わないとき: %s" % [f.field for f in got]
    assert all("field21" in f.detail and "field31" in f.detail for f in got), \
        "参照されていない繰り返し: %s" % [f.detail for f in got]

    # シートに1つの評価日を全病変が引く設計。繰り返しが無いので拾わない
    common = sheet("base", [field("field1", 1, "Article", "評価日")] + [
        field("field%d" % (i * 10), i * 10, "Reference", "検査日", ref="base.field1")
        for i in (1, 2, 3)
    ], [("TR", "%03d" % i, {"field%d" % (i * 10): "DTC"}) for i in (1, 2, 3)])
    assert run(rule_reference_same_sheet, common) == [], "共通の評価日を拾った"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    test_length()
    test_reference_same_sheet()
    print("audit_ecrf_json: R04・R13 の回帰確認に合格")


if __name__ == "__main__":
    main()
