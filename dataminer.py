#!/usr/bin/env python

import multiprocessing.pool
import requests
import os.path
import database
import fixlet_parser

'''
A text file where each line is a URL of a gather site to fetch from
(e.g. http://sync.bigfix.com/cgi-bin/bfgather/assetdiscovery)
'''
GATHER_SITES = 'gathers.txt'

'''
Maximum number of tries to fetch a URL.
'''
FETCH_TRIES = 5

'''
A cache of the output from finding all first fxf files.
'''
FIRST_FILE_CACHE = 'seed_cache.txt'

'''
Maximum number of threads to use while multiprocessing.
'''
PROCESS_POOL_SIZE = 32

### utilities

class MissingUrlException(Exception):
    '''Used by fetchurl() to indicate that it could not succeed.'''
    pass

def maybe(func):
    '''Wraps a one-argument function so that if it's called with None, it returns None instead.'''
    def f(x):
        if x == None:
            return None
        else:
            return func(x)
    return f

def profile(func):
    '''Wraps a function so that every time it's called, records and prints how long it takes'''
    from datetime import datetime; now = datetime.now
    def f(*args):
        a = now()
        ret = func(*args)
        b = now()
        print '{}{} finished w/ elapsed time: {}'.format(func, args, b-a)
        return ret
    return f

@profile
def fetchurl(url):
    '''
    Try several times to fetch a URL and return its requests (see python module)
    handle.

    Throws MissingUrlException if it fails.
    '''
    for i in range(FETCH_TRIES):
        try:
            r = requests.get(url)
            if r.status_code == 200:
                return r
        except Exception:
            pass
    raise MissingUrlException('cannot fetch ' + url)

def url_to_version(url):
    '''
    Given some url corresponding to a fixlet file, this returns the version
    associated with it.

    e.g.
    url_to_version("http://sync.bigfix.com/bfsites/aixpatches_382/52.fxf")
    becomes
    382
    '''
    rslash = url.rfind('/')
    return int(url[url.rfind('_', 0, rslash)+1:rslash])

def strip_version(url):
    '''
    Given some url corresponding to a fixlet file, this strips the version
    number from it.

    e.g.
    strip_version("http://sync.bigfix.com/bfsites/aixpatches_382/52.fxf")
    becomes
    "http://sync.bigfix.com/bfsites/aixpatches/52.fxf"
    '''
    slash = url.rfind('/')
    return url[:url[:slash].rfind('_')] + url[slash:]

def add_version(url, version):
    '''
    Given some url corresponding to a fixlet file, this adds a version
    number to it.

    e.g.
    add_version("http://sync.bigfix.com/bfsites/aixpatches/52.fxf", 382)
    becomes
    "http://sync.bigfix.com/bfsites/aixpatches_382/52.fxf"
    '''
    slash = url.rfind('/')
    return url[:slash] + '_' + str(version) + url[slash:]

### operations used for initialization re. sites

'''
These operations feed into each other to return data about a site.
They're used by both seed() and update() to figure out which sites to
look for, what specific metadata pertains to each site, what fixlet
files are served by each site, and importantly what are the first
occurrences of each file on that site.
'''

def get_gather_urls_list(gather_file=GATHER_SITES):
    '''
    Reads the file with all the sites to gather from and returns those urls
    in a list.
    '''
    with open(gather_file) as f:
        strip_trailing_newline = lambda line: line[:-1]
        return map(strip_trailing_newline, f.readlines())

def to_short_names(url_list):
    '''
    Turns urls of a list of sites into a list of
    "short" names of sites.

    e.g.
    to_short_names(["http://sync.bigfix.com/cgi-bin/bfgather/bessecurity"])
    becomes
    to_short_names(["bessecurity"])
    '''
    to_short_name = lambda url: url[url.rfind('/')+1:]
    return map(to_short_name, url_list)

