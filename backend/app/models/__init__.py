# app/models/__init__.py
import os, pkgutil, importlib

for _, module_name, _ in pkgutil.iter_modules([os.path.dirname(__file__)]):
    if not module_name.startswith("__"):
        importlib.import_module(f"{__name__}.{module_name}")
