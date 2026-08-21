#!/usr/bin/env python3
"""立案時レビューの機械検査をまとめて回す。

規則とチェックリストはこのスクリプトが持たない。公開リポジトリ
`nnh/trial-planning-and-analysis` の `review/` にある2本を呼ぶだけである。
規則をここへ写すと正本が2つになり、片方だけ直された状態に必ずなる。

    python run-planning-review.py --sap <文書> --prt <文書> --ecrf <JSON>

いずれの引数も省略でき、渡したものだけを検査する。文書は plain text か markdown。
docx は `pandoc -t markdown` に、Google Docs は markdown の書き出しに通す。

`review/` の置き場は次の順で探す。

    1. 環境変数 TRIAL_REVIEW_DIR
    2. ~/Projects/nnh/trial-planning-and-analysis/review
    3. ~/trial-planning-and-analysis/review
"""

import argparse
import os
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def methods_dir():
    cands = []
    env = os.environ.get("TRIAL_REVIEW_DIR")
    if env:
        cands.append(env)
    home = os.path.expanduser("~")
    cands.append(os.path.join(home, "Projects", "nnh", "trial-planning-and-analysis", "review"))
    cands.append(os.path.join(home, "trial-planning-and-analysis", "review"))
    for c in cands:
        if os.path.isdir(os.path.join(c, "planning-review")):
            return c
    raise SystemExit("\n".join([
        "review/ の置き場が見つかりません。次を探しました:",
        *["  " + c for c in cands],
        "TRIAL_REVIEW_DIR で場所を指定するか、nnh/trial-planning-and-analysis を clone してください。",
    ]))


def run(label, script, args):
    """検査を1本回す。走ったことを件数ではなく終了コードで示す。"""
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    if not os.path.isfile(script):
        print(f"  検査スクリプトが無い: {script}")
        return 1
    r = subprocess.run([sys.executable, script, *args], text=True,
                       capture_output=True, encoding="utf-8", errors="replace")
    sys.stdout.write(r.stdout)
    if r.stderr.strip():
        sys.stderr.write(r.stderr)
    print(f"\n  （終了コード {r.returncode}。0 でなければ検査は走っていないので件数を0と読まない）")
    return r.returncode


def main() -> int:
    p = argparse.ArgumentParser(description="立案時レビューの機械検査をまとめて回す")
    p.add_argument("--sap", help="統計解析計画書（text/markdown）")
    p.add_argument("--prt", help="研究計画書（text/markdown）")
    p.add_argument("--ecrf", help="電子症例報告書の構造定義 JSON")
    p.add_argument("--severity", default="warning", choices=("info", "warning", "error"),
                   help="この深刻度以上だけ出す（既定 warning）")
    a = p.parse_args()

    if not (a.sap or a.prt or a.ecrf):
        p.error("--sap・--prt・--ecrf のどれかを渡してください")

    m = methods_dir()
    sap_audit = os.path.join(m, "planning-review", "audit_sap_structure.py")
    ecrf_audit = os.path.join(m, "ecrf-review", "audit_ecrf_json.py")
    print(f"方法論の置き場: {m}")

    codes = []
    if a.sap:
        codes.append(run("統計解析計画書の構造（S01-S10）", sap_audit, [a.sap, "--severity", a.severity]))
    if a.prt:
        codes.append(run("研究計画書の構造（S01-S10）", sap_audit, [a.prt, "--severity", a.severity]))
    if a.ecrf:
        codes.append(run("電子症例報告書の構造定義（R01-R12）", ecrf_audit, [a.ecrf, "--severity", a.severity]))

    print("\n" + "=" * 60)
    print("機械検査はここまで。判断が要る項目はチェックリストが持つ。")
    print(f"  研究計画書   {os.path.join(m, 'planning-review', 'checklist-prt.md')}")
    print(f"  図表案       {os.path.join(m, 'planning-review', 'checklist-tlf-shells.md')}")
    print(f"  統計解析計画書 {os.path.join(m, 'sap-review', 'checklist.md')}")
    print(f"  電子症例報告書 {os.path.join(m, 'ecrf-review', 'checklist.md')}")
    return 1 if any(codes) else 0


if __name__ == "__main__":
    sys.exit(main())
