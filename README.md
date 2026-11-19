<div align="center">

# FormatX

### The document workshop

Convert, merge, split, compress and preview your documents.
Everything runs on your own machine, so your files never leave it.

![Python](https://img.shields.io/badge/Python-3.12-659DBD?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.1-8D8741?style=for-the-badge&logo=flask&logoColor=white)
![LibreOffice](https://img.shields.io/badge/LibreOffice-Engine-BC986A?style=for-the-badge&logo=libreoffice&logoColor=white)
![Tesseract](https://img.shields.io/badge/Tesseract-OCR-DAAD86?style=for-the-badge)

</div>

---

## What you can do

| Tool | What it does |
|:--|:--|
| **Convert** | DOCX, XLSX, PPTX, HTML, TXT, JPG and PNG to PDF. DOCX to TXT. PDF to DOCX, XLSX, PNG or JPG |
| **PDF to Word with OCR** | Turn a PDF, even a scan, into an editable Word file |
| **PDF to Excel** | Pull ruled tables out of a PDF into a spreadsheet |
| **Merge** | Combine up to 12 PDFs, or up to 12 Word files, into one |
| **Split and Extract** | Keep only the pages you pick, for example `1, 3, 5-8` |
| **Edit PDF** | Reorder, repeat, remove or rotate pages and add a footer stamp |
| **Compress** | Shrink PDFs, or optimize DOCX, XLSX and PPTX without losing quality |
| **Images to PDF** | Combine JPG and PNG files into a single PDF |
| **Preview** | Look at any page as an image before you process the file |

---

## Quick start

Open a terminal (Command Prompt or PowerShell on Windows) and run:

```bash
cd path\to\FormatX
pip install -r requirements.txt
python -m flask --app formatx run --no-reload --port 8000
```

Then open **http://127.0.0.1:8000** in your browser and you are ready to go.

> **Tip:** Replace `path\to\FormatX` with the folder where you extracted the project.
> Using a virtual environment is a good idea. Run `python -m venv .venv` and activate it before the `pip install` step.

---

## Before you start

FormatX uses a few free programs in the background. Install these first and make sure they can be found on your `PATH`.

| Requirement | Used for |
|:--|:--|
| **Python 3.12** | Running the app |
| **JDK 17 or newer** (a full JDK, not just a JRE) | DOCX to TXT |
| **LibreOffice** (Writer, Calc and Impress) | Word, Excel and PowerPoint to PDF |
| **Tesseract 5** with English language data | OCR for scanned PDFs |
| **WeasyPrint platform libraries** | HTML and TXT to PDF |

If LibreOffice is not on your `PATH`, point FormatX to it. In PowerShell:

```powershell
$env:FORMATX_SOFFICE = "C:\Program Files\LibreOffice\program\soffice.exe"
```

> **Prefer Docker?** It is the easiest route on Windows and macOS because every engine is already included.
>
> ```bash
> docker build -t formatx .
> docker run --rm -p 127.0.0.1:8000:8000 formatx
> ```

---

## Configuration

Set these in your terminal before you start the app.

| Variable | Default | Meaning |
|:--|:--:|:--|
| `FORMATX_REQUEST_MIB` | `60` | Total upload size limit |
| `FORMATX_FILE_MIB` | `40` | Size limit for each file |
| `FORMATX_ENGINE_TIMEOUT` | `120` | Seconds before an engine is stopped |
| `FORMATX_SOFFICE` | `libreoffice` | Name or full path of the LibreOffice program |



## Project layout

```text
FormatX/
|-- formatx/
|   |-- __init__.py       Flask routes, limits and responses
|   |-- validation.py     File checks, passwords and page ranges
|   |-- processing.py     Conversion, merge, split, edit and compress
|   |-- worker.py         Isolated HTML and PDF layout engines
|   |-- templates/        Web page
|   `-- static/           Styles and scripts
|-- java/WordText.java    DOCX to TXT extractor
|-- tests/                API and browser tests
|-- requirements.txt
`-- Dockerfile
```

---

## Privacy

FormatX is made for personal use on your own computer.

* Files are processed in temporary folders that are removed afterwards.
* There is no account system and no document history.
* Nothing is sent to an external service.



---

<div align="center">

Made for people who just want their documents to work.

</div>