"""Keep each part on one sheet: which label goes in which slot of a
multi-label sheet so that no part is split across two sheets, using as few
sheets as possible. A port of the web app's static/js/packing.js — same
algorithm, same results (tests/test_packing.py checks it against the web
app's output).

The labels of a part are records that share an element id, already in the
part order (ordering.order_records). A part with n labels on sheets of
`per` slots:
 - n <= per: one item of size n, which must not be split;
 - n > per: n // per whole sheets of its own, starting at the top of a
   fresh sheet, and a remainder of n % per labels (if not 0) that enters the
   packing as an item like any other. A part is never split more than that
   (it always uses ceil(n / per) sheets, the minimum).

Packing the items into the fewest sheets is bin packing (capacity per, item
size = labels). It is solved exactly:
 1. lower bounds (ceil(sum / per) and Martello-Toth's L2) and first/best-fit
    decreasing for an upper bound; when they meet, that is the optimum;
 2. otherwise "bin completion" over the multiset of item sizes (many parts
    share a size): a sheet holding the largest remaining item is filled with
    a maximal set of the remaining items, memoizing the states already shown
    to fit or not, cutting with the lower bounds above. The number of sheets
    is tried from the lower bound up, so the first that fits is the optimum.
 3. among solutions with that many sheets, the one closest to the part
    order: sheets are filled one after the other, each opened by the first
    part not yet placed and completed with the earliest parts that still
    leave the rest packable (lexicographically earliest assignment); within a
    sheet parts keep the part order.

Everything is time-boxed (`time_box`, default 1 s). If the box expires in
step 2 the first/best-fit packing is returned with proven=False; if it
expires in step 3 the sheets chosen so far are kept and the rest filled from
a packing already known to fit.
"""

import time
from dataclasses import dataclass
from functools import cmp_to_key

KEEP_OFF = "off"
KEEP_OPTIMIZE = "optimize"
KEEP_MODES = (KEEP_OFF, KEEP_OPTIMIZE)


def _ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def _parts_of(records) -> list[tuple[str, list[int]]]:
    """Parts in order of first appearance: [(element_id, [record index, ...])]."""
    by_id: dict[str, list[int]] = {}
    for i, r in enumerate(records):
        by_id.setdefault(r.element_id, []).append(i)
    return list(by_id.items())


def flow_summary(records, per: int) -> dict:
    """Sheets, empty slots and split parts when labels just run on in order
    ("off"). A part is split when it spans more sheets than it needs."""
    n = len(records)
    sheets = _ceil_div(n, per) if per > 0 else 0
    split = 0
    for _, idx in _parts_of(records):
        first, last = idx[0] // per, idx[-1] // per
        if last - first + 1 > _ceil_div(len(idx), per):
            split += 1
    return {"sheets": sheets, "blanks": sheets * per - n, "split_parts": split}


# ---- bounds and heuristics --------------------------------------------------

def _lower_bound(counts: list[int], C: int, total: int) -> int:
    """Martello-Toth's L2 (which includes ceil(sum / C))."""
    cnt = [0] * (C + 2)
    sm = [0] * (C + 2)
    for s in range(1, C + 1):
        cnt[s] = cnt[s - 1] + counts[s]
        sm[s] = sm[s - 1] + counts[s] * s
    best = _ceil_div(total, C)
    half = C // 2
    for alpha in range(half + 1):
        n1 = cnt[C] - cnt[C - alpha]
        n2 = cnt[C - alpha] - cnt[half]
        sum2 = sm[C - alpha] - sm[half]
        sum3 = sm[half] - sm[max(alpha - 1, 0)]
        lb = n1 + n2 + max(0, _ceil_div(sum3 - (n2 * C - sum2), C))
        best = max(best, lb)
    return best


def _decreasing(sizes: list[int], C: int) -> list[list[int]]:
    """First-fit and best-fit decreasing; the smaller packing (bins of item indexes)."""
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i], i))

    def run(best: bool) -> list[list[int]]:
        bins: list[list[int]] = []
        left: list[int] = []
        for i in order:
            at = -1
            for b in range(len(bins)):
                if left[b] < sizes[i]:
                    continue
                if not best:
                    at = b
                    break
                if at < 0 or left[b] < left[at]:
                    at = b
            if at < 0:
                bins.append([])
                left.append(C)
                at = len(bins) - 1
            bins[at].append(i)
            left[at] -= sizes[i]
        return bins

    ff, bf = run(False), run(True)
    return bf if len(bf) < len(ff) else ff


# ---- exact search -----------------------------------------------------------

class _Timeout(Exception):
    pass


