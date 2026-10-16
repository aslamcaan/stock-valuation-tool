"""Excel functions pycel lacks, for offline verification of exported workbooks."""
from statistics import median as _median


def _flat(args):
    for a in args:
        if isinstance(a, (tuple, list)):
            yield from _flat(a)
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
            yield a


def median(*args):
    xs = list(_flat(args))
    return _median(xs) if xs else "#NUM!"
