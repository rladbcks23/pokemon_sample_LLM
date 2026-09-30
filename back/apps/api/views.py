"""프론트(Vue)용 조회 API."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.api.common import format_key, get_format, get_ruleset, pokemon_brief
from apps.meta.models import UsageStat


def latest_usage(ruleset, fmt: str, source: str = 'opgg'):
    """가장 최근 스냅샷의 사용률 queryset (시즌·날짜 기준)."""
    qs = UsageStat.objects.filter(ruleset=ruleset, format_key=format_key(ruleset, fmt), source=source)
    last = qs.order_by('-snapshot_date', '-season').values('snapshot_date', 'season').first()
    if not last:
        return qs.none(), None
    return qs.filter(**last), last


@api_view(['GET'])
def ranking(request):
    """랭킹(메타): 인게임 픽률 순위와 직전 시즌 대비 변동.

    GET /api/ranking/?format=doubles&limit=50
    """
    rs, fmt = get_ruleset(request), get_format(request)
    limit = int(request.query_params.get('limit', 0)) or None
    qs, last = latest_usage(rs, fmt)
    rows = qs.order_by('rank')[:limit] if limit else qs.order_by('rank')
    return Response({
        'ruleset': rs.id, 'format': fmt,
        'season': last and last['season'], 'snapshot_date': last and last['snapshot_date'],
        'items': [{
            'rank': u.rank, 'prev_rank': u.prev_rank, 'change': u.rank_change,
            'is_new': u.prev_rank is None,
            'pokemon': pokemon_brief(rs.id, u.pokemon_key),
        } for u in rows],
    })
