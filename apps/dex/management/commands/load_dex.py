"""게임 데이터 적재: data/champions_*/*.csv → ruleset, pokemon, ability, pokemon_ability, move, learnset, item
+ 고정 데이터(type_chart, nature).

사용법: python manage.py load_dex
레귤레이션별로 기존 데이터를 지우고 다시 넣는다. meta 데이터는 ID 문자열로 참조하므로 영향 없음.
CSV는 scripts/export_champions.js로 만든다.
"""
import csv
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.dex.ids import to_id
from apps.dex.models import Ability, Item, Learnset, Move, Nature, Pokemon, PokemonAbility, Ruleset, TypeChart

DATA = Path(settings.BASE_DIR) / 'data'

RULESETS = [
    # id, 이름, Showdown mod, CSV 폴더, 시작일, 종료일
    ('champions_mb', 'Regulation M-B', 'championsregmb', 'champions_mb', date(2026, 6, 17), date(2026, 9, 9)),
    ('champions_mc', 'Regulation M-C', 'champions', 'champions_mc', date(2026, 9, 9), date(2026, 12, 2)),
]

# (영문, 한글, 상승, 하락) - PokeAPI 기준
NATURES = [
    ('Hardy', '노력', '', ''), ('Lonely', '외로움', 'atk', 'def'), ('Brave', '용감', 'atk', 'spe'),
    ('Adamant', '고집', 'atk', 'spa'), ('Naughty', '개구쟁이', 'atk', 'spd'), ('Bold', '대담', 'def', 'atk'),
    ('Docile', '온순', '', ''), ('Relaxed', '무사태평', 'def', 'spe'), ('Impish', '장난꾸러기', 'def', 'spa'),
    ('Lax', '촐랑', 'def', 'spd'), ('Timid', '겁쟁이', 'spe', 'atk'), ('Hasty', '성급', 'spe', 'def'),
    ('Serious', '성실', '', ''), ('Jolly', '명랑', 'spe', 'spa'), ('Naive', '천진난만', 'spe', 'spd'),
    ('Modest', '조심', 'spa', 'atk'), ('Mild', '의젓', 'spa', 'def'), ('Quiet', '냉정', 'spa', 'spe'),
    ('Bashful', '수줍음', '', ''), ('Rash', '덜렁', 'spa', 'spd'), ('Calm', '차분', 'spd', 'atk'),
    ('Gentle', '얌전', 'spd', 'def'), ('Sassy', '건방', 'spd', 'spe'), ('Careful', '신중', 'spd', 'spa'),
    ('Quirky', '변덕', '', ''),
]

ABILITY_SLOTS = (('0', 'ability1'), ('1', 'ability2'), ('H', 'ability_hidden'), ('S', 'ability_special'))


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def int_or_none(v: str):
    return int(v) if v not in ('', None) else None


class Command(BaseCommand):
    help = '게임 데이터 CSV(data/champions_*)와 고정 데이터를 DB에 적재'

    @transaction.atomic
    def handle(self, *args, **options):
        for rid, name, mod, folder, start, end in RULESETS:
            rs, _ = Ruleset.objects.update_or_create(
                id=rid, defaults={'name': name, 'showdown_mod': mod, 'start_date': start, 'end_date': end})
            self.load_ruleset(rs, DATA / folder)
        self.load_static()

    def load_ruleset(self, rs: Ruleset, folder: Path) -> None:
        # 기존 데이터 삭제 (pokemon_ability, learnset은 CASCADE)
        for model in (Pokemon, Move, Item, Ability):
            model.objects.filter(ruleset=rs).delete()

        abilities = Ability.objects.bulk_create([
            Ability(ruleset=rs, showdown_id=r['id'], name=r['name'], name_ko=r['name_ko'], short_desc=r['short_desc'])
            for r in read_csv(folder / 'abilities.csv')])
        ability_by_name = {a.name: a for a in abilities}

        rows = read_csv(folder / 'pokemon.csv')
        pokemon = Pokemon.objects.bulk_create([
            Pokemon(ruleset=rs, showdown_id=r['id'], name=r['name'], name_ko=r['name_ko'], num=int(r['num']),
                    base_species=r['base_species'], forme=r['forme'], is_mega=r['is_mega'] == '1',
                    required_item=r['required_item'], type1=r['type1'], type2=r['type2'],
                    hp=int(r['hp']), atk=int(r['atk']), defense=int(r['def']), spa=int(r['spa']),
                    spd=int(r['spd']), spe=int(r['spe']), bst=int(r['bst']), weight_kg=float(r['weight_kg']))
            for r in rows])
        pokemon_by_sid = {p.showdown_id: p for p in pokemon}
        PokemonAbility.objects.bulk_create([
            PokemonAbility(pokemon=pokemon_by_sid[r['id']], ability=ability_by_name[r[col]], slot=slot)
            for r in rows for slot, col in ABILITY_SLOTS if r[col]])

        moves = Move.objects.bulk_create([
            Move(ruleset=rs, showdown_id=r['id'], name=r['name'], name_ko=r['name_ko'], type=r['type'],
                 category=r['category'], power=int(r['power'] or 0), accuracy=int_or_none(r['accuracy']),
                 pp=int(r['pp']), priority=int(r['priority']), target=r['target'], flags=r['flags'],
                 secondary_chance=int_or_none(r['secondary_chance']), short_desc=r['short_desc'])
            for r in read_csv(folder / 'moves.csv')])
        move_by_sid = {m.showdown_id: m for m in moves}

        items = Item.objects.bulk_create([
            Item(ruleset=rs, showdown_id=r['id'], name=r['name'], name_ko=r['name_ko'],
                 mega_from=r['mega_from'], mega_to=r['mega_to'], short_desc=r['short_desc'])
            for r in read_csv(folder / 'items.csv')])

        learnset = Learnset.objects.bulk_create([
            Learnset(pokemon=pokemon_by_sid[r['pokemon_id']], move=move_by_sid[r['move_id']])
            for r in read_csv(folder / 'learnsets.csv')], batch_size=2000)

        self.stdout.write(f'{rs.id}: pokemon {len(pokemon)}, move {len(moves)}, item {len(items)}, '
                          f'ability {len(abilities)}, learnset {len(learnset)}')

    def load_static(self) -> None:
        TypeChart.objects.all().delete()
        TypeChart.objects.bulk_create([
            TypeChart(attacking=r['attacking'], defending=r['defending'], multiplier=float(r['multiplier']))
            for r in read_csv(DATA / 'champions_mc' / 'typechart.csv')])
        Nature.objects.all().delete()
        Nature.objects.bulk_create([Nature(id=to_id(n), name=n, name_ko=ko, plus_stat=plus, minus_stat=minus)
                                    for n, ko, plus, minus in NATURES])
        self.stdout.write(f'type_chart {TypeChart.objects.count()}, nature {Nature.objects.count()}')