def fetch_url_contents(url_list):
    '''
    Given a list of urls, fetch their contents.
    '''
    def fetch_url_content(url):
        try:
            handle = fetchurl(url)
            return handle.content
        except MissingUrlException:
            return None
    return map(fetch_url_content, url_list)

def parse_site_metadata(site_contents):

    '''
    Given a list of site directories contents, parse metadata in each
    directory and return a list of them (property-value pairs).

    e.g.
    parse_site_metadata(["http://sync.bigfix.com/cgi-bin/bfgather/bessecurity"])
    becomes
    [("MIME-Version", "1.0"),
     ("FullSiteURL", "http://sync.bigfix.com/bfsites/bessecurity_2045/__fullsite"),
     ("Version", "2045"),
     ...]
    '''

    parse = maybe(fixlet_parser.parse_directory_metadata)
    return map(parse, site_contents)

def to_site_directories(text_contents):
    '''
    Given a list of directory text contents as fetched from sync,
    returns a list of parsed directories.

    A directory is represented by list of dictionaries, each of which
    represents the contents of one entry in the directory which corresponds
    to one file served by that directory.

    e.g.
    Given
    [the contents at "http://sync.bigfix.com/cgi-bin/bfgather/bessecurity",
     the contents at "http://sync.bigfix.com/cgi-bin/bfgather/bessupport",
     ...]
    this returns
    [[{URL: http://sync.bigfix.com/bfsites/bessecurity_2045/1998%20Security%20Bulletins.fxf,
       NAME: 1998%20Security%20Bulletins.fxf,
       MODIFIED: Wed, 29 Jan 2014 07:00:37 +0000,
       SIZE: 5370,
       TYPE: FILE,
       HASH: 401a8d44a3bc1d641a0abec5356365608ab290c6,
       HASHINFO: sha256,869c877b6e613b478636e6a141b872f6f49cc266bb55a54f703dcbf1e6803099},
      {URL: http://sync.bigfix.com/bfsites/bessecurity_2045/1999%20Security%20Bulletins.fxf,
       ...}, ...]
     [{URL: http://sync.bigfix.com/bfsites/bessupport_1183/1Common%20Tasks.fxf,
       ...}, ...],
    ...]
    '''
    def parse_site_directory_contents(site_contents):
        '''
        Given a list of site directories contents,
        parse each entry in each directory and return a list of them.
        '''
        parse = maybe(fixlet_parser.parse_directory)
        return map(parse, site_contents)

    def filter_directory_contents(site_directories):
        '''
        Given a list of directories, filters out
        1) all files which are not digests ending in .fxf
        2) all files with NONCLIENT in the name
        '''
        @maybe
        def filter_directory(directory):
            def is_fixlet(entry):
                return entry['name'].endswith('.fxf')
            def is_not_nonclient(entry):
                return not ('NONCLIENT' in entry['name'])
            is_valid = lambda entry: is_fixlet(entry) and is_not_nonclient(entry)
            return filter(is_valid, directory)
        return map(filter_directory, site_directories)

    return filter_directory_contents(parse_site_directory_contents(text_contents))

def find_first_fxf(url):
    '''
    Given a url corresponding to a digest file at some version, finds
    the first version of that digest file on sync.

    Returns a tuple:
    (version number of digest file, url of digest file)

    e.g.
    "http://sync.bigfix.com/bfsites/aixpatches_382/52.fxf"
    becomes
    (255, "http://sync.bigfix.com/bfsites/aixpatches_255/52.fxf")
    '''
    version = url_to_version(url)
    attempting = 1
    url = url.replace('_{}/'.format(str(version)), '_1/')
    while attempting <= version:
        try:
            handle = fetchurl(url)
            return (attempting, url)
        except MissingUrlException:
            url = url.replace('_{}/'.format(str(attempting)), '_{}/'.format(str(attempting+1)))
            attempting += 1
    return None # TODO assert something wrong happened here?

