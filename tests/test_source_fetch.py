import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from fetch_source import fetch,source_record

class Response(io.BytesIO):
    headers={}
    def geturl(self):return 'https://example.invalid/feed.zip'

class SourceFetchTests(unittest.TestCase):
    def test_download_records_provenance_and_detects_later_source_change(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'feed.zip'
            with patch('fetch_source.urlopen',return_value=Response(b'test feed')):
                report=fetch('https://example.invalid/feed.zip',target,attribution='Example data')
            self.assertEqual(target.read_bytes(),b'test feed')
            self.assertEqual(source_record(target),report)
            self.assertEqual(report['attribution'],'Example data')
            target.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):source_record(target)

    def test_existing_file_and_oversize_download_are_not_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'feed.zip';target.write_bytes(b'original')
            with patch('fetch_source.urlopen') as request:
                with self.assertRaises(ValueError):fetch('https://example.invalid/feed.zip',target)
                request.assert_not_called()
            self.assertEqual(target.read_bytes(),b'original')
            new=Path(d)/'new.zip'
            with patch('fetch_source.urlopen',return_value=Response(b'too large')):
                with self.assertRaisesRegex(ValueError,'limit'):fetch('https://example.invalid/feed.zip',new,3)
            self.assertFalse(new.exists())
            self.assertEqual(list(Path(d).glob('.source-*')),[])

    def test_local_source_and_non_http_scheme(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'stations.csv';source.write_text('local data')
            self.assertEqual(source_record(source)['kind'],'local')
            with self.assertRaisesRegex(ValueError,'HTTP'):fetch('file:///etc/passwd',Path(d)/'out')

if __name__=='__main__':unittest.main()
