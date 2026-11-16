"""HTML card generation. render_entry keeps the legacy card markup (verified by
diffing generated cards) except for the copy buttons on the Reference and
Citekey lines and the <script> block, which is now always emitted. Everything
else is byte-identical to the legacy cards, and old and new cards stay readable
(cardparse handles the old and the new Reference markup).
"""
import uri

STYLE_BLOCK = (
    "    body            { font-family: Segoe UI, sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; color: #222; }\n"
    "    h2              { border-bottom: 2px solid #0078d4; padding-bottom: 8px; color: #0078d4; }\n"
    "    .tag            { display: inline-block; background: #e3f0fb; color: #0078d4; border-radius: 4px; padding: 2px 10px; margin: 2px; font-size: 0.9em; }\n"
    "    .desc           { background: #f9f9f9; border-left: 3px solid #0078d4; padding: 10px 16px; margin: 16px 0; font-style: italic; color: #444; }\n"
    "    .btn-group      { display: flex; gap: 12px; margin-top: 20px; flex-wrap: wrap; }\n"
    "    .btn-remote     { display: flex; gap: 12px; margin-top: 20px; flex-wrap: wrap; }\n"
    "    .remote-section { margin-top: 32px; padding-top: 16px; border-top: 1px solid #ddd; }\n"
    "    .delete-section { margin-top: 32px; padding-top: 16px; border-top: 1px solid #ffcccc; }\n"
    "    .open-btn       { display: inline-block; padding: 10px 22px; background: #0078d4; color: #fff; text-decoration: none; border-radius: 6px; font-size: 1em; }\n"
    "    .open-btn:hover      { background: #005a9e; }\n"
    "    .remote-btn     { display: inline-block; padding: 10px 22px; background: #6c757d; color: #fff; text-decoration: none; border-radius: 6px; font-size: 1em; }\n"
    "    .remote-btn:hover    { background: #495057; }\n"
    "    .folder-btn     { display: inline-block; padding: 10px 22px; background: #b5830a; color: #fff; text-decoration: none; border-radius: 6px; font-size: 1em; }\n"
    "    .folder-btn:hover    { background: #8c6508; }\n"
    "    .copy-btn       { display: inline-block; padding: 10px 22px; background: #28a745; color: #fff; text-decoration: none; border-radius: 6px; font-size: 1em; cursor: pointer; border: none; font-family: Segoe UI, sans-serif; }\n"
    "    .copy-btn:hover      { background: #1e7e34; }\n"
    "    .copy-btn.copied     { background: #155724; }\n"
    "    .copy-inline    { padding: 2px 10px; margin-left: 10px; background: #28a745; color: #fff; border: none; border-radius: 4px; font-size: 0.8em; cursor: pointer; font-family: Segoe UI, sans-serif; vertical-align: middle; }\n"
    "    .copy-inline:hover   { background: #1e7e34; }\n"
    "    .copy-inline.copied  { background: #155724; }\n"
    "    .pdf-btn        { display: inline-block; padding: 10px 22px; background: #e83e3e; color: #fff; text-decoration: none; border-radius: 6px; font-size: 1em; }\n"
    "    .pdf-btn:hover       { background: #b52a2a; }\n"
    "    .update-btn     { display: inline-block; padding: 10px 22px; background: #ffc107; color: #222; text-decoration: none; border-radius: 6px; font-size: 1em; }\n"
    "    .update-btn:hover    { background: #d39e00; }\n"
    "    .delete-btn     { display: inline-block; padding: 10px 22px; background: #dc3545; color: #fff; text-decoration: none; border-radius: 6px; font-size: 1em; cursor: pointer; border: none; font-family: Segoe UI, sans-serif; }\n"
    "    .delete-btn:hover    { background: #a71d2a; }\n"
    "    .path-block     { background: #f0f0f0; border-radius: 6px; padding: 10px 14px; margin-top: 8px; font-size: 0.85em; color: #444; word-break: break-all; font-family: Consolas, monospace; }\n"
    "    .path-label     { font-weight: bold; margin-top: 16px; display: block; }"
)

COPY_PATH_FN = (
    "    function copyPath(elementId, btn, label) {\n"
    "      var path = document.getElementById(elementId).innerText;\n"
    "      navigator.clipboard.writeText(path).then(function() {\n"
    "        btn.textContent = 'Copied!';\n"
    "        btn.classList.add('copied');\n"
    "        setTimeout(function() {\n"
    "          btn.innerHTML = '&#128203; ' + label;\n"
    "          btn.classList.remove('copied');\n"
    "        }, 2000);\n"
    "      });\n"
    "    }\n"
)

# Copy just the FOLDER of a displayed path: derive it in the browser from the
# path element's text (last '\' or '/' segment dropped), so no separate path
# value has to be embedded/escaped in the markup.
COPY_FOLDER_FN = (
    "    function copyFolderPath(elementId, btn, label) {\n"
    "      var path = document.getElementById(elementId).innerText;\n"
    "      var i = Math.max(path.lastIndexOf('\\\\'), path.lastIndexOf('/'));\n"
    "      var folder = i >= 0 ? path.substring(0, i) : path;\n"
    "      navigator.clipboard.writeText(folder).then(function() {\n"
    "        btn.textContent = 'Copied!';\n"
    "        btn.classList.add('copied');\n"
    "        setTimeout(function() {\n"
    "          btn.innerHTML = '&#128193; ' + label;\n"
    "          btn.classList.remove('copied');\n"
    "        }, 2000);\n"
    "      });\n"
    "    }\n"
)


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _folder_of(path):
    """The directory containing `path` -- the last '\\' or '/' segment dropped
    (matches the JS copyFolderPath helper, so the file:// link and the copy
    button point at the same folder)."""
    i = max(path.rfind("\\"), path.rfind("/"))
    return path[:i] if i >= 0 else path


