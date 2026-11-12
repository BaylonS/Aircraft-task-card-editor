# Aircraft Task Card Editor

Double-click **Aircraft Task Card Editor** on the desktop, or run **Launch.cmd**.
Add one or more original PDFs, enter the tail number and description, preview,
choose an output folder, then create completed copies. Preview has Previous/Next
buttons to inspect every page of the selected PDF. Added header text is black.

Each PDF is validated on every page before it is saved. A failed PDF produces
no output; other files in the batch continue. Existing names receive numbered
suffixes. Originals and existing outputs are never overwritten. No whiteout or
redaction is used. Use blank originals rather than already completed copies.
Each entry has its own Text size (pt) box, defaulting to 10 points. Enter a size
from 7 to 36 points (decimals are allowed). Preview uses those exact sizes.
Text can wrap, but it is never automatically shrunk. If it will not fit the
header, choose a smaller size or shorten the entry; no output is saved for that PDF.

Header detection uses Tail Number: or TAIL: plus actual table borders on each
page, with coordinates independent of page size and rotation. Unknown layouts,
occupied cells, scanned documents without searchable text, locked PDFs and
modification-restricted PDFs are rejected with a page-specific explanation.
Images and annotations in target cells are also rejected. Always review output
before operational use. Editing signed documents invalidates their signatures.

## Download and share

Download this repository using **Code → Download ZIP**, then extract the ZIP before installing.
Share this project: https://github.com/BaylonS/Aircraft-task-card-editor

## Install on another Windows PC

1. Install Python 3.10 or newer from https://www.python.org/downloads/windows/
   with Tcl/Tk and pip included. Enable Python on PATH.
2. Copy this folder (excluding .venv) to a permanent location.
3. In PowerShell in that folder run:
   `powershell -ExecutionPolicy Bypass -File .\Install.ps1`
   This installs PyMuPDF into a local environment and creates a desktop shortcut.
4. Open the desktop shortcut. Keep the folder in place; the shortcut points to it.

Manual launch: `python -m pip install -r requirements.txt`, then `python editor.py`.
Tkinter comes with standard Windows Python. On Linux install your distribution's
python3-tk package; run editor.py normally. The shortcut installer is Windows-only.

Source: editor.py. Dependency: PyMuPDF 1.28.2. All processing runs locally.
PyMuPDF licensing: https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright
