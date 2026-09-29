"""DB 확인용 임시 페이지 (읽기 전용).

실행: streamlit run ui/db_viewer.py
"""
import base64
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pokemon.db"
ASSETS = ROOT / "assets"  # scripts/download_assets.py로 받음

st.set_page_config(page_title="Pokémon DB Viewer", layout="wide")


@st.cache_resource
def conn() -> sqlite3.Connection:
    # 읽기 전용으로 열어서 실수로 데이터가 바뀌지 않게 함
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)


@st.cache_data
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn(), params=params)


@st.cache_resource
def icons(kind: str) -> dict[str, str]:
    """assets/{kind}/*.png → {파일명(DB ID): data URI}. 폴더가 없으면 빈 dict (아이콘 없이 표시)."""
    folder = ASSETS / kind
    if not folder.exists():
        return {}
    return {f.stem: "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()
            for f in folder.glob("*.png")}


def icon(kind: str, key) -> str | None:
    return icons(kind).get(key) if isinstance(key, str) else None


def img_col(label: str = "", width: str = "small"):
    return st.column_config.ImageColumn(label, width=width)


if not DB_PATH.exists():
    st.error(f"DB 파일이 없습니다: {DB_PATH}\n\n`python scripts/load_db.py`로 먼저 만들어 주세요.")
    st.stop()

page = st.sidebar.radio("페이지", ["테이블", "사용률", "파티", "SQL"])
if not icons("pokemon"):
    st.sidebar.caption("아이콘을 보려면 `python scripts/download_assets.py`를 실행하세요.")


# ---------------------------------------------------------------------------
# 테이블: 아무 테이블이나 골라서 보기 + 검색
# ---------------------------------------------------------------------------
if page == "테이블":
    tables = q("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")["name"].tolist()
    counts = {t: q(f'SELECT COUNT(*) n FROM "{t}"')["n"][0] for t in tables}
    table = st.sidebar.selectbox("테이블", tables, format_func=lambda t: f"{t} ({counts[t]:,})")
    df = q(f'SELECT * FROM "{table}"')

    c1, c2 = st.columns([3, 1])
    keyword = c1.text_input("검색 (모든 컬럼에서 포함 여부)")
    if "ruleset_id" in df.columns:
        rulesets = ["전체", *sorted(df["ruleset_id"].dropna().unique())]
        rs = c2.selectbox("레귤레이션", rulesets)
        if rs != "전체":
            df = df[df["ruleset_id"] == rs]
    if keyword:
        mask = df.astype(str).apply(lambda col: col.str.contains(keyword, case=False, regex=False)).any(axis=1)
        df = df[mask]

    # 포켓몬/도구 테이블은 앞쪽에 아이콘 컬럼 추가
    config = {}
    if table == "pokemon":
        df = df.copy()
        df.insert(0, "이미지", df["id"].map(lambda k: icon("pokemon", k)))
        df.insert(df.columns.get_loc("type1") + 1, "타입1", df["type1"].map(lambda k: icon("types", k)))
        df.insert(df.columns.get_loc("type2") + 1, "타입2", df["type2"].map(lambda k: icon("types", k)))
        config = {"이미지": img_col(), "타입1": img_col(), "타입2": img_col()}
    elif table == "item":
        df = df.copy()
        df.insert(0, "아이콘", df["id"].map(lambda k: icon("items", k)))
        config = {"아이콘": img_col()}

    st.caption(f"{table}: {len(df):,}행")
    st.dataframe(df, use_container_width=True, hide_index=True, height=650, column_config=config,
                 row_height=40 if table == "pokemon" else None)


