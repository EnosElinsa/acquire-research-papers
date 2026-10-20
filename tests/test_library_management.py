from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter


def pdf(path: Path, text: str = '') -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({'/Title': text})
    with path.open('wb') as stream:
        writer.write(stream)


def pair(root: Path, stem: str = 'paper', doi: str = '10.1234/test', *, raw=None):
    root.mkdir(parents=True, exist_ok=True)
    pdf(root / f'{stem}.pdf', f'DOI {doi}')
    content = raw or ('@article{k,title={a study of GPU and iPhone 中文},'
                      'journal={IEEE Transactions on Tests},year={2023},'
                      f'doi={{{doi}}}' + '}').encode()
    (root / f'{stem}.bib').write_bytes(content)
    return content


def test_audit_reports_finalization_duplicates_missing_and_unknown(tmp_path):
    from acquire_research_papers.library import audit_library
    pair(tmp_path, 'first')
    pair(tmp_path, 'copy')
    pdf(tmp_path / 'orphan.pdf')
    report = audit_library(tmp_path, metadata={'10.1234/test': {
        'doi': '10.1234/test', 'title': 'A Study of GPU and iPhone 中文',
        'issue_date': '2024-01', 'online_date': '2023-02', 'volume': '4',
        'issue': '1', 'pages': '10-20', 'status': 'published', 'source': 'publisher',
    }}, output=tmp_path / 'audit')
    assert report['summary']['duplicate_dois'] == 1
    assert any(row['status'] == 'missing_bib' for row in report['items'])
    assert report['items'][0]['publication_status'] == 'outdated'
    assert report['items'][0]['official']['online_date'] == '2023-02'
    assert all((tmp_path / 'audit' / name).exists() for name in (
        'audit.json', 'audit.csv', 'report.md', 'manual-download.csv'))
    unknown = audit_library(tmp_path, metadata={}, output=tmp_path / 'audit2')
    assert all(item.get('publication_status') != 'current' for item in unknown['items'])


def test_current_citation_does_not_prove_current_pdf(tmp_path):
    from acquire_research_papers.library import audit_library
    pair(tmp_path, raw=b'@article{k,title={Work},year={2025},volume={4},pages={10-20},issue_date={2025-01},doi={10.1234/test}}')
    official = {'doi':'10.1234/test', 'issue_date':'2025-01', 'volume':'4', 'pages':'10-20',
                'evidence_kind':'publisher_metadata'}
    item = audit_library(tmp_path, metadata={'10.1234/test': official})['items'][0]
    assert item['citation_status'] == 'current'
    assert item['local_version']['pdf'] == 'requires_verification'
    assert item['publication_status'] == 'unknown'
    pdf(tmp_path / 'paper.pdf', 'Early Access - DOI 10.1234/test')
    item = audit_library(tmp_path, metadata={'10.1234/test': official})['items'][0]
    assert item['publication_status'] == 'outdated'
    assert item['local_version']['pdf'] == 'early_access'


def test_organize_preserves_bib_bytes_and_apply_resume_rollback(tmp_path):
    from acquire_research_papers.library import apply_plan, organize_library
    root = tmp_path / 'library'
    raw = b'\xef\xbb\xbf@article{k,title={GPU and iPhone},journal={IEEE Tests},year={2023},doi={10.1234/test}}\r\n'
    pair(root, raw=raw)
    plan_path = tmp_path / 'plan.json'
    plan = organize_library(root, output=plan_path)
    assert all('GPU' in Path(item['target']).name and 'iPhone' in Path(item['target']).name
               for item in plan['actions'])
    assert apply_plan(plan_path)['status'] == 'applied'
    target = Path(next(item['target'] for item in plan['actions'] if item['target'].endswith('.bib')))
    assert target.read_bytes() == raw
    assert apply_plan(plan_path)['status'] == 'applied'
    assert apply_plan(plan_path, rollback=True)['status'] == 'rolled_back'
    assert (root / 'paper.bib').read_bytes() == raw
    assert (root / 'paper.pdf').exists()


def test_apply_rejects_changed_source_and_destination_collision(tmp_path):
    from acquire_research_papers.library import apply_plan, organize_library
    root = tmp_path / 'library'
    pair(root)
    plan = organize_library(root, output=tmp_path / 'plan.json')
    (root / 'paper.bib').write_bytes(b'changed')
    result = apply_plan(tmp_path / 'plan.json')
    assert result['status'] == 'failed'
    assert (root / 'paper.pdf').exists()
    assert 'hash' in str(result['items']).lower()
    # Preflight ensures no earlier move happens before a later hash failure.
    assert all(not Path(action['target']).exists() for action in plan['actions'])


