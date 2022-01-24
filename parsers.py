from collections import defaultdict
import difflib
from glob import glob
from heapq import merge
import os
import re
from typing import Any


class BibFile:
    def __init__(self, fname: str = None):
        self.bib_entries: dict[str, BibEntry] = {}
        self.non_entry_lines: list[str] = []
        self.fname = fname
        if self.fname is not None:
            self.parse_bib()

    def parse_bib(self):
        """
        Extract the bibliography entries from a bibtex file
        """
        with open(self.fname, "r") as f:
            content = f.read()

        for entry in re.split(r"\@(?=\w+\s*\{)", content):
            if not entry.strip():
                continue
            self.parse_entry(entry)

    def parse_entry(self, entry: str):
        match = re.match(r"(\w+)\s*\{([\S\s]+)\}", entry)
        if match is None:
            raise ValueError("Invalid bibtex entry: {}".format(entry))

        entry_type, content = match.groups()
        if entry_type.lower() in ("control",):
            self.non_entry_lines.append("@" + entry)
            return
        key, fields = content.split("\n", 1)
        key = key.strip().replace(",", "")
        self.bib_entries[key] = BibEntry(entry_type, key, fields)

    def __repr__(self):
        return "Bib file: {}".format(self.fname)

    def __str__(self):
        final_str = "".join(self.non_entry_lines)
        return final_str + ",\n\n".join(
            str(entry) for entry in self.bib_entries.values()
        )

    def __add__(self, other: "BibFile") -> "BibFile":
        new_bib = BibFile()
        new_bib.non_entry_lines = self.non_entry_lines + other.non_entry_lines
        new_bib.bib_entries = self.bib_entries.copy()
        for key, value in other.bib_entries.items():
            if key in new_bib.bib_entries:
                text = "Warning: duplicate key {} adding {} and {}.".format(
                    key, repr(new_bib), repr(other)
                )
                if value == new_bib.bib_entries[key]:
                    print(text + "The entries seem to be the same. Merging")
                    new_entry = value.merge(new_bib.bib_entries[key])
                    new_bib.bib_entries[new_entry.id_key] = new_entry
                else:
                    new_key = key + "Copy"
                    index = 1
                    while new_key + str(index) in new_bib.bib_entries:
                        index += 1
                    new_key += str(index)
                    print(
                        text
                        + "The entries seem to be different. Adding both with keys {} and {}. CHECK THIS ENTRY".format(
                            key, new_key
                        )
                    )
                    new_bib.bib_entries[new_key] = value
            else:
                new_bib.bib_entries[key] = value
        return new_bib

    def __radd__(self, other: Any) -> "BibFile":
        if not other:
            return self
        else:
            raise ValueError("Cannot add bib files to {}".format(repr(other)))

    def find_duplicated_entries(self) -> list[str]:
        """
        Find the duplicated entries in the bib file
        """
        duplicated_entries = []
        unique_entries = []
        for key, value in self.bib_entries.items():
            if value in unique_entries:
                duplicated_entries.append(key)
            else:
                unique_entries.append(value)
        return duplicated_entries

    def merge_duplicated_entries(self):
        """
        Merge the duplicated entries in the bib file

        Returns
        -------
        merged_keys: dict[str, str]
            The keys of the entries that have been merged and the key of the
            entry that has been merged into.
        """
        duplicated_entries = self.find_duplicated_entries()
        merged_keys = {}
        for key1 in duplicated_entries:
            entry1 = self.bib_entries[key1]
            key2, entry2 = self.get_key_entry(entry1, key1)
            new_entry = entry1.merge(entry2)
            if key1 != new_entry.id_key:
                merged_keys[key1] = new_entry.id_key
            if key2 != new_entry.id_key:
                merged_keys[key2] = new_entry.id_key

            _ = self.bib_entries.pop(key1)
            _ = self.bib_entries.pop(key2)
            self.bib_entries[new_entry.id_key] = new_entry
        return dict(merged_keys)

    def get_key_entry(self, entry: "BibEntry", key: str) -> tuple[str, "BibEntry"]:
        for key2, value in self.bib_entries.items():
            if entry == value and key != key2:
                return key2, value
        raise ValueError("Entry not found in bib file")

    def write(self, fout: str):
        """
        Writes the bibliography entries to a file
        """
        with open(fout, "w") as f:
            f.write(str(self))


class BibEntry:
    def __init__(self, type: str, id_key: str, fields: str = None):
        self.type = type
        self.id_key = id_key
        self.fields: dict[str, str] = {}
        if fields is not None:
            self.parse_entry(fields)

    def parse_entry(self, fields: str):
        for entry_key, info in re.findall('\s*(\w+)\s*=\s*[\{"](.*)[\}"]', fields):
            self.fields[entry_key.lower()] = info.strip()

    def __repr__(self):
        return "{} bibentry of {}".format(self.type, self.fields)

    def __str__(self):
        final_str = f"@{self.type}{{{self.id_key},\n"
        for key, value in self.fields.items():
            final_str += f"\t{key} = {{{value}}},\n"
        final_str = final_str[:-2] + "\n}"
        return final_str

    def __eq__(self, other):
        cond = self.id_key == other.id_key
        for field in ("title", "doi", "isbn"):
            if field in self.fields and field in other.fields:
                if self.fields[field] and other.fields[field]:
                    cond = cond or (self.fields[field] == other.fields[field])
        return cond

    def merge(self, other: "BibEntry") -> "BibEntry":
        """
        Merge two bib entries. If the entries are the same, the self one is kept.
        """
        id_key = self.id_key if len(self.id_key) < len(other.id_key) else other.id_key
        new_entry = BibEntry(self.type, id_key)
        new_entry.fields = {**other.fields, **self.fields}
        return new_entry


