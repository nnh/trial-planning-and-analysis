#!/usr/bin/env python3
"""固定データの機械検査。

data-verification.md の手順のうち、規則で判定できる部分だけを引き受ける。
4.1（実値の走査）・4.4（固定前後の差分）・4.5（規定の隙間に落ちる症例）の
機械化できる部分が対象で、4.2（条文と実装の突合）は人が読む項目なので入れて
いない。4.3（構造定義の検査）は ../ecrf-review/audit_ecrf_json.py が持つので
ここでは扱わない。

0 件でもデータが正しいことにはならない。ここで見ているのは実値の形と内部整合
だけで、データそのものの正しさは原資料との照合でしか分からない
（data-verification.md「検出できないもの」）。

    python audit_fixed_data.py inventory <データのディレクトリ>
    python audit_fixed_data.py audit     <データのディレクトリ> [--expect 宣言値.csv]
    python audit_fixed_data.py diff      <固定前のディレクトリ> <固定後のディレクトリ>

規則

    D01  宣言が名指しする変数・値が実データに無い       error
    D02  宣言に無い値が実データにある                   warning
    D03  値の前後に空白・制御文字がある                 error
    D04  正規化すると一致する値が複数の綴りで存在する   warning
    D05  空白・判定不能を表す値が混在する               info
    D06  全件が空の変数                                 info
    D07  日付変数が ISO 8601 で読めない                 error
    D08  被験者内で識別子が重複する                     error
    D09  被験者の集合がドメイン間で食い違う             warning
    D10  発生の有無と日付が整合しない                   warning

終了コード

    0  検査が走り、error 級の指摘が無かった
    1  検査が走り、error 級の指摘があった
    2  検査が走らなかった（入力が無い・読めない・外部パッケージが無い）

2 を 0 と区別するのは、検査が走らないまま 0 件と読む事故を避けるためである。
読み込みの文字符号化が合わない、外部パッケージが無い、ディレクトリが空、の
いずれも「指摘なし」ではない。

入力は CSV（受領データ）と Dataset-JSON v1.1 を標準ライブラリだけで読む。
XPT は外部パッケージ（pyreadstat）が要るので、関数の中で読み込み、入っていない
端末では 2 を返す。
"""

import argparse
import collections
import csv
import hashlib
import json
import os
import re
import sys
import unicodedata

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SEVERITIES = ("error", "warning", "info")
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}

# 値の分布を出すかどうかのしきい値。data-verification.md 4.1 の 25 に合わせる。
DEFAULT_MAX_LEVELS = 25

# 判定を表す変数の接尾辞。固定前後で変わるとイベント判定が変わる（4.4）。
DECISION_SUFFIXES = ("OCCUR", "STAT", "REASND", "ORRES", "STRESC", "TERM",
                     "DECOD", "OUT", "SCAT", "CAT", "BLFL")

# 被験者の識別子。受領データの綴りが違う試験があるので候補で持つ。
SUBJECT_KEYS = ("USUBJID", "SUBJID", "SUBJECTID")

# 突合のキーに使わない変数。--SEQ は固定時に振り直される（4.4）。
KEY_EXCLUDED_SUFFIXES = ("SEQ", "DY")

# 突合のキーの候補。被験者の識別子に続けて、内容を表す項目を足す。
# 判定を表す変数はキーに入れない（下の diff_key）。TERM はかつて候補だったが、
# DSTERM のように判定変数でもあるため、変わった行が別の行として数えられていた。
KEY_SUFFIX_CANDIDATES = ("SPID", "TESTCD", "TRT", "CAT", "LNKID")

# 実行時の設定。既定は「直さない・直下だけ見る」で、緩めるときは引数で明示する。
ALLOW_RAGGED = False
RECURSIVE = False
RAGGED_FIXED = []
KEY_PLAIN_CANDIDATES = ("VISITNUM", "VISIT")

# 空白・判定不能を表す値。集計から静かに外れる、または 0 件で通る素地になる。
UNDETERMINED = {
    "", ".", "-", "ー", "‐", "NA", "N/A", "N.A.", "NULL", "NONE", "NE", "ND",
    "UNK", "UNKNOWN", "不明", "未実施", "未検", "未評価", "判定不能", "評価不能",
    "該当なし", "該当せず", "なし", "無", "無し",
}

RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
RE_ISO8601 = re.compile(
    r"^\d{4}(-\d{2}(-\d{2}(T\d{2}(:\d{2}(:\d{2}(\.\d+)?)?)?)?)?)?$")
