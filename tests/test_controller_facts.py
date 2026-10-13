import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from controller_facts import collect


class ControllerFactsTests(unittest.TestCase):
    def test_incremental_partial_tail_dedup_and_log_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);log=root/'real.jsonl';cache=root/'facts.json'
            events=[{'type':'session_meta','payload':{'id':'first'}},
                    {'type':'token_usage_record','payload':{'response_id':'r1','usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':5}}},
                    {'type':'response_item','payload':{'type':'function_call','name':'spawn_agent','call_id':'c1','arguments':json.dumps({'task_name':'build','model':'gpt-6.1-sol','reasoning_effort':'high','fork_turns':'none','message':'private message never cached'})}}]
            log.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
            first=collect(log,cache);self.assertEqual(first['unique_responses'],1)
            self.assertEqual(collect(log,cache)['new_events'],0)
            self.assertNotIn('private message',cache.read_text())
            response=json.dumps({'type':'response_item','payload':{'type':'function_call_output','call_id':'c1','output':'{"task_name":"/root/build"}'}})
            with log.open('a',encoding='utf-8') as stream:stream.write(response[:30])
            self.assertEqual(collect(log,cache)['calls'],[])
            with log.open('a',encoding='utf-8') as stream:
                stream.write(response[30:]+'\n'+json.dumps(events[1])+'\n')
            resumed=collect(log,cache)
            self.assertEqual(resumed['calls'][0]['agent_id'],'/root/build')
            self.assertEqual(resumed['usage']['input_tokens'],100)
            log.write_text(json.dumps({'type':'session_meta','payload':{'id':'second'}})+'\n',encoding='utf-8')
            self.assertEqual(collect(log,cache)['unique_responses'],0)


if __name__=='__main__':unittest.main()