class _Solver:
    """Bin completion over size counts: c[s] = items of size s still to place."""

    def __init__(self, C: int, deadline: float, now):
        self.C = C
        self.deadline = deadline
        self.now = now
        self.nodes = 0
        # key -> {"inf": most bins known too few, "feas": fewest known enough, "pat": ...}
        self.memo: dict[tuple, dict] = {}

    def tick(self) -> None:
        self.nodes += 1
        if (self.nodes & 63) == 0 and self.now() > self.deadline:
            raise _Timeout()

    def patterns(self, c: list[int], must: int) -> list[tuple[list[tuple[int, int]], int]]:
        """Every maximal way to fill one bin from `c` including an item of size
        `must`: [(pattern [(size, count)...], fill)], fullest sizes first."""
        C = self.C
        out = []
        sizes = [s for s in range(C, 0, -1) if c[s] > 0 or s == must]
        take = [0] * (C + 1)

        def go(k: int, room: int) -> None:
            self.tick()
            if k == len(sizes):
                for s in sizes:  # maximal: no remaining item still fits
                    if s <= room and c[s] - take[s] > 0:
                        return
                out.append(([(s, take[s]) for s in sizes if take[s] > 0], C - room))
                return
            s = sizes[k]
            most = min(c[s], room // s)
            least = 1 if s == must else 0
            for t in range(most, least - 1, -1):
                take[s] = t
                go(k + 1, room - t * s)
            take[s] = 0

        if c[must] > 0:
            go(0, C)
        return out

    def fits(self, c: list[int], total: int, bins: int) -> bool:
        """Can the items in `c` (sum `total`) be packed in `bins` bins?"""
        if total == 0:
            return True
        if bins <= 0 or total > bins * self.C:
            return False
        k = tuple(c)
        e = self.memo.get(k)
        if e:
            if "feas" in e and bins >= e["feas"]:
                return True
            if "inf" in e and bins <= e["inf"]:
                return False
        self.tick()
        if _lower_bound(c, self.C, total) > bins:
            self.note(k, bins, False)
            return False
        s = self.C
        while c[s] == 0:
            s -= 1
        # Stable sort, fullest first (JS Array.prototype.sort is stable too).
        for pat, fill in sorted(self.patterns(c, s), key=lambda p: -p[1]):
            for size, n in pat:
                c[size] -= n
            try:
                ok = self.fits(c, total - fill, bins - 1)
            finally:
                for size, n in pat:
                    c[size] += n
            if ok:
                self.note(k, bins, True, pat)
                return True
        self.note(k, bins, False)
        return False

    def note(self, k: tuple, bins: int, yes: bool, pat=None) -> None:
        m = self.memo.setdefault(k, {})
        if yes:
            if "feas" not in m or bins < m["feas"]:
                m["feas"] = bins
                m["pat"] = pat
        elif "inf" not in m or bins > m["inf"]:
            m["inf"] = bins

    def known(self, c: list[int], bins: int):
        """The bins (pattern lists) of a packing already found for `c`."""
        out = []
        cur = list(c)
        left = bins
        while True:
            if sum(cur[s] * s for s in range(1, self.C + 1)) == 0:
                return out
            e = self.memo.get(tuple(cur))
            if not e or "feas" not in e or e["feas"] > left:
                return None
            out.append(e["pat"])
            for size, n in e["pat"]:
                cur[size] -= n
            left = e["feas"] - 1


# ---- the packing ------------------------------------------------------------

def _cmp_items(a: list[int], b: list[int]) -> int:
    """Earliest-first: the list with the smaller index where they first differ
    wins; a longer list beats its own prefix (a fuller sheet)."""
    for x, y in zip(a, b):
        if x != y:
            return x - y
    return len(b) - len(a)


def pack_sizes(sizes: list[int], C: int, time_box: float = 1.0, now=time.monotonic) -> dict:
    """Packs item sizes (1..C each) into the fewest bins of capacity C.
    Returns {bins: [[item index...]...] (items ascending, bins by first item),
    proven, lower_bound, order_exact}."""
    m = len(sizes)
    deadline = now() + time_box
    if m == 0:
        return {"bins": [], "proven": True, "lower_bound": 0, "order_exact": True}
    counts = [0] * (C + 1)
    for s in sizes:
        counts[s] += 1
    total = sum(sizes)
    solver = _Solver(C, deadline, now)

    # 1. Bounds and a heuristic packing.
    lb = _lower_bound(counts, C, total)
    heuristic = _decreasing(sizes, C)
    need = len(heuristic)
    proven = lb >= need
    witness = None

    # 2. Exact: how few bins, from the lower bound up.
    if not proven:
        try:
            t = lb
            while t < need:
                if solver.fits(counts, total, t):
                    need = t
                    witness = solver.known(counts, t)
                    break
                lb = t + 1
                t += 1
            proven = True
        except _Timeout:
            pass

    def by_patterns(patterns):
        queues: dict[int, list[int]] = {}
        for i, s in enumerate(sizes):
            queues.setdefault(s, []).append(i)
        at: dict[int, int] = {}
        out = []
        for pat in patterns:
            b = []
            for s, n in pat:
                start = at.get(s, 0)
                b.extend(queues[s][start:start + n])
                at[s] = start + n
            out.append(sorted(b))
        return out

    fallback = by_patterns(witness) if witness else [sorted(b) for b in heuristic]
    if len(fallback) != need:
        fallback = [sorted(b) for b in heuristic]

    # 3. The exact packing closest to the part order.
    bins = None
    order_exact = False
    if proven:
        c = list(counts)
        placed = [False] * m
        queues: dict[int, list[int]] = {}
        for i, s in enumerate(sizes):
            queues.setdefault(s, []).append(i)
        chosen: list[list[int]] = []
        left = need
        first = 0
        left_total = total
        try:
            while left > 0 and left_total > 0:
                while placed[first]:
                    first += 1
                must = sizes[first]
                cands = []
                for pat, fill in solver.patterns(c, must):
                    items = sorted(i for s, n in pat for i in queues[s][:n])
                    cands.append((pat, fill, items))
                cands.sort(key=cmp_to_key(lambda a, b: _cmp_items(a[2], b[2])))
                pick = None
                for cand in cands:
                    pat, fill, _ = cand
                    for s, n in pat:
                        c[s] -= n
                    try:
                        ok = solver.fits(c, left_total - fill, left - 1)
                    finally:
                        for s, n in pat:
                            c[s] += n
                    if ok:
                        pick = cand
                        break
                if pick is None:
                    raise RuntimeError("packing: no sheet fits although the rest fits")
                pat, fill, items = pick
                for i in items:
                    placed[i] = True
                    queues[sizes[i]].remove(i)
                for s, n in pat:
                    c[s] -= n
                chosen.append(items)
                left_total -= fill
                left -= 1
            bins = chosen
            order_exact = True
        except _Timeout:
            rest = solver.known(c, left)
            if rest is not None:
                tail = []
                for pat in rest:
                    b = []
                    for s, n in pat:
                        for _ in range(n):
                            b.append(queues[s].pop(0))
                    tail.append(sorted(b))
                bins = chosen + tail
    if bins is None or len(bins) != need:
        bins = fallback
    bins = sorted((sorted(b) for b in bins), key=lambda b: b[0])
    return {"bins": bins, "proven": proven, "lower_bound": lb, "order_exact": order_exact}


@dataclass
class Packing:
    layout: list[int]  # record index per slot, -1 = empty; a multiple of per long
    sheets: int
    blanks: int
    proven: bool
    lower_bound: int
    order_exact: bool


def pack_records(records, per: int, time_box: float = 1.0, now=time.monotonic) -> Packing:
    """The slot sequence for `records` (grouped by part, in part order) on
    sheets of `per` slots with no part split that needn't be."""
    if not per > 1 or not records:
        layout = list(range(len(records)))
        sheets = _ceil_div(len(layout), per) if per > 0 else 0
        if per > 0:
            layout += [-1] * (sheets * per - len(layout))
        return Packing(layout, sheets, len(layout) - len(records), True, sheets, True)
    blocks = []  # (pos, sub, slots)
    items = []  # (part position, [record indexes])
    for pi, (_, idx) in enumerate(_parts_of(records)):
        n = len(idx)
        rest = idx
        if n > per:
            whole = n // per
            for s in range(whole):
                blocks.append((pi, 0, idx[s * per:(s + 1) * per]))
            rest = idx[whole * per:]
        if rest:
            items.append((pi, rest))
    packed = pack_sizes([len(it[1]) for it in items], per, time_box, now)
    for b in packed["bins"]:
        slots = [i for k in b for i in items[k][1]]
        blocks.append((items[b[0]][0], 1, slots))
    blocks.sort(key=lambda b: (b[0], b[1]))
    layout = []
    for _, _, slots in blocks:
        layout += slots
        layout += [-1] * (per - len(slots))
    return Packing(
        layout=layout,
        sheets=len(blocks),
        blanks=len(layout) - len(records),
        proven=packed["proven"],
        lower_bound=packed["lower_bound"] + sum(1 for b in blocks if b[1] == 0),
        order_exact=packed["order_exact"],
    )


def slots_of(records, layout: list[int]) -> list:
    """The records (None = an empty slot) a layout stands for."""
    return [None if i < 0 else records[i] for i in layout]


def split_parts(slots, per: int) -> int:
    """Parts on more sheets than they need, for a slot sequence."""
    span: dict[str, tuple[set, int]] = {}
    for i, r in enumerate(slots):
        if r is None:
            continue
        sheets, n = span.get(r.element_id, (set(), 0))
        sheets.add(i // per)
        span[r.element_id] = (sheets, n + 1)
    return sum(1 for sheets, n in span.values() if len(sheets) > _ceil_div(n, per))