# ---------------------------------------------------------------------------
# 사용률: 포켓몬 하나 골라서 기술/도구/특성/성격/SP 사용률을 한글로
# ---------------------------------------------------------------------------
elif page == "사용률":
    groups = q("""SELECT DISTINCT ruleset_id, format_id, source, season FROM usage_stat
                  ORDER BY ruleset_id DESC, source, format_id""")
    labels = [f"{r.source} · {r.format_id} · {r.season}" for r in groups.itertuples()]
    g = groups.iloc[st.sidebar.selectbox("데이터", range(len(labels)), format_func=lambda i: labels[i])]

    ranking = q("""SELECT u.id, u.rank AS 순위, p.name_ko AS 포켓몬, u.usage_pct AS "사용률%", u.pokemon_id
                   FROM usage_stat u
                   LEFT JOIN pokemon p ON p.ruleset_id = u.ruleset_id AND p.id = u.pokemon_id
                   WHERE u.ruleset_id=? AND u.format_id=? AND u.source=? AND u.season=?
                   ORDER BY u.rank""", (g.ruleset_id, g.format_id, g.source, g.season))

    left, right = st.columns([1, 2])
    with left:
        st.subheader("순위")
        view = ranking.drop(columns=["id", "pokemon_id"])
        view.insert(1, "이미지", ranking["pokemon_id"].map(lambda k: icon("pokemon", k)))
        if view["사용률%"].isna().all():  # OP.GG는 순위만 있음
            view = view.drop(columns=["사용률%"])
        st.dataframe(view, hide_index=True, height=700, use_container_width=True,
                     column_config={"이미지": img_col()}, row_height=40)
    with right:
        names = ranking["포켓몬"].fillna(ranking["pokemon_id"]).tolist()
        idx = st.selectbox("포켓몬", range(len(names)), format_func=lambda i: f"{ranking['순위'][i]}위 {names[i]}")
        stat_id = int(ranking["id"][idx])
        pid = ranking["pokemon_id"][idx]
        info = q("SELECT type1, type2, hp, atk, def, spa, spd, spe FROM pokemon WHERE ruleset_id=? AND id=?",
                 (g.ruleset_id, pid))
        head = st.columns([1, 5])
        if icon("pokemon", pid):
            head[0].image(icon("pokemon", pid), width=96)
        with head[1]:
            st.markdown(f"### {names[idx]}")
            if not info.empty:
                r = info.iloc[0]
                types = [t for t in (r.type1, r.type2) if t and icon("types", t)]
                if types:
                    st.image([icon("types", t) for t in types], width=90)
                st.caption(f"H{r.hp} / A{r['atk']} / B{r['def']} / C{r.spa} / D{r.spd} / S{r.spe}")
        detail = q("""
            SELECT d.kind, d.target_id, d.pct,
                   COALESCE(m.name_ko, i.name_ko, a.name_ko, n.name_ko, p.name_ko) AS name_ko
            FROM usage_detail d
            JOIN usage_stat u ON u.id = d.usage_stat_id
            LEFT JOIN move m    ON d.kind='move'     AND m.ruleset_id=u.ruleset_id AND m.id=d.target_id
            LEFT JOIN item i    ON d.kind='item'     AND i.ruleset_id=u.ruleset_id AND i.id=d.target_id
            LEFT JOIN ability a ON d.kind='ability'  AND a.ruleset_id=u.ruleset_id AND a.id=d.target_id
            LEFT JOIN nature n  ON d.kind='nature'   AND n.id=d.target_id
            LEFT JOIN pokemon p ON d.kind='teammate' AND p.ruleset_id=u.ruleset_id AND p.id=d.target_id
            WHERE d.usage_stat_id=? ORDER BY d.pct DESC""", (stat_id,))

        kinds = [("move", "기술"), ("item", "도구"), ("ability", "특성"), ("nature", "성격"),
                 ("spread", "SP 배분 (HP/공/방/특공/특방/스피드)"), ("teammate", "동료")]
        cols = st.columns(2)
        shown = 0
        for kind, label in kinds:
            part = detail[detail["kind"] == kind]
            if part.empty:
                continue
            with cols[shown % 2]:
                st.markdown(f"**{label}**")
                view = pd.DataFrame({"이름": part["name_ko"].fillna(part["target_id"]), "%": part["pct"]})
                config, height = {}, None
                if kind in ("item", "teammate"):
                    folder = "items" if kind == "item" else "pokemon"
                    view.insert(0, " ", part["target_id"].map(lambda k: icon(folder, k)).values)
                    config, height = {" ": img_col()}, (32 if kind == "teammate" else None)
                st.dataframe(view, hide_index=True, use_container_width=True, column_config=config,
                             row_height=height)
            shown += 1


