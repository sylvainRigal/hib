"""Parse the configured PDF-converter command template. The template is split into argv tokens (double-quote aware), then
the placeholders {input}/{outdir}/{output} are substituted per token (or over the
whole string for the PowerShell path). Backslashes are literal (Windows paths).
"""


def tokenize_template(template):
    """Quote-aware split into raw argv tokens. Double-quotes group a token and are
    consumed; unquoted whitespace separates (runs collapse). '""' is a real empty
    token. Empty/all-whitespace -> []. An unterminated quote raises ValueError."""
    tokens = []
    cur = []
    in_quotes = False
    have_token = False
    for c in template:
        if c == '"':
            in_quotes = not in_quotes
            have_token = True
        elif (not in_quotes) and c in " \t\r\n":
            if have_token:
                tokens.append("".join(cur))
                cur = []
                have_token = False
        else:
            cur.append(c)
            have_token = True
    if in_quotes:
        raise ValueError("unterminated quote")
    if have_token:
        tokens.append("".join(cur))
    return tokens


def _subst(s, vin, voutdir, vout):
    # Sequential, no rescan: a value containing a placeholder is not re-expanded.
    return s.replace("{input}", vin).replace("{outdir}", voutdir).replace("{output}", vout)


def substitute_placeholders(tokens, vin, voutdir, vout):
    return [_subst(t, vin, voutdir, vout) for t in tokens]


def substitute_string(template, vin, voutdir, vout):
    return _subst(template, vin, voutdir, vout)
