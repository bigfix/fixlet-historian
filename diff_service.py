#!/usr/bin/python

import difflib
import Levenshtein as levenshtein
import json
import sqlite3
import sys
import re

assert len(sys.argv) == 3

ALL_KEYS = ['relevance', 'text', 'actions']
DBNAME = 'fxfdata.db'

connection = sqlite3.connect(DBNAME)
old_id = sys.argv[1]
new_id = sys.argv[2]
statement = 'Select contents From RevisionContents Where id=?'

s1 = json.loads(connection.execute(statement, (old_id,)).fetchone()[0])
s2 = json.loads(connection.execute(statement, (new_id,)).fetchone()[0])

diff_formats = {
    'equal': lambda x, y: (x, y),
    'delete': lambda x, y: ('<span class="removed">'+x+'</span>', ''),
    'insert': lambda x, y: ('', '<span class="added">'+y+'</span>'),
    'replace': lambda x, y: ('<span class="removed">'+x+'</span>',
                             '<span class="added">'+y+'</span>')
}

def transform_output(old_string, new_string, opcodes):
    old_out, new_out = u'', u''
    for opcode in opcodes:
        transform_func = diff_formats[opcode[0]]
        old_substr = old_string[opcode[1]:opcode[2]]
        new_substr = new_string[opcode[3]:opcode[4]]
        output = transform_func(old_substr, new_substr)
        old_out += output[0]
        new_out += output[1]
    return old_out, new_out

def preprocess_input(old_string):
    return re.sub('&lt;!--.*?--&gt;', '', old_string.replace('\n', '<br />'))

def diff(old_string, new_string):
    '''
    Compute the diff in 'opcode format' between the old and new string.

    The opcode format is a list of 5-tuples indicating a sequence of edit
    operations required to get from the old string to the new string.

    Implementation note: we use both python's difflib and levenshtein diffing
    algorithms because this seems to give a useful compromise between readability
    and accuracy. On the one hand, the Levenshtein algorithm gives a "minimal"
    diff which is always accurate and symmetric but not always human-readable, and
    on the other hand the Longest-Common-Subsequence algorithm tends to produce
    human-readable continguous diffs but lacks accuracy and symmetry reliably.

    Taking the minimum *number* of opcodes for the sequence of transformations should
    usually yield the contiguous diffs given by LCS except when it produces
    very suboptimal diffs, in which case we use Levenshtein edits instead.
    '''
    difflib_codes = difflib.SequenceMatcher(None, before, after).get_opcodes()
    levenshtein_codes = levenshtein.opcodes(before, after)
    return min(difflib_codes, levenshtein_codes, key=lambda x: len(x))
    

old_file = {}
new_file = {}
for key in ALL_KEYS:
    # if key == 'text': # TODO remove after conversion on db-side?
    #     s1[key] = [s1[key]]
    #     s2[key] = [s2[key]]

    m = max(len(s1[key]), len(s2[key]))
    s1[key] += [u''] * (m-len(s1[key]))
    s2[key] += [u''] * (m-len(s2[key]))

    if len(s1[key]) != 0:
        old_file[key] = []
        new_file[key] = []
    for i in range(len(s1[key])):
        before, after = map(preprocess_input, (s1[key][i], s2[key][i]))
        opcodes = diff(before, after)
        o1, o2 = transform_output(before, after, opcodes)
        old_file[key].append(o1)
        new_file[key].append(o2)

print json.dumps([old_file, new_file])

#print 'TODO: future diff goes here'
#print 'was passed in parameters {} and {}'.format(sys.argv[1], sys.argv[2])

