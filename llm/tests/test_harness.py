"""설명 하네스: 점수 계산·자동 검사 (DB·모델 없이)."""
import json
import unittest
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from harness import rubric
from harness.live import Live

PACKET = {
    'kind': 'sample', 'format': '싱글', 'source': 'OP.GG 샘플',
    'pokemon': {'name_ko': '한카리아스', 'types': ['드래곤', '땅']},
    'item': {'name_ko': '구애스카프'}, 'moves': [{'name_ko': '지진'}, {'name_ko': '역린'}],
    'roles': ['물리 딜러'], 'sp': 'A32 S32', 'speed': 169,
    'others': [{'item': '생명의구슬', 'role': '물리 딜러'}],
}
GROUND = json.dumps(PACKET, ensure_ascii=False)
VOCAB = {'pokemon': ['한카리아스', '망나뇽'], 'move': ['지진', '역린', '스톤에지'], 'item': ['구애스카프', '생명의구슬']}
GOOD = ('구애스카프로 선공을 잡는 물리 딜러예요. 생명의구슬형과 달리 스피드에 SP를 몰아 빠른 상대보다 먼저 지진과 역린을 꽂아요. '
        '기술이 묶이니 막이가 나오면 바로 교체하는 게 좋아요.')


def ids(fails):
    return {f['id'] for f in fails}


class ScoreTest(unittest.TestCase):
    def test_full_marks(self):
        sc = rubric.score('sample', [], {})
        self.assertEqual(sc['total'], 100)
        self.assertTrue(sc['pass'])

    def test_items_sum_to_100(self):
        for kind in rubric.ITEMS:
            self.assertEqual(sum(full for _, full, _ in rubric.ITEMS[kind].values()), 100)

    def test_one_effect_mistake_fails_min(self):
        sc = rubric.score('sample', [{'rule': 'J1-a', 'quote': 'x', 'fix': ''}], {})
        self.assertEqual(sc['items']['J1'], 10)
        self.assertEqual(sc['below_min'], ['J1'])
        self.assertFalse(sc['pass'])           # 합계 90이어도 최소점수 미달

    def test_non_repeatable_rule_counts_once(self):
        d = [{'rule': 'J6-a', 'quote': 'a'}, {'rule': 'J6-a', 'quote': 'b'}]
        self.assertEqual(rubric.score('sample', d, {})['items']['J6'], 5)

    def test_per_instance_rule_stacks(self):
        d = [{'rule': 'J6-e', 'quote': 'a'}, {'rule': 'J6-e', 'quote': 'b'}]
        self.assertEqual(rubric.score('sample', d, {})['items']['J6'], 8)

    def test_party_scaling(self):
        self.assertEqual(rubric.rule_points('J5-a', 'party'), round(4 * 8 / 10))
        self.assertEqual(rubric.rule_points('J2-a', 'party'), 5)
        self.assertEqual(rubric.rule_points('J3-a', 'party'), 10)

    def test_na_rescales_and_core_items_cannot_be_na(self):
        sc = rubric.score('sample', [{'rule': 'J5-a'}], {'S1': '샘플 하나뿐', 'J1': '안 됨'})
        self.assertEqual(sc['na'], {'S1': '샘플 하나뿐'})
        self.assertEqual(sc['total'], round(84 * 100 / 88, 1))

    def test_too_many_na(self):
        sc = rubric.score('party', [], {'P3': 'a', 'J4': 'b', 'J5': 'c'})
        self.assertTrue(sc['too_many_na'])
        self.assertFalse(sc['pass'])

    def test_rubric_text_has_every_rule(self):
        text = rubric.rubric_text('party')
        self.assertIn('P3-c', text)
        self.assertNotIn('S1-a', text)


class AutoCheckTest(unittest.TestCase):
    def check(self, text, packet=PACKET, **kw):
        return rubric.auto_check('sample', text, packet, GROUND, VOCAB, **kw)

    def test_good_passes(self):
        self.assertEqual(self.check(GOOD), [])

    def test_ungrounded_number(self):
        self.assertIn('A1', ids(self.check(GOOD.replace('꽂아요.', '꽂아 60% 대미지를 줘요.'))))

    def test_count_words_allowed(self):
        self.assertNotIn('A1', ids(self.check(GOOD.replace('지진과 역린을', '기술 2개를'))))

    def test_ungrounded_names(self):
        f = ids(self.check(GOOD.replace('지진과 역린을', '스톤에지를').replace('빠른 상대', '망나뇽')))
        self.assertTrue({'A2', 'A3'} <= f)

    def test_role_in_first_sentence(self):
        self.assertIn('A4', ids(self.check(GOOD.replace('물리 딜러예요', '물리막이예요'))))

    def test_doubles_term(self):
        self.assertIn('A5', ids(self.check(GOOD + ' 기점잡이와 같이 써요.', {**PACKET, 'format': '더블'})))

    def test_source(self):
        self.assertIn('A6', ids(self.check(GOOD.replace('좋아요.', '좋아요. 대회에서 쓰인 형태예요.'))))

    def test_markdown_and_foreign(self):
        self.assertIn('A7', ids(self.check('**' + GOOD)))
        self.assertIn('A7', ids(self.check(GOOD + ' 強い')))

    def test_length(self):
        self.assertIn('A8', ids(self.check('물리 딜러예요.')))

    def test_banned(self):
        self.assertIn('A9', ids(self.check(GOOD.replace('물리 딜러예요', '최강의 물리 딜러예요'))))

    def test_duplicate(self):
        self.assertIn('A10', ids(self.check(GOOD, others=[GOOD.replace('좋아요', '좋습니다')])))

    def test_mega_name(self):
        p = {**PACKET, 'pokemon': {'name_ko': '메가한카리아스', 'mega_from': '한카리아스'}}
        g = json.dumps(p, ensure_ascii=False)
        f = rubric.auto_check('sample', GOOD + ' 한카리아스는 무섭게 때려요.', p, g, VOCAB)
        self.assertIn('A11', ids(f))
        self.assertNotIn('A11', ids(rubric.auto_check('sample', GOOD + ' 메가한카리아스는 무섭게 때려요.', p, g, VOCAB)))


