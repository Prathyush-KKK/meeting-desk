"""The API's route groups, one module each. ``app/main.py`` mounts them.

Deliberately empty: the job modules import helpers from ``app.routes.common``, and the admin
routes import the jobs, so a package ``__init__`` that imported every router would make
``python -m app.jobs.queue`` (the worker) fail on a circular import.
"""
