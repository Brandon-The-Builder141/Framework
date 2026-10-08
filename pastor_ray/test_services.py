import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pastor_ray.sermons import intent,parse_topic,build_sermon,question_context
from pastor_ray.services import service_passage,build_service


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_request_phrases_and_duration(self):
        for text in ('Ray, give me a morning sermon','I want a morning sermon','Can you give us a morning service?'):
            self.assertEqual(intent(text),('sermon','morning service'))
        self.assertEqual(intent('Give me a 20-minute morning sermon on hope'),('sermon','morning service hope 20 minutes'))
        self.assertEqual(parse_topic('morning service'),('morning service',15))
        self.assertEqual(parse_topic('morning 20 minutes'),('morning',20))
        self.assertEqual(parse_topic('hope 12 minutes'),('hope',12))
        self.assertIsNone(intent("Don't give me a morning sermon"))

    def test_detailed_natural_request_is_not_rejected_as_too_long(self):
        request='morning service titled Built on Rock. '+('Explain context and practical applications. '*8)+'20 minutes'
        topic,minutes=parse_topic(request)
        self.assertGreater(len(topic),250)
        self.assertEqual(minutes,20)

    def test_explicit_three_verses_preserved(self):
        self.assertEqual(len(service_passage('Built on Rock Matthew 7:24; Isaiah 26:4; James 1:22')),3)

    def test_context_includes_historical_setting_and_warning_condition(self):
        from pastor_ray.services import passage_context
        from pastor_ray.scripture import passages
        context=passage_context(passages('Joshua 23:13'))
        self.assertTrue(any('Joshua 23:1 (KJV)' in line and 'rest' in line for line in context))
        self.assertTrue(any('Joshua 23:12 (KJV)' in line for line in context))

    def test_short_contiguous_source(self):
        for topic in ('morning','morning service','forgiveness','John 3:16'):
            verses=service_passage(topic)
            self.assertEqual(len(verses),4)
        self.assertTrue(service_passage('morning')[0].startswith('Lamentations 3:22'))
        self.assertEqual(service_passage('morning service parenting'),[])

    def test_long_service_question_keeps_relevant_application(self):
        transcript='Opening. '*800+'\n\nReconciliation means rebuilding trust over time.\n\n'+'Other context. '*500+'\n\n'+'Closing prayer. '*300
        excerpt=question_context(transcript,'What does reconciliation mean?')
        self.assertIn('Reconciliation means rebuilding trust',excerpt)
        self.assertIn('Closing prayer',excerpt)
        self.assertLess(len(excerpt),12000)

    async def test_structured_sections_and_exact_reading(self):
        brain=SimpleNamespace(complete=AsyncMock(return_value=('Meaningful explanation. '*200)+'Amen.'))
        sources,text=await build_sermon(brain,'morning',15)
        self.assertEqual(len(sources),4)
        self.assertEqual(brain.complete.await_count,8)
        self.assertIn(sources[0],text)
        prompts=' '.join(str(c) for c in brain.complete.call_args_list)
        self.assertIn('literary setting',prompts)
        self.assertIn('everyday applications',prompts)

    async def test_teaching_uses_dedicated_model_path(self):
        brain=SimpleNamespace(complete=AsyncMock(),teach=AsyncMock(return_value=('Meaningful explanation. '*200)+'Amen.'))
        await build_service(brain,'morning',15)
        self.assertEqual(brain.teach.await_count,8)
        brain.complete.assert_not_awaited()

    async def test_unverified_original_language_claim_fails_before_model_review(self):
        from pastor_ray.services import review_section
        brain=SimpleNamespace(complete=AsyncMock(),review=AsyncMock())
        ok,issues=await review_section(brain,'The Greek word eides means evidence.',[],[])
        self.assertFalse(ok)
        self.assertIn('lexicon',issues)
        brain.review.assert_not_awaited()

    async def test_false_exact_kjv_claim_after_quote_is_rejected(self):
        from pastor_ray.services import review_section
        brain=SimpleNamespace(complete=AsyncMock())
        ok,_=await review_section(brain,'The phrase "Trust everyone blindly" is an exact quotation from the KJV.',[],[],model_review=False)
        self.assertFalse(ok)
        brain.complete.assert_not_awaited()

    async def test_short_draft_rejected(self):
        brain=SimpleNamespace(complete=AsyncMock(return_value='Too short.'))
        with self.assertRaises(ValueError): await build_service(brain,'morning',15)


if __name__=='__main__': unittest.main()
