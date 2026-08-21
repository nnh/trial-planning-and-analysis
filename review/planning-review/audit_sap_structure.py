#!/usr/bin/env python3
"""統計解析計画書・研究計画書の構造を機械検査する。

文書の構造だけを見る。記述の内容が正しいかは判定しない。0 件でも記述が正しい
ことにはならず、内容の観点は checklist-prt.md・checklist-tlf-shells.md と
../sap-review/checklist.md が持つ。

ここに入れたのは、複数試験のレビューで実際に挙がった指摘のうち、規則で判定
できたものだけである。人が読んで判断する項目は入れていない。判断の要る項目
まで機械にすると、出力が長くなって読まれなくなる。

入力は plain text か markdown。Google Docs なら markdown で書き出し、docx なら
`pandoc -t markdown` に通す。

    python audit_sap_structure.py <文書> [--severity warning] [--format tsv]

規則

    S01  目次と本文の見出しが一致しない         warning
    S02  節番号が重複している                   error
    S03  節番号が飛んでいる                     warning
    S04  句点で終わらない段落                   warning
    S05  同じ段落が複数回現れる                 error
    S06  略号一覧が無い、または一覧に無い略号   info
    S07  一度しか現れない図表番号               warning
    S08  全角の英数字                           info
    S09  編集メモ・未確定の痕跡                 warning
    S10  メールアドレス                         warning

S05 は章の二重化を拾う。ある試験の統計解析計画書では第13章がまるごと二重になっ
ていた。
S07 は図表案と本文の逆引きの代わりになる。図表番号は本来、図表案で定義され本文から
参照されるので最低 2 回現れる。1 回しか出ない番号は、定義だけあって本文に根拠が無いか、
本文が参照しているのに図表案に無いかのどちらかである。
S10 は作業メモの混入を拾う。正本の末尾に作業メモを置く運用だと、固定のたびに外す作業が
手で入り、忘れれば個人の連絡先を含む文書が規制文書として保管される。
"""

import argparse
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# Windows のコンソールは cp932 なので、絵文字や一部の記号で落ちる。出力先が
# コンソールでないとき（パイプ・リダイレクト）は locale で書かれるため、明示的に
# UTF-8 へ寄せる。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


SEVERITIES = ("info", "warning", "error")

# 見出し: markdown の # と、番号だけの行の両方を拾う。
#   "## 4.4 主要評価項目"  "4.4 主要評価項目"  "4.4. 主要評価項目"
RE_HEADING = re.compile(r"^\s{0,3}(?:#{1,6}\s*)?(\d+(?:\.\d+){0,4})\.?[ 　\t]+(\S.*?)\s*$")

# 目次の行: 末尾にページ番号やドットリーダーが付く。
RE_TOC = re.compile(r"^\s*(\d+(?:\.\d+){0,4})\.?[ 　\t]+(.+?)[ 　\t.．・]*(\d{1,3})?\s*$")

# markdown の順序付きリスト。単一レベルの「N. 」は見出しと見分けが付かないため、
# 前後の非空行も同じ形かどうかで判定する（見出しは連続して並ばない）。
RE_ORDERED_ITEM = re.compile(r"^\s*\d+\.[ 　	]")

# 図表番号: 表 5.4.1 / 図5.4.1 / Table 5.4.1 / Figure 5.4.1
RE_TLF = re.compile(r"(表|図|Table|Figure)\s*(\d+(?:[.\-]\d+){1,4})")

RE_MAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

RE_FULLWIDTH_ALNUM = re.compile(r"[Ａ-Ｚａ-ｚ０-９]")

# 編集メモ・未確定の痕跡。実際に残っていた語から作る。(正規表現, 表示名, 深刻度)。
#
# 数値のプレースホルダだけ info にしてある。図表案は実データを入れる前の枠なので、
# xx(%) の形が正しく置かれている。warning にすると図表案の数だけ出て、他の指摘が
# 埋もれる（実際の統計解析計画書で 45 件出た）。
MEMO_PATTERNS = [
    (r"TBD|TODO|FIXME", "未確定の印", "warning"),
    (r"要確認|要検討|要修正|後で|あとで", "作業メモ", "warning"),
    (r"（案）|\(案\)|暫定|仮置き|たたき台", "確定前の印", "warning"),
    (r"[●○◯]{2,}|〇〇|××|ＸＸ", "伏字のプレースホルダ", "warning"),
    (r"\bxx\b|\bXX\b|ｘｘ", "数値のプレースホルダ", "info"),
    (r"＜＜|＞＞|<<[^>]{1,40}>>", "差し込みの印", "warning"),
    (r"コメント[:：]|申し送り|査読", "査読の痕跡", "warning"),
]