# ---------------------------------------------------------------------------
# 파티: 출처/포맷별 파티 목록 → 멤버 6마리
# ---------------------------------------------------------------------------
elif page == "파티":
    sources = q("SELECT DISTINCT source FROM team ORDER BY source")["source"].tolist()
    source = st.sidebar.selectbox("출처", sources)
    formats = q("SELECT DISTINCT format_id FROM team WHERE source=? ORDER BY 1", (source,))["format_id"].tolist()
    fmt = st.sidebar.selectbox("포맷", formats)

    teams = q("""SELECT t.id, t.name AS 이름, t.player AS 플레이어, t.rating AS 레이팅, t.result AS 결과,
                        t.played_on AS 날짜,
                        GROUP_CONCAT(COALESCE(p.name_ko, m.pokemon_id), ', ') AS 멤버
                 FROM team t
                 JOIN team_member m ON m.team_id = t.id
                 LEFT JOIN pokemon p ON p.ruleset_id = t.ruleset_id AND p.id = m.pokemon_id
                 WHERE t.source=? AND t.format_id=?
                 GROUP BY t.id ORDER BY t.id""", (source, fmt))
    keyword = st.text_input("멤버 검색 (예: 한카리아스)")
    if keyword:
        teams = teams[teams["멤버"].str.contains(keyword, regex=False)]

    # 멤버 6마리를 이미지 컬럼 1~6으로
    slots = q("""SELECT m.team_id, m.slot, m.pokemon_id FROM team_member m JOIN team t ON t.id = m.team_id
                 WHERE t.source=? AND t.format_id=?""", (source, fmt))
    grid = slots.pivot(index="team_id", columns="slot", values="pokemon_id")
    teams = teams.reset_index(drop=True)
    for n in range(1, 7):
        col = grid[n] if n in grid.columns else pd.Series(dtype=object)
        teams.insert(n, str(n), teams["id"].map(col).map(lambda k: icon("pokemon", k)))
    team_config = {str(n): img_col() for n in range(1, 7)}
    st.caption(f"{len(teams):,}개 파티 — 행을 클릭하면 아래에 상세가 나옵니다")
    sel = st.dataframe(teams, hide_index=True, use_container_width=True, height=400, row_height=40,
                       column_config=team_config, on_select="rerun", selection_mode="single-row")

    rows = sel.selection.rows
    if rows:
        team_id = int(teams.iloc[rows[0]]["id"])
        members = q("""
            SELECT m.slot AS 슬롯, m.pokemon_id AS _pid, COALESCE(p.name_ko, m.pokemon_id) AS 포켓몬,
                   m.item_id AS _iid, COALESCE(i.name_ko, m.item_id) AS 도구, COALESCE(a.name_ko, m.ability_id) AS 특성,
                   COALESCE(n.name_ko, m.nature_id) AS 성격,
                   m.sp_hp||'/'||m.sp_atk||'/'||m.sp_def||'/'||m.sp_spa||'/'||m.sp_spd||'/'||m.sp_spe AS SP,
                   COALESCE(m1.name_ko, m.move1) AS 기술1, COALESCE(m2.name_ko, m.move2) AS 기술2,
                   COALESCE(m3.name_ko, m.move3) AS 기술3, COALESCE(m4.name_ko, m.move4) AS 기술4,
                   m.is_gimmick_user AS 메가, m.brought AS 출전, m.lead AS 선봉
            FROM team_member m
            JOIN team t ON t.id = m.team_id
            LEFT JOIN pokemon p ON p.ruleset_id=t.ruleset_id AND p.id=m.pokemon_id
            LEFT JOIN item i    ON i.ruleset_id=t.ruleset_id AND i.id=m.item_id
            LEFT JOIN ability a ON a.ruleset_id=t.ruleset_id AND a.id=m.ability_id
            LEFT JOIN nature n  ON n.id=m.nature_id
            LEFT JOIN move m1   ON m1.ruleset_id=t.ruleset_id AND m1.id=m.move1
            LEFT JOIN move m2   ON m2.ruleset_id=t.ruleset_id AND m2.id=m.move2
            LEFT JOIN move m3   ON m3.ruleset_id=t.ruleset_id AND m3.id=m.move3
            LEFT JOIN move m4   ON m4.ruleset_id=t.ruleset_id AND m4.id=m.move4
            WHERE m.team_id=? ORDER BY m.slot""", (team_id,))
        members.insert(1, "이미지", members["_pid"].map(lambda k: icon("pokemon", k)))
        members.insert(members.columns.get_loc("도구"), "아이콘", members["_iid"].map(lambda k: icon("items", k)))
        members = members.drop(columns=["_pid", "_iid"])
        st.subheader(f"파티 #{team_id}")
        st.dataframe(members, hide_index=True, use_container_width=True, row_height=56,
                     column_config={"이미지": img_col(), "아이콘": img_col()})


# ---------------------------------------------------------------------------
# SQL: 직접 쿼리 (읽기 전용)
# ---------------------------------------------------------------------------
else:
    default = """SELECT p.name_ko, p.type1, p.type2, p.bst
FROM pokemon p
WHERE p.ruleset_id = 'champions_mc' AND p.is_mega = 1
ORDER BY p.bst DESC
LIMIT 20"""
    sql = st.text_area("SQL (읽기 전용)", default, height=180)
    if st.button("실행", type="primary"):
        try:
            st.dataframe(pd.read_sql_query(sql, conn()), hide_index=True, use_container_width=True)
        except Exception as e:  # 잘못된 쿼리는 에러 메시지만 표시
            st.error(str(e))
