import json

from acquire_research_papers.artifacts import sha256_file
from acquire_research_papers.legacy_runs import status


def test_existing_discovery_is_read_without_rewriting_and_detects_changed_candidates(tmp_path):
    candidates = tmp_path / 'candidates.jsonl'
    candidates.write_text('{}')
    manifest = tmp_path / 'discovery-manifest.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'status': 'review_required',
        'candidates': candidates.name, 'candidates_sha256': sha256_file(candidates)}))
    original = manifest.read_bytes()
    result = status(tmp_path)
    assert result['compatibility_adapter']
    assert result['next_actions'][0]['action'] == 'review'
    assert not (tmp_path / 'run-context.json').exists()
    candidates.write_text('changed')
    assert status(tmp_path)['steps']['discovery']['status'] == 'stale'
    assert manifest.read_bytes() == original


def test_changed_delivery_is_never_reported_complete(tmp_path):
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(b'original')
    rows = tmp_path / 'acquisition-manifest.jsonl'
    rows.write_text(json.dumps({'state': 'delivered', 'pdf': str(pdf),
                                'pdf_sha256': sha256_file(pdf)}))
    (tmp_path / 'delivery-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'status': 'delivered', 'acquisition_manifest': rows.name}))
    pdf.unlink()
    assert status(tmp_path)['steps']['acquisition']['status'] == 'stale'


def test_legacy_manifest_cannot_follow_an_external_artifact(tmp_path):
    import pytest
    (tmp_path / 'discovery-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'candidates': '../outside.jsonl', 'candidates_sha256': 'a' * 64}))
    with pytest.raises(ValueError, match='leaves'):
        status(tmp_path)


def test_truncated_delivery_rows_are_stale_even_with_unchanged_delivery_manifest(tmp_path):
    rows = tmp_path / 'acquisition-manifest.jsonl'
    rows.write_text('')
    (tmp_path / 'delivery-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'status': 'delivered', 'acquisition_manifest': rows.name,
        'total': 1, 'delivered': 1, 'manual_required': 0, 'retryable': 0, 'contract_error': 0}))
    result = status(tmp_path)
    assert result['steps']['acquisition']['status'] == 'stale'
    assert result['next_actions'][0]['action'] == 'inspect'