# markdown のリンク。目次の行が [見出し [頁](#..)](#..) の形になることがある
# （docx を pandoc に通すと必ずこうなる）。比較の前に外す。
RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# markdown の強調。Google Docs 由来の見出しは `# **1. 概要**` の形になる。
RE_EMPHASIS = re.compile(r"\*\*|__|\*|(?<![A-Za-z0-9])_(?![A-Za-z0-9])")

# 表のセル。この形の行は文ではないので、段落の規則から外す。
RE_TABLE_LINE = re.compile(r"^(　|\||\+[-=]|:?-{3,})")

# 定義行。「起算日：…」「Event：…」の形は句点で終わらないのが正常。
RE_DEF_LINE = re.compile(r"^[^\s：:]{1,12}[：:]")

# 略号一覧が置かれる節の見出し
RE_ABBR_SECTION = re.compile(r"(略号|略語|用語の定義|Abbreviat|Glossary)")

# 略号として拾う語: 英大文字2〜10（数字とハイフンを含んでよい）
RE_ABBR = re.compile(r"\b([A-Z][A-Z0-9\-]{1,9})\b")

# 略号ではないもの。単位・規格・ファイル形式など。
ABBR_STOP = {
    "AND", "OR", "NOT", "THE", "AND/OR", "PDF", "CSV", "XML", "HTML", "URL",
    "ID", "IDS", "NA", "N/A", "OK", "NG", "II", "III", "IV", "VI", "VII", "VIII",
    "IX", "XI", "XII", "MG", "KG", "ML", "DL", "UL", "MM", "CM", "MS",
}


class Finding:
    def __init__(self, rule, severity, line, message):
        self.rule = rule
        self.severity = severity
        self.line = line
        self.message = message


def normalize(s: str) -> str:
    """比較用に正規化する。全角と半角、連続する空白、記号のゆれを畳む。"""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[\s　]+", "", s)
    s = re.sub(r"[・.．,，:：;；\-－―ー~〜\"'“”‘’()（）\[\]【】]", "", s)
    return s


def read_lines(path: Path):
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return path.read_text(encoding=enc).splitlines()
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"エラー: 文字符号化を判定できません: {path}")


def split_paragraphs(lines):
    """空行区切りで段落に分ける。(開始行番号, 本文) を返す。"""
    out, buf, start = [], [], 0
    for i, ln in enumerate(lines, 1):
        if ln.strip():
            if not buf:
                start = i
            buf.append(ln.strip())
        elif buf:
            out.append((start, " ".join(buf)))
            buf = []
    if buf:
        out.append((start, " ".join(buf)))
    return out


def strip_inline(s: str) -> str:
    """見出しと目次の照合用に、markdown の飾りを外す。

    Google Docs を markdown で書き出すと見出しが `# **1. 概要**` の形になり、
    目次は `[**1. 概要** **4**](url)` になる。docx を pandoc に通したときは
    `[1. 概要 [4](#..)](#..)` になる。どちらも飾りを外さないと番号が読めない。
    """
    for _ in range(2):
        s = RE_MD_LINK.sub(r"\1", s)
    s = RE_EMPHASIS.sub("", s)
    return s.replace("\\", "")


