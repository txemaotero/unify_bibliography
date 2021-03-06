from collections import deque
import difflib
import os
import re
from typing import Any
from tqdm import tqdm
from functools import lru_cache

from pylatexenc.latex2text import LatexNodes2Text


ACCENT_CONVERTER = LatexNodes2Text()


@lru_cache(maxsize=1024)
def convert_to_lower_unicode(text: str) -> str:
    """Converts text to lower unicode and removes brackets."""
    unicode = ACCENT_CONVERTER.latex_to_text(text)
    return re.sub("[\ \{\}]", "", unicode.lower())


def simplify_field(text: str) -> str:
    text = ACCENT_CONVERTER.latex_to_text(text)
    # remove brackets and dots and lowercase
    text = re.sub("[\{\}\.]", "", text.lower())
    # replace double dash with single dash
    return text.replace("--", "-")


class BibFile:
    """
    Class to manage the bibliography entries in a .bib file

    Parameters
    ----------
    fname : str
        The name of the bib file

    Attributes
    ----------
    bib_entries : dict[str, BibEntry]
        The bibliography entries in the bib file
    non_entry_lines : list[str]
        The lines that are not bib entries (usually header lines)

    """

    def __init__(self, fname: str = None):
        self.bib_entries: dict[str, BibEntry] = {}
        self.non_entry_lines: list[str] = []
        self.fname = fname
        if self.fname is not None:
            self.parse_bib()

    def __getitem__(self, key: str) -> "BibEntry":
        return self.bib_entries[key]

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
        """
        Initialize a bib entry from its corresponding string in the bib file.
        """
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

    def find_duplicated_entries(self) -> list[list[str]]:
        """
        Find duplicated entries in the bib file checking the title, doi and issbn.
        """
        duplicated = []
        keys, values = list(self.bib_entries.keys()), list(self.bib_entries.values())
        remaining = deque(list(range(len(keys))))
        while remaining:
            index = remaining.popleft()
            aux = [index]
            for i in list(remaining):
                if values[index] == values[i]:
                    aux.append(i)
                    remaining.remove(i)
            if len(aux) > 1:
                duplicated.append(aux)
        return [[keys[i] for i in aux] for aux in duplicated]

    def merge_duplicated_entries(self):
        """
        Merge the duplicated entries in the bib file

        Returns
        -------
        merged_keys: dict[str, str]
            The keys of the entries that have been merged and the key of the
            entry that has been merged into. Useful to adapt the latex file
            with the replace_cite_entries method.
        """
        duplicated_entries = self.find_duplicated_entries()
        merged_keys = {}
        for group in duplicated_entries:
            new_entry = self.bib_entries[group[0]]
            for key in group[1:]:
                new_entry = new_entry.merge(self.bib_entries[key])
            for key in group:
                merged_keys[key] = new_entry.id_key
                _ = self.bib_entries.pop(key)
            self.bib_entries[new_entry.id_key] = new_entry
        return merged_keys

    def get_key_entry(self, entry: "BibEntry", key: str) -> tuple[str, "BibEntry"]:
        """
        Get the key and the entry of the bib items that is equal but not the
        same as the given.
        """
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
    """
    Class to represent a bibtex entry.

    Note: two BibEntry objects are equal if they have the same id_key, title,
    doi or issbn.

    Parameters
    ----------
    type : str
        The type of the entry (article, book, ...)
    id_key : str
        The bib key of the entry
    fields : str
        The text of the bib file with the information of the entry (authors,
        year, ...)

    Attributes
    ----------
    type : str
        The type of the entry (article, book, ...)
    id_key : str
        The bib key of the entry
    fields : dict[str, str]
        A dictionary with the fields of the entry.

    """

    def __init__(self, type: str, id_key: str, fields: str = None):
        self.type = type
        self.id_key = id_key
        self.fields: dict[str, str] = {}
        if fields is not None:
            self.parse_entry(fields)

    def __repr__(self):
        return "{} bibentry of {}".format(self.type, self.id_key)

    def __str__(self):
        final_str = f"@{self.type}{{{self.id_key},\n"
        for key, value in self.fields.items():
            # Put doble braces to keep uppercase
            final_str += f"\t{key} = {{{value}}},\n"
        final_str = final_str[:-2] + "\n}"
        return final_str

    def __eq__(self, other):
        cond = self.id_key == other.id_key
        for field in ("title", "doi", "isbn"):
            if field in self.fields and field in other.fields:
                if self.fields[field] and other.fields[field]:
                    field_1 = self.fields[field].lower()
                    field_2 = other.fields[field].lower()
                    # If field title, convert to unicode and lowercase and remomve spaces
                    if field == "title":
                        field_1 = convert_to_lower_unicode(field_1)
                        field_2 = convert_to_lower_unicode(field_2)

                    cond = cond or (field_1 == field_2)
        return cond

    def parse_entry(self, fields: str):
        """
        Parse the text containing the fields of the entry.
        """
        key_split = re.split("\s*(\w+)\s*=\s*", fields)
        entry_key = None
        for element in key_split:
            if not element.strip():
                continue
            if entry_key is None:
                entry_key = element.lower()
            else:
                field = element.strip()
                if field[-1] == ",":
                    field = field[:-1]
                field = re.sub("[\n\r\ ]+", " ", field)
                if re.fullmatch("\{.*\}", field) or re.fullmatch('".*"', field):
                    field = field[1:-1]
                if entry_key == "author":
                    # Separate Compound names and add dots JM -> J. M.
                    field = re.sub(
                        r"\s+([A-Z]+)(\s|$)",
                        lambda m: " "
                        + " ".join(i + "." for i in m.group(1))
                        + m.group(2),
                        field,
                    )
                self.fields[entry_key] = field
                entry_key = None

    def merge(self, other: "BibEntry") -> "BibEntry":
        """
        Merge two bib entries. If the entries are the same, the self one is
        retained.
        """
        id_key = self.id_key if len(self.id_key) < len(other.id_key) else other.id_key
        new_entry = BibEntry(self.type, id_key)
        new_entry.fields = {**other.fields, **self.fields}
        return new_entry

    def is_similar(self, other: "BibEntry", n_similarities: int=3) -> bool:
        """
        Check if other bib entry is similar.

        First, checks if they are equal. If not, it checks if the auhors are
        the same and other fields that are in both entries. If the number of
        similar fields is greater than n_similarities, the entries are
        considered similar.
        """
        if self == other:
            return True
        common_not_empty_fields = []
        for field in set(self.fields.keys()) & set(other.fields.keys()):
            if self.fields[field].strip() and other.fields[field].strip():
                common_not_empty_fields.append(field)
        similarities = 0
        for field in common_not_empty_fields:
            # Special quick checks that restrict the number of comparisons
            if field in ("volume", "number", "year"):
                if self.fields[field].strip() == other.fields[field].strip():
                    similarities += 1
                    continue
                return False
            # Authors are tricky H. William can be the same as Humayun William
            # We only check the last name
            field1 = simplify_field(self.fields[field])
            field2 = simplify_field(other.fields[field])
            if field1 == field2:
                similarities += 1
            elif field == "author":
                authors1 = field1.split(" and ")
                authors2 = field2.split(" and ")
                if len(authors1) != len(authors2):
                    return False
                similarities += all(
                    aut1.split()[0] == aut2.split()[0]
                    for aut1, aut2 in zip(authors1, authors2)
                )

        return similarities >= n_similarities