def _author_list(authors):
    parts = []
    for last, first in authors:
        s = _esc(first)
        if first and last:
            s += " "
        s += _esc(last)
        parts.append(s)
    return ", ".join(parts)


def render_entry(entry):
    out = []
    a = out.append
    a('<!DOCTYPE html>\n<html lang="en">\n<head>\n')
    a('  <meta charset="UTF-8">\n')
    a('  <meta name="keywords" content="')
    a(", ".join(_esc(t) for t in entry.tags))
    a('">\n')
    a('  <meta name="description" content="')
    a(_esc(entry.description))
    a('">\n')
    a('  <meta name="author" content="')
    a(_author_list(entry.authors))
    a('">\n')
    a('  <title>')
    a(_esc(entry.title))
    a('</title>\n')
    a('  <style>\n')
    a(STYLE_BLOCK)
    a('\n  </style>\n</head>\n<body>\n')
    a('  <h2>')
    a(_esc(entry.title))
    a('</h2>\n\n')
    a('  <p><strong>Type:</strong> ')
    a(_esc(entry.item_type))
    a('</p>\n\n')
    # Reference and citekey each get a copy button. The value is wrapped in an
    # id'd span so copyPath can read it from the DOM -- the same trick the path
    # blocks use, and it keeps the value out of the onclick attribute (no JS
    # string escaping, no quote-in-reference hazard).
    a('  <p><strong>Reference:</strong> <span id="referenceValue">')
    a(_esc(entry.reference))
    a('</span>')
    a('<button class="copy-inline" onclick="copyPath(\'referenceValue\', this, \'Copy Reference\')">&#128203; Copy Reference</button>')
    a('</p>\n\n')
    a('  <p><strong>Citekey:</strong> <span id="citekeyValue">')
    a(_esc(entry.citekey))
    a('</span>')
    a('<button class="copy-inline" onclick="copyPath(\'citekeyValue\', this, \'Copy Citekey\')">&#128203; Copy Citekey</button>')
    a('</p>\n\n')
    a('  <p><strong>Version:</strong> ')
    a(_esc(entry.version))
    a('</p>\n\n')
    a('  <p><strong>Short Title:</strong> ')
    a(_esc(entry.short_title))
    a('</p>\n\n')
    a('  <p><strong>Authors:</strong> ')
    a(_author_list(entry.authors))
    a('</p>\n\n')
    a('  <p><strong>Tags:</strong><br>\n')
    for tag in entry.tags:
        a('    <span class="tag">')
        a(_esc(tag))
        a('</span>\n')
    a('  </p>\n\n')
    a('  <p><strong>Date:</strong> ')
    a(_esc(entry.date))
    a('</p>\n\n')
    a('  <div class="desc">')
    a(_esc(entry.description))
    a('</div>\n')

    # Gate on `is not None` (not truthiness) so an empty-string path still renders
    # its block (the legacy cards gate on the path being present, not non-empty).
    # add never passes "" (real path or None); only a hand-edited JSON reaches it.
    if entry.local_path is not None:
        a('\n  <span class="path-label">Local Path:</span>\n')
        a('  <div class="path-block" id="localPath">')
        a(_esc(entry.local_path))
        a('</div>\n\n')
        a('  <div class="btn-group">\n')
        a('    <a class="open-btn" href="')
        a(uri.open_href(entry.local_path))
        a('">&#128196; Local File</a>\n')
        a('    <a class="folder-btn" href="')
        a(uri.file_uri(_folder_of(entry.local_path)))
        a('/">&#128193; Open File Location</a>\n')
        a('    <button class="copy-btn" onclick="copyPath(\'localPath\', this, \'Copy Path\')">&#128203; Copy Path</button>\n')
        a('    <button class="copy-btn" onclick="copyFolderPath(\'localPath\', this, \'Copy Folder Path\')">&#128193; Copy Folder Path</button>\n')
        if entry.pdf_path is not None:
            a('    <a class="pdf-btn" href="')
            a(uri.file_uri(entry.pdf_path))
            a('">&#128196; Local PDF</a>\n')
        a('  </div>\n')

    if entry.remote_path is not None:
        a('\n  <div class="remote-section">\n')
        a('    <span class="path-label">Remote Path:</span>\n')
        a('    <div class="path-block" id="remotePath">')
        a(_esc(entry.remote_path))
        a('</div>\n')
        a('    <div class="btn-remote">\n')
        a('      <a class="remote-btn" href="')
        a(uri.open_href(entry.remote_path))
        a('">&#127760; Remote File</a>\n')
        a('      <a class="folder-btn" href="')
        a(uri.file_uri(_folder_of(entry.remote_path)))
        a('/">&#128193; Open Remote Location</a>\n')
        a('      <button class="copy-btn" onclick="copyPath(\'remotePath\', this, \'Copy Remote Path\')">&#128203; Copy Remote Path</button>\n')
        a('      <button class="copy-btn" onclick="copyFolderPath(\'remotePath\', this, \'Copy Remote Folder\')">&#128193; Copy Remote Folder</button>\n')
        a('    </div>\n')
        a('  </div>\n')

    # copyPath is always needed now (the citekey/reference buttons use it);
    # copyFolderPath only when a path block was rendered.
    a('\n  <script>\n')
    a(COPY_PATH_FN)
    if entry.local_path is not None or entry.remote_path is not None:
        a(COPY_FOLDER_FN)
    a('  </script>\n')

    a('</body>\n</html>\n')
    return "".join(out)