def test_import_is_non_destructive_and_collision_names_are_deterministic(tmp_path):
    from acquire_research_papers.library import apply_plan, import_library
    source, target = tmp_path / 'incoming', tmp_path / 'library'
    pair(source, 'one', '10.1234/one')
    pair(source, 'two', '10.1234/two')
    first = import_library(source, target, output=tmp_path / 'plan.json')
    second = import_library(source, target, output=tmp_path / 'plan2.json')
    assert [a['target'] for a in first['actions']] == [a['target'] for a in second['actions']]
    assert len({a['target'].casefold() for a in first['actions']}) == 4
    assert apply_plan(tmp_path / 'plan.json')['status'] == 'applied'
    assert (source / 'one.bib').exists()
    assert len(list(target.glob('*.pdf'))) == 2


def test_gb18030_bib_decodes_without_transcoding_and_ambiguous_bib_is_skipped(tmp_path):
    from acquire_research_papers.library import audit_library, organize_library
    raw = '@article{k,title={中文研究},year={2025},doi={10.1234/cjk}}'.encode('gb18030')
    pair(tmp_path, doi='10.1234/cjk', raw=raw)
    (tmp_path / 'ambiguous.bib').write_text('@article{a,title={A}}\n@article{b,title={B}}')
    report = audit_library(tmp_path, metadata={})
    assert any(i.get('encoding') == 'gb18030' for i in report['items'])
    assert any(i['status'] == 'ambiguous' for i in report['items'])
    plan = organize_library(tmp_path, output=tmp_path / 'plan.json')
    assert any('中文研究' in item['target'] for item in plan['actions'])


def test_update_stages_pair_instead_of_touching_existing_library(tmp_path):
    from acquire_research_papers.library import update_library
    from types import SimpleNamespace
    root = tmp_path / 'library'
    raw = pair(root)
    class Application:
        def fetch(self, value, output):
            assert value == '10.1234/test'
            pair(output, 'official', raw=b'@article{k,title={Work},year={2024},volume={4},pages={1--2},doi={10.1234/test}}')
            return SimpleNamespace(status='delivered')
    result = update_library(root, output=tmp_path / 'updates', application=Application(),
        metadata={'10.1234/test': {'doi':'10.1234/test', 'issue_date':'2024',
            'volume':'4', 'pages':'1-2', 'status':'published'}})
    assert (root / 'paper.bib').read_bytes() == raw
    assert result['items'][0]['status'] == 'staged'
    assert Path(result['plan']).exists()


def test_chapter_import_needs_explicit_identity_and_boundaries(tmp_path):
    from acquire_research_papers.library import apply_plan, import_library
    root = tmp_path / 'book'
    pair(root)
    chapter = {'source': 'paper.pdf', 'start_page':1, 'end_page':1,
               'doi':'10.1234/chapter', 'title':'A Chapter', 'year':'2025',
               'bib': '@incollection{k,title={A Chapter},year={2025},doi={10.1234/chapter}}'}
    result = import_library(root, tmp_path / 'library', output=tmp_path / 'plan.json',
                            chapters=[chapter])
    assert any(action.get('provenance', {}).get('page_range') == [1,1]
               for action in result['actions'])
    assert apply_plan(tmp_path / 'plan.json')['status'] == 'applied'
    assert (root / 'paper.pdf').exists()


def test_cli_registration_dispatch_and_offline_fixture(tmp_path):
    from acquire_research_papers import library_cli
    pair(tmp_path / 'library')
    metadata = tmp_path / 'metadata.json'
    metadata.write_text('{}')
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest='command')
    library_cli.register(modes)
    args = parser.parse_args(['library','audit',str(tmp_path/'library'), '--metadata', str(metadata),
                              '--output',str(tmp_path/'audit')])
    assert library_cli.dispatch(args)['summary']['pairs'] == 1
    assert library_cli.dispatch(argparse.Namespace(command='fetch')) is None


def test_official_ieee_metadata_distinguishes_online_and_issue_dates():
    from acquire_research_papers.library.metadata import parse_publisher_metadata
    page = '''<html><script>xplGlobal.document.metadata = {
      "doi":"10.1109/TEST.1", "title":"A GPU Study", "publicationTitle":"IEEE Tests",
      "publicationDate":"June 2025", "dateOfPublication":"20 December 2024",
      "volume":"9", "issue":"6", "startPage":"1", "endPage":"12"
    };</script></html>'''
    record = parse_publisher_metadata(page, 'https://ieeexplore.ieee.org/document/123', '10.1109/test.1')
    assert record['issue_date'] == '2025-06'
    assert record['online_date'] == '2024-12-20'
    assert record['pages'] == '1-12'
    assert record['evidence_kind'] == 'publisher_metadata'


