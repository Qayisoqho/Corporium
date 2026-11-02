"""Per-definition vertical spacing, as a percentage of the displayed font size."""
import math

FIELDS = ('space_before', 'space_after')


def initialize(db, table):
    assert table in ('annotation_layers', 'writing_types')
    columns = {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}
    for field in (*FIELDS, *(('line_spacing',) if table == 'annotation_layers' else ())):
        if field not in columns:
            # NULL preserves the existing surface's default layout; zero is explicit.
            db.execute('ALTER TABLE ' + table + ' ADD COLUMN ' + field + ' REAL')


def values(body, previous=None, *, internal=False):
    previous = dict(previous or {})
    result = {}
    for field in (*FIELDS, *(('line_spacing',) if internal else ())):
        value = body.get(field, previous.get(field))
        if value is not None and (type(value) not in (int, float) or
                                  not math.isfinite(value) or not -300 <= value <= 300):
            if field == 'line_spacing':
                raise ValueError('内部行距须留空或填写 -300–300 的数字（%）')
            raise ValueError('行前、行后间距须留空或填写 -300–300 的数字（%）')
        result[field] = value
    return result
