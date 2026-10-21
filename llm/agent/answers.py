"""도구 결과로 답 문장을 만든다 (로컬 4B 모델이 숫자·이름을 지어내지 않게).

모델은 요청을 파악하고 도구를 고른다. 이번 턴에 부른 도구 흐름으로 답의 종류를 알 수 있으면 여기서 답을 쓰고,
모르면 None (모델 글을 그대로 씀: 되묻기·거절 등). 숫자·이름은 모두 도구 결과에서만 가져온다.
말투는 학습 데이터 템플릿(training/make_data.py)과 같게.

trace: [(도구 이름, 인자, 결과)] 이번 턴에 성공한 호출 순서대로.
"""
import re

FOREIGN = re.compile(r'[^\x00-\x7F가-힣ㄱ-ㆎ·…—–→←×%\s]')
SP_LETTER = {'hp': 'H', 'atk': 'A', 'def': 'B', 'spa': 'C', 'spd': 'D', 'spe': 'S'}
FORMAT_KO = {'singles': '싱글', 'doubles': '더블'}


def josa(word: str, with_batchim: str, without: str) -> str:
    ch = word[-1] if word else ''
    batchim = '가' <= ch <= '힣' and (ord(ch) - 0xAC00) % 28 != 0
    return word + (with_batchim if batchim else without)


def sp_text(sp: dict) -> str:
    return ' '.join(f'{SP_LETTER[k]}{v}' for k, v in (sp or {}).items() if v and k in SP_LETTER)


def role_text(roles: list[str]) -> str:
    return ', '.join(roles).replace(' (', '·').replace(')', '') or '확인 필요'


def team_ref(title: str) -> str:
    title = (title or '').strip()
    return f"상위 파티 '{title}'" if title and not FOREIGN.search(title) else '상위 파티'


def source_label(source: str) -> str:
    return source.replace(' 샘플', ' 공개 샘플') if source.endswith('샘플') else source + ' 샘플'


def key(s: dict) -> tuple:
    return s.get('pokemon'), s.get('item') or ''


def names_from(trace) -> dict:
    """(포켓몬, 도구) → "한글이름 @ 한글도구" (search_samples의 readable, get_team의 name 앞부분)."""
    out = {}
    for name, _, res in trace:
        rows = []
        if name == 'search_samples' and isinstance(res, dict):
            rows = [(r['sample'], r['readable']) for r in res.get('samples', [])]
        elif name == 'get_team' and isinstance(res, dict):
            rows = [(m['sample'], m['name']) for m in res.get('members', [])]
        for s, line in rows:
            out[key(s)] = line.split(' / ')[0]
    return out


def last(trace, name, cond=lambda a, r: True):
    return next(((a, r) for n, a, r in reversed(trace) if n == name and cond(a, r)), None)


def weak_sorted(s: dict) -> list[tuple[str, list]]:
    return sorted(s['weak_types_2plus'].items(), key=lambda kv: -len(kv[1]))      # 많이 겹치는 약점부터


def weak_lines(s: dict) -> str:
    return '\n'.join(f"- {t} {len(ms)}마리: {'·'.join(ms)} / "
                     + (f"받아 줄 멤버: {'·'.join(s['weak_cover'][t])}" if s['weak_cover'].get(t) else '받아 줄 멤버 없음')
                     for t, ms in weak_sorted(s))


def roles_line(summary: dict) -> str:
    text = '구성: ' + '·'.join(f'{k} {v}' for k, v in summary['roles'].items())
    if summary.get('mega_pokemon'):
        text += f" / 메가진화 포켓몬 {summary['mega_pokemon']}마리"
    return text


def warnings_line(check: dict) -> str:
    w = [x for x in check.get('warnings', []) if not x.startswith('약점 3마리 이상')]
    return ('\n주의: ' + '; '.join(w)) if w else ''


def full_check(trace, members=None):
    """후보 비교가 아닌 check_party 결과 (members를 주면 같은 멤버로 점검한 것)."""
    want = sorted(map(key, members)) if members else None
    found = last(trace, 'check_party', lambda a, r: isinstance(r, dict) and 'summary' in r
                 and (want is None or sorted(map(key, a.get('members', []))) == want))
    return found and found[1]


