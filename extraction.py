import inspect
import tokenize
from keyword import kwlist
from collections import defaultdict, OrderedDict, namedtuple
from io import BytesIO

FrameInfo = namedtuple('FrameInfo', ['filename', 'function', 'lineno',
                                      'source_map', 'name_map', 'assignments'])

def walk_tb(tb):
    """
    Follow the call stack, collecting source lines & variable values


    Params
    ---
    tb: traceback object

    Yields
    ---

    TODO
    """
    while tb:
        yield inspect_tb(tb)
        tb = tb.tb_next


def inspect_tb(tb):
    """


    # all the line nrs in all returned structures are true (absolute) nrs
    """
    frame = tb.tb_frame
    lineno = tb.tb_lineno
    finfo = inspect.getframeinfo(frame)
    filename, function = finfo.filename, finfo.function
    source, startline = get_source(frame)
    name_map = get_name_map(source, line_offset=startline-1)
    assignments = get_vars(name_map.keys(), frame.f_locals, frame.f_globals)
    source_lines = [(ln + startline, line) for ln, line in enumerate(source)]
    source_map = OrderedDict(source_lines)
    finfo =  FrameInfo(filename, function, lineno,
                       source_map, name_map, assignments)

    return finfo


def get_source(frame):
    """
    get source lines for this frame

    Params
    ---
    frame : frame object

    Returns
    ---
    lines : list of str

    startline : int
        line number of lines[0] in the original source file
    """
    if frame.f_code.co_name == '<module>':
        # TODO see if this is still necessary
        lines, _ = inspect.findsource(frame)
        startline = 1
    else:
        lines, startline = inspect.getsourcelines(frame)

    return lines, startline


def get_name_map(source, line_offset=0):
    """
    find all the names in the source, with line & column numbers
    """
    if isinstance(source, list):
        source = "".join(source)

    # tokenize insists on reading from a byte buffer/file, but we
    # already have our source as a very nice string, thank you.
    # So we pack it up again:
    source_bytes = BytesIO(source.encode('utf-8')).readline
    tokens = tokenize.tokenize(source_bytes)

    names_found = []
    dot_continuation = False
    was_name = False
    for ttype, token, (sline, scol), (eline, ecol), line in tokens:
        if ttype == tokenize.NAME and token not in kwlist:
            if not dot_continuation:
                names_found.append((token, (sline, scol), (eline, ecol)))
                was_dot_continuation = False
            else:
                # this name seems to be part of an attribute lookup,
                # which we want to treat as one long name.
                prev = names_found[-1]
                extended_name = prev[0] + "." + token
                old_eline, old_ecol = prev[2]
                end_line = max(old_eline, eline)
                end_col = max(old_ecol, ecol)
                names_found[-1] = (extended_name, prev[1], (end_line, end_col))
                dot_continuation = False
                was_dot_continuation = True
            was_name = True
        else:
            if token == '.' and was_name:
                dot_continuation = True
            elif token == '(' and was_name and not was_dot_continuation:
                # forget the name we just found because
                # it is a function or class definition
                names_found = names_found[:-1]
            was_name = False

    name2locs = defaultdict(list)
    for name, (sline, scol), (eline, ecol) in names_found:
        sline += line_offset
        eline += line_offset
        name2locs[name].append((sline, scol, eline, ecol))

    return name2locs


def get_vars(names, loc, glob):
    assignments = []
    for name in names:
        try:
            val = lookup(name, loc, glob)
        except UndefinedName:
            pass
        else:
            assignments.append((name, val))
    return OrderedDict(assignments)


class UndefinedName(KeyError):
    pass

class UnresolvedAttribute():
    def __init__(self, basename, attr_path, last_resolved, value):
        self.basename = basename
        self.attr_path = attr_path
        self.last_resolved = last_resolved
        self.last_resolvable_value = value

    @property
    def last_resolvable_name(self):
        return self.basename + '.'.join([''] + self.attr_path[:self.last_resolved])


def lookup(name, scopeA, scopeB):
    basename, *attr_path = name.split('.')
    if basename in scopeA:
        val = scopeA[basename]
    elif basename in scopeB:
        val = scopeB[basename]
    else:
        # not all names in the source file will be
        # defined (yet) when we get to see the frame
        raise UndefinedName(basename)

    for k, attr in enumerate(attr_path):
        try:
            val = getattr(val, attr)
        except AttributeError:
            return UnresolvedAttribute(basename, attr_path, k, val)

    return val