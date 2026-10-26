"""placeholder"""
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
def write_local(res, tool, X, partial=False):
    d = HERE / "reports"; d.mkdir(exist_ok=True)
    (d / "local_report.json").write_text(json.dumps({"tool": tool, "results": res}, indent=1, default=str))
def dump(X):
    return X.contract