def test_crossref_alone_is_not_publisher_version_proof(tmp_path):
    from acquire_research_papers.library import audit_library
    pair(tmp_path)
    report = audit_library(tmp_path, metadata={'10.1234/test': {
        'doi':'10.1234/test','evidence_kind':'discovery_registry',
        'issue_date':'2025-01','online_date':'2023-02','volume':'9','pages':'1-12'}})
    assert report['items'][0]['publication_status'] == 'possible_update'
    assert report['items'][0]['official']['evidence_kind'] == 'discovery_registry'


def test_apply_recovers_interrupted_case_only_rename(tmp_path):
    import shutil
    from acquire_research_papers.library import apply_plan, organize_library
    from acquire_research_papers.library.metadata import write_json
    root = tmp_path / 'library'
    pair(root)
    plan_path = tmp_path / 'plan.json'
    plan = organize_library(root, output=plan_path)
    backup = root/'.arp-backups'/plan['sha256'][:16]
    backup.mkdir(parents=True)
    # Simulate power loss after journaling and removing a case-only source.
    action = plan['actions'][0]
    source = Path(action['source'])
    shutil.copyfile(source, backup/'0.source')
    source.unlink()
    write_json(backup/'journal.json', {'plan':plan['sha256'], 'items':{'0':{'status':'prepared'}}})
    result = apply_plan(plan_path)
    assert result['status'] == 'applied'
    assert Path(action['target']).exists()


def test_apply_destination_collision_and_modified_output_rollback_protection(tmp_path):
    from acquire_research_papers.library import apply_plan, organize_library
    root = tmp_path / 'library'
    pair(root)
    path = tmp_path / 'plan.json'
    plan = organize_library(root, output=path)
    target = Path(plan['actions'][0]['target'])
    target.write_bytes(b'unrelated')
    assert apply_plan(path)['status'] == 'failed'
    assert target.read_bytes() == b'unrelated'
    target.unlink()
    assert apply_plan(path)['status'] == 'applied'
    target.write_bytes(b'edited')
    result = apply_plan(path, rollback=True)
    assert result['status'] == 'failed'
    assert target.read_bytes() == b'edited'


def test_pdf_bib_delivery_bundle_pairs_by_hash_bound_provenance(tmp_path):
    from acquire_research_papers.library import scan_library
    from acquire_research_papers.library.metadata import digest
    pair(tmp_path)
    (tmp_path/'paper.bib').rename(tmp_path/'citation.bib')
    (tmp_path/'provenance.json').write_text(json.dumps({'metadata':{'doi':'10.1234/test'},
        'pdf_sha256':digest(tmp_path/'paper.pdf'), 'bibtex_sha256':digest(tmp_path/'citation.bib')}))
    report = scan_library(tmp_path)
    assert report['summary']['pairs'] == 1
    assert report['items'][0]['pairing_evidence'] == 'hash_bound_provenance'


def test_apply_tampered_plan_is_rejected(tmp_path):
    from acquire_research_papers.library import apply_plan, organize_library
    root = tmp_path / 'library'
    pair(root)
    path = tmp_path/'plan.json'
    plan = organize_library(root, output=path)
    plan['actions'][0]['target'] = str(tmp_path/'stolen.pdf')
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match='digest'):
        apply_plan(path)
    assert (root/'paper.pdf').exists()


def test_bounded_manual_watch_does_not_accept_preexisting_downloads(tmp_path):
    from acquire_research_papers.library import update_library
    root, incoming = tmp_path/'library', tmp_path/'incoming'
    pair(root)
    pair(incoming)
    result = update_library(root, output=tmp_path/'update', watch=incoming,
        timeout=0.25, poll_interval=0.1, metadata={'10.1234/test':{
            'doi':'10.1234/test','volume':'2','pages':'1-2','issue_date':'2025'}})
    assert result['status'] == 'manual_required'
    assert result['items'][0]['reason'] == 'preexisting_download_use_explicit_import'
    assert len(list((tmp_path/'update').glob('*manual*csv'))) == 1
    assert (root/'paper.pdf').exists()