def find_site_roots(directories):
    '''
    Given a list of directories, finds the first fixlet file
    of each entry of each directory.

    This returns a list of list of file entries (one list per site)

    e.g.
    [[(255, "http://sync.bigfix.com/bfsites/aixpatches_255/52.fxf"),
      (255, "http://sync.bigfix.com/bfsites/aixpatches_255/51.fxf"),
      ...]
     [(1, "another fixlet file"),
      ...],
    ...]

    N.B. This uses multiprocessing to speed up the process!
    This function takes a long time to complete so it is much better
    to read from the FIRST_FILE_CACHE file
    '''

    def process_entry(entry):
        return find_first_fxf(entry['url'])

    @maybe
    def process_directory(directory):
        global pool
        return pool.map(process_entry, directory)

    return map(process_directory, directories)

### database operations - seeding

def create_application_seed(short_names, urls, site_roots, metadata):
    '''
    Given an ordered list of site short names,
    an ordered list of urls,
    an ordered list of the first fixlet file version - url pairs,
    and an ordered list of metadata
    (all ordered so that the corresponding indices of each entry
     match up with the same site),

    this initializes the application seed (the database).
    '''
    database.init()
    for site in zip(short_names, urls, site_roots, metadata):
        name, url, fxffiles, meta = site
        if not fxffiles is None:
            database.atomic(lambda db: initialize_site(db, name, url, fxffiles, meta))

def initialize_site(db, site_name, site_url, fxffiles, metadata):
    '''
    Given a site's name, url,
    a list of (version, url) pairs returned by find_first_fxf,
    and site metadata, initializes in the database:

    1) The site entry in the database table Sites
    2) The fixlet files and their contents
    3) The fixlets corresponding to these files and their contents
    '''

    # initialize the site
    db.query("INSERT INTO Sites VALUES (?,?)", site_name, site_url)
    site_id = db.cursor.lastrowid

    for fxffile in fxffiles:
        version, fxf_url = fxffile

        # turns the url http://.../<fixlet-name>.fxf to <fixlet-name>
        fxf_name = fxf_url[fxf_url.rfind('/')+1:-4]

        # initialize the .fxf file
        db.query('INSERT INTO FxfFiles VALUES (?,?,?,?)', site_id, version, version, fxf_name)
        fxf_id = db.cursor.lastrowid
        db.query('INSERT INTO FxfRevisions VALUES (?,?,?,?)', fxf_id, version,
                 database.revtype('new'), fxf_url)
        fxf_revision_id = db.cursor.lastrowid

        # fetch contents of the file and initialize that
        fxf_handle = fetchurl(fxf_url)
        fxf_handle.encoding = 'windows-1252'
        fxf_text = fxf_handle.text
        db.query('INSERT INTO FxfContents VALUES (?,?)', fxf_revision_id, fxf_text)

        # parse the fixlets per file
        fixlets = fixlet_parser.parse_fxffile(fxf_text)

        for fixlet_id in fixlets:
            fixlet = fixlets[fixlet_id]

            # record the fixlet and its contents
            db.query('INSERT INTO Revisions VALUES (?,?,?,?,?,?,?)', site_id, fixlet_id, version,
                     database.revtype('new'), fixlet.modified, fixlet.title, fxf_revision_id)
            fixlet_revision_id = db.cursor.lastrowid
            db.query('INSERT INTO RevisionContents VALUES (?,?)',
                     fixlet_revision_id, fixlet.contents)

### database operations - updating

def update_application_database(metadata, added_fxffiles):
    '''
    Updates the application database given site metadata and a list of added
    .fxf files. Does this by doing the following:
    1) If any fxf files which were previously not tracked were added to some
    publication of a site, saves them to the database.
    2) For each fxf file this updates it to the latest version.
    '''
    save_added_fxffiles(added_fxffiles)

    for fxf in database.atomic(fxffile_list):
        try:
            to_version = int(database.atomic(lambda db: latest_published_version(db, fxf, metadata)))
            database.atomic(lambda db: update_fxffile(db, fxf, to_version))
            print 'Successfully updated file (id {}).'.format(fxf[0])
        except Exception as e:
            import traceback
            print 'Could not update file (id {})! Details:'.format(fxf[0])
            traceback.print_exc()
            # import pdb; pdb.set_trace()

