from __future__ import annotations


import pytest


def test_author_exact_doi_dedup_issue_date_and_coverage(tmp_path):
    from acquire_research_papers.author_discovery import discover_author
    records = {
        'orcid': [
            {'doi':'10.1234/ONE', 'title':'One', 'issue_date':'2025-01', 'online_date':'2024-11'},
            {'doi':'10.1234/two', 'title':'Two', 'online_date':'2025-03', 'type':'preprint'},
        ],
        'dblp': [
            {'doi':'https://doi.org/10.1234/one', 'title':'One', 'issue_date':'2025-01'},
            {'doi':'10.1234/three', 'title':'Three', 'issue_date':'2023-02'},
        ],
    }
    result = discover_author({'name':'Ada Lovelace','orcid':'0000-0002-1825-0097',
        'dblp':'12/34', 'date_from':'2025-01-01', 'date_to':'2025-12-31'},
        records=records, output=tmp_path)
    assert [p['doi'] for p in result['papers']] == ['10.1234/one', '10.1234/two']
    assert result['papers'][0]['online_date'] == '2024-11'
    assert len(result['papers'][0]['sources']) == 2
    assert result['papers'][1]['publication_stage'] == 'preprint'
    assert result['coverage']['complete'] is False
    assert (tmp_path / 'author-discovery.json').exists()


def test_name_only_author_identity_stays_ambiguous_and_source_errors_explicit(tmp_path):
    from acquire_research_papers.author_discovery import discover_author
    result = discover_author({'name':'J. Wang'}, records={
        'database':[{'doi':'10.1234/one','title':'One','year':2025}],
        'orcid': {'error':'not configured'}}, output=tmp_path)
    assert result['identity']['status'] == 'ambiguous'
    assert result['coverage']['sources']['orcid']['error'] == 'not configured'
    assert result['papers'][0]['identity_status'] == 'ambiguous'


def test_author_local_presence_and_no_title_dedup(tmp_path):
    from acquire_research_papers.author_discovery import discover_author
    local = tmp_path / 'local'
    local.mkdir()
    (local/'one.bib').write_text('@article{k,title={Same},doi={10.1234/one},year={2025}}')
    result = discover_author({'name':'Ada','local_dir':str(local)}, records={'database':[
        {'doi':'10.1234/one','title':'Same','year':2025},
        {'doi':'10.1234/two','title':'Same','year':2025}]})
    assert len(result['papers']) == 2
    assert result['papers'][0]['local_status'] == 'bib_only'
    assert result['papers'][1]['local_status'] == 'missing'


def test_invalid_author_dates_and_private_homepage_rejected():
    from acquire_research_papers.author_discovery import discover_author
    with pytest.raises(ValueError):
        discover_author({'name':'Ada','date_from':'2025-99-99'}, records={})
    with pytest.raises(ValueError):
        discover_author({'name':'Ada','homepage':'http://127.0.0.1/secret'}, records={})


def test_author_separates_early_access_and_links_preprint_versions_without_counting_twice():
    from acquire_research_papers.author_discovery import discover_author
    result = discover_author({'name':'Ada', 'orcid':'0000-0002-1825-0097'}, records={'orcid':[
        {'doi':'10.1234/early','title':'Early', 'online_date':'2025-02', 'type':'journal-article'},
        {'doi':'10.1234/final','title':'Final', 'issue_date':'2025-03', 'type':'journal-article'},
        {'doi':'10.1234/pre','title':'Draft Final', 'type':'preprint', 'online_date':'2024-11',
         'is_preprint_of':'10.1234/final'}]})
    assert len(result['groups']['early_access']) == 1
    assert len(result['groups']['formal']) == 1
    assert len(result['groups']['preprints']) == 1
    draft = next(p for p in result['papers'] if p['doi'] == '10.1234/pre')
    assert draft['version_of'] == '10.1234/final'
    assert draft['count_as_formal'] is False


def test_conflicting_dates_crossing_boundary_remain_reviewable():
    from acquire_research_papers.author_discovery import discover_author
    result = discover_author({'name':'Ada','orcid':'0000-0002-1825-0097','date_from':'2020-12'},
        records={'orcid':[{'doi':'10.1234/work','issue_date':'2020-11'}],
                 'database':[{'doi':'10.1234/work','issue_date':'2021-01'}]})
    assert len(result['papers']) == 1
    assert result['papers'][0]['date_scope'] == 'conflict_requires_review'


def test_coauthor_affiliation_does_not_resolve_a_namesake():
    from acquire_research_papers.author_discovery import discover_author
    from acquire_research_papers.library.metadata import crossref_record
    record = crossref_record({'DOI':'10.1234/work','published-print':{'date-parts':[[2025]]},
        'author':[{'given':'Ada','family':'Example','affiliation':[{'name':'Other University'}]},
                  {'given':'Alex','family':'Other','affiliation':[{'name':'Requested University'}]}]})
    result = discover_author({'name':'Ada Example','affiliation':'Requested University'},
                             records={'database':[record]})
    assert result['papers'][0]['identity_status'] == 'ambiguous'
    assert result['papers'][0]['count_as_formal'] is False
    result = discover_author({'name':'Ada Example','affiliation':'Other University'},
                             records={'database':[record]})
    assert result['papers'][0]['identity_status'] == 'supported'


def test_production_author_clients_parse_public_fixture_payloads():
    from acquire_research_papers.author_discovery import PublicAuthorClient, validate_spec
    spec = validate_spec({'name':'Ada','orcid':'0000-0002-1825-0097','dblp':'12/34'})
    class Response:
        text = '<dblpperson><r><article key="journals/test/1"><author>Ada</author><title>GPU <i>Work</i></title><year>2025</year><ee>https://doi.org/10.1234/one</ee></article></r></dblpperson>'
        def json(self):
            return {'group':[{'work-summary':[{'put-code':1,'title':{'title':{'value':'Work'}},
                'external-ids':{'external-id':[{'external-id-type':'doi','external-id-value':'10.1234/one'}]},
                'publication-date':{'year':{'value':'2025'}}}]}]}
    class Http:
        def __init__(self, **kwargs):
            assert kwargs['timeout'] <= 15
            assert kwargs['retries'] == 0
        def get(self, url, **kwargs):
            return Response()
        def close(self):
            pass
    client = PublicAuthorClient(http_factory=Http)
    orcid = client.fetch('orcid', spec)
    assert orcid['records'][0]['doi'] == '10.1234/one'
    assert not orcid['records'][0].get('issue_date')
    assert client.fetch('dblp', spec)['records'][0]['title'] == 'GPU Work'
