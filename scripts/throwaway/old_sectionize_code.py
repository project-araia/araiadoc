# text = {}
# cleaned_headers = []
# if not grobid_service:
#     raw_text = raw_text.replace("<br>", "\n")
#     lines = raw_text.splitlines()

#     indexes = []  # store indexes for content underneath headings
#     raw_headers = []
#     buffer_parts = []  # stores bold text chunks for current heading
#     buffer_indexes = []  # stores line indexes for current heading

#     for idx, line in enumerate(lines):
#         if line.startswith("**"):  # consecutive bold
#             # Extract all bold chunks from the line
#             chunks = [clean_header(m) for m in BOLD_RE.findall(line)]
#             if chunks:
#                 buffer_parts.extend(chunks)
#                 buffer_indexes.append(idx)
#                 continue

#         # Allow blank lines inside a split heading without flushing
#         if line.strip() == "":
#             continue

#         # Non-blank, non-bold => flush heading
#         if buffer_parts:
#             merged_heading = clean_header(" ".join(buffer_parts))
#             if looks_like_heading(merged_heading):
#                 raw_headers.append("".join(buffer_parts))
#                 cleaned_headers.append(merged_heading)
#                 indexes.append(buffer_indexes.copy())
#             buffer_parts.clear()
#             buffer_indexes.clear()

#     # Flush any remaining heading at EOF
#     if buffer_parts:
#         merged_heading = clean_header(" ".join(buffer_parts))
#         if looks_like_heading(merged_heading):
#             raw_headers.append("".join(buffer_parts))
#             cleaned_headers.append(merged_heading)
#             indexes.append(buffer_indexes.copy())

# else:
#     text = raw_text
#     cleaned_headers = list(text.keys())

# # remove any headers and corresponding indexes before the first header called "ABSTRACT"
# headers_to_upper = [header.upper() for header in cleaned_headers]
# if not grobid_service:
#     if "ABSTRACT" in headers_to_upper:
#         abstract_index = headers_to_upper.index("ABSTRACT")
#         cleaned_headers = cleaned_headers[abstract_index:]
#         indexes = indexes[abstract_index:]

#     indexes.append([len(lines)])
#     index_pairs = [(i[-1], j[0]) for i, j in zip(indexes, indexes[1:])]
#     progress.log("Found " + str(len(cleaned_headers)) + " possible headers.")
#     for i, (start, end) in enumerate(index_pairs):
#         header = cleaned_headers[i]
#         raw_header = raw_headers[i]
#         new_header = clean_header(header)
#         section = lines[start:end]
#         new_section = [j for j in section if j not in [header, raw_header, "\n", "", [], "  "]]
#         combined_new_section = (
#             "".join(new_section).replace("  ", " ").replace("<br>", "\n").replace("<br><br>", "\n")
#         )
#         new_section = [unicodedata.normalize("NFD", i) for i in combined_new_section]
#         new_section = [html.unescape(i) for i in new_section]
#         text[new_header] = "".join(new_section)

# # remove DISCLAIMER and ACKNOWLEDGMENTS
# if "DISCLAIMER" in headers_to_upper:
#     del text["DISCLAIMER"]
# if "ACKNOWLEDGMENTS" in headers_to_upper:
#     del text["ACKNOWLEDGMENTS"]
# if "FUNDING" in headers_to_upper:
#     del text["FUNDING"]

# # remove REFERENCES or WORKS CITED, but save for later
# if "REFERENCES" in headers_to_upper:
#     references = copy.deepcopy(text["REFERENCES"])  # copy of value before deleting the source
#     del text["REFERENCES"]
# elif "WORKS CITED" in headers_to_upper:
#     references = copy.deepcopy(text["WORKS CITED"])
#     del text["WORKS CITED"]

# len_subsections = len("".join(list(text.values())))
# if not len(text) or len_subsections / len(raw_text) < 0.90:
#     text = {"text": " ".join(lines)}

# output_files.append(output_file)

# if not no_metadata:
#     try:
#         matching_metadata = [entry for entry in metadata if output_file.stem == entry["osti_id"]][0]
#         base_text_list = [text]
#         representation = ParsedDocumentSchema(
#             source=org,
#             title=matching_metadata["title"],
#             text=base_text_list,
#             abstract=matching_metadata.get("description", ""),
#             authors=matching_metadata["authors"],
#             publisher=matching_metadata.get("journal_name", ""),
#             date=matching_metadata["publication_date"],
#             unique_id=matching_metadata["osti_id"],
#             doi=matching_metadata.get("doi", ""),
#             references=references,
#         )
#         output_rep = representation.model_dump(mode="json")
#     except Exception as e:
#         progress.log("Failure while postprocessing " + str(output_file) + ": " + str(e))
#         fail_count += 1
#         continue
# else:
#     output_rep = text


# def looks_like_heading(text):
#     # Basic cleanup
#     t = clean_header(text)

#     # Basic rejects
#     if not t:
#         return False
#     if re.match(r"^(table|figure)\b", t, re.IGNORECASE):
#         return False
#     if len(t.split()) > 12 or len(t) > 100:
#         return False
#     if len(t) < 3:
#         return False
#     if re.match(r"^[^\w]", t):  # starts with non-alphanumeric
#         return False
#     if t.endswith("."):
#         return False
#     if re.fullmatch(r"[\d\s]+", t):
#         return False
#     # Reject things that look like "119:", "28:", "11:" etc.
#     if re.match(r"^\d+[:.\-]?$", t):
#         return False
#     # Reject short alphanumeric codes like "A12", "X-23"
#     if re.fullmatch(r"[A-Za-z]?\d+[A-Za-z]?", t):
#         return False
#     # Reject headings that are mostly digits/symbols (e.g., "12.3.4", "3-2", etc.)
#     if re.match(r"^[\d\W]+$", t):
#         return False

#     return True


# def clean_header(h):
#     # Remove HTML tags
#     h = re.sub(r"<br\s*/?>", " ", h, flags=re.IGNORECASE)
#     # Remove Markdown bold/italic markers
#     h = re.sub(r"\*+", "", h)
#     # Collapse whitespace
#     h = re.sub(r"\s+", " ", h)
#     return h.strip()
