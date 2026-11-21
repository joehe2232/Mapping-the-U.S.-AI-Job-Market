"""Small rule fixtures only; never used as project data or ingestion evidence."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from posting_rules import classify, extract_skills, state_code
from transform_headcount import cents, value
from posting_entities import entity_links


class PostingRulesTests(unittest.TestCase):
    def test_role_boundaries_and_precedence(self):
        cases = {
            'Senior AI Engineer, AI.x':'ml / ai engineer',
            'Machine Learning Research Scientist':'ai research scientist',
            'Product Manager, AI':'ai product manager',
            'AI Data Engineer':'data engineer',
            'Azure Databricks Data Engineer_TC2_T Mob':'data engineer',
            'Senior Staff Machine Learning Engineer_Voice AI':'ml / ai engineer',
            'Applied AI, Engineer & Creator':'ml / ai engineer',
            'Business Intelligence Analyst':'data / bi analyst',
            'AI sales manager':'', 'data engineering manager':'',
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classify(title), expected)

    def test_ambiguous_research_needs_ai_evidence(self):
        self.assertEqual(classify('Research Scientist','clinical biology'), '')
        self.assertEqual(classify('Research Scientist','machine learning systems'), 'ai research scientist')

    def test_same_skill_alias_rules_on_both_sources(self):
        self.assertEqual(extract_skills('NoSQL; regular language; ragtime'), [])
        skills = extract_skills('Google Cloud; PySpark; large language models; retrieval-augmented generation')
        self.assertEqual(set(skills), {'gcp','spark','llm','rag'})

    def test_state_abbreviation_and_foreign_region(self):
        for text, expected in [('US-PA','PA'),('Pennsylvania','PA'),('NY','NY'),('CA-ON',''),('remote','')]:
            self.assertEqual(state_code(text), expected)

    def test_field_states_and_exact_cents(self):
        self.assertIsNone(value({'state':'extraction_failed','value':'untrusted'}))
        self.assertEqual(value({'state':'known','value':''}), '')
        self.assertEqual(cents('123.45'),'12345.00')
        self.assertEqual(cents('NaN'),'')

    def test_source_identity_merges_and_conflicts(self):
        jobs=[dict(batch_id='test',job_id=j,title='Data Scientist',company=c,role='data scientist')
              for j,c in [('a','Employer'),('b','Employer'),('c','Different employer'),('d','Employer')]]
        sources=[dict(job_id=j,posting_id='source1') for j in ['a','b','c']]
        result={r['job_id']:r for r in entity_links(jobs,sources)}
        self.assertEqual(result['a']['entity_id'],result['b']['entity_id'])
        self.assertNotEqual(result['a']['entity_id'],result['c']['entity_id'])
        self.assertNotEqual(result['a']['entity_id'],result['d']['entity_id'])
        self.assertEqual(result['a']['identity_conflict'],'true')


if __name__ == '__main__':
    unittest.main()
