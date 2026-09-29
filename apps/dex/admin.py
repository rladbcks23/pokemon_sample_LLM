from django.contrib import admin

from apps.dex.models import Ability, Item, Learnset, Move, Nature, Pokemon, PokemonAbility, Ruleset, TypeChart


@admin.register(Ruleset)
class RulesetAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'showdown_mod', 'start_date', 'end_date']


class PokemonAbilityInline(admin.TabularInline):
    model = PokemonAbility
    extra = 0
    raw_id_fields = ['ability']


@admin.register(Pokemon)
class PokemonAdmin(admin.ModelAdmin):
    list_display = ['name_ko', 'name', 'showdown_id', 'ruleset', 'type1', 'type2',
                    'hp', 'atk', 'defense', 'spa', 'spd', 'spe', 'bst', 'is_mega']
    list_filter = ['ruleset', 'is_mega', 'type1', 'type2']
    search_fields = ['name_ko', 'name', 'showdown_id']
    inlines = [PokemonAbilityInline]


@admin.register(Move)
class MoveAdmin(admin.ModelAdmin):
    list_display = ['name_ko', 'name', 'showdown_id', 'ruleset', 'type', 'category', 'power', 'accuracy', 'pp',
                    'priority', 'target']
    list_filter = ['ruleset', 'type', 'category', 'target']
    search_fields = ['name_ko', 'name', 'showdown_id']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['name_ko', 'name', 'showdown_id', 'ruleset', 'mega_from', 'mega_to']
    list_filter = ['ruleset']
    search_fields = ['name_ko', 'name', 'showdown_id']


@admin.register(Ability)
class AbilityAdmin(admin.ModelAdmin):
    list_display = ['name_ko', 'name', 'showdown_id', 'ruleset', 'short_desc']
    list_filter = ['ruleset']
    search_fields = ['name_ko', 'name', 'showdown_id']


@admin.register(Learnset)
class LearnsetAdmin(admin.ModelAdmin):
    list_display = ['pokemon', 'move']
    list_filter = ['pokemon__ruleset']
    search_fields = ['pokemon__name_ko', 'pokemon__showdown_id', 'move__name_ko', 'move__showdown_id']
    list_select_related = ['pokemon', 'move']
    raw_id_fields = ['pokemon', 'move']


@admin.register(TypeChart)
class TypeChartAdmin(admin.ModelAdmin):
    list_display = ['attacking', 'defending', 'multiplier']
    list_filter = ['attacking', 'defending', 'multiplier']


@admin.register(Nature)
class NatureAdmin(admin.ModelAdmin):
    list_display = ['name_ko', 'name', 'plus_stat', 'minus_stat']