class LiveTest(unittest.TestCase):
    def test_events_stream_and_log(self):
        with TemporaryDirectory() as d:
            live = Live(Path(d) / 'log.jsonl', port=18765, quiet=True)
            live.channel('S-1', '한카리아스', 'sample', PACKET)
            on_delta, end = live.stream('S-1', 'writer', 'Claude')
            on_delta('text', '구애')
            end('구애스카프')
            page = urllib.request.urlopen('http://127.0.0.1:18765/').read().decode()
            self.assertIn('EventSource', page)
            with urllib.request.urlopen('http://127.0.0.1:18765/events', timeout=5) as r:
                first = [r.readline().decode() for _ in range(2)][0]
            self.assertIn('"channel"', first)
            types = [json.loads(x)['type'] for x in (Path(d) / 'log.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(types, ['channel', 'msg_start', 'msg_end'])     # 조각(delta)은 로그에 안 남김
            live.log.close()


class LoopTest(unittest.TestCase):
    """2026-10-23 실제로 21바퀴 돈 순환을 가짜 모델로 재현: 긴 설명(93점) ↔ 줄인 설명(89점)."""

    LONG = GOOD + ' 먼저 때려야 할 상대 앞에 꺼내 지진부터 써요.'
    SHORT = GOOD

    def make(self, writer):
        from types import SimpleNamespace

        from harness import run
        h = run.Harness.__new__(run.Harness)
        h.a = SimpleNamespace(max_rounds=0, writer='claude', judge='codex', writer_model=None, judge_model=None)
        h.live = Live(Path(self.tmp.name) / 'log.jsonl', port=None, quiet=True)
        h.vocab = VOCAB
        h.calls = {'write': 0, 'judge': 0, 'feedback': []}

        def write(ch, kind, packet, prev, feedback, label):
            h.calls['write'] += 1
            h.calls['feedback'].append(feedback)
            return writer(prev, feedback)

        def judge(ch, kind, packet, text):
            h.calls['judge'] += 1
            if text == self.LONG:       # 내용은 다 있는데 명령조·길이
                return [{'rule': 'J6-a', 'quote': '', 'fix': '권유로'}, {'rule': 'J6-c', 'quote': '', 'fix': '군더더기'}], {}
            return [{'rule': 'J3-b', 'quote': '', 'fix': f'역린 이유 {h.calls["judge"]}'},     # fix 문구가 매번 다름
                    {'rule': 'J5-a', 'quote': '', 'fix': '언제'}, {'rule': 'J5-b', 'quote': '', 'fix': '먼저'}], {}

        h.write, h.judge = write, judge
        store = run.Store.__new__(run.Store)
        store.rows, store.path = {}, Path(self.tmp.name) / 'out.jsonl'
        return h, store

    def setUp(self):
        self.tmp = TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_stuck_writer_stops(self):
        """고쳐도 늘 줄인 설명만 내는 작성자 → 맴돌기 감지로 멈추고 보류 (예전에는 무한 반복)."""
        def writer(prev, feedback):
            return self.LONG if prev is None else self.SHORT
        h, store = self.make(writer)
        row = h.run_one('sample', 'S-1', 't', PACKET, None, store)
        h.live.log.close()
        self.assertEqual(row['status'], 'held')
        self.assertLessEqual(h.calls['judge'], 6)
        self.assertEqual(row['text'], self.LONG)            # 가장 좋았던 설명을 저장
        fb = '\n'.join(sum(h.calls['feedback'], []))
        self.assertIn('[남겨 두기]', fb)                    # 줄이다가 뺀 내용을 알려 줌
        self.assertIn('계속 반복되는 지적', fb)               # 문구가 달라도 같은 규칙이면 반복으로 셈

    def test_writer_that_listens_passes(self):
        """[남겨 두기]를 받으면 내용을 지키며 고치는 작성자 → 통과."""
        fixed = self.LONG.replace('교체하는 게 좋아요', '교체가 나아요')

        def writer(prev, feedback):
            if prev is None:
                return self.LONG
            return fixed if any('[남겨 두기]' in x for x in feedback) else self.SHORT
        h, store = self.make(writer)
        orig = h.judge
        h.judge = lambda ch, kind, packet, text: ([], {}) if text == fixed else orig(ch, kind, packet, text)
        row = h.run_one('sample', 'S-1', 't', PACKET, None, store)
        h.live.log.close()
        self.assertEqual(row['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