def fxffile_list(db):
    '''
    Returns a list of all fixlet files tracked by the database.

    This is a list of tuples in the format
    (fxffile_id, site, fxffile_version, fxffile_disk_version, fxffile_source_url)
    '''
    files = []
    generator = db.query_generator('SELECT rowid, * FROM FxfFiles')
    while generator.has_next():
        files.append(generator.pop())
    return files

def latest_published_version(db, fxf, metadata):
    '''
    Given a fixlet file datum (a tuple returned by fxffile_list),
    returns the latest version of that file.
    '''
    _, site, _, _, _ = fxf
    site_name = db.query('SELECT Sites.name FROM Sites WHERE rowid=?', site)[0]
    for pair in metadata[site_name]:
        if pair[0] == 'Version':
            return pair[1] # TODO cast to int?
    raise Exception('TODO need to use more robust version-finding')

def disk_site_directories():
    '''
    Reads the database and returns a set of fixlet files tracked for
    each site in the db.
    '''

    def query_directories(db):
        generator = db.query_generator('''
    SELECT S.rowid as site_id, group_concat(F.url) as fixlet_urls
    FROM Sites S LEFT JOIN
    (
        SELECT FF.site as site, FR.source_url as url
        FROM FxfFiles FF, FxfRevisions FR
        WHERE FR.fxf = FF.rowid AND FR.version = FF.disk_latest
    ) F
    ON F.site = S.rowid
    GROUP BY S.rowid
    ORDER BY S.rowid''')
        directories = []
        while generator.has_next():
            row = generator.pop()
            if row[1] == None:
                continue

            urls = set(row[1].split(','))
            urls = map(strip_version, urls)
            directories.append(urls)
        return directories

    return database.atomic(query_directories)

def find_added_fxffiles(site_names, old_directories, new_directories):
    '''
    Given TODO fix the first parameter! see below
    and the currently-parsed directories from sync,
    determines for each site which .fxf files were newly added.

    Returns a dictionary mapping each site's short name
    to a list of .fxf file urls.
    '''

    # Creates a set of all tracked urls
    # TODO we should be able to replace the following code with just a
    # call to fxffile_list and then wrapping it in a set
    # the first parameter has unnecessary information
    old_urls = set()
    for directory in old_directories:
        old_urls = old_urls.union(directory)

    added = {}
    for site, directory in zip(site_names, new_directories):
        if directory is None:
            continue

        added[site] = []
        for entry in directory:
            url = strip_version(entry['url'])
            if not (url in old_urls):
                added[site].append(entry['url'])

    return added # dictionary : site -> list of fxffile urls

def save_added_fxffiles(added_fxffiles):
    '''
    Given a dictionary of .fxf files which were added to the current
    version of the site, initializes them in the database
    '''
    global pool

    # turn the dictionary into just a list and
    # find the site which corresponds to each url
    # TODO this code is pretty verbose for something relatively simple
    fxffiles_sites = {}
    added = [] # list of urls
    for site in added_fxffiles:
        added += added_fxffiles[site]
        for fxffile in added_fxffiles[site]:
            fxffiles_sites[fxffile] = site
    sites = map(lambda x: fxffiles_sites[x], added)

    # find the first occurence of each file.
    # N.B. this could take a long time, so multiprocessing is used to
    # speed it up!
    first_files = pool.map(find_first_fxf, added) # list of (version, url) pairs

    # initialize each file in the database
    insert = lambda newfile: database.atomic(lambda db: insert_new_fxffile(db, newfile))
    success = map(insert, zip(sites, first_files))
    return success