def test_update_apply_backs_up_replacements_and_rolls_back(tmp_path):
    import json
    from acquire_research_papers.library import apply_plan, update_library
    from types import SimpleNamespace
    root = tmp_path/'library'
    old = pair(root)
    old_pdf = (root/'paper.pdf').read_bytes()
    class App:
        def fetch(self, doi, output):
            raw = b'@article{k,title={A New Title},year={2025},volume={2},pages={1--2},doi={10.1234/test}}'
            pair(output, raw=raw)
            pdf(output/'paper.pdf', 'New publisher PDF DOI 10.1234/test')
            return SimpleNamespace(pdf=output/'paper.pdf', bibtex=output/'paper.bib')
    result = update_library(root, output=tmp_path/'update', application=App(),
        metadata={'10.1234/test':{'doi':'10.1234/test','volume':'2','pages':'1-2','issue_date':'2025'}})
    plan = json.loads(Path(result['plan']).read_text())
    backup = root/'.arp-backups'/plan['sha256'][:16]
    backup.mkdir(parents=True)
    # Simulate interrupted replacement after prepare, before removing the original target.
    from acquire_research_papers.library.metadata import write_json
    write_json(backup/'journal.json', {'plan':plan['sha256'], 'items':{'0':{'status':'prepared'}}})
    assert apply_plan(result['plan'])['status'] == 'applied'
    assert (root/'paper.bib').read_bytes() != old
    assert apply_plan(result['plan'], rollback=True)['status'] == 'rolled_back'
    assert (root/'paper.bib').read_bytes() == old
    assert (root/'paper.pdf').read_bytes() == old_pdf


def test_rollback_refuses_corrupted_backup(tmp_path):
    from acquire_research_papers.library import apply_plan, organize_library
    root = tmp_path/'library'
    pair(root)
    path = tmp_path/'plan.json'
    plan = organize_library(root, output=path)
    result = apply_plan(path)
    (Path(result['backup'])/'0.source').write_bytes(b'broken backup')
    result = apply_plan(path, rollback=True)
    assert result['status'] == 'failed'
    assert Path(plan['actions'][0]['target']).exists()


def test_official_metadata_client_falls_back_with_explicit_registry_authority():
    from acquire_research_papers.library.metadata import OfficialMetadataClient
    class Response:
        def json(self):
            return {'message':{'DOI':'10.1109/test.1','title':['Work'],
                'resource':{'primary':{'URL':'https://ieeexplore.ieee.org/document/1'}},
                'published-print':{'date-parts':[[2025,1]]},'volume':'3','page':'1-2'}}
    class Http:
        def get(self, url):
            return Response()
    class Blocked:
        def __init__(self, **kwargs): pass
        def get(self, url): raise RuntimeError('blocked response containing private credentials')
        def close(self): pass
    result = OfficialMetadataClient(http=Http(), publisher_http_factory=Blocked).lookup('10.1109/test.1')
    assert result['evidence_kind'] == 'discovery_registry'
    assert result['publisher_lookup_error'] == 'RuntimeError'
    assert 'credentials' not in str(result)


def test_sciencedirect_metadata_never_requests_the_article_page():
    from acquire_research_papers.library.metadata import OfficialMetadataClient
    class Response:
        def json(self):
            return {'message':{'DOI':'10.1016/test.1', 'resource':{'primary':{
                'URL':'https://www.sciencedirect.com/science/article/pii/S123'}}}}
    class Http:
        def get(self, url): return Response()
    def forbidden(**kwargs):
        raise AssertionError('ScienceDirect HTML must remain manual')
    result = OfficialMetadataClient(http=Http(), publisher_http_factory=forbidden).lookup('10.1016/test.1')
    assert result['evidence_kind'] == 'discovery_registry'
    assert 'publisher_lookup_error' not in result


def test_filename_only_identity_is_review_only(tmp_path):
    from acquire_research_papers.library import scan_library, organize_library
    pair(tmp_path)
    pdf(tmp_path/'paper.pdf')
    assert scan_library(tmp_path)['items'][0]['status'] == 'ambiguous'
    assert not organize_library(tmp_path, output=tmp_path/'plan.json')['actions']


def test_library_apply_refuses_concurrent_mutations(tmp_path):
    from acquire_research_papers.library import organize_library, apply_plan
    from acquire_research_papers.library.plans import _apply_lock
    root = tmp_path/'library'
    pair(root)
    path = tmp_path/'plan.json'
    organize_library(root, output=path)
    with _apply_lock(root/'.arp-backups'/'.apply.lock'):
        with pytest.raises(ValueError, match='another apply'):
            apply_plan(path)
    assert (root/'paper.pdf').exists()
    assert apply_plan(path)['status'] == 'applied'


