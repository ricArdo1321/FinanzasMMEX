# GOOD: OFX export does not touch any .mmb. Idempotent file write atomic via tmp+rename.
# Mode --writer ofx in orchestrator excludes --writer sql.
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable


def export_ofx(rows: Iterable[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=out_path.parent, delete=False, suffix=".tmp"
    ) as tmp:
        tmp.write("OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n\n<OFX>\n")
        for r in rows:
            tmp.write(f"<STMTTRN><FITID>{r['fitid']}</FITID></STMTTRN>\n")
        tmp.write("</OFX>\n")
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, out_path)
