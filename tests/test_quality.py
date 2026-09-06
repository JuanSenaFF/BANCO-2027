import unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from quality import split_requirements,senior_conflict,verify
from validate_auto import canonical_url,req_similarity
from bs4 import BeautifulSoup
class QualityTests(unittest.TestCase):
    def test_sections_exclude_benefits(self):
        html='<h2>Requisitos</h2><ul><li>Python</li><li>SQL básico</li><li>Experiência com APIs</li></ul><h2>Diferenciais</h2><ul><li>AWS</li></ul><h2>Benefícios</h2><ul><li>Plano de saúde</li></ul>'
        a,b=split_requirements(None,{'description':html})
        self.assertEqual(a,['Python','SQL básico','Experiência com APIs']);self.assertEqual(b,['AWS'])
    def test_unknown_section_is_not_mandatory(self):
        self.assertEqual(split_requirements(BeautifulSoup('<li>Python no menu</li>','html.parser')),( [],[]))
    def test_seniority(self):
        self.assertTrue(senior_conflict('Dev Jr','Experiência como sênior'))
        self.assertFalse(senior_conflict('Dev Jr','Trabalhar com colegas seniores'))
    def test_same_linkedin_id(self):
        self.assertEqual(canonical_url('https://linkedin.com/jobs/view/python-123456789'),canonical_url('https://br.linkedin.com/jobs/view/123456789?tracking=foo'))
    def test_similarity(self):
        self.assertEqual(req_similarity(['Python','SQL','APIs'],['SQL','APIs','Python']),1)
    @patch('quality.safe_fetch')
    def test_http403_unknown(self,get):
        get.return_value.status_code=403
        r=verify({'source':'https://example.com'},object())
        self.assertEqual(r['status'],'Possivelmente encerrada');self.assertNotIn('lastVerifiedAt',r)
    @patch('quality.safe_fetch')
    def test_http404_closed(self,get):
        get.return_value.status_code=404
        self.assertEqual(verify({'source':'https://example.com'},object())['status'],'Encerrada')
    @patch('quality.safe_fetch')
    def test_generic200_unknown(self,get):
        get.return_value.status_code=200;get.return_value.text='<h1>Carreiras</h1>'
        self.assertEqual(verify({'source':'https://example.com'},object())['status'],'Possivelmente encerrada')
if __name__=='__main__':unittest.main()
