#!/usr/bin/env python

'''
A library of parsing functions for fixlets.
'''

import json
import cgi
import re

'''
The regular expression for matching the format of an attribute in a directory
entry.
'''
ATTR_REGEX = '\w+: (.*)'

'''
The attributes present in a file's entry on the gather site, in order.
See the function 'parse_directory(text)'.
'''
FILE_ATTRS = ('url', 'name', 'modified', 'size', 'type', 'hash', 'hashinfo')

'''
Same as FILE_ATTRS but without 'hashinfo', which is missing on some sites.
'''
FILE_ATTRS0 = ('url', 'name', 'modified', 'size', 'type', 'hash')

'''
The regular expression for matching a multipart boundary in a fixfile.
'''
BOUND_REGEX = '.*boundary="(.*)"'

'''
Regular expression for a HTML omment.
'''
COMMENT_REGEX = '<!--.*?-->'

class FixletParsingException(Exception):
    pass

def parse_directory(text):
    '''
    Returns a 'directory': a list of file entries.

    A file entry is a dictionary representing a mapping from attributes in
    'FILE_ATTRS' to their actual values, parsed.
    '''
    directory = []
    lines = text.split('\n')
    lines = map(lambda x: x.strip(), lines)

    # go to first entry
    while not lines[2].startswith('URL: '):
        lines = lines[1:]
        if len(lines) < 3:
            return []

    # figure out whether the hashinfo attribute exists in our file entry
    try:
        content = map(lambda x: re.findall(ATTR_REGEX, x)[0], lines[2:9])
        target_attrs = FILE_ATTRS
    except Exception:
        assert lines[8] == ''
        target_attrs = FILE_ATTRS0

    while lines[2].startswith('URL: '):
        content = lines[2:2+len(target_attrs)]
        content = map(lambda x: re.findall(ATTR_REGEX, x)[0], content)
        attrs = dict(zip(target_attrs, content))
        directory.append(attrs)

        lines = lines[len(target_attrs)+3:]
        assert len(lines) >= 3

    return directory

def parse_directory_metadata(text):
    properties = [] # not dictionary because duplicates exist (e.g. relevance)
    lines = text.split('\n')
    lines = map(lambda x: x.strip(), lines)

    try:
        # find boundary of document
        while not lines[0].startswith('Content-Type:'):
            lines = lines[1:]

        # go to header
        header = re.findall(BOUND_REGEX, lines[0])[0]
        lines = lines[1:]
        while not (header in lines[0]):
            lines = lines[1:]

        # parse MIME-properties
        lines = lines[1:]
        while not lines[0] == '':
            separator = lines[0].find(":")
            key = lines[0][:separator]
            value = lines[0][separator+2:]
            properties.append((key, value))
            lines = lines[1:]
    except IndexError:
        return properties

    return properties

def flatten(lists):
    '''
    Flatten nested lists into one list.
    '''
    flattened = []
    for l in lists:
        if not type(l) == list: # cannot flatten
            flattened.append(l)
        else:
            flattened += flatten(l)
    return flattened

def extract_site_name(url):
    return re.findall('/([^/]*)$', url)[0]

def parse_fixlet(sections):
    '''
    Parse the smallest partition of a fixfile (contains ActionScript
    or the text description).

    TODO we currently only parse fixlets - add support for analyses, tasks, etc.
    '''
    text = None
    actions = []
    for section in sections:
        lines = section.split('\n')
        while not lines[0].startswith('Content-Type: '):
            lines = lines[1:]
            
        if (lines[0].split('Content-Type: ')[1].strip()
            == 'text/html; charset=us-ascii'):
            lines = lines[1:]
            section = '\n'.join(lines)
            text = re.sub(COMMENT_REGEX, '', section).strip()
        elif (lines[0].split('Content-Type: ')[1].strip()
              == 'application/x-Fixlet-Windows-Shell'):
            lines = lines[1:]
            section = '\n'.join(lines)
            actions.append(section.strip())
        elif (lines[0].split('Content-Type: ')[1].strip() in
              ('application/x-bigfix-analysis-template' or 
               'application/x-bigfix-itclient-property')):
            # TODO add analysis parsing later (look for x-fixlet-type)
            raise FixletParsingException("not fixlet, is analysis")
        elif (lines[0].split('Content-Type: ')[1].strip()
              == 'application/x-Task-Windows-Shell'):
            # TODO add task parsing later (look for x-fixlet-type)
            raise FixletParsingException("not fixlet, is task")
        else:
            raise FixletParsingException("couldn't recognize " + lines[0].split('Content-Type: ')[1].strip())
    return (text, actions)

class Relevance:
    def __init__(self, clauses, parent):
        self.clauses = clauses
        self.parent = parent
    def compressed_str_list(self):
        c = []
        if self.parent:
            c += self.parent.compressed_str_list()
        return c + self.clauses
    def _to_dict(self):
        info = {'clauses': self.clauses}
        if self.parent:
            info['parent'] = self.parent._to_dict()
        return info

class Fixlet:
    def __init__(self, fid, relevance, title, modified, text, actions):
        self.fid = fid
        self.relevance = relevance
        self.title = title
        self.modified = modified
        self.text = text
        self.actions = actions

    @property
    def contents(self):
        escape = lambda text: cgi.escape(text, True) if not (text is None) else None
        r = list(map(escape, self.relevance.compressed_str_list()))
        a = list(map(escape, self.actions))
        d = {'relevance': r, 'text': [escape(self.text)], 'actions': a}
        return json.dumps(d)

def rsplit_fixfile(text, parent=None):
    '''
    Recursively split a fixfile between boundaries, scraping relevance and
    actionscript as we go.
    '''
    relevance = []
    modified = 'unknown'
    lines = text.split('\n')
    while not lines[0].startswith('Content-Type: multipart/'):
        if lines[0].startswith('X-Relevant-When: '):
            relevance.append(lines[0].split('X-Relevant-When: ')[1].strip() + '\n')
        elif lines[0].startswith('X-Fixlet-ID: '):
            fid = int(lines[0].split('X-Fixlet-ID: ')[1].strip())
        elif lines[0].startswith('Subject: '):
            title = lines[0].split('Subject: ')[1].strip()
        elif lines[0].startswith('X-Fixlet-Modification-Time: '):
            modified = lines[0].split('X-Fixlet-Modification-Time: ')[1].strip()
        lines = lines[1:]
    splitter = re.findall(BOUND_REGEX, lines[0])[0]
    assert len(text.split('--{}--'.format(splitter))) == 2
    main_section = text.split('--{}--'.format(splitter))[0]
    subsections = main_section.split('--{}'.format(splitter))[1:] # remove header
    relevance = Relevance(relevance, parent)

    if lines[0].startswith('Content-Type: multipart/digest'):
        return filter(lambda x: x is not None, 
                      map(lambda x: rsplit_fixfile(x, relevance), subsections))
    elif lines[0].startswith('Content-Type: multipart/related'):
        try:
            text, actions = parse_fixlet(subsections)
            return Fixlet(fid, relevance, title, modified, text, actions)
        except FixletParsingException as e: # TODO handle properly
            try:
                print 'skipped parsing fixlet {} (id {})'.format(title, str(fid))
            except UnicodeEncodeError:
                print 'skipped parsing fixlet <UnicodeEncodeError> (id {})'.format(str(fid))
            return None
    else:
        assert False

def parse_fxffile(text):
    fixlets = flatten(filter(lambda x: x is not None, rsplit_fixfile(text)))
    return dict(map(lambda fxf: (fxf.fid, fxf), fixlets))

