The Fixlet Historian is an application that allows users to visualize
differences between any two versions of a fixlet, as well as inspect a site's
history. It leverages the presence of existing content on `sync.bigfix.com` to
produce this analysis.

Requirements
===

 * `python` (CPython version 2.7) an interpreter for Python

 * `requests` a Python library utility for serving HTTP requests

 * `python-Levenshtein` a Python library for computing textual differences

 * `node` (node.js) a JavaScript server library

 * `npm` a package manager for `node.js` applications

 * `bower` a package manager for JavaScript dependencies

Installation
===

 1. Download and extract the files to where you want your server to be.

 2. Install `requests`. You can follow the instructions
    [here](http://docs.python-requests.org/en/latest/user/install/#install) to
    install it.

 3. Get the application seed. There are several ways to do this:

    * You can download the seed database itself `fxfdata.db` (around 1.5 GB)
      from <here>.

    * You can download `seed_cache.txt` (around 150 KB) from <here> and then run
      `python seed.py`. The presence of this file greatly speeds up the creation
      of the seed database, and this should take around 10 minutes to run.

    * You can run `python seed.py` by itself. This will build both the cache
      file and the seed database. Be aware that this takes a very long time and
      should probably be run overnight.

 4. Run `python update.py` to bring the database to its current version. This
    will take a while to complete.

 5. Run `npm install`. This will install the backend server dependencies.

 6. Go into the subdirectory `frontend` and run `bower install`. This will
    install the frontend server dependencies.

 7. Download `python-Levenshtein`
    [here](http://www.lfd.uci.edu/~gohlke/pythonlibs/#python-levenshtein)
    and download and run the installer appropriate for your system.

Usage
===

To run the server after it's been built, simply run `node main.js`.

To keep the contents of the application database up-to-date run `python
update.py` regularly. It is advised to run this at least once a day.

Technical Details
===

## Architecture

There are three principle components of the application: the persistent
component, the server backend, and the server frontend.

### Persistence

Data persistence is provided by an [application database](#dbdesign) named
`fxfdata.db`. The scripts `seed.py` and `update.py` are simply call functions
from the main file `dataminer.py`. The file `database.py` provides utilities for
interacting with the database, while the file `fixlet_parser.py` provides
utilities for parsing fixlets.

The script `seed.py` initializes the database. It interacts with the auxiliary
files `gathers.txt` and `seed_cache.txt`. `gathers.txt` contains a list of site
URLs to target. `seed_cache.txt` is a serialized Python dictionary produced by
finding the first versions of each fixlet file per site, and can be used to
speed up building the seed database (as this is an expensive operation).

SQLite guarantees atomic updates per transaction. `update.py` provides atomicity
on the level of `fxf` files. If any error occurs as a `fxf` file is updated, the
entire transaction aborts and the script continues. As a result, the failure to
update any fixlet file will not affect the update of any other fixlet file, nor
will it affect the consistency of data previously recorded for that file.

### Server Backend

The server backend consists of the node server `main.js`, as well as a
dependency listing `package.json` and the differential analysis script
`diff_service.py`. `main.js` routes requests with the library `express.js`. When
required, the server retrieves data from the [database file](#dbdesign) and
passes it to the page rendering mechanism. Whenever the server needs to produce
a differential, it runs the command `diff_service.py`, capturing its output.

### Server Frontend

Requests serviced through `main.js` are rendered in `express.js` templates on
the frontend. Parameters to these templates are passed from `main.js` and give
most of the site content. Common public assets reside in the `assets/`
directory.

## <a name="dbdesign"></a>Database Design

This application uses a SQLite database to store data about sites, fixlet files,
and individual fixlets. The database contains seven tables:

 1. The table `RevisionTypes` enumerates metadata values for the state of fixlet
    files and revisions. It is the smallest table, static, and simply records
    constants from `database.py`.

 2. The table `Sites` contains the names of sites and urls. It is a static and
    relatively small table, proportional to the number of sites provided during
    the creation of the database seed.

 3. The table `FxfFiles` contains information about individual fixlet files
    tracked by the application. It contains each file's site and name, as well
    as its latest fetched version and its latest version on disk. These numbers
    are different because the application optimizes away storing redundant
    identical files (which were unchanged in some revision). This table is
    relatively small and relatively static.

 4. The table `FxfRevisions` contains information about each unique version of a
    fixlet file which introduced a change, the nature of the change, and the URL
    the change was fetched from.

 5. For each entry in `FxfRevisions` there exists another entry in `FxfContents`
    which contains the fixlet file content itself. These tables are both large,
    and since the `FxfContents` table is much larger than the `FxfRevisions`
    table the `FxfRevisions` table acts as a kind of index on the `FxfContents`
    table. These tables are dynamic, updated whenever a new revision is spotted
    on `sync.bigfix.com`.

 6. The table `Revisions` contains information about each revision of a
    particular fixlet. It contains information about the fixlet's site, ID,
    version, and title, as well as the nature of the revision, when it was
    published, and which revision of `fxf` it came from.

 7. For each entry in `Revisions` there exists an entry in
    `RevisionContents`. Like `FxfContents`, this table contains the actual
    fixlet contents as it was parsed from the `fxf` file, and the division of
    the tables reduces access time penalties resulting from large row
    sizes. These contents are retained in JSON form with HTML characters escaped
    for direct rendering on the frontend. Both these tables are large and
    dynamic as well.

## <a name="diff"></a>Differential Analysis

Fixlet differentials are produced with the aid of the `python-Levenshtein`
library.

The Levenshtein distance is the mathematical distance between two strings,
formally determined by the length of the minimal sequence of single-character
inserts, replacements, and removals needed to transform one string into
another. The `python-Levenshtein` library computes this sequence
deterministically.

While this sequence is precise in a mathematical sense and the library fast, for
many inputs the algorithm produces operations that are not well
human-readable. Human-readability is determined in large part by the contiguity
of inserted and removed substrings. The Python standard library also produces
text differentials (via the `difflib` library) but these differentials are
neither very precise nor oftentimes very readable at all. However, in certain
cases these differentials are much more readable than those produced by the
Levenshtein algorithm.

As a result, we use a simple heuristic to determine which algorithms to use: we
measure the number of transformation operations needed by each algorithm and
take the one which uses fewer. This maximizes contiguity and also tends to pick
the transformation which is more precise, falling back to Python's algorithm
when the Levenshtein algorithm fails.

Incomplete Elements
===

 * The server build and update processes are not particularly robust. Although
   we make use of SQLite's transaction system for recovery in the common case,
   crashes can sometimes trigger bugs that are difficult to recover from
   manually.

 * Parsing remains brittle. Changes to the format of published fixlets will
   likely break the current system.

 * The timestamps of publication on different revisions are inconsistent.

 * It's likely that there exist better string-matching algorithms for the
   computation of differentials. Further research there would be useful.

 * The differentials poorly handle the case in which a digest is added so that
   successive relevance "shifts down" from where it was inserted. It should be
   possible to produce these diffs more intelligently.

 * The mechanism for adding new `.fxf` files to track has not been tested.

 * Enhancements to the UI, especially to site history.

Planned Features
===

 * Only fixlets are currently parsed. Analyses, Tasks, and other objects which
   are parsable can (probably) be easily added.

 * Many fixlet metadata changes are not currently recorded. The differentials
   can be expanded to include changes to interesting metadata (e.g. fixlet
   titles)

 * A tool to export a fixlet from a given revision.

 * Formatting of content, including Relevance, ActionScript, and HTML.

Bugs
===

 * Fixlets which move from one `.fxf` file to another `.fxf` file are marked as
   having a "new" revision type even though they are not. They should be marked
   "changed" instead.

 * Certain fixlet IDs are duplicates, and fixlet files containing these
   duplicates fail to update properly.

 * HTML escaping may be inconsistent.

Support
===
Any issues or questions regarding this software should be filed via [GitHub issues](https://github.com/bigfix/fixlet-historian/issues).
