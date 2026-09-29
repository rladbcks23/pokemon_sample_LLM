from django.contrib import admin

from apps.meta.models import PokemonSet, Team, TeamMember, UsageDetail, UsageStat


class TeamMemberInline(admin.TabularInline):
    model = TeamMember
    extra = 0
    fields = ['slot', 'pokemon_key', 'item_key', 'ability_key', 'nature_key',
              'sp_hp', 'sp_atk', 'sp_def', 'sp_spa', 'sp_spd', 'sp_spe',
              'move1', 'move2', 'move3', 'move4', 'is_gimmick_user', 'brought', 'lead']


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'source', 'format_key', 'player', 'rating', 'result', 'played_on', 'members_summary']
    list_filter = ['ruleset', 'source', 'format_key', 'result']
    search_fields = ['name', 'player', 'external_id', 'members__pokemon_key']
    inlines = [TeamMemberInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('members')

    @admin.display(description='멤버')
    def members_summary(self, obj):
        return ', '.join(m.pokemon_key for m in obj.members.all())


@admin.register(PokemonSet)
class PokemonSetAdmin(admin.ModelAdmin):
    list_display = ['name', 'pokemon_key', 'item_key', 'ability_key', 'nature_key', 'sp', 'format_key', 'source']
    list_filter = ['ruleset', 'format_key', 'source']
    search_fields = ['name', 'pokemon_key', 'item_key']


class UsageDetailInline(admin.TabularInline):
    model = UsageDetail
    extra = 0
    fields = ['kind', 'target_key', 'pct']


@admin.register(UsageStat)
class UsageStatAdmin(admin.ModelAdmin):
    list_display = ['rank', 'pokemon_key', 'usage_pct', 'source', 'format_key', 'season', 'snapshot_date']
    list_filter = ['ruleset', 'source', 'format_key', 'season']
    search_fields = ['pokemon_key']
    inlines = [UsageDetailInline]
