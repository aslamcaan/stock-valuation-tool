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


def rsq(ys, xs):
    """R squared of the straight line through (x, y), as Excel's RSQ."""
    pairs = list(zip(_flat([xs]), _flat([ys])))
    if len(pairs) < 2:
        return "#DIV/0!"
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    return sxy * sxy / (sxx * syy) if sxx and syy else "#DIV/0!"