def test_update_preserves_official_source_provenance_through_apply_and_rollback(tmp_path):
    from types import SimpleNamespace
    from acquire_research_papers.library import update_library, apply_plan, scan_library
    from acquire_research_papers.library.metadata import digest
    root = tmp_path/'library'
    pair(root)
    class App:
        def fetch(self, doi, output):
            pair(output, raw=b'@article{k,title={Work},year={2025},volume={2},pages={1--2},doi={10.1234/test}}')
            proof = output/'provenance.json'
            proof.write_text(json.dumps({'metadata':{'doi':doi}, 'pdf_sha256':digest(output/'paper.pdf'),
                'bibtex_sha256':digest(output/'paper.bib'), 'bibtex_source':'publisher_export_api',
                'official_bibtex_url':'https://publisher.example/export'}))
            return SimpleNamespace(pdf=output/'paper.pdf', bibtex=output/'paper.bib', provenance=proof)
    result = update_library(root, output=tmp_path/'updates', application=App(),
        metadata={'10.1234/test':{'doi':'10.1234/test','volume':'2','pages':'1-2','issue_date':'2025'}})
    assert apply_plan(result['plan'])['status'] == 'applied'
    assert scan_library(root)['items'][0]['citation_source'] == 'publisher_export_api'
    assert apply_plan(result['plan'], rollback=True)['status'] == 'rolled_back'
    assert scan_library(root)['items'][0]['citation_source'] == 'manual_import'


def test_raw_chapter_citation_bytes_and_identity_are_preserved(tmp_path):
    from acquire_research_papers.library import import_library, apply_plan
    source = tmp_path/'source'
    pair(source)
    raw = b'\xef\xbb\xbf@incollection{k,title={A Chapter},year={2025},doi={10.1234/chapter}}\r\n'
    (source/'chapter.bib').write_bytes(raw)
    chapter = {'source':'paper.pdf', 'bib_file':'chapter.bib', 'doi':'10.1234/chapter',
               'title':'A Chapter', 'year':2025, 'start_page':1, 'end_page':1}
    plan = import_library(source, tmp_path/'destination', output=tmp_path/'plan.json', chapters=[chapter])
    assert apply_plan(tmp_path/'plan.json')['status'] == 'applied'
    action = next(a for a in plan['actions'] if a.get('provenance') and a['target'].endswith('.bib'))
    assert Path(action['target']).read_bytes() == raw
    with pytest.raises(ValueError, match='title/year'):
        import_library(source, tmp_path/'another', output=tmp_path/'wrong.json',
                       chapters=[{**chapter, 'title':'Wrong'}])


def test_new_manual_pair_is_staged_only_after_identity_and_placement_check(tmp_path, monkeypatch):
    import time
    from acquire_research_papers.library import update_library
    root, incoming = tmp_path/'library', tmp_path/'incoming'
    pair(root)
    incoming.mkdir()
    real_sleep = time.sleep
    def deliver(duration):
        if not (incoming/'paper.bib').exists():
            pair(incoming, raw=b'@article{k,title={Work},year={2025},volume={2},pages={1--2},doi={10.1234/test}}')
        real_sleep(duration)
    monkeypatch.setattr(time, 'sleep', deliver)
    result = update_library(root, output=tmp_path/'updates', watch=incoming, timeout=0.4,
        poll_interval=0.1, metadata={'10.1234/test':{'doi':'10.1234/test', 'volume':'2',
                                                  'pages':'1-2', 'issue_date':'2025'}})
    assert result['status'] == 'staged'


def test_update_repairs_missing_pdf_and_rolls_back_provenance(tmp_path):
    from types import SimpleNamespace
    from acquire_research_papers.library import update_library, apply_plan, scan_library
    root = tmp_path/'library'
    original_bib = pair(root)
    (root/'paper.pdf').unlink()
    class App:
        def fetch(self, doi, output):
            pair(output)
            return SimpleNamespace(pdf=output/'paper.pdf', bibtex=output/'paper.bib')
    result = update_library(root, output=tmp_path/'updates', application=App(), metadata={})
    assert apply_plan(result['plan'])['status'] == 'applied'
    assert (root/'paper.provenance.json').is_file()
    assert scan_library(root)['items'][0]['citation_source'] == 'manual_import'
    assert apply_plan(result['plan'], rollback=True)['status'] == 'rolled_back'
    assert not (root/'paper.pdf').exists()
    assert not (root/'paper.provenance.json').exists()
    assert (root/'paper.bib').read_bytes() == original_bib


def test_multiple_pdf_dois_require_identity_review_before_organize(tmp_path):
    from acquire_research_papers.library import scan_library, organize_library
    pair(tmp_path)
    pdf(tmp_path/'paper.pdf', 'DOI 10.1234/test and DOI 10.1234/other')
    assert scan_library(tmp_path)['items'][0]['status'] == 'ambiguous'
    assert not organize_library(tmp_path, output=tmp_path/'plan.json')['actions']
