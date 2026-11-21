"""Static, exportable diagrams for the notebook and Milestone 2 report/video."""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

NAVY='#17324D'
BLUE='#E8F1FA'
GREEN='#E7F3EC'
AMBER='#FFF1D8'
GRAY='#F0F3F6'


def box(ax,x,y,w,h,title,body,color=BLUE):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.012',
        facecolor=color,edgecolor='#A4B5C4',linewidth=1.2))
    ax.text(x+w/2,y+h-.035,title,ha='center',va='top',fontsize=11,fontweight='bold',color=NAVY)
    ax.text(x+w/2,y+h/2-.023,body,ha='center',va='center',fontsize=9.5,color=NAVY,linespacing=1.5)


def arrow(ax,start,end,label=None,dashed=False):
    ax.add_patch(FancyArrowPatch(start,end,arrowstyle='-|>',mutation_scale=13,
        linewidth=1.3,color='#607D8B',linestyle='--' if dashed else '-'))
    if label:
        ax.text((start[0]+end[0])/2,(start[1]+end[1])/2+.015,label,
                ha='center',va='bottom',fontsize=8.5,color='#455A64',backgroundcolor='white')


def save(fig,folder,name):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    fig.savefig(folder/(name+'.png'),dpi=180,bbox_inches='tight',facecolor='white')
    fig.savefig(folder/(name+'.svg'),bbox_inches='tight',facecolor='white')


def architecture(folder):
    fig,ax=plt.subplots(figsize=(15,8));ax.set(xlim=(0,1),ylim=(0,1));ax.axis('off')
    fig.suptitle('Where originals, MongoDB processing and SQL analysis live',
                 fontsize=19,fontweight='bold',color=NAVY,y=.98)
    xs=[.025,.275,.525,.775];w=.2;h=.18
    rows=[(.70,[('BLS + O*NET files','data/downloads/\ndata/raw/'),
                 ('PostgreSQL raw.*','Original cells as TEXT\nFile + release provenance'),
                 ('SQL reference cleaning','Numbers, NULLs, suppression\nSOC + skill examples'),
                 ('PostgreSQL clean.*','Official metro benchmarks\nOccupations + skill references')]),
          (.405,[('Same Headcount files','251 original JSON pages\nAll query occurrences retained'),
                   ('Python + staging.*','Deterministic selection\nArrays flattened, versions kept'),
                   ('SQL + entity resolution','Typed child relations\nSource-linked ad groups'),
                   ('PostgreSQL serving.*','2,815 analysis ad groups\nBLS + O*NET integrations')]),
          (.11,[('Same Headcount files','Original wrappers unchanged\nSHA-256 inventory'),
                 ('MongoDB raw_pages','251 immutable page payloads\nManifest + checkpoint retained'),
                 ('MongoDB aggregation','Unwind, sort pointers, group\nNormalize fields, dates + cents'),
                 ('MongoDB clean_*','3,705 job summaries\n27,771 salary-range documents')])]
    for ri,(y,items) in enumerate(rows):
        for col,(title,body) in enumerate(items):
            box(ax,xs[col],y,w,h,title,body,
                GRAY if col==0 else GREEN if col==3 else BLUE)
            if col<3:arrow(ax,(xs[col]+w+.014,y+h/2),(xs[col+1]-.014,y+h/2))
    arrow(ax,(.875,.69),(.875,.60),'join by SOC + metro')
    ax.text(.5,.34,'MongoDB and PostgreSQL processing are reconciled against the same source files.',
            ha='center',fontsize=11,color=NAVY)
    ax.text(.5,.305,'The MongoDB outputs are not claimed as the upstream input of the existing SQL pipeline.',
            ha='center',fontsize=9.5,color='#526779')
    ax.text(.5,.025,'Raw JSON remains semi-structured. Relational derivatives remain valid and useful for integration.',
            ha='center',fontsize=11,color=NAVY)
    save(fig,folder,'storage_workflow');return fig


