"""메타/파티 데이터 적재: data/raw/ 원본 → usage_stat, usage_detail, team, team_member, pokemon_set.

사용법: python manage.py load_meta
meta 데이터를 전부 지우고 다시 넣는다. load_dex를 먼저 실행해야 한다 (ID 검증에 게임 데이터 사용).
원본은 scripts/collect_samples.py로 수집한다.

- OP.GG 픽률 순위 스냅샷(snapshot_ranking 원본) → rank_snapshot
- OP.GG 인게임 랭크 통계 → usage_stat/detail (M-C, 기술·도구·특성·성격·SP 배분 %, 순위)
- Smogon 월별 통계(chaos) → usage_stat/detail (사용률 %, 동료 포함)
- OP.GG 레플리카 팀 → team/team_member,  OP.GG 샘플 빌드 → pokemon_set
- Showdown 리플레이 → team/team_member (출전·선봉·메가·승패 포함)
- VGCPastes 대회 팀(pokepaste) → team/team_member (SP 포함)
- 리플레이 SP 채우기: 리플레이에는 SP가 공개되지 않음. 6마리 육성(도구·특성·성격·기술)이 모두 같은
  VGCPastes 팀이 있고 그 SP가 한 가지일 때만 그 SP를 넣음 (sp_from에 출처). 애매하면 비워 둠
"""
import re
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.dex.ids import DexIndex, opgg_item_id, opgg_pokemon_id, to_id
from apps.meta import opgg_tier
from apps.dex.models import Item, Learnset
from apps.meta.models import (SP_MAX_PER_STAT, SP_MAX_TOTAL, SP_STATS, PokemonSet, RankSnapshot, Team, TeamMember,
                              UsageDetail, UsageStat)
from apps.meta.pokepaste import parse_paste
from apps.meta.replay import match_species, parse_replay

RAW = Path(settings.DATA_DIR) / 'raw'

SMOGON_FORMATS = {  # Showdown 포맷 → (ruleset, format_key, source)
    'gen9championsvgc2026regmb': ('champions_mb', 'champions_mb_doubles', 'smogon'),
    'gen9championsvgc2026regmbbo3': ('champions_mb', 'champions_mb_doubles', 'smogon_bo3'),
    'gen9championsbssregmb': ('champions_mb', 'champions_mb_singles', 'smogon'),
    'gen9championsvgc2026regmc': ('champions_mc', 'champions_mc_doubles', 'smogon'),
    'gen9championsvgc2026regmcbo3': ('champions_mc', 'champions_mc_doubles', 'smogon_bo3'),
    'gen9championsbssregmc': ('champions_mc', 'champions_mc_singles', 'smogon'),
}
REPLAY_FORMATS = {
    'gen9championsvgc2026regmcbo3': ('champions_mc', 'champions_mc_doubles'),
    'gen9championsvgc2026regmc': ('champions_mc', 'champions_mc_doubles'),
    'gen9championsbssregmc': ('champions_mc', 'champions_mc_singles'),
}
OPGG_RULESET = 'champions_mc'   # OP.GG는 현재 레귤레이션만 제공
OPGG_SP_FIELDS = ('hp', 'attack', 'defense', 'spAtk', 'spDef', 'speed')


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def sp_valid(sp: dict) -> bool:
    return all(0 <= v <= SP_MAX_PER_STAT for v in sp.values()) and sum(sp.values()) <= SP_MAX_TOTAL


