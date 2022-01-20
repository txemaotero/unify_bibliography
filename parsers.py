

from collections import defaultdict
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
        with open(self.fname, 'r') as f:
            content = f.read()

        for entry in re.split(r'\@(?=\w+\{)', content):
            if not entry.strip():
                continue
            self.parse_entry(entry)

    def parse_entry(self, entry: str):
        match = re.match(r'(\w+)\s*\{([\S\s]+)\}', entry)
        if match is None:
            raise ValueError('Invalid bibtex entry: {}'.format(entry))

        entry_type, content = match.groups()
        if entry_type.lower() in ('control',):
            self.non_entry_lines.append('@' + entry)
            return
        key, fields = content.split('\n', 1)
        key = key.strip().replace(',', '')
        self.bib_entries[key] = BibEntry(entry_type, key, fields)

    def __repr__(self):
        return 'Bib file: {}'.format(self.fname)

    def __str__(self):
        final_str = ''.join(self.non_entry_lines)
        return final_str + ',\n\n'.join(str(entry) for entry in self.bib_entries.values())

    def __add__(self, other: "BibFile") -> "BibFile":
        new_bib = BibFile()
        new_bib.non_entry_lines = self.non_entry_lines + other.non_entry_lines
        new_bib.bib_entries = self.bib_entries.copy()
        for key, value in other.bib_entries.items():
            if key in new_bib.bib_entries:
                text = 'Warning: duplicate key {} adding {} and {}.'.format(
                    key, repr(new_bib), repr(other))
                if value == new_bib.bib_entries[key]:
                    print(text + 'The entries seem to be the same. Merging')
                    new_entry = value.merge(new_bib.bib_entries[key])
                    new_bib.bib_entries[new_entry.id_key] = new_entry
                else:
                    new_key = key + 'Copy'
                    index = 1
                    while new_key + str(index) in new_bib.bib_entries:
                        index += 1
                    new_key += str(index)
                    print(text + 'The entries seem to be different. Adding both with keys {} and {}'.format(key, new_key))
                    new_bib.bib_entries[new_key] = value
            else:
                new_bib.bib_entries[key] = value
        return new_bib

    def __radd__(self, other: Any) -> "BibFile":
        if not other:
            return self
        else:
            raise ValueError('Cannot add bib files to {}'.format(repr(other)))

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
        """
        duplicated_entries = self.find_duplicated_entries()
        merged_keys = defaultdict(list)
        for key1 in duplicated_entries:
            entry1 = self.bib_entries[key1]
            key2, entry2 = self.get_key_entry(entry1, key1)
            new_entry = entry1.merge(entry2)
            if key1 != new_entry.id_key:
                merged_keys[new_entry.id_key].append(key1)
            if key2 != new_entry.id_key:
                merged_keys[new_entry.id_key].append(key2)

            _ = self.bib_entries.pop(key1)
            _ = self.bib_entries.pop(key2)
            self.bib_entries[new_entry.id_key] = new_entry
        return dict(merged_keys)

    def get_key_entry(self, entry: "BibEntry", key: str) -> tuple[str, "BibEntry"]:
        for key2, value in self.bib_entries.items():
            if entry == value and key != key2:
                return key2, value
        raise ValueError('Entry not found in bib file')
    
    def write(self, fout: str):
        with open(fout, 'w') as f:
            f.write(str(self))


class BibEntry:
    def __init__(self, type: str, id_key: str, fields: str = None):
        self.type = type
        self.id_key = id_key
        self.fields: dict[str, str] = {}
        if fields is not None:
            self.parse_entry(fields)

    def parse_entry(self, fields: str):
        for entry_key, info in re.findall('\s*(\w+)\s*=\s*\{(.*)\}', fields):
            self.fields[entry_key.lower()] = info.strip()

    def __repr__(self):
        return '{} bibentry of {}'.format(self.type, self.fields)

    def __str__(self):
        final_str = f'@{self.type}{{{self.id_key},\n'
        for key, value in self.fields.items():
            final_str += f'\t{key} = {{{value}}},\n'
        final_str = final_str[:-2] + '\n}'
        return final_str

    def __eq__(self, other):
        cond = self.id_key == other.id_key
        for field in ('title', 'doi', 'isbn'):
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


if __name__ == '__main__':
    from glob import glob

    bibfiles = [BibFile(fname) for fname in glob('./example_files/*bib')]
    total_bib = sum(bibfiles)
    titles = [i.fields['title']
              for i in total_bib.bib_entries.values() if 'title' in i.fields]

    total_bib.write('not_merged.bib')
    print(total_bib.find_duplicated_entries())
    print(total_bib.merge_duplicated_entries())
    total_bib.write('merged.bib')
