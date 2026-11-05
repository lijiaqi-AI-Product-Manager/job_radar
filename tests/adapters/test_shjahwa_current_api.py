import json
from pathlib import Path

import httpx
import pytest

from jobradar.adapters.base import SkipRecord, load_all
from jobradar.adapters.beisen import BeisenAdapter
from jobradar.sources import load_sources


@pytest.fixture(scope='module')
def shjahwa():
    root=Path(__file__).parents[2]
    evidence=json.loads((root/'tests/fixtures/beisen/shjahwa-current-api.json').read_text(encoding='utf-8'))
    source=next(s for s in load_sources(root/'sources') if s.id==evidence['source_id'])
    return source,evidence


def test_shjahwa_uses_the_current_public_format_and_keeps_its_campus_scope(shjahwa):
    source,evidence=shjahwa
    def no_network(request):
        pytest.fail('field replay must not access the network')
    with httpx.Client(transport=httpx.MockTransport(no_network)) as client:
        adapter=load_all()[source.adapter](source,client)
        for raw in evidence['samples']:
            if str(raw['CategoryId'])=='2':
                job=adapter.normalize(raw)
                assert job.source_id==evidence['source_id'] and job.company=='上海家化'
                assert raw['Category']=='校园招聘' and job.recruit_type=='campus'
                assert job.source_job_id==str(raw['JobAdId'])
                assert job.source_job_id in evidence['previous_stable_ids']
                assert 'jobAdId='+raw['Id'] in job.url
                assert job.description or job.requirements
            else:
                with pytest.raises(SkipRecord):
                    adapter.normalize(raw)


@pytest.mark.parametrize('invalid',[None,True,0,-1,'0','01','invalid'])
def test_legacy_identity_must_not_fall_back_to_a_new_publication_id(shjahwa,invalid):
    source,evidence=shjahwa
    raw={**evidence['samples'][0],'JobAdId':invalid}
    with httpx.Client() as client,pytest.raises(RuntimeError,match='legacy job identity'):
        BeisenAdapter(source,client).normalize(raw)


def test_other_beisen_sources_keep_their_existing_publication_identity(shjahwa):
    source,evidence=shjahwa
    params={k:v for k,v in source.params.items() if k!='job_id_field'}
    source=source.model_copy(update={'params':params})
    raw=evidence['samples'][0]
    with httpx.Client() as client:
        assert BeisenAdapter(source,client).normalize(raw).source_job_id==raw['Id']
