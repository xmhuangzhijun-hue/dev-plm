# Development guide

Read README.md and STATUS.md first. Project facts live in projects/; private sources and credentials must stay outside public inputs. Keep secrets out of code, logs and screenshots.

Frontend source: src/ for offline views; backend/web/ for the private workbench. Do not hand-edit generated site/. Use explicit public data roots for public builds. Run relevant tests after changes.

Runtime logs and project documents are read-only views of explicitly authorized files. Do not broaden reader grants or source directories without authorization. Preserve existing user files and unrelated edits.
