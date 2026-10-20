import json

import pytest

from acquire_research_papers.run_context import RunContext, RunLocked


def test_resume_reuses_only_matching_inputs_and_unchanged_outputs(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('first')
    output = tmp_path / 'output.txt'
    calls = []

    def work():
        calls.append(1)
        output.write_text(source.read_text())
        return {'status': 'complete', 'outputs': [str(output)], 'completed': 1}

    context = RunContext(tmp_path / 'run')
    context.execute('copy', inputs=[source], parameters={}, operation=work)
    assert context.execute('copy', inputs=[source], parameters={}, operation=work)['reused']
    output.write_text('tampered')
    context.execute('copy', inputs=[source], parameters={}, operation=work)
    source.write_text('second')
    context.execute('copy', inputs=[source], parameters={}, operation=work)
    assert len(calls) == 3
    assert output.read_text() == 'second'


def test_lock_is_exclusive_and_released_after_error(tmp_path):
    context = RunContext(tmp_path)
    with context.lock():
        with pytest.raises(RunLocked):
            with RunContext(tmp_path).lock():
                pass
    with pytest.raises(ZeroDivisionError):
        context.execute('bad', inputs=[], parameters={}, operation=lambda: 1 / 0)
    with context.lock():
        pass
    state = context.status()
    assert state['steps']['bad']['status'] == 'failed'
    assert state['next_actions']


def test_pending_items_are_distinct_and_retryable(tmp_path):
    context = RunContext(tmp_path)
    result = context.execute('fetch', inputs=[], parameters={}, operation=lambda: {
        'status': 'user_download', 'completed': 1,
        'items': {'a': {'status': 'complete'}, 'b': {'status': 'user_download'}},
        'next_actions': [{'action': 'manual-fetch', 'item': 'b'}],
    })
    assert result['completed'] == 1
    assert context.status()['next_actions'] == [{'action': 'manual-fetch', 'item': 'b'}]
    manifest = json.loads((tmp_path / 'run-context.json').read_text())
    assert manifest['steps']['fetch']['items']['b']['status'] == 'user_download'


def test_status_detects_output_changes_without_mutating_record(tmp_path):
    output = tmp_path / 'result.txt'
    output.write_text('ok')
    context = RunContext(tmp_path / 'run')
    context.execute('result', inputs=[], parameters={}, operation=lambda: {
        'status': 'complete', 'outputs': [str(output)]})
    output.unlink()
    assert context.status()['steps']['result']['status'] == 'stale'


@pytest.mark.parametrize('change', ['modify', 'delete'])
def test_status_detects_changed_or_missing_inputs_without_rewriting_audit(tmp_path, change):
    source = tmp_path / 'source.txt'
    source.write_text('original')
    output = tmp_path / 'result.txt'
    output.write_text('complete output')
    context = RunContext(tmp_path / 'run')
    context.execute('copy', inputs=[source], parameters={}, operation=lambda: {
        'status': 'complete', 'outputs': [str(output)]})
    recorded = context.path.read_bytes()
    if change == 'modify':
        source.write_text('changed')
    else:
        source.unlink()

    status = context.status()

    assert status['steps']['copy']['status'] == 'stale'
    assert status['next_actions'] == [{'action': 'rerun', 'step': 'copy', 'reason': 'input_changed'}]
    assert context.path.read_bytes() == recorded


@pytest.mark.parametrize('change', ['modify', 'delete'])
def test_execute_does_not_complete_when_input_changes_during_operation(tmp_path, change):
    source = tmp_path / 'source.txt'
    source.write_text('before')
    output = tmp_path / 'result.txt'
    context = RunContext(tmp_path / 'run')
    def operation():
        output.write_text(source.read_text())
        if change == 'modify':
            source.write_text('after')
        else:
            source.unlink()
        return {'status': 'complete', 'outputs': [str(output)]}

    result = context.execute('copy', inputs=[source], parameters={}, operation=operation)

    assert result['status'] == 'stale'
    assert result['next_actions'] == [{'action': 'rerun', 'step': 'copy', 'reason': 'input_changed'}]
    recorded = json.loads(context.path.read_text(encoding='utf-8'))
    assert recorded['steps']['copy']['status'] == 'stale'
    assert recorded['steps']['copy']['result']['status'] == 'stale'


def test_status_reports_both_input_and_output_changes(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('original')
    output = tmp_path / 'result.txt'
    output.write_text('output')
    context = RunContext(tmp_path / 'run')
    context.execute('copy', inputs=[source], parameters={}, operation=lambda: {
        'status': 'complete', 'outputs': [str(output)]})
    source.write_text('changed')
    output.unlink()

    status = context.status()

    assert status['steps']['copy']['status'] == 'stale'
    assert status['next_actions'] == [
        {'action': 'rerun', 'step': 'copy', 'reason': 'input_changed'},
        {'action': 'rerun', 'step': 'copy', 'reason': 'output_changed'},
    ]
