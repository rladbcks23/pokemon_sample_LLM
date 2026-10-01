// Pokémon Showdown의 champions mod 데이터를 CSV로 내보낸다.
// 사용법: node scripts/export_champions.js <showdown 빌드 경로> [mod=champions] [out=data/champions_mc]
// showdown 빌드: git clone --depth 1 https://github.com/smogon/pokemon-showdown && npm i && node build
'use strict';
const fs = require('fs');
const path = require('path');

const [psDir, modId = 'champions', outDir = 'data/champions_mc'] = process.argv.slice(2);
if (!psDir) {
	console.error('usage: node export_champions.js <pokemon-showdown dir> [mod] [outDir]');
	process.exit(1);
}
const {Dex, TeamValidator} = require(path.resolve(psDir, 'dist/sim'));
const dex = Dex.mod(modId);

// 레귤레이션별 싱글/더블 포맷 (로스터는 동일, 선출 수만 다름)
const FORMATS = {
	champions: {singles: 'gen9championsbssregmc', doubles: 'gen9championsvgc2026regmc'},
	championsregmb: {singles: 'gen9championsbssregmb', doubles: 'gen9championsvgc2026regmb'},
}[modId];
const validator = TeamValidator.get(FORMATS.doubles);

const POKEAPI = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/';
const KO = 3; // PokeAPI languages.csv: ko

function parseCsv(text) {
	const rows = [];
	for (const line of text.split(/\r?\n/)) {
		if (!line) continue;
		const cells = [];
		let cur = '', q = false;
		for (let i = 0; i < line.length; i++) {
			const c = line[i];
			if (q) {
				if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c;
			} else if (c === '"') q = true;
			else if (c === ',') { cells.push(cur); cur = ''; } else cur += c;
		}
		cells.push(cur);
		rows.push(cells);
	}
	const [header, ...body] = rows;
	return body.map(r => Object.fromEntries(header.map((h, i) => [h, r[i]])));
}

async function fetchCsv(name) {
	const res = await fetch(POKEAPI + name);
	if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
	return parseCsv(await res.text());
}

// PokeAPI identifier("karate-chop") -> Showdown id("karatechop") 기준 한국어 이름 맵
async function koNames(entityCsv, namesCsv, idCol) {
	const [entities, names] = await Promise.all([fetchCsv(entityCsv), fetchCsv(namesCsv)]);
	const koById = new Map(names.filter(n => +n.local_language_id === KO).map(n => [n[idCol], n.name]));
	const map = new Map();
	for (const e of entities) {
		const ko = koById.get(e.id);
		if (ko) map.set(e.identifier.replace(/[^a-z0-9]/g, ''), ko);
	}
	return map;
}

function toCsv(rows) {
	if (!rows.length) return '';
	const cols = Object.keys(rows[0]);
	const esc = v => {
		if (v === undefined || v === null) return '';
		const s = typeof v === 'object' ? JSON.stringify(v) : String(v);
		return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
	};
	return [cols.join(','), ...rows.map(r => cols.map(c => esc(r[c])).join(','))].join('\n');
}

function write(name, rows) {
	fs.mkdirSync(outDir, {recursive: true});
	// BOM: 엑셀에서 한글이 깨지지 않도록
	fs.writeFileSync(path.join(outDir, name), '﻿' + toCsv(rows) + '\n');
	console.log(`${name}: ${rows.length} rows`);
}

