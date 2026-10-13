"""Read-only checks of actual exported CSV scale, identity, and known names.

This is schema/known-name validation, not general named-entity recognition.
Unknown text requires high's hash-bound review in the existing data selfcheck.
No source, mapping, provenance, or exported cell is silently edited.
"""
import csv
from datetime import datetime
import hashlib
import html
import math
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote


NAME_KINDS = {'person_name', 'company_name', 'geographic_name'}
NAME_HEADERS = {'姓名', '人名', '人员姓名', '公司名', '公司名称', '企业名称',
                '地名', '地区名称', '城市名称', 'personname',
                'companyname', 'cityname', 'locationname'}
KINDS = {'id', 'number', 'timestamp', 'enum', 'text'}


def _text(value):
    value = str(value)
    for _ in range(2):
        value = html.unescape(unquote(value))
        value = re.sub(r'\\u([0-9a-fA-F]{4})', lambda match: chr(int(match[1], 16)), value)
    return re.sub(r'[\u200b-\u200f\ufeff]', '', unicodedata.normalize('NFKC', value)).casefold()


def _digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def stable_entity_id(namespace, source_key):
    """Deterministic pseudonymous ID; retain original/mapping only internally.

    Use the SAME neutral namespace/key for an object across tables and downloads.
    Hash IDs are not a claim of irreversible anonymization or collision-free NER.
    """
    if not isinstance(namespace, str) or not re.fullmatch(r'[A-Z][A-Z0-9]{0,15}', namespace):
        raise ValueError('namespace must be a neutral uppercase ID prefix')
    if not isinstance(source_key, str) or not source_key.strip():
        raise ValueError('A nonempty stable source key is required')
    key = unicodedata.normalize('NFKC', source_key)
    return namespace+'_'+hashlib.sha256((namespace+'\0'+key).encode('utf-8')).hexdigest()


