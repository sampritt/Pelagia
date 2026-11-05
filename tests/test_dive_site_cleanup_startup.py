import csv
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pelagia.dive_site_cleanup_startup import apply_catalog


class StartupCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv = Path(self.temp.name) / 'sites.csv'
        self.db_path = Path(self.temp.name) / 'db.sqlite'
        self.write_catalog()
        with self.connect() as db:
            db.executescript(Path('pelagia/schema.sql').read_text())
            db.execute("INSERT INTO dive_sites (id,master_site_id,name) VALUES (1,'OLD','Old site')")
            db.execute("INSERT INTO users (id,username) VALUES (1,'user')")
            db.execute("INSERT INTO dives (user_id,dive_site_id,date,site_name,latitude,longitude) VALUES (1,1,'2026-01-01','Logged site',20,30)")
            db.execute("INSERT INTO dive_site_comments (dive_site_id,user_id,body) VALUES (1,1,'old comment')")

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def write_catalog(self, name='New site'):
        with self.csv.open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['master_site_id','dive_site_name','country_or_area','country_code','latitude','longitude','max_depth_m','legacy_import_id'])
            writer.writerow(['NEW',name,'Australia','AU','-30','150','NA','7'])

    def test_replaces_data_and_restart_preserves_new_links(self):
        with self.connect() as db:
            self.assertTrue(apply_catalog(db, self.csv))
            self.assertEqual(tuple(db.execute('SELECT id,master_site_id,name FROM dive_sites').fetchone()), (7,'NEW','New site'))
            self.assertEqual(tuple(db.execute('SELECT dive_site_id,site_name,latitude,longitude FROM dives').fetchone()), (None,'Logged site',20,30))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dive_site_comments').fetchone()[0],0)
            db.execute('UPDATE dives SET dive_site_id=7'); db.commit()
            self.assertFalse(apply_catalog(db, self.csv))
            self.assertEqual(db.execute('SELECT dive_site_id FROM dives').fetchone()[0],7)
            self.write_catalog('Updated site')
            self.assertTrue(apply_catalog(db, self.csv))
            self.assertIsNone(db.execute('SELECT dive_site_id FROM dives').fetchone()[0])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_bad_catalogue_does_not_delete_existing_data(self):
        self.csv.write_text('master_site_id,legacy_import_id\n')
        with self.connect() as db:
            with self.assertRaises(ValueError): apply_catalog(db, self.csv)
            self.assertEqual(db.execute('SELECT master_site_id FROM dive_sites').fetchone()[0],'OLD')

    def test_concurrent_workers_apply_once(self):
        def run(_):
            with self.connect() as db: return apply_catalog(db,self.csv)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(run, range(2))), [False,True])


if __name__=='__main__': unittest.main()
