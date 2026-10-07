"""검수 전에 잘못된 도구 호출과 육성형 중복을 잡는 검사."""
import unittest

from agent.tools import TOOLS
from training.scripts.review_combined import sample_key, schema_errors
from training.scripts.compact_context import action_records, mask_last_response, prepare_messages, system_prompt


class ReviewValidationTest(unittest.TestCase):
    def test_missing_pokemon_and_removed_tool_are_rejected(self):
        records = [[{'role': 'assistant', 'tool_calls': [
            {'function': {'name': 'search_samples', 'arguments': {'role': '한카리아스'}}},
            {'function': {'name': 'analyze_party', 'arguments': {'members': []}}},
        ]}]]
        errors = schema_errors(records, TOOLS)
        self.assertEqual(len(errors), 2)
        self.assertTrue(any('pokemon' in e for e in errors))
        self.assertTrue(any('analyze_party' in e for e in errors))
        self.assertEqual(schema_errors([[{'role': 'assistant', 'tool_calls': [
            {'function': {'name': 'search_samples', 'arguments': {'pokemon': '한카리아스'}}}
        ]}]], TOOLS), [])

    def test_same_build_has_same_identity_despite_serialization(self):
        sample = {'pokemon': 'garchomp', 'item': 'lifeorb', 'ability': 'roughskin',
                  'nature': 'jolly', 'sp': {'atk': 32, 'spe': 32, 'hp': 2},
                  'moves': ['earthquake', 'protect', 'rockslide', 'dragonclaw']}
        duplicate = {**sample, 'sp': {**sample['sp'], 'def': 0, 'spa': 0, 'spd': 0},
                     'moves': list(reversed(sample['moves']))}
        self.assertEqual(sample_key(sample), sample_key(duplicate))
        self.assertNotEqual(sample_key(sample), sample_key({**sample, 'item': 'choicescarf'}))

    def test_input_reference_preserves_build_and_call_target_is_not_compressed(self):
        import json
        s = {'pokemon': 'garchomp', 'item': 'lifeorb', 'ability': 'roughskin',
             'nature': 'jolly', 'sp': {'hp': 2, 'atk': 32, 'spe': 32},
             'moves': ['earthquake', 'protect', 'rockslide', 'dragonclaw']}
        row = {'id': 'test', 'messages': [
            {'role': 'user', 'content': '예전 질문'}, {'role': 'assistant', 'content': '예전 답변'},
            {'role': 'user', 'content': '1. ' + json.dumps(s) + '\n도구를 바꿔 줘'},
            {'role': 'assistant', 'content': '', 'tool_calls': [
                {'function': {'name': 'search_samples', 'arguments': {'pokemon': '한카리아스'}}}]},
            {'role': 'tool', 'content': json.dumps({'samples': [{'sample': s}, {'sample': s}]})},
            {'role': 'assistant', 'content': '', 'tool_calls': [
                {'function': {'name': 'propose_party', 'arguments': {'members': [s]}}}]}]}
        actions = list(action_records(row, 'system'))
        self.assertEqual(len(actions), 2)  # 과거 턴의 답변은 새 정답으로 중복 생성하지 않음.
        self.assertEqual(actions[-1]['messages'][-1], row['messages'][-1])
        text = actions[-1]['messages'][-2]['content']
        registry = json.loads(text.split('[육성형 원문]\n')[1].split('\n\n')[0])
        self.assertEqual(list(registry.values()), [s])
        self.assertIn('sample_ref', text)
        self.assertIn('search_samples', text)
        self.assertIn('예전 답변', str(actions[-1]['messages']))

    def test_loss_only_covers_last_answer(self):
        result = mask_last_response({'input_ids': [1, 8, 9, 2, 3, 8, 9, 4, 5]}, [8, 9])
        self.assertEqual(result['labels'], [-100] * 7 + [4, 5])
        with self.assertRaises(ValueError):
            mask_last_response({'input_ids': [1, 2]}, [8, 9])

    def test_all_tools_are_present_and_missing_argument_remains_required(self):
        prompt = system_prompt('original', TOOLS)
        for t in TOOLS:
            self.assertIn(t['name'] + '(', prompt)
        self.assertIn('search_samples(pokemon:string,format?', prompt)

    def test_common_origin_is_never_split(self):
        from training.scripts.rebuild_colab_data import split_sources
        a = {'pokemon': 'garchomp', 'item': 'lifeorb', 'ability': 'roughskin',
             'nature': 'jolly', 'sp': {'atk': 32, 'spe': 32, 'hp': 2}, 'moves': ['earthquake']}
        def row(id, group, sample):
            return {'id': id, 'group': group, 'kind': 'sample_top', 'messages': [{'role': 'assistant', 'tool_calls': [
                {'function': {'name': 'propose_party', 'arguments': {'members': [sample]}}}]}]}
        rows = [row('a', 'team:1', a), row('b', 'pokemon:garchomp', a)]
        rows += [row(str(i), 'team:' + str(i), {**a, 'pokemon': 'p' + str(i)}) for i in range(2, 12)]
        splits, report = split_sources(rows, 42, .3)
        destination = {r['id']: split for split, rs in splits.items() for r in rs}
        self.assertEqual(destination['a'], destination['b'])
        self.assertEqual(report['shared_source_keys'], 0)
        self.assertEqual(report['eval_missing_kinds'], [])

    def test_completing_empty_moves_does_not_change_fixed_build(self):
        from training.scripts.rebuild_colab_data import fixed_kept
        s = {'pokemon': 'garchomp', 'item': 'lifeorb', 'ability': 'roughskin',
             'nature': 'jolly', 'sp': {'hp': 2, 'atk': 32, 'spe': 32}, 'moves': []}
        full = {**s, 'moves': ['earthquake', 'protect', 'rockslide', 'dragonclaw']}
        self.assertTrue(fixed_kept(s, [full]))
        self.assertFalse(fixed_kept(s, [{**full, 'item': 'choicescarf'}]))


if __name__ == '__main__':
    unittest.main()