def audit_csv_exports(paths, schema, known_names=(), allowed_terms=(), name_review=None,
                      max_findings=100):
    """Stream selected CSVs and return evidence, never modify files.

    schema maps basename -> {columns:{name:{kind, pattern/values}}, primary_key,
    primary_key_kind, effective_key, object_columns, time_column, event_column,
    foreign_keys}. primary_key_kind defaults to 'surrogate'; 'natural' explicitly
    allows a meaningful typed business key to also be the effective key.
    effective_key must describe business identity/content, including real entity,
    time/event/measurement context as appropriate; surrogate row ID alone fails.
    Legitimate identifier-only dimensions may declare table_role='dimension'.
    name_review maps basename -> {sha256, filename_checked, columns_checked,
    text_checked, evidence}, supplied only after actual high review of THIS CSV.
    Known-name hits/prohibited schema/invalid references cannot be overridden by
    a generic review. A fully typed enum/ID schema still needs filename/header review.
    """
    if not isinstance(max_findings, int) or max_findings < 1:
        raise ValueError('max_findings must be a positive integer')
    paths = [Path(path) for path in paths]
    names = [path.name for path in paths]
    if len(names) != len(set(names)) or set(names) != set(schema):
        raise ValueError('Actual CSV set must exactly match selected schema basenames')
    known = sorted({_text(name) for name in known_names if str(name).strip()})
    allowed = {_text(term) for term in allowed_terms}
    findings, finding_count, reviews_needed = [], 0, []
    files, keys, references, file_hashes = {}, {}, [], {}

    def issue(filename, kind, **detail):
        nonlocal finding_count
        finding_count += 1
        if len(findings) < max_findings:
            findings.append({'file': filename, 'kind': kind, **detail})

    def check_names(filename, value, **detail):
        normalized = _text(value)
        for name in known:
            if name in normalized:
                issue(filename, 'known-name', matched=name, **detail)

    for path in paths:
        name = path.name
        if path.suffix.lower() != '.csv' or not path.is_file() or path.is_symlink():
            raise ValueError('Only actual regular CSV files may be audited')
        spec = schema[name]
        columns = spec.get('columns', {})
        if not isinstance(columns, dict) or not columns:
            raise ValueError('Explicit column schema required: '+name)
        for column, rule in columns.items():
            if not isinstance(rule, dict) or rule.get('kind') not in KINDS | NAME_KINDS:
                raise ValueError('Column kind required: '+name+':'+column)
            if rule['kind'] in NAME_KINDS or re.sub(r'[\s_\-]', '', _text(column)) in NAME_HEADERS:
                issue(name, 'name-column', column=column)
        primary = spec.get('primary_key', [])
        effective = spec.get('effective_key', [])
        if not primary or not effective or not set(primary+effective) <= set(columns):
            raise ValueError('Explicit valid primary_key/effective_key required: '+name)
        primary_kind = spec.get('primary_key_kind', 'surrogate')
        if primary_kind not in ('surrogate', 'natural'):
            raise ValueError('primary_key_kind must be surrogate or natural: '+name)
        object_columns = spec.get('object_columns', [])
        if not set(object_columns) <= set(columns):
            raise ValueError('Unknown object column: '+name)
        timestamp, event = spec.get('time_column'), spec.get('event_column')
        if (timestamp and timestamp not in columns) or (event and event not in columns):
            raise ValueError('Unknown time/event column: '+name)
        if timestamp and columns[timestamp]['kind'] != 'timestamp':
            raise ValueError('Declared time_column must have timestamp kind: '+name)
        if spec.get('table_role', 'detail') != 'dimension':
            if all(columns[column]['kind'] == 'id' for column in effective):
                raise ValueError('Detail effective_key needs actual business content, not only IDs: '+name)
            if primary_kind == 'natural':
                for label, key_columns in (('primary_key', primary), ('effective_key', effective)):
                    fields = set(key_columns)
                    typed_business = {column for column in fields
                                      if columns[column]['kind'] in ('number', 'timestamp', 'enum')}
                    entity = any(column in fields and columns[column]['kind'] == 'id'
                                 for column in object_columns)
                    timed = timestamp in fields and columns[timestamp]['kind'] == 'timestamp'
                    eventful = event in fields and columns[event]['kind'] == 'enum'
                    if not (entity and (timed or eventful)) and len(typed_business) < 2:
                        raise ValueError('Natural '+label+' needs entity/time/event semantics or two typed business fields: '+name)
            elif set(effective) <= set(primary):
                raise ValueError('effective_key cannot consist only of surrogate primary keys: '+name)
        start_hash = _digest(path)
        if start_hash in file_hashes:
            issue(name, 'duplicate-export', other_file=file_hashes[start_hash])
        file_hashes[start_hash] = name
        check_names(name, name, location='filename')
        for column in columns:
            check_names(name, column, location='header', column=column)
        row_signatures, effective_signatures, primary_values = set(), set(), set()
        objects = {column: set() for column in object_columns}
        events, unknown_text = {}, set()
        time_min = time_max = None
        rows = 0
        with path.open('r', encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames != list(columns) or len(reader.fieldnames or []) != len(set(reader.fieldnames or [])):
                raise ValueError('Actual ordered CSV columns must match explicit schema: '+name)
            for row in reader:
                rows += 1
                if None in row or any(value is None for value in row.values()):
                    issue(name, 'row-width', row=rows+1)
                    continue
                signature = hashlib.sha256(repr(tuple(row.values())).encode()).digest()
                if signature in row_signatures:
                    issue(name, 'duplicate-row', row=rows+1)
                row_signatures.add(signature)
                business = tuple(row[column] for column in effective)
                effective_signatures.add(business)
                key = tuple(row[column] for column in primary)
                if not all(key) or key in primary_values:
                    issue(name, 'invalid-primary-key', row=rows+1)
                primary_values.add(key)
                for column, rule in columns.items():
                    value = row[column]
                    check_names(name, value, location='cell', row=rows+1, column=column)
                    if value == '' and rule.get('nullable'):
                        continue
                    kind = rule['kind']
                    if kind == 'id':
                        pattern = rule.get('pattern')
                        if not pattern:
                            raise ValueError('ID schema needs a neutral full-match pattern: '+name+':'+column)
                        if not re.fullmatch(pattern, value):
                            issue(name, 'invalid-id', row=rows+1, column=column)
                    elif kind == 'number':
                        try:
                            numeric = float(value)
                            if not math.isfinite(numeric):
                                raise ValueError('Nonfinite')
                        except ValueError:
                            issue(name, 'invalid-number', row=rows+1, column=column)
                    elif kind == 'timestamp':
                        try:
                            datetime.fromisoformat(value.replace('Z', '+00:00'))
                        except ValueError:
                            issue(name, 'invalid-timestamp', row=rows+1, column=column)
                    elif kind == 'enum':
                        if 'values' not in rule:
                            raise ValueError('Enum schema requires explicit allowed business values')
                        if value not in rule['values']:
                            issue(name, 'unknown-enum', row=rows+1, column=column)
                    elif kind == 'text' and value and _text(value) not in allowed:
                        unknown_text.add(column)
                for column in object_columns:
                    if row[column]:
                        objects[column].add(row[column])
                if event:
                    events[row[event]] = events.get(row[event], 0)+1
                if timestamp and row[timestamp]:
                    try:
                        current = datetime.fromisoformat(row[timestamp].replace('Z', '+00:00'))
                        time_min = min(time_min, current) if time_min is not None else current
                        time_max = max(time_max, current) if time_max is not None else current
                    except (ValueError, TypeError):
                        issue(name, 'inconsistent-time', row=rows+1, column=timestamp)
                for reference in spec.get('foreign_keys', []):
                    ref_columns = reference['columns']
                    if not set(ref_columns) <= set(columns):
                        raise ValueError('Unknown foreign key columns')
                    value = tuple(row[column] for column in ref_columns)
                    if any(value) or not reference.get('nullable'):
                        references.append((name, rows+1, reference, value))
        if _digest(path) != start_hash:
            issue(name, 'file-changed-during-audit')
        if len(effective_signatures) < rows:
            issue(name, 'duplicate-business-content', duplicate_count=rows-len(effective_signatures))
        if rows == 0:
            issue(name, 'empty-csv')
        keys[name] = (primary, primary_values)
        files[name] = {'sha256': start_hash, 'rows': rows, 'effective_rows': len(effective_signatures),
                       'independent_objects': {column: len(values) for column, values in objects.items()},
                       'time_start': time_min.isoformat() if time_min is not None else None,
                       'time_end': time_max.isoformat() if time_max is not None else None,
                       'events': events, 'free_text_columns': sorted(unknown_text)}
        review = (name_review or {}).get(name, {})
        if (review.get('sha256') != start_hash or review.get('filename_checked') is not True
                or review.get('columns_checked') is not True or review.get('text_checked') is not True
                or not isinstance(review.get('evidence'), str) or not review['evidence'].strip()):
            reviews_needed.append(name)
    for name, row, reference, value in references:
        target = reference['target_file']
        if target not in keys or reference['target_columns'] != keys[target][0]:
            raise ValueError('References must target an exported primary key')
        if value not in keys[target][1]:
            issue(name, 'missing-foreign-key', row=row, target_file=target)
    return {'schema_version': 1,
            'data_status': 'fail' if finding_count else ('review_required' if reviews_needed else 'pass'),
            'files': files, 'findings': findings, 'finding_count': finding_count,
            'truncated_findings': max(0, finding_count-len(findings)),
            'name_review_required': reviews_needed,
            'name_method': 'schema, known source names, exact business allowlist, hash-bound actual review',
            'general_name_recognition': False, 'source_files_modified': False}


def check_expansion(baseline, current, plan):
    """Check actual effective scale vs contextual targets, not every table x2.

    plan.main_tables maps filenames to target_effective_rows and optional
    adjustment_reason. An existing baseline defaults to ceil(2*effective_rows);
    a smaller target needs a concrete reason. New cases require an explicit target,
    never an invented historical baseline. Domain/coverage claims still need tests.
    """
    tables = plan.get('main_tables')
    if not isinstance(tables, dict) or not tables:
        raise ValueError('Select important main detail tables in the existing data-plan')
    if not isinstance(plan.get('generation_method'), str) or not plan['generation_method'].strip():
        raise ValueError('A reproducible domain generation method is required')
    results, failures = {}, []
    for name, policy in tables.items():
        actual = current.get('files', {}).get(name)
        old = (baseline or {}).get('files', {}).get(name)
        if actual is None:
            raise ValueError('Current actual exported main table missing: '+name)
        old_count = old.get('effective_rows') if old else None
        if old_count is not None and (not isinstance(old_count, int) or isinstance(old_count, bool) or old_count < 1):
            raise ValueError('Existing baseline must contain a positive actual effective_rows')
        starting_target = 2*old_count if old_count is not None else None
        target = policy.get('target_effective_rows', starting_target)
        if not isinstance(target, int) or isinstance(target, bool) or target < 1:
            raise ValueError('A positive contextual effective-row target is required: '+name)
        reason = policy.get('adjustment_reason', '')
        if starting_target is not None and target < starting_target and not str(reason).strip():
            raise ValueError('A below-x2 planning target needs business/performance reasons: '+name)
        if actual['effective_rows'] < target:
            failures.append(name+': effective rows below contextual target')
        missing = set(policy.get('required_events', []))-set(actual.get('events', {}))
        if missing:
            failures.append(name+': missing planned event coverage '+','.join(sorted(missing)))
        results[name] = {'baseline_effective_rows': old_count,
                         'planning_starting_target': starting_target, 'target_effective_rows': target,
                         'actual_effective_rows': actual['effective_rows'],
                         'actual_independent_objects': actual.get('independent_objects', {}),
                         'time_start': actual.get('time_start'), 'time_end': actual.get('time_end'),
                         'actual_events': actual.get('events', {}), 'adjustment_reason': reason}
    if current.get('data_status') != 'pass':
        failures.append('Current CSV audit/review is incomplete or failed')
    return {'schema_version': 1, 'expansion_status': 'fail' if failures else 'pass',
            'tables': results, 'failures': failures,
            'domain_validity_automatically_verified': False}