# 部分日付を許す書き方。SDTM は欠けた要素を - で埋める形も許す。
RE_ISO8601_PARTIAL = re.compile(r"^[\d-]{4,10}(T[\d:.-]{2,12})?$")


class Finding:
    def __init__(self, rule, severity, domain, variable, detail):
        self.rule = rule
        self.severity = severity
        self.domain = domain
        self.variable = variable
        self.detail = detail


class Dataset:
    """1 ドメイン分の表。列は宣言順に持つ。値はすべて文字列として扱う。"""

    def __init__(self, domain, columns, rows, source):
        self.domain = domain
        self.columns = columns
        self.rows = rows
        self.source = source

    def column(self, name):
        i = self.columns.index(name)
        return [r[i] for r in self.rows]

    def suffix(self, suffix):
        """ドメイン接頭辞 + suffix の変数名を返す。無ければ None。"""
        name = self.domain + suffix
        return name if name in self.columns else None

    def subject_key(self):
        for k in SUBJECT_KEYS:
            if k in self.columns:
                return k
        return None


class Unreadable(Exception):
    """検査が走らなかったことを表す。終了コード 2 に対応する。"""


# ---------------------------------------------------------------- 読み込み


def read_csv(path, encoding):
    try:
        with open(path, encoding=encoding, newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return [], []
            rows = [r for r in reader]
    except UnicodeDecodeError as e:
        raise Unreadable(
            "%s を %s で読めない（%s）。受領データに別の符号化が混ざっている"
            "疑いがある。--encoding で指定し直す" % (path, encoding, e.reason))
    header = [h.strip().upper() for h in header]
    width = len(header)

    dupes = sorted({h for h in header if header.count(h) > 1})
    if dupes:
        raise Unreadable(
            "%s のヘッダに同じ列名が複数ある: %s。どちらの列を読むかが決まらない"
            % (path, "・".join(dupes)))

    # 列数の合わない行は直さずに拒否する。余りを捨てると自由記述の中のカンマで
    # 列がずれた受領物を、切り詰めた別の表として検査してしまう。足りない分を空欄で
    # 埋めると、落ちた列が「値なし」として集計に入る。どちらも受領物の構造不良を
    # 検出せずに通す。受領仕様が末尾の欠落を許すときだけ --allow-ragged で明示する。
    bad = [(i, len(r)) for i, r in enumerate(rows, start=2) if len(r) != width]
    if bad and not ALLOW_RAGGED:
        i, n = bad[0]
        raise Unreadable(
            "%s の列数が合わない（%d 行）。最初は %d 行目で、ヘッダ %d 列に対して "
            "%d 列。引用符の欠落で自由記述のカンマが列区切りになっていないかを見る。"
            "受領仕様が末尾の欠落を許すなら --allow-ragged を付ける"
            % (path, len(bad), i, width, n))

    fixed = []
    for r in rows:
        if len(r) < width:
            r = r + [""] * (width - len(r))
        elif len(r) > width:
            r = r[:width]
        fixed.append(["" if v is None else str(v) for v in r])
    if bad:
        RAGGED_FIXED.append((path, len(bad)))
    return header, fixed


def read_dataset_json(path):
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    cols = spec.get("columns") or spec.get("items") or []
    header = [(c.get("name") or c.get("itemOID") or "").upper() for c in cols]
    rows = []
    for r in spec.get("rows", []):
        rows.append(["" if v is None else str(v) for v in r])
    return header, rows


def read_xpt(path):
    """XPT は外部パッケージが要る。入っていない端末では検査を走らせない。"""
    try:
        import pyreadstat
    except ImportError:
        raise Unreadable(
            "XPT を読むには pyreadstat が要る（python -m pip install pyreadstat）。"
            "入っていないので %s は検査していない" % path)
    df, _ = pyreadstat.read_xport(path)
    header = [c.upper() for c in df.columns]
    rows = [["" if v is None else str(v) for v in rec]
            for rec in df.itertuples(index=False, name=None)]
    return header, rows


def domain_of(header, rows, path):
    """DOMAIN 列があればそれを、無ければファイル名を採る。"""
    if "DOMAIN" in header:
        i = header.index("DOMAIN")
        vals = {r[i].strip().upper() for r in rows if r[i].strip()}
        if len(vals) == 1:
            return vals.pop()
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[^A-Za-z0-9]", "", stem).upper()


def load_dir(path, encoding, manifest=None):
    """ディレクトリ直下のデータを読む。読めなければ Unreadable を投げる。

    manifest を渡したときは、そこに並んだファイルだけを読む。並んでいないファイルが
    直下にあれば止める。写し損ないと宣言の陳腐化は、どちらも件数では分からない。

    既定で直下だけを見る。手順は受領カットを版別フォルダへ保管し、解析が使う版だけを
    直下へ置く。配下まで辿ると、保管した旧版の同じドメインも一緒に読み、解析が使う版と
    検査が見る版が別になる。配布形式の都合で階層を持つ受領物は --recursive で明示する。
    """
    if not os.path.isdir(path):
        raise Unreadable("ディレクトリがない: %s" % path)

    if manifest:
        files = []
        bad = []
        for name, want in manifest:
            full = os.path.join(path, name)
            if not os.path.isfile(full):
                bad.append("%s が無い" % name)
                continue
            if want:
                got = sha256_of(full)
                if got != want:
                    bad.append("%s が宣言と違う（宣言 %s… / 実物 %s…）"
                               % (name, want[:12], got[:12]))
            files.append(full)
        listed = {n for n, _ in manifest}
        for n in sorted(os.listdir(path)):
            ext = os.path.splitext(n)[1].lower()
            if (os.path.isfile(os.path.join(path, n))
                    and ext in (".csv", ".json", ".xpt") and n not in listed):
                bad.append("%s は受領マニフェストに無い" % n)
        if bad:
            raise Unreadable(
                "受領マニフェストと %s の中身が合わない:\n  %s"
                % (path, "\n  ".join(bad)))
        return read_files(files, encoding, path)

    files = []
    if RECURSIVE:
        for root, _dirs, names in os.walk(path):
            for n in sorted(names):
                ext = os.path.splitext(n)[1].lower()
                if ext in (".csv", ".json", ".xpt"):
                    files.append(os.path.join(root, n))
    else:
        for n in sorted(os.listdir(path)):
            full = os.path.join(path, n)
            ext = os.path.splitext(n)[1].lower()
            if os.path.isfile(full) and ext in (".csv", ".json", ".xpt"):
                files.append(full)
    if not files:
        sub_dirs = [n for n in sorted(os.listdir(path))
                    if os.path.isdir(os.path.join(path, n))]
        hint = ""
        if sub_dirs and not RECURSIVE:
            hint = ("。直下だけを見ている。配下の %s に入っているなら、"
                    "解析が使う版を直下へ置くか --recursive を付ける"
                    % "・".join(sub_dirs[:5]))
        raise Unreadable(
            "%s に CSV・Dataset-JSON・XPT がない。拡張子で探しているので、"
            "別の拡張子で置かれていないかを見る%s" % (path, hint))

    return read_files(files, encoding, path)


def read_files(files, encoding, path):
    datasets = []
    for p in sorted(files):
        ext = os.path.splitext(p)[1].lower()
        if ext == ".csv":
            header, rows = read_csv(p, encoding)
        elif ext == ".json":
            header, rows = read_dataset_json(p)
        else:
            header, rows = read_xpt(p)
        if not header:
            continue
        datasets.append(Dataset(domain_of(header, rows, p), header, rows, p))
    if not datasets:
        raise Unreadable("%s から読めた表が 0 件だった" % path)
    return datasets


def load_manifest(path):
    """受領マニフェスト。現行の入力がどのファイルかを宣言で持つ。

    直下だけを見る規則で旧版の混入は防げるが、写し損ないは防げない。同じ名前の
    古いファイルが1つ残っても件数は合う。宣言に並べた集合と実在を突き合わせる。

    列は file（直下からの相対名）と、任意で sha256。
    """
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        if not rdr.fieldnames or "file" not in rdr.fieldnames:
            raise Unreadable("受領マニフェストに file 列がない: %s" % path)
        for r in rdr:
            name = (r.get("file") or "").strip()
            if name:
                rows.append((name, (r.get("sha256") or "").strip().lower()))
    if not rows:
        raise Unreadable("受領マニフェストが空: %s" % path)
    return rows


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_keys(path):
    """突合のキーの宣言。列は domain と key（; 区切りの変数名）。

    キーを実装の推測に任せると、ドメインごとに何で結んだかが結果から読めない。
    宣言があれば、結べなかったことも宣言との差として出せる。
    """
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        need = ("domain", "key")
        if not rdr.fieldnames or any(c not in rdr.fieldnames for c in need):
            raise Unreadable("キーの宣言に domain・key 列がない: %s" % path)
        for r in rdr:
            dom = (r.get("domain") or "").strip().upper()
            key = [x.strip().upper()
                   for x in (r.get("key") or "").replace(";", ",").split(",")
                   if x.strip()]
            if dom:
                out[dom] = key
    if not out:
        raise Unreadable("キーの宣言が空: %s" % path)
    return out


def by_domain(datasets, path):
    """ドメイン名で引ける形にする。同名が2つあれば止める。

    辞書に詰め直すと後から読んだ方が黙って残る。保管した旧版が混ざったとき、
    解析が使う版と検査が見る版が別になったことに気づけない。
    """
    out = {}
    for d in datasets:
        if d.domain in out:
            raise Unreadable(
                "%s に同じドメイン %s の表が 2 つある（%s と %s）。どちらを使うかが"
                "決まらない。解析が使う版だけを置く"
                % (path, d.domain, out[d.domain].source, d.source))
        out[d.domain] = d
    return out


def load_expect(path):
    """宣言値の CSV を読む。列は domain,variable,value（value は空でよい）。"""
    if not os.path.isfile(path):
        raise Unreadable("宣言値のファイルがない: %s" % path)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise Unreadable("宣言値のファイルが空: %s" % path)
    head = [h.strip().lower() for h in rows[0]]
    body = rows[1:] if head[:2] == ["domain", "variable"] else rows
    expect = collections.defaultdict(set)
    for r in body:
        if len(r) < 2 or not r[0].strip():
            continue
        dom = r[0].strip().upper()
        var = r[1].strip().upper()
        val = r[2].strip() if len(r) > 2 else ""
        expect[(dom, var)].add(val)
    if not expect:
        raise Unreadable("宣言値が 1 件も読めなかった: %s" % path)
    return expect


# ------------------------------------------------------------------ 規則


def normalize(v):
    return unicodedata.normalize("NFKC", v).strip().casefold()


def rule_expect(datasets, expect):
    """D01・D02 宣言が名指しする値と実データを突き合わせる。"""
    out = []
    if not expect:
        return out
    by_domain = {d.domain: d for d in datasets}
    for (dom, var), values in sorted(expect.items()):
        ds = by_domain.get(dom)
        if ds is None:
            out.append(Finding("D01", "error", dom, var,
                               "宣言が名指しするドメインが実データにない"))
            continue
        if var not in ds.columns:
            out.append(Finding("D01", "error", dom, var,
                               "宣言が名指しする変数が実データにない"))
            continue
        declared = {v for v in values if v}
        if not declared:
            continue
        actual = collections.Counter(v for v in ds.column(var) if v != "")
        for v in sorted(declared):
            if v not in actual:
                near = [a for a in actual if normalize(a) == normalize(v)]
                hint = ("実データの綴りは %s" % "・".join(sorted(near))
                        if near else "近い綴りも無い")
                out.append(Finding(
                    "D01", "error", dom, var,
                    "宣言が名指しする値 '%s' がその綴りで存在しない（%s）。"
                    "条件は該当 0 件で通る" % (v, hint)))
        extra = sorted(a for a in actual if a not in declared)
        for v in extra:
            out.append(Finding(
                "D02", "warning", dom, var,
                "宣言に無い値 '%s' が %d 件ある" % (v, actual[v])))
    return out


def rule_whitespace(datasets):
    """D03 値の前後に空白・制御文字がある。照合が静かに外れる。"""
    out = []
    for ds in datasets:
        for i, var in enumerate(ds.columns):
            bad = collections.Counter()
            for r in ds.rows:
                v = r[i]
                if not v:
                    continue
                if v != v.strip() or v.strip("　") != v.strip():
                    bad["前後の空白"] += 1
                elif RE_CONTROL.search(v):
                    bad["制御文字"] += 1
            for kind, n in sorted(bad.items()):
                out.append(Finding("D03", "error", ds.domain, var,
                                   "%sを含む値が %d 件ある" % (kind, n)))
    return out


def rule_spelling(datasets, max_levels):
    """D04 正規化すると一致する値が複数の綴りで存在する。"""
    out = []
    for ds in datasets:
        for i, var in enumerate(ds.columns):
            groups = collections.defaultdict(collections.Counter)
            for r in ds.rows:
                v = r[i]
                if v:
                    groups[normalize(v)][v] += 1
            if len(groups) > max_levels * 20:
                continue
            for key, forms in sorted(groups.items()):
                if len(forms) > 1:
                    shown = "・".join("'%s'(%d)" % (f, n)
                                      for f, n in sorted(forms.items()))
                    out.append(Finding(
                        "D04", "warning", ds.domain, var,
                        "同じ値が複数の綴りで入っている: %s" % shown))
    return out


def rule_undetermined(datasets):
    """D05 空白・判定不能を表す値の混在を数える。"""
    out = []
    for ds in datasets:
        n = len(ds.rows)
        if n == 0:
            continue
        for i, var in enumerate(ds.columns):
            hits = collections.Counter()
            for r in ds.rows:
                v = r[i].strip()
                if v and v.upper() in UNDETERMINED:
                    hits[v] += 1
            for v, c in sorted(hits.items()):
                out.append(Finding(
                    "D05", "info", ds.domain, var,
                    "判定不能を表す値 '%s' が %d 件（%.1f%%）ある" %
                    (v, c, 100.0 * c / n)))
    return out


def rule_all_blank(datasets):
    """D06 全件が空の変数。宣言はあるが値が無い。"""
    out = []
    for ds in datasets:
        if not ds.rows:
            continue
        for i, var in enumerate(ds.columns):
            if all(r[i].strip() == "" for r in ds.rows):
                out.append(Finding("D06", "info", ds.domain, var,
                                   "全 %d 件が空" % len(ds.rows)))
    return out


def rule_dates(datasets):
    """D07 日付変数が ISO 8601 で読めない。"""
    out = []
    for ds in datasets:
        for i, var in enumerate(ds.columns):
            if not (var.endswith("DTC") or var.endswith("DT")):
                continue
            bad = collections.Counter()
            for r in ds.rows:
                v = r[i].strip()
                if not v:
                    continue
                if not RE_ISO8601.match(v) and not RE_ISO8601_PARTIAL.match(v):
                    bad[v] += 1
            if bad:
                shown = "・".join("'%s'(%d)" % (v, n)
                                 for v, n in sorted(bad.items())[:5])
                out.append(Finding(
                    "D07", "error", ds.domain, var,
                    "ISO 8601 で読めない値が %d 種・%d 件ある: %s" %
                    (len(bad), sum(bad.values()), shown)))
    return out


def rule_duplicate_key(datasets):
    """D08 被験者内で識別子が重複する。"""
    out = []
    for ds in datasets:
        subj = ds.subject_key()
        seq = ds.suffix("SEQ")
        if not subj or not seq:
            continue
        si, qi = ds.columns.index(subj), ds.columns.index(seq)
        counts = collections.Counter((r[si], r[qi]) for r in ds.rows)
        dup = [k for k, n in counts.items() if n > 1 and k[1] != ""]
        if dup:
            out.append(Finding(
                "D08", "error", ds.domain, seq,
                "被験者内で %s が重複する組が %d 件ある" % (seq, len(dup))))
    return out


def rule_subject_sets(datasets):
    """D09 被験者の集合がドメイン間で食い違う。導出の元が無い症例を拾う。"""
    out = []
    ref = None
    for ds in datasets:
        if ds.domain == "DM":
            ref = ds
            break
    if ref is None:
        return out
    subj = ref.subject_key()
    if not subj:
        return out
    known = set(ref.column(subj))
    for ds in datasets:
        if ds is ref:
            continue
        k = ds.subject_key()
        if not k:
            continue
        here = {v for v in ds.column(k) if v}
        unknown = here - known
        if unknown:
            out.append(Finding(
                "D09", "warning", ds.domain, k,
                "DM に無い被験者が %d 名分のレコードで現れる" % len(unknown)))
        missing = known - here
        if missing and here:
            out.append(Finding(
                "D09", "warning", ds.domain, k,
                "DM に在って本ドメインに 1 件も現れない被験者が %d 名いる。"
                "導出の元が無い症例になりうる" % len(missing)))
    return out


def rule_occur_dates(datasets):
    """D10 発生の有無と日付が整合しない（4.5 のフラグと日付の不整合）。"""
    out = []
    for ds in datasets:
        occur = ds.suffix("OCCUR")
        if not occur:
            continue
        date = ds.suffix("STDTC") or ds.suffix("DTC")
        if not date:
            continue
        oi, di = ds.columns.index(occur), ds.columns.index(date)
        n_no_but_date = n_yes_but_blank = 0
        for r in ds.rows:
            o, d = r[oi].strip().upper(), r[di].strip()
            if o == "N" and d:
                n_no_but_date += 1
            elif o == "Y" and not d:
                n_yes_but_blank += 1
        if n_no_but_date:
            out.append(Finding(
                "D10", "warning", ds.domain, occur,
                "発生なしなのに %s に値がある行が %d 件ある" %
                (date, n_no_but_date)))
        if n_yes_but_blank:
            out.append(Finding(
                "D10", "warning", ds.domain, occur,
                "発生ありなのに %s が空の行が %d 件ある" %
                (date, n_yes_but_blank)))
    return out


# ------------------------------------------------------------------ 差分


def diff_key(ds):
    """突合のキーを選ぶ。

    --SEQ は固定時に振り直されるので使わない（4.4）。判定を表す変数も使わない。
    キーに入れると、その値が変わった行が別の行になり、追加1・削除1として数えられて、
    判定の変化として出てこない。DSTERM のようにキー候補と判定変数の両方に当たる
    変数がこれに当たる。変わりうる値を突合の軸にしない。
    """
    key = []
    subj = ds.subject_key()
    if subj:
        key.append(subj)
    for suf in KEY_SUFFIX_CANDIDATES:
        if suf in DECISION_SUFFIXES:
            continue
        name = ds.suffix(suf)
        if name and name not in key:
            key.append(name)
    for name in KEY_PLAIN_CANDIDATES:
        if name in ds.columns and name not in key:
            key.append(name)
    return key


def keyed_rows(ds, key):
    idx = [ds.columns.index(k) for k in key]
    seen = collections.Counter()
    out = {}
    for r in ds.rows:
        k = tuple(r[i] for i in idx)
        seen[k] += 1
        out[k + (seen[k],)] = r
    return out, seen


def is_decision(ds, var):
    if not var.startswith(ds.domain):
        return var in ("DSTERM", "DSDECOD")
    return var[len(ds.domain):] in DECISION_SUFFIXES


def run_diff(before, after, encoding, max_shown,
             man_before=None, man_after=None, keys=None):
    b = by_domain(load_dir(before, encoding, man_before), before)
    a = by_domain(load_dir(after, encoding, man_after), after)
    lines = []
    lines.append("固定前: %s（ドメイン %d・レコード %d）" %
                 (before, len(b), sum(len(d.rows) for d in b.values())))
    lines.append("固定後: %s（ドメイン %d・レコード %d）" %
                 (after, len(a), sum(len(d.rows) for d in a.values())))
    lines.append("")

    only_b = sorted(set(b) - set(a))
    only_a = sorted(set(a) - set(b))
    if only_b:
        lines.append("固定前にしかないドメイン: %s" % "・".join(only_b))
    if only_a:
        lines.append("固定後にしかないドメイン: %s" % "・".join(only_a))
    if only_b or only_a:
        lines.append("")

    changed_decision = []
    # 判定への影響を確かめられなかったもの。0 件でないなら「変化なし」とは返せない
    unverified = []
    for dom in only_b:
        unverified.append("%s  固定後に無い。判定への影響は未評価" % dom)
    for dom in only_a:
        unverified.append("%s  固定前に無い。判定への影響は未評価" % dom)
    for dom in sorted(set(a) & set(b)):
        da, db = a[dom], b[dom]
        if keys is not None:
            if dom not in keys:
                lines.append("## %s  キーの宣言が無いので件数だけ出す"
                             "（固定前 %d → 固定後 %d）" %
                             (dom, len(db.rows), len(da.rows)))
                unverified.append("%s  突合のキーが宣言されていない。行ごとの照合を"
                                  "していない" % dom)
                continue
            key = list(keys[dom])
            lack = [k for k in key if k not in db.columns or k not in da.columns]
            if lack:
                lines.append("## %s  宣言されたキーの変数が無い: %s" %
                             (dom, "・".join(lack)))
                unverified.append("%s  宣言されたキー %s がデータに無い。照合不能"
                                  % (dom, "+".join(key)))
                continue
        else:
            key = diff_key(db)
            key = [k for k in key if k in da.columns]
        if not key:
            lines.append("## %s  突合のキーが決まらないので件数だけ出す"
                         "（固定前 %d → 固定後 %d）" %
                         (dom, len(db.rows), len(da.rows)))
            unverified.append("%s  突合のキーが決まらない。行ごとの照合ができていない"
                              % dom)
            continue
        ra, seen_a = keyed_rows(da, key)
        rb, seen_b = keyed_rows(db, key)

        added = sorted(set(ra) - set(rb))
        removed = sorted(set(rb) - set(ra))
        common = sorted(set(ra) & set(rb))

        cols = [c for c in db.columns
                if c in da.columns
                and not any(c.endswith(s) for s in KEY_EXCLUDED_SUFFIXES)]
        # 片側にしかない列は値の比較に入らない。判定を表す列なら未評価として残す
        for c in sorted(set(db.columns) - set(da.columns)):
            if is_decision(db, c):
                unverified.append("%s.%s  固定後に列が無い。判定への影響は未評価"
                                  % (dom, c))
        for c in sorted(set(da.columns) - set(db.columns)):
            if is_decision(da, c):
                unverified.append("%s.%s  固定前に列が無い。判定への影響は未評価"
                                  % (dom, c))
        per_var = collections.Counter()
        transitions = collections.defaultdict(collections.Counter)
        changed_rows = set()
        bi = {c: db.columns.index(c) for c in cols}
        ai = {c: da.columns.index(c) for c in cols}
        for k in common:
            for c in cols:
                vb, va = rb[k][bi[c]], ra[k][ai[c]]
                if vb != va:
                    per_var[c] += 1
                    changed_rows.add(k)
                    if is_decision(db, c):
                        transitions[c][(vb, va)] += 1

        if not (added or removed or per_var):
            continue
        lines.append("## %s（キー: %s）" % (dom, "+".join(key)))
        lines.append("  レコード 固定前 %d → 固定後 %d（追加 %d・削除 %d・"
                     "内容変更 %d）" % (len(db.rows), len(da.rows), len(added),
                                          len(removed), len(changed_rows)))
        dupes = sum(1 for v in list(seen_a.values()) + list(seen_b.values())
                    if v > 1)
        if dupes:
            lines.append("  キーが一意でない組が %d 件ある。出現順で対応付けた"
                         "ので、内容変更の件数は上限値として読む" % dupes)
            unverified.append("%s  キーが一意でない組が %d 件。行の対応が確定して"
                              "いない" % (dom, dupes))
        if added or removed:
            unverified.append("%s  行が増減した（追加 %d・削除 %d）。判定への影響は"
                              "未評価" % (dom, len(added), len(removed)))
        for c, n in sorted(per_var.items(), key=lambda x: (-x[1], x[0]))[:max_shown]:
            mark = " ← 判定を表す変数" if is_decision(db, c) else ""
            lines.append("  %s: %d 件変更%s" % (c, n, mark))
        for c in sorted(transitions):
            for (vb, va), n in sorted(transitions[c].items()):
                changed_decision.append("%s.%s  '%s' → '%s'  %d 件" %
                                        (dom, c, vb, va, n))
        lines.append("")

    lines.append("## 判定を表す変数の変化")
    if changed_decision:
        lines.extend("  " + s for s in changed_decision)
    else:
        lines.append("  なし。")

    lines.append("")
    lines.append("## 判定への影響を確かめられなかったもの")
    if unverified:
        lines.extend("  " + s for s in unverified)
    else:
        lines.append("  なし。")

    if changed_decision or unverified:
        lines.append("")
        lines.append("  イベント判定が変わりうる。電子症例報告書のクエリ記録を"
                     "取り寄せて経緯を確認する（data-verification.md 4.4）。")
        lines.append("  未評価が残っている間は「変化なし」とは読まない。")
    return lines, bool(changed_decision or unverified)


# ---------------------------------------------------------------- 出力


def run_inventory(path, encoding, max_levels, manifest=None):
    datasets = load_dir(path, encoding, manifest)
    lines = ["対象: %s（ドメイン %d・レコード %d・変数 %d）" %
             (path, len(datasets), sum(len(d.rows) for d in datasets),
              sum(len(d.columns) for d in datasets)), ""]
    for ds in datasets:
        subj = ds.subject_key()
        n_subj = len(set(ds.column(subj))) if subj else 0
        lines.append("## %s  レコード %d・変数 %d・被験者 %d（%s）" %
                     (ds.domain, len(ds.rows), len(ds.columns), n_subj,
                      os.path.basename(ds.source)))
        for i, var in enumerate(ds.columns):
            vals = [r[i] for r in ds.rows]
            nonblank = [v for v in vals if v.strip() != ""]
            width = max((len(v) for v in nonblank), default=0)
            uniq = collections.Counter(nonblank)
            head = "  %2d %-12s 長 %-3d 空 %d/%d 水準 %d" % (
                i + 1, var, width, len(vals) - len(nonblank), len(vals),
                len(uniq))
            if 0 < len(uniq) <= max_levels:
                dist = "・".join("%s(%d)" % (v, n)
                                for v, n in sorted(uniq.items()))
                lines.append(head + "  " + dist)
            elif uniq:
                top = "・".join("%s(%d)" % (v, n)
                               for v, n in uniq.most_common(3))
                lines.append(head + "  先頭 " + top)
            else:
                lines.append(head)
        lines.append("")
    lines.append("実値の一覧である。統計解析計画書が名指しする値がこの一覧に"
                 "その綴りで在るかを、人が突き合わせる（4.1）。")
    return lines


def run_audit(path, encoding, expect_path, max_levels, manifest=None):
    datasets = load_dir(path, encoding, manifest)
    expect = load_expect(expect_path) if expect_path else {}

    findings = []
    findings += rule_expect(datasets, expect)
    findings += rule_whitespace(datasets)
    findings += rule_spelling(datasets, max_levels)
    findings += rule_undetermined(datasets)
    findings += rule_all_blank(datasets)
    findings += rule_dates(datasets)
    findings += rule_duplicate_key(datasets)
    findings += rule_subject_sets(datasets)
    findings += rule_occur_dates(datasets)
    return datasets, expect, findings


def main():
    p = argparse.ArgumentParser(description="固定データの機械検査")
    p.add_argument("mode", choices=("inventory", "audit", "diff"))
    p.add_argument("path", help="データのディレクトリ（diff では固定前）")
    p.add_argument("path2", nargs="?", help="diff のときの固定後のディレクトリ")
    p.add_argument("--expect", help="宣言値の CSV（domain,variable,value）")
    p.add_argument("--encoding", default="utf-8-sig",
                   help="CSV の文字符号化（既定 utf-8-sig）")
    p.add_argument("--max-levels", type=int, default=DEFAULT_MAX_LEVELS,
                   help="値の分布を出す水準数の上限（既定 %d）" % DEFAULT_MAX_LEVELS)
    p.add_argument("--severity", choices=SEVERITIES, default="info",
                   help="この深刻度までを出す（既定 info＝全部）")
    p.add_argument("--format", choices=("text", "tsv"), default="text")
    p.add_argument("--allow-ragged", action="store_true",
                   help="列数の合わない行を拒否せず、末尾を埋めるか切り詰める"
                        "（受領仕様が末尾の欠落を許す場合だけ）")
    p.add_argument("--recursive", action="store_true",
                   help="ディレクトリの配下まで辿る（既定は直下だけ）")
    p.add_argument("--manifest",
                   help="受領マニフェスト（列 file・任意で sha256）。"
                        "並んだファイルだけを読み、並んでいないものが直下にあれば止める")
    p.add_argument("--manifest2",
                   help="diff の固定後に当てる受領マニフェスト")
    p.add_argument("--keys",
                   help="突合のキーの宣言（列 domain・key）。"
                        "宣言の無いドメインは照合せず未評価として残す")
    a = p.parse_args()

    global ALLOW_RAGGED, RECURSIVE
    ALLOW_RAGGED = a.allow_ragged
    RECURSIVE = a.recursive

    try:
        man = load_manifest(a.manifest) if a.manifest else None
        man2 = load_manifest(a.manifest2) if a.manifest2 else None
        keys = load_keys(a.keys) if a.keys else None

        if a.mode == "inventory":
            for line in run_inventory(a.path, a.encoding, a.max_levels, man):
                print(line)
            return 0

        if a.mode == "diff":
            if not a.path2:
                print("ERROR: diff には固定前と固定後の 2 つを渡す")
                return 2
            lines, decided = run_diff(a.path, a.path2, a.encoding,
                                      a.max_levels, man, man2, keys)
            for line in lines:
                print(line)
            return 1 if decided else 0

        datasets, expect, findings = run_audit(
            a.path, a.encoding, a.expect, a.max_levels, man)
    except Unreadable as e:
        print("検証できなかった: %s" % e)
        return 2

    limit = SEVERITY_ORDER[a.severity]
    findings = [f for f in findings if SEVERITY_ORDER[f.severity] <= limit]
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule,
                                 f.domain, f.variable))

    if a.format == "tsv":
        print("\t".join(["深刻度", "規則", "ドメイン", "変数", "指摘内容"]))
        for f in findings:
            print("\t".join([f.severity, f.rule, f.domain, f.variable,
                             f.detail.replace("\t", " ")]))
    else:
        print("対象: %s（ドメイン %d・レコード %d・変数 %d）" %
              (a.path, len(datasets), sum(len(d.rows) for d in datasets),
               sum(len(d.columns) for d in datasets)))
        print("照合した宣言: %d 件%s" %
              (len(expect), "" if expect else "（--expect を渡していない。"
                                              "D01・D02 は走っていない）"))
        counts = collections.Counter(f.severity for f in findings)
        print("検出: error %d / warning %d / info %d" %
              (counts["error"], counts["warning"], counts["info"]))
        print()
        current = None
        for f in findings:
            key = (f.severity, f.rule)
            if key != current:
                current = key
                n = sum(1 for x in findings
                        if (x.severity, x.rule) == key)
                print("## [%s] %s（%d件）" % (f.severity.upper(), f.rule, n))
            print("- %s.%s  %s" % (f.domain, f.variable, f.detail))
        if not findings:
            print("指摘なし。実値の形と内部整合だけを見ている。"
                  "データそのものの正しさは原資料との照合でしか分からない。")

    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
