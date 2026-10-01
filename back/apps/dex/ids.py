"""출처마다 다른 이름 표기를 Showdown ID로 맞추는 유틸.

- Showdown ID: 소문자 영숫자 (Garchomp-Mega-Z → garchompmegaz)
- OP.GG: 하이픈 구분, 메가가 앞에 옴 (mega-garchomp-z), 성별·지역 표기가 다름
"""
import re
from dataclasses import dataclass, field


def to_id(name: str | None) -> str:
    """Showdown ID 규칙: 소문자 영숫자만."""
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


@dataclass
class DexIndex:
    """레귤레이션 하나의 ID 목록. 다른 출처의 ID를 검증·변환할 때 사용."""
    pokemon: dict[str, dict] = field(default_factory=dict)   # showdown_id → {name, base_species, forme, is_mega}
    moves: set[str] = field(default_factory=set)
    items: set[str] = field(default_factory=set)
    abilities: set[str] = field(default_factory=set)

    @classmethod
    def from_db(cls, ruleset_id: str) -> 'DexIndex':
        from apps.dex.models import Ability, Item, Move, Pokemon

        idx = cls()
        for p in Pokemon.objects.filter(ruleset_id=ruleset_id).values(
                'showdown_id', 'name', 'base_species', 'forme', 'is_mega'):
            idx.pokemon[p['showdown_id']] = p
        idx.moves = set(Move.objects.filter(ruleset_id=ruleset_id).values_list('showdown_id', flat=True))
        idx.items = set(Item.objects.filter(ruleset_id=ruleset_id).values_list('showdown_id', flat=True))
        idx.abilities = set(Ability.objects.filter(ruleset_id=ruleset_id).values_list('showdown_id', flat=True))
        return idx

    def resolve_cosmetic(self, pokemon_id: str) -> str:
        """외형만 다른 폼(vivillonhighplains 등)은 DB에 없으므로 기본 폼으로. 합친 폼은 남긴 폼으로."""
        if pokemon_id in self.pokemon:
            return pokemon_id
        if MERGED_POKEMON.get(pokemon_id) in self.pokemon:
            return MERGED_POKEMON[pokemon_id]
        bases = [p for p, r in self.pokemon.items() if not r['forme'] and pokemon_id.startswith(p)]
        return max(bases, key=len) if bases else pokemon_id

    def base_id(self, pokemon_id: str) -> str:
        """메가 폼이면 원래 폼 ID (파티에는 메가 전 포켓몬 + 메가스톤으로 저장)."""
        p = self.pokemon.get(pokemon_id)
        if not p or not p['is_mega']:
            return pokemon_id
        base = to_id(p['base_species'])
        if p['forme'].startswith('F-') and base + 'f' in self.pokemon:      # 메가냐오닉스(암컷) → 냐오닉스 암컷
            return base + 'f'
        if base in self.pokemon:
            return base
        # 기본 폼이 없는 포켓몬 (메가플라엣테 → 플라엣테-영원의꽃): 같은 종의 메가 아닌 폼
        forms = [k for k, r in self.pokemon.items() if r['base_species'] == p['base_species'] and not r['is_mega']]
        return forms[0] if len(forms) == 1 else base

    def is_mega(self, pokemon_id: str) -> bool:
        return bool(self.pokemon.get(pokemon_id, {}).get('is_mega'))


# ---------------------------------------------------------------------------
# OP.GG
# ---------------------------------------------------------------------------

OPGG_POKEMON_OVERRIDES = {
    'floette-eternal-flower': 'floetteeternal',
    'maushold-family-of-three': 'mausholdfour',  # 네식구·세식구는 성능이 같아 네식구 하나로 합침
    'maushold-family-of-four': 'mausholdfour',
    'mega-meowstic': 'meowsticmmega',
    'mega-meowstic-male': 'meowsticmmega',
    'mega-meowstic-female': 'meowsticfmega',
}
# 성능이 같아 하나로 합친 폼: 제외한 폼 → 남긴 폼 (scripts/export_champions.js의 MERGED_FORMES)
MERGED_POKEMON = {
    'maushold': 'mausholdfour',
    'vivillonfancy': 'vivillon', 'vivillonpokeball': 'vivillon',
    'polteageistantique': 'polteageist',
    'sinistchamasterpiece': 'sinistcha',
    'squawkabillyblue': 'squawkabilly', 'squawkabillywhite': 'squawkabillyyellow',
}

OPGG_REGION = {'alolan': 'alola', 'galarian': 'galar', 'hisuian': 'hisui', 'paldean': 'paldea'}
# 메가스톤 이름이 Showdown과 다른 것
OPGG_ITEM_OVERRIDES = {
    'staraptorite': 'staraptite', 'barbaraclite': 'barbaracite',
    'scolipedite': 'scolipite', 'scraftite': 'scraftinite',
}


def opgg_item_id(key: str | None) -> str:
    iid = to_id(key)
    return OPGG_ITEM_OVERRIDES.get(iid, iid)


def opgg_pokemon_id(key: str, dex: DexIndex) -> str:
    if key in OPGG_POKEMON_OVERRIDES:
        return OPGG_POKEMON_OVERRIDES[key]
    parts = key.split('-')
    if parts[0] == 'mega':                       # mega-garchomp-z → garchomp-mega-z
        parts = [parts[1], 'mega', *parts[2:]]
    parts = [OPGG_REGION.get(p, p) for p in parts if p != 'plumage']  # squawkabilly-blue-plumage
    if parts[-1] == 'male':                      # basculegion-male → basculegion
        parts = parts[:-1]
    elif parts[-1] == 'female':                  # indeedee-female → indeedeef
        parts[-1] = 'f'
    pid = to_id(''.join(parts))
    pid = MERGED_POKEMON.get(pid, pid)
    if pid not in dex.pokemon:
        # 기본 폼 이름이 붙은 경우 (lycanroc-midday → lycanroc)
        base = to_id(parts[0])
        if base in dex.pokemon and dex.pokemon[base]['base_species'] == dex.pokemon[base]['name']:
            forme_key = to_id(''.join(parts[1:]))
            if not any(to_id(p['forme']) == forme_key for p in dex.pokemon.values()
                       if to_id(p['base_species']) == base):
                return base
    return pid
