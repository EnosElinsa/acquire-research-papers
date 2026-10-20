import json
from pathlib import Path

from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.mineru import MineruCache, MineruResult
from acquire_research_papers.paths import AppPaths


def test_offline_capabilities_and_run_status_never_initialize_browser(tmp_path, monkeypatch, capsys):
    def forbidden(**kwargs):
        raise AssertionError('offline operation initialized browser')
    monkeypatch.setattr(Application, 'default', forbidden)
    a, b, output = [tmp_path / name for name in ('a.json', 'b.json', 'comparison.json')]
    a.write_text(json.dumps([{'doi': '10.1234/a', 'title': 'Same title'}]))
    b.write_text(json.dumps([{'doi': '10.1234/b', 'title': 'Same title'}]))
    args = ['collection', 'compare', '--left', str(a), '--right', str(b),
            '--output', str(output), '--run', str(tmp_path / 'run')]
    assert run_cli(args) == 0
    capsys.readouterr()
    assert run_cli(args) == 0
    assert json.loads(capsys.readouterr().out)['reused']
    assert run_cli(['run', 'status', '--run', str(tmp_path / 'run')]) == 0
    assert not json.loads(capsys.readouterr().out)['next_actions']


def test_parse_works_without_bibtex_and_evidence_is_bound_to_parse(tmp_path, capsys):
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(b'%PDF-1.4\nbody\n%%EOF\n')
    calls = []
    def parser(source: Path, output: Path):
        calls.append(source)
        output = output / 'parsed'
        output.mkdir(parents=True, exist_ok=True)
        markdown = output / 'paper.md'
        markdown.write_text('A precise finding in the full text.', encoding='utf-8')
        return MineruResult('fixture', output, markdown)
    app = Application.for_test(app_root=tmp_path / 'data', repository_root=tmp_path / 'repo',
                              mineru_cache=MineruCache(tmp_path / 'cache', runner=parser))
    output = tmp_path / 'parse.json'
    assert run_cli(['parse', '--pdf', str(pdf), '--output', str(output), '--run', str(tmp_path / 'run')],
                   application=app) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result['official_acquisition_complete']
    assert len(calls) == 1
    decision = {'schema_version': 2, 'reviewer': 'kiro-cli', 'executor': {'host': 'kiro-cli'},
        'policy': 'fulltext', 'policy_version': '1', 'reason': 'Exact full-text evidence',
        'full_text_sha256': result['full_text_sha256'], 'markdown_sha256': result['markdown_sha256'],
        'records': [{'claim_id': 'claim', 'paper_id': result['paper_id'], 'relation': 'direct-support',
            'read_scope': 'full-text', 'section': 'Results', 'page': None,
            'excerpt': 'A precise finding', 'explanation': 'Explicit result'}]}
    records = tmp_path / 'evidence.json'
    records.write_text(json.dumps([decision]))
    args = ['evidence', 'validate', '--parse-result', str(output), '--records', str(records),
            '--output', str(tmp_path / 'validated.json'), '--run', str(tmp_path / 'evidence-run')]
    assert run_cli(args, application=app) == 0
    capsys.readouterr()
    Path(result['markdown']).write_text('Changed text')
    assert run_cli(args, application=app) == 64
    assert 'hash' in json.loads(capsys.readouterr().out)['message']


def test_env_file_can_be_before_or_after_subcommands(tmp_path, monkeypatch, capsys):
    from acquire_research_papers import configuration_commands as config
    monkeypatch.setattr(config, 'runtime_paths', lambda: AppPaths.for_root(tmp_path))
    selected = tmp_path / 'selected.env'
    selected.write_text('OPENALEX_API_KEY=example\n')
    for args in (['--env-file', str(selected), 'config', 'status'],
                 ['config', 'status', '--env-file', str(selected)]):
        assert run_cli(args) == 0
        result = json.loads(capsys.readouterr().out)
        assert result['openalex']
        assert 'example' not in json.dumps(result)


def test_capability_output_redacts_tokens_in_records_and_signed_urls(tmp_path, capsys):
    source = tmp_path / 'records.json'
    source.write_text(json.dumps([{'doi': '10.1234/a', 'password': 'private-sentinel',
        'official_url': 'https://publisher.example/a?token=private-sentinel'}]))
    empty = tmp_path / 'empty.json'
    empty.write_text('[]')
    output = tmp_path / 'merged.json'
    assert run_cli(['collection', 'merge', '--left', str(source), '--right', str(empty),
                    '--output', str(output), '--run', str(tmp_path / 'run')]) == 0
    assert 'private-sentinel' not in capsys.readouterr().out
    assert 'private-sentinel' not in output.read_text()
    assert 'private-sentinel' not in (tmp_path / 'run/run-context.json').read_text()


