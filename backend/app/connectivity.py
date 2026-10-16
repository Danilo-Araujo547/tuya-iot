from sqlalchemy import select
from .db import Measurement


def offline_intervals(db, device, first, last):
    """Only shade confirmed offline periods; expired reports become unknown."""
    base = select(Measurement).where(Measurement.device_id == device.id,
                                     Measurement.property == 'online')
    previous = db.execute(base.where(Measurement.observed < first)
                          .order_by(Measurement.observed.desc(), Measurement.id.desc()).limit(1)).scalar_one_or_none()
    rows = db.execute(base.where(Measurement.observed >= first, Measurement.observed < last)
                      .order_by(Measurement.observed, Measurement.id)).scalars().all()
    if previous:
        rows.insert(0, previous)
    ttl = device.config.get('expected_interval', 300) * 3
    result = []
    for index, row in enumerate(rows):
        if row.value is not False:
            continue
        end = min(last, row.observed + ttl,
                  rows[index + 1].observed if index + 1 < len(rows) else last)
        start = max(first, row.observed)
        if end <= start:
            continue
        if result and result[-1]['end'] == start:
            result[-1]['end'] = end
        else:
            result.append({'start': start, 'end': end})
    return result
