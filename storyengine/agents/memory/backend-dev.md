# Backend Dev Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- T8-001 render endpoint already exists (pipeline.py:849). Always grep before building — task descriptions can be stale.
- Adding routes to existing routers does NOT require touching main.py — only new router files need registration.
- T7-003: Pipeline executor bot methods must save result URLs to DB. run_thumbnail was missing thumbnail_url write — compare with run_render pattern.
- T7-004: When adding fields to VideoDetail, ALL THREE places must be updated: Pydantic model (models.py), SQL SELECT, and r.get() constructor mapping. Missing any one = field silently returns null.