def test_jsonl_preserves_unicode_line_separator_and_rejects_bad_source_ids(tmp_path, capsys):
    source = tmp_path / 'records.jsonl'
    source.write_text(json.dumps({'doi': '10.1234/a', 'title': 'A\u2028B'}, ensure_ascii=False) + '\n', encoding='utf-8')
    output = tmp_path / 'export.json'
    assert run_cli(['export', '--input', str(source), '--format', 'json', '--output', str(output)]) == 0
    capsys.readouterr()
    assert json.loads(output.read_text(encoding='utf-8'))[0]['title'] == 'A\u2028B'
    source.write_text(json.dumps({'doi': '10.1234/a', 'source_ids': []}))
    empty = tmp_path / 'empty.json'
    empty.write_text('[]')
    assert run_cli(['collection', 'merge', '--left', str(source), '--right', str(empty),
                    '--output', str(output)]) == 64
    assert 'source_ids' in capsys.readouterr().out


def test_acquisition_revalidates_frozen_selection_before_reusing_run(tmp_path, capsys):
    from acquire_research_papers.acquisition.corpus import CorpusAcquisitionWorkflow
    from acquire_research_papers.selection import SelectionStore
    selection = SelectionStore.write(tmp_path / 'selection', {}, ())
    app = Application.for_test(app_root=tmp_path / 'data', repository_root=tmp_path / 'repo')
    app.corpus_acquisition = CorpusAcquisitionWorkflow(acquirer=lambda *a: None)
    args = ['acquire', 'selection', '--selection', str(selection.manifest_path),
            '--output', str(tmp_path / 'delivery'), '--run', str(tmp_path / 'run')]
    assert run_cli(args, application=app) == 0
    capsys.readouterr()
    assert run_cli(args, application=app) == 0
    assert json.loads(capsys.readouterr().out)['reused']
    selection.selected_path.write_text('tampered')
    assert run_cli(args, application=app) == 64
    assert 'SHA-256' in capsys.readouterr().out


def test_permanent_acquisition_failure_requires_source_inspection(tmp_path, capsys):
    from acquire_research_papers.acquisition.corpus import CorpusAcquisitionWorkflow
    from acquire_research_papers.selection import SelectionStore, build_selection_records
    from acquire_research_papers.discovery.contracts import CandidateMetadata
    from acquire_research_papers.bibliography import MetadataMismatch
    record = CandidateMetadata(key='a', title='Paper', year=2026, venue='Journal',
        relevance_score=0, hard_gates_passed=True, evidence_fields=('doi',), doi='10.1234/a')
    selection = SelectionStore.write(tmp_path / 'selection', {},
        build_selection_records([record], venues=(), delivery={}))
    def fail(*args):
        raise MetadataMismatch('publisher identity differs')
    app = Application.for_test(app_root=tmp_path / 'data', repository_root=tmp_path / 'repo')
    app.corpus_acquisition = CorpusAcquisitionWorkflow(acquirer=fail)
    assert run_cli(['acquire', 'selection', '--selection', str(selection.manifest_path),
                    '--output', str(tmp_path / 'delivery')], application=app) == 78
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'failed'
    assert result['next_actions'][0]['action'] == 'inspect-source'


def test_same_capability_for_multiple_inputs_keeps_each_step_in_one_run(tmp_path, capsys):
    run = tmp_path / 'run'
    for key in ('a', 'b'):
        assert run_cli(['metadata', 'resolve', '--input', '10.1234/' + key,
            '--output', str(tmp_path / (key + '.json')), '--run', str(run)]) == 0
        capsys.readouterr()
    assert len(json.loads((run / 'run-context.json').read_text())['steps']) == 2


def test_resolve_candidate_file_preserves_ambiguous_identity(tmp_path, capsys):
    source = tmp_path / 'candidate.json'
    source.write_text(json.dumps({'doi': '10.1234/a', 'source_ids': {'doi': '10.1234/b'}}))
    assert run_cli(['metadata', 'resolve', '--input', str(source), '--output', str(tmp_path / 'identity.json')]) == 0
    assert json.loads(capsys.readouterr().out)['identity_status'] == 'ambiguous'
