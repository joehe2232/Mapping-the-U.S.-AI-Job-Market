"""Conservative title and technology rules for the six proposed roles."""
import html
import re

US_STATES = set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())
STATE_NAMES = dict(zip((
    'Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia'
).lower().split('|'), 'AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split()))


def state_code(value):
    value = str(value or '').strip()
    short = value.removeprefix('US-').upper()
    return short if short in US_STATES else STATE_NAMES.get(value.lower(), '')
SKILLS = {
    'python': r'\bpython\b', 'sql': r'\bsql\b',
    'aws': r'\baws\b|\bamazon web services\b', 'azure': r'\bazure\b',
    'gcp': r'\bgcp\b|\bgoogle cloud\b', 'pytorch': r'\bpytorch\b',
    'tensorflow': r'\btensorflow\b', 'docker': r'\bdocker\b',
    'kubernetes': r'\bkubernetes\b|\bk8s\b', 'apache airflow': r'\bairflow\b',
    'spark': r'\bspark\b|\bpyspark\b', 'kafka': r'\bkafka\b',
    'databricks': r'\bdatabricks\b', 'snowflake': r'\bsnowflake\b',
    'tableau': r'\btableau\b', 'power bi': r'\bpower\s*bi\b',
    'llm': r'\bllms?\b|\blarge language models?\b',
    'generative ai': r'\bgenerative ai\b|\bgenai\b|\bgen ai\b',
    'rag': r'\brag\b|\bretrieval[\s-]+augmented generation\b',
    'mlops': r'\bmlops\b|\bml ops\b', 'langchain': r'\blangchain\b',
}
AI = r'\bai\b|\bartificial intelligence\b|\bmachine learning\b|\bml\b|\bllms?\b|\bgenerative ai\b'


def plain(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', value or '')).split())


def classify(title, description=''):
    t = plain(title).lower().replace('_', ' ')
    if re.search(r'\bproduct manager\b', t) and re.search(AI, t):
        return 'ai product manager'
    if re.search(r'\bresearch scientist\b', t) and re.search(AI, t + ' ' + description.lower()):
        return 'ai research scientist'
    if re.search(r'\bdata engineer\b', t):
        return 'data engineer'
    if re.search(r'\b(machine learning|ml|ai|artificial intelligence)[\s,/-]+engineer\b', t):
        return 'ml / ai engineer'
    if re.search(r'\bdata scientist\b', t):
        return 'data scientist'
    if re.search(r'\b(data analyst|business intelligence analyst|bi analyst)\b', t):
        return 'data / bi analyst'
    return ''


def extract_skills(value):
    return [skill for skill, pattern in SKILLS.items() if re.search(pattern, value or '', re.I)]