// 폼 이름 한국어 표기 (없는 건 영어 그대로)
const FORME_KO = {
	'Mega': '메가', 'Mega-X': '메가X', 'Mega-Y': '메가Y', 'Mega-Z': '메가Z',
	'Alola': '알로라', 'Galar': '가라르', 'Hisui': '히스이', 'Paldea': '팔데아',
	'Paldea-Combat': '팔데아-컴뱃', 'Paldea-Blaze': '팔데아-블레이즈', 'Paldea-Aqua': '팔데아-워터',
	'Heat': '히트', 'Wash': '워시', 'Frost': '프로스트', 'Fan': '스핀', 'Mow': '커트',
	// 성별
	'M': '수컷', 'F': '암컷', 'M-Mega': '수컷-메가', 'F-Mega': '암컷-메가',
	// 루가루암
	'Midday': '한낮의 모습', 'Midnight': '한밤중의 모습', 'Dusk': '황혼의 모습',
	// 시비꼬
	'Green': '그린 페더', 'Blue': '블루 페더', 'Yellow': '옐로 페더', 'White': '화이트 페더',
	// 펌킨인
	'Small': '소과종', 'Average': '중과종', 'Large': '대과종', 'Super': '특대과종',
	// 스트린더
	'Amped': '하이한 모습', 'Low-Key': '로우한 모습',
	// 비비용
	'Icy Snow': '빙설의 모양', 'Polar': '설국의 모양', 'Tundra': '설원의 모양', 'Continental': '대륙의 모양',
	'Garden': '정원의 모양', 'Elegant': '우아한 모양', 'Meadow': '화원의 모양', 'Modern': '모던한 모양',
	'Marine': '마린의 모양', 'Archipelago': '군도의 모양', 'High Plains': '황야의 모양', 'Sandstorm': '사진의 모양',
	'River': '대하의 모양', 'Monsoon': '스콜의 모양', 'Savanna': '사바나의 모양', 'Sun': '태양의 모양',
	'Ocean': '오션의 모양', 'Jungle': '정글의 모양', 'Fancy': '팬시한 모양', 'Pokeball': '볼의 모양',
	// 플라엣테 / 포트데스 / 파밀리쥐 / 그우린차
	'Eternal': '영원의꽃',
	'Phony': '위작폼', 'Antique': '진작폼',
	'Four': '네식구',
	'Unremarkable': '범작의 모습', 'Masterpiece': '걸작의 모습',
};

// PokeAPI에 한국어 이름이 없는 항목 (챔피언스 신규 등) 수동 보강
const MANUAL_KO = {
	auraguard: '파동의방호', eelevate: '천정부지', firemane: '불꽃의갈기', // 특성
	leek: '대파', // 도구
};

// 성능이 같아 하나로 합치는 폼: 제외할 폼 → 남길 폼. 남긴 폼은 이름에 폼 이름을 붙이지 않음
// 파밀리쥐: 세식구(기본 폼)를 빼고 네식구만 "파밀리쥐"로
const MERGED_FORMES = new Map([['Maushold', 'Maushold-Four']]);
const KEPT_FORMES = new Set(MERGED_FORMES.values());

function isLegalSpecies(species) {
	if (species.isNonstandard || species.tier === 'Illegal') return false;
	// 배틀 중에만 바뀌는 폼(메가 제외)과 외형만 다른 폼은 제외
	if (species.battleOnly && !species.isMega) return false;
	if (dex.species.get(species.baseSpecies).cosmeticFormes?.includes(species.name)) return false;
	// 성능이 같아 하나로 합치는 폼 (파밀리쥐 네식구 = 세식구)
	if (MERGED_FORMES.has(species.name)) return false;
	const set = {species: species.name, name: species.baseSpecies, moves: [], ability: '', item: ''};
	return !validator.checkSpecies(set, species, species, {});
}

