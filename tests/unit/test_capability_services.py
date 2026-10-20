import json

import pytest
from pypdf import PdfWriter

from acquire_research_papers.capabilities import (
    compare_collections, freeze_selection, merge_collection, resolve_identity, verify_local_pair,
)


def candidate(doi='10.1234/a', title='Paper'):
    return {'key': title, 'title': title, 'doi': doi, 'year': 2026, 'venue': 'Journal',
            'official_url': 'https://publisher.example/paper', 'authors': ['Ada Lovelace'],
            'abstract': 'Original abstract', 'relevance_score': 0, 'hard_gates_passed': True,
            'evidence_fields': ['title', 'abstract']}


def test_collection_exact_identity_and_similarity_are_separate():
    first, second = candidate(), candidate('10.1234/b')
    result = compare_collections([first], [second])
    assert not result['shared']
    assert result['similarity_hints']
    assert resolve_identity({'doi': '10.1234/a', 'source_ids': {'doi': '10.1234/b'}})['status'] == 'ambiguous'
    assert resolve_identity({'title': 'Only a title'})['status'] == 'unresolved'


def test_merge_keeps_conflicting_metadata_and_original_values():
    first, changed = candidate(), {**candidate(), 'abstract': 'Other abstract'}
    merged = merge_collection([first, changed])
    assert len(merged['records']) == 1
    assert merged['records'][0]['abstract'] == 'Original abstract'
    assert merged['conflicts'][0]['field'] == 'abstract'


def test_independent_pair_verification_preserves_raw_bytes(tmp_path):
    pdf, bib = tmp_path / 'paper.pdf', tmp_path / 'citation.bib'
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({'/Title': 'Paper DOI 10.1234/a'})
    writer.write(pdf)
    raw = b'\xef\xbb\xbf@article{k,title={Paper},author={Lovelace, Ada},year={2026},journal={Journal},doi={10.1234/a}}\r\n'
    bib.write_bytes(raw)
    result = verify_local_pair(pdf, bib, candidate())
    assert result['status'] == 'complete'
    assert result['source_trust'] == 'user-supplied'
    assert not result['official_acquisition_complete']
    assert bib.read_bytes() == raw


def test_freeze_requires_hash_bound_accepted_reviews_and_never_rewrites(tmp_path):
    from acquire_research_papers.run_context import content_hash
    records = [candidate()]
    decision = {'identity': 'doi:10.1234/a', 'input_sha256': content_hash(records[0]),
                'decision': 'accept', 'reason': 'matches scope', 'policy': 'relevance',
                'policy_version': '1', 'evidence': ['title', 'abstract'], 'schema_version': 2,
                'reviewer': 'claude-code', 'executor': {'host': 'claude-code'}}
    result = freeze_selection(records, [decision], tmp_path)
    manifest = tmp_path / 'selection-manifest.json'
    before = manifest.read_bytes()
    freeze_selection(records, [decision], tmp_path)
    assert manifest.read_bytes() == before
    assert result['completed'] == 1
    with pytest.raises(ValueError, match='hash'):
        freeze_selection([{**records[0], 'title': 'Changed'}], [decision], tmp_path)
    assert json.loads(before)['schema_version'] == 1


def test_conflicting_duplicate_identities_require_explicit_merge_before_review():
    from acquire_research_papers.capabilities import validate_reviews
    from acquire_research_papers.run_context import content_hash
    first = candidate()
    changed = {**first, 'abstract': 'Changed abstract'}
    decision = {'identity': 'doi:10.1234/a', 'input_sha256': content_hash(changed),
                'decision': 'accept', 'reason': 'matches scope', 'policy': 'identity',
                'policy_version': '1', 'evidence': ['doi'], 'schema_version': 2,
                'reviewer': 'kiro-cli', 'executor': {'host': 'kiro-cli'}}
    with pytest.raises(ValueError, match='duplicate'):
        validate_reviews([first, changed], [decision], policy='identity')


def test_exports_preserve_numeric_zero_and_false():
    from acquire_research_papers.capability_cli import _export
    rows = [{'count': 0, 'enabled': False, 'missing': None}]
    assert '0,False,' in _export(rows, 'csv').decode('utf-8-sig')
    assert '| 0 | False |  |' in _export(rows, 'markdown').decode('utf-8')


def test_metadata_snapshot_hash_matches_public_sanitized_fields():
    from acquire_research_papers.capabilities import metadata_snapshots
    from acquire_research_papers.capability_cli import request_for
    from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator
    from acquire_research_papers.run_context import content_hash
    record = {**candidate(), 'official_url': 'https://publisher.example/a?token=private-sentinel'}
    result = metadata_snapshots([record], coordinator=DiscoveryCoordinator(()), request=request_for('enrich'))
    for snapshot in result['snapshots']:
        assert snapshot['content_sha256'] == content_hash(snapshot['fields'])
    assert 'private-sentinel' not in json.dumps(result)


def test_freezing_cannot_persist_signed_url_secrets(tmp_path):
    from acquire_research_papers.run_context import content_hash
    record = {**candidate(), 'official_url': 'https://publisher.example/a?token=private-sentinel'}
    decision = {'schema_version': 2, 'reviewer': 'codex', 'executor': {'host': 'codex'},
        'identity': 'doi:10.1234/a', 'input_sha256': content_hash(record), 'policy': 'identity',
        'policy_version': '1', 'decision': 'accept', 'reason': 'DOI checked', 'evidence': ['doi']}
    freeze_selection([record], [decision], tmp_path, policy='identity')
    assert 'private-sentinel' not in (tmp_path / 'selected-papers.jsonl').read_text()