def sample_answer(trace, sample) -> str | None:
    hit = None
    for n, a, r in trace:
        if n == 'search_samples' and isinstance(r, dict):
            for row in r.get('samples', []):
                if key(row['sample']) == key(sample) and row['sample'].get('moves') == sample.get('moves'):
                    hit = (a, r, row)
    if not hit:
        return None
    a, r, row = hit
    short = row['readable'].split(' / ')[0]
    shapes = r.get('shapes') or {}
    shape = (row['roles'] or [''])[0].split(' (')[0]
    text = (f"{short} ({sp_text(row['sample']['sp'])}) 추천 (화면에 띄움).\n"
            f"{source_label(row['source'])}이고, SP·기술 기준 역할은 {josa(role_text(row['roles']), '이에요', '예요')}.")
    if shapes.get(shape) and shapes.get('total'):
        text += f"\n{short.split(' @ ')[0]} 샘플 {shapes['total']}개 중 {shape}형이 {shapes[shape]}개예요."
    return text + '\n공개 샘플이라는 근거는 있지만, 다른 육성형보다 강하다고 단정할 수는 없어요.'


def party_answer(trace, members, compare: bool = True, lead: str | None = None) -> str:
    names = names_from(trace)
    check = full_check(trace, members)
    sp = {m['pokemon']: m['sp'] for m in (check or {}).get('members', [])}
    # 검색 결과에 없는 멤버(화면에 원래 있던 육성형)는 check_party가 준 한글 이름으로
    ko = {m['pokemon']: m['name_ko'] for n, _, r in trace if n == 'check_party' and isinstance(r, dict)
          for m in r.get('members', [])}
    lines = '\n'.join(f"- {names.get(key(m)) or ko.get(m['pokemon']) or m['pokemon']} "
                      f"({sp.get(m['pokemon']) or sp_text(m.get('sp'))})" for m in members)
    team = last(trace, 'get_team')
    lead = lead or (f"{team_ref(team[1].get('title'))}를 바탕으로 짰어요 (화면에 띄움)." if team
                    else '추천 파티를 화면에 띄웠어요.')
    cmp = last(trace, 'check_party', lambda a, r: isinstance(r, dict) and 'candidates' in r)
    extra = ''
    if cmp and not team and compare:
        rows = []
        for c in cmp[1]['candidates']:
            pros = f"장점: {', '.join(c['covers'])} 받아 줌" if c['covers'] else ''
            cons = f"단점: {', '.join(w.split(' ')[0] for w in c['new_weak'])} 약점 늘어남" if c['new_weak'] else ''
            rows.append(f"- {c['name_ko']} ({role_text(c['roles'])})" + (f"\n  {' / '.join(x for x in (pros, cons) if x)}"
                                                                       if pros or cons else ''))
        extra = '\n\n비교한 후보:\n' + '\n'.join(rows)
    tail = ('\n\n' + roles_line(check['summary']) + warnings_line(check)) if check else ''
    return f"{lead}\n{lines}{extra}{tail}"


WEATHER = {'rain': ('비', '불꽃'), 'sun': ('쾌청', '물')}      # 날씨 → (이름, 대미지가 반감되는 타입)


def top_weak(s: dict, weather: str | None = None) -> tuple[str, list] | None:
    """가장 많이 겹치는 약점 (날씨로 반감되는 타입은 빼고)."""
    halved = WEATHER.get(weather, (None, None))[1]
    return next(((t, ms) for t, ms in weak_sorted(s) if t != halved), None)


def weakness_answer(check: dict, weather: str | None = None, plan: str = '') -> str:
    """plan: 추천 수정 방안 (받아 줄 후보·바꿀 멤버, intents.counter_plan). 없으면 일반 안내."""
    s = check['summary']
    if not s['weak_types_2plus']:
        return '2마리 이상 겹치는 약점은 없어요. 약점이 멤버마다 흩어져 있어서 상성은 고른 편이에요.' + warnings_line(check)
    text = '2마리 이상 겹치는 약점이에요.\n' + weak_lines(s)
    if weather:
        name, halved = WEATHER[weather]
        if halved in s['weak_types_2plus']:
            text += (f"\n\n{name} 파티라 날씨가 있는 동안은 {halved} 기술 대미지가 반감돼서 {halved} 약점 부담이 줄어요. "
                     f"다만 날씨가 끝나거나 상대가 날씨를 바꾸면 그대로 약점이에요.")
            if not plan and all(len(v) < 3 and s['weak_cover'].get(k) for k, v in s['weak_types_2plus'].items() if k != halved):
                text += ' 나머지 약점은 2마리씩이고 받아 줄 멤버가 있어서 크게 걱정할 정도는 아니에요.'
    top = top_weak(s, weather)
    if top and len(top[1]) >= 3 or plan:
        t, ms = top or (None, [])
        if t and not plan:
            text += (f"\n\n{t} 약점이 {len(ms)}마리로 가장 많아요. {t} 공격을 받아 줄 포켓몬을 넣거나 "
                     f"{'·'.join(ms)} 중 한 마리를 바꾸는 걸 추천해요.")
        text += plan
    return text + warnings_line(check)