class LatexFile:
    """
    Class to modify a latex file.

    Parameters
    ----------
    fname : str
        The path to the latex file to modify.

    Attributes
    ----------
    fname : str
        The path to the latex file to modify.
    file_dir : str
        The full path of the directory containing the latex file.
    file_label : str
        The label of the latex file. This is taken from the name of the last
        subdir containing the file.
    original_content : str
        The original content of the latex file. This remains always the same.
    modified_content : str
        The resulting content of the latex file after applying the
        modifications.
    title : str
        The title defined in the latex file.
    packages : dict[str, str]
        The packages included in the latex file. The keys are the package names
        and the values are the lines used to include the package (with the
        additional options).

    """

    def __init__(self, fname: str):
        self.fname = fname
        self.file_dir = os.path.dirname(fname)
        self.file_label = os.path.split(self.file_dir)[-1]
        with open(fname, "r") as f:
            self.original_content = f.read()
        self.modified_content = self.original_content
        self.title = self.get_title()
        self.packages = self.get_packages()

    def __str__(self) -> str:
        return self.modified_content

    def __repr__(self) -> str:
        return "LatexFile {}".format(self.fname)

    def _input_to_replace(self, match: re.Match):
        f_input = match.group(1)
        if len(os.path.basename(f_input).split(".")) == 1:
            f_input += ".tex"
        if not os.path.exists(f_input):
            f_input = os.path.join(self.file_dir, f_input)
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
        Returns the path to substitute from a re.Match
        """
        path = os.path.normpath(os.path.join(f"{self.file_dir}", match.group(2)))
        return r'\{0}{{"{1}"}}'.format(match.group(1), path)

    def get_title(self) -> str:
        """
        Returns the title defined in the latex file.
        """
        match = re.search(r"\\title\s*\{([\S\s]*?)\}", self.modified_content)
        if match:
            return match.group(1).strip()
        else:
            return ""

    def get_packages(self) -> dict[str, str]:
        """
        Parses the included packages in the latex file.
        """
        packages = {}
        for match in re.finditer(
            r"\\usepackage\s*\[[\S\s]*?\]\s*\{([\S\s]*?)\}", self.modified_content
        ):
            packages[match.group(1)] = match.group(0)
        return packages

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
                r"(\\(cite|citenum|citeauthor)\{[\S\s]*?)" + old,
                lambda m: m.group(1) + new,
                self.modified_content,
            )

    def diff(self):
        """
        Prints the diff between the original and modified content.
        """
        diff_lines = difflib.unified_diff(
            self.original_content.split("\n"), self.modified_content.split("\n")
        )
        for line in diff_lines:
            print(line)

    def fix_partial_paths(self):
        """
        Fix partial paths defined in the latex file.
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
        Changes the labels and references to add the file label and avoid
        duplicates.
        """
        self.modified_content = re.sub(
            r"\\(label.*?|ref.*?|Cref.*?)\{(.*?)\}",
            self._label_ref_to_replace,
            self.modified_content,
        )

    def substitute_inputs(self):
        """
        Substitutes the inputs in the latex file with their content.
        """
        while r"\input{" in self.modified_content:
            self.modified_content = re.sub(
                r'\\input\{["\']*(.*?)["\']*\}',
                self._input_to_replace,
                self.modified_content,
            )

    def extract_sections(self, unnumbered_sections: bool = True):
        """
        Removes the lines that do not correspond to a section.

        Usefull to include article in a thesis. Removes the lines
        before the first section and those after the \end{document} line. Also
        removes the lines containting bibliography inputs (\\bibliography{...}
        or \\bibliographystyle). It also ensures that the acknowledge and
        conflict of interest are unnumbered sections if unnumbered_sections is
        True.

        Parameters
        ----------
        unnumbered_sections : bool, optional
            If True, ensures that the Acknowledge and Conflict of Interest
            sections are unnumbered. Defaults to True.
        """
        start = False
        final_lines = []
        sec_re = re.compile(r"\\section\*?\{([\s\S]*?)\}")
        for line in self.modified_content.splitlines():
            if not start and (match := sec_re.match(line)):
                if not match.group(1).strip():
                    continue
                final_lines.append(r"\section{" + match.group(1) + "}")
                start = True
            elif not start:
                continue
            else:
                if r"\end" in line and "document" in line:
                    break
                elif r"\bibliography" in line:
                    continue
                elif match := sec_re.match(line):
                    section = match.group(1).strip().lower()
                    if unnumbered_sections and re.match(
                        r"(acknowledg|conflicts? of interest?).*",
                        section,
                    ):
                        final_lines.append(r"\section*{" + match.group(1) + "}")
                    else:
                        final_lines.append(r"\section{" + match.group(1) + "}")
                else:
                    final_lines.append(line)

        self.modified_content = "\n".join(final_lines)

    def adapt_citations(self):
        """
        Changes cite formated like "...bla [1]. Bla..." to "...bla.[1] Bla...".

        Also ensures that the cites made after "Ref." are citenum.
        """
        self.modified_content = re.sub(
            r"(?<![\.\,])\ *([\ \n])(\\cite\{[^\}]*?\})([\.\,])(\s*)",
            lambda m: m.group(3) + m.group(2) + m.group(1) + m.group(4),
            self.modified_content,
        )
        self.modified_content = re.sub(
            r"([Rr]efs?\.)([\ \n])\\cite\{([^\}]*?)\}",
            lambda m: m.group(1) + m.group(2) + r"\citenum{" + m.group(3) + "}",
            self.modified_content,
        )

    def lines_for_results(self):
        """
        Returns the lines to add in the results.tex file in the thesis.

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


if __name__ == "__main__":
    """
    Very useful code to find possible duplicate entries that are not so obvious
    
    Call the scrpt like this:

        python3 parsers.py bibliography.bib similar_entries.txt
    """
    import sys

    bfil = BibFile(sys.argv[1])
    fout = sys.argv[2] if len(sys.argv) > 2 else 'similar_bib_entries.txt'

    entries = list(bfil.bib_entries.values())

    with open(fout, 'w') as f:
        progress = tqdm(total=len(entries)*(len(entries)-1)/2)
        for i, ent in tqdm(enumerate(entries)):
            first = True
            for j in range(i+1, len(entries)):
                progress.update()
                if ent.is_similar(entries[j]):
                    if first:
                        f.write("# This entry:\n")
                        f.write(str(ent) + '\n')
                        f.write("# Is similar to:\n\n")
                        first = False
                    f.write(str(entries[j]) + '\n\n')