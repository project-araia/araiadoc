import re

# experiments dealing with markdown from marker library

lines = open("2519320/2519320.md").readlines()
indexes = []
headers = []
text = {}


def clean_header(header):
    for char in ["#", "##", "\n", "*", "**"]:
        header = header.replace(char, "")
    return header.lstrip()


# "Introduction: , Statement of Purpose: , Background:, etc."
subsection_pattern = re.compile(r"^(\w+(?: \w+){0,3}):")

for idx, line in enumerate(lines):
    if line.startswith("#"):
        indexes.append(idx)
        headers.append(line)

cached_headers = []

index_pairs = zip(indexes[:-1], indexes[1:])
for i, (start, end) in enumerate(index_pairs):
    header = headers[i]
    new_header = clean_header(header)
    if i == 0:
        potential_title = new_header
    section = lines[start:end]
    new_section = [i for i in section if i not in [header, "\n"]]

    cached_headers.append(new_header)

    already_entered_lines = []
    for i, line in enumerate(new_section):
        possible_new_header = re.search(subsection_pattern, line.lstrip())
        if possible_new_header:
            subsection_title = possible_new_header.group(1)
            line = line.split(subsection_title + ": ")[-1]
            text[subsection_title] = [line]
            already_entered_lines.append(i)
            cached_headers.append(subsection_title)

    new_section = [line for line in new_section if line not in already_entered_lines]
    if not len(new_section):
        new_section = cached_headers
    text[new_header] = new_section
    cached_headers = []

print("done")
