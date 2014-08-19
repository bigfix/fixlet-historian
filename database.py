
import sqlite3
import traceback

'''
Name of the database to read site data from and to dump fixlet file data to.
'''
DBNAME = 'fxfdata.db'

'''
Default enumeration of revision types.
'''
REVISION_TYPES = {
    'new': 0,
    'changed': 1,
    'current': 2,
    'removed': 3,
    'missing': 4,
}

# TODO add non-NULL column constraints everywhere?
TABLE_SQL = [
'''CREATE TABLE RevisionTypes (
  id integer primary key,
  name text)''',

'''CREATE TABLE Sites (
  name text,
  url text)''',

# TODO add primary key(site, name) constraint?
'''CREATE TABLE FxfFiles (
  site integer references Sites(rowid),
  latest integer,
  disk_latest integer,
  name text)''',
  
'''CREATE TABLE FxfRevisions (
  fxf integer references FxfFiles(rowid),
  version integer,
  type integer references RevisionType(id),
  source_url text,
  primary key (fxf, version))''',

'''CREATE TABLE FxfContents (
  revision integer references FxfRevisions(rowid),
  text contents,
  primary key (revision))''',

'''CREATE TABLE Revisions (
  site integer references Sites(rowid),
  fixlet_id integer,
  version integer,
  type integer references RevisionType(id),
  published date,
  title text,
  source_file integer references FxfRevisions(rowid),
  primary key (site, fixlet_id, version))''',

'''CREATE TABLE RevisionContents (
  id integer references Revisions(rowid),
  contents text,
  primary key (id))''',
]

class CursorGenerator:
    '''
    Wraps a sqlite3 cursor generator into a kind of "stream".
    '''
    def __init__(self, cursor, sql):
        cursor.execute(sql)
        self.cursor = cursor
        self.next_row = None
    def _refresh(self):
        if self.next_row is None:
            self.next_row = self.cursor.fetchone()
        return self.next_row
    def has_next(self):
        return not self._refresh() is None
    def peek(self):
        return self._refresh()
    def pop(self):
        ret = self._refresh()
        self.next_row = None
        return ret

class ConnectionWrapper:
    '''
    Wraps a sqlite3 connection so as to reduce syntax for
    1) queries returning a single row of data
    2) queries returning many rows
    '''
    def __init__(self, connection):
        self.connection = connection
        self.cursor = None
    def query(self, sql, *args):
        self.cursor = self.connection.execute(sql, args)
        return self.cursor.fetchone()
    def _query_debug(self, sql, *args):
        print sql, args
        self.query(sql, *args)
    def query_generator(self, sql):
        self.cursor = self.connection.cursor()
        return CursorGenerator(self.cursor, sql)

def revtype(type_str):
    '''
    Given a string describing a revision type,
    this returns the constant associated with it in the db
    '''
    return REVISION_TYPES[type_str]

def atomic(func, dbname=DBNAME):
    '''
    Run the given function in a single database transaction.
    '''
    connection = sqlite3.connect(dbname)
    connection.text_factory = str # used to handle some unicode bugs
    db = ConnectionWrapper(connection)
    try:
        # ensures db closes
        with connection:
            # ensures transaction either aborts or commits
            return func(db)
    finally:
        connection.close()

def init(dbname=DBNAME):
    '''
    Initialize the database.
    '''
    def work(db):

        if db.query("""SELECT count(*) FROM sqlite_master WHERE type='table' AND name='RevisionTypes'""")[0] == 1 and db.query('SELECT count(*) FROM RevisionTypes')[0] == len(REVISION_TYPES):
            print 'note: database has already been initialized!',
            return

        for statement in TABLE_SQL:
            db.query(statement)
        for revtype in REVISION_TYPES:
            db.query('INSERT INTO RevisionTypes VALUES (?,?)', REVISION_TYPES[revtype], revtype)

    # note: work is not really atomic; we're using a shortcut here
    # to reduce how much code we need to write
    atomic(work, dbname)