class LatexFile:
    def __init__(self, fname: str):
        self.fname = fname
        self.file_dir = os.path.dirname(fname)
        self.file_label = os.path.split(self.file_dir)[-1]
        with open(fname, "r") as f:
            self.original_content = f.read()
        self.modified_content = self.original_content
        self.title = self.get_title()

    def __str__(self) -> str:
        return self.modified_content

    def __repr__(self) -> str:
        return "LatexFile {}".format(self.fname)

    def _input_to_replace(self, match: re.Match):
        f_input = match.group(1)
        if not os.path.exists(f_input):
            f_input = os.path.join(self.file_dir, match.group(1))
            if not os.path.exists(f_input):
                raise FileNotFoundError(
                    f"File {f_input} not found to replace the input."
                )

        with open(f_input, "r") as f:
            content = f.read()
        content = content.replace(r"\endinput", "")
        return content

    def _label_ref_to_replace(self, match: re.Match):
        label = match.group(2)
        isolate_label = self.file_label + "_" + label.split(":")[-1]
        label = ":".join(label.split(":")[:-1] + [isolate_label])
        return r"\{0}{{{1}}}".format(match.group(1), label)

    def _path_to_replace(self, match: re.Match):
        """
        Devuelve el path a reemplazar
        """
        path = os.path.normpath(os.path.join(f"{self.file_dir}", match.group(2)))
        return r'\{0}{{"{1}"}}'.format(match.group(1), path)

    def write(self, fout: str = None):
        """
        Writes the modified content to a file

        If fout is None, "_mod" is added to the original file name
        """
        if fout is None:
            fout = self.fname.replace(".tex", "_mod.tex")
        with open(fout, "w") as f:
            f.write(str(self))

    def replace_cite_entries(self, merged_dict: dict[str, str]):
        for old, new in merged_dict.items():
            self.modified_content = re.sub(
                r"(\\(cite|citenum)\{[\S\s]*?)" + old,
                lambda m: m.group(1) + new,
                self.modified_content,
            )

    def diff(self):
        diff_lines = difflib.unified_diff(
            self.original_content.split("\n"), self.modified_content.split("\n")
        )
        for line in diff_lines:
            print(line)

    def get_title(self) -> str:
        match = re.search(r"\\title\s*\{([\S\s]*?)\}", self.modified_content)
        if match:
            return match.group(1).strip()
        else:
            return ""

    def fix_partial_paths(self):
        """
        Arregla las rutas parciales de los inputs
        """
        with_file_commands = (
            "includegraphics",
            "input",
            "include",
        )
        commands_for_re = r"\\({})".format(
            "|".join(i + ".*?" for i in with_file_commands)
        )
        self.modified_content = re.sub(
            commands_for_re + r'\{["\']*(.*?)["\']*\}',
            self._path_to_replace,
            self.modified_content,
        )

    def fix_labels_refs(self):
        """
        Arregla los labels y los refs
        """
        self.modified_content = re.sub(
            r"\\(label.*?|ref.*?)\{(.*?)\}",
            self._label_ref_to_replace,
            self.modified_content,
        )

    def substitute_inputs(self):
        """
        Substitute the inputs in the fixed_content.
        """
        while r"\input{" in self.modified_content:
            self.modified_content = re.sub(
                r'\\input\{["\']*(.*?)["\']*\}',
                self._input_to_replace,
                self.modified_content,
            )

    def adapt_for_thesis(self):
        """
        Filters the lines in the document to only the ones with content.

        Usefull to include article in a thesis. Removes the lines
        before the first section and those after the \end{document} line. Also
        removes the lines containting bibliography inputs (\\bibliography{...}
        or \\bibliographystyle). It also ensures that the acknoledge and
        conflict of interest are unnumbered sections.
        """
        start = False
        final_lines = []
        for line in self.modified_content.splitlines():
            if not start and r"\section{" in line:
                final_lines.append(line)
                start = True
            elif not start:
                continue
            else:
                if r"\end" in line and "document" in line:
                    break
                elif r"\bibliography" in line:
                    continue
                elif re.match(
                    r"^\s*\\section\{(acknowledge|conflicts? of interest?).*",
                    line.lower(),
                ):
                    final_lines.append(re.sub(r"\\section\*?", r"\\section*", line))
                else:
                    final_lines.append(line)

        self.modified_content = "\n".join(final_lines)
        
    def lines_for_results(self):
        """
        Returns the lines to add in the results.tex file.
        
        Check the chaptermark, it is the same as title.
        """
        return f"""
\chapter{{{self.title}}}
\label{{article:{self.file_label}}}
\chaptermark{{{self.title}}}
\input{{mainmatter/article_intro/{self.file_label}.tex}}
\includearticle{{mainmatter/article_pdf/{self.file_label}.pdf}}
\input{{mainmatter/article_source/{self.file_label}/manuscript_mod.tex}}
"""