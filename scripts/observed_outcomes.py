"""Validate measured comparisons inside the existing browser report.

This is not a browser runner or a visual/semantic acceptance verdict. The first
independent review still checks the actual interaction, source and screenshots.
"""
import math

POLICY = 'observed-outcomes-v1'


def outcome_policy(run):
    if 'web_outcome_policy' not in run:
        return None
    if run['web_outcome_policy'] != POLICY:
        raise ValueError('Unknown Web outcome policy')
    return POLICY


def _json(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _json(v) for k, v in value.items())
    return False


def _same(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def _substantive(value):
    if type(value) in (int, float):
        return True
    if isinstance(value, str):
        return value.strip().casefold() not in {'', 'ok', 'success', 'passed', 'pass', '成功', '通过', '完成'}
    if isinstance(value, dict):
        return any(_substantive(v) for v in value.values())
    if isinstance(value, list):
        return any(_substantive(v) for v in value)
    return False


def _comparisons(rows, label):
    if not isinstance(rows, list) or not rows:
        raise ValueError('Web outcome requires observed comparisons: ' + label)
    labels = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid Web outcome comparison: ' + label)
        name = row.get('label')
        if not isinstance(name, str) or not name.strip() or name in labels:
            raise ValueError('Web outcome comparison needs distinct labels: ' + label)
        labels.add(name)
        if 'expected' not in row or 'actual' not in row:
            raise ValueError('Web outcome needs expected and actual values: ' + label)
        if not _json(row['expected']) or not _json(row['actual']):
            raise ValueError('Web outcome must contain finite JSON values: ' + label)
        if not _same(row['expected'], row['actual']):
            raise ValueError('Web observed result differs from expected: ' + label + '/' + name)
    if not any(_substantive(row['actual']) for row in rows):
        raise ValueError('Web outcome cannot be only success flags or empty values: ' + label)


def validate_observed_outcomes(run, report, assertions):
    if not outcome_policy(run):
        return {}
    if not run.get('web_experience_policy'):
        raise ValueError('Web outcome policy requires its existing Web evidence contract')
    core = report.get('core_outcomes')
    roles = ('primary', 'changed_input', 'recovery')
    if not isinstance(core, dict) or not all(isinstance(core.get(k), str) and core[k] in assertions for k in roles):
        raise ValueError('Web core_outcomes must reference primary, changed_input and recovery assertions')
    if len({core[k] for k in roles}) != len(roles):
        raise ValueError('Web core outcome roles require distinct existing assertions')
    for role in roles:
        assertion = assertions[core[role]]
        if assertion.get('passed') is not True:
            raise ValueError('Web core outcome assertion did not pass: ' + role)
        inputs = assertion.get('observed_input')
        if not isinstance(inputs, dict) or not inputs or not _json(inputs):
            raise ValueError('Web core outcome requires actual input snapshot: ' + role)
        _comparisons(assertion.get('comparisons'), role)
    first, changed = (assertions[core[k]] for k in ('primary', 'changed_input'))
    if first.get('workflow_id') != changed.get('workflow_id'):
        raise ValueError('Changed input must exercise the same primary workflow')
    if _same(first['observed_input'], changed['observed_input']):
        raise ValueError('Changed input did not change the primary workflow input')
    recovery = assertions[core['recovery']]
    failure = recovery.get('recovery_observation')
    if not isinstance(failure, dict) or not all(isinstance(failure.get(k), str) and failure[k].strip()
                                               for k in ('trigger', 'observed_error', 'resumed_action')):
        raise ValueError('Web recovery needs the actual failure and resumed action')
    return {'web_outcome_policy': POLICY, 'core_outcomes': {k: core[k] for k in roles}}
