# climpdfgetter

Download and convert climate pdfs from EPA and (in the future) other sources.

## Installation

```
$ git clone https://github.com/jlnav/climpdfgetter.git
$ cd climpdfgetter; pip install -e .
```

## Basic Usage

### Downloading documents

```Usage: climpdf crawl [OPTIONS] STOP_IDX START_IDX```

Specify a source out of ``EPA``, ``NOAA``, or ``OSTI`` to ``climpdf crawl``. Then specify
the *stop index* and *start index* out of the search results. For instance, to download
the first hundred documents:

```climpdf crawl 100 0```

### Counting results

```Usage: climpdf count [OPTIONS] SOURCE```

Specify a source to count the number of downloaded files.

For instance:

````bash
$ climpdf count EPA
2342
````

### Resuming downloads

```Usage: climpdf resume [OPTIONS] SOURCE NUM_DOCS```

Instruct ``climpdf`` to download ``NUM_DOCS`` additional documents from the
specified source.

For instance:

```climpdf resume EPA 1000```

### Document conversion

```Usage: climpdf convert [OPTIONS] SOURCE```

Instruct ``climpdf`` to try converting downloaded files in a given directory
to json. Subdirectories are also searched.

For instance:

```climpdf convert data/EPA_2024-12-18_15:09:27```

or:

```climpdf convert data```

## Development

Development and package management is done with [Pixi](https://pixi.sh/latest/).

Enter the development environment with:

``` pixi shell -e dev```

## Additional information

``climpdf`` uses:

- [crawl4ai](https://crawl4ai.com/mkdocs/) as its primary webcrawler
library. Downloads are at "human speeds" to try avoiding being blocked
or rate-limited.

- [docling](https://ds4sd.github.io/docling/) as its document conversion engine.
