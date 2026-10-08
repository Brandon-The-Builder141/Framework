import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace as S
from unittest.mock import AsyncMock,patch
from pastor_ray.pastoral import plan_service
from pastor_ray.sermons import SermonSession

class PastoralTests(unittest.IsolatedAsyncioTestCase):
    async def test_general_request_selects_verified_scripture(self):
        plan={'title':'Steady Steps','purpose':'Put faith into action','references':['James 1:22-24'],'applications':['work','home','pressure']}
        brain=S(complete=AsyncMock(return_value=json.dumps(plan)))
        result=await plan_service(brain,'Lead a morning service')
        self.assertEqual(len(result['sources']),3)
        self.assertTrue(result['sources'][0].startswith('James 1:22 (KJV)'))

    async def test_fabricated_scripture_cannot_start_service(self):
        brain=S(complete=AsyncMock(return_value=json.dumps({'title':'Test','references':['Imaginary 99:1-3']})))
        with self.assertRaises(ValueError): await plan_service(brain,'choose a topic')
        self.assertEqual(brain.complete.await_count,2)

    async def test_first_section_plays_before_generation_finishes(self):
        played=asyncio.Event()
        async def build(brain,topic,minutes,**kwargs):
            await kwargs['on_section']('First real teaching section',1)
            await kwargs['on_section']('Exact reading',2)
            await asyncio.wait_for(played.wait(),1)
            await kwargs['on_section']('Closing prayer',3)
        bot=S(brain=S(),public_context=AsyncMock(return_value=[]))
        session=SermonSession(bot)
        session.topic='morning'
        session.announce=AsyncMock()
        session.set_listening=AsyncMock()
        session.play=AsyncMock(side_effect=lambda path:played.set())
        with tempfile.TemporaryDirectory() as folder,patch('pastor_ray.sermons.plan_service',AsyncMock(return_value={'title':'Chosen by Ray','sources':['source']})),patch('pastor_ray.sermons.build_service',build),patch('pastor_ray.sermons.synthesize',AsyncMock()):
            await asyncio.wait_for(session.stream_service(15,folder),3)
        self.assertEqual(session.play.await_count,3)
        self.assertIn('Closing prayer',session.transcript)

    async def test_stopping_cancels_producer_with_full_buffer(self):
        async def build(brain,topic,minutes,**kwargs):
            for i in range(20): await kwargs['on_section']('section',i)
        session=SermonSession(S(brain=S(),public_context=AsyncMock(return_value=[])))
        session.announce=AsyncMock()
        async def hold(path): await asyncio.Event().wait()
        session.play=hold
        with tempfile.TemporaryDirectory() as folder,patch('pastor_ray.sermons.plan_service',AsyncMock(return_value={'title':'Title','sources':[]})),patch('pastor_ray.sermons.build_service',build),patch('pastor_ray.sermons.synthesize',AsyncMock()):
            task=asyncio.create_task(session.stream_service(15,folder))
            await asyncio.sleep(.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(task,1)

    async def test_playback_waits_for_small_opening_reserve(self):
        ready=[]
        async def build(brain,topic,minutes,**kwargs):
            await kwargs['on_section']('Welcome',1)
            await kwargs['on_section']('Reading',2)
        async def synth(text,path):ready.append(text)
        async def play(path):self.assertEqual(ready,['Welcome','Reading'])
        session=SermonSession(S(brain=S(),public_context=AsyncMock(return_value=[])))
        session.announce=AsyncMock();session.play=play;session.set_listening=AsyncMock()
        with tempfile.TemporaryDirectory() as folder,patch('pastor_ray.sermons.plan_service',AsyncMock(return_value={'title':'Title','sources':[]})),patch('pastor_ray.sermons.build_service',build),patch('pastor_ray.sermons.synthesize',synth):
            await asyncio.wait_for(session.stream_service(20,folder),2)

    async def test_failure_after_first_section_is_propagated(self):
        async def build(brain,topic,minutes,**kwargs):
            await kwargs['on_section']('Opening',1)
            await kwargs['on_section']('Reading',2)
            raise RuntimeError('generation failed')
        session=SermonSession(S(brain=S(),public_context=AsyncMock(return_value=[])))
        session.announce=AsyncMock();session.play=AsyncMock();session.set_listening=AsyncMock()
        with tempfile.TemporaryDirectory() as folder,patch('pastor_ray.sermons.plan_service',AsyncMock(return_value={'title':'Title','sources':[]})),patch('pastor_ray.sermons.build_service',build),patch('pastor_ray.sermons.synthesize',AsyncMock()):
            with self.assertRaisesRegex(RuntimeError,'generation failed'):
                await asyncio.wait_for(session.stream_service(20,folder),2)
        self.assertEqual(session.play.await_count,2)

    async def test_three_verse_request_rejects_four(self):
        brain=S(complete=AsyncMock(return_value=json.dumps({'title':'Test','references':['James 1:22-25']})))
        with self.assertRaises(ValueError):await plan_service(brain,'Choose three related verses')
        self.assertIn('exactly 3 verses total',brain.complete.call_args_list[0].args[0][0]['content'])
        self.assertIn('previous plan selected 4',brain.complete.call_args_list[1].args[0][1]['content'])

    async def test_writing_continues_while_first_audio_is_generating(self):
        second_written=asyncio.Event()
        async def build(brain,topic,minutes,**kwargs):
            await kwargs['on_section']('first',1)
            second_written.set()
            await kwargs['on_section']('second',2)
        async def synth(text,path):
            await asyncio.wait_for(second_written.wait(),1)
        session=SermonSession(S(brain=S(),public_context=AsyncMock(return_value=[])))
        session.announce=AsyncMock();session.play=AsyncMock();session.set_listening=AsyncMock()
        with tempfile.TemporaryDirectory() as folder,patch('pastor_ray.sermons.plan_service',AsyncMock(return_value={'title':'Title','sources':[]})),patch('pastor_ray.sermons.build_service',build),patch('pastor_ray.sermons.synthesize',synth):
            await asyncio.wait_for(session.stream_service(20,folder),2)
        self.assertEqual(session.play.await_count,2)

    async def test_known_shaming_draft_is_rejected_before_model(self):
        from pastor_ray.services import review_section
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        ok,issues=await review_section(brain,'When a health scare overwhelms you, that is visible evidence that the foundation was sand.',[],[])
        self.assertFalse(ok)
        brain.complete.assert_not_awaited()

    async def test_invalid_review_does_not_approve_audio(self):
        from pastor_ray.services import review_section
        brain=S(complete=AsyncMock(return_value='Looks fine'))
        with self.assertRaises(ValueError):await review_section(brain,'Draft',[],[])

    async def test_independent_reviewer_rejects_writer_approved_content(self):
        from pastor_ray.services import review_section
        brain=S(complete=AsyncMock(return_value='{"ok":true}'),review=AsyncMock(return_value='{"ok":false,"issues":"Wrong chronology and conditional warning"}'))
        ok,issues=await review_section(brain,'A draft.',[],[])
        self.assertFalse(ok)
        self.assertIn('chronology',issues)
        brain.review.assert_awaited_once()
        brain.complete.assert_not_awaited()

    async def test_generated_labelled_readings_rejected_before_model_review(self):
        from pastor_ray.services import review_section
        for text in ('(Application: Matthew 7:25 - And it rained upon him, and there came a flood.)',
                     'Matthew 7:25 (KJV): invented words.',
                     '1 Corinthians 13:4 — invented words.'):
            brain=S(complete=AsyncMock(return_value='{"ok":true}'))
            ok,_=await review_section(brain,text,[],[])
            self.assertFalse(ok,text)
            brain.complete.assert_not_awaited()

    async def test_prose_scripture_references_can_be_reviewed(self):
        from pastor_ray.services import review_section
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        ok,_=await review_section(brain,'Matthew 7:25 describes the storm against the house.',[],[])
        self.assertTrue(ok)
        brain.complete.assert_awaited_once()

    async def test_invented_direct_attribution_rejected(self):
        from pastor_ray.services import review_section
        from pastor_ray.scripture import passages
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        ok,_=await review_section(brain,'When you hear Jesus say, "Be diligent," make the call.',passages('Matthew 7:24-26'),[])
        self.assertFalse(ok)
        brain.complete.assert_not_awaited()

    async def test_grounded_direct_attribution_can_be_reviewed(self):
        from pastor_ray.services import review_section
        from pastor_ray.scripture import passages
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        ok,_=await review_section(brain,'Jesus says, "I will liken him unto a wise man".',passages('Matthew 7:24-26'),[])
        self.assertTrue(ok)

    async def test_unlabelled_biblical_paraphrase_cannot_pass_as_quote(self):
        from pastor_ray.services import review_section
        from pastor_ray.scripture import passages
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        ok,_=await review_section(brain,'The wise builder hears the word, "Trust in the Lord always," and does it.',passages('Matthew 7:24-26'),[])
        self.assertFalse(ok)
        brain.complete.assert_not_awaited()

    async def test_context_verse_cannot_replace_selected_second_verse(self):
        from pastor_ray.services import review_section
        from pastor_ray.scripture import passages
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        selected=passages('Hebrews 11:1; Romans 1:17; 2 Corinthians 5:7')
        ok,reason=await review_section(brain,'The second verse, Hebrews 11:2, speaks of the elders.',selected,passages('Hebrews 11:1-3'),selected[1:2])
        self.assertFalse(ok)
        self.assertIn('Romans 1:17',reason)
        brain.complete.assert_not_awaited()

    async def test_reference_colon_can_introduce_explanation(self):
        from pastor_ray.services import review_section
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        ok,_=await review_section(brain,'This connects to 1 John 1:6: our actions must match what we say.',[],[])
        self.assertTrue(ok)

    async def test_title_and_explicit_modern_explanation_are_not_scripture_quotes(self):
        from pastor_ray.services import review_section
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        ok,_=await review_section(brain,'Today our topic is "Walking By Faith." In plain English, "keep going" explains the application.',[],[])
        self.assertTrue(ok)
        brain.complete.assert_awaited_once()

    async def test_example_near_reference_is_not_mistaken_for_scripture(self):
        from pastor_ray.services import review_section
        from pastor_ray.scripture import passages
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        text='Philippians 4:13 is the believer\'s response that says, for example, "Even when I feel overwhelmed by bills, I can seek support."'
        ok,_=await review_section(brain,text,passages('Philippians 4:13'),[])
        self.assertTrue(ok)

    async def test_reference_introducing_fabricated_quote_is_rejected(self):
        from pastor_ray.services import review_section
        from pastor_ray.scripture import passages
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        ok,_=await review_section(brain,'Philippians 4:13 states plainly, "You will pay off all your bills."',passages('Philippians 4:13'),[])
        self.assertFalse(ok)
        brain.complete.assert_not_awaited()

    async def test_rewrite_receives_all_detected_corrections(self):
        from pastor_ray.services import review_section
        from pastor_ray.scripture import passages
        brain=S(complete=AsyncMock())
        ok,issues=await review_section(brain,'Matthew 7:25 (KJV): "invented words"',passages('Matthew 7:24-26'),[],passages('Matthew 7:24'))
        self.assertFalse(ok)
        self.assertIn('Matthew 7:24',issues)
        self.assertIn('verse-labelled',issues)
        self.assertIn('invented words',issues)

    async def test_opening_is_short_and_scripture_is_separate_audio(self):
        from pastor_ray.services import build_service
        from pastor_ray.scripture import passages
        calls=[]
        brain=S(complete=AsyncMock(return_value=('Useful explanation. '*250)+'Amen.'))
        async def section(text,index):calls.append((text,index))
        await build_service(brain,'morning',15,on_section=section,verified_sources=passages('James 1:22-24'))
        self.assertEqual([index for _,index in calls],list(range(1,10)))
        self.assertNotIn('James 1:22 (KJV)',calls[0][0])
        self.assertIn('James 1:22 (KJV)',calls[1][0])
        self.assertIn('Aim for 80 words',str(brain.complete.call_args_list[0]))

    async def test_financial_giving_as_remedy_is_rejected(self):
        from pastor_ray.services import review_section
        brain=S(complete=AsyncMock(return_value='{"ok":true}'))
        ok,_=await review_section(brain,'Facing financial uncertainty, he might deliberately increase his tithes, trusting that the seed sown will yield a harvest.',[],[])
        self.assertFalse(ok)
        brain.complete.assert_not_awaited()

    async def test_truncated_closing_is_never_emitted(self):
        from pastor_ray.services import build_service
        from pastor_ray.scripture import passages
        normal=('Useful explanation. '*250)+'Amen.'
        truncated=('Useful explanation. '*250)+'and when the storm'
        brain=S(complete=AsyncMock(side_effect=[normal]*7+[truncated,truncated]))
        emitted=[]
        async def section(text,index):emitted.append(text)
        with self.assertRaisesRegex(ValueError,'incomplete'):
            await build_service(brain,'morning',15,on_section=section,verified_sources=passages('James 1:22-24'))
        self.assertFalse(any(text.endswith('and when the storm') for text in emitted))
