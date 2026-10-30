"""Rebuilt contracts, not the unavailable original 26-task experiment."""
import json
from pathlib import Path


def case(args, expected):
    return {"args": args, "expected": expected}


def raises(args, name="ValueError"):
    return {"args": args, "raises": name}


SPECS = [
    ("clamp", "Clamp a number to inclusive bounds; reject reversed bounds.",
     "def clamp(x, low, high):\n    return min(x, low)\n",
     "def clamp(x, low, high):\n    if low > high: raise ValueError('bounds')\n    return max(low, min(x, high))\n",
     [case([5, 0, 10], 5), case([-2, 0, 10], 0), case([20, 0, 10], 10), raises([1, 3, 2])]),
    ("unique", "Deduplicate a list while preserving first-seen order.",
     "def unique(values):\n    return sorted(set(values))\n",
     "def unique(values):\n    return list(dict.fromkeys(values))\n",
     [case([[3, 1, 3, 2]], [3, 1, 2]), case([[]], []), case([[0, 0, -1]], [0, -1])]),
    ("chunks", "Split a list into chunks, retaining the final partial chunk; reject size <= 0.",
     "def chunks(values, size):\n    return [values[i:i+size] for i in range(0,len(values)-size+1,size)]\n",
     "def chunks(values, size):\n    if size <= 0: raise ValueError('size')\n    return [values[i:i+size] for i in range(0,len(values),size)]\n",
     [case([[1,2,3,4,5],2], [[1,2],[3,4],[5]]), case([[],3], []), raises([[1],0])]),
    ("flatten", "Recursively flatten nested lists, keeping non-list values unchanged.",
     "def flatten(values):\n    return [x for group in values for x in group]\n",
     "def flatten(values):\n    out=[]\n    for x in values:\n        out.extend(flatten(x)) if isinstance(x,list) else out.append(x)\n    return out\n",
     [case([[1,[2,[3]],4]], [1,2,3,4]), case([[]], []), case([[[],0,'x']], [0,'x'])]),
    ("median", "Calculate median of unsorted numbers; reject empty input.",
     "def median(values):\n    return values[len(values)//2]\n",
     "def median(values):\n    if not values: raise ValueError('empty')\n    a=sorted(values); n=len(a)\n    return a[n//2] if n%2 else (a[n//2-1]+a[n//2])/2\n",
     [case([[8,2,4]],4), case([[4,1,3,2]],2.5), raises([[]])]),
    ("merge_intervals", "Sort and merge overlapping or touching inclusive intervals.",
     "def merge_intervals(items):\n    return items\n",
     "def merge_intervals(items):\n    out=[]\n    for a,b in sorted(items):\n        if out and a<=out[-1][1]: out[-1][1]=max(out[-1][1],b)\n        else: out.append([a,b])\n    return out\n",
     [case([[[5,7],[1,3],[3,6]]],[[1,7]]), case([[]],[]), case([[[1,2],[4,6]]],[[1,2],[4,6]])]),
    ("binary_search", "Return index of target in sorted unique numbers or -1 when absent.",
     "def binary_search(values, target):\n    return 0\n",
     "def binary_search(values, target):\n    lo,hi=0,len(values)-1\n    while lo<=hi:\n        mid=(lo+hi)//2\n        if values[mid]==target: return mid\n        if values[mid]<target: lo=mid+1\n        else: hi=mid-1\n    return -1\n",
     [case([[1,3,5,7],5],2), case([[1,3,5],4],-1), case([[],9],-1)]),
    ("two_sum", "Return [earlier_index,later_index] for first pair found by left-to-right scan; [] if absent.",
     "def two_sum(values, target):\n    return [0,1]\n",
     "def two_sum(values, target):\n    seen={}\n    for i,x in enumerate(values):\n        if target-x in seen: return [seen[target-x],i]\n        seen.setdefault(x,i)\n    return []\n",
     [case([[1,2,4,8],10],[1,3]), case([[3,3],6],[0,1]), case([[1],2],[])]),
    ("balanced", "Check balanced (), [] and {}; ignore all other characters.",
     "def balanced(text):\n    return text.count('(')==text.count(')')\n",
     "def balanced(text):\n    stack=[]; pairs={')':'(',']':'[','}':'{'}\n    for c in text:\n        if c in '([{': stack.append(c)\n        elif c in pairs:\n            if not stack or stack.pop()!=pairs[c]: return False\n    return not stack\n",
     [case(['([)]'],False), case(['a{b[c](d)}'],True), case([''],True), case([']'],False)]),
    ("word_counts", "Count case-insensitive ASCII words, ignoring punctuation.",
     "def word_counts(text):\n    return {w:1 for w in text.split()}\n",
     "import re\nfrom collections import Counter\ndef word_counts(text):\n    return dict(Counter(re.findall(r'[a-z]+',text.lower())))\n",
     [case(['Hello, HELLO world!'],{'hello':2,'world':1}), case([''],{}), case(['A-a'],{'a':2})]),
    ("slugify", "Lowercase ASCII alphanumeric slug; collapse other runs to '-' and strip ends.",
     "def slugify(text):\n    return text.lower().replace(' ','-')\n",
     "import re\ndef slugify(text):\n    return re.sub(r'[^a-z0-9]+','-',text.lower()).strip('-')\n",
     [case(['  Hello, WORLD!  '],'hello-world'), case(['A___B'],'a-b'), case(['!!!'],'')]),
    ("safe_divide", "Divide numbers; return None for a zero denominator.",
     "def safe_divide(a,b):\n    return a//b\n",
     "def safe_divide(a,b):\n    return None if b==0 else a/b\n",
     [case([5,2],2.5), case([3,0],None), case([-6,3],-2.0)]),
    ("parse_bool", "Accept true/yes/1 and false/no/0 case-insensitively after trimming; otherwise ValueError.",
     "def parse_bool(text):\n    return bool(text)\n",
     "def parse_bool(text):\n    t=text.strip().lower()\n    if t in ('true','yes','1'): return True\n    if t in ('false','no','0'): return False\n    raise ValueError('boolean')\n",
     [case(['false'],False), case([' YES '],True), raises(['maybe'])]),
    ("deep_get", "Read a dotted dict path; missing keys return default. Preserve false/0 values.",
     "def deep_get(data,path,default=None):\n    return data.get(path,default)\n",
     "def deep_get(data,path,default=None):\n    cur=data\n    for key in path.split('.'):\n        if not isinstance(cur,dict) or key not in cur: return default\n        cur=cur[key]\n    return cur\n",
     [case([{'a':{'b':0}},'a.b',9],0), case([{},'a.b',9],9), case([{'a':False},'a'],False)]),
    ("transpose", "Transpose a rectangular matrix; empty input returns []; ragged rows raise ValueError.",
     "def transpose(rows):\n    return rows\n",
     "def transpose(rows):\n    if not rows: return []\n    if any(len(r)!=len(rows[0]) for r in rows): raise ValueError('ragged')\n    return [list(c) for c in zip(*rows)]\n",
     [case([[[1,2,3],[4,5,6]]],[[1,4],[2,5],[3,6]]), case([[]],[]), raises([[[1],[2,3]]])]),
    ("rotate", "Rotate a list right by k positions; support negative k and empty lists.",
     "def rotate(values,k):\n    return values[k:]+values[:k]\n",
     "def rotate(values,k):\n    if not values: return []\n    k%=len(values)\n    return values[-k:]+values[:-k] if k else list(values)\n",
     [case([[1,2,3,4],1],[4,1,2,3]), case([[1,2,3],-1],[2,3,1]), case([[],4],[])]),
    ("moving_average", "Return means of all complete windows; reject nonpositive window size.",
     "def moving_average(values,k):\n    return [sum(values)/len(values)]\n",
     "def moving_average(values,k):\n    if k<=0: raise ValueError('window')\n    return [sum(values[i:i+k])/k for i in range(len(values)-k+1)]\n",
     [case([[1,2,3,4],2],[1.5,2.5,3.5]), case([[1],3],[]), raises([[1],0])]),
    ("json_lines", "Parse newline-delimited JSON, skip blank lines; malformed JSON raises ValueError.",
     "import json\ndef json_lines(text):\n    return json.loads(text)\n",
     "import json\ndef json_lines(text):\n    return [json.loads(line) for line in text.splitlines() if line.strip()]\n",
     [case(['{"x":1}\n\n{"x":2}\n'],[{'x':1},{'x':2}]), case([' \n'],[]), raises(['bad'])]),
    ("top_words", "Top k words by descending frequency, lexicographic tie break; nonpositive k returns [].",
     "def top_words(words,k):\n    return sorted(set(words))[:k]\n",
     "from collections import Counter\ndef top_words(words,k):\n    if k<=0: return []\n    c=Counter(words)\n    return sorted(c,key=lambda w:(-c[w],w))[:k]\n",
     [case([['z','a','z','b','a','z'],2],['z','a']), case([['b','a'],2],['a','b']), case([['x'],0],[])]),
    ("max_subarray", "Maximum nonempty contiguous subarray sum; empty input raises ValueError.",
     "def max_subarray(values):\n    return sum(values)\n",
     "def max_subarray(values):\n    if not values: raise ValueError('empty')\n    best=current=values[0]\n    for x in values[1:]:\n        current=max(x,current+x); best=max(best,current)\n    return best\n",
     [case([[-2,1,-3,4,-1,2,1,-5,4]],6), case([[-4,-2,-9]],-2), raises([[]])]),
    ("is_prime", "Return whether an integer is prime, including correct behavior for negatives/0/1/2.",
     "def is_prime(n):\n    return n%2==1\n",
     "def is_prime(n):\n    if n<2: return False\n    d=2\n    while d*d<=n:\n        if n%d==0: return False\n        d+=1\n    return True\n",
     [case([2],True), case([9],False), case([97],True), case([-3],False), case([1],False)]),
    ("factorial", "Factorial of nonnegative integer; reject negatives.",
     "def factorial(n):\n    return n\n",
     "def factorial(n):\n    if n<0: raise ValueError('negative')\n    out=1\n    for i in range(2,n+1): out*=i\n    return out\n",
     [case([0],1), case([5],120), raises([-1])]),
    ("fibonacci", "Zero-indexed Fibonacci F(0)=0, F(1)=1; reject negatives.",
     "def fibonacci(n):\n    return n\n",
     "def fibonacci(n):\n    if n<0: raise ValueError('negative')\n    a,b=0,1\n    for _ in range(n): a,b=b,a+b\n    return a\n",
     [case([7],13), case([0],0), case([1],1), raises([-1])]),
    ("days_between", "Signed day difference end-start for ISO date strings; invalid dates raise ValueError.",
     "def days_between(start,end):\n    return 0\n",
     "from datetime import date\ndef days_between(start,end):\n    return (date.fromisoformat(end)-date.fromisoformat(start)).days\n",
     [case(['2024-02-28','2024-03-01'],2), case(['2026-01-02','2026-01-01'],-1), raises(['bad','2024-01-01'])]),
    ("csv_total", "Sum numeric amount column in CSV with header; skip empty amounts.",
     "def csv_total(text):\n    return 0\n",
     "import csv\nimport io\ndef csv_total(text):\n    return sum(float(r['amount']) for r in csv.DictReader(io.StringIO(text)) if r['amount'].strip())\n",
     [case(['name,amount\na,1.5\nb,2.25\n'],3.75), case(['name,amount\na,\nb,-2\n'],-2.0), case(['name,amount\n'],0)]),
    ("parse_query", "Parse query string into key -> list of values; decode percent escapes/+ and preserve blanks.",
     "def parse_query(text):\n    return dict(x.split('=') for x in text.split('&'))\n",
     "from urllib.parse import parse_qs\ndef parse_query(text):\n    return parse_qs(text,keep_blank_values=True)\n",
     [case(['q=hello+world&q=a%2Bb&x='],{'q':['hello world','a+b'],'x':['']}), case([''],{}), case(['a=1'],{'a':['1']})]),
]