def relational_schema(folder):
    fig,ax=plt.subplots(figsize=(15,9));ax.set(xlim=(0,1),ylim=(0,1));ax.axis('off')
    fig.suptitle('Headcount analysis schema: preserve each relation\'s grain',
                 fontsize=19,fontweight='bold',color=NAVY,y=.98)
    box(ax,.36,.70,.28,.19,'clean.postings','3,705 provider job records\nKey: batch_id + job_id\nRole, SOC, company, text',GREEN)
    box(ax,.025,.70,.25,.19,'BLS reference','Area + SOC benchmark\nEmployment + wage median\nNullable match',BLUE)
    box(ax,.725,.70,.25,.19,'O*NET reference','Occupation + software examples\nJoin through mapped onet_soc\nDirect / proxy labels',BLUE)
    box(ax,.025,.365,.25,.20,'clean.posting_locations','21,335 location entries\nKey: job + location_index\nCountry, state, source / BLS metro',GREEN)
    box(ax,.725,.365,.25,.20,'clean.source_postings','19,157 source listings\nKey: job + posting_index\nSource ID, city, status, pay state',GREEN)
    box(ax,.025,.035,.25,.20,'clean.posting_skills','15,817 job-skill links\nKey: job + skill\nOne dictionary mention per job',GREEN)
    box(ax,.36,.035,.28,.20,'clean.job_entities','3,705 membership links\njob_id -> entity_id\n2,815 source-linked ad groups',AMBER)
    box(ax,.725,.035,.25,.20,'clean.pay_ranges','27,771 source money ranges\nKey: job + posting + money_index\nDecimal dollars + quality flags',GREEN)
    arrow(ax,(.275,.795),(.35,.795),'SOC + metro',True)
    arrow(ax,(.725,.795),(.65,.795),'O*NET-SOC',True)
    arrow(ax,(.36,.72),(.16,.58),'1 : many')
    arrow(ax,(.64,.72),(.85,.58),'1 : many')
    ax.plot([.39,.31,.31],[.70,.64,.29],color='#607D8B',linewidth=1.3)
    arrow(ax,(.31,.29),(.15,.25))
    ax.text(.322,.46,'1 : many',rotation=90,fontsize=8.5,color='#455A64',va='center')
    ax.plot([.62,.68,.68],[.70,.64,.14],color='#607D8B',linewidth=1.3)
    arrow(ax,(.68,.14),(.653,.14))
    ax.text(.692,.43,'1 : 1 membership',rotation=90,fontsize=8.5,color='#455A64',va='center')
    arrow(ax,(.85,.35),(.85,.25),'1 : many')
    ax.text(.50,.49,'A job can have many locations,\nsource listings and pay ranges.',ha='center',va='center',
            fontsize=12,color=NAVY,linespacing=1.5)
    ax.text(.50,.365,'Count distinct ad groups for analysis.\nDo not count expanded child rows as jobs.',
            ha='center',fontsize=11,color=NAVY,linespacing=1.5)
    save(fig,folder,'relational_schema');return fig


def cleaning_counts(folder,occurrences,provider_jobs,ad_groups):
    fig,ax=plt.subplots(figsize=(11,5.7))
    labels=['Raw query\noccurrences','Selected provider\njob IDs','Source-linked\nanalysis ad groups']
    values=[occurrences,provider_jobs,ad_groups]
    bars=ax.bar(labels,values,color=['#799AB8','#397BA9','#328065'],width=.6)
    ax.bar_label(bars,labels=[f'{v:,}' for v in values],padding=8,fontsize=14,fontweight='bold')
    ax.set_ylim(0,max(values)*1.20);ax.set_ylabel('Records at the stated grain')
    ax.set_title('Two levels of duplicate handling',loc='left',fontsize=17,fontweight='bold',pad=18)
    ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.text(.12,.005,'Original pages remain intact. These stages use different counting units; none is a national vacancy total.',
             fontsize=10,color='#526779')
    fig.tight_layout();save(fig,folder,'cleaning_counts');return fig