def insert_new_fxffile(db, newfile):
    '''
    Given a tuple of an .fxf file
    (site name, (first version present, url of that version)),
    this inserts a single new .fxf file into the database.
    '''
    # TODO this code is really similar to initialize_site - fix redundancies?
    site_name, version_info = newfile
    version, fxf_url = version_info
    
    # turns the url http://.../<fixlet-name>.fxf to <fixlet-name>
    fxf_name = fxf_url[fxf_url.rfind('/')+1:-4] # .../<fixlet-name>.fxf

    # insert .fxf data
    site_id = db.query('SELECT rowid FROM Sites WHERE name=?', site_name)[0]
    db.query('INSERT INTO FxfFiles VALUES (?,?,?,?)', site_id, version, version, fxf_name)
    fxf_id = db.cursor.lastrowid
    db.query('INSERT INTO FxfRevisions VALUES (?,?,?,?)',
             fxf_id, version, database.revtype('new'), fxf_url)
    fxf_revision_id = db.cursor.lastrowid

    # fetch and insert .fxf contents
    fxf_handle = fetchurl(fxf_url)
    fxf_handle.encoding = 'windows-1252'
    fxf_text = fxf_handle.text
    db.query('INSERT INTO FxfContents VALUES (?,?)', fxf_revision_id, fxf_text)

    # parse new fixlets
    fixlets = fixlet_parser.parse_fxffile(fxf_text)

    for fixlet_id in fixlets:
        fixlet = fixlets[fixlet_id]

        # insert the new fixlet into the database
        # TODO this is a source of a bug! we indicate that this fixlet is new
        # but in fact it could already be present in the db in some other file
        # this bug may be in different places too so we should determine how
        # to make sure the db is correct after running update
        db.query('INSERT INTO Revisions VALUES (?,?,?,?,?,?,?)',
                 site_id, fixlet_id, version, database.revtype('new'),
                 fixlet.modified, fixlet.title, fxf_revision_id)
        fixlet_revision_id = db.cursor.lastrowid
        db.query('INSERT INTO RevisionContents VALUES (?,?)',
                 fixlet_revision_id, fixlet.contents)

    return True