def find_toc_range(lines):
    """目次の範囲を推定する。

    先頭 40% の中で、番号付きの行が 5 行以上連続する最初の塊を目次とみなす。
    ページ番号やドットリーダーが無い目次もあるため、連続性だけで判定する。
    空行は連続を切らない（docx 由来の目次は1行おきになる）。
    """
    limit = max(20, int(len(lines) * 0.4))
    best = None
    run_start, run_n = None, 0
    for i, ln in enumerate(lines[:limit]):
        ln = strip_inline(ln)
        if RE_TOC.match(ln) and not ln.lstrip().startswith("#"):
            if run_start is None:
                run_start = i
            run_n += 1
        else:
            # 空行は連続を切らない。docx 由来の目次は1行おきになるので、ここで
            # 打ち切ると先頭の5件だけを目次と読んでしまう。
            if not ln.strip():
                continue
            if run_n >= 5 and best is None:
                best = (run_start, i)
            run_start, run_n = None, 0
    if best is None and run_n >= 5:
        best = (run_start, limit)
    return best


def collect_headings(lines, skip):
    """本文の見出しを (行番号, 番号, 見出し文) で集める。

    ATX 見出し（`#` 付き）が5件以上ある文書では、それだけを見出しとみなす。
    見出しスタイルの付いた docx を pandoc に通すと必ず ATX になるので、
    実務ではこちらに倒れる。番号だけの行も拾うと、表のセル（`12 mos (365日)`
    のような行）を見出しと誤って読む。
    """
    atx = sum(1 for ln in lines if re.match(r"^#{1,6}\s", ln))
    atx_only = atx >= 5
    out = []
    lo, hi = skip if skip else (-1, -1)
    for i, ln in enumerate(lines):
        if lo <= i < hi:
            continue
        if atx_only and not ln.startswith("#"):
            continue
        m = RE_HEADING.match(strip_inline(ln))
        if not m:
            continue
        num, title = m.group(1), m.group(2)
        # 「5.4.1 は 3 例」のような本文の数値参照を弾く。見出しは短い。
        # ただし `#` 付きは見出しであることが確実なので長さで弾かない。英語の
        # 表題は 60 字を超えることがあり、弾くと欠番として誤報告する。
        if not ln.lstrip().startswith("#") and len(title) > 60:
            continue
        # 箇条書きの継続を弾く
        if ln.lstrip().startswith(("-", "*", "|", ">")):
            continue
        if not ln.lstrip().startswith("#") and _is_ordered_list_item(lines, i):
            continue
        out.append((i + 1, num, title))
    return out


def _is_ordered_list_item(lines, i) -> bool:
    """`N. ` の行が箇条書きかを、前後の非空行の形で判定する。"""
    if not RE_ORDERED_ITEM.match(lines[i]):
        return False
    for step in (-1, 1):
        j = i + step
        while 0 <= j < len(lines) and not lines[j].strip():
            j += step
        if 0 <= j < len(lines):
            t = lines[j]
            if RE_ORDERED_ITEM.match(t) or re.match(r"^\s*[-*+][ 	]", t):
                return True
    return False


def rule_toc(lines, headings, toc_range):
    f = []
    if not toc_range:
        return f
    lo, hi = toc_range
    toc = {}
    for i in range(lo, hi):
        m = RE_TOC.match(strip_inline(lines[i]))
        if m:
            toc[m.group(1)] = (i + 1, m.group(2).strip())

    body = {num: (ln, title) for ln, num, title in headings}
    for num, (ln, title) in sorted(toc.items()):
        if num not in body:
            f.append(Finding("S01", "warning", ln,
                             f"目次の {num} {title} に対応する本文の見出しがありません"))
        elif normalize(title) != normalize(body[num][1]):
            f.append(Finding("S01", "warning", body[num][0],
                             f"{num} の見出しが目次と違います（目次「{title}」／本文「{body[num][1]}」）"))
    for num, (ln, title) in sorted(body.items()):
        if num not in toc and num.count(".") <= 1:
            f.append(Finding("S01", "warning", ln,
                             f"本文の見出し {num} {title} が目次にありません"))
    return f


