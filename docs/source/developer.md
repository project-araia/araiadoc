# Developer & Agent Guides

This section outlines the codebase conventions, environment setups, and automation guides for both human developers and autonomous AI agents.

---

## Development Environment Setup

The repository is managed using **Pixi**. To enter a shell with all required developer packages (like `pre-commit`, `black`, `pytest`):

```bash
pixi shell -e dev
```

### Verification and Quality Controls

Before pushing code or finalizing pull requests, ensure that:

1. **Linting and Formatting** conform to the project standards.
2. **Tests** are successful. Run the full suite with:
   ```bash
   pixi run pytest
   ```

---

## Code Style Conventions

We maintain strict guidelines to keep the codebase clean, readable, and highly maintainable:

- **Library Assumptions:** Never assume a library is available unless it is specified in `pyproject.toml`. Check neighboring imports or dependency lists before importing external utilities.
- **Secure Handling:** Never log, print, or commit keys, database credentials, or third-party tokens.

---

## Documentation

Build the documentation locally in the `araiadoc/docs` directory with:

```bash
make clean; make html
```

Then open `araiadoc/docs/build/html/index.html` in your browser to view the documentation.

---

## Agent Skills & Automation

`araiadoc` supports autonomous AI agents. The `.agents/skills` directory contains specialized skill markdown files defining the workflows, CLI commands, and expectations.

The skills directory is organized as follows:

- **`crawl_epa` / `crawl_osti`:** Guidelines for crawling source documents asynchronously.
- **`section_dataset_s2orc`:** Instructions on parsing the `s2orc_v2` span annotations and creating matching paragraphs.
- **`araia_verify`:** Guide to executing `verify-sectionization` to check content integrity.
- **`araia_review`:** Review and audit topical relevance against generator queries.
- **`araia_compare` / `get_from_titanv`:** Overlap detection, dataset comparison, and legacy extraction.

**Rule:** Before generating CLI arguments, **always verify flag names against the corresponding skill file** in `.agents/skills/` to ensure full parity with the actual Click definitions in `src/araiadoc/crawl.py`.