class Command(BaseCommand):
    help = 'data/raw/ 수집 원본(OP.GG, Smogon, Showdown 리플레이)을 meta 테이블에 적재'

    def handle(self, *args, **options):
        self.counts = Counter()
        self.skipped = Counter()
        self.unmatched = defaultdict(Counter)
        self.dexes = {rid: DexIndex.from_db(rid) for rid in ('champions_mb', 'champions_mc')}
        if not self.dexes[OPGG_RULESET].pokemon:
            self.stderr.write('게임 데이터가 없습니다. 먼저 python manage.py load_dex 를 실행하세요.')
            return

        with transaction.atomic():
            for model in (UsageStat, Team, PokemonSet, RankSnapshot):   # detail, member는 CASCADE
                model.objects.all().delete()
            self.load_rank_snapshots()
            self.load_opgg_ranked()
            self.load_smogon()
            self.load_opgg_teams()
            self.load_opgg_samples()
            self.load_replays()
            self.load_vgcpastes()
            self.fill_replay_sp()
            self.check_moves()
            self.sets_from_teams()
        self.report()

    # ------------------------------------------------------------------ 공통

    def verify(self, kind: str, value: str, valid) -> str:
        """DB에 없는 ID는 기록만 하고 그대로 저장 (나중에 매핑 보완)."""
        if value and value not in valid:
            self.unmatched[kind][value] += 1
        return value

    def report(self) -> None:
        self.stdout.write('\n=== 적재 결과 ===')
        for k, v in self.counts.items():
            self.stdout.write(f'  {k}: {v}')
        if self.skipped:
            self.stdout.write('=== 건너뜀 ===')
            for k, v in self.skipped.items():
                self.stdout.write(f'  {k}: {v}')
        if self.unmatched:
            self.stdout.write('=== DB에 없는 ID (상위 15개) ===')
            for kind, c in self.unmatched.items():
                self.stdout.write(f'  [{kind}] {sum(c.values())}건: {c.most_common(15)}')

    def save_usage(self, stats: list[tuple[UsageStat, list[UsageDetail]]]) -> None:
        UsageStat.objects.bulk_create([u for u, _ in stats])
        details = []
        for u, ds in stats:
            for d in ds:
                d.usage_stat = u
            details += ds
        UsageDetail.objects.bulk_create(details, batch_size=2000)

    def save_teams(self, teams: list[tuple[Team, list[TeamMember]]]) -> None:
        Team.objects.bulk_create([t for t, _ in teams])
        members = []
        for t, ms in teams:
            for m in ms:
                m.team = t
            members += ms
        TeamMember.objects.bulk_create(members, batch_size=2000)

    # ------------------------------------------------------------------ 순위 스냅샷

    def load_rank_snapshots(self) -> None:
        """data/raw/opgg/tier/{single|double}/*.json (manage.py snapshot_ranking이 저장한 원본)"""
        dex = self.dexes[OPGG_RULESET]
        for f in sorted((RAW / 'opgg' / 'tier').glob('*/*.json')):
            data = load_json(f)
            n = opgg_tier.store(data, dex)
            self.counts[f'rank_snapshot {data["format"]} {data["createdAt"]}'] = n

    # ------------------------------------------------------------------ 사용률

    def load_opgg_ranked(self) -> None:
        dex = self.dexes[OPGG_RULESET]
        for season_dir in sorted((RAW / 'opgg' / 'ranked').glob('*')):
            season = season_dir.name
            for fmt_dir in sorted(season_dir.glob('*')):
                fmt = {'single': 'singles', 'double': 'doubles'}[fmt_dir.name]
                # 시즌별 순위 이력 (collect_samples.py opgg-history). 마지막 항목이 직전 시즌
                hist_path = RAW / 'opgg' / 'history' / season / f'{fmt_dir.name}.json'
                history = load_json(hist_path) if hist_path.exists() else {}
                if not history:
                    self.skipped[f'opgg 순위 이력 없음 ({season} {fmt_dir.name}) → 순위 변동 비움'] += 1
                stats, seen = [], set()
                for f in sorted(fmt_dir.glob('*.json')):
                    d = load_json(f)
                    det = d['overview']['detail']
                    body = det['detail']
                    names = {kind: {x['id']: x.get('key') or x.get('name') for x in d['lookupData'].get(kind, [])}
                             for kind in ('moves', 'items', 'abilities', 'natures')}
                    pid = self.verify('pokemon(opgg)', opgg_pokemon_id(body['pokemon']['key'], dex), dex.pokemon)
                    if pid in seen:  # 같은 포켓몬의 다른 표기 (aegislash-blade 등) → 먼저 나온 것만
                        self.skipped[f"opgg 인게임 통계 중복 ({body['pokemon']['key']})"] += 1
                        continue
                    seen.add(pid)
                    u = UsageStat(ruleset_id=OPGG_RULESET, format_key=f'{OPGG_RULESET}_{fmt}', pokemon_key=pid,
                                  source='opgg', season=season,
                                  snapshot_date=datetime.strptime(det['createdAt'][:10], '%Y-%m-%d').date(),
                                  rank=d['overview']['ranking']['pokemon']['rank'],
                                  prev_rank=(history.get(f.stem) or [{}])[-1].get('rank'))
                    ds = []
                    for kind, src, valid in (('move', 'moves', dex.moves), ('item', 'items', dex.items),
                                             ('ability', 'abilities', dex.abilities)):
                        for x in body.get(src) or []:
                            raw = names[src].get(x['id'])
                            key = opgg_item_id(raw) if kind == 'item' else to_id(raw)
                            ds.append(UsageDetail(kind=kind, target_key=self.verify(f'{kind}(opgg)', key, valid),
                                                  pct=x['usagePercent']))
                    for x in body.get('natures') or []:
                        ds.append(UsageDetail(kind='nature', target_key=to_id(names['natures'].get(x['id'])),
                                              pct=x['usagePercent']))
                    for x in body.get('training') or []:
                        sp = '/'.join(str(int(h, 16)) for h in x['spread'].split('-'))  # 16진수 → 10진수
                        ds.append(UsageDetail(kind='spread', target_key=sp, pct=x['usagePercent']))
                    stats.append((u, ds))
                self.save_usage(stats)
                self.counts[f'usage_stat opgg {season} {fmt}'] = len(stats)

    def load_smogon(self) -> None:
        """Smogon 월별 통계 (chaos JSON). 가중치 합계 기준으로 %를 계산."""
        def top(counter: dict, n: int = 15):
            return sorted(counter.items(), key=lambda kv: -kv[1])[:n]

        for f in sorted((RAW / 'smogon').glob('*/*.json')):
            month, fmt = f.parent.name, f.stem.rsplit('-', 1)[0]
            if fmt not in SMOGON_FORMATS:
                continue
            ruleset_id, format_key, source = SMOGON_FORMATS[fmt]
            dex = self.dexes[ruleset_id]
            y, m = map(int, month.split('-'))
            snapshot = date(y + (m == 12), m % 12 + 1, 1)  # 통계가 집계된 달의 다음 달 1일
            ranked = sorted(load_json(f)['data'].items(), key=lambda kv: -kv[1]['usage'])
            stats = []
            seen = set()
            for rank, (name, v) in enumerate(ranked, 1):
                # 합친 폼(파밀리쥐 세식구 → 네식구)은 남긴 폼으로, 둘 다 있으면 사용률 높은 쪽만
                pid = dex.resolve_cosmetic(to_id(name))
                if pid in seen:
                    self.skipped[f'smogon 합친 폼 중복 ({name})'] += 1
                    continue
                seen.add(pid)
                total = sum(v['Abilities'].values()) or 1
                pct = lambda w: round(w / total * 100, 3)  # noqa: E731
                u = UsageStat(ruleset_id=ruleset_id, format_key=format_key, source=source, season=month,
                              pokemon_key=self.verify('pokemon(smogon)', pid, dex.pokemon),
                              snapshot_date=snapshot, rank=rank, usage_pct=round(v['usage'] * 100, 3))
                ds = []
                for kind, key, valid in (('move', 'Moves', dex.moves), ('item', 'Items', dex.items),
                                         ('ability', 'Abilities', dex.abilities)):
                    for tid, w in top(v[key]):
                        if tid not in ('', 'nothing'):
                            ds.append(UsageDetail(kind=kind, target_key=self.verify(f'{kind}(smogon)', tid, valid),
                                                  pct=pct(w)))
                # Spreads는 "성격:SP" 형식 → 성격과 SP 배분으로 나눠 집계
                natures, spreads = Counter(), Counter()
                for k, w in v['Spreads'].items():
                    nat, sp = k.split(':')
                    natures[to_id(nat)] += w
                    spreads[sp] += w
                for kind, c in (('nature', natures), ('spread', spreads)):
                    ds += [UsageDetail(kind=kind, target_key=tid, pct=pct(w)) for tid, w in top(c)]
                ds += [UsageDetail(kind='teammate', target_key=dex.resolve_cosmetic(to_id(mate)), pct=pct(w))
                       for mate, w in top(v['Teammates'], 12)]
                stats.append((u, ds))
            self.save_usage(stats)
            self.counts[f'usage_stat {source} {month} {format_key}'] = len(stats)

    # ------------------------------------------------------------------ 파티 / 육성형

    def opgg_build(self, slot: dict, dex: DexIndex) -> dict | None:
        """OP.GG 슬롯 → Build 필드. 빈 슬롯이거나 SP 규칙 위반이면 None."""
        if not slot.get('pokemon'):
            return None
        pid = self.verify('pokemon(opgg)', opgg_pokemon_id(slot['pokemon'], dex), dex.pokemon)
        cs = slot.get('customStats') or {}
        sp = {s: int(cs.get(src) or 0) for s, src in zip(SP_STATS, OPGG_SP_FIELDS)}
        if not sp_valid(sp):
            return None
        moves = [self.verify('move(opgg)', to_id(m), dex.moves) for m in (slot.get('moves') or [])] + [''] * 4
        return {
            'pokemon_key': dex.base_id(pid),
            'item_key': self.verify('item(opgg)', opgg_item_id(slot.get('item')), dex.items),
            'ability_key': self.verify('ability(opgg)', to_id(slot.get('ability')), dex.abilities),
            'nature_key': to_id(slot.get('nature')),
            **{f'sp_{s}': v for s, v in sp.items()},
            'move1': moves[0], 'move2': moves[1], 'move3': moves[2], 'move4': moves[3],
            '_is_mega': dex.is_mega(pid),
        }

    def load_opgg_teams(self) -> None:
        dex = self.dexes[OPGG_RULESET]
        for fmt in ('single', 'double'):
            path = RAW / 'opgg' / f'replica-teams_{fmt}.json'
            if not path.exists():
                continue
            teams = []
            for t in load_json(path):
                builds = [self.opgg_build(sl, dex) for sl in t['slots']]
                if any(b is None and sl.get('pokemon') for b, sl in zip(builds, t['slots'])):
                    self.skipped['opgg 레플리카 팀 (SP 규칙 위반)'] += 1
                    continue
                builds = [b for b in builds if b]
                if not builds:
                    self.skipped['opgg 레플리카 팀 (빈 팀)'] += 1
                    continue
                team = Team(ruleset_id=OPGG_RULESET, format_key=f'{OPGG_RULESET}_{fmt}s', source='opgg_replica',
                            external_id=str(t['id']), name=t.get('title') or '',
                            player=(t.get('author') or {}).get('nickname') or '',
                            played_on=datetime.fromisoformat(t['createdAt'].replace('Z', '+00:00')).date(),
                            raw_paste=json.dumps(t['slots'], ensure_ascii=False))
                members = [TeamMember(slot=i, is_gimmick_user=b.pop('_is_mega'), **b)
                           for i, b in enumerate(builds, 1)]
                teams.append((team, members))
            self.save_teams(teams)
            self.counts[f'team opgg_replica {fmt}'] = len(teams)

    def load_opgg_samples(self) -> None:
        dex = self.dexes[OPGG_RULESET]
        for fmt in ('single', 'double'):
            path = RAW / 'opgg' / f'sample-builds_{fmt}.json'
            if not path.exists():
                continue
            sets = []
            for x in load_json(path):
                b = self.opgg_build(x['slot'], dex)
                if not b:
                    self.skipped['opgg 샘플 빌드 (SP 규칙 위반/빈 슬롯)'] += 1
                    continue
                b.pop('_is_mega')
                sets.append(PokemonSet(ruleset_id=OPGG_RULESET, format_key=f'{OPGG_RULESET}_{fmt}s',
                                       name=x.get('title') or '', source='opgg_sample', **b))
            PokemonSet.objects.bulk_create(sets)
            self.counts[f'pokemon_set opgg_sample {fmt}'] = len(sets)

    def load_replays(self) -> None:
        for fmt_dir in sorted((RAW / 'showdown' / 'replays').glob('*')):
            if fmt_dir.name not in REPLAY_FORMATS:
                continue
            ruleset_id, format_key = REPLAY_FORMATS[fmt_dir.name]
            dex = self.dexes[ruleset_id]
            teams = []
            for f in sorted(fmt_dir.glob('*.json')):
                rep = load_json(f)
                played = datetime.fromtimestamp(rep['uploadtime'], tz=timezone.utc).date()
                for side in parse_replay(rep['log']):
                    if len(side.species) < 6:
                        self.skipped['리플레이 파티 (6마리 미만)'] += 1
                        continue
                    team = Team(ruleset_id=ruleset_id, format_key=format_key, source='showdown_replay',
                                external_id=f"{rep['id']}:{side.side}", name=rep['id'], player=side.player,
                                played_on=played, rating=rep.get('rating') or None, result=side.result)
                    members = []
                    for i, sid in enumerate(side.species, 1):
                        sid = self.verify('pokemon(replay)', dex.resolve_cosmetic(sid), dex.pokemon)
                        st = side.sets.get(sid, {})
                        moves = [self.verify('move(replay)', m, dex.moves) for m in st.get('moves', [])] + [''] * 4
                        members.append(TeamMember(
                            slot=i, pokemon_key=dex.base_id(sid),
                            item_key=self.verify('item(replay)', st.get('item', ''), dex.items),
                            ability_key=self.verify('ability(replay)', st.get('ability', ''), dex.abilities),
                            nature_key=st.get('nature', ''),
                            move1=moves[0], move2=moves[1], move3=moves[2], move4=moves[3],
                            is_gimmick_user=match_species(sid, side.mega),
                            brought=match_species(sid, side.brought),
                            lead=match_species(sid, side.lead)))
                    teams.append((team, members))
            self.save_teams(teams)
            self.counts[f'team showdown_replay {fmt_dir.name}'] = len(teams)

    # ------------------------------------------------------------------ VGCPastes

    @staticmethod
    def placement(rank: str) -> int | None:
        """'Champion' → 1, 'Runner Up' → 2, '3rd' / 'Top 4' / 'Top 8' → 숫자."""
        r = rank.lower()
        if 'champion' in r or r in ('1st', 'winner'):
            return 1
        if 'runner' in r or 'finalist' in r:
            return 2
        m = re.search(r'\d+', r)
        return int(m.group()) if m else None

    def load_vgcpastes(self) -> None:
        """data/raw/vgcpastes/{ruleset}.json (collect_samples.py vgcpastes). 챔피언스 VGC = 더블."""
        for path in sorted((RAW / 'vgcpastes').glob('*.json')):
            ruleset_id = path.stem
            if ruleset_id not in self.dexes:
                continue
            dex = self.dexes[ruleset_id]
            stone_of = {i.showdown_id: to_id(i.mega_from) for i in Item.objects.filter(ruleset_id=ruleset_id)
                        if i.mega_from}
            teams = []
            for t in load_json(path):
                t = {k: ('' if v == '-' else v) for k, v in t.items()}     # 시트의 빈칸 표시 '-'
                sets = parse_paste(t.get('paste', ''))
                if not sets or any(s['sp'] and not sp_valid(s['sp']) for s in sets):
                    self.skipped['VGCPastes 팀 (빈 팀/SP 규칙 위반)'] += 1
                    continue
                try:
                    played = datetime.strptime(t.get('date', ''), '%d %b %Y').date()
                except ValueError:
                    played = None
                team = Team(ruleset_id=ruleset_id, format_key=f'{ruleset_id}_doubles', source='vgcpastes',
                            external_id=t['id'], name=t.get('title', ''), event=t.get('event', '')[:128],
                            player=(t.get('player') or t.get('owner') or '')[:64],
                            placement=self.placement(t.get('rank', '')), played_on=played,
                            raw_paste=t.get('paste', ''))
                members = []
                for i, s in enumerate(sets[:6], 1):
                    pid = self.verify('pokemon(vgcpastes)', dex.resolve_cosmetic(to_id(s['species'])), dex.pokemon)
                    base = dex.base_id(pid)
                    item = self.verify('item(vgcpastes)', to_id(s['item']), dex.items)
                    moves = [self.verify('move(vgcpastes)', to_id(m), dex.moves) for m in s['moves']] + [''] * 4
                    sp = s['sp'] or {}
                    members.append(TeamMember(
                        slot=i, pokemon_key=base, item_key=item,
                        ability_key=self.verify('ability(vgcpastes)', to_id(s['ability']), dex.abilities),
                        nature_key=to_id(s['nature']),
                        **{f'sp_{k}': sp.get(k, 0) for k in SP_STATS},
                        move1=moves[0], move2=moves[1], move3=moves[2], move4=moves[3],
                        is_gimmick_user=dex.is_mega(pid) or stone_of.get(item) in (base, base.removesuffix('f'))))
                teams.append((team, members))
            self.save_teams(teams)
            self.counts[f'team vgcpastes {ruleset_id}'] = len(teams)

    def fill_replay_sp(self) -> None:
        """리플레이 멤버 SP 채우기 (확실한 것만).

        6마리 종이 같고, 리플레이 팀시트의 6마리 도구·특성·성격·기술이 VGCPastes 팀과 모두 같으며,
        그런 팀들의 SP가 한 가지뿐일 때만. 인기 육성은 팀마다 SP가 달라서 한 마리만 같아서는 채우지 않음.
        """
        def build(m):
            return (m.pokemon_key, m.item_key, m.ability_key, m.nature_key, frozenset(m.moves))

        sp_of = lambda m: tuple(getattr(m, f'sp_{s}') for s in SP_STATS)
        by_team = defaultdict(list)       # (ruleset, 6마리 육성) → [(팀 ID, {종: SP})]
        for t in Team.objects.filter(source='vgcpastes').prefetch_related('members'):
            ms = list(t.members.all())
            if len(ms) == 6 and all(any(sp_of(m)) for m in ms):
                by_team[(t.ruleset_id, frozenset(build(m) for m in ms))].append(
                    (t.external_id, {m.pokemon_key: sp_of(m) for m in ms}))
        updated, teams = [], 0
        for t in Team.objects.filter(source='showdown_replay').prefetch_related('members'):
            ms = list(t.members.all())
            if len(ms) != 6 or not all(m.item_key and m.ability_key and m.nature_key for m in ms):
                continue                  # 팀시트가 없는 리플레이
            cands = by_team.get((t.ruleset_id, frozenset(build(m) for m in ms)), [])
            if not cands or len({tuple(sorted(sp.items())) for _, sp in cands}) != 1:
                continue                  # 같은 팀이 없거나, 있어도 SP가 여러 가지
            tid, sp = cands[0]
            for m in ms:
                for s, v in zip(SP_STATS, sp[m.pokemon_key]):
                    setattr(m, f'sp_{s}', v)
                m.sp_from = f'vgcpastes:{tid}'
            updated += ms
            teams += 1
        TeamMember.objects.bulk_update(updated, [f'sp_{s}' for s in SP_STATS] + ['sp_from'], batch_size=2000)
        self.counts['리플레이 SP 채움 (같은 VGCPastes 팀)'] = f'{teams}팀 / {len(updated)}마리'

    def check_moves(self) -> None:
        """배울 수 없는 기술이 있는 파티는 is_legal=False (예: 단애의칼을 든 액슬루미온). 목록에서 숨김."""
        learn = defaultdict(set)
        for rid, p, m in Learnset.objects.values_list('pokemon__ruleset_id', 'pokemon__showdown_id', 'move__showdown_id'):
            learn[(rid, p)].add(m)
        bad, ok = [], []
        for t in Team.objects.prefetch_related('members'):
            illegal = [f'{m.pokemon_key}:{x}' for m in t.members.all() for x in m.moves
                       if x not in learn[(t.ruleset_id, m.pokemon_key)]]
            t.is_legal = not illegal
            (bad if illegal else ok).append(t)
            if illegal:
                self.skipped[f'배울 수 없는 기술 → 숨김 ({t.source} {t.external_id})'] = ', '.join(illegal)
        Team.objects.bulk_update(bad + ok, ['is_legal'], batch_size=2000)

    def sets_from_teams(self) -> None:
        """파티 멤버 → 포켓몬 샘플 (pokemon_set). SP가 있고 도구·특성·성격·기술 4개가 다 있는 것만.

        같은 육성(포맷·포켓몬·도구·특성·성격·SP·기술)은 하나로, 이미 OP.GG 샘플에 있는 것도 뺌.
        배울 수 없는 기술이 있는 파티(is_legal=False)는 쓰지 않음.
        """
        fields = ['pokemon_key', 'item_key', 'ability_key', 'nature_key', *[f'sp_{s}' for s in SP_STATS]]
        key = lambda fk, b: (fk, *[getattr(b, f) for f in fields], frozenset(b.moves))
        seen = {key(s.format_key, s) for s in PokemonSet.objects.all()}
        for src, out in (('vgcpastes', 'vgcpastes_team'), ('opgg_replica', 'opgg_team')):
            sets = []
            for t in Team.objects.filter(source=src).exclude(is_legal=False).prefetch_related('members'):
                for m in t.members.all():
                    if not (any(getattr(m, f'sp_{s}') for s in SP_STATS) and m.item_key and m.ability_key
                            and m.nature_key and len(m.moves) == 4):
                        continue
                    k = key(t.format_key, m)
                    if k in seen:
                        continue
                    seen.add(k)
                    sets.append(PokemonSet(ruleset_id=t.ruleset_id, format_key=t.format_key, name=t.name[:64],
                                           source=out, **{f: getattr(m, f) for f in fields},
                                           move1=m.move1, move2=m.move2, move3=m.move3, move4=m.move4))
            PokemonSet.objects.bulk_create(sets, batch_size=2000)
            self.counts[f'pokemon_set {out} (파티 멤버에서)'] = len(sets)

