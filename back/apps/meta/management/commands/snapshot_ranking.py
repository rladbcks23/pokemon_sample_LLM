"""OP.GG 픽률 순위를 받아 스냅샷으로 저장. 매일 한 번 실행 (같은 갱신 시각이면 건너뜀).

사용법: python manage.py snapshot_ranking
"""
from django.core.management.base import BaseCommand

from apps.dex.ids import DexIndex
from apps.meta import opgg_tier


class Command(BaseCommand):
    help = 'OP.GG 싱글·더블 픽률 순위를 받아 RankSnapshot에 저장 (원본은 data/raw/opgg/tier/)'

    def handle(self, *args, **options):
        dex = DexIndex.from_db(opgg_tier.RULESET)
        for battle in ('single', 'double'):
            data = opgg_tier.fetch(battle)
            path = opgg_tier.save_raw(data)
            n = opgg_tier.store(data, dex)
            state = f'{n}마리 저장' if n else '이미 저장된 갱신 시각 → 건너뜀'
            self.stdout.write(f'{battle} {data["season"]} {data["createdAt"]}: {state} ({path.name})')