def rule_numbering(headings):
    f = []
    seen = defaultdict(list)
    for ln, num, title in headings:
        seen[num].append((ln, title))
    for num, hits in sorted(seen.items()):
        if len(hits) > 1:
            where = "・".join(str(ln) for ln, _ in hits)
            f.append(Finding("S02", "error", hits[1][0],
                             f"節番号 {num} が {len(hits)} 回現れます（{where} 行目）"))

    # 欠番: 親ごとに子の番号が 1 から連続しているか
    children = defaultdict(set)
    for _, num, _ in headings:
        parts = num.split(".")
        parent = ".".join(parts[:-1])
        try:
            children[parent].add(int(parts[-1]))
        except ValueError:
            continue
    line_of = {num: ln for ln, num, _ in headings}
    for parent, kids in sorted(children.items()):
        if not kids:
            continue
        missing = sorted(set(range(1, max(kids) + 1)) - kids)
        if missing:
            head = f"{parent}." if parent else ""
            anchor = line_of.get(f"{head}{max(kids)}", 0)
            f.append(Finding("S03", "warning", anchor,
                             f"{head}* の番号が飛んでいます: {'・'.join(head + str(m) for m in missing)}"))
    return f


def rule_paragraphs(paras):
    """S04（未完の文）と S05（段落の重複）。

    どちらも散文だけを対象にする。docx を pandoc に通すと表のセルと図表の見出しが
    段落として出てくるが、これらは句点で終わらないのが正常で、行の見出しは図表を
    またいで何度も現れるのが正常である。実際の統計解析計画書で S04 が 223 件、
    S05 が 10 件出て、すべてこれだった。

    散文の判定は「句点を1つ以上含むこと」で行う。未完の文とは、句点で区切られた
    文が続いた末尾だけが切れている状態を指すので、これで漏れない。
    """
    f = []
    enders = "。．.!?！？：:）)」』】>"
    for ln, text in paras:
        t = text.strip()
        if len(t) < 40:
            continue
        if RE_HEADING.match(t) or t.startswith(("-", "*", "|", ">", "#", "!", "```")):
            continue
        if RE_TABLE_LINE.match(t):
            continue
        if "。" not in t:
            continue
        # 「起算日：…」「Event：…」のような定義行は、句点で終わらないのが正常。
        if RE_DEF_LINE.match(t):
            continue
        # pandoc の span 記法（[…]{.underline} 等）が残る行は変換の痕跡なので見ない。
        if "{." in t:
            continue
        if t.endswith(tuple(enders)):
            continue
        f.append(Finding("S04", "warning", ln,
                         f"句点で終わっていません: {t[:40]}…"))

    # 重複の判定。要旨の章を持つ研究計画書では、概要と本文で同じ段落が正当に
    # 繰り返される（ある試験の計画書では 1.1 概要 と 2.1 目的 が該当した）。
    # 一方、別の試験で起きた章の二重化では、重複する段落が固まって多数出る。
    # 件数で区別し、少数なら warning、5 件以上なら章の二重化を疑って error にする。
    counts = Counter()
    where = defaultdict(list)
    sample = {}
    for ln, text in paras:
        t = text.strip()
        if RE_TABLE_LINE.match(t) or "。" not in t:
            continue
        key = normalize(t)
        if len(key) < 60:
            continue
        counts[key] += 1
        where[key].append(ln)
        sample.setdefault(key, t)
    dups = {k: n for k, n in counts.items() if n > 1}
    sev = "error" if len(dups) >= 5 else "warning"
    tail = "（重複が多く、章の二重化が疑われます）" if sev == "error" else "（要旨と本文の繰り返しなら正常）"
    for key in dups:
        lns = "・".join(str(x) for x in where[key])
        f.append(Finding("S05", sev, where[key][0],
                         f"同じ段落が {counts[key]} 回現れます{tail}（{lns} 行目）: {sample[key][:40]}…"))
    return f


def rule_abbreviations(lines, headings):
    f = []
    has_section = any(RE_ABBR_SECTION.search(t) for _, _, t in headings)
    if not has_section:
        f.append(Finding("S06", "info", 0,
                         "略号一覧の節がありません。略号は初出で定義するか一覧を置きます"))
        return f
    # 一覧の節の中身を集める
    listed = set()
    start = None
    for ln, num, title in headings:
        if RE_ABBR_SECTION.search(title):
            start = ln
            break
    if start:
        for ln in lines[start:start + 200]:
            if RE_HEADING.match(ln) and not RE_ABBR_SECTION.search(ln):
                break
            listed |= {a for a in RE_ABBR.findall(ln)}
    used = Counter()
    where = {}
    for i, ln in enumerate(lines, 1):
        for a in RE_ABBR.findall(ln):
            if a in ABBR_STOP or a.isdigit():
                continue
            used[a] += 1
            where.setdefault(a, i)
    for a, n in sorted(used.items()):
        if a not in listed and n >= 2:
            f.append(Finding("S06", "info", where[a],
                             f"略号 {a} が {n} 回使われていますが一覧にありません"))
    return f