(async () => {
	const [koSpecies, koMove, koAbility, koItem] = await Promise.all([
		koNames('pokemon_species.csv', 'pokemon_species_names.csv', 'pokemon_species_id'),
		koNames('moves.csv', 'move_names.csv', 'move_id'),
		koNames('abilities.csv', 'ability_names.csv', 'ability_id'),
		koNames('items.csv', 'item_names.csv', 'item_id'),
	]);

	// --- pokemon ---
	const pokemon = [];
	for (const s of dex.species.all()) {
		if (!s.exists || !isLegalSpecies(s)) continue;
		const baseKo = koSpecies.get(dex.species.get(s.baseSpecies).id);
		// 기본 폼도 다른 폼이 있으면 폼 이름을 붙임 (예: 루가루암-한낮의 모습)
		const forme = KEPT_FORMES.has(s.name) ? '' : s.forme || (FORME_KO[s.baseForme] ? s.baseForme : '');
		pokemon.push({
			id: s.id,
			name: s.name,
			name_ko: baseKo ? (forme ? `${baseKo}-${FORME_KO[forme] || forme}` : baseKo) : '',
			num: s.num,
			base_species: s.baseSpecies,
			forme: s.forme,
			is_mega: s.isMega ? 1 : 0,
			required_item: s.requiredItem || '',
			type1: s.types[0],
			type2: s.types[1] || '',
			hp: s.baseStats.hp, atk: s.baseStats.atk, def: s.baseStats.def,
			spa: s.baseStats.spa, spd: s.baseStats.spd, spe: s.baseStats.spe,
			bst: s.bst,
			ability1: s.abilities[0] || '',
			ability2: s.abilities[1] || '',
			ability_hidden: s.abilities.H || '',
			ability_special: s.abilities.S || '',
			weight_kg: s.weightkg,
			tier: s.tier,
			doubles_tier: s.doublesTier,
			tags: s.tags.join('|'),
		});
	}
	write('pokemon.csv', pokemon);

	// --- moves ---
	const moves = dex.moves.all().filter(m => m.exists && !m.isNonstandard && !m.isZ && !m.isMax);
	write('moves.csv', moves.map(m => ({
		id: m.id,
		name: m.name,
		name_ko: koMove.get(m.id) || '',
		type: m.type,
		category: m.category,
		power: m.basePower,
		accuracy: m.accuracy === true ? '' : m.accuracy,
		pp: m.pp,
		priority: m.priority,
		target: m.target,
		flags: Object.keys(m.flags).join('|'),
		secondary_chance: m.secondary?.chance ?? '',
		short_desc: m.shortDesc,
	})));
	const legalMoves = new Set(moves.map(m => m.id));

	// --- learnsets (진화 전 단계에서 배우는 기술 포함) ---
	const learnsets = [];
	for (const p of pokemon) {
		if (p.is_mega) continue; // 메가는 원래 폼의 기술을 그대로 사용
		for (const moveId of dex.species.getMovePool(p.id)) {
			if (legalMoves.has(moveId)) learnsets.push({pokemon_id: p.id, move_id: moveId});
		}
	}
	write('learnsets.csv', learnsets);

	// --- items ---
	const items = dex.items.all().filter(i => i.exists && !i.isNonstandard);
	write('items.csv', items.map(i => ({
		id: i.id,
		name: i.name,
		name_ko: koItem.get(i.id) || MANUAL_KO[i.id] || '',
		// 최신 Showdown은 megaStone이 {기본종: 메가폼} 객체 (예전엔 문자열 + megaEvolves)
		mega_from: (i.megaStone && typeof i.megaStone === 'object' ? Object.keys(i.megaStone)[0] : i.megaEvolves) || '',
		mega_to: (i.megaStone && typeof i.megaStone === 'object' ? Object.values(i.megaStone)[0] : i.megaStone) || '',
		short_desc: i.shortDesc,
	})));

	// --- abilities (로스터 포켓몬이 가진 특성만) ---
	const usedAbilities = new Set(pokemon.flatMap(p =>
		[p.ability1, p.ability2, p.ability_hidden, p.ability_special].filter(Boolean)));
	write('abilities.csv', [...usedAbilities].sort().map(name => {
		const a = dex.abilities.get(name);
		return {id: a.id, name: a.name, name_ko: koAbility.get(a.id) || MANUAL_KO[a.id] || '', short_desc: a.shortDesc};
	}));

	// --- typechart ---
	const typechart = [];
	const types = dex.types.names().filter(t => t !== 'Stellar');
	for (const atk of types) {
		for (const def of types) {
			const multiplier = dex.getImmunity(atk, def) ? 2 ** dex.getEffectiveness(atk, def) : 0;
			typechart.push({attacking: atk, defending: def, multiplier});
		}
	}
	write('typechart.csv', typechart);
})().catch(e => { console.error(e); process.exit(1); });
