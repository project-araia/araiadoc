# climpdfgetter

Download and convert climate pdfs from EPA and OSTI.

## Installation

```bash
git clone https://git-out.gss.anl.gov/araia/climpdfgetter.git
cd climpdfgetter
```

Then either:

**Recommended**: Use [Pixi](https://pixi.sh/latest/) to take advantage of the included, guaranteed-working environment:

```bash
curl -fsSL https://pixi.sh/install.sh | sh
pixi shell
```



```bash
git clone https://git-out.gss.anl.gov/araia/climpdfgetter.git
cd climpdfgetter; pip install -e .
```

## Basic Usage

### Downloading documents

#### EPA

```Usage: climpdf crawl-epa [OPTIONS] STOP_IDX START_IDX```

Specify the *stop index* and *start index* out of the search results. For instance, to download
the first hundred documents:

```climpdf crawl EPA 100 0```

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

```pixi shell -e dev```

## Additional information

``climpdf`` uses:

- [crawl4ai](https://crawl4ai.com/mkdocs/) as its primary webcrawler
library. Downloads are at "human speeds" to try avoiding being blocked
or rate-limited.

- [pdf2json](https://github.com/nesar/pdf2json/), via [nougat](https://github.com/facebookresearch/nougat),
as its document-conversion engine.
