import unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from quality import split_requirements,senior_conflict,verify,requirements_quality_conflict
from validate_auto import canonical_url,req_similarity,similarity_band
from rules import validation_state
from build_catalog import apply_verification
from bs4 import BeautifulSoup
class QualityTests(unittest.TestCase):
    def test_sections_exclude_benefits(self):
        html='<h2>Requisitos</h2><ul><li>Python</li><li>SQL básico</li><li>Experiência com APIs</li></ul><h2>Diferenciais</h2><ul><li>AWS</li></ul><h2>Benefícios</h2><ul><li>Plano de saúde</li></ul>'
        a,b=split_requirements(None,{'description':html})
        self.assertEqual(a,['Python','SQL básico','Experiência com APIs']);self.assertEqual(b,['AWS'])
    def test_process_steps_do_not_leak_into_requirements(self):
        html='<h2>Requisitos</h2><ul><li>Python</li><li>SQL</li><li>APIs REST</li></ul><h2>Etapas do processo seletivo</h2><ul><li>Teste cognitivo</li><li>Entrevista com a liderança</li></ul>'
        a,b=split_requirements(None,{'description':html})
        self.assertEqual(a,['Python','SQL','APIs REST']);self.assertEqual(b,[])
    def test_benefit_items_are_filtered_even_without_heading(self):
        html='<h2>Requisitos</h2><ul><li>Python</li><li>SQL</li><li>Git</li><li>Vale-Refeição</li><li>Plano médico</li></ul>'
        a,_=split_requirements(None,{'description':html})
        self.assertEqual(a,['Python','SQL','Git'])
    def test_technical_role_requires_hard_skill_signal(self):
        self.assertTrue(requirements_quality_conflict('Engenharia de Software .Net Júnior',['Curiosidade e vontade de aprender','Proatividade','Boa comunicação']))
        self.assertFalse(requirements_quality_conflict('Engenharia de Software .Net Júnior',['C# e .NET','APIs REST','SQL']))
    def test_polluted_requirement_set_is_rejected(self):
        req=['Python','SQL','Vale-Refeição','Plano médico','Entrevista com a liderança','Teste cognitivo']
        self.assertTrue(requirements_quality_conflict('Data Analyst I',req))
    def test_unknown_section_is_not_mandatory(self):
        self.assertEqual(split_requirements(BeautifulSoup('<li>Python no menu</li>','html.parser')),( [],[]))
    def test_seniority(self):
        self.assertTrue(senior_conflict('Dev Jr','Experiência como sênior'))
        self.assertFalse(senior_conflict('Dev Jr','Trabalhar com colegas seniores'))
    def test_numbered_levels_above_entry_are_excluded(self):
        self.assertTrue(senior_conflict('Anti-Fraud Spec III','SQL e Python'))
        self.assertTrue(senior_conflict('Cyber Security Spec II (BISO)','Cloud Security'))
        self.assertTrue(senior_conflict('Data Analyst II','SQL'))
        self.assertFalse(senior_conflict('Data Analyst I','SQL'))
    def test_same_linkedin_id(self):
        self.assertEqual(canonical_url('https://linkedin.com/jobs/view/python-123456789'),canonical_url('https://br.linkedin.com/jobs/view/123456789?tracking=foo'))
    def test_similarity(self):
        self.assertEqual(req_similarity(['Python','SQL','APIs'],['SQL','APIs','Python']),1)
        self.assertEqual(req_similarity(['APIs REST','Postgres','Microsserviços'],['REST APIs','PostgreSQL','Microservices']),1)
        self.assertEqual(similarity_band(['Python','SQL','APIs','Docker'],['Python','SQL','APIs','Docker','Kafka']),'review')
    def test_validation_states_are_explicit(self):
        self.assertEqual(validation_state({'status':'Possivelmente encerrada'}),'pending')
        self.assertEqual(validation_state({'status':'Encerrada'}),'closed')
        self.assertEqual(validation_state({'status':'Ativa','lastVerifiedAt':'2099-01-01T00:00:00Z'}),'confirmed')
        self.assertEqual(validation_state({'status':'Ativa','lastVerifiedAt':'2020-01-01T00:00:00Z'}),'pending')
    def test_inconclusive_check_does_not_close_active_job(self):
        result = apply_verification(
            {'status': 'Ativa'},
            {'status': 'Possivelmente encerrada', 'verificationReason': 'HTTP 403'},
        )
        self.assertEqual(result['status'], 'Ativa')
        self.assertEqual(result['validationState'], 'pending')
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