def update_fxffile(db, fxf_data, to_version):
    '''
    Given a tuple as returned by fxffile_list, updates some .fxf file
    to the latest version.
    '''
    fxffile_id, site_id, latest, disk_latest, fxf_name = fxf_data

    # TODO could probably use fxffile_id here instead of matching by name
    fxf_url, current_content = db.query('''
SELECT R.source_url, C.text
FROM FxfRevisions R, FxfContents C, FxfFiles F
WHERE C.revision=R.rowid AND R.fxf=F.rowid
  AND R.version=? AND F.name=? AND F.site=?''',
                                        disk_latest, fxf_name, site_id)
    current_version = int(latest)

    while current_version < to_version:
        # loop update version number and url
        current_version += 1
        fxf_url = add_version(strip_version(fxf_url), current_version)

        try:
            fxf_handle = fetchurl(fxf_url)
        except MissingUrlException:
            # we couldn't find it so it's probably missing
            db.query('UPDATE FxfFiles SET latest=? WHERE rowid=?',
                     current_version, fxffile_id)
            db.query('INSERT INTO FxfRevisions VALUES (?,?,?,?)',
                     fxffile_id, current_version,
                     database.revtype('missing'), fxf_url)
            continue

        fxf_handle.encoding = 'windows-1252'
        fxf_text = fxf_handle.text

        if fxf_text == current_content: # TODO sometimes a problem with unicode casting here
            # file didn't change - bump up the version
            db.query('UPDATE FxfFiles SET latest=? WHERE rowid=?',
                     current_version, fxffile_id)
        else:
            # save file to db
            db.query('UPDATE FxfFiles SET disk_latest=?, latest=? WHERE rowid=?',
                     current_version, current_version, fxffile_id)
            db.query('INSERT INTO FxfRevisions VALUES (?,?,?,?)',
                     fxffile_id, current_version,
                     database.revtype('changed'), fxf_url)
            fxf_revision_id = db.cursor.lastrowid
            db.query('INSERT INTO FxfContents VALUES (?,?)',
                     fxf_revision_id, fxf_text)

            # parse and check if each fixlet changed
            fixlets = fixlet_parser.parse_fxffile(fxf_text)

            for fixlet_id in fixlets:
                fixlet = fixlets[fixlet_id]

                last_fixlet = db.query('SELECT rowid, published, title FROM Revisions WHERE site=? AND fixlet_id=? ORDER BY version desc LIMIT 1',
                                       site_id, fixlet_id)

                if last_fixlet == None:
                    # new fixlet was added
                    # TODO could also be a source of bug where fixlet marked new
                    # more than once - see above
                    db.query('INSERT INTO Revisions VALUES (?,?,?,?,?,?,?)',
                             site_id, fixlet_id, current_version,
                             database.revtype('new'), fixlet.modified,
                             fixlet.title, fxf_revision_id)
                    fixlet_revision_id = db.cursor.lastrowid
                    db.query('INSERT INTO RevisionContents VALUES (?,?)',
                             fixlet_revision_id, fixlet.contents)
                    continue

                last_fixlet_rowid, last_fixlet_modified, last_fixlet_title = last_fixlet
                last_fixlet_contents = db.query('SELECT contents FROM RevisionContents WHERE id=?',
                                                last_fixlet_rowid)[0]

                if (last_fixlet_title == fixlet.title and
                    last_fixlet_modified == fixlet.modified and
                    last_fixlet_contents == fixlet.contents):
                    # fixlet did not change - ignore
                    continue

                # record new update
                db.query('INSERT INTO Revisions VALUES (?,?,?,?,?,?,?)',
                         site_id, fixlet_id,
                         current_version, database.revtype('changed'),
                         fixlet.modified, fixlet.title,
                         fxf_revision_id)
                fixlet_revision_id = db.cursor.lastrowid
                db.query('INSERT INTO RevisionContents VALUES (?,?)',
                         fixlet_revision_id, fixlet.contents)
            
### main functions directly called by update.py and seed.py

@profile
def seed():
    from datetime import datetime; now = datetime.now
    print 'start seed', str(now())
    urls = get_gather_urls_list()
    short_names = to_short_names(urls)
    site_contents = fetch_url_contents(urls)
    metadata = parse_site_metadata(site_contents)
    directories = to_site_directories(site_contents)

    if not os.path.exists(FIRST_FILE_CACHE):
        site_roots = find_site_roots(directories)
        with open(FIRST_FILE_CACHE, 'w') as f:
            f.write(repr(site_roots))
    else:
        with open(FIRST_FILE_CACHE) as f:
            site_roots = eval(f.read())

    create_application_seed(short_names, urls, site_roots, metadata)

@profile
def update():
    from datetime import datetime; now = datetime.now
    print 'start update', str(now())
    urls = get_gather_urls_list()
    short_names = to_short_names(urls)
    site_contents = fetch_url_contents(urls)
    metadata = parse_site_metadata(site_contents)

    # transform metadata into dictionary format
    # note that this destroys all properties with the same name
    # except one because only one "key" is allowed in a dictionary
    md = {}
    for site in zip(short_names, metadata):
        if site[0] is None:
            continue
        md[site[0]] = site[1]
    metadata = md

    old_directories = disk_site_directories()
    new_directories = to_site_directories(site_contents)
    sites_added_fxffiles = find_added_fxffiles(short_names,
                                               old_directories, new_directories)

    update_application_database(metadata, sites_added_fxffiles)
    print 'done', str(now())

# globally used for multiprocessing (for distributing find_first_fxf)
# initialized down here because of some possible bugs re: multiprocessing
pool = multiprocessing.pool.ThreadPool(processes=PROCESS_POOL_SIZE)
