**hib** is a small command-line tool for Windows that archives documents and
indexes them by tags. Every document you add becomes an *entry* made of:

- a **storage folder** with a random name (`a<yyyymmdd><8 hex>`) that holds a copy
  of the source file and, when it can be generated, its PDF;
- a **JSON metadata record** (item type, title, authors, date, tags, description,
  citekey, reference, local and remote paths);
- an **HTML card** you can open in a browser, with buttons to open the file, its
  folder or its PDF and to copy its citekey, reference or path.

Entries are found again by **citekey** (e.g. `Smith2026`) or by **reference**,
exact or partial: `hib o smith` opens the stored file, `hib cd smith` moves your
shell into its folder.

hib is written in Python 3, uses the standard library only (the optional Word to
PDF conversion excepted) and needs no installer.

!!!Entirely coded by Claude IA!!!
