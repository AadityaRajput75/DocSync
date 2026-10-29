import pytest

from docsync.documentation import validate_draft
from docsync.models import Draft


@pytest.mark.parametrize("source,name", [
    ("from sklearn.linear_model import LinearRegression\nregression = LinearRegression()\n",
     "LinearRegression"),
    ("from sklearn.linear_model import LinearRegression as LR\n", "LR"),
    ("from sklearn.linear_model import LinearRegression as LR\n", "sklearn.linear_model.LinearRegression"),
    ("import numpy as np\n", "np"),
    ("import numpy as np\n", "numpy"),
    ("import matplotlib.pyplot\n", "matplotlib.pyplot"),
    ("from .models import Model\n", "Model"),
    ("class Example:\n    def run(self): pass\n", "Example.run"),
])
def test_source_backed_symbols_accepted(tmp_path, source, name):
    snapshot = {"files": {"script.py": {"text": source}}}
    draft = Draft(content=f"# Guide\nUse `{name}()`.\n", summary="Overview",
                  symbols=[name], citations=[dict(path="script.py", start=1, end=1)])
    validate_draft({"root": str(tmp_path)}, snapshot,
                   {"path": "docs/overview.md", "old": "", "ranges": []}, draft)


@pytest.mark.parametrize("source,name", [
    ("import numpy as np\n", "np.Invented"),
    ("from sklearn.linear_model import LinearRegression\n", "InventedEstimator"),
    ("from sklearn.linear_model import *\n", "LinearRegression"),
    ("from sklearn.linear_model import LinearRegression as LR\n", "LinearRegression"),
])
def test_unsupported_symbols_still_rejected(tmp_path, source, name):
    snapshot = {"files": {"script.py": {"text": source}}}
    draft = Draft(content="# Guide\nOverview.\n", summary="Overview", symbols=[name],
                  citations=[dict(path="script.py", start=1, end=1)])
    with pytest.raises(ValueError, match="symbols not found in source"):
        validate_draft({"root": str(tmp_path)}, snapshot,
                       {"path": "docs/overview.md", "old": "", "ranges": []}, draft)


def test_unsupported_call_still_rejected(tmp_path):
    snapshot = {"files": {"script.py": {"text": "import numpy as np\n"}}}
    draft = Draft(content="# Guide\nUse `InventedEstimator()`.\n", summary="Overview",
                  citations=[dict(path="script.py", start=1, end=1)])
    with pytest.raises(ValueError, match="unverifiable function"):
        validate_draft({"root": str(tmp_path)}, snapshot,
                       {"path": "docs/overview.md", "old": "", "ranges": []}, draft)
