# check-traceability.py
#
# 生成した traceability.html をブラウザで実際に開いて操作し、壊れていないか確かめる。
# 目視だけでは JS の例外に気付けない（画面は出るが以後クリックが効かない状態になる）ため、
# 索引を触ったら必ず回す。
#
#   python scripts/check-traceability.py                 ... Box の output/traceability.html
#   python scripts/check-traceability.py <path.html>     ... 任意のファイル
#
# 要 playwright（`pip install playwright && playwright install chromium`）。入っていない端末では
# その旨を出して終わる（索引の生成自体は playwright に依存しない）。
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('playwright が無いため確認を飛ばす（pip install playwright）')
    sys.exit(0)

HTML = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else \
    os.path.join(boxpath.trial_dir(), 'output', 'traceability.html')
if not os.path.exists(HTML):
    sys.exit(f'{HTML} が無い。先に build-traceability.py を回す。')

errs, fails = [], []


def want(cond, msg):
    print(('  OK   ' if cond else '  NG   ') + msg)
    if not cond:
        fails.append(msg)


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width': 1100, 'height': 900})
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.on('console', lambda m: errs.append(f'console.{m.type}: {m.text}')
          if m.type == 'error' else None)
    pg.goto('file://' + HTML)
    pg.wait_for_timeout(900)

    def rows():
        return [' / '.join(x for x in r.inner_text().split('\n') if x.strip())
                for r in pg.query_selector_all('.row')]

    def row_of(label):
        for i, r in enumerate(pg.query_selector_all('.row')):
            if r.query_selector('.lbl').inner_text() == label:
                return i, r
        return None, None


    def spec_link(sel, what):
        """詳細の中の仕様書リンクが、同梱の HTML の実在する節を指しているか"""
        a_ = pg.query_selector(sel + ' a[href*="spec"], ' + sel + ' a[href*="derivation"]')
        want(bool(a_), f'{what}の詳細の仕様書がリンクになる')
        if not a_:
            return
        href = a_.get_attribute('href')
        f_, _, anc = href.partition('#')
        fp = os.path.join(os.path.dirname(HTML), f_)
        want(os.path.exists(fp), f'仕様書 HTML が実在する（{f_}）')
        if anc and os.path.exists(fp):
            with open(fp, encoding='utf-8') as fh:
                want(f'id="{anc}"' in fh.read(), f'節の錨が実在する（#{anc}）')

    print(f'{HTML}（{os.path.getsize(HTML):,} バイト）')
    print('起動')
    want(len(pg.query_selector_all('.row')) == 7, '段が7つ並ぶ')
    want(all('選ぶ' in r for r in rows()), '最初はどの段も未選択')

    print('入口の導線')
    want(all(bool(pg.query_selector('#ex' + n)) for n in '12345'),
         '例が入口（検索の直下）にある')
    want(pg.evaluate("() => { const e = document.getElementById('ex1');"
                     " return e.getBoundingClientRect().top <"
                     " document.getElementById('chain').getBoundingClientRect().top; }"),
         '例が鎖より上にある')
    wl = pg.query_selector_all('#whole .ext')
    want(len(wl) == 2, '全図表1ページ版の日英ボタンが見出しの隣に出る')
    for a_ in wl:
        href = a_.get_attribute('href')
        want(os.path.exists(os.path.join(os.path.dirname(HTML), href)),
             f'{a_.inner_text()} のリンク先が実在する（{href}）')

    print('例から一直線に辿る')
    # 4つの例はいずれも CRF の1欄が SDTM の1変数へ1対1で対応するもの（機械的に洗い出した全件）
    # ADaM が1つに決まるのは性別とドナー情報だけで、幹細胞源と糖尿病の治療は ADaM 側が
    # 2候補に分かれる（variable-map が同じ SDTM 変数から2変数を導いている）
    for btn, sd, ad in (('#ex1', 'DM.SEX', 'ADSL.SEX'), ('#ex2', 'PR.PRTRT', ''),
                        ('#ex3', 'PR.PRCAT', 'ADSL.DONOR'), ('#ex4', 'FA.FASCAT', '')):
        pg.click(btn)
        pg.wait_for_timeout(400)
        ch = rows()
        want(sd in ch[3], f'{sd} が入力欄から一意に決まる')
        want(ad in ch[4] if ad else '件から選ぶ' in ch[4],
             f'{sd} の ADaM は' + (f'{ad} に決まる' if ad else '候補から選ばせる'))
        want('An-' in ch[5] or '件から選ぶ' in ch[5], f'{sd} から解析まで届く')
        print('       ' + ' ／ '.join(ch[1:]))

    print('KM の図は解析を経由せず ADaM から直結する')
    # 図は ARD の結果値ではなく ADTTE から曲線を描くため解析IDを持たない。空欄や「たどれない」
    # では追跡が切れて見えるので、経由しないことと直結を画面で言う
    pg.evaluate("() => { location.hash = 'n=out:F_5_4_1'; }")
    pg.wait_for_timeout(400)
    ch = rows()
    want('5.4.1' in ch[6], '図が選ばれる')
    want('経由しない' in ch[5] and 'たどれない' not in ch[5],
         '解析の段は「経由しない」と出る（たどれないと出さない）')
    want('ADTTE' in ch[4], '解析を飛ばして ADaM が埋まる')
    want(bool(pg.query_selector('.row.sel .alt')), '複数候補の段には変える手段が出る')
    want(len(pg.query_selector_all('.row.skip')) == 1 and
         len(pg.query_selector_all('.row.direct')) == 2,
         '迂回1段と直結2段の印が付く')
    for r in ch:
        print('       ' + r)

    print('上流を絞り込んでも下流の選択が残る')
    # 図表を選んだまま上流の段から1つ選ぶ操作。下流を一律に消すと追っていた図表が外れてしまう
    opts = pg.query_selector_all('.drawer[data-l="sdtm"][data-m="pick"] .opt')
    if not opts:
        i, r = row_of('SDTM 変数')
        r.click()
        pg.wait_for_timeout(300)
        opts = pg.query_selector_all('.drawer[data-l="sdtm"][data-m="pick"] .opt')
    want(len(opts) > 1, f'SDTM 変数の候補が出る（{len(opts)} 件）')
    if opts:
        opts[0].click()
        pg.wait_for_timeout(400)
        ch = rows()
        want('5.4.1' in ch[6], '上流を選んでも図表の選択が残る')
        want('ADTTE' in ch[4], '間の ADaM も残る')
        for r in ch:
            print('       ' + r)
    pg.click('#reset')
    pg.wait_for_timeout(300)

    print('検索から入る')
    pg.fill('#q', '白血球数')
    pg.wait_for_timeout(300)
    hits = pg.query_selector_all('.hit')
    want(len(hits) > 0, '検索が当たる')
    hits[0].click()
    pg.wait_for_timeout(400)
    ch = rows()
    want('患者背景' in ch[0], '帳票が自動で埋まる')
    want('LB 001' in ch[2], 'SDTM レコードが自動で埋まる')
    want('LB.LBORRES' in ch[3], '入力欄が入る変数が自動で選ばれる')
    want(len(pg.query_selector_all('.row.sel')) >= 5, '決まる段は自動で埋まる')
    want(bool(pg.query_selector('.row.want')) or all('選ぶ' not in r for r in ch),
         '決まらない段は選ばせる（一覧が開く）')
    for r in ch:
        print('       ' + r)

    print('段を選び直す')
    i, r = row_of('ADaM 変数')
    r.click()
    pg.wait_for_timeout(300)
    opts = pg.query_selector_all('.opt')
    want(len(opts) > 1, 'ADaM の候補が出る')
    tgt = [o for o in opts if o.inner_text().startswith('ADLB.AVAL')]
    (tgt[0] if tgt else opts[0]).click()
    pg.wait_for_timeout(400)
    ch = rows()
    want('患者背景' in ch[0], '選び直しても前の段が残る')
    want('ADLB.AVAL' in ch[4], 'ADaM が選ばれる')
    want('An-' in ch[5] or '件から選ぶ' in ch[5], '解析が埋まるか選択待ちになる')
    for r_ in ch:
        print('       ' + r_)

    print('詳細を開く')
    i, r = row_of('SDTM レコード')
    r.query_selector('.more').click()
    pg.wait_for_timeout(300)
    t = pg.inner_text('.drawer[data-l="rec"]')
    want('固定値' in t, 'レコードの固定値が出る')
    want('値の出どころ' in t and '入り得る値' in t, 'レコードの変数の表が出る')
    want('根拠' in t, 'つながりの根拠が出る')

    print('詳細は開いたまま並ぶ')
    i, r = row_of('SDTM 変数')
    r.query_selector('.more').click()
    pg.wait_for_timeout(300)
    want(bool(pg.query_selector('.drawer[data-l="rec"][data-m="det"]')) and
         bool(pg.query_selector('.drawer[data-l="sdtm"][data-m="det"]')),
         '別の段の詳細を開いても前の詳細が閉じない')
    i, r = row_of('SDTM 変数')                 # 描き直されるので取り直して押す
    r.query_selector('.more').click()          # 押した段だけが閉じる
    pg.wait_for_timeout(300)
    want(not pg.query_selector('.drawer[data-l="sdtm"]') and
         bool(pg.query_selector('.drawer[data-l="rec"][data-m="det"]')),
         'もう一度押すとその段だけ閉じる')

    print('仕様書へ飛ぶ')
    i, r = row_of('ADaM 変数')
    r.query_selector('.more').click()
    pg.wait_for_timeout(300)
    spec_link('.drawer[data-l="adam"]', 'ADaM 変数')

    print('図表から遡る')
    pg.click('#ex5')
    pg.wait_for_timeout(400)
    ch = rows()
    want('5.4.1' in ch[6], '図表が選ばれる')
    want('An-5.4.1' in ch[5], '解析が自動で埋まる')
    i, r = row_of('解析結果(ARD)')
    r.query_selector('.more').click()
    pg.wait_for_timeout(300)
    want(len(pg.query_selector_all('.drawer[data-l="an"] table tr')) > 1,
         '解析の結果値が表で出る')
    spec_link('.drawer[data-l="an"]', '解析結果(ARD)')

    print('入力欄の一覧は aCRF をブロックに1つ置く')
    pg.click('#btabs button[data-l="field"]')
    pg.wait_for_timeout(700)
    want(bool(pg.query_selector('#blist .grp .ext')), 'ブロックの見出しに aCRF が出る')
    want(len(pg.query_selector_all('#blist .opt .ext')) == 0, '欄ごとの aCRF は出ない')
    v = pg.evaluate("""() => {
      // 見出しのリンク先が、そのブロックに並ぶ欄の帳票と一致するか（ブロックは1帳票で閉じる）
      let checked = 0, bad = 0, heads = 0;
      document.getElementById('blist').querySelectorAll('.grp').forEach(gr => {
        heads++;
        const a = gr.querySelector('.ext');
        const href = a ? a.getAttribute('href').split('#')[0] : null;
        for (let e = gr.nextElementSibling; e && !e.classList.contains('grp');
             e = e.nextElementSibling) {
          if (!e.classList.contains('opt')) continue;
          const o = N.get(e.dataset.id).o;
          checked++;
          if (((SH.get(o.sl) || {}).url || null) !== href) bad++;
        }
      });
      return {heads: heads, checked: checked, bad: bad};
    }""")
    want(v['heads'] > 1 and v['checked'] > 1, f"ブロック {v['heads']} に欄 {v['checked']} が並ぶ")
    want(v['bad'] == 0, '見出しの aCRF がブロックの欄の帳票と一致する')
    pg.click('#btabs button[data-l="field"]')
    pg.wait_for_timeout(300)

    print('一覧から選ぶ')
    pg.click('#btabs button[data-l="out"]')
    pg.wait_for_timeout(300)
    opts = pg.query_selector_all('#blist .opt')
    want(len(opts) > 1, '図表の一覧が出る')
    opts[0].click()
    pg.wait_for_timeout(400)
    ch = rows()
    want(len(pg.query_selector_all('.row.sel')) >= 2, '一覧から選ぶと決まる段が埋まる')
    for r_ in ch:
        print('       ' + r_)

    print('最初から選び直す')
    want(pg.is_visible('#bar'), '選んでいる間は操作の帯が出る')
    pg.click('#reset')
    pg.wait_for_timeout(300)
    want(len(pg.query_selector_all('.row.sel')) == 0, '押すとどの段も未選択に戻る')
    want(not pg.is_visible('#bar'), '未選択のときは帯を出さない')
    want('n=' not in pg.evaluate('location.hash'), 'URL のノードの住所も消える')
    want(pg.eval_on_selector('#q', 'e => e.value') == '', '検索欄も空に戻る')
    want(not pg.is_visible('#blist'), '開いていた一覧も閉じる')

    # つながり具合は画面に出さない（開発側の情報）。ここで測って端末に出す
    print('つながり具合')
    m = pg.evaluate("""() => {
      const reach = (s, M) => { const seen = new Set([s]), st = [s];
        while (st.length) { const c = st.pop(); (M.get(c) || []).forEach(e => {
          if (!seen.has(e.to)) { seen.add(e.to); st.push(e.to); } }); } return seen; };
      const flds = ALL.field.filter(f => N.get(f).o.v);
      const oc = ALL.out.filter(o => [...reach(o, UP)].some(x => lay(x) === 'field')).length;
      const fo = flds.filter(f => [...reach(f, DN)].some(x => lay(x) === 'out')).length;
      const av = ALL.an.filter(a => (UP.get(a) || []).some(e => e.why.indexOf('一致') >= 0)).length;
      return {outs: ALL.out.length, oc: oc, flds: flds.length, fo: fo,
              ans: ALL.an.length, av: av};
    }""")
    pc = lambda a, b_: f'{round(a / b_ * 100)}%' if b_ else '—'
    print(f"       図表 {m['outs']} のうち {m['oc']}（{pc(m['oc'], m['outs'])}）が"
          f" CRF の入力欄まで遡れる")
    print(f"       SDTM へ入る入力欄 {m['flds']} のうち {m['fo']}"
          f"（{pc(m['fo'], m['flds'])}）が図表まで下れる")
    print(f"       解析 {m['ans']} のうち {m['av']}（{pc(m['av'], m['ans'])}）が"
          f"解析対象の変数・値で ADaM と結び付く")
    b.close()

print(f'\nコンソール/ページエラー {len(errs)} 件 / 確認の失敗 {len(fails)} 件')
for e in errs[:20]:
    print('  ', e)
sys.exit(1 if (errs or fails) else 0)
