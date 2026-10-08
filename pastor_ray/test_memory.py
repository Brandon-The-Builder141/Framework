import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import AsyncMock
import httpx
from pastor_ray.storage import Store
from pastor_ray.brain import Brain
from pastor_ray import discipleship
from pastor_ray.settings import load_config


class DurableMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'ray.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_first_conversation_survives_ninety_days_and_restart(self):
        self.store.remember_turn(1,'My brother is named Michael.','Thank you for sharing.')
        with self.store.db:
            self.store.db.execute('UPDATE turns SET created_at=?',(time.time()-90*86400,))
        for i in range(100):
            self.store.remember_turn(1,f'Later conversation {i}','Reply')
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.retrieve(1,'our first conversation')[0]['content'],'My brother is named Michael.')
        self.assertIn('Michael',self.store.retrieve(1,'my brother')[0]['content'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM turns').fetchone()[0],202)
        self.assertEqual(self.store.retrieve(2,'Michael'),[])

    def test_old_relevant_fact_and_new_correction_both_retrieved(self):
        self.store.remember_turn(1,'Michael my brother lost his job. Michael is unemployed.','Reply')
        for i in range(15):
            self.store.remember_turn(1,f'Michael job search update number {i}','Reply')
        self.store.remember_turn(1,'Correction: Michael is employed now.','Reply')
        records=self.store.retrieve(1,'Michael brother job')
        self.assertTrue(any('my brother' in r['content'] for r in records))
        self.assertTrue(any('employed now' in r['content'] for r in records))
        self.assertLessEqual(len(records),8)

    def test_discord_redelivery_does_not_duplicate_archive(self):
        first = self.store.archive(1,'user','Original message',source_id=12345)
        self.assertIsNotNone(first)
        self.assertIsNone(self.store.archive(1,'user','Original message',source_id=12345))
        self.assertEqual(len(self.store.history(1)),1)

    def test_semantic_search_and_forget_including_backup(self):
        self.store.remember_turn(1,'I am mourning my dad.','Reply')
        self.store.remember_turn(2,'Other private story','Reply')
        self.store.save_vectors(self.store.unembedded(1),[[1.,0.]])
        self.store.save_vectors(self.store.unembedded(2),[[1.,0.]])
        result = self.store.retrieve(1,'bereavement',[1.,0.])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['uid'],'1')
        self.store.save_plan(1,{'topic':'prayer'})
        self.store.backup()
        self.store.forget(1)
        self.assertEqual(self.store.retrieve(1,'mourning',[1.,0.]),[])
        self.assertIsNone(self.store.plan(1))
        for path in self.path.parent.glob('backups/*.sqlite3'):
            with closing(sqlite3.connect(path)) as backup:
                self.assertEqual(backup.execute("SELECT COUNT(*) FROM turns WHERE uid='1'").fetchone()[0],0)
                self.assertEqual(backup.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0],1)

    def test_legacy_migration_preserves_original_unknown_date(self):
        path = self.path.parent/'old.sqlite3'
        with closing(sqlite3.connect(path)) as old, old:
            old.execute('CREATE TABLE turns(id INTEGER PRIMARY KEY, uid TEXT,role TEXT,content TEXT)')
            old.execute("INSERT INTO turns VALUES(1,'1','user','original legacy message')")
        migrated = Store(path)
        try:
            rows = migrated.retrieve(1,'legacy')
            self.assertEqual(rows[0]['content'],'original legacy message')
            self.assertIsNone(rows[0]['created_at'])
        finally:
            migrated.close()

    def test_plan_resume_reflection_and_explicit_advancement(self):
        self.assertIn('step 1/',discipleship.command(self.store,1,'start John'))
        discipleship.command(self.store,1,'reflect Learning to listen')
        discipleship.command(self.store,1,'pace one reading a week')
        discipleship.command(self.store,1,'pause')
        discipleship.command(self.store,1,'next')
        self.assertEqual(self.store.plan(1)['step'],0)
        self.store.close()
        self.store = Store(self.path)
        discipleship.command(self.store,1,'resume')
        self.assertIn('step 2/',discipleship.command(self.store,1,'next'))
        self.assertEqual(self.store.plan(1)['reflections'][0]['text'],'Learning to listen')
        self.assertIsNone(self.store.plan(2))
        self.assertIsNone(discipleship.intent("I don't want to start a study about faith"))
        self.assertEqual(discipleship.intent("Let's study John"),'start John')


class RetrievalFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_embedding_failure_still_retrieves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'db')
            brain = Brain(load_config())
            try:
                store.remember_turn(1,'Michael is my brother.','Reply')
                brain.client.post = AsyncMock(side_effect=httpx.ConnectError('offline'))
                self.assertIn('Michael',(await brain.memories(store,1,'Michael'))[0]['content'])
            finally:
                await brain.close()
                store.close()


if __name__=='__main__':
    unittest.main()
