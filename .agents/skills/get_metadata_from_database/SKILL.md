---
name: get-metadata-from-database
description: Associate metadata from a PostgreSQL database with sectionized documents using the araiadoc tool.
---

# `get-metadata-from-database` Skill

Fetch metadata from a PostgreSQL database (S2ORC) and associate it with previously sectionized documents. Enriches document JSON files with title, authors, publisher, date, DOI, and references from the database.

## Usage

```bash
pixi run -e araiadoc araiadoc get-metadata-from-database SOURCE_DIR DBNAME USER PASSWORD HOST PORT TABLE_NAME
```

### Arguments

| Argument | Description |
|----------|-------------|
| `SOURCE_DIR` | Directory containing the sectionized JSON files to enrich |
| `DBNAME` | Name of the PostgreSQL database |
| `USER` | Database username |
| `PASSWORD` | Database password |
| `HOST` | Database hostname |
| `PORT` | Database port (typically 5432) |
| `TABLE_NAME` | Name of the table containing metadata |

## Examples

- Retrieve metadata from a local database:
  ```bash
  pixi run -e araiadoc araiadoc get-metadata-from-database data/documents mydb user secret localhost 5432 metadata
  ```

- Connect to a remote database with custom port:
  ```bash
  pixi run -e araiadoc araiadoc get-metadata-from-database data/sectionized_output s2orc_db admin password 5432 postgres paper_metadata
  ```

- Use a specific table name:
  ```bash
  pixi run -e araiadoc araiadoc get-metadata-from-database ./output s2orc user pass localhost 5432 s2orc_papers
  ```

## How It Works

1. Scans the source directory recursively for `.json` files
2. Extracts corpus ID from each filename (removes `_processed` suffix if present)
3. Queries the database table for matching `corpus_id`
4. Merges database metadata with existing sectionized content
5. Extracted `Abstract` and `References` sections are preserved separately
6. Writes enriched documents to a new output directory

## Database Schema Expected

The database table should contain:
- `corpus_id` - Primary key for matching documents
- `title` - Document title
- `author` - Author information
- `publisher` - Publishing venue
- `date` - Publication date
- `doi` - Digital Object Identifier

## Output

- **Location**: `{SOURCE_DIR}_with_metadata_db/`
- **Format**: JSON files following `ParsedDocumentSchema`
- **Structure**:
  ```json
  {
    "unique_id": "12345",
    "source": "s2orc",
    "title": "Document Title",
    "text": { "Introduction": "...", "Methods": "..." },
    "abstract": "Document abstract text",
    "authors": "Author names",
    "publisher": "Journal name",
    "date": 2020,
    "doi": "10.xxxx/xxxxx",
    "references": "References text"
  }
  ```

## Notes

- Uses parallel processing (all CPU cores) for database queries
- Skips files that don't have a matching database entry
- Progress is displayed with success/failure counts
- Database connection is closed after each file query
- The corpus ID is extracted from filenames - ensure naming convention matches