def improve_answer(check: dict, weather: str | None, plan: str) -> str:
    """지금 파티에서 고칠 점: 경고(딜러 쏠림·SP 낭비 등) + 겹치는 약점 + 추천 수정 방안."""
    s = check['summary']
    halved = WEATHER.get(weather, (None, None))[1]
    points = [w for w in check.get('warnings', []) if not w.startswith('약점 3마리 이상')]
    for t, ms in weak_sorted(s):
        rain = f" ({WEATHER[weather][0]}로 반감)" if t == halved else ''
        cover = f"받아 줄 멤버: {'·'.join(s['weak_cover'][t])}" if s['weak_cover'].get(t) else '받아 줄 멤버 없음'
        points.append(f"{t} 약점 {len(ms)}마리{rain}: {'·'.join(ms)} / {cover}")
    if not points:
        return '크게 고칠 점은 없어요. 2마리 이상 겹치는 약점이 없고 점검 경고도 없어요.'
    return '지금 파티에서 손볼 만한 점이에요.\n' + '\n'.join(f'- {p}' for p in points) + plan


def weather_threats(th: dict, weather: str | None) -> dict:
    """날씨로 반감되는 타입(비면 불꽃)으로 찌르는 건 빼고 다시 셈."""
    halved = WEATHER.get(weather, (None, None))[1]
    if not halved:
        return th
    out = []
    for x in th.get('threats', []):
        targets = [t for t in x['targets'] if f'({halved} ×' not in t]
        if len(targets) >= th['need_hits']:
            out.append({**x, 'targets': targets, 'hits': len(targets)})
    return {**th, 'threats': sorted(out, key=lambda x: (-x['hits'], x['rank']))}


def threats_answer(th: dict, weather: str | None = None) -> str:
    note = (f"\n{WEATHER[weather][0]} 파티라 {WEATHER[weather][1]} 기술로 찌르는 건 뺐어요 (날씨가 있는 동안 반감)."
            if weather else '')
    if not th.get('threats'):
        return f"픽률 상위 {th['checked_top']}마리 중에 {th['need_hits']}마리 이상을 약점으로 찌르는 포켓몬은 없어요." + note
    lines = []
    for x in th['threats'][:3]:
        types = list(dict.fromkeys(re.findall(r'\((\S+) ×', ' '.join(x['targets']))))
        who = '·'.join(dict.fromkeys(t.split('←')[0] for t in x['targets']))
        lines.append(f"- {x['name_ko']} (픽률 {x['rank']}위) — {'·'.join(types)} 공격으로 {who} {x['hits']}마리")
    return (f"픽률 상위 {th['checked_top']}마리 중 자주 쓰는 기술로 우리 파티 {th['need_hits']}마리 이상을 찌르는, 조심할 포켓몬이에요.\n"
            + '\n'.join(lines) + '\n(기술 사용률 10% 이상만 셈. 특성에 의한 무효·대미지 크기는 반영 안 함)' + note)


def item_answer(info: dict, fmt: str) -> str | None:
    items = ((info.get('usage') or {}).get('item') or [])
    if not items:
        return None
    usage = ' · '.join(f"{x['name_ko']} {x['pct']}%" for x in items[:5])
    return f"{FORMAT_KO.get(fmt, fmt)} {info['name_ko']} 도구 사용률: {usage}\n원하는 도구를 말해 주면 그 도구를 든 샘플을 찾아볼게요."


def render(question: str, trace: list, fmt: str) -> str | None:
    """이번 턴 도구 흐름으로 답을 만든다. 모르는 흐름이면 None."""
    if not trace:
        return None
    shown = last(trace, 'propose_party', lambda a, r: isinstance(r, dict) and r.get('shown'))
    if shown:
        members = shown[0]['members']
        if len(members) == 1:
            return sample_answer(trace, members[0]) or party_answer(trace, members)
        return party_answer(trace, members)
    empty = last(trace, 'search_samples')
    if empty and isinstance(empty[1], list) and empty[1] and 'none' in empty[1][0]:
        n = empty[1][0]['none']                 # 마지막 검색이 비었으면 (지어내지 않고) 없다고
        what = ' '.join(x for x in (n['item'], n['role']) if x)
        return (f"{josa(n['pokemon'], '은', '는')} {what + ' ' if what else ''}공개 샘플이 없어요. "
                '다른 도구나 형태를 말해 주거나, 샘플 제작에서 직접 바꿔 보세요.')
    th = last(trace, 'find_threats')
    if th and isinstance(th[1], dict):
        return threats_answer(th[1])
    check = full_check(trace)
    if check and re.search(r'약점|상성|어때', question):
        return weakness_answer(check)
    info = last(trace, 'get_pokemon')
    if info and isinstance(info[1], dict) and re.search(r'말고|다른|템|도구|아이템', question):
        return item_answer(info[1], fmt)
    return None
