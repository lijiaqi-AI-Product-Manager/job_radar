"""跨文件归属与来源范围，避免后续配置漂移扩大公告证明的覆盖。"""

from pathlib import Path

import yaml

from jobradar.sources import load_sources

ROOT=Path(__file__).parents[1]


def test_selected_notice_sources_keep_exact_registered_entities_and_sample_scope():
    sources={s.id:s for s in load_sources(ROOT/'sources')}
    evidence=yaml.safe_load((ROOT/'targets/university_notice_checks.yaml').read_text(encoding='utf-8'))
    samples=yaml.safe_load((ROOT/'targets/source_checks.yaml').read_text(encoding='utf-8'))
    checks={r['source_id']:r for r in samples['checks']}
    targets=yaml.safe_load((ROOT/'targets/top_companies.yaml').read_text(encoding='utf-8'))
    for record in evidence['checks']:
        source=sources[record['source_id']]
        sample=checks[source.id]
        assert source.source_kind=='aggregator' and source.adapter=='jysd'
        assert source.company==record['company']==''.join(record['registered_company'].split())
        assert source.params['match']==[record['registered_company']]
        assert source.params['notice_ids']==[s['source_job_id'] for s in sample['samples']]
        assert sample['record_kind']=='recruitment_notice'
        assert source.company in targets['aliases'].get(record['target'],[]) or source.company==record['target']


def test_qualification_opt_ins_have_current_adapter_specific_evidence():
    sources={s.id:s for s in load_sources(ROOT/'sources')}
    evidence=yaml.safe_load((ROOT/'targets/qualification_checks.yaml').read_text(encoding='utf-8'))
    for record in evidence['checks']:
        source=sources[record['source_id']]
        assert source.adapter in {'beisen','hotjob'} and source.params['detail_fields'] is True
        assert record['field']=={'beisen':'Require','hotjob':'serviceCondition'}[source.adapter]
        assert (ROOT/record['fixture']).is_file()
