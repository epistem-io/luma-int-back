# application/logic/luma/engine_compat.py
"""
Workaround for an import bug in luma_ge (luma-stack main since 2026-11-17,
including the commit pinned in requirements.txt).

luma_ge/predictor.py uses typing.Tuple and typing.Callable in annotations
but no longer imports them: its `from typing import ...` line lost both
names when the rfe_update branch was merged into main. On Python below 3.14
annotations are evaluated when a function is defined, so a plain
`import luma_ge.predictor` raises NameError.

load_engine_predictor() loads that module with the two names already in its
namespace. Import this module before anything imports luma_ge.predictor.

Remove this file once the engine imports the names itself and
requirements.txt pins a commit that has the fix.
"""
import importlib.util
import sys
import typing

_MODULE = 'luma_ge.predictor'


def load_engine_predictor():
    if _MODULE in sys.modules:
        return sys.modules[_MODULE]

    spec = importlib.util.find_spec(_MODULE)
    module = importlib.util.module_from_spec(spec)
    module.Tuple = typing.Tuple
    module.Callable = typing.Callable

    sys.modules[_MODULE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_MODULE, None)
        raise

    # what a normal import would also do
    setattr(sys.modules['luma_ge'], 'predictor', module)
    return module


load_engine_predictor()
