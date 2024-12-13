# climpdfgetter

Download climate pdfs from EPA and other sources.

## Installation

```
$ git clone https://github.com/jlnav/climpdfgetter.git
$ cd climpdfgetter; pip install -e .
```

## Basic Usage

```Usage: climpdf crawl [OPTIONS] {EPA|NOAA|OSTI} PAGES```

Specify a source out of ``EPA``, ``NOAA``, or ``OSTI`` to ``climpdf crawl``.
Optionally specify the number of *pages* of results.

For instance ``climpdf crawl EPA 3`` will download 150 pdfs since the base EPA
results page returns 50 results.