def rule_tlf_numbers(lines):
    f = []
    hits = defaultdict(list)
    for i, ln in enumerate(lines, 1):
        for kind, num in RE_TLF.findall(ln):
            k = "図" if kind in ("図", "Figure") else "表"
            hits[(k, num)].append(i)
    for (kind, num), where in sorted(hits.items()):
        if len(where) == 1:
            f.append(Finding("S07", "warning", where[0],
                             f"{kind} {num} が1度しか現れません（図表案と本文の一方に無い可能性）"))
    return f


def rule_characters(lines):
    f = []
    for i, ln in enumerate(lines, 1):
        m = RE_FULLWIDTH_ALNUM.search(ln)
        if m:
            f.append(Finding("S08", "info", i,
                             f"全角の英数字があります: {ln.strip()[:40]}…"))
        for pat, label, sev in MEMO_PATTERNS:
            mm = re.search(pat, ln)
            if mm:
                f.append(Finding("S09", sev, i,
                                 f"{label}が残っています（{mm.group(0)}）: {ln.strip()[:40]}…"))
                break
        for mail in RE_MAIL.findall(ln):
            f.append(Finding("S10", "warning", i,
                             f"メールアドレスがあります（研究計画書の連絡先の節なら正常）: {mail}"))
    return f


def audit(path: Path):
    lines = read_lines(path)
    paras = split_paragraphs(lines)
    toc_range = find_toc_range(lines)
    headings = collect_headings(lines, toc_range)

    f = []
    f += rule_toc(lines, headings, toc_range)
    f += rule_numbering(headings)
    f += rule_paragraphs(paras)
    f += rule_abbreviations(lines, headings)
    f += rule_tlf_numbers(lines)
    f += rule_characters(lines)
    return lines, headings, toc_range, f


def main() -> int:
    p = argparse.ArgumentParser(description="統計解析計画書・研究計画書の構造を機械検査する")
    p.add_argument("path", help="plain text か markdown")
    p.add_argument("--severity", choices=SEVERITIES, default="info",
                   help="この深刻度以上だけ出す（既定 info＝全部）")
    p.add_argument("--format", choices=("text", "tsv"), default="text")
    p.add_argument("--rule", action="append",
                   help="この規則だけ出す（S01 など。複数指定可）")
    a = p.parse_args()

    path = Path(a.path)
    if not path.is_file():
        print(f"エラー: ファイルがありません: {path}")
        return 1

    lines, headings, toc_range, findings = audit(path)

    floor = SEVERITIES.index(a.severity)
    findings = [x for x in findings if SEVERITIES.index(x.severity) >= floor]
    if a.rule:
        want = {r.upper() for r in a.rule}
        findings = [x for x in findings if x.rule in want]
    findings.sort(key=lambda x: (-SEVERITIES.index(x.severity), x.rule, x.line))

    if a.format == "tsv":
        print("rule\tseverity\tline\tmessage")
        for x in findings:
            print(f"{x.rule}\t{x.severity}\t{x.line}\t{x.message}")
        return 0

    toc = f"{toc_range[0] + 1}-{toc_range[1]} 行目" if toc_range else "検出せず"
    print(f"対象: {path}（{len(lines)} 行・見出し {len(headings)} 件・目次 {toc}）")
    print()
    if not findings:
        print("指摘はありません。構造の検査のみで、記述の内容は判定していません。")
        return 0

    by_rule = Counter(x.rule for x in findings)
    for x in findings:
        print(f"  [{x.rule}/{x.severity}] {x.line} 行目: {x.message}")
    print()
    print(f"計 {len(findings)} 件（{'・'.join(f'{r} {n}' for r, n in sorted(by_rule.items()))}）")
    print("構造の検査のみです。0 件でも記述が正しいことにはなりません。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
