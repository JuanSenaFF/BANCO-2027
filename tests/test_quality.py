import html,json,unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from quality import deduplicate_requirement_containers,parse_json_ld,split_requirements,senior_conflict,verify,requirements_quality_conflict
from validate_auto import canonical_url,req_similarity,similarity_band
from rules import validation_state
from build_catalog import apply_verification
from bs4 import BeautifulSoup
class QualityTests(unittest.TestCase):
    def test_jsonld_parser_supports_plain_and_encoded_payloads(self):
        posting={'@type':'JobPosting','title':'Cientista de Dados Jr.'}
        plain=json.dumps(posting,ensure_ascii=False)
        self.assertEqual(parse_json_ld(plain),posting)
        self.assertEqual(parse_json_ld(html.escape(plain)),posting)
        self.assertEqual(parse_json_ld(html.escape(html.escape(plain))),posting)
        self.assertIsNone(parse_json_ld('{invalid'))

    def test_sections_exclude_benefits(self):
        html='<h2>Requisitos</h2><ul><li>Python</li><li>SQL básico</li><li>Experiência com APIs</li></ul><h2>Diferenciais</h2><ul><li>AWS</li></ul><h2>Benefícios</h2><ul><li>Plano de saúde</li></ul>'
        a,b=split_requirements(None,{'description':html})
        self.assertEqual(a,['Python','SQL básico','Experiência com APIs']);self.assertEqual(b,['AWS'])
    def test_requirement_section_stops_before_unheaded_benefits_and_metadata(self):
        html='<h2>Requisitos</h2><ul><li>Python</li><li>SQL</li><li>APIs REST</li></ul><p>Viva Bem: programa de saúde</p><p>Universidade corporativa</p><p>Nível de experiência Não aplicável</p>'
        a,_=split_requirements(None,{'description':html})
        self.assertEqual(a,['Python','SQL','APIs REST'])
    def test_process_steps_do_not_leak_into_requirements(self):
        html='<h2>Requisitos</h2><ul><li>Python</li><li>SQL</li><li>APIs REST</li></ul><h2>Etapas do processo seletivo</h2><ul><li>Teste cognitivo</li><li>Entrevista com a liderança</li></ul>'
        a,b=split_requirements(None,{'description':html})
        self.assertEqual(a,['Python','SQL','APIs REST']);self.assertEqual(b,[])
    def test_benefit_items_are_filtered_even_without_heading(self):
        html='<h2>Requisitos</h2><ul><li>Python</li><li>SQL</li><li>Git</li><li>Vale-Refeição</li><li>Plano médico</li></ul>'
        a,_=split_requirements(None,{'description':html})
        self.assertEqual(a,['Python','SQL','Git'])
    def test_inline_emphasis_does_not_drop_requirement_text(self):
        description='<h2>Requisitos</h2><p>Conhecimento em <strong>Python</strong></p><p>SQL</p><p>APIs REST</p>'
        req,_=split_requirements(None,{'description':description})
        self.assertEqual(req,['Conhecimento em Python','SQL','APIs REST'])
    def test_container_text_is_not_duplicated_with_list_items(self):
        description='<h2>Requisitos</h2><p><ul><li>Python</li><li>SQL</li><li>APIs REST</li></ul></p>'
        req,_=split_requirements(None,{'description':description})
        self.assertEqual(req,['Python','SQL','APIs REST'])
    def test_historical_combined_requirement_is_removed(self):
        individual=[
            'Superior em Tecnologia, Engenharias ou áreas correlatas.',
            'Experiência em projetos de controles internos de TI e gestão de acessos.',
            'Experiência de 1 a 2 anos na área.',
        ]
        combined=' '.join(individual) + ' ' + ('Contexto adicional. ' * 5)
        self.assertEqual(deduplicate_requirement_containers([combined,*individual]),individual)
    def test_english_qualification_headings_are_recognized(self):
        description='<h2>Minimum qualifications</h2><ul><li>Python</li><li>SQL</li><li>REST APIs</li></ul><h2>Preferred qualifications</h2><ul><li>GCP</li></ul>'
        req,diff=split_requirements(None,{'description':description})
        self.assertEqual(req,['Python','SQL','REST APIs'])
        self.assertEqual(diff,['GCP'])
    def test_employment_type_stops_requirement_section(self):
        description='<h2>Requisitos</h2><ul><li>Python</li><li>SQL</li><li>APIs REST</li></ul><h2>Tipo de emprego</h2><p>Tempo integral</p>'
        req,_=split_requirements(None,{'description':description})
        self.assertEqual(req,['Python','SQL','APIs REST'])
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
        self.assertTrue(senior_conflict('SSD Brasil - Cyber Analyst lll - SOC','Cloud Security'))
        self.assertFalse(senior_conflict('Data Analyst I','SQL'))
        self.assertTrue(senior_conflict('Analista de Risco de Crédito Pl','SQL'))
        self.assertTrue(senior_conflict('Software Engineer II','Python'))
        self.assertTrue(senior_conflict('Data Engineer III','Python'))
        self.assertTrue(senior_conflict('Backend Dev Sr.','Python'))
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
        self.assertIsNone(result['lastVerifiedAt'])
    def test_new_inconclusive_check_supersedes_old_confirmation(self):
        result = apply_verification(
            {'status':'Ativa','lastVerifiedAt':'2026-09-20T00:00:00Z'},
            {'status':'Possivelmente encerrada','validationState':'pending','lastCheckedAt':'2026-09-24T00:00:00Z'},
        )
        self.assertEqual(result['previouslyVerifiedAt'],'2026-09-20T00:00:00Z')
        self.assertEqual(validation_state({**result,'status':'Ativa'}),'pending')
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
    @patch('quality.safe_fetch')
    def test_entity_encoded_gupy_jsonld_is_confirmed(self,get):
        posting={
            '@context':'https://schema.org','@type':'JobPosting','title':'Cientista de Dados Jr.',
            'hiringOrganization':{'name':'PagBank'},
            'validThrough':'2099-12-31','datePosted':'2026-05-25',
            'description':'<h2>Requisitos e qualificações</h2><ul><li>Python para análise de dados</li><li>SQL para manipulação de dados</li><li>Fundamentos de Machine Learning</li></ul><p>O profissional apoiará análises, modelos preditivos, documentação e iniciativas de risco.</p>',
        }
        encoded=html.escape(json.dumps(posting,ensure_ascii=False))
        get.return_value.status_code=200
        get.return_value.text=f'<script type="application/ld+json">{encoded}</script>'
        result=verify({'source':'https://pagseguro.gupy.io/jobs/11175121','role':'Cientista de Dados Jr.','company':'PagBank'},object())
        self.assertEqual(result['status'],'Ativa')
        self.assertEqual(result['validationState'],'confirmed')
        self.assertEqual(result['verificationReason'],'JobPosting correspondente e válido')
        self.assertEqual(result['validThrough'],'2099-12-31')
        self.assertTrue({'Python para análise de dados','SQL para manipulação de dados','Fundamentos de Machine Learning'}.issubset(result['requirements']))
    @patch('quality.safe_fetch')
    def test_jobposting_from_another_company_is_not_confirmed(self,get):
        posting={
            '@type':'JobPosting','title':'Software Engineer Junior',
            'hiringOrganization':{'name':'Other Company'},
            'description':'<h2>Requirements</h2><ul><li>Python</li><li>SQL</li><li>REST APIs</li></ul>' + 'x'*200,
        }
        get.return_value.status_code=200
        get.return_value.text=f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        result=verify({'source':'https://example.com/job','role':'Software Engineer Junior','company':'Google'},object())
        self.assertEqual(result['validationState'],'pending')
        self.assertEqual(result['verificationReason'],'JobPosting pertence a outra empresa')
    @patch('quality.safe_fetch')
    def test_senior_jobposting_does_not_confirm_junior_record(self,get):
        posting={
            '@type':'JobPosting','title':'Software Engineer Senior',
            'hiringOrganization':{'name':'Google LLC'},
            'description':'<h2>Requirements</h2><ul><li>Python</li><li>SQL</li><li>REST APIs</li></ul>' + 'x'*200,
        }
        get.return_value.status_code=200
        get.return_value.text=f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        result=verify({'source':'https://example.com/job','role':'Software Engineer Junior','company':'Google'},object())
        self.assertEqual(result['validationState'],'pending')
        self.assertEqual(result['verificationReason'],'JobPosting tem senioridade fora do recorte')
if __name__=='__main__':unittest.main()