def build():
    root = Path(__file__).resolve().parent
    tasks = []
    allowed = ['list_files','read_file','write_file','edit_file','search_text','run_tests','run_command',
               'discover_tools','update_plan','remember','recall','git_status']
    for number, (function, description, broken, reference, cases) in enumerate(SPECS, 1):
        id = f"t{number:02d}_{function}"
        fixture = root / "fixtures" / id
        fixture.mkdir(parents=True, exist_ok=True)
        (fixture / "app.py").write_text(broken, encoding="utf-8")
        visible = cases[:2]
        test = ("import pytest\nfrom app import " + function + "\n\n"
                + "@pytest.mark.parametrize('args,expected'," + repr([(c['args'], c['expected']) for c in visible if 'expected' in c]) + ")\n"
                + f"def test_visible(args,expected):\n    assert {function}(*args)==expected\n")
        (fixture / "test_app.py").write_text(test, encoding="utf-8")
        (fixture / "CLAUDE.md").write_text("Implement only the requested behavior. Preserve test files. Run pytest after edits.\n", encoding="utf-8")
        tasks.append({"id": id, "fixture": f"fixtures/{id}", "prompt": f"Fix app.py function {function}. {description} "
                      "Read the existing code and tests, make the change, and run tests. Do not modify test files.",
                      "allowed_tools": allowed, "editable_paths": ["app.py"], "max_steps": 20, "timeout": 240,
                      "context_chars": 16000, "verifier": {"function": function, "cases": cases}, "reference": reference})
    (root / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Built {len(tasks)} reconstructed contracts; not the original benchmark.")


if __name__ == "__main__":
    build()
